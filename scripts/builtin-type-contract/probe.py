#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 180
PUBLIC_TYPES = [
    {"name": "Int", "params": []},
    {"name": "Char", "params": []},
    {"name": "Float", "params": []},
    {"name": "Bool", "params": []},
    {"name": "String", "params": []},
    {"name": "Bytes", "params": []},
    {"name": "Unit", "params": []},
    {"name": "List", "params": ["T"]},
    {"name": "Map", "params": ["K", "V"]},
    {"name": "Set", "params": ["T"]},
]
PUBLIC_NAMES = {info["name"] for info in PUBLIC_TYPES}
DOCUMENTED_TYPES = [
    {**info, "use": "any"} for info in PUBLIC_TYPES
] + [{"name": "Never", "params": [], "use": "return"}]
PRELUDE_ADTS = {"Option", "Result", "ForeignError"}
HIDDEN_TYPES = {"Array", "Never"}
NEWLY_DOCUMENTED_FUNCTIONS = {
    "parse_int_radix",
    "char_is_letter",
    "char_is_digit",
    "char_is_alnum",
    "char_is_upper",
    "char_is_lower",
    "char_is_space",
}


def java_command(jar, *args):
    return ["java", "-Xss512m", "-Xmx2g", "-jar", str(jar), *args]


def checker_is_complete(jar):
    source = (
        "fn accepts(c: Char, b: Bytes, m: Map[String, Int], "
        "s: Set[Int]) -> Unit = ()\n"
        "fn rejects(x: Zzzzz) -> Unit = ()\n"
    )
    expected_hint = (
        "builtin types: Int, Char, Float, Bool, String, Bytes, Unit, "
        "List, Map, Set — or declare `type Zzzzz = ...`"
    )
    with tempfile.TemporaryDirectory(prefix="dawn-builtin-types-") as tmp:
        path = Path(tmp) / "probe.dawn"
        path.write_text(source)
        proc = subprocess.run(
            java_command(jar, "__check", str(path)),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TIMEOUT,
        )
    diagnostics = [line.split("\t") for line in proc.stdout.splitlines()
                   if line.startswith("D\t")]
    return (
        proc.returncode == 0
        and len(diagnostics) == 1
        and len(diagnostics[0]) >= 6
        and diagnostics[0][4] == "unknown type: Zzzzz"
        and diagnostics[0][5] == expected_hint
    )


def checker_diagnostics(jar, source, standalone=False):
    with tempfile.TemporaryDirectory(prefix="dawn-never-context-") as tmp:
        path = Path(tmp) / "probe.dawn"
        path.write_text(source)
        proc = subprocess.run(
            java_command(jar, "__check", str(path)),
            cwd=Path(tmp) if standalone else ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TIMEOUT,
        )
    if proc.returncode != 0:
        return None
    return [
        fields[4:6]
        for fields in (line.split("\t") for line in proc.stdout.splitlines())
        if len(fields) >= 6 and fields[0] == "D"
    ]


def checker_accepts(jar, source):
    return checker_diagnostics(jar, source) == []


def checker_rejects(jar, source, message, standalone=False):
    diagnostics = checker_diagnostics(jar, source, standalone=standalone)
    return diagnostics is not None and [fields[0] for fields in diagnostics] == [message]


def never_context_results(jar):
    storage_message = "`Never` can only be written as a function return type"
    return {
        "NEVER_TOP_RETURN": checker_accepts(
            jar, 'fn top_return_contract() -> Never = panic("top")\n'
        ),
        "NEVER_LOCAL_RETURN": checker_accepts(
            jar,
            "fn local_return_outer() -> Never = {\n"
            '  fn local_return_contract() -> Never = panic("local")\n'
            "  local_return_contract()\n"
            "}\n",
        ),
        "NEVER_TRAIT_RETURN": checker_accepts(
            jar,
            "trait TraitReturnContract[T] {\n"
            "  fn trait_return_contract(value: T) -> Never\n"
            "  fn trait_default_contract(value: T) -> Never = panic(\"default\")\n"
            "}\n",
        ),
        "NEVER_IMPL_RETURN": checker_accepts(
            jar,
            "trait ImplReturnTrait[T] {\n"
            "  fn impl_return_contract(value: T) -> Never\n"
            "}\n"
            "type ImplReturnToken = ImplReturnToken\n"
            "impl ImplReturnTrait[ImplReturnToken] {\n"
            "  fn impl_return_contract(value: ImplReturnToken) -> Never = panic(\"impl\")\n"
            "}\n",
        ),
        "NEVER_EFFECT_RETURN": checker_accepts(
            jar,
            "effect EffectReturnContract {\n"
            "  fn effect_return_contract() -> Never\n"
            "}\n",
        ),
        "NEVER_FUNCTION_TYPE_RETURN": checker_accepts(
            jar,
            "alias NeverFunctionContract = fn() -> Never\n"
            "alias NestedNeverFunctionContract = fn(Int) -> fn() -> Never\n"
            "type NeverFunctionHolder = { run: fn() -> Never }\n",
        ),
        "NEVER_STORAGE_PARAMETER": checker_rejects(
            jar,
            "fn storage_parameter_contract(value: Never) -> Unit = ()\n",
            storage_message,
        ),
        "NEVER_STORAGE_FIELD": checker_rejects(
            jar,
            "type StorageFieldContract = { value: Never }\n",
            storage_message,
        ),
        "NEVER_STORAGE_CONST": checker_rejects(
            jar,
            'const NEVER_STORAGE_CONST_CONTRACT: Never = panic("const")\n',
            storage_message,
        ),
        "NEVER_STORAGE_LET": checker_rejects(
            jar,
            "fn storage_let_outer() -> Unit = {\n"
            '  let storage_let_contract: Never = panic("let")\n'
            "  ()\n"
            "}\n",
            storage_message,
        ),
        "NEVER_STORAGE_GENERIC": checker_rejects(
            jar,
            "fn storage_generic_contract() -> List[Never] = []\n",
            storage_message,
        ),
        "NEVER_STORAGE_TUPLE": checker_rejects(
            jar,
            'fn storage_tuple_contract() -> (Never, Int) = panic("tuple")\n',
            storage_message,
        ),
        "NEVER_FUNCTION_PARAMETER": checker_rejects(
            jar,
            "fn function_parameter_contract(f: fn(Never) -> Unit) -> Unit = ()\n",
            storage_message,
        ),
        "NEVER_STORAGE_ASSOC": checker_rejects(
            jar,
            "trait StorageAssocTrait[T] {\n"
            "  type Item\n"
            "  fn assoc_owner(value: T) -> T\n"
            "}\n"
            "type StorageAssocSubject = StorageAssocSubject\n"
            "impl StorageAssocTrait[StorageAssocSubject] {\n"
            "  type Item = Never\n"
            "  fn assoc_owner(value: StorageAssocSubject) -> StorageAssocSubject = value\n"
            "}\n",
            storage_message,
        ),
        "NEVER_ALIAS_DIRECT": checker_rejects(
            jar,
            "alias AliasDirectContract = Never\n",
            storage_message,
        ),
        "NEVER_RESERVED_NAME": (
            checker_rejects(
                jar,
                "type Never = ReservedNameContract\n",
                "`Never` is a builtin type and cannot be redefined",
            )
            and checker_rejects(
                jar,
                "fn reserved_type_parameter_contract[Never](value: Int) -> Unit = ()\n",
                "`Never` is a compiler-owned type name and cannot be a type parameter",
            )
        ),
        "NEVER_BODY_DIVERGES": checker_rejects(
            jar,
            "fn body_contract() -> Never = ()\n",
            "function `body_contract` declares return type Never but its body is Unit",
        ),
        "IO_EXIT_UNIT": checker_rejects(
            jar,
            "use std/io\n"
            "fn io_exit_unit_contract(code: Int) -> Unit !io = io.exit(code)\n"
            "fn io_exit_never_contract(code: Int) -> Never !io = io.exit(code)\n",
            "function `io_exit_never_contract` declares return type Never but its body is Unit",
            standalone=True,
        ),
    }


def lsp_exchange(jar, messages, wanted_ids):
    payload = b""
    for message in messages:
        body = json.dumps(message).encode()
        payload += b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
    proc = subprocess.run(
        java_command(jar, "lsp"),
        cwd=ROOT,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT,
    )
    if proc.returncode != 0:
        return None
    data = proc.stdout
    offset = 0
    out = {}
    while offset < len(data):
        header_end = data.find(b"\r\n\r\n", offset)
        if header_end < 0:
            return None
        length = None
        for line in data[offset:header_end].decode("utf-8", "replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length is None:
            return None
        body_start = header_end + 4
        frame = json.loads(data[body_start:body_start + length])
        offset = body_start + length
        frame_id = frame.get("id")
        if frame_id in wanted_ids:
            out[frame_id] = frame.get("result")
    return out if set(out) == set(wanted_ids) else None


def lsp_results(jar):
    cases = {
        "root": ("", 0, 0),
        "return": ("fn f() -> Nev", 0, len("fn f() -> Nev")),
        "function_type": ("alias F = fn() -> Nev", 0, len("alias F = fn() -> Nev")),
        "effect_return": (
            "effect Stop { fn stop() -> Nev",
            0,
            len("effect Stop { fn stop() -> Nev"),
        ),
        "parameter": ("fn f(value: Nev", 0, len("fn f(value: Nev")),
        "match_arm": (
            "fn f(value: Int) -> Int = match value { _ -> Nev",
            0,
            len("fn f(value: Int) -> Int = match value { _ -> Nev"),
        ),
    }
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}},
        },
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
    ]
    ids = {}
    next_id = 2
    for name, (source, line, character) in cases.items():
        uri = (ROOT / f"zz_builtin_type_{name}.dawn").as_uri()
        messages.append({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "dawn",
                    "version": 1,
                    "text": source,
                }
            },
        })
        ids[next_id] = name
        messages.append({
            "jsonrpc": "2.0",
            "id": next_id,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        })
        next_id += 1
    shutdown_id = next_id
    messages.extend([
        {"jsonrpc": "2.0", "id": shutdown_id, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ])
    frames = lsp_exchange(jar, messages, set(ids))
    if frames is None:
        return None
    out = {}
    for frame_id, name in ids.items():
        result = frames[frame_id]
        if not isinstance(result, list):
            return None
        out[name] = {item.get("label") for item in result}
    return out if set(out) == set(cases) else None


def lsp_is_complete(results):
    if results is None:
        return False
    labels = results["root"]
    governed = labels & (PUBLIC_NAMES | PRELUDE_ADTS | HIDDEN_TYPES)
    return governed == PUBLIC_NAMES | PRELUDE_ADTS


def lsp_never_is_contextual(results):
    return (
        results is not None
        and "Never" in results["return"]
        and "Never" in results["function_type"]
        and "Never" in results["effect_return"]
        and "Never" not in results["root"]
        and "Never" not in results["parameter"]
        and "Never" not in results["match_arm"]
    )


def lsp_hover_results(jar):
    cases = {
        "top": 'fn hover_top() -> Never = panic("top")\n',
        "function_type": "alias HoverFn = fn() -> Never\n",
        "storage": "fn hover_storage(value: Never) -> Unit = ()\n",
        "handler_function_return": (
            "effect HoverHandlerFn { fn call(value: fn() -> Never) -> Unit }\n"
            "fn hover_handler_function_return() -> Unit = {\n"
            "  with handle HoverHandlerFn { call(value: fn() -> Never) => () }\n"
            "  ()\n"
            "}\n"
        ),
        "handler_storage": (
            "effect HoverHandlerStorage { fn stop(value: Int) -> Unit }\n"
            "fn hover_handler_storage() -> Unit = {\n"
            "  with handle HoverHandlerStorage { stop(value: Never) => () }\n"
            "  ()\n"
            "}\n"
        ),
    }
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}},
        },
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
    ]
    ids = {}
    next_id = 2
    for name, source in cases.items():
        uri = (ROOT / f"zz_builtin_type_hover_{name}.dawn").as_uri()
        messages.append({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "dawn",
                    "version": 1,
                    "text": source,
                }
            },
        })
        offset = source.rindex("Never") + 1
        prefix = source[:offset]
        line = prefix.count("\n")
        character = len(prefix.rsplit("\n", 1)[-1])
        ids[next_id] = name
        messages.append({
            "jsonrpc": "2.0",
            "id": next_id,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        })
        next_id += 1
    messages.extend([
        {"jsonrpc": "2.0", "id": next_id, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ])
    frames = lsp_exchange(jar, messages, set(ids))
    if frames is None:
        return None
    out = {}
    for frame_id, name in ids.items():
        result = frames[frame_id]
        if result is None:
            out[name] = None
            continue
        if not isinstance(result, dict):
            return None
        contents = result.get("contents")
        if not isinstance(contents, dict):
            return None
        out[name] = contents.get("value")
    return out if set(out) == set(cases) else None


def lsp_never_hover_is_contextual(results):
    expected = "```dawn\nNever\n```"
    return (
        results is not None
        and results["top"] == expected
        and results["function_type"] == expected
        and results["handler_function_return"] == expected
        and results["storage"] != expected
        and results["handler_storage"] != expected
    )


def doc_results(jar):
    proc = subprocess.run(
        java_command(jar, "doc", "--builtins"),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=TIMEOUT,
    )
    combined = proc.stdout + proc.stderr
    if proc.returncode != 0:
        if "the builtin reference omits a public function:" in combined:
            return False, None, False
        return False, None, None
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return True, None, None
    functions = {
        fn.get("name")
        for group in doc.get("groups", [])
        for fn in group.get("fns", [])
    }
    return True, doc.get("types"), NEWLY_DOCUMENTED_FUNCTIONS <= functions


def main():
    if len(sys.argv) != 2:
        print("usage: probe.py <compiler.jar>", file=sys.stderr)
        return 2
    jar = Path(sys.argv[1]).resolve()
    failed = []
    if not checker_is_complete(jar):
        failed.append("CHECKER_TYPE_INVENTORY")
    lsp = lsp_results(jar)
    if not lsp_is_complete(lsp):
        failed.append("LSP_TYPE_INVENTORY")
    if not lsp_never_is_contextual(lsp):
        failed.append("LSP_NEVER_RETURN_CONTEXT")
    if not lsp_never_hover_is_contextual(lsp_hover_results(jar)):
        failed.append("LSP_NEVER_RETURN_HOVER")
    for marker, passed in never_context_results(jar).items():
        if not passed:
            failed.append(marker)
    doc_ran, types, functions_complete = doc_results(jar)
    if doc_ran and types != DOCUMENTED_TYPES:
        failed.append("DOC_TYPE_INVENTORY")
    if functions_complete is False:
        failed.append("DOC_FUNCTION_INVENTORY")
    elif functions_complete is None:
        failed.append("DOC_FUNCTION_INVENTORY")
    for marker in failed:
        print(f"ASSERT: {marker}")
    if failed:
        return 1
    print("builtin-type-contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

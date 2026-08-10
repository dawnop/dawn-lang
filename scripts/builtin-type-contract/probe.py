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


def lsp_labels(jar):
    uri = (ROOT / "zz_builtin_type_probe.dawn").as_uri()
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}},
        },
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "dawn",
                    "version": 1,
                    "text": "\n",
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": 0},
            },
        },
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ]
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
    while True:
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
        if frame.get("id") == 2:
            result = frame.get("result")
            if not isinstance(result, list):
                return None
            return {item.get("label") for item in result}


def lsp_is_complete(jar):
    labels = lsp_labels(jar)
    if labels is None:
        return False
    governed = labels & (PUBLIC_NAMES | PRELUDE_ADTS | HIDDEN_TYPES)
    return governed == PUBLIC_NAMES | PRELUDE_ADTS


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
    if not lsp_is_complete(jar):
        failed.append("LSP_TYPE_INVENTORY")
    doc_ran, types, functions_complete = doc_results(jar)
    if doc_ran and types != PUBLIC_TYPES:
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

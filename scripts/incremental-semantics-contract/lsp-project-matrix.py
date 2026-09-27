#!/usr/bin/env python3
"""Compare real cross-module overlay revisions without changing fixture files.

The fixed fixture separates provider implementation and signature changes from
an unrelated consumer body. This validates protocol behavior, not latency.

Positions are checked against the text of each revision, not only against a
comparison run: a diagnostic in the provider and the consumer's definition
reply must name the line the provider's current text puts them on. The
provider moves while the consumer's step is reused, which is the case where a
session that kept the reused step's view of its predecessors would answer
with where they used to be (docs/lsp-module-memo-design.md). With
`--expect-counts`, an observed server must also have re-checked exactly the
modules each revision's rule says it must.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from lsp_stats import decode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lsp-workspace-contract"))
from workspace import LspClient, did_open, did_change, did_close, position

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("project edit anchor is missing or ambiguous")
    return text.replace(old, new)


def artifact_hashes(command):
    # Record explicit launch inputs, not a claim about the transitive classpath.
    paths = []
    executable = shutil.which(command[0])
    if executable:
        paths.append(Path(executable))
    for index, argument in enumerate(command):
        if index and command[index - 1] in {"-cp", "-classpath", "--class-path"}:
            for entry in argument.split(os.pathsep):
                path = Path(entry)
                if path.is_file():
                    paths.append(path)
                elif path.is_dir():
                    paths.extend(path.rglob("*.class"))
        elif argument.endswith(".jar") and Path(argument).is_file():
            paths.append(Path(argument))
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}


def validate_epoch(publishes, main_uri, main_version, error_uri, error_message):
    latest = {item["uri"]: item for item in publishes}
    if main_uri not in latest or latest[main_uri].get("version") != main_version:
        raise RuntimeError("consumer was not republished at its current version")
    errors = [(item["uri"], diagnostic.get("message")) for item in publishes
              for diagnostic in item.get("diagnostics", [])]
    expected = [] if error_uri is None else [(error_uri, error_message)]
    if errors != expected:
        raise RuntimeError(f"project diagnostics differ: {errors!r} != {expected!r}")


def validate_versions(publishes, expected):
    if len(publishes) != len(expected) or {item["uri"] for item in publishes} != set(expected):
        raise RuntimeError("project must publish each affected URI exactly once")
    for item in publishes:
        version = expected[item["uri"]]
        if version is None:
            if "version" in item or item.get("diagnostics") != []:
                raise RuntimeError("closed provider must receive an unversioned diagnostic clear")
        elif item.get("version") != version:
            raise RuntimeError("open project document publication has stale or absent version")


def line_of(text, needle):
    if text.count(needle) != 1:
        raise ValueError("position anchor is missing or ambiguous")
    return text[:text.index(needle)].count("\n")


def reply_line(reply):
    location = reply[0] if isinstance(reply, list) and reply else reply
    if not isinstance(location, dict) or "range" not in location:
        raise RuntimeError(f"definition reply has no location: {reply!r}")
    return location.get("uri"), location["range"]["start"]["line"]


def validate_positions(publishes, replies, lib_uri, lib_text, needle):
    """Every provider diagnostic starts on the needle's line; the definition
    of `exported` names the line its declaration is on now."""
    for item in publishes:
        if item["uri"] != lib_uri:
            continue
        for diagnostic in item.get("diagnostics", []):
            line = diagnostic["range"]["start"]["line"]
            if needle is None or line != line_of(lib_text, needle):
                raise RuntimeError(f"provider diagnostic on line {line}, text puts it on "
                                   f"{None if needle is None else line_of(lib_text, needle)}")
    uri, line = reply_line(replies["definition"])
    if uri != lib_uri or line != line_of(lib_text, "pub fn exported"):
        raise RuntimeError(f"definition names {uri}:{line}, text puts it on line "
                           f"{line_of(lib_text, 'pub fn exported')}")


# (reused, checked) per revision, for a server that reuses by the module rule:
# the provider is checked again whenever its text changed, and the consumer
# whenever its own text changed or the provider's exports did.
EXPECTED_COUNTS = {
    "provider-body": (1, 1), "provider-signature": (0, 2), "consumer-recovery": (1, 1),
    "provider-error": (1, 1), "provider-recovery": (1, 1), "provider-move": (1, 1),
    "provider-move-error": (1, 1), "provider-move-recovery": (1, 1),
    "close-provider": (0, 2), "reopen-provider": (0, 2),
}


def validate_counts(label, counts):
    observed = [row["counts"] for row in counts if row["observed"]]
    if len(observed) != 1:
        raise RuntimeError(f"{label}: expected one observed analysis, got {counts!r}")
    got = (observed[0]["reused_modules"], observed[0]["checked_modules"])
    if got != EXPECTED_COUNTS[label]:
        raise RuntimeError(f"{label}: reused/checked {got} != {EXPECTED_COUNTS[label]}")


def selftest():
    assert line_of("a\nb\nc", "c") == 2
    for invalid in ("", "c c"):
        try:
            line_of(invalid, "c")
        except ValueError:
            continue
        raise AssertionError("ambiguous position anchor accepted")
    text = "# moved\npub fn exported(x: Int) -> Bool = nope\n"
    at = {"uri": "lib", "range": {"start": {"line": 1}}}
    diag = {"uri": "lib", "diagnostics": [{"range": {"start": {"line": 1}}}]}
    validate_positions([diag], {"definition": at}, "lib", text, "nope")
    validate_positions([], {"definition": [at]}, "lib", text, None)
    stale = {"uri": "lib", "range": {"start": {"line": 0}}}
    for publishes, definition, needle in (([diag], stale, "nope"),
                                         ([{**diag, "diagnostics": [{"range": {"start": {"line": 0}}}]}], at, "nope"),
                                         ([diag], at, None), ([], {**at, "uri": "main"}, None), ([], None, None)):
        try:
            validate_positions(publishes, {"definition": definition}, "lib", text, needle)
        except RuntimeError:
            continue
        raise AssertionError("stale position accepted")
    print("OK: position oracle and five rejection cases")
    row = {"observed": True, "counts": {"reused_modules": 1, "checked_modules": 1}}
    validate_counts("provider-body", [row])
    for label, rows in (("provider-signature", [row]), ("provider-body", [row, row]),
                        ("provider-body", [{"observed": False, "counts": None}])):
        try:
            validate_counts(label, rows)
        except RuntimeError:
            continue
        raise AssertionError("wrong analysis counts accepted")
    print("OK: count oracle and three rejection cases")
    assert replace_once("a target b", "target", "changed") == "a changed b"
    for invalid in ("absent", "target target"):
        try:
            replace_once(invalid, "target", "changed")
        except ValueError:
            continue
        raise AssertionError("drifted project edit anchor accepted")
    clean = {"uri": "main", "version": 2, "diagnostics": []}
    error = {"uri": "lib", "version": 3, "diagnostics": [{"message": "expected error"}]}
    validate_epoch([clean], "main", 2, None, None)
    validate_epoch([error, clean], "main", 2, "lib", "expected error")
    cases = [([], 2, None, None), ([clean], 3, None, None),
             ([error, clean], 2, None, None), ([clean], 2, "lib", "expected error"),
             ([error, clean], 2, "main", "expected error"),
             ([error, clean], 2, "lib", "different error"),
             ([error, error, clean], 2, "lib", "expected error")]
    for publishes, version, owner, message in cases:
        try:
            validate_epoch(publishes, "main", version, owner, message)
        except RuntimeError:
            continue
        raise AssertionError("invalid project publication accepted")
    print("OK: project publication oracle and seven rejection cases")
    validate_versions([error, clean], {"lib": 3, "main": 2})
    cleared = {"uri": "lib", "diagnostics": []}
    validate_versions([cleared, clean], {"lib": None, "main": 2})
    for items, expected in (([clean], {"lib": 3, "main": 2}),
                            ([error, clean], {"lib": 4, "main": 2}),
                            ([error, clean], {"lib": None, "main": 2}),
                            ([{**cleared, "version": 3}, clean], {"lib": None, "main": 2})):
        try:
            validate_versions(items, expected)
        except RuntimeError:
            continue
        raise AssertionError("stale/missing provider publication accepted")
    print("OK: project version oracle and four rejection cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--expect-counts", action="store_true",
                        help="require an observed server's per-revision reuse counts")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a server command")
    fixture = Path(__file__).resolve().parent / "project-edit-fixture"
    paths = {name: fixture / "src" / (name + ".dawn") for name in ("lib", "main")}
    texts = {name: path.read_text() for name, path in paths.items()}
    uris = {name: path.as_uri() for name, path in paths.items()}
    fingerprints = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [fixture / "dawn.toml", *paths.values()]}
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "command": command, "sources": fingerprints, "timing_evidence": False,
        "launch_artifacts": artifact_hashes(command),
        "artifact_scope": "explicit executable, jar arguments and classpath files; not transitive classpath attestation",
    }
    boolean_lib = replace_once(texts["lib"], "exported(x: Int) -> Int = x + 1", "exported(x: Int) -> Bool = true")
    boolean_main = replace_once(texts["main"], "probe(x: Int) -> Int", "probe(x: Int) -> Bool")
    moved_lib = "# moved provider\n\n" + boolean_lib
    steps = [
        ("provider-body", "lib", replace_once(texts["lib"], "x + 1", "x + 9"), None),
        ("provider-signature", "lib", boolean_lib, "main"),
        ("consumer-recovery", "main", boolean_main, None),
        ("provider-error", "lib", replace_once(boolean_lib, "= true", "= missing_value"), "lib"),
        ("provider-recovery", "lib", boolean_lib, None),
        ("provider-move", "lib", moved_lib, None),
        ("provider-move-error", "lib",
         "# moved provider\n\n# and moved again\n\n" + replace_once(boolean_lib, "= true", "= missing_value"), "lib"),
        ("provider-move-recovery", "lib", moved_lib, None),
        ("close-provider", "lib", None, "main"),
        ("reopen-provider", "lib", boolean_lib, None),
    ]
    expected_messages = {
        "provider-signature": "function `probe` declares return type Int but its body is Bool",
        "provider-error": "undefined variable: missing_value",
        "provider-move-error": "undefined variable: missing_value",
        "close-provider": "function `probe` declares return type Bool but its body is Int",
    }
    history_versions = {name: 1 for name in texts}
    history = []
    for label, name, text, _ in steps:
        history_versions[name] += 1
        history.append({"label": label, "uri": uris[name], "version": history_versions[name],
                        "operation": "close" if text is None else "open" if label == "reopen-provider" else "change",
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest() if text is not None else None})
    metadata["history"] = history
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rows, current = [], dict(texts)
    versions = {name: 1 for name in texts}
    client = LspClient(command, ROOT)
    try:
        client.initialize()
        mark = client.mark()
        for name in ("lib", "main"):
            client.send(did_open(uris[name], current[name]))
        initial = client.barrier(mark)
        if any(frame.get("params", {}).get("diagnostics") for frame in initial
               if frame.get("method") == "textDocument/publishDiagnostics"):
            raise RuntimeError("project baseline contains diagnostics")
        for label, name, text, error_owner in steps:
            mark, stderr_mark = client.mark(), len(client.stderr_text())
            versions[name] += 1
            if text is None:
                client.send(did_close(uris[name]))
            elif label == "reopen-provider":
                client.send(did_open(uris[name], text, versions[name]))
                current[name] = text
            else:
                client.send(did_change(uris[name], text, versions[name]))
                current[name] = text
            frames = client.barrier(mark)
            publishes = [frame["params"] for frame in frames
                         if frame.get("method") == "textDocument/publishDiagnostics"]
            validate_epoch(publishes, uris["main"], versions["main"],
                           uris[error_owner] if error_owner else None, expected_messages.get(label))
            validate_versions(publishes, {uris["main"]: versions["main"],
                                         uris["lib"]: None if label == "close-provider" else versions["lib"]})
            replies = {method: client.result("textDocument/" + method, {
                "textDocument": {"uri": uris["main"]},
                "position": position(current["main"], "exported(x)")})
                for method in ("hover", "definition", "completion")}
            if error_owner is None and (not replies["hover"] or not replies["definition"]):
                raise RuntimeError(f"{label}: clean query target unresolved")
            lib_text = texts["lib"] if text is None and name == "lib" else current["lib"]
            if replies["definition"]:
                validate_positions(publishes, replies, uris["lib"], lib_text,
                                   "missing_value" if "missing_value" in lib_text else None)
            counts = [decode(line) for line in client.stderr_text()[stderr_mark:].splitlines()
                      if line.startswith("LSP_BODY_STATS\t")]
            if args.expect_counts:
                validate_counts(label, counts)
            rows.append({"label": label, "diagnostics": publishes, "replies": replies,
                         "analysis_counts": counts})
            (args.output / "samples.json").write_text(json.dumps(rows, indent=2) + "\n")
        client.shutdown_exit()
    finally:
        (args.output / "stderr.txt").write_text(client.stderr_text())
        client.close()
    semantic = [{key: value for key, value in row.items() if key != "analysis_counts"} for row in rows]
    (args.output / "semantic.json").write_text(json.dumps(semantic, indent=2) + "\n")
    if args.compare:
        previous = json.loads((args.compare / "metadata.json").read_text())
        if previous["sources"] != fingerprints or previous.get("history") != history:
            raise RuntimeError("project comparison fixture differs")
        if json.loads((args.compare / "semantic.json").read_text()) != semantic:
            raise RuntimeError("project protocol results differ from the comparison run")
    for name, path in paths.items():
        if path.read_text() != texts[name]:
            raise RuntimeError("project benchmark changed a fixture file")
    print(f"OK: {len(rows)} cross-module protocol revisions; no timing claim")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        selftest()
    else:
        main()

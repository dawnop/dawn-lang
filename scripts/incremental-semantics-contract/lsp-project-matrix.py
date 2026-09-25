#!/usr/bin/env python3
"""Compare real cross-module overlay revisions without changing fixture files.

The fixed fixture separates provider implementation and signature changes from
an unrelated consumer body. This validates protocol behavior, not latency.
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

COUNT_FIELDS = ("checked_bodies", "reused_bodies", "reused_modules",
                "cold_rejected_bodies", "unobserved_modules", "retained_body_products")
EXPECTED_COUNTS = {
    "provider-body": (1, 3, 0, 0, 0, 4),
    "provider-signature": (2, 2, 0, 1, 0, 2),
    "consumer-recovery": (2, 0, 1, 0, 0, 4),
    "provider-error": (1, 1, 0, 0, 1, 0),
    "provider-recovery": (4, 0, 0, 0, 0, 4),
    "provider-move": (0, 4, 0, 0, 0, 4),
    "close-provider": (2, 2, 0, 1, 0, 2),
    "reopen-provider": (3, 1, 0, 0, 0, 4),
}


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


def validate_counts(counts, label):
    if len(counts) != 1 or not counts[0]["observed"] or counts[0]["scope"] != "project":
        raise RuntimeError("expected one observed project analysis")
    actual = tuple(counts[0]["counts"][field] for field in COUNT_FIELDS)
    if actual != EXPECTED_COUNTS[label]:
        raise RuntimeError(f"{label}: project counts {actual} != {EXPECTED_COUNTS[label]}")


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


def selftest():
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
    for label, expected in EXPECTED_COUNTS.items():
        good = {"observed": True, "scope": "project", "counts": dict(zip(COUNT_FIELDS, expected))}
        validate_counts([good], label)
        for invalid in ([], [good, good], [{**good, "scope": "standalone"}],
                        [{**good, "counts": {**good["counts"], "checked_bodies": expected[0] + 1}}]):
            try:
                validate_counts(invalid, label)
            except RuntimeError:
                continue
            raise AssertionError("invalid project count observation accepted")
    print("OK: eight exact project censuses and thirty-two rejection cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--expect-reuse", action="store_true")
    parser.add_argument("--expect-parse-counts", choices=("prepared", "cold"))
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
    steps = [
        ("provider-body", "lib", replace_once(texts["lib"], "x + 1", "x + 9"), None),
        ("provider-signature", "lib", boolean_lib, "main"),
        ("consumer-recovery", "main", boolean_main, None),
        ("provider-error", "lib", replace_once(boolean_lib, "= true", "= missing_value"), "lib"),
        ("provider-recovery", "lib", boolean_lib, None),
        ("provider-move", "lib", "# moved provider\n\n" + boolean_lib, None),
        ("close-provider", "lib", None, "main"),
        ("reopen-provider", "lib", boolean_lib, None),
    ]
    expected_messages = {
        "provider-signature": "function `probe` declares return type Int but its body is Bool",
        "provider-error": "undefined variable: missing_value",
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
            counts = [decode(line) for line in client.stderr_text()[stderr_mark:].splitlines()
                      if line.startswith("LSP_BODY_STATS\t")]
            entries = [line.split("\t")[1:] for line in client.stderr_text()[stderr_mark:].splitlines()
                       if line.startswith("LSP_PARSE_ENTRY\t")]
            if any(entry not in (["0"], ["1"], ["2"]) for entry in entries):
                raise RuntimeError("invalid project parser-entry trace")
            parse_counts = [entries.count([str(index)]) for index in range(3)] if entries else None
            if args.expect_parse_counts:
                expected = [2, 2, 2] if args.expect_parse_counts == "prepared" else [2, 0, 0]
                if parse_counts != expected:
                    raise RuntimeError(f"{label}: project parse/index/projection counts {parse_counts} != {expected}")
            if args.expect_reuse:
                validate_counts(counts, label)
            rows.append({"label": label, "diagnostics": publishes, "replies": replies,
                         "analysis_counts": counts, "parse_counts": parse_counts})
            (args.output / "samples.json").write_text(json.dumps(rows, indent=2) + "\n")
        client.shutdown_exit()
    finally:
        (args.output / "stderr.txt").write_text(client.stderr_text())
        client.close()
    semantic = [{key: value for key, value in row.items() if key not in {"analysis_counts", "parse_counts"}} for row in rows]
    (args.output / "semantic.json").write_text(json.dumps(semantic, indent=2) + "\n")
    if args.compare:
        previous = json.loads((args.compare / "metadata.json").read_text())
        if previous["sources"] != fingerprints or previous.get("history") != history:
            raise RuntimeError("project comparison fixture differs")
        if json.loads((args.compare / "semantic.json").read_text()) != semantic:
            raise RuntimeError("project protocol cold/prepared results differ")
    for name, path in paths.items():
        if path.read_text() != texts[name]:
            raise RuntimeError("project benchmark changed a fixture file")
    print(f"OK: {len(rows)} cross-module protocol revisions; no timing claim")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        selftest()
    else:
        main()

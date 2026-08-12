#!/usr/bin/env python3
"""Probe for-pattern queries and completion scope through the LSP server."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


HEADER_OWNER = "for pattern headers expose binder and constructor queries"
RANGE_COMPLETION_OWNER = "range upper-bound completion offers outer locals"
SCOPE_OWNER = "for completion does not leak pattern or body locals"

LIB_TEXT = "pub type Only = Only(value: Int)\n"
TEXT = (
    "use qlib as q\n"
    "\n"
    "type Choice = Left(value: Int) | Right(value: Int)\n"
    "\n"
    "fn probe(source: List[q.Only], choices: List[Choice], outer: Int) -> Int = {\n"
    "  for q.Only(header_value) in source {\n"
    "    let _ = header_value\n"
    "    let body_local = header_value\n"
    "    let _ = body_local\n"
    "  }\n"
    "  for Left(shared) | Right(shared) in choices {\n"
    "    let _ = shared\n"
    "  }\n"
    "  for range_value in outer..outer {\n"
    "    let _ = range_value\n"
    "  }\n"
    "  outer\n"
    "}\n"
)


def position(index: int, text: str = TEXT) -> dict[str, int]:
    return {
        "line": text.count("\n", 0, index),
        "character": index - (text.rfind("\n", 0, index) + 1),
    }


def frame(message: dict) -> bytes:
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def replies(raw: bytes) -> dict[int, object]:
    out = {}
    rest = raw
    while True:
        head = rest.find(b"\r\n\r\n")
        if head < 0:
            return out
        header = rest[:head].decode("ascii", "replace")
        length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = rest[head + 4 : head + 4 + length]
        rest = rest[head + 4 + length :]
        try:
            message = json.loads(body)
        except ValueError:
            continue
        if isinstance(message, dict) and "id" in message and "result" in message:
            out[message["id"]] = message["result"]


def hover_text(result: object) -> str:
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents")
    if isinstance(contents, dict):
        return contents.get("value", "")
    return contents if isinstance(contents, str) else ""


def range_start(result: object):
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return None
    target = result.get("targetSelectionRange") or result.get("range")
    return target.get("start") if isinstance(target, dict) else None


def definition_uri(result: object):
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return None
    return result.get("targetUri") or result.get("uri")


def completion_labels(result: object) -> list[str]:
    if isinstance(result, dict):
        result = result.get("items", [])
    if not isinstance(result, list):
        return []
    return [item.get("label") for item in result if isinstance(item, dict)]


def fail(owner: str) -> None:
    print("ASSERT: " + owner)


def main() -> int:
    java, jar, cwd = sys.argv[1:]
    ctor = TEXT.index("q.Only(header") + len("q.")
    header_bind = TEXT.index("header_value")
    header_use = TEXT.index("header_value", header_bind + 1)
    header_start = TEXT.index("q.Only(header")
    source_use = TEXT.index("in source") + len("in ")
    range_upper = TEXT.index("..outer") + len("..")
    after = TEXT.rindex("outer")
    shared_occurrences = []
    start = 0
    while True:
        found = TEXT.find("shared", start)
        if found < 0:
            break
        shared_occurrences.append(found)
        start = found + 1

    temp = tempfile.TemporaryDirectory(prefix="for-pattern-lsp-")
    project = Path(temp.name)
    source_dir = project / "src"
    source_dir.mkdir()
    (project / "dawn.toml").write_text(
        'schema = 1\nname = "for_pattern_lsp"\n', encoding="utf-8"
    )
    lib_path = source_dir / "qlib.dawn"
    main_path = source_dir / "main.dawn"
    lib_path.write_text(LIB_TEXT, encoding="utf-8")
    main_path.write_text(TEXT, encoding="utf-8")
    lib_uri = lib_path.resolve().as_uri()
    uri = main_path.resolve().as_uri()

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "processId": None, "rootUri": project.resolve().as_uri(), "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": lib_uri, "languageId": "dawn", "version": 1,
                             "text": LIB_TEXT}}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "languageId": "dawn", "version": 1,
                             "text": TEXT}}},
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(ctor)}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(ctor)}},
        {"jsonrpc": "2.0", "id": 4, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(header_bind)}},
        {"jsonrpc": "2.0", "id": 5, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(header_use)}},
        {"jsonrpc": "2.0", "id": 6, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(source_use)}},
        {"jsonrpc": "2.0", "id": 7, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(header_use)}},
        {"jsonrpc": "2.0", "id": 8, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(after)}},
        {"jsonrpc": "2.0", "id": 9, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[1])}},
        {"jsonrpc": "2.0", "id": 10, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[1])}},
        {"jsonrpc": "2.0", "id": 11, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[2])}},
        {"jsonrpc": "2.0", "id": 12, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(header_bind)}},
        {"jsonrpc": "2.0", "id": 13, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(header_start)}},
        {"jsonrpc": "2.0", "id": 14, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(range_upper)}},
        {"jsonrpc": "2.0", "id": 15, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ]
    done = subprocess.run(
        [java, "-Xss512m", "-Xmx2g", "-jar", jar, "lsp"],
        input=b"".join(frame(message) for message in messages),
        capture_output=True,
        cwd=cwd,
    )
    if done.returncode != 0:
        sys.stderr.write(done.stdout.decode("utf-8", "replace"))
        sys.stderr.write(done.stderr.decode("utf-8", "replace"))
        fail(HEADER_OWNER)
        fail(RANGE_COMPLETION_OWNER)
        fail(SCOPE_OWNER)
        return 1

    got = replies(done.stdout)
    header_ok = True
    if "Only" not in hover_text(got.get(2)):
        header_ok = False
    if (definition_uri(got.get(3)) != lib_uri or
            range_start(got.get(3)) != position(LIB_TEXT.rindex("Only"), LIB_TEXT)):
        header_ok = False
    if "header_value: Int" not in hover_text(got.get(4)):
        header_ok = False
    if range_start(got.get(5)) != position(header_bind):
        header_ok = False
    if range_start(got.get(12)) != position(header_bind):
        header_ok = False
    if "shared: Int" not in hover_text(got.get(9)):
        header_ok = False
    if range_start(got.get(10)) != position(shared_occurrences[0]):
        header_ok = False

    source_labels = completion_labels(got.get(6))
    body_labels = completion_labels(got.get(7))
    after_labels = completion_labels(got.get(8))
    shared_labels = completion_labels(got.get(11))
    header_labels = completion_labels(got.get(13))
    range_upper_labels = completion_labels(got.get(14))
    range_completion_ok = range_upper_labels.count("outer") == 1
    scope_ok = (
        source_labels.count("source") == 1
        and source_labels.count("outer") == 1
        and "header_value" not in source_labels
        and "body_local" not in source_labels
        and body_labels.count("header_value") == 1
        and body_labels.count("outer") == 1
        and "body_local" not in body_labels
        and header_labels == []
        and "range_value" not in range_upper_labels
        and "header_value" not in range_upper_labels
        and "body_local" not in range_upper_labels
        and "shared" not in range_upper_labels
        and "header_value" not in after_labels
        and "body_local" not in after_labels
        and "shared" not in after_labels
        and "range_value" not in after_labels
        and after_labels.count("outer") == 1
        and shared_labels.count("shared") == 1
        and shared_labels.count("outer") == 1
    )

    if not header_ok:
        fail(HEADER_OWNER)
    if not range_completion_ok:
        fail(RANGE_COMPLETION_OWNER)
    if not scope_ok:
        fail(SCOPE_OWNER)
    if not header_ok or not range_completion_ok or not scope_ok:
        print(json.dumps(got, sort_keys=True), file=sys.stderr)
        return 1
    print("PASS  for-pattern header queries and completion scopes are exact")
    return 0


if __name__ == "__main__":
    sys.exit(main())

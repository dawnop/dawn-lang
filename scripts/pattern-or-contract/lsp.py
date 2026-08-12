#!/usr/bin/env python3
"""Probe every or-pattern binder occurrence and its shared environment."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


LIB_TEXT = "pub type Qualified = Pick(value: Int)\n"
TEXT = (
    "use qlib as q\n"
    "\n"
    "type Choice = Left(value: Int) | Right(value: Int)\n"
    "\n"
    "fn pick(choice: Choice) -> Int =\n"
    "  match choice {\n"
    "    Left(shared) | Right(shared) -> shared\n"
    "  }\n"
    "\n"
    "fn tail_len(xs: List[Int]) -> Int =\n"
    "  match xs {\n"
    "    [..rest] | [x, ..rest] -> len(rest)\n"
    "  }\n"
    "\n"
    "fn qualified(value: q.Qualified) -> Int =\n"
    "  match value {\n"
    "    q.Pick(picked) -> picked\n"
    "  }\n"
)


def position(index, text=TEXT):
    return {
        "line": text.count("\n", 0, index),
        "character": index - (text.rfind("\n", 0, index) + 1),
    }


def frame(message):
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def replies(raw):
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
        body = rest[head + 4:head + 4 + length]
        rest = rest[head + 4 + length:]
        try:
            message = json.loads(body)
        except ValueError:
            continue
        if isinstance(message, dict) and "id" in message and "result" in message:
            out[message["id"]] = message["result"]


def hover_text(result):
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents")
    if isinstance(contents, dict):
        return contents.get("value", "")
    if isinstance(contents, str):
        return contents
    return ""


def range_start(result):
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return None
    target = result.get("targetSelectionRange") or result.get("range")
    if not isinstance(target, dict):
        return None
    return target.get("start")


def definition_uri(result):
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return None
    return result.get("targetUri") or result.get("uri")


def completion_labels(result):
    if isinstance(result, dict):
        result = result.get("items", [])
    if not isinstance(result, list):
        return []
    return [item.get("label") for item in result if isinstance(item, dict)]


def fail(message):
    print("ASSERT: " + message)


def main():
    java, jar, cwd = sys.argv[1:]
    shared_occurrences = []
    rest_occurrences = []
    for needle, found_at in (("shared", shared_occurrences), ("rest", rest_occurrences)):
        start = 0
        while True:
            found = TEXT.find(needle, start)
            if found < 0:
                break
            found_at.append(found)
            start = found + 1
    if len(shared_occurrences) != 3 or len(rest_occurrences) != 3:
        fail("the LSP fixture keeps three occurrences of each shared binding")
        return 1

    qualified_ctor = TEXT.index("q.Pick") + len("q.")
    qualified_binds = []
    start = 0
    while True:
        found = TEXT.find("picked", start)
        if found < 0:
            break
        qualified_binds.append(found)
        start = found + 1
    if len(qualified_binds) != 2:
        fail("the qualified-pattern fixture keeps its binding and use")
        return 1

    temp = tempfile.TemporaryDirectory(prefix="pattern-or-lsp-")
    project = Path(temp.name)
    source = project / "src"
    source.mkdir()
    (project / "dawn.toml").write_text(
        'schema = 1\nname = "pattern_or_lsp"\n', encoding="utf-8")
    lib_path = source / "qlib.dawn"
    main_path = source / "main.dawn"
    lib_path.write_text(LIB_TEXT, encoding="utf-8")
    main_path.write_text(TEXT, encoding="utf-8")
    lib_uri = lib_path.resolve().as_uri()
    uri = main_path.resolve().as_uri()

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"processId": None, "rootUri": project.resolve().as_uri(), "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": lib_uri, "languageId": "dawn", "version": 1,
                             "text": LIB_TEXT}}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "languageId": "dawn", "version": 1, "text": TEXT}}},
    ]
    for request_id, index in enumerate(shared_occurrences, start=2):
        messages.append({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "textDocument/hover",
            "params": {"textDocument": {"uri": uri}, "position": position(index)},
        })
    for request_id, index in enumerate(rest_occurrences, start=5):
        messages.append({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "textDocument/hover",
            "params": {"textDocument": {"uri": uri}, "position": position(index)},
        })
    messages.extend([
        {"jsonrpc": "2.0", "id": 8, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[1])}},
        {"jsonrpc": "2.0", "id": 9, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(rest_occurrences[1])}},
        {"jsonrpc": "2.0", "id": 10, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri},
            "position": position(shared_occurrences[2] + len("shared"))}},
        {"jsonrpc": "2.0", "id": 11, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(qualified_ctor)}},
        {"jsonrpc": "2.0", "id": 12, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(qualified_ctor)}},
        {"jsonrpc": "2.0", "id": 13, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(qualified_binds[0])}},
        {"jsonrpc": "2.0", "id": 14, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(qualified_binds[0])}},
        {"jsonrpc": "2.0", "id": 15, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(qualified_binds[1])}},
        {"jsonrpc": "2.0", "id": 16, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(qualified_binds[1])}},
        {"jsonrpc": "2.0", "id": 17, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ])

    done = subprocess.run(
        [java, "-Xss512m", "-Xmx2g", "-jar", jar, "lsp"],
        input=b"".join(frame(message) for message in messages),
        capture_output=True,
        cwd=cwd,
    )
    if done.returncode != 0:
        temp.cleanup()
        sys.stderr.write(done.stdout.decode("utf-8", "replace"))
        sys.stderr.write(done.stderr.decode("utf-8", "replace"))
        fail("or-pattern LSP server exits successfully")
        return 1

    got = replies(done.stdout)
    failures = []

    def reject(message):
        if message not in failures:
            failures.append(message)

    for request_id in (2, 3, 4):
        if "shared: Int" not in hover_text(got.get(request_id)):
            reject("every or-pattern binding occurrence has hover")
            break
    for request_id in (5, 6, 7):
        if "rest: List[Int]" not in hover_text(got.get(request_id)):
            reject("every list-rest binding occurrence has hover")
            break

    if range_start(got.get(8)) != position(shared_occurrences[0]):
        reject("later alternatives resolve to the first canonical binding")

    if range_start(got.get(9)) != position(TEXT.find("..rest")):
        reject("list-rest alternatives resolve to the first canonical binding")

    if completion_labels(got.get(10)).count("shared") != 1:
        reject("or-pattern completion deduplicates the shared symbol")

    pqual_owner = "qualified constructor patterns expose constructor and binding queries"
    if "Pick" not in hover_text(got.get(11)):
        reject(pqual_owner)
    if (definition_uri(got.get(12)) != lib_uri or
            range_start(got.get(12)) != position(LIB_TEXT.index("Pick"), LIB_TEXT)):
        reject(pqual_owner)
    for request_id in (13, 15):
        if "picked: Int" not in hover_text(got.get(request_id)):
            reject(pqual_owner)
    if range_start(got.get(14)) != position(qualified_binds[0]):
        reject(pqual_owner)
    if range_start(got.get(16)) != position(qualified_binds[0]):
        reject(pqual_owner)

    for message in failures:
        fail(message)
    if failures:
        print(json.dumps(got, sort_keys=True), file=sys.stderr)
        temp.cleanup()
        return 1

    temp.cleanup()
    print("PASS  binders and qualified constructors hover and resolve canonically")
    return 0


if __name__ == "__main__":
    sys.exit(main())

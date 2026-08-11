#!/usr/bin/env python3
"""Probe every or-pattern binder occurrence and its shared environment."""

import json
import subprocess
import sys


TEXT = (
    "type Choice = Left(value: Int) | Right(value: Int)\n"
    "\n"
    "fn pick(choice: Choice) -> Int =\n"
    "  match choice {\n"
    "    Left(shared) | Right(shared) -> shared\n"
    "  }\n"
)
URI = "untitled:pattern-or-contract.dawn"


def position(index):
    return {
        "line": TEXT.count("\n", 0, index),
        "character": index - (TEXT.rfind("\n", 0, index) + 1),
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


def completion_labels(result):
    if isinstance(result, dict):
        result = result.get("items", [])
    if not isinstance(result, list):
        return []
    return [item.get("label") for item in result if isinstance(item, dict)]


def fail(message, replies_by_id=None):
    print("ASSERT: " + message)
    if replies_by_id is not None:
        print(json.dumps(replies_by_id, sort_keys=True), file=sys.stderr)
    return 1


def main():
    java, jar, cwd = sys.argv[1:]
    occurrences = []
    start = 0
    while True:
        found = TEXT.find("shared", start)
        if found < 0:
            break
        occurrences.append(found)
        start = found + 1
    if len(occurrences) != 3:
        return fail("the LSP fixture must contain three `shared` occurrences")

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"processId": None, "rootUri": None, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": URI, "languageId": "dawn", "version": 1, "text": TEXT}}},
    ]
    for request_id, index in enumerate(occurrences, start=2):
        messages.append({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "textDocument/hover",
            "params": {"textDocument": {"uri": URI}, "position": position(index)},
        })
    messages.extend([
        {"jsonrpc": "2.0", "id": 5, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": URI}, "position": position(occurrences[1])}},
        {"jsonrpc": "2.0", "id": 6, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": URI}, "position": position(occurrences[2] + len("shared"))}},
        {"jsonrpc": "2.0", "id": 7, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ])

    done = subprocess.run(
        [java, "-Xss512m", "-Xmx2g", "-jar", jar, "lsp"],
        input=b"".join(frame(message) for message in messages),
        capture_output=True,
        cwd=cwd,
    )
    if done.returncode != 0:
        sys.stderr.write(done.stdout.decode("utf-8", "replace"))
        sys.stderr.write(done.stderr.decode("utf-8", "replace"))
        return fail("or-pattern LSP server exits successfully")

    got = replies(done.stdout)
    for request_id in (2, 3, 4):
        if "shared: Int" not in hover_text(got.get(request_id)):
            return fail("every or-pattern binding occurrence has hover", got)

    if range_start(got.get(5)) != position(occurrences[0]):
        return fail("later alternatives resolve to the first canonical binding", got)

    if completion_labels(got.get(6)).count("shared") != 1:
        return fail("or-pattern completion deduplicates the shared symbol", got)

    print("PASS  every binder hovers, definitions canonicalize, and completion deduplicates")
    return 0


if __name__ == "__main__":
    sys.exit(main())

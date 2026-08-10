#!/usr/bin/env python3
"""Hover at named positions in a project, and print `<label>\t<hover text>`.

The subject is the LSP's typed-child mapping, which decides whether a node
under a call gets its typed node handed to it. An unannotated lambda's
parameter is the sharpest probe there is: its hover text is rendered from the
typed node and from nothing else, so a missing mapping shows up as an empty
hover rather than as a wrong one. A qualified constructor's *name* is the same
kind of probe from the other side -- the signature is offered at that span by
`walk_ctor_call` and by no other path.

Positions are given as `label=needle` with an optional `+delta`; the needle is
searched in the named file.
"""

import json
import subprocess
import sys


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


def main():
    cli, root, path = sys.argv[1], sys.argv[2], sys.argv[3]
    text = open(path).read()
    uri = "file://" + path

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"processId": None, "rootUri": None, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "dawn", "version": 1, "text": text}}},
    ]
    labels = {}
    next_id = 2
    for spec in sys.argv[4:]:
        label, needle = spec.split("=", 1)
        delta = 0
        if "+" in needle:
            needle, raw_delta = needle.rsplit("+", 1)
            delta = int(raw_delta)
        index = text.index(needle) + delta
        messages.append({"jsonrpc": "2.0", "id": next_id, "method": "textDocument/hover",
                         "params": {"textDocument": {"uri": uri}, "position": {
                             "line": text.count("\n", 0, index),
                             "character": index - (text.rfind("\n", 0, index) + 1)}}})
        labels[next_id] = label
        next_id += 1
    messages.append({"jsonrpc": "2.0", "id": next_id, "method": "shutdown", "params": {}})
    messages.append({"jsonrpc": "2.0", "method": "exit", "params": {}})

    done = subprocess.run([cli, "lsp"], input=b"".join(frame(m) for m in messages),
                          capture_output=True, cwd=root)
    if done.returncode != 0:
        sys.stderr.write(done.stderr.decode("utf-8", "replace"))
        return done.returncode
    got = replies(done.stdout)
    for ident in sorted(labels):
        one_line = " ".join(hover_text(got.get(ident)).split())
        print(f"{labels[ident]}\t{one_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

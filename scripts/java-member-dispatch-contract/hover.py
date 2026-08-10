#!/usr/bin/env python3
"""Hover over an argument of `Class.Member(args)`.

The argument is walked either way; what the walk cannot do without the XJava
child mapping is hand the argument its typed node, and a local's hover text is
rendered from that node alone. So an empty hover here is exactly the missing
mapping, and `let scale: Float` is exactly its presence.

The buffer is `untitled:` on purpose -- the analyze(text) path needs no file on
disk, and `java.lang.Math` is a JDK class, which is all the language server
resolves.
"""

import json
import subprocess
import sys

TEXT = (
    'use java "java.lang.Math"\n'
    "\n"
    "fn f(scale: Float) -> Float !io = Math.IEEEremainder(scale, 3.0)\n"
)
URI = "untitled:Untitled-1"


def position(needle: str) -> dict:
    index = TEXT.index(needle)
    return {
        "line": TEXT.count("\n", 0, index),
        "character": index - (TEXT.rfind("\n", 0, index) + 1),
    }


def frame(message: dict) -> bytes:
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def main() -> int:
    cli, cwd = sys.argv[1], sys.argv[2]
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"processId": None, "rootUri": None, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": URI, "languageId": "dawn", "version": 1, "text": TEXT}}},
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": URI}, "position": position("scale, 3.0")}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ]
    done = subprocess.run(
        [cli, "lsp"],
        input=b"".join(frame(message) for message in messages),
        capture_output=True,
        cwd=cwd,
    )
    sys.stdout.write(done.stdout.decode("utf-8", "replace"))
    sys.stderr.write(done.stderr.decode("utf-8", "replace"))
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())

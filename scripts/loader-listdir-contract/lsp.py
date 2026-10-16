#!/usr/bin/env python3
"""A project directory the loader cannot list is reported by the language server.

    lsp.py <server command...> <workspace>

Opens `<workspace>/src/main.dawn` in a server and requires a diagnostic that says
`cannot list source directory`, published on the directory that could not be
listed. Before #759 the walk returned an empty list for it, so the server
checked a project with modules missing and said nothing. The server keeps
partial results; what it may not do is present them as the whole workspace.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

FRAME_SECONDS = 120
SETTLE_SECONDS = 3


class Server:
    def __init__(self, command: list[str]) -> None:
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        self.buffer = b""

    def send(self, message: dict) -> None:
        body = json.dumps(message, separators=(",", ":")).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()

    def receive(self, seconds: float) -> dict | None:
        deadline = time.monotonic() + seconds
        fd = self.proc.stdout.fileno()
        while True:
            boundary = self.buffer.find(b"\r\n\r\n")
            if boundary >= 0:
                length = None
                for line in self.buffer[:boundary].decode("ascii").split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":", 1)[1].strip())
                end = boundary + 4 + length
                if len(self.buffer) >= end:
                    body = self.buffer[boundary + 4 : end]
                    self.buffer = self.buffer[end:]
                    return json.loads(body)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                raise RuntimeError("server closed before the expected frame")
            self.buffer += chunk


def main() -> int:
    command, workspace = sys.argv[1:-1], Path(sys.argv[-1]).resolve()
    main_uri = (workspace / "src" / "main.dawn").as_uri()
    hidden_uri = (workspace / "src" / "hidden").as_uri()
    server = Server(command)
    server.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"processId": None, "rootUri": workspace.as_uri(), "capabilities": {}}})
    while (frame := server.receive(FRAME_SECONDS)) is not None and frame.get("id") != 1:
        pass
    server.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    server.send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
        "textDocument": {"uri": main_uri, "languageId": "dawn", "version": 1,
                         "text": (workspace / "src" / "main.dawn").read_text()}}})
    published: dict[str, list[str]] = {}
    seen_main = False
    timeout = FRAME_SECONDS
    while (frame := server.receive(timeout)) is not None:
        if frame.get("method") == "textDocument/publishDiagnostics":
            params = frame["params"]
            published[params["uri"]] = [d["message"] for d in params["diagnostics"]]
            if params["uri"] == main_uri:
                seen_main = True
        if seen_main:
            timeout = SETTLE_SECONDS  # the rest of the same burst, then stop waiting
    server.send({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None})
    server.send({"jsonrpc": "2.0", "method": "exit", "params": {}})
    messages = published.get(hidden_uri, [])
    if not any(m.startswith("cannot list source directory") for m in messages):
        print(f"LSP_SILENT_ON_UNLISTABLE_DIR: published {published}")
        return 1
    print("loader-listdir lsp: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

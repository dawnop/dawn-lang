#!/usr/bin/env python3
"""Exercise one LSP document's captured module index across a manifest edit.

The first server opens a buffer while dependency alias ``dep`` selects package
A, waits until analysis publishes diagnostics, then changes the on-disk
manifest to package B before requesting selective-import completion. That
request must still read A. A new server session must read B.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time


TIMEOUT_SECONDS = 120
CAPTURED_MISMATCH = "CAPTURED_SESSION_MISMATCH"


class LspProcess:
    def __init__(self, command: list[str], cwd: Path) -> None:
        self.proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.buffer = b""

    def send(self, message: dict[str, object]) -> None:
        body = json.dumps(message, separators=(",", ":")).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()

    def receive(self) -> dict[str, object]:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        fd = self.proc.stdout.fileno()
        while True:
            boundary = self.buffer.find(b"\r\n\r\n")
            if boundary >= 0:
                header = self.buffer[:boundary].decode("ascii")
                length = None
                for line in header.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":", 1)[1].strip())
                if length is None:
                    raise RuntimeError("LSP frame omitted Content-Length")
                end = boundary + 4 + length
                if len(self.buffer) >= end:
                    body = self.buffer[boundary + 4 : end]
                    self.buffer = self.buffer[end:]
                    return json.loads(body)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("timed out waiting for LSP frame")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise RuntimeError("timed out waiting for LSP output")
            chunk = os.read(fd, 65536)
            if not chunk:
                stderr = self.stderr_text()
                raise RuntimeError(
                    f"LSP server closed before the expected frame\n{stderr}"
                )
            self.buffer += chunk

    def receive_until(self, predicate) -> dict[str, object]:
        while True:
            frame = self.receive()
            if predicate(frame):
                return frame

    def stderr_text(self) -> str:
        if self.proc.stderr is None:
            return ""
        if self.proc.poll() is None:
            return ""
        return self.proc.stderr.read().decode("utf-8", "replace")

    def close(self) -> None:
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            status = self.proc.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise RuntimeError("LSP server did not exit")
        if status != 0:
            raise RuntimeError(f"LSP server exited {status}\n{self.stderr_text()}")


def write_manifest(app: Path, package: str) -> None:
    (app / "dawn.toml").write_text(
        f'schema = 1\nname = "app"\n\n[deps]\ndep = "../{package}"\n'
    )


def setup_fixture(root: Path) -> Path:
    app = root / "app"
    (app / "src").mkdir(parents=True)
    (app / "src" / "main.dawn").write_text("pub fn main() -> Unit !io = ()\n")
    for package, name, exported in (
        ("a", "pkg_a", "alpha"),
        ("b", "pkg_b", "beta"),
    ):
        package_root = root / package
        (package_root / "src").mkdir(parents=True)
        (package_root / "dawn.toml").write_text(
            f'schema = 1\nname = "{name}"\n'
        )
        (package_root / "src" / "api.dawn").write_text(
            f"pub fn {exported}() -> Int = 1\n"
        )
    write_manifest(app, "a")
    return app


def labels(result: object) -> list[str]:
    if not isinstance(result, list):
        raise RuntimeError(f"completion result is not a list: {result!r}")
    return sorted(
        item["label"] for item in result if isinstance(item, dict) and "label" in item
    )


def complete_once(
    command: list[str], repo: Path, app: Path, mutate_after_open: bool
) -> list[str]:
    server = LspProcess(command, repo)
    uri = (app / "src" / "main.dawn").resolve().as_uri()
    text = "use dep/api.{"
    server.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}},
        }
    )
    server.receive_until(lambda frame: frame.get("id") == 1)
    server.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    server.send(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "dawn",
                    "version": 1,
                    "text": text + "\n",
                }
            },
        }
    )
    server.receive_until(
        lambda frame: frame.get("method") == "textDocument/publishDiagnostics"
        and isinstance(frame.get("params"), dict)
        and frame["params"].get("uri") == uri
    )
    if mutate_after_open:
        write_manifest(app, "b")
    server.send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": len(text)},
            },
        }
    )
    response = server.receive_until(lambda frame: frame.get("id") == 2)
    server.send(
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None}
    )
    server.receive_until(lambda frame: frame.get("id") == 3)
    server.send({"jsonrpc": "2.0", "method": "exit", "params": {}})
    server.close()
    return labels(response.get("result"))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: completion.py <server command...>", file=sys.stderr)
        return 2
    repo = Path(__file__).resolve().parents[2]
    fixture = Path(tempfile.mkdtemp(prefix="dawn-project-plan-completion-"))
    try:
        app = setup_fixture(fixture)
        captured = complete_once(sys.argv[1:], repo, app, mutate_after_open=True)
        if captured != ["alpha"]:
            print(f"{CAPTURED_MISMATCH}: expected ['alpha']; got {captured}")
            return 1
        fresh = complete_once(sys.argv[1:], repo, app, mutate_after_open=False)
        if fresh != ["beta"]:
            print(f"FRESH_SESSION_MISMATCH: expected ['beta']; got {fresh}")
            return 1
        print("completion-consistency: OK")
        return 0
    finally:
        shutil.rmtree(fixture)


if __name__ == "__main__":
    sys.exit(main())

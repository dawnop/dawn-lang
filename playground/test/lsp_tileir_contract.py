#!/usr/bin/env python3
"""The Playground's language service resolves `use tileir/` like /run does.

The gateway (lsp_gateway.py) opens a buffer that imports tileir as the main file
of playground/lsp-tile, whose manifest names the two packages the runner's does,
and every other buffer as the untitled document it always was. This drives the
REAL language server (`dawn lsp`, not the fake child of lsp_contract.py) through
the gateway, with the browser's own URI, because the fake cannot say whether
`use tileir/dev` resolves.

Cases: the flash attention starter has no diagnostics and hover works on a
tileir name; a program that does not import tileir is analysed as before; a
dependency the visitor writes into the program is still refused (the manifest
is the gateway's); a buffer that becomes a tileir program, and stops being one,
is followed in both directions; a gateway without the project reproduces the
false errors this exists to remove (the negative control).
"""

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import lsp_contract as c  # noqa: E402  (the fake-child contract's WebSocket client)

SAMPLE = os.path.join(ROOT, "site", "play-ui", "samples", "flash_attn.dawn")
PLAIN_ERROR = "pub fn main() -> Unit !io = println(nope)\n"
URI = c.URI
STEP_SECONDS = 60


def read_sample():
    with open(SAMPLE, encoding="utf-8") as stream:
        return stream.read()


def start_gateway(port, log_path, *, tile_main):
    env = dict(os.environ)
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PLAY_LSP_HOST": "127.0.0.1",
        "PLAY_LSP_PORT": str(port),
        "PLAY_LSP_ORIGINS": c.ORIGIN,
        "PLAY_LSP_MAX_SESSIONS": "1",
        "PLAY_LSP_IDLE_SECONDS": "120",
        "PLAY_LSP_LIFETIME_SECONDS": "170",
        "PLAY_LSP_SETUP_SECONDS": "15",
        "PLAY_LSP_HANDSHAKE_SECONDS": "5",
        "PLAY_LSP_UNSAFE_LOCAL": "1",
        "PLAY_LSP_CHILD": "%s lsp" % shlex.quote(os.path.join(ROOT, "bin", "dawn")),
        "PLAY_LSP_TILE_MAIN": tile_main,
    })
    gateway = subprocess.Popen(
        [sys.executable, "-B", os.environ.get("PLAY_LSP_TEST_GATEWAY", c.GATEWAY)],
        cwd=ROOT, env=env, stdout=open(log_path, "wb"), stderr=subprocess.STDOUT,
    )
    return gateway


class Session:
    def __init__(self, port):
        stream, response = c.upgrade_when_available(port, timeout=10)
        stream.settimeout(STEP_SECONDS)
        self.ws = c.WebSocket(stream)
        self.next_id = 1
        self.version = 0
        self.ws.send_json(c.rpc(0, "initialize", {"capabilities": {}}))
        reply = self.until(lambda m: m.get("id") == 0)
        assert "capabilities" in reply.get("result", {}), reply
        self.ws.send_json(c.note("initialized", {}))

    def until(self, predicate):
        while True:
            message = c.recv_reply(self.ws, "tileir contract")
            if predicate(message):
                return message

    def open(self, text):
        self.version += 1
        self.ws.send_json(c.note("textDocument/didOpen", {"textDocument": {
            "uri": URI, "languageId": "dawn", "version": self.version, "text": text}}))

    def change(self, text):
        self.version += 1
        self.ws.send_json(c.note("textDocument/didChange", {
            "textDocument": {"uri": URI, "version": self.version},
            "contentChanges": [{"text": text}]}))

    def diagnostics(self):
        """The diagnostics the server publishes for the current version."""
        want = self.version
        message = self.until(
            lambda m: m.get("method") == "textDocument/publishDiagnostics"
            and m["params"].get("version", want) == want)
        assert message["params"]["uri"] == URI, message
        return message["params"]["diagnostics"]

    def hover_at(self, text, needle):
        line, column = next(
            (i, row.index(needle) + 1)
            for i, row in enumerate(text.split("\n")) if needle in row)
        self.next_id += 1
        ident = self.next_id
        self.ws.send_json(c.rpc(ident, "textDocument/hover", {
            "textDocument": {"uri": URI}, "position": {"line": line, "character": column}}))
        return self.until(lambda m: m.get("id") == ident).get("result")

    def close(self):
        self.ws.close()


def messages(diagnostics):
    return " | ".join(d["message"].split("\n")[0] for d in diagnostics)


def with_gateway(tile_main, body):
    port = c.free_port()
    with tempfile.TemporaryDirectory() as work:
        log_path = os.path.join(work, "gateway.log")
        gateway = start_gateway(port, log_path, tile_main=tile_main)
        try:
            c.wait_until(lambda: gateway.poll() is None and _listening(port), timeout=20)
            session = Session(port)
            try:
                body(session)
            finally:
                session.close()
        finally:
            gateway.terminate()
            try:
                gateway.wait(timeout=10)
            except subprocess.TimeoutExpired:
                gateway.kill()
                gateway.wait(timeout=5)


def _listening(port):
    import socket
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
        return True
    except OSError:
        return False


def main():
    sample = read_sample()
    tile_main = os.path.join(ROOT, "playground", "lsp-tile", "src", "main.dawn")
    assert os.path.isfile(tile_main), tile_main

    # the project's manifest names exactly the runner's two packages
    with open(os.path.join(ROOT, "playground", "lsp-tile", "dawn.toml"), encoding="utf-8") as stream:
        manifest = stream.read()
    deps = [line.split("=")[0].strip() for line in manifest.split("[deps]", 1)[1].split("\n") if "=" in line]
    assert deps == ["tileir", "tileref"], deps
    c.ok("the language service's project names the runner's two packages and no others")

    def flow(session):
        # a tileir program: no false errors, and hover knows a tileir name
        session.open(sample)
        found = session.diagnostics()
        assert found == [], ("TILEIR_FALSE_ERRORS", messages(found))
        c.ok("the flash attention starter has no diagnostics")
        hover = session.hover_at(sample, "load_cell(q)")
        assert hover and "load_cell" in json.dumps(hover), ("TILEIR_HOVER", hover)
        c.ok("hover answers on a tileir name")

        # a dependency the visitor writes is not honoured: json is not in the manifest
        session.change("use json/value.{Json}\n" + sample)
        found = session.diagnostics()
        assert found and "json" in messages(found), ("SMUGGLED_DEPENDENCY_RESOLVED", messages(found))
        c.ok("a dependency written into the program does not resolve")

        # the buffer stops being a tileir program: analysed as the untitled buffer it was
        session.change(PLAIN_ERROR)
        found = session.diagnostics()
        assert found and "nope" in messages(found) and "tileir" not in messages(found), messages(found)
        c.ok("a program that does not import tileir is analysed as before")

        # and becomes one again
        session.change(sample)
        found = session.diagnostics()
        assert found == [], ("TILEIR_FALSE_ERRORS_AFTER_SWITCH", messages(found))
        assert session.hover_at(sample, "load_cell(q)"), "hover after switching back"
        c.ok("a buffer that becomes a tileir program, again, resolves it")

    with_gateway(tile_main, flow)

    # the negative control: no project, the old behaviour, false errors
    def old(session):
        session.open(sample)
        found = session.diagnostics()
        assert len(found) > 0, "the control did not reproduce the false errors"
        c.ok("without the project the same starter is full of false errors (control)")

    with_gateway("", old)
    print("----")
    print("tileir language service: passed")


if __name__ == "__main__":
    main()

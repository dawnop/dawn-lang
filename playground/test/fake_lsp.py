#!/usr/bin/env python3
"""Small deterministic stdio LSP used only by the gateway contract."""

import json
import os
import sys


DOCUMENT_URI = "untitled:dawn-playground/prog.dawn"
AUDIT = os.environ.get("FAKE_LSP_AUDIT")
DIAGNOSTIC_VERSION = 1_000_003
OMIT_DIAGNOSTIC_VERSION = os.environ.get(
    "FAKE_LSP_OMIT_DIAGNOSTIC_VERSION"
) == "1"


def audit(message):
    if AUDIT:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(AUDIT, "a", encoding="utf-8") as stream:
            stream.write(line)


def read_message():
    header = bytearray()
    while not header.endswith(b"\r\n\r\n"):
        one = sys.stdin.buffer.read(1)
        if not one:
            return None
        header.extend(one)
        if len(header) > 8192:
            raise RuntimeError("oversized header")
    length = None
    for line in bytes(header[:-4]).split(b"\r\n"):
        name, separator, value = line.partition(b":")
        if separator and name.lower() == b"content-length":
            length = int(value.strip())
    if length is None or length > 262144:
        raise RuntimeError("bad Content-Length")
    body = sys.stdin.buffer.read(length)
    if len(body) != length:
        raise RuntimeError("truncated body")
    return json.loads(body)


def send(message):
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()


def location(uri):
    return {
        "uri": uri,
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 3},
        },
    }


def publish():
    params = {
        # Deliberately unrelated to the browser's 1, 2, ... versions.  The
        # gateway contract must observe this exact child value rather than
        # reconstructing a plausible one from client state.
        "version": DIAGNOSTIC_VERSION,
        "uri": DOCUMENT_URI,
        "diagnostics": [{
            "range": location(DOCUMENT_URI)["range"],
            "severity": 2,
            "source": "fake-dawnc",
            "message": "contract diagnostic",
            "data": {"privatePath": "/tmp/should-not-cross"},
            "relatedInformation": [{
                "location": location("file:///etc/passwd"),
                "message": "outside the scratch buffer",
            }],
        }],
    }
    if OMIT_DIAGNOSTIC_VERSION:
        del params["version"]
    send({
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": params,
    })


def main():
    # This canary models compiler stderr containing submitted source.  The
    # gateway contract asserts that the gateway logs only the byte count.
    sys.stderr.write("SOURCE_CANARY_MUST_NOT_APPEAR\n")
    sys.stderr.flush()
    shutdown = False
    while True:
        message = read_message()
        if message is None:
            return 0
        audit(message)
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": 1,
                        "completionProvider": {},
                        "hoverProvider": True,
                        "definitionProvider": True,
                        "documentSymbolProvider": True,
                        "documentFormattingProvider": True,
                    }
                },
            })
        elif method == "initialized":
            pass
        elif method in {"textDocument/didOpen", "textDocument/didChange"}:
            params = message.get("params", {})
            if method == "textDocument/didOpen":
                text = params.get("textDocument", {}).get("text")
            else:
                changes = params.get("contentChanges", [])
                text = changes[0].get("text") if changes else None
            if text == "MALFORMED_CHILD_FRAME":
                sys.stdout.buffer.write(b"Content-Length: nope\r\n\r\n")
                sys.stdout.buffer.flush()
            else:
                publish()
        elif method == "textDocument/completion":
            if message.get("params", {}).get("position", {}).get("line") == 99:
                # Let the contract fill the gateway's pending-request budget.
                continue
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": [{"label": "println", "kind": 3}],
            })
        elif method == "textDocument/hover":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"contents": {"kind": "plaintext", "value": "Int"}},
            })
        elif method == "textDocument/definition":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": [location(DOCUMENT_URI), location("file:///etc/passwd")],
            })
        elif method == "shutdown":
            shutdown = True
            send({"jsonrpc": "2.0", "id": request_id, "result": None})
        elif method == "exit":
            return 0 if shutdown else 1
        elif request_id is not None:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            })


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        sys.stderr.write("fake-lsp failure: %s\n" % type(error).__name__)
        raise

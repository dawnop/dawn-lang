#!/usr/bin/env python3
"""Bounded production smoke for gateway -> sandbox -> native dawnc LSP."""

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import time


HOST = "127.0.0.1"
PORT = int(os.environ.get("PLAY_LSP_SMOKE_PORT", "8088"))
ORIGIN = os.environ.get("PLAY_LSP_SMOKE_ORIGIN", "https://dawn-lang.dawnop.com")
PROTOCOL = "dawn-lsp-v1"
URI = "untitled:dawn-playground/prog.dawn"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME_BYTES = 262_144
BUSY_ATTEMPTS = 5
BUSY_RETRY_SECONDS = 2
SMOKE_SECONDS = 30

if "\r" in ORIGIN or "\n" in ORIGIN:
    raise SystemExit("PLAY_LSP_SMOKE_ORIGIN must be one HTTP Origin")
try:
    ORIGIN.encode("ascii")
except UnicodeEncodeError as error:
    raise SystemExit("PLAY_LSP_SMOKE_ORIGIN must be ASCII") from error


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("deploy smoke exceeded its 30-second deadline")
    return seconds


def exact(stream, size, deadline):
    out = bytearray()
    while len(out) < size:
        stream.settimeout(remaining(deadline))
        part = stream.recv(size - len(out))
        if not part:
            raise RuntimeError("WebSocket closed inside a frame")
        out.extend(part)
    return bytes(out)


def send_frame(stream, opcode, payload=b"", deadline=None):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    mask = secrets.token_bytes(4)
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, 0x80 | length))
    elif length <= 0xFFFF:
        header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
    masked = bytes(value ^ mask[index & 3] for index, value in enumerate(payload))
    if deadline is not None:
        stream.settimeout(remaining(deadline))
    stream.sendall(header + mask + masked)


def send_json(stream, message, deadline):
    send_frame(
        stream,
        1,
        json.dumps(message, separators=(",", ":")),
        deadline,
    )


def read_frame(stream, deadline):
    first, second = exact(stream, 2, deadline)
    if not first & 0x80 or first & 0x70 or second & 0x80:
        raise RuntimeError("invalid server WebSocket frame")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", exact(stream, 2, deadline))[0]
    elif length == 127:
        length = struct.unpack("!Q", exact(stream, 8, deadline))[0]
    if length > MAX_FRAME_BYTES:
        raise RuntimeError("oversized server WebSocket frame")
    return first & 0x0F, exact(stream, length, deadline)


def read_json(stream, deadline):
    while True:
        opcode, payload = read_frame(stream, deadline)
        if opcode == 9:
            send_frame(stream, 10, payload, deadline)
            continue
        if opcode == 8:
            code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
            raise RuntimeError("gateway closed before smoke completed (%d)" % code)
        if opcode != 1:
            raise RuntimeError("gateway sent a non-text data frame")
        return json.loads(payload)


def rpc(request_id, method, params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


class GatewayBusy(RuntimeError):
    """The bounded gateway has no free native-process slot yet."""


def smoke_once():
    deadline = time.monotonic() + SMOKE_SECONDS
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    request = (
        "GET /lsp HTTP/1.1\r\n"
        "Host: dawn-lang.dawnop.com\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Origin: %s\r\n"
        "Sec-WebSocket-Protocol: %s\r\n\r\n"
    ) % (key, ORIGIN, PROTOCOL)

    with socket.create_connection(
        (HOST, PORT), timeout=min(10, remaining(deadline))
    ) as stream:
        stream.settimeout(remaining(deadline))
        stream.sendall(request.encode("ascii"))
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            header.extend(exact(stream, 1, deadline))
            if len(header) > 8192:
                raise RuntimeError("oversized WebSocket upgrade response")
        if header.startswith(b"HTTP/1.1 503 "):
            raise GatewayBusy("gateway has no free LSP session")
        if not header.startswith(b"HTTP/1.1 101 "):
            raise RuntimeError("gateway refused smoke: %r" % bytes(header).split(b"\r\n", 1)[0])
        digest = hashlib.sha1(
            (key + GUID).encode("ascii"), usedforsecurity=False
        ).digest()
        expected = base64.b64encode(digest)
        if b"Sec-WebSocket-Accept: " + expected + b"\r\n" not in header:
            raise RuntimeError("gateway returned the wrong WebSocket accept")
        if b"Sec-WebSocket-Protocol: dawn-lsp-v1\r\n" not in header:
            raise RuntimeError("gateway did not negotiate dawn-lsp-v1")

        send_json(stream, rpc(1, "initialize", {"capabilities": {}}), deadline)
        initialized = read_json(stream, deadline)
        if initialized.get("id") != 1 or not isinstance(
            initialized.get("result", {}).get("capabilities"), dict
        ):
            raise RuntimeError("native LSP initialize failed")
        send_json(
            stream,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            deadline,
        )
        send_json(stream, {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": URI,
                    "languageId": "dawn",
                    "version": 1,
                    "text": "pub fn main() -> Unit = ()",
                }
            },
        }, deadline)
        diagnostics = read_json(stream, deadline)
        if (
            diagnostics.get("method") != "textDocument/publishDiagnostics"
            or diagnostics.get("params", {}).get("uri") != URI
            or not isinstance(diagnostics.get("params", {}).get("diagnostics"), list)
        ):
            raise RuntimeError("native LSP diagnostics failed")
        send_frame(stream, 8, struct.pack("!H", 1000), deadline)
        opcode, payload = read_frame(stream, deadline)
        if opcode != 8 or len(payload) < 2 or struct.unpack("!H", payload[:2])[0] != 1000:
            raise RuntimeError("gateway did not complete the close handshake")


def main():
    # A deploy smoke may race a browser reconnect after systemd becomes
    # active.  Retry only the gateway's explicit busy response, for at most
    # eight seconds; every protocol/native failure remains fail-fast.
    for attempt in range(BUSY_ATTEMPTS):
        try:
            smoke_once()
            print("dawn-play-lsp smoke ok")
            return
        except GatewayBusy:
            if attempt + 1 == BUSY_ATTEMPTS:
                raise RuntimeError("gateway remained busy during deploy smoke") from None
            time.sleep(BUSY_RETRY_SECONDS)


if __name__ == "__main__":
    main()

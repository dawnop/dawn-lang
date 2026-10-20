#!/usr/bin/env python3
"""Bounded production smoke for gateway -> sandbox -> native dawnc LSP."""

import base64
import hashlib
import importlib.util
import json
import os
import secrets
import socket
import struct
import sys
import time
import urllib.parse
from pathlib import Path


def _site_origin():
    """DAWN_SITE_ORIGIN, from the environment or scripts/repo.env.

    Loaded by path: this runs as `python3 -I` from /opt/dawn/playground/deploy,
    and redeploy.sh ships scripts/repo_env.py and scripts/repo.env to the
    deployed root, laid out like the repository.
    """
    path = Path(__file__).resolve().parents[2] / "scripts" / "repo_env.py"
    spec = importlib.util.spec_from_file_location("repo_env", path)
    if spec is None or spec.loader is None or not path.is_file():
        raise SystemExit(f"{path} is missing; redeploy.sh ships it")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.site_origin()


HOST = "127.0.0.1"
PORT = int(os.environ.get("PLAY_LSP_SMOKE_PORT", "8088"))
SITE_ORIGIN = _site_origin()
# nginx routes /api/lsp by the site's server_name, whatever Origin is sent.
SITE_HOST = urllib.parse.urlsplit(SITE_ORIGIN).hostname
ORIGIN = os.environ.get("PLAY_LSP_SMOKE_ORIGIN", SITE_ORIGIN)
PROTOCOL = "dawn-lsp-v1"
URI = "untitled:dawn-playground/prog.dawn"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME_BYTES = 262_144
BUSY_ATTEMPTS = 5
BUSY_RETRY_SECONDS = 2
SMOKE_SECONDS = 30
# `systemctl is-active` reports a Type=simple unit active once python3 is
# exec'd, before asyncio.start_server() has bound the port; the v0.95.0 deploy
# smoke hit that window and was refused. So a refused or timed-out connect is
# retried with exponential backoff for this long; the override exists for the
# contract test's bounded-failure case and is clamped to (0, 60].
CONNECT_SECONDS = min(60.0, float(os.environ.get("PLAY_LSP_SMOKE_CONNECT_SECONDS", "10")))
CONNECT_FIRST_BACKOFF = 0.1
if not CONNECT_SECONDS > 0:
    raise SystemExit("PLAY_LSP_SMOKE_CONNECT_SECONDS must be positive")

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


def connect():
    """Connect to the gateway, retrying only refusal and connect timeout.

    Anything after the TCP connect (handshake, child, diagnostics) stays
    fail-fast in smoke_once(). Retries are logged on stderr so the success
    line on stdout is unchanged.
    """
    give_up = time.monotonic() + CONNECT_SECONDS
    backoff = CONNECT_FIRST_BACKOFF
    retries = 0
    while True:
        left = give_up - time.monotonic()
        try:
            stream = socket.create_connection(
                (HOST, PORT), timeout=max(0.05, min(10, left))
            )
        except (ConnectionRefusedError, TimeoutError) as error:
            left = give_up - time.monotonic()
            if left <= 0:
                raise RuntimeError(
                    "gateway not accepting on %s:%d after %d connect retries "
                    "in %gs: %s" % (HOST, PORT, retries, CONNECT_SECONDS, error)
                ) from None
            pause = min(backoff, left)
            retries += 1
            print(
                "dawn-play-lsp smoke: connect retry %d in %.2fs (%s)"
                % (retries, pause, type(error).__name__),
                file=sys.stderr,
                flush=True,
            )
            time.sleep(pause)
            backoff *= 2
            continue
        if retries:
            print(
                "dawn-play-lsp smoke: connected after %d connect retries" % retries,
                file=sys.stderr,
                flush=True,
            )
        return stream


def smoke_once():
    stream = connect()
    deadline = time.monotonic() + SMOKE_SECONDS
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    request = (
        "GET /lsp HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Origin: %s\r\n"
        "Sec-WebSocket-Protocol: %s\r\n\r\n"
    ) % (SITE_HOST, key, ORIGIN, PROTOCOL)

    with stream:
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
    # active.  Retry the gateway's explicit busy response for at most eight
    # seconds, and (in connect()) a not-yet-listening port for CONNECT_SECONDS;
    # every protocol/native failure remains fail-fast.
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

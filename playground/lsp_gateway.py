#!/usr/bin/env python3
"""Bounded WebSocket-to-stdio bridge for the Playground's native LSP.

One accepted WebSocket owns one ``dawnc lsp`` process.  This file deliberately
does not turn the LSP server into a multi-tenant process: the process boundary
is the session boundary, so request ids, lifecycle state and diagnostics can
never be routed to another browser by mistake.

There is no server-side WebSocket API in the JDK used by ``packages/web`` and
the repository has no pinned WebSocket dependency.  The gateway therefore
implements only the small RFC 6455 server surface it needs, in the Python
standard library already used by the repository's deployment checks:

* one bounded HTTP upgrade on a loopback listener;
* masked text messages, fragmentation, ping/pong and close;
* no extensions, binary messages, cookies or application-level sessions.

Every public limit has a hard ceiling below.  Environment variables are
range-checked, and the production unit pins the intended public policy.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import logging
import math
import os
import secrets
import shlex
import signal
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any, NoReturn


LOG = logging.getLogger("dawn-play-lsp")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SUBPROTOCOL = "dawn-lsp-v1"
DOCUMENT_URI = "untitled:dawn-playground/prog.dawn"

HARD_MAX_SESSIONS = 2
HARD_SOURCE_BYTES = 65_536
HARD_MESSAGE_BYTES = 262_144
HARD_HEADER_BYTES = 8_192
HARD_IDLE_SECONDS = 600
HARD_LIFETIME_SECONDS = 1_800
HARD_SETUP_SECONDS = 15
HARD_HANDSHAKES = 32
HARD_FRAMES_PER_MESSAGE = 64
HARD_CONTROL_FRAMES_PER_MESSAGE = 32
HARD_PENDING_REQUESTS = 16
HARD_MESSAGES_PER_SESSION = 20_000
HARD_IO_SECONDS = 5
MESSAGE_BURST = 64.0
MESSAGE_RATE_PER_SECOND = 10.0

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8088
DEFAULT_MAX_SESSIONS = 2
DEFAULT_SOURCE_BYTES = HARD_SOURCE_BYTES
DEFAULT_MESSAGE_BYTES = HARD_MESSAGE_BYTES
DEFAULT_IDLE_SECONDS = HARD_IDLE_SECONDS
DEFAULT_LIFETIME_SECONDS = HARD_LIFETIME_SECONDS
DEFAULT_SETUP_SECONDS = HARD_SETUP_SECONDS
DEFAULT_HANDSHAKE_SECONDS = 5
DEFAULT_PING_SECONDS = 30
DEFAULT_SHUTDOWN_SECONDS = 2
DEFAULT_ORIGINS = ("https://dawn-lang.dawnop.com",)
DEFAULT_SANDBOX = "/opt/dawn/playground/sandbox/run-lsp-sandboxed.sh"
HTTP_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&'*+-.^_`|~"
)
MAX_JSONRPC_INTEGER = 9_007_199_254_740_991


class GatewayError(Exception):
    """A client protocol failure that becomes a WebSocket close."""

    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class ChildProtocolError(Exception):
    """The child stopped speaking bounded LSP framing/JSON."""


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise SystemExit(f"{name} must be in {minimum}..{maximum}, got {value}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise SystemExit(f"{name} must be 0 or 1, got {raw!r}")


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    origins: frozenset[str]
    max_sessions: int
    source_bytes: int
    message_bytes: int
    idle_seconds: int
    lifetime_seconds: int
    setup_seconds: int
    handshake_seconds: int
    ping_seconds: int
    shutdown_seconds: int
    unsafe_local: bool
    child_argv: tuple[str, ...]
    sandbox_script: str

    @staticmethod
    def from_env() -> "Config":
        origins_raw = os.environ.get("PLAY_LSP_ORIGINS", ",".join(DEFAULT_ORIGINS))
        origins = frozenset(item.strip() for item in origins_raw.split(",") if item.strip())
        if not origins:
            raise SystemExit("PLAY_LSP_ORIGINS must name at least one exact Origin")

        unsafe = _env_bool("PLAY_LSP_UNSAFE_LOCAL")
        child_raw = os.environ.get("PLAY_LSP_CHILD", "")
        if unsafe:
            if not child_raw:
                raise SystemExit("PLAY_LSP_UNSAFE_LOCAL=1 requires PLAY_LSP_CHILD")
            child_argv = tuple(shlex.split(child_raw))
            if not child_argv:
                raise SystemExit("PLAY_LSP_CHILD is empty")
        else:
            if child_raw:
                raise SystemExit("PLAY_LSP_CHILD is only allowed with PLAY_LSP_UNSAFE_LOCAL=1")
            child_argv = ()

        host = os.environ.get("PLAY_LSP_HOST", DEFAULT_HOST)
        if host not in {"127.0.0.1", "::1"}:
            raise SystemExit("PLAY_LSP_HOST must be a numeric loopback address")
        sandbox_script = os.environ.get("PLAY_LSP_SANDBOX_SCRIPT", DEFAULT_SANDBOX)
        if not unsafe and (
            not os.path.isabs(sandbox_script)
            or not os.path.isfile(sandbox_script)
            or not os.access(sandbox_script, os.X_OK)
        ):
            raise SystemExit(
                "PLAY_LSP_SANDBOX_SCRIPT must be an absolute executable file"
            )

        return Config(
            host=host,
            port=_env_int("PLAY_LSP_PORT", DEFAULT_PORT, minimum=1, maximum=65_535),
            origins=origins,
            max_sessions=_env_int(
                "PLAY_LSP_MAX_SESSIONS",
                DEFAULT_MAX_SESSIONS,
                minimum=1,
                maximum=HARD_MAX_SESSIONS,
            ),
            source_bytes=_env_int(
                "PLAY_LSP_SOURCE_BYTES",
                DEFAULT_SOURCE_BYTES,
                minimum=1,
                maximum=HARD_SOURCE_BYTES,
            ),
            message_bytes=_env_int(
                "PLAY_LSP_MESSAGE_BYTES",
                DEFAULT_MESSAGE_BYTES,
                minimum=1_024,
                maximum=HARD_MESSAGE_BYTES,
            ),
            idle_seconds=_env_int(
                "PLAY_LSP_IDLE_SECONDS",
                DEFAULT_IDLE_SECONDS,
                minimum=1,
                maximum=HARD_IDLE_SECONDS,
            ),
            lifetime_seconds=_env_int(
                "PLAY_LSP_LIFETIME_SECONDS",
                DEFAULT_LIFETIME_SECONDS,
                minimum=2,
                maximum=HARD_LIFETIME_SECONDS,
            ),
            setup_seconds=_env_int(
                "PLAY_LSP_SETUP_SECONDS",
                DEFAULT_SETUP_SECONDS,
                minimum=1,
                maximum=HARD_SETUP_SECONDS,
            ),
            handshake_seconds=_env_int(
                "PLAY_LSP_HANDSHAKE_SECONDS",
                DEFAULT_HANDSHAKE_SECONDS,
                minimum=1,
                maximum=30,
            ),
            ping_seconds=_env_int(
                "PLAY_LSP_PING_SECONDS",
                DEFAULT_PING_SECONDS,
                minimum=1,
                maximum=60,
            ),
            shutdown_seconds=_env_int(
                "PLAY_LSP_SHUTDOWN_SECONDS",
                DEFAULT_SHUTDOWN_SECONDS,
                minimum=1,
                maximum=10,
            ),
            unsafe_local=unsafe,
            child_argv=child_argv,
            sandbox_script=sandbox_script,
        )


@dataclass(frozen=True)
class Upgrade:
    key: str
    origin: str


def _header_tokens(values: list[str]) -> set[str]:
    return {
        token.strip().lower()
        for value in values
        for token in value.split(",")
        if token.strip()
    }


def _header_items(values: list[str]) -> list[str]:
    return [
        token.strip()
        for value in values
        for token in value.split(",")
        if token.strip()
    ]


def _one(headers: dict[str, list[str]], name: str) -> str:
    values = headers.get(name, [])
    if len(values) != 1:
        raise ValueError(f"expected one {name} header")
    return values[0]


def parse_upgrade(block: bytes, config: Config) -> Upgrade:
    """Parse one already-bounded HTTP/1.1 WebSocket upgrade."""

    try:
        text = block.decode("iso-8859-1")
    except UnicodeDecodeError as exc:  # latin-1 is total; kept as an invariant
        raise ValueError("header is not ISO-8859-1") from exc
    lines = text.split("\r\n")
    if len(lines) < 3 or lines[-2:] != ["", ""]:
        raise ValueError("incomplete HTTP header")
    request = lines[0].split(" ")
    if request != ["GET", "/lsp", "HTTP/1.1"]:
        raise ValueError("expected GET /lsp HTTP/1.1")

    headers: dict[str, list[str]] = {}
    for line in lines[1:-2]:
        if not line or line[0] in " \t" or ":" not in line:
            raise ValueError("malformed HTTP header line")
        name, value = line.split(":", 1)
        if not name or any(ch not in HTTP_TOKEN_CHARS for ch in name):
            raise ValueError("malformed HTTP header name")
        headers.setdefault(name.lower(), []).append(value.strip(" \t"))

    if not _one(headers, "host"):
        raise ValueError("missing Host")
    if _header_tokens(headers.get("upgrade", [])) != {"websocket"}:
        raise ValueError("missing WebSocket Upgrade")
    if "upgrade" not in _header_tokens(headers.get("connection", [])):
        raise ValueError("missing Connection: Upgrade")
    if _one(headers, "sec-websocket-version") != "13":
        raise ValueError("WebSocket version must be 13")
    origin = _one(headers, "origin")
    if origin not in config.origins:
        raise PermissionError("Origin is not allowed")
    # WebSocket subprotocol names are case-sensitive (unlike HTTP field names
    # and the Upgrade/Connection tokens checked above).
    if SUBPROTOCOL not in _header_items(headers.get("sec-websocket-protocol", [])):
        raise PermissionError(f"{SUBPROTOCOL} subprotocol is required")
    if "content-length" in headers or "transfer-encoding" in headers:
        raise ValueError("upgrade request must not carry a body")

    key = _one(headers, "sec-websocket-key")
    try:
        decoded = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid Sec-WebSocket-Key") from exc
    if len(decoded) != 16:
        raise ValueError("Sec-WebSocket-Key must decode to 16 bytes")
    return Upgrade(key=key, origin=origin)


async def read_upgrade(reader: asyncio.StreamReader, config: Config) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        if len(data) >= HARD_HEADER_BYTES:
            raise ValueError("HTTP header exceeds 8192 bytes")
        piece = await reader.read(min(1024, HARD_HEADER_BYTES - len(data)))
        if not piece:
            raise ValueError("EOF during HTTP header")
        data.extend(piece)
    end = data.index(b"\r\n\r\n") + 4
    if end != len(data):
        # A browser sends no bytes after the upgrade until it has received 101.
        # Refusing pipelined bytes keeps the protocol boundary unambiguous.
        raise ValueError("bytes followed the WebSocket upgrade")
    return bytes(data)


async def http_reply(
    writer: asyncio.StreamWriter,
    status: int,
    reason: str,
    body: str,
    *,
    retry_after: int | None = None,
) -> None:
    payload = body.encode("utf-8")
    lines = [
        f"HTTP/1.1 {status} {reason}\r\n",
        "Connection: close\r\n",
        "Content-Type: text/plain; charset=utf-8\r\n",
        f"Content-Length: {len(payload)}\r\n",
    ]
    if retry_after is not None:
        lines.append(f"Retry-After: {retry_after}\r\n")
    lines.append("\r\n")
    writer.write("".join(lines).encode("ascii") + payload)
    await asyncio.wait_for(writer.drain(), timeout=HARD_IO_SECONDS)


async def accept_upgrade(writer: asyncio.StreamWriter, upgrade: Upgrade) -> None:
    # RFC 6455 mandates SHA-1 here as a protocol checksum, not for security.
    digest = hashlib.sha1(
        (upgrade.key + WS_GUID).encode("ascii"), usedforsecurity=False
    ).digest()
    accept = base64.b64encode(digest).decode("ascii")
    writer.write(
        (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            f"Sec-WebSocket-Protocol: {SUBPROTOCOL}\r\n"
            "\r\n"
        ).encode("ascii")
    )
    await asyncio.wait_for(writer.drain(), timeout=HARD_IO_SECONDS)


class WebSocket:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        max_message: int,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.max_message = max_message
        self._write_lock = asyncio.Lock()
        self._closed = False
        self.last_pong = time.monotonic()

    async def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        if len(payload) < 126:
            header = bytes((0x80 | opcode, len(payload)))
        elif len(payload) <= 0xFFFF:
            header = bytes((0x80 | opcode, 126)) + struct.pack("!H", len(payload))
        else:
            header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", len(payload))
        async with self._write_lock:
            if self._closed and opcode != 0x8:
                return
            self.writer.write(header + payload)
            await asyncio.wait_for(self.writer.drain(), timeout=HARD_IO_SECONDS)

    async def send_text(self, body: bytes) -> None:
        if len(body) > self.max_message:
            raise ChildProtocolError("child JSON exceeds gateway message cap")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ChildProtocolError("child JSON is not UTF-8") from exc
        await self._send_frame(0x1, body)

    async def send_ping(self) -> None:
        await self._send_frame(0x9, b"dawn")

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        safe = reason.encode("utf-8")[:123]
        # Never cut in the middle of a UTF-8 sequence.
        safe = safe.decode("utf-8", errors="ignore").encode("utf-8")
        try:
            await self._send_frame(0x8, struct.pack("!H", code) + safe)
        except (ConnectionError, BrokenPipeError, asyncio.TimeoutError):
            pass

    async def _read_frame(self) -> tuple[bool, int, bytes]:
        first = await self.reader.readexactly(2)
        b0, b1 = first
        fin = bool(b0 & 0x80)
        if b0 & 0x70:
            raise GatewayError(1002, "WebSocket extensions are disabled")
        opcode = b0 & 0x0F
        if not b1 & 0x80:
            raise GatewayError(1002, "client frames must be masked")
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack("!H", await self.reader.readexactly(2))[0]
            if length < 126:
                raise GatewayError(1002, "non-minimal WebSocket length")
        elif length == 127:
            raw = await self.reader.readexactly(8)
            if raw[0] & 0x80:
                raise GatewayError(1002, "invalid WebSocket length")
            length = struct.unpack("!Q", raw)[0]
            if length < 65_536:
                raise GatewayError(1002, "non-minimal WebSocket length")
        control = opcode >= 0x8
        if control and (not fin or length > 125):
            raise GatewayError(1002, "invalid WebSocket control frame")
        if length > self.max_message:
            raise GatewayError(1009, "WebSocket message is too large")
        mask = await self.reader.readexactly(4)
        payload = bytearray(await self.reader.readexactly(length))
        for index in range(length):
            payload[index] ^= mask[index & 3]
        return fin, opcode, bytes(payload)

    async def recv_text(self) -> bytes | None:
        opcode0: int | None = None
        parts: list[bytes] = []
        size = 0
        frames = 0
        control_frames = 0
        while True:
            fin, opcode, payload = await self._read_frame()
            frames += 1
            if frames > HARD_FRAMES_PER_MESSAGE:
                raise GatewayError(1008, "too many WebSocket frames")
            if opcode == 0x8:
                if len(payload) == 1:
                    raise GatewayError(1002, "invalid close payload")
                code = 1000
                reason = ""
                if payload:
                    code = struct.unpack("!H", payload[:2])[0]
                    if (
                        code < 1000
                        or code > 4999
                        or code in {1004, 1005, 1006, 1015}
                        or 1016 <= code <= 2999
                    ):
                        raise GatewayError(1002, "invalid close code")
                    try:
                        reason = payload[2:].decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise GatewayError(1007, "close reason is not UTF-8") from exc
                await self.close(code, reason)
                return None
            if opcode == 0x9:
                control_frames += 1
                if control_frames > HARD_CONTROL_FRAMES_PER_MESSAGE:
                    raise GatewayError(1008, "too many WebSocket control frames")
                await self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                control_frames += 1
                if control_frames > HARD_CONTROL_FRAMES_PER_MESSAGE:
                    raise GatewayError(1008, "too many WebSocket control frames")
                self.last_pong = time.monotonic()
                continue
            if opcode == 0x2:
                raise GatewayError(1003, "binary messages are not supported")
            if opcode == 0x1:
                if opcode0 is not None:
                    raise GatewayError(1002, "new data frame inside fragmented message")
                opcode0 = opcode
            elif opcode == 0x0:
                if opcode0 is None:
                    raise GatewayError(1002, "continuation without a data frame")
            else:
                raise GatewayError(1002, "unsupported WebSocket opcode")
            size += len(payload)
            if size > self.max_message:
                raise GatewayError(1009, "WebSocket message is too large")
            parts.append(payload)
            if fin:
                body = b"".join(parts)
                try:
                    body.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise GatewayError(1007, "text message is not UTF-8") from exc
                return body


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON field: {key}")
        out[key] = value
    return out


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-JSON numeric constant: {value}")


def _validate_json_value(value: Any) -> None:
    """Reject non-finite numbers and unpaired UTF-16 surrogates."""

    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
    elif isinstance(value, list):
        for item in value:
            _validate_json_value(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            key.encode("utf-8")
            _validate_json_value(item)


def parse_json(body: bytes, *, client: bool) -> dict[str, Any]:
    try:
        value = json.loads(
            body,
            object_pairs_hook=_no_duplicate_object,
            parse_constant=_reject_json_constant,
        )
        _validate_json_value(value)
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        if client:
            raise GatewayError(1007, "message is not strict JSON") from exc
        raise ChildProtocolError("child emitted invalid JSON") from exc
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        if client:
            raise GatewayError(1008, "expected a JSON-RPC 2.0 object")
        raise ChildProtocolError("child emitted a non-JSON-RPC object")
    return value


def valid_id(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and abs(value) <= MAX_JSONRPC_INTEGER
    ) or (
        isinstance(value, str) and not value.startswith("gateway:") and len(value) <= 128
    )


def require_params(message: dict[str, Any]) -> dict[str, Any]:
    params = message.get("params")
    if not isinstance(params, dict):
        raise GatewayError(1008, "method params must be an object")
    return params


def require_document(params: dict[str, Any]) -> dict[str, Any]:
    document = params.get("textDocument")
    if not isinstance(document, dict) or document.get("uri") != DOCUMENT_URI:
        raise GatewayError(1008, "only the Playground document URI is allowed")
    return document


def require_position(params: dict[str, Any]) -> dict[str, int]:
    position = params.get("position")
    if not isinstance(position, dict):
        raise GatewayError(1008, "position must be an object")
    line = position.get("line")
    character = position.get("character")
    if (
        not isinstance(line, int)
        or isinstance(line, bool)
        or line < 0
        or not isinstance(character, int)
        or isinstance(character, bool)
        or character < 0
        or line > 2_147_483_647
        or character > 2_147_483_647
    ):
        raise GatewayError(1008, "position must contain non-negative integers")
    return {"line": line, "character": character}


def compact_json(message: dict[str, Any]) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ClientProtocol:
    """Validate and narrow one browser's LSP view to one scratch buffer."""

    def __init__(self, source_bytes: int) -> None:
        self.source_bytes = source_bytes
        self.state = "new"
        self.initialize_id: int | str | None = None
        self.version = -1
        self.pending: dict[int | str, str] = {}

    def _request_id(self, message: dict[str, Any]) -> int | str:
        value = message.get("id")
        if not valid_id(value):
            raise GatewayError(1008, "request id must be a bounded string or integer")
        if value in self.pending or value == self.initialize_id:
            raise GatewayError(1008, "request id is already pending")
        return value

    def _source(self, value: Any) -> str:
        if not isinstance(value, str):
            raise GatewayError(1008, "document text must be a string")
        if len(value.encode("utf-8")) > self.source_bytes:
            raise GatewayError(1009, "Dawn source is too large")
        return value

    def from_client(self, body: bytes) -> bytes:
        message = parse_json(body, client=True)
        method = message.get("method")
        if not isinstance(method, str):
            raise GatewayError(1008, "client messages must name a method")

        if method == "initialize":
            if self.state != "new":
                raise GatewayError(1008, "initialize is only allowed once")
            request_id = self._request_id(message)
            self.initialize_id = request_id
            self.state = "initialize-sent"
            return compact_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "processId": None,
                        "rootUri": None,
                        "capabilities": {"general": {"positionEncodings": ["utf-16"]}},
                        "clientInfo": {"name": "dawn-playground", "version": "1"},
                    },
                }
            )

        if method == "initialized":
            if self.state != "initialize-done" or "id" in message:
                raise GatewayError(1008, "initialized is out of order")
            self.state = "initialized"
            return compact_json({"jsonrpc": "2.0", "method": "initialized", "params": {}})

        if method == "textDocument/didOpen":
            if self.state != "initialized" or "id" in message:
                raise GatewayError(1008, "didOpen is out of order")
            params = require_params(message)
            document = require_document(params)
            version = document.get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 0:
                raise GatewayError(1008, "didOpen version must be a non-negative integer")
            if version > 2_147_483_647:
                raise GatewayError(1008, "didOpen version is too large")
            text = self._source(document.get("text"))
            self.version = version
            self.state = "open"
            return compact_json(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": {
                        "textDocument": {
                            "uri": DOCUMENT_URI,
                            "languageId": "dawn",
                            "version": version,
                            "text": text,
                        }
                    },
                }
            )

        if self.state != "open":
            raise GatewayError(1008, "document is not open")

        if method == "textDocument/didChange":
            if "id" in message:
                raise GatewayError(1008, "didChange must be a notification")
            params = require_params(message)
            document = require_document(params)
            version = document.get("version")
            if (
                not isinstance(version, int)
                or isinstance(version, bool)
                or version <= self.version
                or version > 2_147_483_647
            ):
                raise GatewayError(1008, "didChange version must increase")
            changes = params.get("contentChanges")
            if (
                not isinstance(changes, list)
                or len(changes) != 1
                or not isinstance(changes[0], dict)
            ):
                raise GatewayError(1008, "didChange must contain one Full sync")
            if set(changes[0]) != {"text"}:
                raise GatewayError(1008, "incremental didChange is not allowed")
            text = self._source(changes[0].get("text"))
            self.version = version
            return compact_json(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": {
                        "textDocument": {"uri": DOCUMENT_URI, "version": version},
                        "contentChanges": [{"text": text}],
                    },
                }
            )

        if method in {
            "textDocument/completion",
            "textDocument/hover",
            "textDocument/definition",
        }:
            if len(self.pending) >= HARD_PENDING_REQUESTS:
                raise GatewayError(1008, "too many pending LSP requests")
            request_id = self._request_id(message)
            params = require_params(message)
            require_document(params)
            position = require_position(params)
            self.pending[request_id] = method
            return compact_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": {
                        "textDocument": {"uri": DOCUMENT_URI},
                        "position": position,
                    },
                }
            )

        raise GatewayError(1008, "method is not allowed")

    def from_child(self, body: bytes) -> bytes:
        message = parse_json(body, client=False)
        if "method" in message:
            if message.get("method") != "textDocument/publishDiagnostics":
                raise ChildProtocolError("child emitted an unexpected notification/request")
            params = message.get("params")
            if (
                self.state != "open"
                or not isinstance(params, dict)
                or params.get("uri") != DOCUMENT_URI
                or not isinstance(params.get("diagnostics"), list)
            ):
                raise ChildProtocolError("child diagnostics escaped the Playground URI")
            # Workspace-related information can contain locations in other
            # files.  A Playground session exposes one buffer only, so remove
            # those optional cross-file links before returning diagnostics.
            diagnostics = []
            for diagnostic in params["diagnostics"]:
                if not isinstance(diagnostic, dict):
                    raise ChildProtocolError("child emitted a malformed diagnostic")
                diagnostics.append({
                    key: value
                    for key, value in diagnostic.items()
                    if key not in {"relatedInformation", "data"}
                })
            safe_params: dict[str, Any] = {
                "uri": DOCUMENT_URI,
                "diagnostics": diagnostics,
            }
            if "version" in params:
                version = params["version"]
                if (
                    not isinstance(version, int)
                    or isinstance(version, bool)
                    or version < -2_147_483_648
                    or version > 2_147_483_647
                ):
                    raise ChildProtocolError(
                        "child emitted an invalid diagnostics version"
                    )
                safe_params["version"] = version
            return compact_json(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": safe_params,
                }
            )

        response_id = message.get("id")
        if response_id == self.initialize_id and self.state == "initialize-sent":
            self.initialize_id = None
            if "error" in message:
                self.state = "initialize-failed"
                return compact_json(
                    {
                        "jsonrpc": "2.0",
                        "id": response_id,
                        "error": {
                            "code": -32002,
                            "message": "language service initialization failed",
                        },
                    }
                )
            result = message.get("result")
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("capabilities"), dict)
            ):
                raise ChildProtocolError("child emitted a malformed initialize result")
            self.state = "initialize-done"
            # Advertise the gateway's deliberately narrower surface, not every
            # feature the native server happens to implement.
            return compact_json(
                {
                    "jsonrpc": "2.0",
                    "id": response_id,
                    "result": {
                        "capabilities": {
                            "positionEncoding": "utf-16",
                            "textDocumentSync": 1,
                            "completionProvider": {
                                "resolveProvider": False,
                                "triggerCharacters": ["!"],
                            },
                            "hoverProvider": True,
                            "definitionProvider": True,
                        }
                    },
                }
            )
        if response_id not in self.pending:
            raise ChildProtocolError("child answered an unknown request id")
        method = self.pending.pop(response_id)
        if method == "textDocument/definition" and "result" in message:
            result = message["result"]
            if not isinstance(result, list):
                raise ChildProtocolError("definition result is not a list")
            safe = []
            for location in result:
                if isinstance(location, dict) and location.get("uri") == DOCUMENT_URI:
                    safe.append(location)
            message = {**message, "result": safe}
        return compact_json(message)


async def read_lsp_body(reader: asyncio.StreamReader, max_body: int) -> bytes:
    header = bytearray()
    while not header.endswith(b"\r\n\r\n"):
        if len(header) >= HARD_HEADER_BYTES:
            raise ChildProtocolError("child LSP header exceeds 8192 bytes")
        one = await reader.read(1)
        if not one:
            if not header:
                raise EOFError
            raise ChildProtocolError("child EOF inside LSP header")
        header.extend(one)
    lengths: list[int] = []
    for line in bytes(header[:-4]).split(b"\r\n"):
        if b":" not in line:
            raise ChildProtocolError("child emitted a malformed LSP header")
        name, raw = line.split(b":", 1)
        if name.lower() == b"content-length":
            value = raw.strip(b" \t")
            if not value or not value.isdigit():
                raise ChildProtocolError("child emitted an invalid Content-Length")
            lengths.append(int(value, 10))
    if not lengths or any(value != lengths[0] for value in lengths):
        raise ChildProtocolError("child emitted missing/conflicting Content-Length")
    length = lengths[0]
    if length > max_body:
        raise ChildProtocolError("child LSP body exceeds gateway message cap")
    try:
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ChildProtocolError("child EOF inside LSP body") from exc


def lsp_frame(body: bytes) -> bytes:
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class Session:
    def __init__(
        self,
        session_id: str,
        config: Config,
        ws: WebSocket,
    ) -> None:
        self.id = session_id
        self.config = config
        self.ws = ws
        self.protocol = ClientProtocol(config.source_bytes)
        self.proc: asyncio.subprocess.Process | None = None
        self.started = time.monotonic()
        self.message_count = 0
        self.message_tokens = MESSAGE_BURST
        self.message_updated = self.started

    def consume_message_budget(self) -> None:
        now = time.monotonic()
        elapsed = now - self.message_updated
        self.message_updated = now
        self.message_tokens = min(
            MESSAGE_BURST,
            self.message_tokens + elapsed * MESSAGE_RATE_PER_SECOND,
        )
        self.message_count += 1
        if self.message_count > HARD_MESSAGES_PER_SESSION:
            raise GatewayError(1008, "session message limit reached")
        if self.message_tokens < 1.0:
            raise GatewayError(1008, "session message rate exceeded")
        self.message_tokens -= 1.0

    def child_argv(self) -> tuple[str, ...]:
        if self.config.unsafe_local:
            return self.config.child_argv
        return ("/usr/bin/sudo", "-n", self.config.sandbox_script, "run", self.id)

    async def start_child(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.child_argv(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        LOG.info("session=%s child-start pid=%s", self.id, self.proc.pid)

    async def client_to_child(self) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        while True:
            try:
                body = await asyncio.wait_for(
                    self.ws.recv_text(), timeout=self.config.idle_seconds
                )
            except asyncio.TimeoutError as exc:
                raise GatewayError(1001, "session idle timeout") from exc
            if body is None:
                return
            self.consume_message_budget()
            narrowed = self.protocol.from_client(body)
            self.proc.stdin.write(lsp_frame(narrowed))
            try:
                await asyncio.wait_for(
                    self.proc.stdin.drain(), timeout=HARD_IO_SECONDS
                )
            except asyncio.TimeoutError as exc:
                raise ChildProtocolError("child stopped reading stdin") from exc

    async def child_to_client(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            try:
                body = await read_lsp_body(self.proc.stdout, self.config.message_bytes)
            except EOFError:
                raise ChildProtocolError("child closed stdout")
            narrowed = self.protocol.from_child(body)
            await self.ws.send_text(narrowed)

    async def drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        total = 0
        try:
            while True:
                chunk = await self.proc.stderr.read(4096)
                if not chunk:
                    return
                total += len(chunk)
        finally:
            # Compiler stderr can contain the submitted program.  Record only
            # metadata, never code or a full protocol body.
            if total:
                LOG.warning("session=%s child-stderr bytes=%d", self.id, total)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.config.ping_seconds)
            if time.monotonic() - self.ws.last_pong > self.config.ping_seconds * 3:
                raise GatewayError(1001, "WebSocket heartbeat timeout")
            await self.ws.send_ping()

    async def lifetime(self) -> NoReturn:
        await asyncio.sleep(self.config.lifetime_seconds)
        raise GatewayError(1001, "session lifetime reached")

    async def setup_deadline(self) -> NoReturn:
        """Require the one scratch buffer to be open promptly after upgrade."""

        await asyncio.sleep(self.config.setup_seconds)
        if self.protocol.state != "open":
            raise GatewayError(1001, "session setup timeout")
        # The deadline is satisfied.  Stay pending so this guard cannot win
        # Session.run's FIRST_COMPLETED wait after a successful didOpen.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def graceful_child_stop(self) -> None:
        proc = self.proc
        if proc is None:
            return
        if proc.returncode is None and proc.stdin is not None:
            try:
                if self.protocol.state in {"initialize-done", "initialized", "open"}:
                    shutdown = compact_json(
                        {
                            "jsonrpc": "2.0",
                            "id": "gateway:shutdown",
                            "method": "shutdown",
                            "params": {},
                        }
                    )
                    exiting = compact_json(
                        {"jsonrpc": "2.0", "method": "exit", "params": {}}
                    )
                    proc.stdin.write(lsp_frame(shutdown) + lsp_frame(exiting))
                    await asyncio.wait_for(
                        proc.stdin.drain(), timeout=self.config.shutdown_seconds
                    )
            except (BrokenPipeError, ConnectionError, asyncio.TimeoutError):
                pass
            finally:
                proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.config.shutdown_seconds)
            return
        except asyncio.TimeoutError:
            pass

        if not self.config.unsafe_local:
            try:
                stopper = await asyncio.create_subprocess_exec(
                    "/usr/bin/sudo",
                    "-n",
                    self.config.sandbox_script,
                    "stop",
                    self.id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(
                        stopper.wait(), timeout=self.config.shutdown_seconds + 4
                    )
                except asyncio.TimeoutError:
                    # sudo has changed all of its uids to root, so this
                    # unprivileged gateway cannot signal it.  The transient
                    # service's TimeoutStopSec and BindsTo remain authoritative.
                    LOG.warning("session=%s sandbox-stop-command-timeout", self.id)
                else:
                    if stopper.returncode != 0:
                        LOG.warning(
                            "session=%s sandbox-stop-command-rc=%d",
                            self.id,
                            stopper.returncode,
                        )
            except OSError:
                LOG.warning("session=%s sandbox-stop-launch-failed", self.id)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.config.shutdown_seconds)
        except asyncio.TimeoutError:
            if not self.config.unsafe_local:
                # Fail closed on admission.  RuntimeMaxSec/BindsTo remain the
                # authority for a wedged unit, but the gateway must not count
                # its slot as free while the owning systemd-run process still
                # exists.  In ordinary operation the explicit stop above
                # makes this wait complete immediately.
                LOG.error(
                    "session=%s sandbox-process-did-not-stop admission-held",
                    self.id,
                )
                await proc.wait()
                return
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(
                    proc.wait(), timeout=self.config.shutdown_seconds
                )
            except asyncio.TimeoutError:
                LOG.error("session=%s local-child-did-not-stop", self.id)

    async def run(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        close_code = 1000
        close_reason = ""
        try:
            await self.start_child()
            assert self.proc is not None
            client_task = asyncio.create_task(
                self.client_to_child(), name=f"{self.id}-client"
            )
            child_task = asyncio.create_task(
                self.child_to_client(), name=f"{self.id}-child"
            )
            stderr_task = asyncio.create_task(
                self.drain_stderr(), name=f"{self.id}-stderr"
            )
            heartbeat_task = asyncio.create_task(
                self.heartbeat(), name=f"{self.id}-heartbeat"
            )
            lifetime_task = asyncio.create_task(
                self.lifetime(), name=f"{self.id}-lifetime"
            )
            setup_task = asyncio.create_task(
                self.setup_deadline(), name=f"{self.id}-setup"
            )
            wait_task = asyncio.create_task(self.proc.wait(), name=f"{self.id}-wait")
            tasks = [
                client_task,
                child_task,
                stderr_task,
                heartbeat_task,
                lifetime_task,
                setup_task,
                wait_task,
            ]
            done, _ = await asyncio.wait(
                [
                    client_task,
                    child_task,
                    heartbeat_task,
                    lifetime_task,
                    setup_task,
                    wait_task,
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # A clean client close wins races with the subprocess shutting
            # down.  Every other early child exit is a service failure.
            if client_task in done and not client_task.cancelled():
                error = client_task.exception()
                if error is None:
                    return
                raise error
            for task in done:
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
            if wait_task in done:
                raise ChildProtocolError(f"LSP child exited {self.proc.returncode}")
            if child_task in done:
                raise ChildProtocolError("LSP child output ended")
        except GatewayError as exc:
            close_code, close_reason = exc.code, exc.reason
            LOG.info("session=%s client-close code=%d reason=%s", self.id, exc.code, exc.reason)
        except (
            ChildProtocolError,
            BrokenPipeError,
            ConnectionError,
            asyncio.IncompleteReadError,
        ) as exc:
            close_code, close_reason = 1011, "language service stopped"
            LOG.warning("session=%s child-failure kind=%s", self.id, type(exc).__name__)
        except Exception:
            close_code, close_reason = 1011, "language service stopped"
            LOG.exception("session=%s unexpected-failure", self.id)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.ws.close(close_code, close_reason)
            await self.graceful_child_stop()
            LOG.info(
                "session=%s end child_rc=%s lifetime_ms=%d",
                self.id,
                self.proc.returncode if self.proc else None,
                int((time.monotonic() - self.started) * 1000),
            )


class Gateway:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.active = 0
        self.handshakes = 0
        self.connection_tasks: set[asyncio.Task[Any]] = set()

    async def connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection_task = asyncio.current_task()
        if connection_task is not None:
            self.connection_tasks.add(connection_task)
        session_id = ""
        admitted = False
        handshaking = False
        try:
            # Do not queue an unbounded number of slow HTTP upgrades behind a
            # semaphore: reject above the hard handshake budget immediately.
            if self.handshakes >= HARD_HANDSHAKES:
                await http_reply(
                    writer,
                    503,
                    "Service Unavailable",
                    "Too many WebSocket handshakes\n",
                    retry_after=2,
                )
                return
            self.handshakes += 1
            handshaking = True
            try:
                block = await asyncio.wait_for(
                    read_upgrade(reader, self.config),
                    timeout=self.config.handshake_seconds,
                )
                upgrade = parse_upgrade(block, self.config)
            except PermissionError:
                await http_reply(writer, 403, "Forbidden", "WebSocket origin/subprotocol refused\n")
                return
            except (ValueError, asyncio.TimeoutError):
                await http_reply(writer, 400, "Bad Request", "Invalid WebSocket upgrade\n")
                return

            if self.active >= self.config.max_sessions:
                LOG.info(
                    "connection-refused reason=busy active=%d", self.active
                )
                await http_reply(
                    writer,
                    503,
                    "Service Unavailable",
                    "Language service busy\n",
                    retry_after=2,
                )
                return
            self.active += 1
            admitted = True
            session_id = secrets.token_hex(16)
            await accept_upgrade(writer, upgrade)
            self.handshakes -= 1
            handshaking = False

            peer = writer.get_extra_info("peername")
            LOG.info("session=%s accept peer=%s active=%d", session_id, peer, self.active)
            ws = WebSocket(reader, writer, self.config.message_bytes)
            await Session(session_id, self.config, ws).run()
        except (ConnectionError, BrokenPipeError, asyncio.IncompleteReadError):
            if session_id:
                LOG.info("session=%s socket-ended", session_id)
        except Exception:
            LOG.exception("session=%s connection-failure", session_id or "pre-handshake")
        finally:
            try:
                if handshaking:
                    self.handshakes -= 1
                if admitted:
                    self.active -= 1
                writer.close()
                try:
                    await asyncio.wait_for(
                        writer.wait_closed(), timeout=HARD_IO_SECONDS
                    )
                except (ConnectionError, BrokenPipeError, asyncio.TimeoutError):
                    pass
            finally:
                # Cancellation can be reinjected at wait_closed(); never leave
                # a completed task in the shutdown ownership set.
                if connection_task is not None:
                    self.connection_tasks.discard(connection_task)

    async def serve(self) -> None:
        server = await asyncio.start_server(
            self.connection,
            self.config.host,
            self.config.port,
            limit=HARD_HEADER_BYTES + 1,
        )
        sockets = server.sockets or []
        bound = ", ".join(str(sock.getsockname()) for sock in sockets)
        LOG.info(
            "listening=%s max_sessions=%d source_bytes=%d message_bytes=%d",
            bound,
            self.config.max_sessions,
            self.config.source_bytes,
            self.config.message_bytes,
        )
        stop = asyncio.Event()
        stop_requested = [False]
        previous_signals: dict[signal.Signals, Any] = {}

        def request_stop(_signum: int, _frame: Any) -> None:
            # Keep the signal handler reentrancy-safe. signal_tick observes
            # this flag in normal task context and begins Session cleanup.
            stop_requested[0] = True

        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                previous_signals[signum] = signal.signal(signum, request_stop)
            except (OSError, ValueError):
                # Signal handlers may only be installed by the main thread;
                # asyncio.run still cancels tasks during ordinary teardown.
                pass

        serve_task = asyncio.create_task(server.serve_forever(), name="gateway-listener")
        stop_task = asyncio.create_task(stop.wait(), name="gateway-stop")

        async def signal_tick() -> None:
            # Some Python/event-loop combinations do not wake the selector
            # promptly for a caught signal after subprocess activity.  This
            # timer guarantees the reentrancy-safe flag is observed anyway.
            while not stop_requested[0]:
                await asyncio.sleep(1)
            stop.set()

        signal_task = asyncio.create_task(signal_tick(), name="gateway-signal-tick")
        try:
            done, _ = await asyncio.wait(
                [serve_task, stop_task], return_when=asyncio.FIRST_COMPLETED
            )
            if serve_task in done:
                await serve_task
        finally:
            LOG.info("gateway stop requested")
            server.close()
            serve_task.cancel()
            stop_task.cancel()
            signal_task.cancel()

            # Cancel accepted connections only after the listener is closed;
            # each Session finally block then closes its WebSocket and child.
            # asyncio.Server.wait_closed() can wait for those callbacks, so it
            # must come after the owned connection tasks have been reaped.
            LOG.info("gateway stopping connections=%d", len(self.connection_tasks))
            while self.connection_tasks:
                self.connection_tasks = {
                    task for task in self.connection_tasks if not task.done()
                }
                if not self.connection_tasks:
                    break
                connections = list(self.connection_tasks)
                for task in connections:
                    task.cancel()
                await asyncio.gather(*connections, return_exceptions=True)
                LOG.info("gateway stopped-connection-batch count=%d", len(connections))
            await server.wait_closed()
            await asyncio.gather(
                serve_task, stop_task, signal_task, return_exceptions=True
            )
            for signum, previous in previous_signals.items():
                signal.signal(signum, previous)
            LOG.info("gateway stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="validate environment and exit")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.environ.get("PLAY_LSP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config.from_env()
    if args.check_config:
        print("dawn-play-lsp config ok")
        return
    try:
        asyncio.run(Gateway(config).serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

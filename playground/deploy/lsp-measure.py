#!/usr/bin/env python3
"""Bounded, direct-native measurements for the Playground LSP design.

This harness intentionally bypasses the WebSocket gateway.  It starts one
fresh ``dawnc lsp`` process for every recorded row, speaks LSP over stdio, and
records raw observations rather than computed summaries.  Run the deployed
release binary from the production-compatible cgroup whose limits are under
review; the child inherits that cgroup.

The default matrix is deliberately slow: every case has ten fresh processes
and the idle case observes sixty seconds.  ``--iterations`` below ten is useful
for a preflight, but its output does not satisfy the design's admission gate.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, TextIO


sys.dont_write_bytecode = True

URI = "untitled:dawn-playground/prog.dawn"
SOURCE_LIMIT_BYTES = 65_536
HEADER_LIMIT_BYTES = 8_192
BODY_LIMIT_BYTES = 16 * 1024 * 1024
DEFAULT_ITERATIONS = 10
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_IDLE_SECONDS = 60.0
DEFAULT_BURST_UPDATES = 20
DEFAULT_SAMPLE_INTERVAL_SECONDS = 0.10
CLEANUP_GRACE_SECONDS = 2.0
TERMINATE_GRACE_SECONDS = 1.0
KILL_GRACE_SECONDS = 1.0
MAX_MESSAGES_PER_WAIT = 256

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_DIR = ROOT / "site" / "play-ui" / "samples"
SAMPLE_NAMES = ("comptime", "effects", "hello", "shapes", "traits")

FEATURE_SOURCE = (
    "fn twice(v: Int) -> Int = v + v\n"
    "\n"
    "fn go() -> Int = twice(21)\n"
)

SCENARIO_ORDER = (
    "idle",
    "samples",
    "source-64k",
    "burst",
    "features",
    "disconnect",
)
SCENARIO_ALIASES = {
    "sample": "samples",
    "64k": "source-64k",
    "feature": "features",
}

COLUMNS = (
    "schema_version",
    "timestamp_utc",
    "scenario",
    "case",
    "iteration",
    "status",
    "error",
    "source_bytes",
    "diagnostics_count",
    "init_latency_ms",
    "diagnostics_latency_ms",
    "completion_latency_ms",
    "hover_latency_ms",
    "definition_latency_ms",
    "burst_updates",
    "burst_send_latency_ms",
    "burst_stale_diagnostics_latency_ms",
    "burst_diagnostics_latency_ms",
    "burst_barrier_latency_ms",
    "burst_total_latency_ms",
    "init_cpu_ms",
    "scenario_cpu_ms",
    "cpu_total_ms",
    "rss_kib",
    "pss_kib",
    "peak_rss_kib",
    "peak_sampled_rss_kib",
    "peak_sampled_pss_kib",
    "cleanup_time_ms",
    "cleanup_mode",
    "exit_code",
    "reaped",
    "validation",
    "binary_name",
    "binary_version",
    "harness_commit",
    "host",
    "kernel",
    "machine",
    "page_size",
    "cgroup_version",
    "cgroup_path",
    "cgroup_memory_max",
    "cgroup_memory_high",
    "cgroup_memory_swap_max",
    "cgroup_cpu_max",
    "cgroup_pids_max",
    "timeout_seconds",
    "idle_seconds",
    "sample_interval_seconds",
)


class MeasurementError(RuntimeError):
    """The measured process violated a protocol or result invariant."""


class FrameDecoder:
    """Incremental Content-Length decoder with bounded memory."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> None:
        if not data:
            raise MeasurementError("LSP stdout reached EOF")
        self.buffer.extend(data)
        if len(self.buffer) > HEADER_LIMIT_BYTES + BODY_LIMIT_BYTES:
            raise MeasurementError("LSP receive buffer exceeded its bound")

    def pop(self) -> dict[str, Any] | None:
        marker = self.buffer.find(b"\r\n\r\n")
        if marker < 0:
            if len(self.buffer) > HEADER_LIMIT_BYTES:
                raise MeasurementError("LSP header exceeded 8192 bytes")
            return None
        if marker > HEADER_LIMIT_BYTES:
            raise MeasurementError("LSP header exceeded 8192 bytes")

        header = bytes(self.buffer[:marker])
        lengths: list[int] = []
        for raw_line in header.split(b"\r\n"):
            if not raw_line or b":" not in raw_line:
                raise MeasurementError("LSP emitted a malformed header line")
            raw_name, raw_value = raw_line.split(b":", 1)
            try:
                name = raw_name.decode("ascii").strip().lower()
                value = raw_value.decode("ascii").strip()
            except UnicodeDecodeError as error:
                raise MeasurementError("LSP header was not ASCII") from error
            if not name:
                raise MeasurementError("LSP emitted an empty header name")
            if name == "content-length":
                if not value.isascii() or not value.isdigit():
                    raise MeasurementError("LSP emitted an invalid Content-Length")
                lengths.append(int(value, 10))

        if not lengths or any(length != lengths[0] for length in lengths):
            raise MeasurementError("LSP emitted missing/conflicting Content-Length")
        length = lengths[0]
        if length > BODY_LIMIT_BYTES:
            raise MeasurementError("LSP body exceeded the harness limit")
        body_start = marker + 4
        body_end = body_start + length
        if len(self.buffer) < body_end:
            return None
        body = bytes(self.buffer[body_start:body_end])
        del self.buffer[:body_end]

        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MeasurementError("LSP emitted an invalid UTF-8 JSON body") from error
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise MeasurementError("LSP emitted a non-JSON-RPC object")
        return message


def compact_json(message: dict[str, Any]) -> bytes:
    return json.dumps(
        message, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def frame(message: dict[str, Any]) -> bytes:
    body = compact_json(message)
    if len(body) > BODY_LIMIT_BYTES:
        raise MeasurementError("outbound LSP body exceeded the harness limit")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def rpc(request_id: int, method: str, params: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def note(method: str, params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def milliseconds(seconds: float) -> str:
    return f"{seconds * 1000.0:.3f}"


def clean_field(value: Any, limit: int = 1_000) -> str:
    text = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return text[:limit]


def public_error(error: Exception, executable: str) -> str:
    """Keep failure rows useful without publishing worker-local coordinates."""

    text = f"{type(error).__name__}: {error}"
    for private in (executable, str(ROOT), str(Path.home())):
        if private:
            text = text.replace(private, "<path>")
    text = re.sub(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", "<ip>", text)
    # Unexpected OSError messages can contain some other absolute worker path.
    text = re.sub(r"(?<![A-Za-z0-9._-])/(?:[^\s'\"]+)", "<path>", text)
    return clean_field(text)


def public_cgroup_label(path: str) -> str:
    if path == "unknown":
        return path
    components: list[str] = []
    for component in path.strip("/").split("/"):
        if not component:
            continue
        component = re.sub(r"^(user|session)-[0-9]+", r"\1-<id>", component)
        component = re.sub(
            r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "<id>",
            component,
        )
        component = re.sub(r"(?i)[0-9a-f]{32,}", "<id>", component)
        if len(component) >= 16 and all(char in "0123456789abcdefABCDEF" for char in component):
            component = "<id>"
        components.append(component)
    return "/".join(components) or "root"


def exact_64k_source() -> str:
    prefix = "pub fn main() -> Unit = ()\n"
    prefix_bytes = prefix.encode("utf-8")
    remaining = SOURCE_LIMIT_BYTES - len(prefix_bytes)
    if remaining < 2:
        raise AssertionError("64 KiB source prefix unexpectedly filled the budget")
    # A Dawn comment runs from '#' through the newline.  ASCII makes character
    # count and UTF-8 byte count identical, and the final newline closes it.
    source = prefix + "#" + ("p" * (remaining - 2)) + "\n"
    encoded = source.encode("utf-8")
    if len(encoded) != SOURCE_LIMIT_BYTES:
        raise AssertionError("64 KiB source construction is not byte-exact")
    return source


def source_bytes(source: str) -> int:
    return len(source.encode("utf-8"))


def nth_index(text: str, needle: str, occurrence: int) -> int:
    start = -1
    for _ in range(occurrence):
        start = text.find(needle, start + 1)
        if start < 0:
            raise AssertionError(f"feature probe needle not found: {needle!r}")
    return start


def lsp_position(text: str, offset: int) -> dict[str, int]:
    if offset < 0 or offset > len(text):
        raise AssertionError("position offset outside source")
    line_start = text.rfind("\n", 0, offset) + 1
    return {
        "line": text.count("\n", 0, offset),
        "character": len(text[line_start:offset].encode("utf-16-le")) // 2,
    }


def position_params(source: str, offset: int) -> dict[str, Any]:
    return {
        "textDocument": {"uri": URI},
        "position": lsp_position(source, offset),
    }


def validate_position(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise MeasurementError(f"{label} is not an object")
    line = value.get("line")
    character = value.get("character")
    if (
        not isinstance(line, int)
        or isinstance(line, bool)
        or line < 0
        or not isinstance(character, int)
        or isinstance(character, bool)
        or character < 0
    ):
        raise MeasurementError(f"{label} is not a non-negative LSP position")
    return {"line": line, "character": character}


def validate_range(value: Any, label: str) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        raise MeasurementError(f"{label} is not an object")
    start = validate_position(value.get("start"), f"{label}.start")
    end = validate_position(value.get("end"), f"{label}.end")
    if (end["line"], end["character"]) < (start["line"], start["character"]):
        raise MeasurementError(f"{label} is backwards")
    return {"start": start, "end": end}


def response_result(message: dict[str, Any], request_id: int) -> Any:
    if message.get("id") != request_id:
        raise MeasurementError(f"response id did not match request {request_id}")
    if "error" in message:
        error = message.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            detail = clean_field(error.get("message", ""), 240)
            raise MeasurementError(f"LSP request failed ({code}): {detail}")
        raise MeasurementError("LSP request returned a malformed error")
    if "result" not in message:
        raise MeasurementError("LSP response had neither result nor error")
    return message["result"]


def validate_initialize(message: dict[str, Any], request_id: int) -> None:
    result = response_result(message, request_id)
    if not isinstance(result, dict) or not isinstance(result.get("capabilities"), dict):
        raise MeasurementError("initialize result lacks capabilities")
    capabilities = result["capabilities"]
    if capabilities.get("textDocumentSync") != 1:
        raise MeasurementError("native LSP does not advertise Full sync")
    if not isinstance(capabilities.get("completionProvider"), dict):
        raise MeasurementError("native LSP does not advertise completion")
    if capabilities.get("hoverProvider") is not True:
        raise MeasurementError("native LSP does not advertise hover")
    if capabilities.get("definitionProvider") is not True:
        raise MeasurementError("native LSP does not advertise definition")


def validate_diagnostics(message: dict[str, Any]) -> list[dict[str, Any]]:
    if message.get("method") != "textDocument/publishDiagnostics":
        raise MeasurementError("expected publishDiagnostics notification")
    params = message.get("params")
    if not isinstance(params, dict) or params.get("uri") != URI:
        raise MeasurementError("publishDiagnostics named the wrong document")
    diagnostics = params.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise MeasurementError("publishDiagnostics diagnostics is not a list")
    for index, diagnostic in enumerate(diagnostics):
        if not isinstance(diagnostic, dict):
            raise MeasurementError(f"diagnostic {index} is not an object")
        validate_range(diagnostic.get("range"), f"diagnostic {index}.range")
        if not isinstance(diagnostic.get("message"), str):
            raise MeasurementError(f"diagnostic {index} lacks a message")
    return diagnostics


def validate_completion(message: dict[str, Any], request_id: int) -> list[dict[str, Any]]:
    result = response_result(message, request_id)
    if isinstance(result, dict):
        result = result.get("items")
    if not isinstance(result, list):
        raise MeasurementError("completion result is neither a list nor CompletionList")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(result):
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise MeasurementError(f"completion item {index} lacks a string label")
        items.append(item)
    return items


def hover_text(contents: Any) -> str:
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        value = contents.get("value")
        if isinstance(value, str):
            return value
        raise MeasurementError("hover MarkupContent lacks a string value")
    if isinstance(contents, list):
        return "\n".join(hover_text(item) for item in contents)
    raise MeasurementError("hover contents has an unsupported shape")


def validate_hover(message: dict[str, Any], request_id: int) -> str:
    result = response_result(message, request_id)
    if not isinstance(result, dict):
        raise MeasurementError("hover feature probe returned null/non-object")
    text = hover_text(result.get("contents"))
    if not text.strip():
        raise MeasurementError("hover feature probe returned empty contents")
    if "range" in result:
        validate_range(result["range"], "hover.range")
    return text


def validate_definition(
    message: dict[str, Any], request_id: int
) -> list[dict[str, Any]]:
    result = response_result(message, request_id)
    if not isinstance(result, list) or not result:
        raise MeasurementError("definition feature probe returned no locations")
    locations: list[dict[str, Any]] = []
    for index, location in enumerate(result):
        if not isinstance(location, dict) or location.get("uri") != URI:
            raise MeasurementError(
                f"definition location {index} is not in the current buffer"
            )
        validate_range(location.get("range"), f"definition location {index}.range")
        locations.append(location)
    return locations


def parse_proc_status(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, raw = line.split(":", 1)
        fields = raw.strip().split()
        if fields and fields[0].isdigit():
            values[name] = int(fields[0], 10)
    return values


def parse_proc_stat(text: str) -> tuple[int, int] | None:
    # comm is parenthesized and may itself contain spaces or ')'.  Fields after
    # the last ')' start at field 3; utime/stime are fields 14/15.
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].strip().split()
    if len(fields) < 13:
        return None
    try:
        return int(fields[11], 10), int(fields[12], 10)
    except ValueError:
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None


def read_proc_metrics(pid: int) -> dict[str, int | None]:
    status_text = read_text(Path(f"/proc/{pid}/status"))
    status = parse_proc_status(status_text) if status_text is not None else {}
    pss: int | None = None
    smaps = read_text(Path(f"/proc/{pid}/smaps_rollup"))
    if smaps is not None:
        pss = parse_proc_status(smaps).get("Pss")

    user_ticks: int | None = None
    system_ticks: int | None = None
    stat_text = read_text(Path(f"/proc/{pid}/stat"))
    if stat_text is not None:
        parsed = parse_proc_stat(stat_text)
        if parsed is not None:
            user_ticks, system_ticks = parsed
    return {
        "rss_kib": status.get("VmRSS"),
        "peak_rss_kib": status.get("VmHWM"),
        "pss_kib": pss,
        "user_ticks": user_ticks,
        "system_ticks": system_ticks,
    }


class ProcSampler:
    """Low-rate /proc sampler; kernel VmHWM remains the primary RSS peak."""

    def __init__(self, pid: int, interval: float) -> None:
        self.pid = pid
        self.interval = interval
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.last: dict[str, int | None] = {}
        self.max_rss: int | None = None
        self.max_pss: int | None = None
        self.thread = threading.Thread(
            target=self._run, name=f"lsp-measure-{pid}", daemon=True
        )
        self._record(read_proc_metrics(pid))
        self.thread.start()

    def _record(self, observed: dict[str, int | None]) -> None:
        with self.lock:
            if any(value is not None for value in observed.values()):
                self.last = observed
            rss = observed.get("rss_kib")
            pss = observed.get("pss_kib")
            if rss is not None:
                self.max_rss = rss if self.max_rss is None else max(self.max_rss, rss)
            if pss is not None:
                self.max_pss = pss if self.max_pss is None else max(self.max_pss, pss)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self._record(read_proc_metrics(self.pid))

    def snapshot(self) -> dict[str, int | None]:
        self._record(read_proc_metrics(self.pid))
        with self.lock:
            out = dict(self.last)
            out["peak_sampled_rss_kib"] = self.max_rss
            out["peak_sampled_pss_kib"] = self.max_pss
            return out

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.interval * 4.0))


def proc_cgroup(pid: int) -> tuple[str, str]:
    text = read_text(Path(f"/proc/{pid}/cgroup"))
    if text is None:
        return "unknown", "unknown"
    unified: str | None = None
    first_path: str | None = None
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, path = parts
        if first_path is None:
            first_path = path
        if hierarchy == "0" and controllers == "":
            unified = path
    if unified is not None:
        return "v2", unified
    return "v1", first_path or "unknown"


def cgroup_metadata(pid: int) -> dict[str, str]:
    version, path = proc_cgroup(pid)
    out = {
        "cgroup_version": version,
        "cgroup_path": clean_field(public_cgroup_label(path)),
        "cgroup_memory_max": "",
        "cgroup_memory_high": "",
        "cgroup_memory_swap_max": "",
        "cgroup_cpu_max": "",
        "cgroup_pids_max": "",
    }
    if version != "v2" or path == "unknown":
        return out
    root = Path("/sys/fs/cgroup").resolve()
    group = (root / path.lstrip("/")).resolve()
    try:
        group.relative_to(root)
    except ValueError:
        return out
    for column, filename in (
        ("cgroup_memory_max", "memory.max"),
        ("cgroup_memory_high", "memory.high"),
        ("cgroup_memory_swap_max", "memory.swap.max"),
        ("cgroup_cpu_max", "cpu.max"),
        ("cgroup_pids_max", "pids.max"),
    ):
        value = read_text(group / filename)
        if value is not None:
            out[column] = clean_field(value.strip())
    return out


class NativeLsp:
    """One native process and its bounded stdio transport."""

    def __init__(self, executable: str, timeout: float, sample_interval: float) -> None:
        self.timeout = timeout
        self.decoder = FrameDecoder()
        self.next_id = 1
        environment = os.environ.copy()
        # A deployed release uses its embedded std.  Do not accidentally
        # measure a checkout supplied through the caller's shell.
        environment.pop("DAWN_STD", None)
        started = time.monotonic()
        self.proc = subprocess.Popen(
            [executable, "lsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd="/",
            env=environment,
            bufsize=0,
            start_new_session=True,
        )
        self.started = started
        if self.proc.stdin is None or self.proc.stdout is None:
            self.proc.kill()
            self.proc.wait()
            raise MeasurementError("failed to create native LSP pipes")
        self.stdin_fd = self.proc.stdin.fileno()
        self.stdout_fd = self.proc.stdout.fileno()
        os.set_blocking(self.stdin_fd, False)
        os.set_blocking(self.stdout_fd, False)
        self.sampler = ProcSampler(self.proc.pid, sample_interval)
        self.cgroup = cgroup_metadata(self.proc.pid)

    def deadline(self, seconds: float | None = None) -> float:
        return time.monotonic() + (self.timeout if seconds is None else seconds)

    def send_bytes(self, payload: bytes, deadline: float) -> None:
        view = memoryview(payload)
        with selectors.DefaultSelector() as selector:
            selector.register(self.stdin_fd, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out writing an LSP frame")
                if not selector.select(remaining):
                    raise TimeoutError("timed out writing an LSP frame")
                try:
                    written = os.write(self.stdin_fd, view)
                except BlockingIOError:
                    continue
                except BrokenPipeError as error:
                    raise MeasurementError("native LSP closed stdin") from error
                if written <= 0:
                    raise MeasurementError("native LSP stdin made no progress")
                view = view[written:]

    def send(self, message: dict[str, Any], deadline: float | None = None) -> None:
        self.send_bytes(frame(message), self.deadline() if deadline is None else deadline)

    def send_many(
        self, messages: Iterable[dict[str, Any]], deadline: float | None = None
    ) -> None:
        payload = b"".join(frame(message) for message in messages)
        self.send_bytes(payload, self.deadline() if deadline is None else deadline)

    def read(self, deadline: float) -> dict[str, Any]:
        while True:
            message = self.decoder.pop()
            if message is not None:
                return message
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for an LSP message")
            with selectors.DefaultSelector() as selector:
                selector.register(self.stdout_fd, selectors.EVENT_READ)
                if not selector.select(remaining):
                    raise TimeoutError("timed out waiting for an LSP message")
            try:
                chunk = os.read(self.stdout_fd, 65_536)
            except BlockingIOError:
                continue
            if not chunk:
                code = self.proc.poll()
                raise MeasurementError(f"native LSP stdout closed (exit={code})")
            self.decoder.feed(chunk)

    def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        deadline: float,
        label: str,
    ) -> dict[str, Any]:
        for _ in range(MAX_MESSAGES_PER_WAIT):
            message = self.read(deadline)
            if predicate(message):
                return message
            # With requests serialized, an unmatched response is never stale.
            if "id" in message:
                raise MeasurementError(f"unexpected response while waiting for {label}")
        raise MeasurementError(f"too many messages while waiting for {label}")

    def request(self, method: str, params: Any) -> tuple[int, dict[str, Any], float]:
        request_id = self.next_id
        self.next_id += 1
        started = time.monotonic()
        deadline = started + self.timeout
        self.send(rpc(request_id, method, params), deadline)
        message = self.wait_for(
            lambda item: item.get("id") == request_id,
            deadline,
            f"{method} response",
        )
        return request_id, message, time.monotonic() - started

    def initialize(self) -> tuple[float, float | None]:
        request_id = self.next_id
        self.next_id += 1
        deadline = time.monotonic() + self.timeout
        self.send(
            rpc(
                request_id,
                "initialize",
                {
                    "processId": None,
                    "rootUri": None,
                    "capabilities": {
                        "general": {"positionEncodings": ["utf-16"]},
                        "textDocument": {
                            "completion": {
                                "completionItem": {"snippetSupport": False}
                            },
                            "hover": {
                                "contentFormat": ["markdown", "plaintext"]
                            },
                        },
                    },
                },
            ),
            deadline,
        )
        message = self.wait_for(
            lambda item: item.get("id") == request_id,
            deadline,
            "initialize response",
        )
        validate_initialize(message, request_id)
        latency = time.monotonic() - self.started
        self.send(note("initialized", {}))
        metrics = self.sampler.snapshot()
        return latency, cpu_milliseconds(metrics)

    def open_document(self, source: str) -> tuple[list[dict[str, Any]], float]:
        started = time.monotonic()
        deadline = started + self.timeout
        self.send(
            note(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": URI,
                        "languageId": "dawn",
                        "version": 1,
                        "text": source,
                    }
                },
            ),
            deadline,
        )
        message = self.wait_for(
            lambda item: item.get("method")
            == "textDocument/publishDiagnostics",
            deadline,
            "initial diagnostics",
        )
        diagnostics = validate_diagnostics(message)
        return diagnostics, time.monotonic() - started

    def _close_stdin(self) -> None:
        try:
            self.proc.stdin.close()  # type: ignore[union-attr]
        except (BrokenPipeError, OSError):
            pass

    def _wait_until(self, deadline: float) -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return self.proc.poll() is not None
        try:
            self.proc.wait(timeout=remaining)
            return True
        except subprocess.TimeoutExpired:
            return False

    def _signal_group(self, sig: signal.Signals) -> None:
        if self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, sig)
        except ProcessLookupError:
            pass

    def cleanup(self, disconnect: bool) -> dict[str, Any]:
        started = time.monotonic()
        mode = "already-exited" if self.proc.poll() is not None else ""
        grace_deadline = started + CLEANUP_GRACE_SECONDS

        if self.proc.poll() is None and disconnect:
            mode = "eof"
            self._close_stdin()
            self._wait_until(grace_deadline)
        elif self.proc.poll() is None:
            mode = "graceful"
            try:
                request_id = self.next_id
                self.next_id += 1
                self.send(rpc(request_id, "shutdown", None), grace_deadline)
                response = self.wait_for(
                    lambda item: item.get("id") == request_id,
                    grace_deadline,
                    "shutdown response",
                )
                if response_result(response, request_id) is not None:
                    raise MeasurementError("shutdown result was not null")
                self.send(note("exit", {}), grace_deadline)
            except (MeasurementError, TimeoutError, OSError):
                mode = "terminate"
            self._close_stdin()
            self._wait_until(grace_deadline)

        if self.proc.poll() is None:
            mode = "terminate"
            self._signal_group(signal.SIGTERM)
            self._wait_until(time.monotonic() + TERMINATE_GRACE_SECONDS)
        if self.proc.poll() is None:
            mode = "kill"
            self._signal_group(signal.SIGKILL)
            self._wait_until(time.monotonic() + KILL_GRACE_SECONDS)
        reaped = self.proc.poll() is not None
        if reaped:
            # poll() has already reaped in normal subprocess implementations;
            # wait() also makes that invariant explicit.
            self.proc.wait()
        self.sampler.stop()
        return {
            "cleanup_time_ms": milliseconds(time.monotonic() - started),
            "cleanup_mode": mode or "unreaped",
            "exit_code": "" if self.proc.returncode is None else self.proc.returncode,
            "reaped": "true" if reaped else "false",
        }


def cpu_milliseconds(metrics: dict[str, int | None]) -> float | None:
    user = metrics.get("user_ticks")
    system = metrics.get("system_ticks")
    if user is None or system is None:
        return None
    ticks = os.sysconf("SC_CLK_TCK")
    return (user + system) * 1000.0 / ticks


def common_metadata(
    executable: str,
    binary_version: str,
    host_label: str,
    commit_label: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        # Raw artifacts are intended to be safe to attach to a public PR.  A
        # basename identifies the selected artifact without publishing a home
        # directory, mount point, or worker layout.
        "binary_name": clean_field(os.path.basename(executable)),
        "binary_version": clean_field(binary_version),
        "harness_commit": commit_label or detect_harness_commit(),
        "host": clean_field(host_label),
        "kernel": clean_field(platform.release()),
        "machine": clean_field(platform.machine()),
        "page_size": os.sysconf("SC_PAGE_SIZE"),
    }


def detect_harness_commit() -> str:
    if not (ROOT / ".git").exists():
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"
    value = result.stdout.strip()
    return clean_field(value) if value else "unknown"


def blank_row(
    common: dict[str, Any],
    scenario: str,
    case: str,
    iteration: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    row: dict[str, Any] = {column: "" for column in COLUMNS}
    row.update(common)
    row.update(
        {
            "timestamp_utc": dt.datetime.now(dt.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "scenario": scenario,
            "case": case,
            "iteration": iteration,
            "status": "running",
            "timeout_seconds": args.timeout,
            "idle_seconds": args.idle_seconds,
            "sample_interval_seconds": args.sample_interval,
        }
    )
    if set(row) != set(COLUMNS):
        raise AssertionError("TSV row and header columns diverged")
    return row


def require_clean_diagnostics(
    diagnostics: list[dict[str, Any]], label: str
) -> None:
    if diagnostics:
        message = clean_field(diagnostics[0].get("message", "diagnostic"), 200)
        raise MeasurementError(f"{label} is not valid Dawn source: {message}")


def run_feature_probe(session: NativeLsp, row: dict[str, Any]) -> None:
    use = nth_index(FEATURE_SOURCE, "twice(21)", 1) + 1

    request_id, response, latency = session.request(
        "textDocument/completion", position_params(FEATURE_SOURCE, use)
    )
    items = validate_completion(response, request_id)
    if "twice" not in {item["label"] for item in items}:
        raise MeasurementError("completion feature probe did not include 'twice'")
    row["completion_latency_ms"] = milliseconds(latency)

    request_id, response, latency = session.request(
        "textDocument/hover", position_params(FEATURE_SOURCE, use)
    )
    text = validate_hover(response, request_id)
    if "twice" not in text:
        raise MeasurementError("hover feature probe did not describe 'twice'")
    row["hover_latency_ms"] = milliseconds(latency)

    request_id, response, latency = session.request(
        "textDocument/definition", position_params(FEATURE_SOURCE, use)
    )
    locations = validate_definition(response, request_id)
    expected = {
        "start": lsp_position(FEATURE_SOURCE, nth_index(FEATURE_SOURCE, "twice", 1)),
        "end": lsp_position(
            FEATURE_SOURCE, nth_index(FEATURE_SOURCE, "twice", 1) + len("twice")
        ),
    }
    if not any(location.get("range") == expected for location in locations):
        raise MeasurementError("definition feature probe returned the wrong local range")
    row["definition_latency_ms"] = milliseconds(latency)
    row["validation"] = "completion=twice;hover=twice;definition=current-buffer"


def run_burst(session: NativeLsp, row: dict[str, Any], updates: int) -> None:
    # Mirror site/play-ui's one-in-flight rule.  The first edit is sent at
    # once; the following local generations replace one queued snapshot while
    # that analysis is running.  Its stale diagnostics releases the flight,
    # then only the newest Full sync crosses the wire.  Sending all local
    # generations directly would measure a protocol pattern the deployed
    # browser deliberately never produces.
    local_sources = [
        FEATURE_SOURCE + f"@ burst-intermediate-{version}\n"
        for version in range(2, updates + 1)
    ]
    final_source = FEATURE_SOURCE + f"# burst-final-{updates}\n"
    local_sources.append(final_source)

    started = time.monotonic()
    first_deadline = started + session.timeout
    session.send(
        note(
            "textDocument/didChange",
            {
                "textDocument": {"uri": URI, "version": 2},
                "contentChanges": [{"text": local_sources[0]}],
            },
        ),
        first_deadline,
    )
    first = session.wait_for(
        lambda item: item.get("method") == "textDocument/publishDiagnostics",
        first_deadline,
        "first burst diagnostics",
    )
    stale_diagnostics = validate_diagnostics(first)
    first_diagnostics_at = time.monotonic()
    if not stale_diagnostics:
        raise MeasurementError("burst stale generation unexpectedly had no diagnostic")

    # Receiving the stale result is the browser's signal to release its one
    # in-flight slot.  All remaining local edits have already coalesced into
    # final_source, so only it and a semantic barrier are written now.
    barrier_id = session.next_id
    session.next_id += 1
    use = nth_index(final_source, "twice(21)", 1) + 1
    final_messages = [
        note(
            "textDocument/didChange",
            {
                "textDocument": {"uri": URI, "version": updates + 1},
                "contentChanges": [{"text": final_source}],
            },
        ),
        rpc(
            barrier_id,
            "textDocument/hover",
            position_params(final_source, use),
        ),
    ]

    final_started = time.monotonic()
    deadline = final_started + session.timeout
    session.send_many(final_messages, deadline)
    sent = time.monotonic()
    row["burst_updates"] = updates
    row["burst_send_latency_ms"] = milliseconds(sent - final_started)
    row["burst_stale_diagnostics_latency_ms"] = milliseconds(
        first_diagnostics_at - started
    )
    row["source_bytes"] = source_bytes(final_source)

    final_diagnostics: dict[str, Any] | None = None
    barrier: dict[str, Any] | None = None
    diagnostics_at: float | None = None
    for _ in range(MAX_MESSAGES_PER_WAIT):
        message = session.read(deadline)
        if message.get("method") == "textDocument/publishDiagnostics":
            if final_diagnostics is not None:
                raise MeasurementError("final burst sync produced duplicate diagnostics")
            final_diagnostics = message
            diagnostics_at = time.monotonic()
        elif message.get("id") == barrier_id:
            barrier = message
            break
        elif "id" in message:
            raise MeasurementError("burst received an unexpected response")
    if barrier is None or final_diagnostics is None or diagnostics_at is None:
        raise MeasurementError("burst did not produce diagnostics and a query barrier")
    diagnostics = validate_diagnostics(final_diagnostics)
    require_clean_diagnostics(diagnostics, "burst final text")
    hover = validate_hover(barrier, barrier_id)
    if "twice" not in hover:
        raise MeasurementError("burst query barrier did not observe final semantic state")
    row["diagnostics_count"] = len(diagnostics)
    row["burst_diagnostics_latency_ms"] = milliseconds(diagnostics_at - sent)
    row["burst_barrier_latency_ms"] = milliseconds(time.monotonic() - sent)
    row["burst_total_latency_ms"] = milliseconds(time.monotonic() - started)
    row["validation"] = (
        f"local-updates={updates};wire-syncs=2;"
        "stale-diagnostics-discarded;final-hover=twice"
    )


def run_one(
    executable: str,
    common: dict[str, Any],
    scenario: str,
    case: str,
    iteration: int,
    source: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Exception | None]:
    row = blank_row(common, scenario, case, iteration, args)
    row["source_bytes"] = source_bytes(source) if source else 0
    session: NativeLsp | None = None
    failure: Exception | None = None
    init_cpu: float | None = None
    disconnect = scenario == "disconnect"

    try:
        session = NativeLsp(executable, args.timeout, args.sample_interval)
        row.update(session.cgroup)
        init_latency, init_cpu = session.initialize()
        row["init_latency_ms"] = milliseconds(init_latency)
        row["init_cpu_ms"] = "" if init_cpu is None else f"{init_cpu:.3f}"

        if scenario == "idle":
            time.sleep(args.idle_seconds)
            row["validation"] = f"idle={args.idle_seconds:g}s"
        else:
            diagnostics, latency = session.open_document(source)
            row["diagnostics_latency_ms"] = milliseconds(latency)
            row["diagnostics_count"] = len(diagnostics)
            require_clean_diagnostics(diagnostics, case)
            if scenario == "features":
                run_feature_probe(session, row)
            elif scenario == "burst":
                run_burst(session, row, args.burst_updates)
            elif scenario == "disconnect":
                row["validation"] = "clean-open-before-eof"
            else:
                row["validation"] = "clean-diagnostics"

        if session.proc.poll() is not None:
            raise MeasurementError(
                f"native LSP exited before cleanup ({session.proc.returncode})"
            )
        row["status"] = "ok"
    except Exception as error:  # retain the partial raw row before failing fast
        failure = error
        row["status"] = "error"
        row["error"] = public_error(error, executable)
    finally:
        if session is not None:
            observed = session.sampler.snapshot()
            total_cpu = cpu_milliseconds(observed)
            if total_cpu is not None:
                row["cpu_total_ms"] = f"{total_cpu:.3f}"
                if init_cpu is not None:
                    row["scenario_cpu_ms"] = f"{max(0.0, total_cpu - init_cpu):.3f}"
            for column in (
                "rss_kib",
                "pss_kib",
                "peak_rss_kib",
                "peak_sampled_rss_kib",
                "peak_sampled_pss_kib",
            ):
                value = observed.get(column)
                row[column] = "" if value is None else value
            cleanup = session.cleanup(disconnect=disconnect)
            row.update(cleanup)
            if failure is None:
                expected_mode = "eof" if disconnect else "graceful"
                if cleanup["cleanup_mode"] != expected_mode:
                    failure = MeasurementError(
                        f"cleanup required {cleanup['cleanup_mode']} instead of {expected_mode}"
                    )
                elif cleanup["reaped"] != "true":
                    failure = MeasurementError("native LSP was not reaped")
                elif cleanup["exit_code"] != 0:
                    failure = MeasurementError(
                        f"native LSP cleanup exited {cleanup['exit_code']}"
                    )
                elif disconnect and float(cleanup["cleanup_time_ms"]) > (
                    CLEANUP_GRACE_SECONDS * 1000.0
                ):
                    failure = MeasurementError(
                        "disconnect cleanup exceeded the 2-second admission limit"
                    )
                if failure is not None:
                    row["status"] = "error"
                    row["error"] = public_error(failure, executable)
    return row, failure


def load_samples(sample_dir: Path) -> list[tuple[str, str]]:
    samples: list[tuple[str, str]] = []
    for name in SAMPLE_NAMES:
        path = sample_dir / f"{name}.dawn"
        try:
            raw = path.read_bytes()
            source = raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as error:
            raise MeasurementError(
                f"cannot read sample {path} ({type(error).__name__})"
            ) from error
        if len(raw) > SOURCE_LIMIT_BYTES:
            raise MeasurementError(
                f"sample {path} exceeds the Playground source limit, {len(raw)} is greater than {SOURCE_LIMIT_BYTES}"
            )
        samples.append((name, source))
    return samples


def cases_for(
    scenarios: list[str], sample_dir: Path = DEFAULT_SAMPLE_DIR
) -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    samples = load_samples(sample_dir) if "samples" in scenarios else []
    source_64k = exact_64k_source() if "source-64k" in scenarios else ""
    for scenario in scenarios:
        if scenario == "samples":
            cases.extend(("sample", name, source) for name, source in samples)
        elif scenario == "source-64k":
            cases.append((scenario, "exact-valid-65536-bytes", source_64k))
        elif scenario == "idle":
            cases.append((scenario, "initialized-no-document", ""))
        else:
            cases.append((scenario, scenario, FEATURE_SOURCE))
    return cases


def resolve_scenarios(values: list[str] | None) -> list[str]:
    if not values or values == ["all"]:
        return list(SCENARIO_ORDER)
    selected: set[str] = set()
    for raw in values:
        for token in raw.split(","):
            name = SCENARIO_ALIASES.get(token.strip(), token.strip())
            if name == "all":
                selected.update(SCENARIO_ORDER)
            elif name in SCENARIO_ORDER:
                selected.add(name)
            else:
                allowed = ", ".join(("all",) + SCENARIO_ORDER)
                raise MeasurementError(f"unknown scenario {name!r}; choose from {allowed}")
    return [scenario for scenario in SCENARIO_ORDER if scenario in selected]


def positive_int(value: str) -> int:
    number = int(value, 10)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not (number > 0.0):
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def resolve_executable(value: str) -> str:
    expanded = os.path.expanduser(value)
    display = os.path.basename(expanded) or "dawnc"
    if os.sep in expanded:
        candidate = os.path.realpath(expanded)
    else:
        found = shutil.which(expanded)
        if found is None:
            raise MeasurementError(f"dawnc executable not found: {display}")
        candidate = os.path.realpath(found)
    if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
        raise MeasurementError(f"dawnc is not an executable file: {display}")
    return candidate


def binary_version(executable: str, timeout: float) -> str:
    environment = os.environ.copy()
    environment.pop("DAWN_STD", None)
    try:
        result = subprocess.run(
            [executable, "--version"],
            cwd="/",
            env=environment,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise MeasurementError(
            f"dawnc --version failed ({type(error).__name__})"
        ) from error
    version = result.stdout.strip()
    if not version or not version.startswith("dawnc ") or "(native)" not in version:
        raise MeasurementError(
            "dawnc --version did not return one 'dawnc ... (native)' line"
        )
    if "\n" in version or "\r" in version:
        raise MeasurementError("dawnc --version returned multiple lines")
    return version


def open_output(value: str) -> tuple[TextIO, bool]:
    if value == "-":
        return sys.stdout, False
    path = Path(value).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("x", encoding="utf-8", newline=""), True
    except FileExistsError as error:
        raise MeasurementError(f"refusing to overwrite output: {path.name}") from error
    except OSError as error:
        raise MeasurementError(
            f"cannot create output {path.name} ({type(error).__name__})"
        ) from error


def self_test() -> None:
    source = exact_64k_source()
    assert len(source.encode("utf-8")) == SOURCE_LIMIT_BYTES
    assert source.startswith("pub fn main() -> Unit = ()\n#")
    assert source.endswith("\n")

    first = {"jsonrpc": "2.0", "id": 7, "result": "🎈"}
    second = note("initialized", {})
    encoded = frame(first) + frame(second)
    first_body = compact_json(first)
    assert encoded.startswith(b"Content-Length: %d\r\n\r\n" % len(first_body))
    decoder = FrameDecoder()
    decoded: list[dict[str, Any]] = []
    for index in range(0, len(encoded), 3):
        decoder.feed(encoded[index : index + 3])
        while True:
            item = decoder.pop()
            if item is None:
                break
            decoded.append(item)
    assert decoded == [first, second]
    assert decoder.buffer == bytearray()

    bad = FrameDecoder()
    bad.feed(b"Content-Length: 1\r\nContent-Length: 2\r\n\r\n{}")
    try:
        bad.pop()
    except MeasurementError:
        pass
    else:
        raise AssertionError("conflicting Content-Length was accepted")

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "capabilities": {
                "textDocumentSync": 1,
                "completionProvider": {},
                "hoverProvider": True,
                "definitionProvider": True,
            }
        },
    }
    validate_initialize(initialize, 1)
    diagnostics = {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": URI, "diagnostics": []},
    }
    assert validate_diagnostics(diagnostics) == []
    assert parse_proc_status("VmRSS:\t123 kB\nVmHWM:\t456 kB\n") == {
        "VmRSS": 123,
        "VmHWM": 456,
    }
    stat_fields = ["S"] + ["0"] * 10 + ["12", "3"]
    assert parse_proc_stat("99 (name with space) " + " ".join(stat_fields)) == (12, 3)
    assert public_cgroup_label("/user.slice/user-1000.slice/session-44.scope") == (
        "user.slice/user-<id>.slice/session-<id>.scope"
    )
    redacted = public_error(
        MeasurementError("failed at /home/example/work and 192.0.2.1"),
        "/home/example/work/dawnc",
    )
    assert "/home/example" not in redacted and "192.0.2.1" not in redacted

    fake_args = argparse.Namespace(
        timeout=15.0, idle_seconds=60.0, sample_interval=0.1
    )
    row = blank_row({}, "idle", "self-test", 1, fake_args)
    assert tuple(row) == COLUMNS
    sink = io.StringIO(newline="")
    writer = csv.DictWriter(sink, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)
    parsed = list(csv.DictReader(io.StringIO(sink.getvalue()), delimiter="\t"))
    assert len(parsed) == 1 and tuple(parsed[0]) == COLUMNS
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-measure-") as temp:
        sample_dir = Path(temp)
        expected_samples = []
        for name in SAMPLE_NAMES:
            source = f"# {name}\n"
            (sample_dir / f"{name}.dawn").write_text(source, encoding="utf-8")
            expected_samples.append(("sample", name, source))
        explicit_samples = parser().parse_args(
            ["--self-test", "--samples", os.fspath(sample_dir)]
        )
        assert explicit_samples.samples == sample_dir
        assert cases_for(["samples"], explicit_samples.samples) == expected_samples
        # The failure has to name the directory it searched. A mistyped
        # --samples and the deployed default differ only in the directory, so
        # a basename-only message reads the same for both.
        missing = sample_dir / "absent"
        try:
            cases_for(["samples"], missing)
        except MeasurementError as error:
            assert os.fspath(missing) in str(error), str(error)
        else:
            raise AssertionError("a missing sample directory was accepted")
    print("lsp-measure self-test ok")


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(
        description="Measure fresh direct-native Dawn LSP sessions into raw TSV."
    )
    out.add_argument("--dawnc", help="path to the release native dawnc executable")
    out.add_argument("--output", help="new raw TSV path, or '-' for stdout")
    out.add_argument(
        "--host-label",
        default="local",
        help="non-sensitive host label written to TSV (default: local)",
    )
    out.add_argument(
        "--harness-commit",
        help="public commit/ref label to record instead of local Git auto-detection",
    )
    out.add_argument(
        "--iterations",
        type=positive_int,
        default=DEFAULT_ITERATIONS,
        help=f"fresh processes per case (default: {DEFAULT_ITERATIONS})",
    )
    out.add_argument(
        "--scenario",
        action="append",
        help="repeat or comma-separate: all, idle, samples, source-64k, burst, features, disconnect",
    )
    out.add_argument(
        "--samples",
        type=Path,
        default=DEFAULT_SAMPLE_DIR,
        metavar="DIR",
        help="editor sample directory (default: repository site/play-ui/samples)",
    )
    out.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"strict per-operation timeout seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    out.add_argument(
        "--idle-seconds",
        type=positive_float,
        default=DEFAULT_IDLE_SECONDS,
        help=f"idle observation seconds (default: {DEFAULT_IDLE_SECONDS:g})",
    )
    out.add_argument(
        "--burst-updates",
        type=positive_int,
        default=DEFAULT_BURST_UPDATES,
        help=(
            "local edit generations coalesced by the one-in-flight rule "
            f"(default: {DEFAULT_BURST_UPDATES}; two Full sync messages cross the wire)"
        ),
    )
    out.add_argument(
        "--sample-interval",
        type=positive_float,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
        help=f"/proc PSS sampling interval (default: {DEFAULT_SAMPLE_INTERVAL_SECONDS:g})",
    )
    out.add_argument(
        "--self-test",
        action="store_true",
        help="exercise byte/framing/parser/TSV invariants without dawnc",
    )
    return out


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        if sys.flags.optimize:
            raise MeasurementError("--self-test requires Python assertions (do not use -O)")
        self_test()
        return 0
    if platform.system() != "Linux" or not Path("/proc/self/status").exists():
        raise MeasurementError("resource measurements require Linux /proc")
    if not args.dawnc or not args.output:
        raise MeasurementError("--dawnc and --output are required unless --self-test is used")
    if args.burst_updates < 2:
        raise MeasurementError("--burst-updates must be at least 2")
    if args.iterations < DEFAULT_ITERATIONS:
        print(
            f"warning: {args.iterations} iterations is a preflight, not the >=10-run admission gate",
            file=sys.stderr,
        )

    executable = resolve_executable(args.dawnc)
    version = binary_version(executable, args.timeout)
    public_label = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
    if public_label.fullmatch(args.host_label) is None:
        raise MeasurementError(
            "--host-label must be a simple non-sensitive label (letters, digits, ._- )"
        )
    if (
        args.harness_commit is not None
        and public_label.fullmatch(args.harness_commit) is None
    ):
        raise MeasurementError(
            "--harness-commit must be a simple hex/ref label without paths or whitespace"
        )
    common = common_metadata(
        executable, version, args.host_label, args.harness_commit
    )
    scenarios = resolve_scenarios(args.scenario)
    cases = cases_for(scenarios, args.samples)
    stream, should_close = open_output(args.output)
    rows = 0
    try:
        writer = csv.DictWriter(
            stream,
            fieldnames=COLUMNS,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        stream.flush()
        for scenario, case, source in cases:
            for iteration in range(1, args.iterations + 1):
                row, failure = run_one(
                    executable, common, scenario, case, iteration, source, args
                )
                writer.writerow(row)
                stream.flush()
                rows += 1
                print(
                    f"[{rows}] {scenario}/{case} {iteration}/{args.iterations}: {row['status']}",
                    file=sys.stderr,
                )
                if failure is not None:
                    raise failure
    finally:
        if should_close:
            stream.close()
    output_label = "stdout" if args.output == "-" else Path(args.output).name
    print(f"wrote {rows} fresh-process rows to {output_label}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MeasurementError, TimeoutError) as error:
        print(f"lsp-measure: {error}", file=sys.stderr)
        raise SystemExit(1) from None

#!/usr/bin/env python3
"""Black-box contract for the bounded Playground WebSocket/LSP gateway."""

import base64
import csv
import hashlib
import json
import os
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATEWAY = os.path.join(ROOT, "playground", "lsp_gateway.py")
FAKE = os.path.join(ROOT, "playground", "test", "fake_lsp.py")
SMOKE = os.path.join(ROOT, "playground", "deploy", "lsp-smoke.py")
DEPLOY = os.path.join(ROOT, "playground", "deploy")
SANDBOX = os.path.join(ROOT, "playground", "sandbox")
MEASUREMENT = os.path.join(
    ROOT,
    "playground",
    "test",
    "lsp-measurements",
    "2026-08-30-win-wsl2.tsv",
)
ORIGIN = "http://play.test"
PROTOCOL = "dawn-lsp-v1"
URI = "untitled:dawn-playground/prog.dawn"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read_exact(stream, size):
    parts = []
    left = size
    while left:
        part = stream.recv(left)
        if not part:
            raise AssertionError("socket closed inside a frame")
        parts.append(part)
        left -= len(part)
    return b"".join(parts)


def read_header(stream):
    data = bytearray()
    while not data.endswith(b"\r\n\r\n"):
        part = stream.recv(1)
        if not part:
            raise AssertionError("socket closed inside HTTP response")
        data.extend(part)
        if len(data) > 8192:
            raise AssertionError("HTTP response header is oversized")
    return bytes(data)


def upgrade(port, *, origin=ORIGIN, protocol=PROTOCOL, path="/lsp"):
    stream = socket.create_connection(("127.0.0.1", port), timeout=3)
    stream.settimeout(3)
    key = base64.b64encode(b"0123456789abcdef").decode("ascii")
    lines = [
        "GET %s HTTP/1.1" % path,
        "Host: play.test",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Version: 13",
        "Sec-WebSocket-Key: %s" % key,
    ]
    if origin is not None:
        lines.append("Origin: %s" % origin)
    if protocol is not None:
        lines.append("Sec-WebSocket-Protocol: %s" % protocol)
    stream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    response = read_header(stream)
    if response.startswith(b"HTTP/1.1 101 "):
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest())
        assert b"Sec-WebSocket-Accept: " + expected + b"\r\n" in response, response
        assert b"Sec-WebSocket-Protocol: " + PROTOCOL.encode() + b"\r\n" in response, response
    return stream, response


def upgrade_when_available(port, timeout=3):
    deadline = time.monotonic() + timeout
    while True:
        stream, response = upgrade(port)
        if response.startswith(b"HTTP/1.1 101 "):
            return stream, response
        stream.close()
        if not response.startswith(b"HTTP/1.1 503 ") or time.monotonic() >= deadline:
            raise AssertionError("gateway did not admit a session: %r" % response)
        time.sleep(0.02)


class WebSocket:
    def __init__(self, stream):
        self.stream = stream

    def send_frame(self, opcode, payload=b"", *, fin=True, masked=True):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        first = (0x80 if fin else 0) | opcode
        marker = 0x80 if masked else 0
        length = len(payload)
        if length < 126:
            header = bytes((first, marker | length))
        elif length <= 0xFFFF:
            header = bytes((first, marker | 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, marker | 127)) + struct.pack("!Q", length)
        if masked:
            mask = b"\x12\x34\x56\x78"
            payload = bytes(value ^ mask[index & 3] for index, value in enumerate(payload))
            header += mask
        self.stream.sendall(header + payload)

    def send_json(self, message):
        self.send_frame(1, json.dumps(message, separators=(",", ":")))

    def recv_frame(self):
        first, second = read_exact(self.stream, 2)
        assert not first & 0x70, "server set an RSV bit"
        assert not second & 0x80, "server frame was masked"
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", read_exact(self.stream, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read_exact(self.stream, 8))[0]
        return bool(first & 0x80), first & 0x0F, read_exact(self.stream, length)

    def recv_json(self):
        while True:
            fin, opcode, payload = self.recv_frame()
            if opcode == 9:
                self.send_frame(10, payload)
                continue
            assert fin and opcode == 1, (fin, opcode, payload)
            return json.loads(payload)

    def expect_close(self, code):
        while True:
            _, opcode, payload = self.recv_frame()
            if opcode == 9:
                self.send_frame(10, payload)
                continue
            assert opcode == 8 and len(payload) >= 2, (opcode, payload)
            actual = struct.unpack("!H", payload[:2])[0]
            assert actual == code, (actual, payload[2:])
            return

    def close(self):
        self.send_frame(8, struct.pack("!H", 1000))
        self.expect_close(1000)
        self.stream.close()


def rpc(request_id, method, params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def note(method, params):
    return {"jsonrpc": "2.0", "method": method, "params": params}


def position_params(uri=URI):
    return {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 1}}


def initialize(ws, request_id=1):
    message = rpc(request_id, "initialize", {
        "processId": 999,
        "rootUri": "file:///must/not/reach/dawnc",
        "capabilities": {"workspace": {"configuration": True}},
    })
    body = json.dumps(message, separators=(",", ":")).encode()
    split = len(body) // 2
    ws.send_frame(1, body[:split], fin=False)
    ws.send_frame(0, body[split:])
    response = ws.recv_json()
    assert response.get("id") == request_id
    capabilities = response.get("result", {}).get("capabilities")
    assert set(capabilities or {}) == {
        "positionEncoding",
        "textDocumentSync",
        "completionProvider",
        "hoverProvider",
        "definitionProvider",
    }, response
    ws.send_json(note("initialized", {"untrusted": True}))


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true")


def read_audit(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def ok(label):
    print("  ok  " + label)


def read_text(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def deployment_contract():
    """Pin the checked-in production boundary without needing root/systemd."""
    service = read_text(os.path.join(DEPLOY, "dawn-play-lsp.service"))
    unit_slice = read_text(os.path.join(DEPLOY, "dawn-play-lsp.slice"))
    nginx = read_text(os.path.join(DEPLOY, "nginx-play.conf"))
    wrapper = read_text(os.path.join(SANDBOX, "run-lsp-sandboxed.sh"))
    sudoers = read_text(os.path.join(SANDBOX, "sudoers.dawn-play"))
    redeploy = read_text(os.path.join(DEPLOY, "redeploy.sh"))

    for line in (
        "Environment=PLAY_LSP_HOST=127.0.0.1",
        "Environment=PLAY_LSP_PORT=8088",
        "Environment=PLAY_LSP_ORIGINS=https://dawn-lang.dawnop.com",
        "Environment=PLAY_LSP_MAX_SESSIONS=2",
        "Environment=PLAY_LSP_SOURCE_BYTES=65536",
        "Environment=PLAY_LSP_MESSAGE_BYTES=262144",
        "Environment=PLAY_LSP_IDLE_SECONDS=600",
        "Environment=PLAY_LSP_LIFETIME_SECONDS=1800",
        "Environment=PLAY_LSP_SETUP_SECONDS=15",
        "Environment=PLAY_LSP_SANDBOX_SCRIPT=/opt/dawn/playground/sandbox/run-lsp-sandboxed.sh",
        "ExecStartPre=/usr/bin/test -x /opt/dawn/bin/dawnc",
        "ExecStart=/usr/bin/python3 -I -B /opt/dawn/playground/lsp_gateway.py",
    ):
        assert line in service, line
    assert "MemoryMax=512M" in unit_slice
    assert "TasksMax=48" in unit_slice

    for line in (
        "location = /api/lsp {",
        "proxy_pass http://127.0.0.1:8088/lsp;",
        "proxy_set_header Origin $http_origin;",
        "proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;",
        "proxy_buffering off;",
        "proxy_request_buffering off;",
    ):
        assert line in nginx, line

    for line in (
        "--property=Slice=dawn-play-lsp.slice",
        "--property=DynamicUser=yes",
        "--property=PrivateNetwork=yes",
        "--property=NoNewPrivileges=yes",
        "--property=CapabilityBoundingSet=",
        "--property=MemoryMax=256M",
        "--property=RuntimeMaxSec=31m",
        "-- /opt/dawn/bin/dawnc lsp",
    ):
        assert line in wrapper, line
    invalid_id = subprocess.run(
        [os.path.join(SANDBOX, "run-lsp-sandboxed.sh"), "run", "../bad"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=2,
    )
    assert invalid_id.returncode == 2, invalid_id.stdout

    assert sudoers.count("NOPASSWD:") == 2
    assert sudoers.count(
        "/opt/dawn/playground/sandbox/run-lsp-sandboxed.sh"
    ) == 1
    assert '*) NATIVE_BIN="$PWD/$NATIVE_BIN" ;;' in redeploy
    assert 'NATIVE_VERSION=$("$NATIVE_BIN" version)' in redeploy
    # The unit is present on the production host, so only the other branch can
    # be exercised here; pin the present one by text.
    for line in (
        "sudo systemctl restart dawn-play dawn-play-lsp",
        "sudo systemctl is-active --quiet dawn-play-lsp",
        "/usr/bin/python3 -I -B /opt/dawn/playground/deploy/lsp-smoke.py",
    ):
        assert line in redeploy, line

    # Rollback has to survive a reboot: step 6 installs both units with
    # `enable --now`, so stopping them alone leaves the endpoint coming back
    # up with the machine.
    deploy_doc = read_text(os.path.join(DEPLOY, "DEPLOY.md"))
    rollback = deploy_doc[deploy_doc.index("## Rollback"):]
    assert "systemctl disable --now dawn-play dawn-play-lsp" in rollback, rollback
    assert "systemctl stop dawn-play dawn-play-lsp" not in rollback, rollback
    ok("deployment route, cgroup, sudo, rollback and native-artifact boundaries are pinned")


def remote_restart_contract():
    """Run redeploy.sh's remote half where the LSP unit was never installed.

    The restart is the one part of the deploy that has no dry run: it happens
    over ssh, on the far side, after the rsyncs have already landed. Under
    `set -e` an unconditional `restart dawn-play-lsp` turned "this host has not
    done DEPLOY.md step 6 yet" into a failed deploy. Stubs stand in for
    systemctl, sudo, curl and sleep, so the branch runs here instead of only
    on a host nobody has.
    """
    redeploy = read_text(os.path.join(DEPLOY, "redeploy.sh"))
    start = redeploy.index("REMOTE_RESTART='") + len("REMOTE_RESTART='")
    script = redeploy[start:redeploy.index("'\n", start)]
    assert "systemctl cat dawn-play-lsp.service" in script, script

    with tempfile.TemporaryDirectory(prefix="dawn-lsp-restart-") as temp:
        log = os.path.join(temp, "commands")
        stubs = os.path.join(temp, "bin")
        os.mkdir(stubs)
        for name, body in (
            # `systemctl cat` fails the way it does on a host without the unit.
            ("systemctl", 'printf "%s\\n" "systemctl $*" >>"$LOG"\n'
                          'case "$1" in cat) exit 1 ;; esac\nexit 0\n'),
            ("sudo", 'printf "%s\\n" "sudo $*" >>"$LOG"\nexec "$@"\n'),
            ("curl", 'printf "%s\\n" "curl $*" >>"$LOG"\necho ok\n'),
            ("sleep", "exit 0\n"),
        ):
            path = os.path.join(stubs, name)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("#!/bin/sh\n" + body)
            os.chmod(path, 0o755)
        result = subprocess.run(
            ["/bin/sh", "-c", script],
            env={"PATH": stubs + ":/usr/bin:/bin", "LOG": log},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        commands = read_text(log) if os.path.exists(log) else ""

    assert result.returncode == 0, (result.returncode, result.stdout)
    assert "DEPLOY.md step 6" in result.stdout, result.stdout
    assert "sudo systemctl restart dawn-play\n" in commands, commands
    assert "restart dawn-play dawn-play-lsp" not in commands, commands
    assert "is-active" not in commands, commands
    # The runner still gets restarted and health-checked, absent unit or not.
    assert "8087/health" in commands, commands
    ok("a redeploy to a host without the LSP unit skips it and says so")


def measurement_evidence_contract():
    """Keep the checked-in 10x development evidence complete and public-safe."""
    with open(MEASUREMENT, encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)
    required = {
        "scenario", "case", "iteration", "status", "error", "source_bytes",
        "diagnostics_latency_ms", "cleanup_time_ms", "exit_code", "reaped",
        "binary_name", "binary_version", "harness_commit", "host",
        "cgroup_version", "cgroup_memory_max", "cgroup_memory_swap_max",
        "cgroup_cpu_max", "cgroup_pids_max",
    }
    assert reader.fieldnames is not None and required <= set(reader.fieldnames)
    assert not ({"source", "source_text", "body", "uri"} & set(reader.fieldnames))
    expected = {
        ("idle", "initialized-no-document"): 10,
        ("sample", "comptime"): 10,
        ("sample", "effects"): 10,
        ("sample", "hello"): 10,
        ("sample", "shapes"): 10,
        ("sample", "traits"): 10,
        ("source-64k", "exact-valid-65536-bytes"): 10,
        ("burst", "burst"): 10,
        ("features", "features"): 10,
        ("disconnect", "disconnect"): 10,
    }
    observed = {}
    for row in rows:
        key = (row["scenario"], row["case"])
        observed[key] = observed.get(key, 0) + 1
        assert row["status"] == "ok" and row["error"] == ""
        assert row["reaped"] == "true" and row["exit_code"] == "0"
        assert row["binary_name"] == "dawnc-exact"
        assert row["binary_version"] == "dawnc 0.70.0 (native)"
        assert row["harness_commit"] == "27945626"
        assert row["host"] == "win-wsl2"
        assert (
            row["cgroup_version"],
            row["cgroup_memory_max"],
            row["cgroup_memory_swap_max"],
            row["cgroup_cpu_max"],
            row["cgroup_pids_max"],
        ) == ("v2", "268435456", "0", "100000 100000", "16")
        public = "\t".join(row.values())
        for private in ("/home/", "/Users/", "\\Users\\", "127.0.0.1"):
            assert private not in public
    assert observed == expected and len(rows) == 100
    assert all(
        row["source_bytes"] == "65536"
        for row in rows if row["scenario"] == "source-64k"
    )
    assert max(
        float(row["diagnostics_latency_ms"])
        for row in rows if row["scenario"] == "sample"
    ) < 3000
    assert max(
        float(row["cleanup_time_ms"])
        for row in rows if row["scenario"] == "disconnect"
    ) < 2000
    ok("10x native measurement evidence is complete, bounded and public-safe")


def main():
    deployment_contract()
    remote_restart_contract()
    measurement_evidence_contract()
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-contract-") as temp:
        audit_path = os.path.join(temp, "audit.jsonl")
        log_path = os.path.join(temp, "gateway.log")
        environment = os.environ.copy()
        environment.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "PLAY_LSP_HOST": "127.0.0.1",
            "PLAY_LSP_PORT": str(port),
            "PLAY_LSP_ORIGINS": ORIGIN,
            "PLAY_LSP_MAX_SESSIONS": "2",
            "PLAY_LSP_SOURCE_BYTES": "64",
            "PLAY_LSP_MESSAGE_BYTES": "4096",
            "PLAY_LSP_IDLE_SECONDS": "15",
            "PLAY_LSP_LIFETIME_SECONDS": "20",
            "PLAY_LSP_SETUP_SECONDS": "1",
            "PLAY_LSP_HANDSHAKE_SECONDS": "2",
            "PLAY_LSP_PING_SECONDS": "10",
            "PLAY_LSP_SHUTDOWN_SECONDS": "1",
            "PLAY_LSP_UNSAFE_LOCAL": "1",
            "PLAY_LSP_CHILD": "%s -B %s" % (
                shlex.quote(sys.executable), shlex.quote(FAKE)
            ),
            "FAKE_LSP_AUDIT": audit_path,
        })
        with open(log_path, "wb") as log:
            gateway = subprocess.Popen(
                [sys.executable, "-B", GATEWAY],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        busy_smoke = None
        try:
            def listening():
                if gateway.poll() is not None:
                    raise AssertionError("gateway exited before listening")
                try:
                    probe = socket.create_connection(("127.0.0.1", port), timeout=0.1)
                    probe.close()
                    return True
                except OSError:
                    return False

            wait_until(listening)

            stream, response = upgrade(port, path="/api/lsp")
            assert response.startswith(b"HTTP/1.1 400 "), response
            stream.close()
            ok("only nginx-rewritten /lsp is accepted")

            stream, response = upgrade(port, origin="https://evil.invalid")
            assert response.startswith(b"HTTP/1.1 403 "), response
            stream.close()
            # A disjoint origin is refused by exact matching and by substring
            # matching alike, so it cannot tell the two apart. These two carry
            # an allowed origin inside them and separate the rules: only exact
            # matching refuses them. Registrable-suffix confusion
            # (play.test.evil.invalid is owned by evil.invalid) and a path
            # suffix, which is not part of an origin at all.
            for confusing in (ORIGIN + ".evil.invalid", ORIGIN + "/evil"):
                stream, response = upgrade(port, origin=confusing)
                assert response.startswith(b"HTTP/1.1 403 "), (confusing, response)
                stream.close()
            stream, response = upgrade(port, protocol=None)
            assert response.startswith(b"HTTP/1.1 403 "), response
            stream.close()
            stream, response = upgrade(port, protocol="DAWN-LSP-V1")
            assert response.startswith(b"HTTP/1.1 403 "), response
            stream.close()
            with open(log_path, encoding="utf-8", errors="replace") as stream_log:
                assert "child-start" not in stream_log.read()
            ok("Origin and dawn-lsp-v1 subprotocol are mandatory")

            smoke_environment = os.environ.copy()
            smoke_environment.update({
                "PLAY_LSP_SMOKE_PORT": str(port),
                "PLAY_LSP_SMOKE_ORIGIN": ORIGIN,
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            smoke = subprocess.run(
                [sys.executable, "-B", SMOKE],
                cwd=ROOT,
                env=smoke_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
            assert (
                smoke.returncode == 0
                and smoke.stdout == "dawn-play-lsp smoke ok\n"
            ), smoke.stdout
            ok("deployment smoke exercises handshake, child and diagnostics")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            ws = WebSocket(stream)
            initialize(ws)
            source = "pub fn main() -> Unit !io = println(\"hi\")"
            ws.send_json(note("textDocument/didOpen", {
                "textDocument": {
                    "uri": URI,
                    "languageId": "not-dawn",
                    "version": 1,
                    "text": source,
                }
            }))
            diagnostics = ws.recv_json()
            assert diagnostics["method"] == "textDocument/publishDiagnostics", diagnostics
            diagnostic = diagnostics["params"]["diagnostics"][0]
            assert "relatedInformation" not in diagnostic and "data" not in diagnostic

            ws.send_json(note("textDocument/didChange", {
                "textDocument": {"uri": URI, "version": 2},
                "contentChanges": [{"text": "pub fn main() -> Unit = ()"}],
            }))
            assert ws.recv_json()["method"] == "textDocument/publishDiagnostics"

            ws.send_json(rpc(2, "textDocument/completion", position_params()))
            assert ws.recv_json()["result"][0]["label"] == "println"
            ws.send_json(rpc(3, "textDocument/hover", position_params()))
            assert ws.recv_json()["result"]["contents"]["value"] == "Int"
            ws.send_json(rpc(4, "textDocument/definition", position_params()))
            definitions = ws.recv_json()["result"]
            assert [item["uri"] for item in definitions] == [URI], definitions

            ws.send_frame(9, b"contract-ping")
            fin, opcode, payload = ws.recv_frame()
            assert fin and opcode == 10 and payload == b"contract-ping"
            ws.close()
            wait_until(lambda: any(item.get("method") == "exit" for item in read_audit(audit_path)))

            audit = read_audit(audit_path)
            init = next(item for item in audit if item.get("method") == "initialize")
            assert init["params"] == {
                "processId": None,
                "rootUri": None,
                "capabilities": {"general": {"positionEncodings": ["utf-16"]}},
                "clientInfo": {"name": "dawn-playground", "version": "1"},
            }, init
            opened = next(item for item in audit if item.get("method") == "textDocument/didOpen")
            assert opened["params"]["textDocument"]["languageId"] == "dawn"
            ok("fragmentation, LSP lifecycle, sync, queries and one-buffer filtering")

            first_stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            second_stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            first = WebSocket(first_stream)
            second = WebSocket(second_stream)
            initialize(first, 60)
            initialize(second, 60)
            for ws, source in ((first, "pub const first = 1"), (second, "pub const second = 2")):
                ws.send_json(note("textDocument/didOpen", {
                    "textDocument": {"uri": URI, "version": 1, "text": source}
                }))
                assert ws.recv_json()["method"] == "textDocument/publishDiagnostics"
            first.send_json(rpc(61, "textDocument/completion", position_params()))
            second.send_json(rpc(61, "textDocument/hover", position_params()))
            assert first.recv_json()["result"][0]["label"] == "println"
            assert second.recv_json()["result"]["contents"]["value"] == "Int"
            first.close()
            second.close()
            ok("concurrent connections own independent children and request ids")

            held_stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            second_held_stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            held = WebSocket(held_stream)
            second_held = WebSocket(second_held_stream)
            for request_id, ws in ((70, held), (71, second_held)):
                initialize(ws, request_id)
                ws.send_json(note("textDocument/didOpen", {
                    "textDocument": {"uri": URI, "version": 1, "text": "()"}
                }))
                assert ws.recv_json()["method"] == "textDocument/publishDiagnostics"
            third, busy = upgrade(port)
            assert busy.startswith(b"HTTP/1.1 503 ") and b"Retry-After: 2\r\n" in busy, busy
            third.close()

            with open(log_path, encoding="utf-8", errors="replace") as stream_log:
                refused_before = stream_log.read().count("reason=busy")
            busy_smoke = subprocess.Popen(
                [sys.executable, "-B", SMOKE],
                cwd=ROOT,
                env=smoke_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            def smoke_was_refused():
                if busy_smoke.poll() is not None:
                    raise AssertionError("busy deploy smoke exited before retrying")
                with open(log_path, encoding="utf-8", errors="replace") as stream_log:
                    return stream_log.read().count("reason=busy") > refused_before

            wait_until(smoke_was_refused)
            held.close()
            second_held.close()
            ok("global session limit fails fast with Retry-After")
            busy_output, _ = busy_smoke.communicate(timeout=5)
            assert (
                busy_smoke.returncode == 0
                and busy_output == "dawn-play-lsp smoke ok\n"
            ), busy_output
            ok("deployment smoke retries only an explicit busy response")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            stalled = WebSocket(stream)
            other_stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            other_stalled = WebSocket(other_stream)
            stalled.expect_close(1001)
            other_stalled.expect_close(1001)
            stream.close()
            other_stream.close()
            replacement, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            WebSocket(replacement).close()
            ok("pre-open setup deadline releases an occupied session")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            invalid = WebSocket(stream)
            invalid.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 1, "text": "()"}
            }))
            invalid.expect_close(1008)
            stream.close()
            ok("out-of-order lifecycle is closed with policy violation")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            wrong_uri = WebSocket(stream)
            initialize(wrong_uri, 10)
            wrong_uri.send_json(note("textDocument/didOpen", {
                "textDocument": {
                    "uri": "file:///etc/passwd",
                    "version": 1,
                    "text": "()",
                }
            }))
            wrong_uri.expect_close(1008)
            stream.close()

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            second_document = WebSocket(stream)
            initialize(second_document, 11)
            second_document.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 1, "text": "()"}
            }))
            assert second_document.recv_json()["method"] == "textDocument/publishDiagnostics"
            second_document.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 2, "text": "()"}
            }))
            second_document.expect_close(1008)
            stream.close()

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            unlisted = WebSocket(stream)
            initialize(unlisted, 12)
            unlisted.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 1, "text": "()"}
            }))
            assert unlisted.recv_json()["method"] == "textDocument/publishDiagnostics"
            unlisted.send_json(rpc(13, "workspace/symbol", {}))
            unlisted.expect_close(1008)
            stream.close()
            ok("file/second documents and unlisted methods are rejected")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            oversized = WebSocket(stream)
            initialize(oversized, 20)
            oversized.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 1, "text": "x" * 65}
            }))
            oversized.expect_close(1009)
            stream.close()
            ok("UTF-8 source limit is enforced before dawnc")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            unmasked = WebSocket(stream)
            unmasked.send_frame(1, b"{}", masked=False)
            unmasked.expect_close(1002)
            stream.close()
            ok("unmasked client frames are rejected")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            binary = WebSocket(stream)
            binary.send_frame(2, b"{}")
            binary.expect_close(1003)
            stream.close()
            ok("binary WebSocket messages are rejected")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            too_large = WebSocket(stream)
            too_large.send_frame(1, b"x" * 4097)
            too_large.expect_close(1009)
            stream.close()
            ok("WebSocket message limit is enforced before JSON parsing")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            malformed = WebSocket(stream)
            malformed.send_frame(
                1,
                b'{"jsonrpc":"2.0","method":"initialize","params":{"x":NaN}}',
            )
            malformed.expect_close(1007)
            stream.close()
            ok("non-standard JSON constants are rejected")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            pending = WebSocket(stream)
            initialize(pending, 30)
            pending.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 1, "text": "()"}
            }))
            assert pending.recv_json()["method"] == "textDocument/publishDiagnostics"
            blocked_position = {
                "textDocument": {"uri": URI},
                "position": {"line": 99, "character": 0},
            }
            for request_id in range(31, 48):
                pending.send_json(rpc(request_id, "textDocument/completion", blocked_position))
            pending.expect_close(1008)
            stream.close()
            ok("pending LSP requests are bounded")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            broken_child = WebSocket(stream)
            initialize(broken_child, 40)
            broken_child.send_json(note("textDocument/didOpen", {
                "textDocument": {
                    "uri": URI,
                    "version": 1,
                    "text": "MALFORMED_CHILD_FRAME",
                }
            }))
            broken_child.expect_close(1011)
            stream.close()
            replacement, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            WebSocket(replacement).close()
            ok("malformed child framing closes and releases its session")

            stream, response = upgrade_when_available(port)
            assert response.startswith(b"HTTP/1.1 101 "), response
            active = WebSocket(stream)
            initialize(active, 50)
            active.send_json(note("textDocument/didOpen", {
                "textDocument": {"uri": URI, "version": 1, "text": "()"}
            }))
            assert active.recv_json()["method"] == "textDocument/publishDiagnostics"
            exits_before = sum(
                item.get("method") == "exit" for item in read_audit(audit_path)
            )
            gateway.terminate()
            try:
                gateway.wait(timeout=8)
            except subprocess.TimeoutExpired as error:
                with open(log_path, encoding="utf-8", errors="replace") as stream_log:
                    details = stream_log.read()
                raise AssertionError(
                    "SIGTERM did not stop gateway:\n" + details
                ) from error
            active.expect_close(1000)
            stream.close()
            wait_until(
                lambda: sum(
                    item.get("method") == "exit" for item in read_audit(audit_path)
                ) > exits_before
            )
            ok("SIGTERM gracefully reaps an active child")

        finally:
            if busy_smoke is not None and busy_smoke.poll() is None:
                busy_smoke.terminate()
                try:
                    busy_smoke.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    busy_smoke.kill()
                    busy_smoke.wait(timeout=3)
            if gateway.poll() is None:
                gateway.terminate()
                try:
                    gateway.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    gateway.kill()
                    gateway.wait(timeout=3)

        with open(log_path, "r", encoding="utf-8", errors="replace") as stream:
            gateway_log = stream.read()
        assert "SOURCE_CANARY_MUST_NOT_APPEAR" not in gateway_log, gateway_log
        assert "child-stderr bytes=" in gateway_log, gateway_log
        ok("child stderr contents are not logged")
    print("----")
    print("22 passed, 0 failed")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Black-box contract for Dawn LSP's byte framing.

The transcript differential validates JSON-RPC behavior after framing has
succeeded. This gate owns the boundary before that: raw header limits,
Content-Length grammar, fatal desynchronization, and pre-allocation rejection
on both server backends.

Usage: scripts/lsp-framing.py [server command...]  (default: ./bin/dawn lsp)
       scripts/lsp-framing.py --self-test
"""

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time


HEADER_MAX_BYTES = 8192
BODY_MAX_BYTES = 64 * 1024 * 1024
STARTUP_LIMIT_S = 120.0
FATAL_LIMIT_S = 5.0
REAP_LIMIT_S = 10.0
RSS_BODY_BYTES = 48 * 1024 * 1024
RSS_DELTA_LIMIT_KIB = 32 * 1024
HEADER_NAME_BYTES = frozenset(
    b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'*+-.^_`|~"
)

FIXED_PARSE_ERROR = {
    "jsonrpc": "2.0",
    "id": None,
    "error": {"code": -32700, "message": "Parse error"},
}


def json_body(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def frame(body, value=None, name=b"Content-Length"):
    if value is None:
        value = str(len(body)).encode("ascii")
    elif isinstance(value, str):
        value = value.encode("utf-8")
    return name + b": " + value + b"\r\n\r\n" + body


def initialize(request_id):
    return json_body({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {"capabilities": {}},
    })


def valid_header_name(name):
    return bool(name) and all(byte in HEADER_NAME_BYTES for byte in name)


def parse_wire_length(raw):
    digits = raw.strip(b" \t")
    if not digits or any(byte < ord("0") or byte > ord("9") for byte in digits):
        raise AssertionError("bad response Content-Length: %r" % raw)
    length = int(digits)
    if length > BODY_MAX_BYTES:
        raise AssertionError("response body exceeds %d bytes" % BODY_MAX_BYTES)
    return length


def parse_frames(data):
    """Parse every response under the same strict framing contract."""
    frames = []
    offset = 0
    while offset < len(data):
        header_end = data.find(b"\r\n\r\n", offset)
        if header_end < 0:
            if len(data) - offset >= HEADER_MAX_BYTES:
                raise AssertionError("response header exceeds %d bytes" % HEADER_MAX_BYTES)
            raise AssertionError("truncated response header: %r" % data[offset:offset + 120])
        header_bytes = header_end + 4 - offset
        if header_bytes > HEADER_MAX_BYTES:
            raise AssertionError("response header is %d bytes" % header_bytes)
        length = None
        for line in data[offset:header_end].split(b"\r\n"):
            colon = line.find(b":")
            if colon <= 0:
                raise AssertionError("malformed response header line: %r" % line)
            name = line[:colon]
            if not valid_header_name(name):
                raise AssertionError("malformed response header name: %r" % name)
            if name.lower() == b"content-length":
                parsed = parse_wire_length(line[colon + 1:])
                if length is not None and length != parsed:
                    raise AssertionError("conflicting response Content-Length fields")
                length = parsed
        if length is None:
            raise AssertionError("response omitted Content-Length")
        body_start = header_end + 4
        body_end = body_start + length
        if body_end > len(data):
            raise AssertionError("truncated response body: want %d bytes" % length)
        try:
            frames.append(json.loads(data[body_start:body_end]))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssertionError("response body is not JSON") from error
        offset = body_end
    return frames


def close_stream(stream):
    if stream is None:
        return
    try:
        stream.close()
    except OSError:
        pass


def kill_group(proc, pgid):
    """Kill the saved process group even when its launcher has already exited."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    close_stream(proc.stdin)
    try:
        proc.wait(timeout=REAP_LIMIT_S)
    except subprocess.TimeoutExpired as error:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired as second_error:
            raise AssertionError("launcher could not be reaped after SIGKILL") from second_error
        raise AssertionError("launcher outlived process-group SIGKILL") from error


def read_temp(output):
    output.seek(0)
    return output.read()


def run_closed(cmd, payload):
    """Run one closed-input stream, killing the whole group on timeout."""
    stdout_file = tempfile.TemporaryFile()
    stderr_file = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=stdout_file,
        stderr=stderr_file,
        start_new_session=True,
    )
    pgid = proc.pid
    try:
        try:
            proc.communicate(payload, timeout=STARTUP_LIMIT_S)
        except subprocess.TimeoutExpired as error:
            kill_group(proc, pgid)
            stderr = read_temp(stderr_file)
            raise AssertionError("server timed out; stderr=%r" % stderr[-400:]) from error
        stdout = read_temp(stdout_file)
        stderr = read_temp(stderr_file)
        if proc.returncode != 0:
            raise AssertionError(
                "server exited %d; stderr=%r" % (proc.returncode, stderr[-400:])
            )
        return parse_frames(stdout)
    finally:
        kill_group(proc, pgid)
        stdout_file.close()
        stderr_file.close()


class OpenServer:
    """Interactive server whose launcher and descendants share one kill group."""

    def __init__(self, cmd):
        self.stderr = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            start_new_session=True,
        )
        self.pgid = self.proc.pid
        self.stdout = bytearray()

    def send(self, payload):
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()

    def drain(self):
        while select.select([self.proc.stdout], [], [], 0)[0]:
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                break
            self.stdout.extend(chunk)

    def wait_for_frames(self, count, timeout_s):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.drain()
            try:
                if len(parse_frames(bytes(self.stdout))) >= count:
                    return True
            except AssertionError:
                pass
            if self.proc.poll() is not None:
                self.drain()
                return False
            time.sleep(0.01)
        return False

    def wait_for_exit(self, timeout_s, sample=None):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.drain()
            if sample is not None:
                sample()
            if self.proc.poll() is not None:
                self.drain()
                return True
            time.sleep(0.01)
        return False

    def error_tail(self):
        self.stderr.seek(0)
        return self.stderr.read()[-400:]

    def close(self):
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        kill_group(self.proc, self.pgid)
        self.drain()
        self.stderr.close()


def group_rss_kib(pgid):
    """Resident KiB for every Linux process in `pgid`, or None elsewhere."""
    if not sys.platform.startswith("linux") or not os.path.isdir("/proc"):
        return None
    total = 0
    found = False
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % entry, encoding="ascii") as stat_file:
                fields = stat_file.read().rsplit(") ", 1)[1].split()
            if int(fields[2]) != pgid:
                continue
            with open("/proc/%s/status" % entry, encoding="ascii") as status_file:
                for line in status_file:
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])
                        found = True
                        break
        except (FileNotFoundError, IndexError, OSError, ValueError):
            pass
    return total if found else None


def assert_initialize_response(value, request_id):
    if value.get("id") != request_id or "result" not in value:
        raise AssertionError("want initialize response id %r, got %r" % (request_id, value))


def expect_initialize(cmd, payload, request_id):
    frames = run_closed(cmd, payload)
    if len(frames) != 1:
        raise AssertionError("want one response, got %r" % frames)
    assert_initialize_response(frames[0], request_id)


def expect_frames(cmd, payload, expected):
    frames = run_closed(cmd, payload)
    if frames != expected:
        raise AssertionError("want %r, got %r" % (expected, frames))


def expect_fixed_fatal(cmd, payload):
    frames = run_closed(cmd, payload)
    if frames != [FIXED_PARSE_ERROR]:
        raise AssertionError("want one fixed parse error, got %r" % frames)


def expect_recovery(cmd, bad_body, request_id):
    frames = run_closed(cmd, frame(bad_body) + frame(initialize(request_id)))
    if len(frames) != 2:
        raise AssertionError("want parse error then initialize, got %r" % frames)
    first = frames[0]
    if first.get("id") is not None or first.get("error", {}).get("code") != -32700:
        raise AssertionError("want recoverable JSON parse error, got %r" % first)
    assert_initialize_response(frames[1], request_id)


def padded_header(total_bytes, body):
    prefix = b"X-Pad: "
    suffix = b"\r\nContent-Length: %d\r\n\r\n" % len(body)
    filler = total_bytes - len(prefix) - len(suffix)
    if filler < 0:
        raise AssertionError("header target is too small")
    header = prefix + b"x" * filler + suffix
    if len(header) != total_bytes:
        raise AssertionError("constructed header has the wrong size")
    return header + body


def expect_open_fatal(cmd, payload, request_id, flood_body=False):
    """A fatal header must answer and exit while the client keeps stdin open."""
    server = OpenServer(cmd)
    writer = None
    rss_note = "RSS unavailable"
    try:
        server.send(frame(initialize(request_id)))
        if not server.wait_for_frames(1, STARTUP_LIMIT_S):
            raise AssertionError(
                "server never completed warm-up; stderr=%r" % server.error_tail()
            )
        pgid = server.pgid
        baseline_rss = group_rss_kib(pgid)
        max_rss = [baseline_rss]

        server.send(payload)
        if flood_body:
            def write_body():
                chunk = b"x" * 65536
                remaining = RSS_BODY_BYTES
                try:
                    while remaining > 0:
                        take = min(remaining, len(chunk))
                        server.proc.stdin.write(chunk[:take])
                        server.proc.stdin.flush()
                        remaining -= take
                except (BrokenPipeError, OSError, ValueError):
                    pass

            writer = threading.Thread(target=write_body, daemon=True)
            writer.start()

        def sample_rss():
            current = group_rss_kib(pgid)
            if current is not None and (max_rss[0] is None or current > max_rss[0]):
                max_rss[0] = current

        if not server.wait_for_exit(FATAL_LIMIT_S, sample_rss):
            delta = None
            if baseline_rss is not None and max_rss[0] is not None:
                delta = max_rss[0] - baseline_rss
            raise AssertionError(
                "framing failure did not exit with stdin open%s"
                % ("; RSS grew %d KiB" % delta if delta is not None else "")
            )
        if server.proc.returncode != 0:
            raise AssertionError(
                "server exited %d; stderr=%r"
                % (server.proc.returncode, server.error_tail())
            )
        frames = parse_frames(bytes(server.stdout))
        if len(frames) != 2:
            raise AssertionError("want warm-up plus one fatal response, got %r" % frames)
        assert_initialize_response(frames[0], request_id)
        if frames[1] != FIXED_PARSE_ERROR:
            raise AssertionError("fatal response is not fixed: %r" % frames[1])

        if baseline_rss is not None and max_rss[0] is not None:
            delta = max_rss[0] - baseline_rss
            rss_note = "RSS delta %d KiB (limit %d KiB)" % (
                delta, RSS_DELTA_LIMIT_KIB,
            )
            if delta > RSS_DELTA_LIMIT_KIB:
                raise AssertionError(rss_note)
        elif not sys.platform.startswith("linux"):
            rss_note = "RSS check skipped off Linux"
        return rss_note
    finally:
        server.close()
        if writer is not None:
            writer.join(timeout=1)


def run_check(results, label, action):
    try:
        detail = action()
        results.append((label, True, detail or "ok"))
    except (AssertionError, BrokenPipeError, OSError, ValueError) as error:
        results.append((label, False, str(error)))


def expect_parsed_frames(data, expected):
    actual = parse_frames(data)
    if actual != expected:
        raise AssertionError("want %r, got %r" % (expected, actual))


def expect_frame_rejection(data):
    try:
        parse_frames(data)
    except AssertionError:
        return
    raise AssertionError("strict response parser accepted malformed framing")


def padded_response(total_bytes, body=b"{}"):
    prefix = b"X-Pad: "
    suffix = b"\r\nContent-Length: %d\r\n\r\n" % len(body)
    filler = total_bytes - len(prefix) - len(suffix)
    if filler < 0:
        raise AssertionError("response header target is too small")
    return prefix + b"x" * filler + suffix + body


def process_running(pid):
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/%d/stat" % pid, encoding="ascii") as stat_file:
                state = stat_file.read().rsplit(") ", 1)[1].split()[0]
            return state != "Z"
        except (FileNotFoundError, IndexError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def self_test_orphan_cleanup():
    launcher_code = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "print(child.pid, flush=True)\n"
    )
    launcher = subprocess.Popen(
        [sys.executable, "-c", launcher_code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    pgid = launcher.pid
    child_pid = None
    try:
        if not select.select([launcher.stdout], [], [], 5.0)[0]:
            raise AssertionError("cleanup fixture launcher produced no child pid")
        child_pid = int(launcher.stdout.readline())
        launcher.wait(timeout=5.0)
        if not process_running(child_pid):
            raise AssertionError("cleanup fixture child did not survive its launcher")
        kill_group(launcher, pgid)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and process_running(child_pid):
            time.sleep(0.01)
        if process_running(child_pid):
            raise AssertionError("saved process group left its orphan child running")
    finally:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        close_stream(launcher.stdout)
        close_stream(launcher.stderr)
        try:
            launcher.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            launcher.kill()
            launcher.wait(timeout=1.0)


def harness_self_tests():
    results = []
    run_check(results, "cleanup kills child after launcher exits", self_test_orphan_cleanup)
    run_check(results, "response parser accepts exact 8192-byte header", lambda:
              expect_parsed_frames(padded_response(HEADER_MAX_BYTES), [{}]))
    run_check(results, "response parser accepts duplicate equal lengths", lambda:
              expect_parsed_frames(
                  b"X-Test: ok\r\nContent-Length:\t2 \r\ncontent-length: 0002\r\n\r\n{}",
                  [{}],
              ))
    rejected = [
        ("response parser rejects last-wins conflict",
         b"Content-Length: 1\r\ncontent-length: 2\r\n\r\n{}"),
        ("response parser rejects signed length",
         b"Content-Length: +2\r\n\r\n{}"),
        ("response parser rejects 9000-byte header", padded_response(9000)),
        ("response parser rejects malformed line",
         b"NoColon\r\nContent-Length: 2\r\n\r\n{}"),
        ("response parser rejects empty field name",
         b": x\r\nContent-Length: 2\r\n\r\n{}"),
        ("response parser rejects oversized body",
         b"Content-Length: 67108865\r\n\r\n"),
        ("response parser rejects truncated body",
         b"Content-Length: 2\r\n\r\n{"),
        ("response parser rejects trailing bytes",
         b"Content-Length: 2\r\n\r\n{}x"),
    ]
    for case, payload in rejected:
        run_check(results, case, lambda payload=payload: expect_frame_rejection(payload))
    return results


def report_results(results):
    failures = 0
    for case, passed, detail in results:
        if passed:
            print("OK   %s: %s" % (case, detail))
        else:
            print("FAIL %s: %s" % (case, detail))
            failures += 1
    return failures


def main():
    self_test_only = sys.argv[1:] == ["--self-test"]
    harness_results = harness_self_tests()
    harness_failures = report_results(harness_results)
    if harness_failures:
        print("FAIL: %d/%d LSP framing harness checks failed" % (
            harness_failures, len(harness_results),
        ))
        return 1
    print("OK: %d LSP framing harness checks passed" % len(harness_results))
    if self_test_only:
        return 0

    cmd = sys.argv[1:] or ["./bin/dawn", "lsp"]
    label = os.environ.get("LSP_FRAMING_LABEL", os.path.basename(cmd[0]))
    results = []

    run_check(results, "clean EOF", lambda: expect_frames(cmd, b"", []))

    exact_id = 701
    exact_body = initialize(exact_id)
    run_check(results, "8192-byte completed header", lambda:
              expect_initialize(cmd, padded_header(HEADER_MAX_BYTES, exact_body), exact_id))
    run_check(results, "8193-byte completed header", lambda:
              expect_fixed_fatal(cmd, padded_header(HEADER_MAX_BYTES + 1, exact_body)))

    zero_id = 702
    run_check(results, "zero length is recoverable JSON", lambda:
              expect_recovery(cmd, b"", zero_id))

    shutdown = json_body({"id": 42, "method": "shutdown"})
    shutdown += b" " * (42 - len(shutdown))
    run_check(results, "leading-zero length", lambda: expect_frames(
        cmd,
        frame(shutdown, value="00042", name=b"cOnTeNt-LeNgTh"),
        [{"jsonrpc": "2.0", "id": 42, "result": None}],
    ))

    bad_values = [
        "", "+1", "-0", "1.0", "1e2", "1_0", "４",
        "9223372036854775808", "2147483648",
    ]
    for bad_value in bad_values:
        payload = frame(exact_body, value=bad_value) + frame(initialize(9999))
        run_check(results, "invalid length %r" % bad_value,
                  lambda payload=payload: expect_fixed_fatal(cmd, payload))

    same_header = (
        b"Content-Length: %d\r\nCONTENT-LENGTH:\t%05d \t\r\n\r\n"
        % (len(exact_body), len(exact_body))
    )
    run_check(results, "duplicate equal lengths", lambda:
              expect_initialize(cmd, same_header + exact_body, exact_id))

    conflict_header = (
        b"Content-Length: 1\r\ncontent-length: %d\r\n\r\n" % len(exact_body)
    )
    run_check(results, "duplicate conflicting lengths", lambda:
              expect_fixed_fatal(cmd, conflict_header + exact_body + frame(initialize(9999))))

    invalid_duplicate = (
        b"Content-Length: %d\r\ncontent-length: +%d\r\n\r\n"
        % (len(exact_body), len(exact_body))
    )
    run_check(results, "duplicate with one invalid length", lambda:
              expect_fixed_fatal(cmd, invalid_duplicate + exact_body + frame(initialize(9999))))

    run_check(results, "missing Content-Length", lambda:
              expect_fixed_fatal(cmd, b"X-Test: value\r\n\r\n" + frame(initialize(9999))))
    for malformed_line in [b"NoColon", b": value", b"Bad Name: value", b"Bad(Name): value"]:
        malformed_header = (
            malformed_line + b"\r\nContent-Length: %d\r\n\r\n" % len(exact_body)
        )
        payload = malformed_header + exact_body + frame(initialize(9999))
        run_check(results, "malformed header line %r" % malformed_line,
                  lambda payload=payload: expect_fixed_fatal(cmd, payload))
    run_check(results, "partial header", lambda:
              expect_fixed_fatal(cmd, b"Content-Len"))
    run_check(results, "partial body", lambda:
              expect_fixed_fatal(cmd, b"Content-Length: 2\r\n\r\n{"))
    run_check(results, "malformed JSON continues", lambda:
              expect_recovery(cmd, b"{", 703))
    run_check(results, "invalid UTF-8 continues", lambda:
              expect_recovery(cmd, b'"\x80"', 706))

    run_check(results, "incomplete header stops at 8192", lambda:
              expect_open_fatal(cmd, b"x" * HEADER_MAX_BYTES, 704))
    run_check(results, "oversized body rejects before allocation", lambda:
              expect_open_fatal(
                  cmd,
                  b"Content-Length: %d\r\n\r\n" % (BODY_MAX_BYTES + 1),
                  705,
                  flood_body=True,
              ))

    failures = report_results(results)
    if failures:
        print("FAIL: %d/%d LSP framing checks failed on %s" % (
            failures, len(results), label,
        ))
        return 1
    print("OK: %d LSP framing checks passed on %s" % (len(results), label))
    return 0


if __name__ == "__main__":
    sys.exit(main())

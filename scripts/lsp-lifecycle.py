#!/usr/bin/env python3
"""Black-box contract for Dawn LSP lifecycle sequencing.

The framing and liveness gates own byte boundaries and scheduling. This gate
owns the protocol phase before any document update or deferred analysis may be
observed: initialize, shutdown, exit, request rejection, and pending discard.

Usage: scripts/lsp-lifecycle.py [server command...]  (default ./bin/dawn lsp)
       scripts/lsp-lifecycle.py --case NAME [server command...]
"""
import json
import os
import subprocess
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TIMEOUT_S = 300.0


def request(request_id, method, params=None):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def notification(method, params=None):
    return {"jsonrpc": "2.0", "method": method, "params": params}


def initialize(request_id):
    return request(request_id, "initialize", {"capabilities": {}})


def text_document(uri):
    return {"textDocument": {"uri": uri}}


def did_open(uri, text):
    return notification("textDocument/didOpen", {
        "textDocument": {
            "uri": uri,
            "languageId": "dawn",
            "version": 1,
            "text": text,
        },
    })


def frame(message):
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def parse_frames(data):
    frames = []
    offset = 0
    while offset < len(data):
        header_end = data.find(b"\r\n\r\n", offset)
        if header_end < 0:
            raise AssertionError("truncated response header: %r" % data[offset:offset + 120])
        content_length = None
        for line in data[offset:header_end].split(b"\r\n"):
            name, separator, raw = line.partition(b":")
            if not separator:
                raise AssertionError("malformed response header: %r" % line)
            if name.lower() == b"content-length":
                content_length = int(raw.strip())
        if content_length is None:
            raise AssertionError("response omitted Content-Length")
        body_start = header_end + 4
        body_end = body_start + content_length
        if body_end > len(data):
            raise AssertionError("truncated response body")
        frames.append(json.loads(data[body_start:body_end]))
        offset = body_end
    return frames


def run_session(server, messages):
    payload = b"".join(frame(message) for message in messages)
    try:
        completed = subprocess.run(
            server,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError("server timed out") from error
    try:
        responses = parse_frames(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AssertionError("server emitted invalid response framing") from error
    return completed.returncode, responses, completed.stderr


def response_with_id(frames, request_id, label):
    found = [message for message in frames if message.get("id") == request_id]
    if len(found) != 1:
        raise AssertionError("%s: expected one response, got %r" % (label, found))
    return found[0]


def expect_result(frames, request_id, expected, label):
    response = response_with_id(frames, request_id, label)
    if response.get("result") != expected or "error" in response:
        raise AssertionError("%s: expected result %r, got %r" % (
            label, expected, response,
        ))


def expect_initialize(frames, request_id, label):
    response = response_with_id(frames, request_id, label)
    capabilities = response.get("result", {}).get("capabilities")
    if not isinstance(capabilities, dict) or "error" in response:
        raise AssertionError("%s: expected initialize result, got %r" % (label, response))


def expect_error(frames, request_id, code, message, label):
    response = response_with_id(frames, request_id, label)
    error = response.get("error")
    if error != {"code": code, "message": message} or "result" in response:
        raise AssertionError("%s: expected error %d, got %r" % (
            label, code, response,
        ))


def expect_exit(actual, expected, label):
    if actual != expected:
        raise AssertionError("%s exit status: expected %d, got %d" % (
            label, expected, actual,
        ))


def expect_no_notifications(frames):
    notifications = [message for message in frames if "method" in message]
    if notifications:
        raise AssertionError("unexpected server notification: %r" % notifications)


def expect_response_ids(frames, expected):
    actual = [message.get("id") for message in frames if "id" in message]
    if actual != expected:
        raise AssertionError("expected response ids %r, got %r" % (expected, actual))


def case_preinit_notification(server):
    uri = "untitled:dawn-lifecycle-preinit"
    status, frames, _ = run_session(server, [
        notification("initialized", {}),
        did_open(uri, "fn broken("),
        request(10, "textDocument/hover", text_document(uri)),
        initialize(11),
        request(12, "textDocument/hover", text_document(uri)),
        request(13, "shutdown"),
        notification("exit", {}),
    ])
    expect_exit(status, 0, "pre-init notification session")
    expect_error(frames, 10, -32002, "Server not initialized", "pre-init request")
    expect_initialize(frames, 11, "first initialize")
    expect_result(frames, 12, None, "request after initialize")
    expect_result(frames, 13, None, "shutdown")
    expect_response_ids(frames, [10, 11, 12, 13])
    expect_no_notifications(frames)


def case_repeat_initialize(server):
    status, frames, _ = run_session(server, [
        initialize(20),
        initialize(21),
        notification("initialize", {"capabilities": {}}),
        request(22, "shutdown"),
        notification("exit", {}),
    ])
    expect_exit(status, 0, "repeat initialize session")
    expect_initialize(frames, 20, "first initialize")
    expect_error(frames, 21, -32600, "Invalid Request", "repeat initialize")
    expect_result(frames, 22, None, "shutdown")
    expect_response_ids(frames, [20, 21, 22])
    expect_no_notifications(frames)


def case_shutdown_notification(server):
    uri = "untitled:dawn-lifecycle-shutdown-note"
    status, frames, _ = run_session(server, [
        initialize(30),
        notification("shutdown"),
        request(31, "textDocument/hover", text_document(uri)),
        request(32, "shutdown"),
        notification("exit", {}),
    ])
    expect_exit(status, 0, "shutdown notification session")
    expect_initialize(frames, 30, "initialize")
    expect_result(frames, 31, None, "request after shutdown notification")
    expect_result(frames, 32, None, "shutdown request")
    expect_response_ids(frames, [30, 31, 32])
    expect_no_notifications(frames)


def case_post_shutdown(server):
    uri = "untitled:dawn-lifecycle-post-shutdown"
    status, frames, _ = run_session(server, [
        initialize(40),
        request(41, "shutdown"),
        did_open(uri, "fn broken("),
        request(42, "textDocument/hover", text_document(uri)),
        notification("initialized", {}),
        notification("exit", {}),
    ])
    expect_exit(status, 0, "post-shutdown session")
    expect_initialize(frames, 40, "initialize")
    expect_result(frames, 41, None, "shutdown")
    expect_error(frames, 42, -32600, "Invalid Request", "request after shutdown")
    expect_response_ids(frames, [40, 41, 42])
    expect_no_notifications(frames)


def case_early_exit(server):
    status, frames, _ = run_session(server, [notification("exit", {})])
    expect_exit(status, 1, "pre-init")
    if frames:
        raise AssertionError("pre-init exit emitted responses: %r" % frames)

    status, frames, _ = run_session(server, [
        initialize(50),
        notification("exit", {}),
    ])
    expect_exit(status, 1, "running")
    expect_initialize(frames, 50, "initialize before early exit")
    expect_response_ids(frames, [50])
    expect_no_notifications(frames)


def case_normal_exit(server):
    status, frames, _ = run_session(server, [
        initialize(60),
        request(61, "shutdown"),
        notification("exit", {}),
    ])
    expect_exit(status, 0, "normal")
    expect_initialize(frames, 60, "initialize")
    expect_result(frames, 61, None, "shutdown")
    expect_response_ids(frames, [60, 61])
    expect_no_notifications(frames)


def case_pending_discard(server):
    uri = "untitled:dawn-lifecycle-pending"
    status, frames, _ = run_session(server, [
        initialize(70),
        did_open(uri, "fn broken("),
        request(71, "shutdown"),
        notification("exit", {}),
    ])
    expect_exit(status, 0, "pending discard session")
    expect_initialize(frames, 70, "initialize")
    expect_result(frames, 71, None, "shutdown")
    expect_response_ids(frames, [70, 71])
    expect_no_notifications(frames)


CASES = {
    "preinit-notification": case_preinit_notification,
    "repeat-initialize": case_repeat_initialize,
    "shutdown-notification": case_shutdown_notification,
    "post-shutdown": case_post_shutdown,
    "early-exit": case_early_exit,
    "normal-exit": case_normal_exit,
    "pending-discard": case_pending_discard,
}


def main():
    args = sys.argv[1:]
    selected = list(CASES)
    if args[:1] == ["--case"]:
        if len(args) < 2 or args[1] not in CASES:
            print("unknown lifecycle case: %s" % (args[1] if len(args) > 1 else ""),
                  file=sys.stderr)
            return 2
        selected = [args[1]]
        args = args[2:]
    server = args or ["./bin/dawn", "lsp"]
    failures = 0
    for name in selected:
        try:
            CASES[name](server)
            print("OK   %s" % name)
        except AssertionError as error:
            print("FAIL %s: %s" % (name, error))
            failures += 1
    if failures:
        print("FAIL: %d/%d LSP lifecycle checks failed" % (failures, len(selected)))
        return 1
    print("OK: %d LSP lifecycle checks passed" % len(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main())

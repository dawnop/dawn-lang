#!/usr/bin/env python3
"""Keep memory mutations outside the server so the oracle can test itself.

The transient mode touches more than the budget without retaining it. The
other modes must fail for retention and for allocation on a fatal header.
"""

import json
import sys
import time


mode = sys.argv[1]
held = []
while True:
    header = bytearray()
    while not header.endswith(b"\r\n\r\n") and len(header) < 8192:
        byte = sys.stdin.buffer.read(1)
        if not byte:
            sys.exit(0)
        header.extend(byte)
    fatal = not header.endswith(b"\r\n\r\n")
    if mode == "retain":
        held.append(bytearray(8 * 1024 * 1024))
    elif mode == "transient" or (mode == "fatal-allocation" and fatal):
        allocation = bytearray(48 * 1024 * 1024)
        # Make the real resident allocation observable, independent of dispatch.
        until = time.process_time() + 0.05
        while time.process_time() < until:
            pass
        if not fatal:
            del allocation
    if fatal:
        response = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "Parse error"}}
    else:
        length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                      if line.lower().startswith(b"content-length:"))
        request = json.loads(sys.stdin.buffer.read(length))
        response = {"jsonrpc": "2.0", "id": request["id"], "result": {}}
    body = json.dumps(response, separators=(",", ":")).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()
    if fatal:
        sys.exit(0)

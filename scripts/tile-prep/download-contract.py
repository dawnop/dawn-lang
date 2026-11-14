#!/usr/bin/env python3
"""One time recovery fixtures, including a progressing transfer over 120s."""
import contextlib
import hashlib
import http.server
import importlib.util
import io
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

spec = importlib.util.spec_from_file_location('tile_full', Path(__file__).with_name('full.py'))
full = importlib.util.module_from_spec(spec)
spec.loader.exec_module(full)
# The fixture server is local even when the developer shell uses a proxy.
os.environ['no_proxy'] = '127.0.0.1,localhost'
os.environ['NO_PROXY'] = '127.0.0.1,localhost'
PAYLOAD = b'x' * (2048 * 123)
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
state = dict(mode='', requests=0)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        state['requests'] += 1
        attempt = state['requests']
        mode = state['mode']
        if mode == 'failure' or mode in ('recovery', 'upstream') and attempt <= 3:
            self.send_error(503)
            return
        if mode == 'upstream':
            self.send_response(302)
            self.send_header('Location', full.JDK_URL)
            self.end_headers()
            return
        if mode == 'permanent':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(PAYLOAD)))
        self.end_headers()
        try:
            if mode == 'zero':
                time.sleep(4)
            elif mode == 'drip':
                for _ in range(30):
                    self.wfile.write(b'x' * 16)
                    self.wfile.flush()
                    time.sleep(.15)
            elif mode == 'reset' and attempt == 1:
                self.wfile.write(PAYLOAD[:128])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
            elif mode == 'progress':
                for i in range(123):
                    self.wfile.write(PAYLOAD[i * 2048:(i + 1) * 2048])
                    self.wfile.flush()
                    if i < 122:
                        time.sleep(1)
            else:
                self.wfile.write(PAYLOAD)
        except (BrokenPipeError, ConnectionResetError):
            pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}/jdk'
try:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for mode, success, requests in [('zero', False, 6), ('drip', False, 6),
                ('reset', True, 2), ('recovery', True, 4), ('failure', False, 6),
                ('permanent', False, 2), ('checksum', False, 1), ('progress', True, 1)]:
            state.update(mode=mode, requests=0)
            cache = root / mode
            started = time.monotonic()
            stream = io.StringIO()
            ok = True
            with contextlib.redirect_stdout(stream):
                try:
                    result = full.download(url, '0' * 64 if mode == 'checksum' else DIGEST,
                        cache, speed_time=45 if mode == 'progress' else 1,
                        attempt_delay=.01, stage_delay=.01)
                    assert full.sha(result) == DIGEST
                except RuntimeError:
                    ok = False
            elapsed = time.monotonic() - started
            print(stream.getvalue(), end='', flush=True)
            assert ok == success and state['requests'] == requests, (mode, ok, state)
            assert not (cache / 'graalvm.tar.partial').exists(), mode
            assert (cache / 'graalvm.tar.gz').exists() == success, mode
            if mode == 'progress':
                assert elapsed > 120, elapsed
            print(f'PASS download {mode}: requests={requests} seconds={elapsed:.6f}', flush=True)
        state.update(mode='cache', requests=0)
        cache = root / 'cache'
        cache.mkdir()
        (cache / 'graalvm.tar.gz').write_bytes(b'corrupt cache')
        full.download(url, DIGEST, cache, attempt_delay=.01, stage_delay=.01)
        full.download(url, DIGEST, cache, attempt_delay=.01, stage_delay=.01)
        assert state['requests'] == 1
        print('PASS corrupt dependency cache falls back; verified hit performs no GET', flush=True)
        if '--upstream-recovery' in sys.argv:
            # Induced first stage failure followed by an authentic pinned
            # upstream transfer. Keep this separate from natural tail samples.
            state.update(mode='upstream', requests=0)
            started = time.monotonic()
            result = full.download(url, full.JDK_SHA, root / 'upstream')
            assert full.sha(result) == full.JDK_SHA and state['requests'] == 4
            print(f'PASS induced upstream recovery: requests=4 seconds={time.monotonic()-started:.6f}', flush=True)
finally:
    server.shutdown()
    server.server_close()

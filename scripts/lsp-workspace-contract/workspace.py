#!/usr/bin/env python3
"""Black-box workspace ownership contract for Dawn's language server.

The protocol driver never waits for a timer. Every update batch ends with an
unknown request; the server must flush pending analysis before returning its
MethodNotFound response, which is the only synchronization barrier used here.
Fixtures live under a private temporary tree, and Java dependencies come from
the file:// repository assembled by run.sh.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time


TIMEOUT_S = 60.0
BARRIER_METHOD = "dawn/workspaceContractBarrier"
LEASE_PREFIX = "LSP_WORKSPACE_LEASE "


class ContractFailure(AssertionError):
    pass


def require(condition, label, detail):
    if not condition:
        raise ContractFailure(f"{label}: {detail}")


def frame(message):
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def notification(method, params=None):
    return {"jsonrpc": "2.0", "method": method, "params": params}


def text_document(uri):
    return {"textDocument": {"uri": uri}}


def did_open(uri, text, version=1):
    return notification("textDocument/didOpen", {
        "textDocument": {
            "uri": uri,
            "languageId": "dawn",
            "version": version,
            "text": text,
        },
    })


def did_change(uri, text, version):
    return notification("textDocument/didChange", {
        "textDocument": {"uri": uri, "version": version},
        "contentChanges": [{"text": text}],
    })


def did_close(uri):
    return notification("textDocument/didClose", text_document(uri))


def position(text, needle, occurrence=1):
    start = -1
    offset = 0
    for _ in range(occurrence):
        start = text.index(needle, offset)
        offset = start + len(needle)
    prefix = text[:start]
    line = prefix.count("\n")
    column_text = prefix.rsplit("\n", 1)[-1]
    character = len(column_text.encode("utf-16-le")) // 2
    return {"line": line, "character": character}


def position_after(text, needle, occurrence=1):
    result = position(text, needle, occurrence)
    result["character"] += len(needle.encode("utf-16-le")) // 2
    return result


def labels(result):
    if not isinstance(result, list):
        return []
    return sorted(item.get("label") for item in result if isinstance(item, dict))


def path_uri(path):
    return Path(path).resolve(strict=False).as_uri()


def dotted_uri(path):
    path = Path(path).resolve(strict=False)
    return path.parent.as_uri() + "/./" + path.name


class LspClient:
    def __init__(self, command, cwd, environment=None):
        env = os.environ.copy()
        if environment:
            env.update(environment)
        self.stderr_file = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_file,
            start_new_session=True,
        )
        self.command = command
        self.buffer = bytearray()
        self.frames = []
        self.next_id = 100
        self.stdin_closed = False

    def mark(self):
        return len(self.frames)

    def send(self, message):
        self.send_raw(frame(message))

    def send_raw(self, payload):
        if self.stdin_closed:
            raise ContractFailure("HARNESS_IO: write after stdin close")
        try:
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise ContractFailure(f"HARNESS_IO: server closed stdin: {error}") from error

    def note(self, method, params=None):
        self.send(notification(method, params))

    def request(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        self.send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })
        return request_id

    def _parse_available(self):
        while True:
            header_end = self.buffer.find(b"\r\n\r\n")
            if header_end < 0:
                return
            content_length = None
            for line in self.buffer[:header_end].split(b"\r\n"):
                name, separator, raw = line.partition(b":")
                if not separator:
                    raise ContractFailure(f"HARNESS_FRAMING: malformed response header {line!r}")
                if name.lower() == b"content-length":
                    content_length = int(raw.strip())
            if content_length is None:
                raise ContractFailure("HARNESS_FRAMING: response omitted Content-Length")
            body_start = header_end + 4
            body_end = body_start + content_length
            if len(self.buffer) < body_end:
                return
            body = bytes(self.buffer[body_start:body_end])
            del self.buffer[:body_end]
            try:
                self.frames.append(json.loads(body))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ContractFailure(f"HARNESS_FRAMING: invalid JSON response: {error}") from error

    def _read_once(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ContractFailure(
                "HARNESS_TIMEOUT: server did not answer; stderr=" + self.stderr_text()[-800:]
            )
        ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
        if not ready:
            raise ContractFailure(
                "HARNESS_TIMEOUT: server did not answer; stderr=" + self.stderr_text()[-800:]
            )
        chunk = os.read(self.proc.stdout.fileno(), 65536)
        if not chunk:
            self._parse_available()
            raise ContractFailure(
                "HARNESS_EOF: server exited before its response; stderr=" + self.stderr_text()[-800:]
            )
        self.buffer.extend(chunk)
        self._parse_available()

    def response(self, request_id):
        deadline = time.monotonic() + TIMEOUT_S
        while True:
            found = [item for item in self.frames if item.get("id") == request_id]
            if len(found) > 1:
                raise ContractFailure(f"HARNESS_PROTOCOL: duplicate response id {request_id}")
            if found:
                return found[0]
            self._read_once(deadline)

    def result(self, method, params=None):
        request_id = self.request(method, params)
        response = self.response(request_id)
        if "error" in response:
            raise ContractFailure(f"HARNESS_PROTOCOL: {method} returned {response['error']!r}")
        return response.get("result")

    def initialize(self):
        result = self.result("initialize", {
            "processId": None,
            "rootUri": None,
            "capabilities": {},
        })
        require(isinstance(result, dict) and isinstance(result.get("capabilities"), dict),
                "HARNESS_PROTOCOL", f"invalid initialize result {result!r}")
        self.note("initialized", {})

    def barrier(self, mark):
        request_id = self.request(BARRIER_METHOD, {})
        response = self.response(request_id)
        require(response.get("error", {}).get("code") == -32601,
                "HARNESS_BARRIER", f"unknown request returned {response!r}")
        response_index = next(
            index for index, item in enumerate(self.frames)
            if item.get("id") == request_id
        )
        return self.frames[mark:response_index]

    def stderr_text(self):
        current = self.stderr_file.tell()
        self.stderr_file.seek(0)
        data = self.stderr_file.read().decode("utf-8", "replace")
        self.stderr_file.seek(current)
        return data

    def lease_events(self):
        events = []
        for line in self.stderr_text().splitlines():
            if line.startswith(LEASE_PREFIX):
                fields = line[len(LEASE_PREFIX):].split()
                if len(fields) == 2 and fields[0] in ("create", "close"):
                    events.append((fields[0], int(fields[1])))
        return events

    def _close_stdin(self):
        if not self.stdin_closed:
            self.stdin_closed = True
            try:
                self.proc.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def finish(self, expected_status=None):
        self._close_stdin()
        deadline = time.monotonic() + TIMEOUT_S
        while self.proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.abort()
                raise ContractFailure("HARNESS_TIMEOUT: server did not exit")
            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if ready:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if chunk:
                    self.buffer.extend(chunk)
                    self._parse_available()
        while True:
            ready, _, _ = select.select([self.proc.stdout], [], [], 0)
            if not ready:
                break
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                break
            self.buffer.extend(chunk)
            self._parse_available()
        status = self.proc.returncode
        if expected_status is not None:
            require(status == expected_status, "HARNESS_EXIT",
                    f"expected status {expected_status}, got {status}; stderr={self.stderr_text()[-800:]}")
        return status

    def shutdown_exit(self):
        result = self.result("shutdown", None)
        require(result is None, "HARNESS_PROTOCOL", f"shutdown returned {result!r}")
        self.note("exit", {})
        return self.finish(expected_status=0)

    def abort(self):
        self._close_stdin()
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait()

    def close(self):
        self.abort()
        self.stderr_file.close()


def diagnostics(frames, uri):
    found = []
    for item in frames:
        if item.get("method") != "textDocument/publishDiagnostics":
            continue
        params = item.get("params", {})
        if params.get("uri") == uri:
            found.append(params.get("diagnostics"))
    return found


def latest_diagnostics(frames, uri, label):
    found = diagnostics(frames, uri)
    require(found, label, f"no publishDiagnostics for {uri}")
    require(isinstance(found[-1], list), label, f"invalid diagnostics payload {found[-1]!r}")
    return found[-1]


def messages(items):
    return [item.get("message", "") for item in items if isinstance(item, dict)]


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def project(path, name, deps=None, java_deps=None):
    path = Path(path)
    (path / "src").mkdir(parents=True, exist_ok=True)
    lines = ["schema = 1", f'name = "{name}"']
    if deps:
        lines.extend(["", "[deps]"])
        for alias, target in deps.items():
            lines.append(f'{alias} = "{target}"')
    if java_deps:
        lines.extend(["", "[java-deps]"])
        for alias, coordinate in java_deps.items():
            lines.append(f'{alias} = "{coordinate}"')
    write(path / "dawn.toml", "\n".join(lines) + "\n")
    return path


def lock(project_path, coordinate, jar_path):
    jar_path = Path(jar_path)
    digest = hashlib.sha256(jar_path.read_bytes()).hexdigest()
    write(Path(project_path) / "dawn.lock", (
        "schema 1\n"
        f"coord {coordinate}\n"
        f"artifact {digest}  {jar_path.name}\n"
    ))


class Fixture:
    def __init__(self, root, maven_repo, cache):
        self.root = Path(root)
        self.maven_repo = Path(maven_repo)
        self.cache = Path(cache)

    def case(self, name):
        return Path(tempfile.mkdtemp(prefix=name + "-", dir=self.root))

    def java_project(self, base, flavor):
        coordinate = f"fixture:api-{flavor}:1"
        target = project(base, f"java_{flavor}", java_deps={"api": coordinate})
        method = "onlyA" if flavor == "a" else "onlyB"
        write(target / "src/main.dawn", (
            'use java "fixture.Shared"\n\n'
            f"pub fn call_{flavor}() -> Int !io = Shared.{method}()\n"
        ))
        jar_path = self.maven_repo / "fixture" / f"api-{flavor}" / "1" / f"api-{flavor}-1.jar"
        lock(target, coordinate, jar_path)
        return target

    def environment(self):
        return {
            "DAWN_MAVEN_MIRROR": self.maven_repo.resolve().as_uri(),
            "COURSIER_CACHE": str(self.cache / "coursier"),
            "DAWN_PKG_CACHE": str(self.cache / "packages"),
            "DAWN_SELFHOST_CP": "",
        }


class Contract:
    def __init__(self, fixture, command, repo):
        self.fixture = fixture
        self.command = command
        self.repo = repo

    def client(self, extra_environment=None):
        environment = self.fixture.environment()
        if extra_environment:
            environment.update(extra_environment)
        client = LspClient(self.command, self.repo, environment)
        client.initialize()
        return client

    def close_client(self, client):
        try:
            if client.proc.poll() is None:
                client.shutdown_exit()
        finally:
            client.close()

    def live_overlay(self):
        root = project(self.fixture.case("live-overlay") / "app", "live_overlay")
        lib_path = root / "src/lib.dawn"
        main_path = root / "src/main.dawn"
        write(lib_path, "pub fn disk_value() -> Int = 1\n")
        write(main_path, "pub fn placeholder() -> Int = 0\n")
        lib_uri = path_uri(lib_path)
        main_uri = path_uri(main_path)
        live_lib = "pub fn live_value() -> Int = 2\n"
        live_main = "use lib.{live_value}\n\npub fn probe() -> Int = live_value()\n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(lib_uri, live_lib))
            client.send(did_open(main_uri, live_main))
            epoch = client.barrier(mark)
            require(latest_diagnostics(epoch, lib_uri, "SINGLE_OVERLAY_NOT_SHARED") == [],
                    "SINGLE_OVERLAY_NOT_SHARED", "live library has diagnostics")
            require(latest_diagnostics(epoch, main_uri, "SINGLE_OVERLAY_NOT_SHARED") == [],
                    "SINGLE_OVERLAY_NOT_SHARED",
                    f"caller did not see live export: {messages(latest_diagnostics(epoch, main_uri, 'SINGLE_OVERLAY_NOT_SHARED'))!r}")

            target = {
                "textDocument": {"uri": main_uri},
                "position": position(live_main, "live_value", occurrence=2),
            }
            hover = client.result("textDocument/hover", target)
            hover_text = hover.get("contents", {}).get("value", "") if isinstance(hover, dict) else ""
            require("fn live_value() -> Int" in hover_text,
                    "SINGLE_OVERLAY_NOT_SHARED", f"hover did not use live export: {hover!r}")
            definition = client.result("textDocument/definition", target)
            expected_range = {
                "start": {"line": 0, "character": 7},
                "end": {"line": 0, "character": 17},
            }
            require(isinstance(definition, list) and len(definition) == 1 and
                    definition[0].get("uri") == lib_uri and
                    definition[0].get("range") == expected_range,
                    "SINGLE_OVERLAY_NOT_SHARED",
                    f"definition did not target live library: {definition!r}")

            completion_text = "use lib.{li\n"
            mark = client.mark()
            client.send(did_change(main_uri, completion_text, 2))
            client.barrier(mark)
            completion = client.result("textDocument/completion", {
                "textDocument": {"uri": main_uri},
                "position": position_after(completion_text, "li", occurrence=2),
            })
            got = labels(completion)
            require("live_value" in got and "disk_value" not in got,
                    "SINGLE_OVERLAY_NOT_SHARED", f"completion used disk export: {got!r}")
        finally:
            self.close_client(client)

    def unsaved_module(self):
        root = project(self.fixture.case("unsaved-module") / "app", "unsaved_module")
        caller_path = root / "src/main.dawn"
        fresh_path = root / "src/new_module.dawn"
        write(caller_path, "pub fn placeholder() -> Int = 0\n")
        caller_uri = path_uri(caller_path)
        fresh_uri = path_uri(fresh_path)
        fresh_text = "pub fn fresh_export() -> Int = 7\n"
        module_text = "use \n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(fresh_uri, fresh_text))
            client.send(did_open(caller_uri, module_text))
            epoch = client.barrier(mark)
            require(latest_diagnostics(epoch, fresh_uri, "UNSAVED_MODULE_IGNORED") == [],
                    "UNSAVED_MODULE_IGNORED", "new module without use was not a clean member")
            module_items = client.result("textDocument/completion", {
                "textDocument": {"uri": caller_uri},
                "position": {"line": 0, "character": len("use ")},
            })
            require("new_module" in labels(module_items), "UNSAVED_MODULE_IGNORED",
                    f"new module path missing from completion: {labels(module_items)!r}")

            export_text = "use new_module.{fr\n"
            mark = client.mark()
            client.send(did_change(caller_uri, export_text, 2))
            client.barrier(mark)
            export_items = client.result("textDocument/completion", {
                "textDocument": {"uri": caller_uri},
                "position": position_after(export_text, "fr"),
            })
            require("fresh_export" in labels(export_items), "UNSAVED_MODULE_IGNORED",
                    f"new module live export missing from completion: {labels(export_items)!r}")

            valid_text = (
                "use new_module.{fresh_export}\n\n"
                "pub fn probe() -> Int = fresh_export()\n"
            )
            mark = client.mark()
            client.send(did_change(caller_uri, valid_text, 3))
            epoch = client.barrier(mark)
            require(latest_diagnostics(epoch, caller_uri, "UNSAVED_MODULE_IGNORED") == [],
                    "UNSAVED_MODULE_IGNORED",
                    f"caller did not import unsaved export: {messages(latest_diagnostics(epoch, caller_uri, 'UNSAVED_MODULE_IGNORED'))!r}")
        finally:
            self.close_client(client)

    def current_module_completion(self):
        root = project(self.fixture.case("current-module") / "app", "current_module")
        current_path = root / "src/current.dawn"
        sibling_path = root / "src/sibling.dawn"
        write(current_path, "pub fn current_export() -> Int = 1\n")
        write(sibling_path, "pub fn sibling_export() -> Int = 2\n")
        current_uri = path_uri(current_path)
        text = "use \n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(current_uri, text))
            client.barrier(mark)
            result = client.result("textDocument/completion", {
                "textDocument": {"uri": current_uri},
                "position": {"line": 0, "character": len("use ")},
            })
            got = labels(result)
            require("sibling" in got and "current" not in got,
                    "CURRENT_MODULE_SELF_SUGGESTED",
                    f"on-disk completion must include sibling and exclude self: {got!r}")
        finally:
            self.close_client(client)

    def extensionless_standalone(self):
        base = self.fixture.case("extensionless")
        root = self.fixture.java_project(base / "app", "a")
        scratch = root / "src/scratch"
        text = (
            'use java "fixture.Shared"\n\n'
            "pub fn probe() -> Int !io = Shared.onlyA()\n"
        )
        write(scratch, text)
        uri = path_uri(scratch)
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(uri, text))
            epoch = client.barrier(mark)
            got = latest_diagnostics(epoch, uri, "EXTENSIONLESS_JOINED_PROJECT")
            require(any("Java class not found: fixture.Shared" in message
                        for message in messages(got)),
                    "EXTENSIONLESS_JOINED_PROJECT",
                    f"extensionless local buffer borrowed project Java deps: {messages(got)!r}")
            require(client.lease_events() == [("create", 0)],
                    "EXTENSIONLESS_JOINED_PROJECT",
                    f"extensionless local buffer created a project lease: {client.lease_events()!r}")
        finally:
            self.close_client(client)

    def source_root_identity(self):
        for order in (("rogue", "main"), ("main", "rogue")):
            base = self.fixture.case("source-root-" + "-".join(order))
            root = project(base / "app", "source_root_identity")
            paths = {
                "rogue": root / "rogue.dawn",
                "main": root / "src/main.dawn",
            }
            modules = {
                "rogue": root / "shared.dawn",
                "main": root / "src/shared.dawn",
            }
            exports = {
                "rogue": "outer_value",
                "main": "inner_value",
            }
            write(modules["rogue"], "pub fn outer_value() -> Int = 1\n")
            write(modules["main"], "pub fn inner_value() -> Int = 2\n")
            texts = {
                name: (
                    f"use shared.{{{export}}}\n\n"
                    f"pub fn {name}_probe() -> Int = {export}()\n"
                )
                for name, export in exports.items()
            }
            for name, path in paths.items():
                write(path, texts[name])
            uris = {name: path_uri(path) for name, path in paths.items()}
            client = self.client()
            try:
                mark = client.mark()
                for name in order:
                    client.send(did_open(uris[name], texts[name]))
                epoch = client.barrier(mark)
                for name in ("rogue", "main"):
                    label = "SOURCE_ROOT_WORKSPACE_MERGED"
                    got = latest_diagnostics(epoch, uris[name], label)
                    require(got == [], label,
                            f"order {order!r} {name} used another source root: "
                            f"{messages(got)!r}")
                    target = exports[name]
                    result = client.result("textDocument/definition", {
                        "textDocument": {"uri": uris[name]},
                        "position": position(texts[name], target, occurrence=2),
                    })
                    require(isinstance(result, list) and len(result) == 1 and
                            result[0].get("uri") == path_uri(modules[name]),
                            label,
                            f"order {order!r} {name} resolved {target} through "
                            f"another source root: {result!r}")
            finally:
                self.close_client(client)

    def did_close(self):
        root = project(self.fixture.case("did-close") / "app", "did_close")
        lib_path = root / "src/lib.dawn"
        main_path = root / "src/main.dawn"
        write(lib_path, "pub fn disk_value() -> Int = 1\n")
        write(main_path, "pub fn placeholder() -> Int = 0\n")
        lib_uri = path_uri(lib_path)
        main_uri = path_uri(main_path)
        live_lib = "pub fn live_value() -> Int = 2\n"
        live_main = "use lib.{live_value}\n\npub fn probe() -> Int = live_value()\n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(lib_uri, live_lib))
            client.send(did_open(main_uri, live_main))
            ready = client.barrier(mark)
            require(latest_diagnostics(ready, main_uri, "DIDCLOSE_ROLLBACK_MISSING") == [],
                    "DIDCLOSE_ROLLBACK_MISSING", "live-overlay precondition failed")

            mark = client.mark()
            client.send(did_close(lib_uri))
            epoch = client.barrier(mark)
            require(latest_diagnostics(epoch, lib_uri, "DIDCLOSE_ROLLBACK_MISSING") == [],
                    "DIDCLOSE_ROLLBACK_MISSING", "closed URI was not cleared")
            caller_diags = latest_diagnostics(epoch, main_uri, "DIDCLOSE_ROLLBACK_MISSING")
            require(caller_diags and any("live_value" in message for message in messages(caller_diags)),
                    "DIDCLOSE_ROLLBACK_MISSING",
                    f"remaining member was not rebuilt from disk: {messages(caller_diags)!r}")
        finally:
            self.close_client(client)

    def diagnostics_current(self):
        root = project(self.fixture.case("diagnostics-current") / "app", "diagnostics_current")
        a_path = root / "src/a.dawn"
        b_path = root / "src/b.dawn"
        write(a_path, "pub fn disk_a() -> Int = 1\n")
        write(b_path, "pub fn disk_b() -> Int = 2\n")
        a_uri = path_uri(a_path)
        b_uri = path_uri(b_path)
        a_text = "pub fn alpha() -> Int = absent_alpha\n"
        b_text = "pub fn beta() -> Int = absent_beta\n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(a_uri, a_text))
            client.send(did_open(b_uri, b_text))
            client.barrier(mark)
            changed = "pub fn alpha() -> Int = absent_alpha_again\n"
            mark = client.mark()
            client.send(did_change(a_uri, changed, 2))
            epoch = client.barrier(mark)
            require(latest_diagnostics(epoch, a_uri, "WORKSPACE_DIAGNOSTICS_CURRENT_ONLY"),
                    "WORKSPACE_DIAGNOSTICS_CURRENT_ONLY", "trigger URI lost its diagnostic")
            require(latest_diagnostics(epoch, b_uri, "WORKSPACE_DIAGNOSTICS_CURRENT_ONLY"),
                    "WORKSPACE_DIAGNOSTICS_CURRENT_ONLY",
                    "non-trigger workspace URI was not republished")
        finally:
            self.close_client(client)

    def diagnostics_empty(self):
        root = project(self.fixture.case("diagnostics-empty") / "app", "diagnostics_empty")
        a_path = root / "src/a.dawn"
        b_path = root / "src/b.dawn"
        write(a_path, "pub fn alpha() -> Int = 1\n")
        write(b_path, "pub fn beta() -> Int = 2\n")
        a_uri = path_uri(a_path)
        b_uri = path_uri(b_path)
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(a_uri, "pub fn alpha() -> Int = 1\n"))
            client.send(did_open(b_uri, "pub fn beta() -> Int = absent_beta\n"))
            client.barrier(mark)
            mark = client.mark()
            client.send(did_change(b_uri, "pub fn beta() -> Int = 2\n", 2))
            epoch = client.barrier(mark)
            require(latest_diagnostics(epoch, b_uri, "EMPTY_DIAGNOSTIC_CLEAR_MISSING") == [],
                    "EMPTY_DIAGNOSTIC_CLEAR_MISSING",
                    "fixed trigger URI did not receive an explicit empty diagnostic array")
        finally:
            self.close_client(client)

    def diagnostics_source_view(self):
        root = project(self.fixture.case("diagnostics-view") / "app", "diagnostics_view")
        a_path = root / "src/a.dawn"
        b_path = root / "src/b.dawn"
        write(a_path, "pub fn alpha() -> Int = 1\n")
        write(b_path, "pub fn beta() -> Int = 2\n")
        a_uri = path_uri(a_path)
        b_uri = path_uri(b_path)
        a_text = "pub fn alpha() -> Int = absent_alpha\n"
        b_text = "# 🎈\n\npub fn beta() -> Int = absent_beta\n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(b_uri, b_text))
            client.send(did_open(a_uri, a_text))
            epoch = client.barrier(mark)
            beta = [item for item in latest_diagnostics(
                epoch, b_uri, "DIAGNOSTIC_SOURCE_VIEW_MISMATCH"
            ) if "absent_beta" in item.get("message", "")]
            expected = {
                "start": {"line": 2, "character": 23},
                "end": {"line": 2, "character": 34},
            }
            require(len(beta) == 1 and beta[0].get("range") == expected,
                    "DIAGNOSTIC_SOURCE_VIEW_MISMATCH",
                    f"diagnostic used another document's SourceView: {beta!r}")
        finally:
            self.close_client(client)

    def duplicate_canonical(self):
        root = project(self.fixture.case("duplicate") / "app", "duplicate_canonical")
        lib_path = root / "src/lib.dawn"
        main_path = root / "src/main.dawn"
        stable = "pub fn stable() -> Int = 1\n"
        alternate = "pub fn alternate() -> Int = 2\n"
        caller = "use lib.{stable}\n\npub fn probe() -> Int = stable()\n"
        write(lib_path, stable)
        write(main_path, caller)
        lib_uri = path_uri(lib_path)
        alias_uri = dotted_uri(lib_path)
        main_uri = path_uri(main_path)
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(lib_uri, stable))
            client.send(did_open(main_uri, caller))
            ready = client.barrier(mark)
            require(latest_diagnostics(ready, main_uri, "DUPLICATE_CANONICAL_LAST_WINS") == [],
                    "DUPLICATE_CANONICAL_LAST_WINS", "stable snapshot precondition failed")

            mark = client.mark()
            client.send(did_open(alias_uri, alternate))
            conflict = client.barrier(mark)
            require(latest_diagnostics(conflict, lib_uri, "DUPLICATE_CANONICAL_LAST_WINS"),
                    "DUPLICATE_CANONICAL_LAST_WINS",
                    "first URI did not receive duplicate-path conflict")
            require(latest_diagnostics(conflict, alias_uri, "DUPLICATE_CANONICAL_LAST_WINS"),
                    "DUPLICATE_CANONICAL_LAST_WINS",
                    "alias URI was silently selected as last writer")
            query = {
                "textDocument": {"uri": main_uri},
                "position": position(caller, "stable", occurrence=2),
            }
            completion = client.result("textDocument/completion", query)
            hover = client.result("textDocument/hover", query)
            definition = client.result("textDocument/definition", query)
            symbols = client.result("textDocument/documentSymbol", text_document(main_uri))
            require(completion == [] and hover is None and definition == [] and symbols == [],
                    "DUPLICATE_CANONICAL_LAST_WINS",
                    "conflicted workspace leaked an old semantic snapshot: "
                    f"completion={completion!r} hover={hover!r} "
                    f"definition={definition!r} symbols={symbols!r}")

            mark = client.mark()
            client.send(did_close(alias_uri))
            recovered = client.barrier(mark)
            require(latest_diagnostics(recovered, alias_uri, "DUPLICATE_CANONICAL_LAST_WINS") == [],
                    "DUPLICATE_CANONICAL_LAST_WINS", "closed duplicate URI was not cleared")
            require(latest_diagnostics(recovered, lib_uri, "DUPLICATE_CANONICAL_LAST_WINS") == [] and
                    latest_diagnostics(recovered, main_uri, "DUPLICATE_CANONICAL_LAST_WINS") == [],
                    "DUPLICATE_CANONICAL_LAST_WINS",
                    "workspace did not recover after duplicate closed")
        finally:
            self.close_client(client)

    def definition_root(self):
        base = self.fixture.case("definition-root")
        shared = project(base / "shared", "shared_pkg")
        shared_file = shared / "src/lib.dawn"
        disk_text = "pub fn target() -> Int = 1\n"
        write(shared_file, disk_text)
        app = project(base / "app", "definition_app", deps={"dep": str(shared.resolve())})
        app_file = app / "src/main.dawn"
        app_text = "use dep/lib.{target}\n\npub fn probe() -> Int = target()\n"
        write(app_file, app_text)
        app_uri = path_uri(app_file)
        shared_live_uri = dotted_uri(shared_file)
        shifted = "# shifted\n# 🎈\npub fn target() -> Int = 9\n"
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(app_uri, app_text))
            client.barrier(mark)
            mark = client.mark()
            client.send(did_open(shared_live_uri, shifted))
            client.barrier(mark)
            result = client.result("textDocument/definition", {
                "textDocument": {"uri": app_uri},
                "position": position(app_text, "target", occurrence=2),
            })
            expected_range = {
                "start": {"line": 0, "character": 7},
                "end": {"line": 0, "character": 13},
            }
            require(isinstance(result, list) and len(result) == 1 and
                    result[0].get("uri") == path_uri(shared_file) and
                    result[0].get("range") == expected_range,
                    "GLOBAL_DEFINITION_LEAK",
                    f"definition borrowed another root's live SourceView: {result!r}")
        finally:
            self.close_client(client)

    def java_roots(self):
        for order in (("a", "b"), ("b", "a")):
            base = self.fixture.case("java-" + "".join(order))
            roots = {flavor: self.fixture.java_project(base / flavor, flavor) for flavor in ("a", "b")}
            uris = {flavor: path_uri(roots[flavor] / "src/main.dawn") for flavor in roots}
            texts = {flavor: (roots[flavor] / "src/main.dawn").read_text(encoding="utf-8") for flavor in roots}
            client = self.client()
            try:
                mark = client.mark()
                for flavor in order:
                    client.send(did_open(uris[flavor], texts[flavor]))
                epoch = client.barrier(mark)
                for flavor in ("a", "b"):
                    got = latest_diagnostics(epoch, uris[flavor], "JAVA_WORKSPACE_LEASE_SHARED")
                    require(got == [], "JAVA_WORKSPACE_LEASE_SHARED",
                            f"order {order!r} root {flavor} saw another Java API: {messages(got)!r}")
            finally:
                self.close_client(client)

    def lease_lifecycle(self):
        base = self.fixture.case("lease-lifecycle")
        root = self.fixture.java_project(base / "app", "a")
        source = root / "src/main.dawn"
        uri = path_uri(source)
        text = source.read_text(encoding="utf-8")
        client = self.client()
        try:
            require(client.lease_events() == [("create", 0)], "LAST_CLOSE_LEASE_RETAINED",
                    f"standalone lease was not created exactly once: {client.lease_events()!r}")
            mark = client.mark()
            client.send(did_open(uri, text))
            client.barrier(mark)
            after_open = client.lease_events()
            require(after_open == [("create", 0), ("create", 1)],
                    "LAST_CLOSE_LEASE_RETAINED",
                    f"project lease creation mismatch: {after_open!r}")

            mark = client.mark()
            client.send(did_change(uri, text + "\n", 2))
            client.barrier(mark)
            require(client.lease_events() == after_open, "LAST_CLOSE_LEASE_RETAINED",
                    f"didChange replaced captured lease: {client.lease_events()!r}")

            mark = client.mark()
            client.send(did_close(uri))
            client.barrier(mark)
            after_close = client.lease_events()
            require(after_close == after_open + [("close", 1)],
                    "LAST_CLOSE_LEASE_RETAINED",
                    f"last close retained project lease: {after_close!r}")

            mark = client.mark()
            client.send(did_open(uri, text, version=3))
            client.barrier(mark)
            after_reopen = client.lease_events()
            require(after_reopen == after_close + [("create", 1)],
                    "LAST_CLOSE_LEASE_RETAINED",
                    f"reopen did not create a fresh project lease: {after_reopen!r}")
            client.shutdown_exit()
            final = client.lease_events()
            require(final.count(("create", 0)) == final.count(("close", 0)) == 1 and
                    final.count(("create", 1)) == final.count(("close", 1)) == 2,
                    "LAST_CLOSE_LEASE_RETAINED",
                    f"normal exit did not balance leases: {final!r}")
        finally:
            client.close()

    def lease_cleanup(self):
        def exercise(kind):
            base = self.fixture.case("lease-cleanup-" + kind)
            root = self.fixture.java_project(base / "app", "a")
            source = root / "src/main.dawn"
            uri = path_uri(source)
            text = source.read_text(encoding="utf-8")
            client = self.client()
            try:
                mark = client.mark()
                client.send(did_open(uri, text))
                client.barrier(mark)
                if kind == "shutdown":
                    client.shutdown_exit()
                elif kind == "exit":
                    client.note("exit", {})
                    client.finish(expected_status=1)
                elif kind == "eof":
                    client.finish(expected_status=0)
                else:
                    client.send_raw(b"Content-Length: invalid\r\n\r\n")
                    client.finish(expected_status=0)
                events = client.lease_events()
                require(events.count(("create", 0)) == events.count(("close", 0)) == 1 and
                        events.count(("create", 1)) == events.count(("close", 1)) == 1,
                        "EXIT_CLEANUP_BYPASSED",
                        f"{kind} exit leaked a lease: {events!r}")
            finally:
                client.close()

        for kind in ("shutdown", "exit", "eof", "fatal"):
            exercise(kind)

    def close_failure(self):
        base = self.fixture.case("close-failure")
        roots = {flavor: self.fixture.java_project(base / flavor, flavor)
                 for flavor in ("a", "b")}
        uris = {flavor: path_uri(roots[flavor] / "src/main.dawn") for flavor in roots}
        texts = {flavor: (roots[flavor] / "src/main.dawn").read_text(encoding="utf-8")
                 for flavor in roots}
        client = self.client({"DAWN_LSP_TEST_CLOSE_PANIC": "project"})
        try:
            mark = client.mark()
            for flavor in ("a", "b"):
                client.send(did_open(uris[flavor], texts[flavor]))
            epoch = client.barrier(mark)
            for flavor in ("a", "b"):
                require(latest_diagnostics(epoch, uris[flavor],
                                           "CLOSE_FAILURE_SKIPPED_REMAINING") == [],
                        "CLOSE_FAILURE_SKIPPED_REMAINING",
                        f"project {flavor} did not reach close-failure precondition")
            try:
                client.shutdown_exit()
            except ContractFailure as error:
                raise ContractFailure(
                    "CLOSE_FAILURE_SKIPPED_REMAINING: "
                    f"one close failure aborted server cleanup: {error}"
                ) from error
            events = client.lease_events()
            require(events.count(("create", 0)) == events.count(("close", 0)) == 1 and
                    events.count(("create", 1)) == events.count(("close", 1)) == 2,
                    "CLOSE_FAILURE_SKIPPED_REMAINING",
                    f"close failure skipped another lease: {events!r}")
        finally:
            client.close()

    def unavailable_retry(self):
        base = self.fixture.case("unavailable-retry")
        root = self.fixture.java_project(base / "app", "a")
        source = root / "src/main.dawn"
        lock_file = root / "dawn.lock"
        valid_lock = lock_file.read_text(encoding="utf-8")
        write(lock_file, "schema 1\ncoord broken\n")
        uri = path_uri(source)
        lock_uri = path_uri(lock_file)
        text = source.read_text(encoding="utf-8")
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(uri, text))
            failed = client.barrier(mark)
            require(latest_diagnostics(failed, lock_uri, "UNAVAILABLE_DIDCHANGE_RETRIED"),
                    "UNAVAILABLE_DIDCHANGE_RETRIED",
                    "malformed lock did not create an unavailable workspace")
            initial_events = client.lease_events()
            require(initial_events == [("create", 0)], "UNAVAILABLE_DIDCHANGE_RETRIED",
                    f"failed workspace installed a project lease: {initial_events!r}")

            write(lock_file, valid_lock)
            mark = client.mark()
            client.send(did_change(uri, text + "\n", 2))
            changed = client.barrier(mark)
            require(client.lease_events() == initial_events,
                    "UNAVAILABLE_DIDCHANGE_RETRIED",
                    f"didChange retried the project factory: {client.lease_events()!r}")
            require(latest_diagnostics(changed, lock_uri,
                                       "UNAVAILABLE_DIDCHANGE_RETRIED"),
                    "UNAVAILABLE_DIDCHANGE_RETRIED",
                    "didChange silently replaced the unavailable state")

            mark = client.mark()
            client.note("textDocument/didSave", text_document(uri))
            saved = client.barrier(mark)
            require(client.lease_events() == initial_events + [("create", 1)],
                    "UNAVAILABLE_DIDCHANGE_RETRIED",
                    f"didSave did not retry exactly once: {client.lease_events()!r}")
            require(latest_diagnostics(saved, lock_uri,
                                       "UNAVAILABLE_DIDCHANGE_RETRIED") == [],
                    "UNAVAILABLE_DIDCHANGE_RETRIED",
                    "successful didSave retry did not clear lock diagnostics")
            require(latest_diagnostics(saved, uri, "UNAVAILABLE_DIDCHANGE_RETRIED") == [],
                    "UNAVAILABLE_DIDCHANGE_RETRIED",
                    "successful didSave retry did not restore document analysis")
        finally:
            self.close_client(client)

    def external_diagnostics(self):
        base = self.fixture.case("external")

        lock_root = self.fixture.java_project(base / "lock", "a")
        lock_file = lock_root / "dawn.lock"
        valid_lock = lock_file.read_text(encoding="utf-8")
        write(lock_file, "schema 1\ncoord broken\n")
        lock_source = lock_root / "src/main.dawn"
        lock_uri = path_uri(lock_file)
        lock_doc_uri = path_uri(lock_source)
        lock_text = lock_source.read_text(encoding="utf-8")
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(lock_doc_uri, lock_text))
            broken = client.barrier(mark)
            require(latest_diagnostics(broken, lock_uri, "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH"),
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "malformed lock was not published at dawn.lock")
            mark = client.mark()
            client.send(did_close(lock_doc_uri))
            cleared = client.barrier(mark)
            require(latest_diagnostics(cleared, lock_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH") == [],
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "last close did not clear lock diagnostics")
            write(lock_file, valid_lock)
            mark = client.mark()
            client.send(did_open(lock_doc_uri, lock_text, version=2))
            recovered = client.barrier(mark)
            require(latest_diagnostics(recovered, lock_doc_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH") == [],
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "fixed lock did not allow workspace recreation")
        finally:
            self.close_client(client)

        missing = project(base / "missing", "missing_java",
                          java_deps={"missing": "fixture:no-such:1"})
        missing_source = missing / "src/main.dawn"
        write(missing_source, 'use java "fixture.Missing"\n')
        missing_doc_uri = path_uri(missing_source)
        manifest_uri = path_uri(missing / "dawn.toml")
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(missing_doc_uri, missing_source.read_text(encoding="utf-8")))
            failed = client.barrier(mark)
            require(latest_diagnostics(failed, manifest_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH"),
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "Maven failure was not published at dawn.toml")
            mark = client.mark()
            client.send(did_close(missing_doc_uri))
            cleared = client.barrier(mark)
            require(latest_diagnostics(cleared, manifest_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH") == [],
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "last close did not clear Maven diagnostics")
        finally:
            self.close_client(client)

        shared = base / "shared"
        (shared / "src").mkdir(parents=True)
        write(shared / "dawn.toml", "schema = 1\nname =\n")
        write(shared / "src/lib.dawn", "pub fn shared() -> Int = 1\n")
        roots = {}
        for name in ("left", "right"):
            roots[name] = project(base / name, name,
                                  deps={"shared": str(shared.resolve())})
            write(roots[name] / "src/main.dawn", f"pub fn {name}() -> Int = 1\n")
        uris = {name: path_uri(roots[name] / "src/main.dawn") for name in roots}
        texts = {name: (roots[name] / "src/main.dawn").read_text(encoding="utf-8") for name in roots}
        shared_manifest_uri = path_uri(shared / "dawn.toml")
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(uris["left"], texts["left"]))
            client.barrier(mark)
            mark = client.mark()
            client.send(did_open(uris["right"], texts["right"]))
            both = client.barrier(mark)
            require(latest_diagnostics(both, shared_manifest_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH"),
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "shared external diagnostic was not published")
            mark = client.mark()
            client.send(did_close(uris["left"]))
            one = client.barrier(mark)
            require(latest_diagnostics(one, shared_manifest_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH"),
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "closing one owner cleared another root's external diagnostic")
            mark = client.mark()
            client.send(did_close(uris["right"]))
            none = client.barrier(mark)
            require(latest_diagnostics(none, shared_manifest_uri,
                                       "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH") == [],
                    "EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH",
                    "last external diagnostic owner did not clear its URI")
        finally:
            self.close_client(client)

    def standalone(self):
        jdk_uri = "untitled:dawn-workspace-jdk"
        host_uri = "untitled:dawn-workspace-host"
        jdk_text = (
            'use java "java.lang.String"\n\n'
            "pub fn probe() -> String !io = String.valueOf(1)\n"
        )
        host_text = 'use java "org.objectweb.asm.ClassWriter"\n'
        client = self.client()
        try:
            mark = client.mark()
            client.send(did_open(jdk_uri, jdk_text))
            client.send(did_open(host_uri, host_text))
            epoch = client.barrier(mark)
            jdk_diags = latest_diagnostics(epoch, jdk_uri, "STANDALONE_SYSTEM_LOADER_LEAK")
            host_diags = latest_diagnostics(epoch, host_uri, "STANDALONE_SYSTEM_LOADER_LEAK")
            require(not any("Java class not found" in message for message in messages(jdk_diags)),
                    "STANDALONE_SYSTEM_LOADER_LEAK",
                    f"zero-jar standalone lease lost JDK classes: {messages(jdk_diags)!r}")
            require(any("Java class not found: org.objectweb.asm.ClassWriter" in message
                        for message in messages(host_diags)),
                    "STANDALONE_SYSTEM_LOADER_LEAK",
                    f"standalone lease leaked compiler ASM: {messages(host_diags)!r}")
        finally:
            self.close_client(client)


CASES = {
    "live-overlay": Contract.live_overlay,
    "unsaved-module": Contract.unsaved_module,
    "current-module-completion": Contract.current_module_completion,
    "extensionless-standalone": Contract.extensionless_standalone,
    "source-root-identity": Contract.source_root_identity,
    "did-close": Contract.did_close,
    "diagnostics-current": Contract.diagnostics_current,
    "diagnostics-empty": Contract.diagnostics_empty,
    "diagnostics-source-view": Contract.diagnostics_source_view,
    "duplicate-canonical": Contract.duplicate_canonical,
    "definition-root": Contract.definition_root,
    "java-roots": Contract.java_roots,
    "lease-lifecycle": Contract.lease_lifecycle,
    "lease-cleanup": Contract.lease_cleanup,
    "close-failure": Contract.close_failure,
    "unavailable-retry": Contract.unavailable_retry,
    "external-diagnostics": Contract.external_diagnostics,
    "standalone": Contract.standalone,
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=sorted(CASES))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--fixture-root", required=True)
    parser.add_argument("--maven-repo", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("server", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.server[:1] == ["--"]:
        args.server = args.server[1:]
    if not args.server:
        parser.error("server command is required after --")
    return args


def main():
    args = parse_args()
    Path(args.fixture_root).mkdir(parents=True, exist_ok=True)
    fixture = Fixture(args.fixture_root, args.maven_repo, args.cache)
    contract = Contract(fixture, args.server, args.repo)
    selected = [args.case] if args.case else list(CASES)
    failures = 0
    for name in selected:
        try:
            CASES[name](contract)
            print(f"PASS  {name}")
        except (ContractFailure, OSError, ValueError) as error:
            print(f"FAIL  {name}: {error}")
            failures += 1
    if failures:
        print(f"lsp-workspace-contract: FAILED ({failures}/{len(selected)} cases)")
        return 1
    print(f"lsp-workspace-contract: OK ({len(selected)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Exercise native semantic boundaries with the differential's existing binary."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time


def check(binary):
    count = 0
    with tempfile.TemporaryDirectory(prefix="native-semantics-") as scratch:
        root = Path(scratch)
        tools = root / "tools"
        tools.mkdir()
        log = root / "calls"
        for name in ("java", "javac", "native-image", "cc", "clang", "curl"):
            tool = tools / name
            tool.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$TOOL_LOG"\nexit 97\n')
            tool.chmod(0o755)
        env = {"HOME": scratch, "PATH": str(tools), "LANG": "C.UTF-8",
               "TOOL_LOG": str(log), "COURSIER_CACHE": str(root / "maven")}
        control = subprocess.run([str(tools / "java")], env=env, check=False)
        assert control.returncode == 97 and log.exists()
        log.unlink()

        def write(path, text):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

        def run(argv, code, fragment=None):
            nonlocal count
            result = subprocess.run([str(binary), *map(str, argv)], cwd=root, env=env,
                                    capture_output=True, timeout=20)
            assert result.returncode == code, (argv, result)
            if fragment:
                assert not result.stdout and fragment.encode() in result.stderr, (argv, result)
            assert not log.exists() and not (root / "maven").exists(), argv
            count += 1
            return result

        header = 'schema = 1\nname = "app"\n'
        java = '[java-deps]\napi = "fixture:api:1"\n'
        source = 'pub fn main() -> Unit !io = ()\n'
        app = root / "app"
        dep = root / "dep"
        write(app / "src/main.dawn", source)
        write(dep / "src/api.dawn", 'pub fn value() -> Int = 1\n')
        for transitive in (False, True):
            write(app / "dawn.toml", header + ('[deps]\ndep = "../dep"\n' if transitive else java))
            write(dep / "dawn.toml", 'schema = 1\nname = "dep"\n' + java)
            origin = dep / "dawn.toml" if transitive else app / "dawn.toml"
            for target in (app, app / "src/main.dawn"):
                for command in ("check", "doc", "emitc", "build", "run", "test"):
                    result = run([command, target], 2, "fixture:api:1")
                    assert str(origin).encode() in result.stderr, result
                    assert b"native compiler" in result.stderr, result
                    assert b"java -jar /path/to/dawn-selfhost.jar" in result.stderr, result
            # Metadata and syntax operations remain available with Java coordinates.
            run(["fmt", "--check", app / "src/main.dawn"], 0)
            run(["parse", app / "src/main.dawn"], 0)
            run(["version", "-m", app], 0)
            run(["add", "fixture:extra:1", "--dir", app], 0)
            # Restore the fixture after the metadata edit.
            write(app / "dawn.toml", header + ('[deps]\ndep = "../dep"\n' if transitive else java))
            lsp(binary, app / "src/main.dawn", origin, env, root)
            count += 1

        for manifest in (header, 'schema = 1\nname = "Bad-Name"\n' + java,
                         header + '[java-deps]\napi = "bad"\n', header + '[deps\n'):
            write(app / "dawn.toml", manifest)
            for target in (app, app / "src/main.dawn"):
                result = run(["check", target], 0 if manifest == header else 1)
                assert b"not supported by the native compiler" not in result.stderr, result
        write(app / "dawn.toml", header + java + '[deps]\ndep = "../dep"\n')
        write(dep / "dawn.toml", 'schema = 1\nname = "Bad-Name"\n' + java)
        for target in (app, app / "src/main.dawn"):
            result = run(["check", target], 1, 'invalid package name `Bad-Name`')
            assert b"not supported by the native compiler" not in result.stderr, result
        write(app / "dawn.toml", header)
        write(app / "src/main.dawn", 'use java "java.lang.String"\npub fn main() -> Unit !io = ()\n')
        run(["check", app], 1, '`use java` is not available in this compiler')
        write(app / "src/main.dawn", 'use dep/api\npub fn main() -> Unit !io = ()\n')
        write(app / "dawn.toml", header + '[deps]\ndep = "../dep"\n')
        write(dep / "dawn.toml", 'schema = 1\nname = "dep"\n')
        write(dep / "src/api.dawn", 'use java "java.lang.String"\npub fn value() -> Int = 1\n')
        run(["check", app], 1, '`use java` is not available in this compiler')
        write(root / "no_src/dawn.toml", header + java)
        run(["check", root / "no_src"], 1, 'project directory has no `src/` folder')
        # The chosen std's directory keeps its provenance diagnostic, even if
        # a Java manifest beside it could otherwise make it look like a project.
        std = Path(__file__).resolve().parents[2] / "std"
        run(["check", "--std", std, std], 1, "is the bundled standard library")
        run(["check", "--std", std, std / "list.dawn"], 0)
        java_std = root / "standard"
        shutil.copytree(std, java_std)
        write(java_std / "dawn.toml", header + java)
        run(["check", "--std", java_std, java_std], 1, "is the bundled standard library")
        run(["check", "--std", java_std, java_std / "list.dawn"], 2, "fixture:api:1")
        run(["doc", "--std", java_std, "--stdlib"], 0)
        # The JVM compiler project itself receives no capability exception.
        run(["check", std.parent / "selfhost/src/nmain.dawn"], 2, "org.ow2.asm:asm:9.7.1")
        assert not log.exists() and not (root / "maven").exists()
    print(f"OK native semantic boundary: {count} assertions; no external tool calls")


def lsp(binary, entry, origin, env, cwd):
    with subprocess.Popen([str(binary), "lsp"], cwd=cwd, env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        buf = b""

        def send(message):
            body = json.dumps({"jsonrpc": "2.0", **message}).encode()
            proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            proc.stdin.flush()

        def until(predicate):
            nonlocal buf
            deadline = time.monotonic() + 20
            while True:
                end = buf.find(b"\r\n\r\n")
                if end >= 0:
                    size = int(buf[:end].split(b":", 1)[1].strip())
                    if len(buf) >= end + 4 + size:
                        message = json.loads(buf[end + 4:end + 4 + size])
                        buf = buf[end + 4 + size:]
                        if predicate(message):
                            return message
                        continue
                left = deadline - time.monotonic()
                assert left > 0 and select.select([proc.stdout], [], [], left)[0], "LSP timeout"
                chunk = os.read(proc.stdout.fileno(), 65536)
                assert chunk, "LSP closed"
                buf += chunk

        try:
            send({"id": 1, "method": "initialize", "params": {"capabilities": {}}})
            until(lambda m: m.get("id") == 1)
            send({"method": "initialized", "params": {}})
            send({"method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": entry.as_uri(), "languageId": "dawn", "version": 1, "text": entry.read_text()}}})
            message = until(lambda m: m.get("method") == "textDocument/publishDiagnostics"
                            and m["params"]["uri"] == origin.as_uri())
            diagnostic = message["params"]["diagnostics"][0]
            assert diagnostic["severity"] == 1 and "fixture:api:1" in diagnostic["message"], diagnostic
            assert diagnostic["range"]["start"] == {"line": 0, "character": 0}, diagnostic
            send({"id": 2, "method": "shutdown", "params": None})
            until(lambda m: m.get("id") == 2)
            send({"method": "exit", "params": None})
            proc.stdin.close()
            assert proc.wait(timeout=10) == 0
            assert not proc.stderr.read()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

#!/usr/bin/env python3
"""Exercise the installer and no-Java CLI using the release candidate, without rebuilding it."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("installer", Path(__file__).with_name("install-native.py"))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def main(package):
    package = Path(package).resolve()
    original = {name: (package / name).read_bytes() for name in installer.INSTALL_INPUTS}
    info = json.loads(original[installer.METADATA])
    tag = info["tag"]
    passed = 0

    def ok(condition, name):
        nonlocal passed
        if not condition:
            raise AssertionError(name)
        passed += 1
        print("OK  " + name, flush=True)

    with tempfile.TemporaryDirectory(prefix="native-install-") as temporary:
        root = Path(temporary)
        prefix = root / "prefix with spaces"
        assets = dict(original)
        urls = []

        class Response(io.BytesIO):
            def geturl(self):
                return installer.REPOSITORY + "/releases/tag/" + tag

        def request(url, **kwargs):
            urls.append(url)
            if url == installer.REPOSITORY + "/releases/latest":
                return Response(b"")
            base = installer.REPOSITORY + "/releases/download/" + tag + "/"
            if not url.startswith(base):
                raise AssertionError("mixed release URLs: " + url)
            name = url[len(base):]
            if name not in assets:
                raise OSError("missing release asset")
            return Response(assets[name])

        with patch.object(installer.urllib.request, "urlopen", request):
            installed = installer.install(tag, prefix)
            ok(installed.read_bytes() == original[installer.ASSET] and not installed.is_symlink(),
               "fixed tag installs the exact candidate as bin/dawn")
            ok(len(urls) == 3 and all("/releases/latest" not in url for url in urls),
               "fixed tag fetches only its metadata, native asset and checksum")
            urls.clear()
            installer.install(prefix=prefix)
            ok(len(urls) == 4 and urls.count(installer.REPOSITORY + "/releases/latest") == 1,
               "latest resolves once and pins every asset to that tag")

            def rejected(name, change=None, error="", install_args=None, mock=None):
                nonlocal assets
                assets = dict(original)
                if change:
                    change(assets)
                before = installed.read_bytes()
                link = os.readlink(installed) if installed.is_symlink() else None
                caught = None
                with mock if mock is not None else contextlib.nullcontext():
                    try:
                        installer.install(**(install_args or {"tag": tag, "prefix": prefix}))
                    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                        caught = exc
                ok(caught is not None and error in str(caught), name + " is refused")
                ok(installed.read_bytes() == before and
                   (os.readlink(installed) if installed.is_symlink() else None) == link and
                   not list(installed.parent.glob(".dawn-install-*")),
                   name + " preserves the old entry and cleans staging")

            def metadata(key, value):
                def change(data):
                    meta = copy.deepcopy(info)
                    parts = key.split(".")
                    target = meta
                    for part in parts[:-1]:
                        target = target[part]
                    target[parts[-1]] = value
                    data[installer.METADATA] = json.dumps(meta).encode()
                return change

            for key, value, error in (
                ("tag", "v0.0.0", "tag/version"),
                ("version", "0.0.0", "tag/version"),
                ("schema", 2, "schema"),
                ("commit", "abc", "source commit"),
                ("host_target", "linux-aarch64", "target/install"),
                ("native.name", "dawnc-linux-aarch64", "asset name"),
                ("native.sha256", "0" * 64, "SHA-256 mismatch"),
                ("builder.version", "0.0.0", "builder version"),
                ("builder.sha256", "", "SHA-256"),
                ("native.source_manifest", "b1:" + "0" * 64, "version does not match"),
                ("native.source_manifest", info["native"]["source_manifest"][:-1] +
                 ("0" if info["native"]["source_manifest"][-1] != "0" else "1"), "source manifest"),
            ):
                rejected("metadata " + key, metadata(key, value), error)
            rejected("bad checksum", lambda data: data.update({installer.ASSET + ".sha256": b"0\n"}),
                     "checksum mismatch")
            rejected("truncated download", lambda data: data.update({installer.ASSET: data[installer.ASSET][:64]}),
                     "checksum mismatch")

            def payload_change(transform):
                def change(data):
                    payload = bytearray(data[installer.ASSET])
                    transform(payload)
                    data[installer.ASSET] = bytes(payload)
                    digest = hashlib.sha256(payload).hexdigest()
                    data[installer.ASSET + ".sha256"] = f"{digest}  {installer.ASSET}\n".encode()
                    meta = copy.deepcopy(info)
                    meta["native"]["sha256"] = digest
                    data[installer.METADATA] = json.dumps(meta).encode()
                return change

            rejected("wrong ELF architecture", payload_change(lambda data: struct.pack_into("<H", data, 18, 183)),
                     "x86_64 ELF")
            rejected("truncated ELF with matching checksum", payload_change(lambda data: data.__delitem__(slice(64, None))),
                     "truncated ELF")
            rejected("ELF interpreter", payload_change(lambda data: struct.pack_into(
                "<I", data, struct.unpack_from("<Q", data, 32)[0], 3)), "ELF interpreter")
            for missing in installer.INSTALL_INPUTS:
                rejected("missing " + missing, lambda data, name=missing: data.pop(name), "missing release asset")
            rejected("network error", error="offline", mock=patch.object(
                installer.urllib.request, "urlopen", side_effect=OSError("offline")))
            for system, machine in (("Darwin", "arm64"), ("Linux", "aarch64"), ("Windows", "AMD64")):
                with patch.object(installer.platform, "system", return_value=system), \
                     patch.object(installer.platform, "machine", return_value=machine):
                    urls.clear()
                    rejected(system + "/" + machine, error="unsupported platform")
                    ok(not urls, "unsupported platform fails before any download")
            rejected("atomic rename failure", error="rename denied", mock=patch.object(
                installer.os, "replace", side_effect=PermissionError("rename denied")))
            mode = installed.parent.stat().st_mode & 0o777
            installed.parent.chmod(0o555)
            try:
                if os.geteuid() != 0:
                    rejected("unwritable destination", error="Permission denied")
                else:
                    rejected("unwritable destination", error="Permission denied", mock=patch.object(
                        installer.tempfile, "TemporaryDirectory", side_effect=PermissionError("Permission denied")))
            finally:
                installed.parent.chmod(mode)
            old_target = root / "checkout-entry"
            old_target.write_bytes(b"old checkout entry\n")
            installed.unlink()
            installed.symlink_to(old_target)
            rejected("bad checksum with old symlink", lambda data: data.update(
                {installer.ASSET + ".sha256": b"bad"}), "checksum mismatch")
            assets = dict(original)
            installer.install(tag, prefix)
            ok(not installed.is_symlink() and old_target.read_bytes() == b"old checkout entry\n",
               "successful replacement of dawn symlink leaves its target intact")
            linked_prefix = root / "linked-prefix"
            linked_prefix.mkdir()
            (linked_prefix / "bin").symlink_to(installed.parent, target_is_directory=True)
            rejected("bin directory symlink", install_args={"tag": tag, "prefix": linked_prefix})

        # Exercise the public script and the documented offline download path.
        result = subprocess.run([sys.executable, "scripts/install-native.py", "--tag", tag,
                                 "--from-dir", str(package), "--prefix", str(prefix)],
                                capture_output=True, text=True)
        ok(result.returncode == 0 and not result.stderr, "public installer consumes the downloaded release set")
        distributed = root / "downloaded-installer.py"
        distributed.write_bytes((package / "install-native.py").read_bytes())
        result = subprocess.run([sys.executable, str(distributed), "--tag", tag,
                                 "--from-dir", str(package), "--prefix", str(prefix)],
                                cwd=root, env={"PATH": "/nonexistent", "HOME": str(root)},
                                capture_output=True, text=True)
        ok(result.returncode == 0 and not result.stderr,
           "published standalone installer works outside the checkout")
        smoke(installed, root, ok)
    print(f"OK: {passed} native installation assertions")


def smoke(installed, root, ok):
    work = root / "empty-consumer"
    home = root / "empty-home"
    tools = root / "tools"
    for directory in (work, home, tools):
        directory.mkdir()
    log = root / "tool-exec.log"
    cc = shutil.which(os.environ.get("CC", "cc"))
    if not cc:
        raise AssertionError("the native installation contract needs cc")
    for name in ("java", "javac", "native-image", "curl"):
        tool = tools / name
        tool.write_text(f'#!/bin/sh\nprintf "%s\\n" "{name}" >> "{log}"\nexit 97\n')
        tool.chmod(0o755)
    compiler = tools / "cc"
    compiler.write_text(f'#!/bin/sh\nprintf "%s\\n" cc >> "{log}"\nexec "{cc}" "$@"\n')
    compiler.chmod(0o755)
    # clang/gcc may invoke their assembler and linker through PATH.
    for name in ("as", "ld"):
        tool = shutil.which(name)
        if tool:
            (tools / name).symlink_to(tool)
    env = {"PATH": str(tools), "HOME": str(home), "TMPDIR": str(work), "LANG": "C.UTF-8"}
    # Prove that the execution traps work before the positive commands.
    for name in ("java", "javac", "native-image"):
        result = subprocess.run([str(tools / name)], env=env, capture_output=True)
        ok(result.returncode == 97, name + " execution trap negative control")
    log.unlink()
    (work / "hello.dawn").write_text('use std/str\n\npub fn main()->Unit !io={println(str.to_upper("installed"))}\n')
    (work / "tests.dawn").write_text('test "installed compiler" { assert 2 + 3 == 5 }\n')
    project = work / "project" / "src"
    project.mkdir(parents=True)
    (project / "main.dawn").write_text((work / "hello.dawn").read_text())

    def run(args, expected=None):
        result = subprocess.run([str(installed), *args], cwd=work, env=env,
                                capture_output=True, timeout=60)
        ok(result.returncode == 0 and not result.stderr and
           (expected is None or result.stdout == expected), "installed dawn " + " ".join(args))
        return result.stdout

    ok(not any((work / name).exists() for name in ("std", "runtime", "selfhost", ".dawn", "dawn.toml")),
       "consumer starts with no compiler sources, checkout std or seed cache")
    run(["check", "hello.dawn"], b"ok\n")
    original_source = (work / "hello.dawn").read_bytes()
    run(["fmt", "hello.dawn"], b"formatted hello.dawn\n")
    ok((work / "hello.dawn").read_bytes() != original_source, "installed fmt rewrites unformatted source")
    run(["fmt", "--check", "hello.dawn"], b"")
    for target in (["--builtins"], ["--stdlib"], ["project"]):
        doc = json.loads(run(["doc", *target]))
        ok(bool(doc), "installed documentation is nonempty JSON: " + target[0])
    run(["run", "hello.dawn"], b"INSTALLED\n")
    run(["build", "hello.dawn", "-o", str(work / "hello")])
    result = subprocess.run([str(work / "hello")], cwd=work, env=env, capture_output=True)
    ok((result.returncode, result.stdout, result.stderr) == (0, b"INSTALLED\n", b""),
       "installed build produces a working native program")
    tests = run(["test", "tests.dawn"])
    ok(b"1 test(s) passed\n" in tests and b"PASS" in tests, "installed test executes its assertion")
    source = (work / "hello.dawn").read_text()
    hover_line, hover_text = next((index, line) for index, line in enumerate(source.splitlines())
                                  if "to_upper" in line)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": (work / "hello.dawn").as_uri(), "languageId": "dawn", "version": 1, "text": source}}},
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": (work / "hello.dawn").as_uri()}, "position": {"line": hover_line, "character": hover_text.index("to_upper") + 1}}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": None},
    ]
    payload = b""
    for message in messages:
        data = json.dumps(message).encode()
        payload += f"Content-Length: {len(data)}\r\n\r\n".encode() + data
    result = subprocess.run([str(installed), "lsp"], cwd=work, env=env, input=payload,
                            capture_output=True, timeout=60)
    responses = []
    remaining = result.stdout
    while remaining:
        header, remaining = remaining.split(b"\r\n\r\n", 1)
        length = int(re.search(rb"Content-Length: ([0-9]+)", header).group(1))
        responses.append(json.loads(remaining[:length]))
        remaining = remaining[length:]
    by_id = {entry["id"]: entry for entry in responses if "id" in entry}
    ok(result.returncode == 0 and not result.stderr and set(by_id) == {1, 2, 3}
       and by_id[2].get("result") is not None and "error" not in by_id[2],
       "installed LSP initializes, opens, hovers and shuts down")
    calls = log.read_text().splitlines()
    ok(calls and set(calls) == {"cc"}, "execution records contain cc and no java, javac, native-image or curl")
    ok(not (home / ".dawn").exists() and not (home / ".cache").exists(),
       "consumer uses embedded std/runtime without a source tree or seed cache")


if __name__ == "__main__":
    main(sys.argv[1])

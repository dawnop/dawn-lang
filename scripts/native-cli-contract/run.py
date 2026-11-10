#!/usr/bin/env python3
"""Absolute native CLI assertions using the binary supplied to the differential."""
import argparse
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent

COMMANDS = ("check", "build", "emitc", "run", "test", "fmt", "doc", "add",
            "cache", "lsp", "parse", "version")


def command_help(help_text, command):
    lines = []
    keeping = False
    for line in help_text.splitlines():
        if line.startswith("  dawn "):
            keeping = line.startswith(f"  dawn {command} ")
            if keeping:
                lines.append(line)
        elif keeping and line.startswith("    "):
            lines.append(line)
        else:
            keeping = False
    assert lines, command
    return ("\n".join(lines) + "\n").encode()


def run(binary, argv, cwd, env, timeout=3):
    # Keep stdin open: a help request that starts LSP must fail this probe.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        with subprocess.Popen([str(binary), *argv], cwd=cwd, env=env,
                              stdin=subprocess.PIPE, stdout=out, stderr=err) as proc:
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
        out.seek(0)
        err.seek(0)
        return code, out.read(), err.read()


def check(binary, version):
    expected = (HERE / "help.txt").read_text().replace(
        "@VERSION@", version)
    failures = []
    count = 0
    with tempfile.TemporaryDirectory(prefix="native-cli-contract-") as work:
        root = Path(work)
        std = root / "blocked std"
        std.mkdir()
        (std / "VERSION").write_text(version + "\n")
        os.mkfifo(std / "modules.txt")
        tools = root / "tools"
        tools.mkdir()
        log = root / "tool-calls"
        for name in ("java", "javac", "native-image", "cc", "clang", "curl"):
            tool = tools / name
            tool.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$TOOL_LOG"\nexit 97\n')
            tool.chmod(0o755)
        env = {"PATH": str(tools), "HOME": work, "LANG": "C.UTF-8",
               "DAWN_STD": str(std), "JAVA_HOME": str(tools), "TOOL_LOG": str(log),
               "CC": str(tools / "cc"), "DAWN_WASM_CC": str(tools / "clang")}
        control = subprocess.run([str(tools / "cc")], env=env, check=False)
        assert control.returncode == 97 and log.read_text().strip() == str(tools / "cc")
        log.unlink()

        def expect(argv, code, out=b"", err=b""):
            nonlocal count
            count += 1
            try:
                got = run(binary, argv, root, env)
                assert got == (code, out, err), repr(got)
                assert not log.exists(), "help or refusal started a tool"
            except (AssertionError, subprocess.TimeoutExpired) as error:
                failures.append(f"{argv!r}: {error}")
                print("FAIL native CLI:", failures[-1], flush=True)

        # Prove the FIFO would stop real std loading, rather than using an
        # invalid directory that silently selects the embedded library.
        source = root / "tiny.dawn"
        source.write_text("pub fn main() -> Unit !io = ()\n")
        try:
            got = run(binary, ["check", "--std", str(std), str(source)], root, env, .5)
            raise AssertionError(f"std negative control did not block: {got!r}")
        except subprocess.TimeoutExpired:
            pass

        for alias in ("--help", "-h", "help"):
            expect([alias], 0, expected.encode())
        expect([], 2, err=expected.encode())
        expect(["unknown-command"], 2,
               err=b"error: unknown command: unknown-command\n" + expected.encode())
        for command in COMMANDS:
            expect([command, "--help"], 0, command_help(expected, command))
        for command in ("build", "lsp"):
            expect([command, "--unknown-option"], 2,
                   err=f"error: unknown option for dawn {command}: --unknown-option\n".encode())
        expect(["cache", "verify", "--help"], 0, command_help(expected, "cache"))
        expect(["build", "--std", str(std), "-o", "with spaces", "--help"], 0,
               command_help(expected, "build"))
        # A help-shaped value is consumed. The final help is the request.
        for command, flag in (("build", "-o"), ("emitc", "--map"), ("add", "--as"),
                              ("check", "--std"), ("version", "-m")):
            expect([command, flag, "--help", "-h"], 0, command_help(expected, command))
        # A JVM-looking option used as a value is not a capability request.
        expect(["build", "-o", "--cp", "--help"], 0, command_help(expected, "build"))
        # Existing, absent and empty classpaths are all capability errors.
        for flags in (["--cp", str(root)], ["--cp", str(root / "missing.jar")],
                      ["--cp", ""], [f"--cp={root}"], ["--cp="], ["--cp=missing.jar"]):
            expect(["test", *flags, str(source)], 2,
                   err=("error: --cp is not supported by the native compiler; "
                        "use java -jar /path/to/dawn-selfhost.jar test ...\n").encode())
        for command, flag in (("run", "--closure"), ("build", "--native"),
                              ("build", "--vendor"), ("lock", "lock")):
            argv = [command] if command == "lock" else [command, flag]
            expect(argv, 2,
                   err=(f"error: {flag} is not supported by the native compiler; "
                        f"use java -jar /path/to/dawn-selfhost.jar {command} ...\n").encode())
        expect(["test", "--cp"], 2, err=b"error: --cp needs a path\n")
        jar = root / "artifact.jar"
        jar.write_bytes(b"PK")
        expect(["version", "-m", str(jar)], 2,
               err=(f"error: cannot read {jar} as a native binary or wasm module: not an ELF "
                    "executable or a wasm module (read a jar's build manifest with "
                    "`java -jar /path/to/dawn-selfhost.jar version -m <file>`)\n").encode())
        expect(["build", "--target", "jvm"], 2,
               err=("error: --target jvm is not supported by the native compiler; "
                    "use java -jar /path/to/dawn-selfhost.jar build ...\n").encode())
        expect(["lsp", "stray"], 2, err=b"error: usage: dawn lsp [--std <dir>]\n")
        expect(["lsp", "--std"], 2, err=b"error: --std needs a directory\n")
        for alias in ("--help", "-h", "help", "--version", "-V"):
            expect([alias, "stray"], 2, err=f"error: usage: dawn {alias}\n".encode())
        versions = [run(binary, argv, root, env) for argv in (["--version"], ["-V"], ["version"])]
        assert versions[0] == versions[1] == versions[2], versions
        assert versions[0][0] == 0 and versions[0][2] == b"", versions
        assert re.fullmatch(rb"dawnc " + re.escape(version.encode()) +
                            rb" \(native\)( b1:[0-9a-f]{12})?\n", versions[0][1]), versions
    assert not failures, f"{len(failures)} of {count} native CLI assertions failed"
    print(f"OK native CLI: {count} absolute assertions; help avoids std and tools")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dawnc", type=Path, required=True)
    parser.add_argument("--expect", required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, "scripts/native-source-tree.py", "--selftest"],
                   cwd=HERE.parents[1], check=True)
    check(args.dawnc.resolve(), args.expect)
    import semantic
    semantic.check(args.dawnc.resolve())

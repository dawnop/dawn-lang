#!/usr/bin/env python3
"""Build a private server using the real immutable analysis-policy entry.

Configuration and optional stderr observation are confined to a copied source
tree. Uninstrumented builds provide the same policy without measurement hooks;
neither variant adds a production command-line flag or protocol method. The
two anchors are the lsp-configured group of mutate.py, where the preflight
proves them against HEAD; the self-test's fixture is made of the same two.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import time

from cold import DAWN, HERE, ROOT, edit, owned
from lsp_stats import FIELDS

NATIVE_FLAGS = ("-std=c11", "-O2", "-fwrapv", "-fexceptions", "-fno-strict-aliasing", "-pthread")


def hashes(directory):
    # This is a staged artifact directory, not a repository-wide input root.
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def stage_source(source, output, text, backend="jvm"):
    output.mkdir(parents=True, exist_ok=False)
    fingerprints = {}
    for directory in ("selfhost", "compiler-plan"):
        shutil.copytree(source / directory, output / directory,
                        ignore=shutil.ignore_patterns("build", ".dawn"))
        for path in sorted((source / directory).rglob("*")):
            if path.is_file() and path.suffix in (".dawn", ".toml", ".lock"):
                fingerprints[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if backend == "native":
        for directory in ("packages", "std", "runtime/c"):
            shutil.copytree(source / directory, output / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
    else:
        (output / "packages").symlink_to(source / "packages", target_is_directory=True)
    (output / "selfhost/src/lsp/server.dawn").write_text(text)
    return fingerprints


def native_command(cc, output):
    return [cc, *NATIVE_FLAGS, "-I", str(output / "runtime/c"), "-o", str(output / "dawnc"),
            str(output / "nmain.c"), str(output / "runtime/c/dawn_rt.c"), "-lm"]


def build_native(output, cc_name):
    if os.environ.get("DAWN_SEED"):
        raise RuntimeError("native private builds require the normal verified seed")
    java_home = os.environ.get("JAVA_HOME")
    if not java_home:
        raise RuntimeError("set JAVA_HOME for native bootstrap tool provenance")
    java = (Path(java_home) / "bin/java").resolve(strict=True)
    cc_path = shutil.which(cc_name)
    if cc_path is None:
        raise RuntimeError("native C compiler executable was not found")
    cc = Path(cc_path).resolve(strict=True)
    launcher = Path(shutil.which(DAWN) or DAWN).resolve(strict=True)
    # The selected bootstrap may live outside the source checkout under test.
    bootstrap_directory = launcher.parent.parent
    bootstrap_jar = bootstrap_directory / "build/dawn-selfhost.jar"
    staged_inputs = {directory + "/" + path: value for directory in
                     ("selfhost", "compiler-plan", "packages", "std", "runtime/c")
                     for path, value in hashes(output / directory).items()}
    commands = []
    def run(label, command):
        started = time.monotonic()
        timed_out = False
        with (output / (label + ".log")).open("w") as log:
            process = subprocess.Popen([str(x) for x in command], cwd=output, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        commands.append({"label": label, "argv": [str(x) for x in command],
                         "status": process.returncode, "timed_out": timed_out,
                         "seconds": time.monotonic() - started})
        (output / "native-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if process.returncode or timed_out:
            raise RuntimeError(f"native {label} failed; see {output / (label + '.log')}")
    run("bootstrap-version", [launcher, "--version"])
    if not bootstrap_jar.is_file():
        raise RuntimeError("native bootstrap must expose its actual build/dawn-selfhost.jar")
    run("java-version", [java, "-version"])
    run("cc-version", [cc, "--version"])
    tools = [launcher, bootstrap_jar, java, cc]
    tools.extend(sorted((bootstrap_directory / "build/lib").glob("*.jar")))
    for name in ("cc1", "as", "ld"):
        value = subprocess.check_output([str(cc), "-print-prog-name=" + name], text=True,
                                        timeout=10).strip()
        path = Path(shutil.which(value) or value)
        if path.is_file():
            tools.append(path.resolve())
    tool_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tools}
    run("emitc", [launcher, "__emitc", "--std", str(output / "std"),
                  "selfhost/src/nmain.dawn", "-o", str(output / "nmain.c")])
    run("cc", native_command(str(cc), output))
    executable = output / "dawnc"
    with executable.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise RuntimeError("native compiler output is not an ELF executable")
    run("native-version", [executable, "--version"])
    current_inputs = {directory + "/" + path: value for directory in
                      ("selfhost", "compiler-plan", "packages", "std", "runtime/c")
                      for path, value in hashes(output / directory).items()}
    if current_inputs != staged_inputs:
        raise RuntimeError("native staged inputs changed during compilation")
    if tool_hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tools}:
        raise RuntimeError("native build tools changed during compilation")
    return {"native_inputs": staged_inputs, "std_sources": hashes(output / "std"),
            "native_outputs": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                               for name in ("nmain.c", "dawnc")},
            "native_tools": tool_hashes,
            "native_commands": commands,
            "tool_scope": "launcher and actual bootstrap jar, adjacent tool jars, Java, C compiler and discoverable cc1/as/ld; system headers/libraries are host-provided",
            "native_flags": NATIVE_FLAGS,
            "normal_seed_records": {str(path.relative_to(bootstrap_directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in (bootstrap_directory / "scripts").glob("seed-*.txt")}}


def anchors():
    """The policy entry's anchor and the observation edit, from mutate.py.
    The registry's policy edit is the default form; configure must make it."""
    group = owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"], "lsp-configured")
    (_, entry, default), = group["policy"]
    (_, point, observed), = group["observe"]
    return entry, point, observed, default


def configure(text, mode, modules, observe):
    if mode not in {"Legacy", "Cold"} or modules < 0:
        raise ValueError("invalid analysis policy or cache limit")
    entry, point, observed, _ = anchors()
    text = edit(text, entry,
                "run_lsp_configured(std_flag, host, LspAnalysisConfig { "
                f"mode: {mode}, max_modules: {modules}" + " })")
    if not observe:
        return text
    # Only a project workspace owns a session; a standalone buffer is
    # analysed cold and has no counts to report.
    text = edit(text, point, observed)
    values = ',\n        '.join(f"to_string(stats.{field})" for field in FIELDS)
    text += '''

# Private benchmark observer: absence is not a zero-work assertion.
fn benchmark_analysis_stats(scope: String, value: Option[incremental.Stats]) -> Unit !io =
  match value {
    None -> io.eprintln("LSP_BODY_STATS\\t" ++ scope ++ "\\tunobserved")
    Some(stats) -> io.eprintln("LSP_BODY_STATS\\t" ++ scope ++ "\\t" ++
      join([
        ''' + values + '''
      ], "\\t"))
  }
'''
    return text


def selftest():
    entry, point, _, default = anchors()
    fixture = "\n".join((entry, point))
    assert configure(entry, "Legacy", 128, False) == default
    for mode in ("Legacy", "Cold"):
        plain = configure(fixture, mode, 1, False)
        assert f"mode: {mode}, max_modules: 1 }}" in plain
        assert "benchmark_analysis_stats" not in plain
        observed = configure(fixture, mode, 1, True)
        assert observed.count("benchmark_analysis_stats(") == 2
        for field in FIELDS:
            assert observed.count(f"to_string(stats.{field})") == 1
    for source, mode, modules in (("", "Cold", 1), (fixture + fixture, "Cold", 1),
                                  (fixture, "Invalid", 1), (fixture, "Cold", -1)):
        try:
            configure(source, mode, modules, True)
        except (ValueError, RuntimeError):
            continue
        raise AssertionError("configuration accepted drifted anchors or invalid policy")
    print("OK: two private policies, observation schema, and four rejection controls")
    command = native_command("/tool/cc", Path("/private"))
    assert command[1:7] == list(NATIVE_FLAGS)
    assert command[-3:] == ["/private/nmain.c", "/private/runtime/c/dawn_rt.c", "-lm"]
    assert command.count("-o") == 1 and command[command.index("-o") + 1] == "/private/dawnc"
    print("OK: native recipe preserves canonical C flags and fresh runtime/output paths")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("Legacy", "Cold"), required=True)
    parser.add_argument("--max-modules", type=int, default=128)
    parser.add_argument("--uninstrumented", action="store_true")
    parser.add_argument("--backend", choices=("jvm", "native"), default="jvm")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="native C compiler executable")
    args = parser.parse_args()
    source = args.source.resolve()
    original = (source / "selfhost/src/lsp/server.dawn").read_text()
    # Validate configuration and exact anchors before creating any output.
    text = configure(original, args.mode, args.max_modules, not args.uninstrumented)
    output = args.output.resolve()
    fingerprints = stage_source(source, output, text, args.backend)
    native = {}
    if args.backend == "native":
        native = build_native(output, args.cc)
        artifact = output / "dawnc"
    else:
        artifact = output / "compiler.jar"
        with (output / "build.log").open("w") as log:
            subprocess.run([DAWN, "build", str(output / "selfhost"), "-o", str(artifact),
                            "--vendor", "org/objectweb/asm", "--vendor", "coursierapi"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    (output / "metadata.json").write_text(json.dumps({
        "source": str(source), "sources": fingerprints, "mode": args.mode,
        "max_modules": args.max_modules,
        "instrumented": not args.uninstrumented,
        "stats_fields": FIELDS,
        "note": "standalone buffers are analysed cold and report no counts; timing includes optional stderr observation",
        "configured_server_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "compiler_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "backend": args.backend,
        **native,
    }, indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        selftest()
    else:
        main()

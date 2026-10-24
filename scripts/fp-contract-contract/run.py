#!/usr/bin/env python3
"""Hold the real driver's and split compiler's Float rounding flags.

Cross-compile the emitted C, including its real runtime header, without an
AArch64 sysroot. Only math.h is stubbed (the emitter needs fmod's declaration).
The CC adapter assembles rather than links: its empty outputs only let the
caller finish staging, and are never run. Removing the flag from those same
captured arguments must fail the same assembly check. Native/JVM execution
and an explicit libc fma provide an independent numerical witness.
"""

import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FLAG = "-ffp-contract=off"
FUSED = re.compile(r"^\s*f(?:n?madd|n?msub)\s", re.MULTILINE)
INPUTS = ["1.0", "1.0000000074505806", "0.9999999925494194"]
EXPECTED = "0\n0\n"


def run(argv, **kwargs):
    result = subprocess.run(list(map(str, argv)), cwd=ROOT, text=True,
                            capture_output=True, **kwargs)
    if result.returncode:
        raise AssertionError(f"command failed ({result.returncode}): {argv}\n"
                             f"{result.stdout}{result.stderr}")
    return result.stdout


def no_fusion(assembly):
    assert not FUSED.search(assembly), "contracted Float arithmetic in emitted C"
    assert re.search(r"^\s*fmul\s", assembly, re.MULTILINE), "no multiply exercised"
    assert re.search(r"^\s*f(?:add|sub)\s", assembly, re.MULTILINE), "no add/subtract exercised"


def cc_adapter(argv):
    work = Path(os.environ["FP_CONTRACT_WORK"])
    if "-print-file-name=crt1.o" in argv:
        print(work / "crt1.o")
        return
    with (work / "argv.jsonl").open("a") as log:
        log.write(json.dumps(argv) + "\n")
    sources = [Path(a) for a in argv if a.endswith(".c") and
               Path(a).name not in {"dawn_rt.c", "dawn_rt_wasi_tag.c", "dawn_build_info.c"}]
    for source in sources:
        # Forward arithmetic/codegen flags from the actual invocation, not a
        # second hardcoded flag row that would survive a broken driver.
        flags = [a for a in argv if a.startswith(("-O", "-ffp-contract=", "-D")) or
                 a in {"-std=c11", "-fwrapv", "-fno-strict-aliasing"}]
        includes = []
        for i, arg in enumerate(argv[:-1]):
            if arg == "-I":
                includes += ["-I", argv[i + 1]]
        base = [os.environ["FP_CONTRACT_CLANG"], "--target=aarch64-linux-gnu",
                "-ffreestanding", "-Wno-parentheses-equality", "-S",
                "-I", work / "include", *includes, source]
        assembly = work / "arithmetic.s"
        run([*base, *flags, "-o", assembly])
        no_fusion(assembly.read_text())
        # A mutation of the real compiler arguments. It must compile and
        # reach the arithmetic assertion, rather than fail for another reason.
        run([*base, *(a for a in flags if a != FLAG), "-o", work / "mutant.s"])
        mutant = (work / "mutant.s").read_text()
        try:
            no_fusion(mutant)
        except AssertionError as error:
            assert str(error) == "contracted Float arithmetic in emitted C", error
        else:
            raise AssertionError("dropping the contraction flag stayed green")
        print(f"PASS aarch64: separate arithmetic; dropped-flag mutant red "
              f"({len(FUSED.findall(mutant))} fused instructions)")
    # The C++ shim, tag and link are captured too, but need no aarch64 object.
    Path(argv[argv.index("-o") + 1]).touch()


def capture(command, work, clang):
    work.mkdir()
    (work / "include").mkdir()
    (work / "include/math.h").write_text("double fmod(double, double);\n")
    (work / "crt1.o").touch()
    adapter = work / "cc"
    adapter.write_text("#!/bin/sh\nexec " + shlex.join(
        [sys.executable, str(Path(__file__).resolve()), "--cc"]) + ' "$@"\n')
    adapter.chmod(0o755)
    env = dict(os.environ, CC=str(adapter), DAWN_WASM_CC=str(adapter),
               FP_CONTRACT_WORK=str(work), FP_CONTRACT_CLANG=clang, CC_JOBS="1")
    output = run(command, env=env)
    calls = [json.loads(line) for line in (work / "argv.jsonl").read_text().splitlines()]
    assert calls, "no compiler invocation captured"
    for argv in calls:
        assert argv.count(FLAG) == 1, f"compile/link missing its rounding flag: {argv}"
    assert (work / "arithmetic.s").is_file(), "no emitted C was assembled"
    print(output, end="")
    return calls


def main():
    started = time.monotonic()
    clang = os.environ.get("DAWN_PINNED_CC") or os.environ.get("CC")
    if not clang or "clang" not in run([clang, "--version"]).lower():
        clang = shutil.which("clang-20") or shutil.which("clang")
    assert clang, "clang is required for the aarch64 contraction contract"
    clang = shutil.which(clang) or clang
    with tempfile.TemporaryDirectory(prefix="fp-contract.", dir=os.environ.get("TMPDIR")) as tmp:
        work = Path(tmp)
        driver = os.environ.get("DAWNC_BIN")
        if not driver:
            run([ROOT / "bin/dawn", "__emitc", ROOT / "selfhost/src/nmain.dawn",
                 "--split", work / "driver"])
            run([ROOT / "scripts/cc-units.sh", "-o", work / "dawnc", work / "driver"],
                env=dict(os.environ, CC=clang))
            driver = str(work / "dawnc")
        driver = str(Path(shutil.which(driver) or driver).resolve())
        for target in ["native", "wasm"]:
            options = [] if target == "native" else ["--target", "wasm"]
            calls = capture([driver, "build", *options, HERE / "arithmetic.dawn",
                             "-o", work / "unused"], work / target, clang)
            assert len(calls) == (1 if target == "native" else 3), calls
            print(f"PASS driver: {target} compile arguments")
        units = work / "units"
        units.mkdir()
        run([driver, "emitc", HERE / "arithmetic.dawn", "-o", units / "main.c"])
        capture([ROOT / "scripts/cc-units.sh", "-o", work / "unused", units],
                work / "split", clang)
        print("PASS cc-units: emitted C compile arguments")
        for command in [[ROOT / "bin/dawn", "run"], [driver, "run"]]:
            actual = run([*command, HERE / "arithmetic.dawn", "--", *INPUTS],
                         env=dict(os.environ, CC=clang))
            assert actual == EXPECTED, actual
        # b*c = 1 - 2^-54 before rounding. Separate operations give +0;
        # fma(-b,c,1) gives +2^-54, fma(b,c,-1) gives -2^-54 exactly.
        libm = ctypes.CDLL(ctypes.util.find_library("m") or None)
        fma = libm.fma
        fma.argtypes = [ctypes.c_double] * 3
        fma.restype = ctypes.c_double
        a, b, c = map(float, INPUTS)
        assert a - b * c == b * c - a == 0.0
        assert fma(-b, c, a) == 2.0 ** -54
        assert fma(b, c, -a) == -(2.0 ** -54)
        print("PASS values: JVM/native bits are 0; fused results are +2^-54 and -2^-54")
    print(f"fp contraction contract ok ({time.monotonic() - started:.2f}s)")


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] == "--cc":
        cc_adapter(sys.argv[2:])
    else:
        main()

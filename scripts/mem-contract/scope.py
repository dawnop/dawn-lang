#!/usr/bin/env python3
"""Exercise final Mem contracts and the actual emitted evidence lookup on both VMs.

The emitter suffix supplies Core that source programs cannot spell. Its two
same-effect records have distinct payloads, so selecting the wrong Scope is
observable even though the public Mem allocation handlers do the same work.
Every negative control must build successfully before its semantic assertion
can fail; compiler errors and missing fixture files never count as a kill.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

# mutate.py owns every source edit exercised below.
from mutate import MUTATIONS, apply

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
JAVA = subprocess.check_output([str(ROOT / "bin/dawn")], env={**os.environ, "DAWN_LAUNCHER_PRINT_JAVA": "1"}, text=True).strip()
JAR = ROOT / "build/dawn-selfhost.jar"


def run(args, *, cwd=ROOT, output=None, expect=0, env=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if output is not None:
        Path(output).write_text(result.stdout)
    if expect is not None and result.returncode != expect:
        raise RuntimeError(f"command exited {result.returncode}, expected {expect}: {args}\n{result.stdout}")
    return result


def compiler(tree=ROOT):
    # Mutant copies exclude build artifacts, but use the same verified seed
    # cache as the parent launcher so an offline gate never needs a download.
    seeds = Path(os.environ.get("DAWN_SEED_CACHE", ROOT / ".dawn/seeds")).resolve()
    run([tree / "bin/dawn", "--version"], cwd=tree, env={**os.environ, "DAWN_SEED_CACHE": str(seeds)})
    return tree / "build/dawn-selfhost.jar"


def copy_tree(target):
    # The launcher extracts the pinned seed's std from its tag, even in a
    # mutant tree. A shared clone supplies those objects without a checkout.
    run(["git", "clone", "--shared", "--no-checkout", ROOT, target])
    shutil.copytree(ROOT, target, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", ".dawn", "build", "node_modules", "dist", "target", "__pycache__"))


def check(jar, source, output, expected):
    result = run([JAVA, "-jar", jar, "check", "--std", ROOT / "std", HERE / source], output=output, expect=expected)
    return result.stdout


def emit_probe(work, tree, jar, runtime_jar):
    source = tree / "selfhost/src/jvm/emit.dawn"
    source.write_text(source.read_text() + "\n" + (HERE / "scope-abi.dawn.txt").read_text())
    emitter = work / "emitter.jar"
    run([JAVA, "-Xss512m", "-jar", jar, "build", source, "-o", emitter, "--std", ROOT / "std",
         "--vendor", "org/objectweb/asm", "--vendor", "coursierapi"], output=work / "build.log")
    result = run([JAVA, "-Xss512m", "-jar", emitter])
    (work / "ScopeEvidenceProbe.class").write_bytes(bytes.fromhex(result.stdout.strip()))
    run(["javac", "-d", work, HERE / "ScopeEvidenceMain.java"])
    return run([JAVA, "-cp", f"{work}{os.pathsep}{runtime_jar}", "ScopeEvidenceMain"], output=work / "run.log", expect=None)


def c_probe(work, tree):
    output = work / "scope_abi"
    run([os.environ.get("CC", "cc"), "-std=c11", "-O1", "-ffunction-sections", ("-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"), "-fwrapv", "-pthread", "-fexceptions", "-ffp-contract=off",
         "-I", tree / "runtime/c", HERE / "scope_abi.c", tree / "runtime/c/dawn_rt.c", "-lm", "-o", output], output=work / "build.log")
    return run([output], output=work / "run.log", expect=None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    compiler()
    with tempfile.TemporaryDirectory(prefix="mem-scope-contract-") as temporary:
        out = args.out or Path(temporary)
        out.mkdir(parents=True, exist_ok=True)
        for source, expected in (("scope_ok.dawn", "10\n11\n2\n"), ("scope_alias.dawn", "7\n"), ("scope_wide.dawn", "36\n")):
            result = run([JAVA, "-Xss512m", "-jar", JAR, "run", HERE / source], output=out / (source + ".log"))
            if result.stdout != expected:
                raise RuntimeError(f"{source}: unexpected stdout {result.stdout!r}")
        assert "escapes its scoped callback" in check(JAR, "scope_escape.dawn", out / "escape.log", 1)
        assert "I64Buf@outer but the initializer is I64Buf@inner" in check(JAR, "scope_relabel.dawn", out / "relabel.log", 1)
        runtime_jar = out / "runtime.jar"
        run([JAVA, "-jar", JAR, "build", HERE / "scope_ok.dawn", "-o", runtime_jar])
        base = out / "jvm-base"
        base.mkdir()
        tree = base / "tree"
        copy_tree(tree)
        result = emit_probe(base, tree, JAR, runtime_jar)
        if result.returncode:
            raise RuntimeError(f"JVM evidence baseline failed:\n{result.stdout}")
        print(result.stdout.strip(), flush=True)
        cbase = out / "native-base"
        cbase.mkdir()
        if c_probe(cbase, ROOT).returncode:
            raise RuntimeError("C evidence baseline failed")
        print("PASS  native evidence domains, append and fresh instances", flush=True)
        if not args.selftest:
            return
        for name in MUTATIONS:
            work = out / name
            work.mkdir()
            tree = work / "tree"
            copy_tree(tree)
            apply(name, tree)
            if name.startswith("jvm-"):
                killed = emit_probe(work, tree, JAR, runtime_jar).returncode != 0
            elif name.startswith("native-"):
                killed = c_probe(work, tree).returncode != 0
            else:
                mutant = compiler(tree)
                source = "scope_escape.dawn" if name == "allow-scope-escape" else "scope_relabel.dawn"
                # The original refusal must be lost. A build error never reaches here.
                check(mutant, source, work / "check.log", 0)
                killed = True
            if not killed:
                raise RuntimeError(f"survived: {name}")
            print(f"PASS  built negative control {name}", flush=True)


if __name__ == "__main__":
    main()

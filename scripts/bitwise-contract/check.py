#!/usr/bin/env python3
"""Close the bitwise audit with independent values and compiling controls.

The host oracle is already consumed by runtime, comptime and LSP tests. Use
its exact integer vectors against the interpreter's private integer evaluator
and the independent reference too, without adding a production API or a
dependency between those packages. Scratch copies also keep every mutation
away from the checkout and regenerate the std embedding before building it.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
DAWN = ROOT / "bin/dawn"


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = load(ROOT / "scripts/fixed-ints/gen.py")
MUTATOR = Path(__file__).with_name("mutate.py")
NAMES = tuple(load(MUTATOR).MUTATIONS)


def run(args, *, expected=0):
    p = subprocess.run(list(map(str, args)), cwd=ROOT, capture_output=True, text=True, timeout=900)
    if expected is not None and p.returncode != expected:
        raise RuntimeError(f"{args[0]} exited {p.returncode}:\n{p.stdout[-6000:]}\n{p.stderr[-6000:]}")
    return p


def dawn_list(xs):
    return "[" + ", ".join(map(str, xs)) + "]"


def cross_layer(work):
    packages = work / "packages"
    packages.mkdir()
    (packages / "tileir").symlink_to(ROOT / "packages/tileir", target_is_directory=True)
    for package, module in [("tileinterp", "interp"), ("tileref", "ref")]:
        target = packages / package
        shutil.copytree(ROOT / "packages" / package, target)
        tests = []
        for w in [8, 16, 32, 64]:
            counts, rows = ORACLE.bitwise_vectors(w, True)
            for i, (a, b, want) in enumerate(rows):
                tests.append(f'\ntest "closeout integer oracle i{w} row {i}" {{')
                if package == "tileinterp":
                    tests.extend([
                        "  with_mem(() => {",
                        "    for checks in [false, true] {",
                        "      let cx = Cx { bufs: [], lens: [], written: mem.new(0), params: [], dtypes: [], bid: [0, 0, 0], grid: [1, 1, 1], ub: checks }",
                        "      var got: List[Int] = []",
                        f"      for n in {dawn_list(counts)} {{",
                        "        got = got ++ [" + ", ".join(
                            f'int_bin(cx, "{op}", {w}, {a}, {rhs})'
                            for op, rhs in [("andi", b), ("ori", b), ("xori", b), ("xori", -1),
                                            ("shli", "n"), ("shri", "n"), ("shru", "n")]) + "]",
                        "      }",
                        f"      assert got == {dawn_list(want)}",
                        "    }",
                        "  })",
                    ])
                else:
                    tests.append(f"  assert bitwise_ref_int({w}, [{a}], [{b}]) == {dawn_list(want[:4])}")
                    shifts = [want[j * 7 + op] for op in [4, 5, 6] for j in range(len(counts))]
                    tests.append(f"  assert shift_ref_int({w}, {dawn_list([a] * len(counts))}, {dawn_list(counts)}) == {dawn_list(shifts)}")
                tests.append("}")
        with (target / "src" / f"{module}.dawn").open("a") as f:
            f.write("\n".join(tests) + "\n")
        p = run([DAWN, "test", target])
        matched = [s for s in p.stdout.splitlines() if s.startswith("PASS  ") and "closeout integer oracle" in s]
        if len(matched) != 28:
            raise RuntimeError(f"{package}: expected 28 executed oracle tests:\n{p.stdout}")
        print(f"PASS {package}: 28 shared rows, 2156 integer expectations" +
              (", both UB modes" if package == "tileinterp" else ""), flush=True)


def c_build(c, target, cc, opt):
    run([cc, "-std=c11", opt, "-fwrapv", "-fexceptions", "-fno-strict-aliasing",
         "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread",
         "-I", ROOT / "runtime/c", "-o", target, c, ROOT / "runtime/c/dawn_rt.c", "-lm"])


def ubsan(work):
    # CC is pinned clang in CI; gcc must remain a separate compiler family.
    clang = os.environ.get("DAWN_PINNED_CC") or shutil.which("clang-18")
    gcc = shutil.which("gcc")
    if not clang or not gcc:
        raise RuntimeError("both gcc and pinned clang-18 are required")
    for name in ["bitwise_fixed", "int_edges"]:
        source = ROOT / "scripts/spike-native" / name
        if not source.is_dir():
            source = source.with_suffix(".dawn")
        want = (ROOT / "scripts/spike-native" / f"{name}.expect").read_text()
        if run([DAWN, "run", source]).stdout != want:
            raise RuntimeError(f"{name}: JVM oracle mismatch")
        c = work / f"{name}.c"
        run([DAWN, "__emitc", source, "-o", c])
        for family, cc in [("gcc", gcc), ("clang", clang)]:
            for opt in ["-O0", "-O2"]:
                target = work / f"{name}-{family}-{opt[1:]}"
                c_build(c, target, cc, opt)
                p = run([target])
                if p.stdout != want or p.stderr:
                    raise RuntimeError(f"{name} {family} {opt}: oracle or UBSan mismatch:\n{p.stderr}")
                print(f"PASS {name} {family} {opt} UBSan: exact oracle, empty stderr", flush=True)


def checker(jar, case, std):
    p = run(["java", "-Xss512m", "-Xmx2g", "-jar", jar, "__check",
             "--std", std,
             ROOT / "scripts/checker-corpus/cases" / case])
    return "\n".join(s for s in p.stdout.splitlines() if s.startswith("D\t"))


PROBES = {
    "narrow-logical": ("i8", "i8.I8", "i8.to_int(a >>> n)", "i8.wrap(-1), 1", "127\n"),
    "negative-count": ("i8", "i8.I8", "i8.to_int(a << n)", "i8.wrap(1), -1", "-128\n"),
    "unsigned-right": ("u64", "u64.U64", "u64.to_int(a >> n)", "u64.MAX, 63", "1\n"),
    "c-truncation": ("i8", "i8.I8", "i8.to_int(a << n)", "i8.wrap(127), 7", "-128\n"),
}


def controls(work, only):
    baseline = ROOT / "build/dawn-selfhost.jar"
    # These fixtures use the prelude alone. The broken Amount would reject
    # migrated std impls before reaching the checker fixture at all.
    std = work / "prelude-only"
    std.mkdir()
    (std / "modules.txt").write_text("# Prelude-only checker control.\n")
    cases = {name: checker(baseline, name, std) for name in ["binary_ops.dawn", "bitwise_ops.dawn"]}
    run([DAWN, "test", ROOT / "selfhost/src/check/checker.dawn"])
    for name in NAMES:
        if only and name != only:
            continue
        tree = work / name
        for part in ["selfhost", "compiler-plan", "std"]:
            shutil.copytree(ROOT / part, tree / part, ignore=shutil.ignore_patterns("build", ".dawn"))
        (tree / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        run([sys.executable, MUTATOR, name, tree])
        if name in PROBES:
            (tree / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/gen-stdsrc.py", tree / "scripts/gen-stdsrc.py")
            run([sys.executable, tree / "scripts/gen-stdsrc.py"])
        jar = tree / "compiler.jar"
        run([DAWN, "build", tree / "selfhost", "-o", jar])
        run(["java", "-jar", jar, "--version"])
        if name == "effect-forward":
            p = run([DAWN, "test", tree / "selfhost/src/check/checker.dawn"], expected=None)
            marker = "FAIL  check/checker :: bitwise Int operators keep native TAST and Amount reduces before a count is checked"
            if p.returncode == 0 or marker not in p.stdout or "\nerror:" in p.stdout + p.stderr:
                raise RuntimeError(f"{name}: missed owning checker test:\n{p.stdout[-4000:]}")
        elif name not in PROBES:
            case = "binary_ops.dawn" if name == "int-trait" else "bitwise_ops.dawn"
            if checker(jar, case, std) == cases[case]:
                raise RuntimeError(f"{name}: checker corpus stayed green")
        else:
            mod, ty, expr, args, want = PROBES[name]
            source = tree / "probe.dawn"
            source.write_text(f"# Runtime operands prevent folding away the mutation.\nuse std/int/{mod}\n"
                              f"fn probe(a: {ty}, n: Int) -> Int = {expr}\n"
                              f'pub fn main() -> Unit !io = println(to_string(probe({args})))\n')
            if run([DAWN, "run", source]).stdout != want:
                raise RuntimeError(f"{name}: positive control failed")
            if name == "c-truncation":
                c, target = tree / "probe.c", tree / "probe.bin"
                run(["java", "-Xss512m", "-Xmx2g", "-jar", jar, "__emitc", source, "-o", c])
                c_build(c, target, "gcc", "-O2")
                p = run([target])
            else:
                p = run(["java", "-Xss512m", "-Xmx2g", "-jar", jar, "run", "--std", tree / "std", source])
            if p.stdout == want or p.stderr:
                raise RuntimeError(f"{name}: numerical control stayed green or crashed: {p}")
            print(f"RED {name}: expected={want.strip()} actual={p.stdout.strip()}", flush=True)
        print(f"PASS mutant {name}: compiler built, owning check red", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=NAMES)
    parser.add_argument("--values-only", action="store_true")
    parser.add_argument("--controls-only", action="store_true")
    args = parser.parse_args()
    run([DAWN, "--version"])
    with tempfile.TemporaryDirectory(prefix="bitwise-contract-") as tmp:
        work = Path(tmp)
        if not args.only and not args.controls_only:
            cross_layer(work)
            ubsan(work)
        if not args.values_only:
            controls(work, args.only)
    print("OK: bitwise closeout contract", flush=True)


if __name__ == "__main__":
    main()

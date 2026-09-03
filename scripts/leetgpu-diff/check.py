#!/usr/bin/env python3
"""The leetgpu ledger's gate: every problem it lists is backed by a kernel.

    scripts/leetgpu-diff/check.py              # check problems.txt
    scripts/leetgpu-diff/check.py --self-test  # negative control

`problems.txt` says which leetgpu problems this backend solves. On its own
that is a claim; this turns each row into things a machine can look up:

  * the kernel has a text golden and a bytecode golden in scripts/tile-golden
    (so layer 0 pins its spelling and layer 1 has handed it to `tileiras`);
  * scripts/tile-golden/run.sh runs it, and kernels.dawn traces it (so the
    goldens are not files nobody compares);
  * the reference exists in the module the row names, and is public;
  * the layer-2 program names the kernel as one of its cases (so the GPU
    computed it against that reference), and classifies it under the tier
    the row claims (the program's own `tolerance_tier()` list is the
    authority, so a row cannot promise bit-exactness the run does not
    check);
  * and the layer-2 ledger's last line records a run that PASSED. A problem
    is listed as solved only while a device has agreed, so a `blocked` run --
    which scripts/tile-gpu-diff/run.sh --check accepts, because an honest
    record of a driver that cannot load a cubin is worth more than none --
    is not enough to keep a row here.

What it does not check: that the kernel actually computes the problem. That
is what the reference and the layer-2 corpus are for, and the reference is
hand-written beside the kernel rather than derived from it.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLE = ROOT / "scripts" / "leetgpu-diff" / "problems.txt"
GOLDEN = ROOT / "scripts" / "tile-golden"
LEDGER = ROOT / "scripts" / "tile-gpu-diff" / "ledger.txt"
TIERS = ("exact", "tolerance")


def tolerance_tier(program_text):
    """The kernels a layer-2 program compares under the tolerance tier.

    Read off its `tolerance_tier()` list, which is the program's own answer;
    a program without one compares everything bit for bit.
    """
    m = re.search(r"pub fn tolerance_tier\(\) -> List\[String\] =\s*\[([^\]]*)\]", program_text)
    if not m:
        return set()
    return {name.strip().strip(chr(34)) for name in m.group(1).split(",") if name.strip()}


def rows(text):
    """The table's data lines, as lists of fields."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append((n, [f.strip() for f in s.split("|")]))
    return out


def read(path):
    return path.read_text() if path.exists() else ""


def check(table_text, files, ledger_text):
    """The problems the table lists, and what is wrong with it.

    `files` maps a repository path to its contents; `ledger_text` is the
    layer-2 ledger. Everything the checker reads arrives here, so the
    self-test can hand it a table nobody would commit.
    """
    problems = []
    seen = {}
    listed = []
    for n, fields in rows(table_text):
        if len(fields) != 6:
            problems.append(f"line {n}: {len(fields)} fields, not 6")
            continue
        pid, title, kernel, reference, corpus, tier = fields
        listed.append(pid)
        if not pid.isdigit():
            problems.append(f"line {n}: problem id {pid!r} is not a number")
        elif pid in seen:
            problems.append(f"line {n}: problem {pid} is already listed on line {seen[pid]}")
        else:
            seen[pid] = n
        if not title:
            problems.append(f"line {n}: problem {pid} has no title")
        if tier not in TIERS:
            problems.append(f"line {n}: tier {tier!r} is not one of {', '.join(TIERS)}")

        for suffix in (".mlir", ".tilebc"):
            if f"scripts/tile-golden/{kernel}{suffix}" not in files:
                problems.append(f"line {n}: {kernel} has no {suffix} golden in scripts/tile-golden")
        run_sh = files.get("scripts/tile-golden/run.sh", "")
        kernels = re.search(r"^kernels=\(([^)]*)\)", run_sh, re.M)
        if not kernels:
            problems.append("scripts/tile-golden/run.sh has no kernels=( ... ) list")
        elif kernel not in kernels.group(1).split():
            problems.append(f"line {n}: {kernel} is not in scripts/tile-golden/run.sh's kernel list")
        if f'"{kernel}" ->' not in files.get("scripts/tile-golden/kernels.dawn", ""):
            problems.append(f"line {n}: scripts/tile-golden/kernels.dawn does not trace {kernel}")

        if "." not in reference:
            problems.append(f"line {n}: reference {reference!r} is not <module>.<function>")
        else:
            module, fn = reference.rsplit(".", 1)
            path = module.replace(".", "/") + ".dawn"
            if path not in files:
                problems.append(f"line {n}: reference module {path} does not exist")
            elif not re.search(rf"^pub fn {re.escape(fn)}\b", files[path], re.M):
                problems.append(f"line {n}: {path} has no public function {fn}")

        if ":" not in corpus:
            problems.append(f"line {n}: corpus {corpus!r} is not <program>:<case>")
        else:
            program, case = corpus.split(":", 1)
            path = f"scripts/tile-gpu-diff/{program}.dawn"
            if path not in files:
                problems.append(f"line {n}: layer-2 program {path} does not exist")
            elif f'"{case}"' not in files[path]:
                problems.append(f"line {n}: {path} has no case named {case}")
            else:
                claimed = "tolerance" if case in tolerance_tier(files[path]) else "exact"
                if claimed != tier:
                    problems.append(
                        f"line {n}: the row claims tier {tier!r} but {path} compares {case} under "
                        f"{claimed!r}")
            if case != kernel:
                problems.append(f"line {n}: the corpus runs {case} but the row names kernel {kernel}")

    if not listed:
        problems.append("the table lists no problems at all")

    entries = [ln.split("#", 1)[0].split() for ln in ledger_text.splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    if not entries:
        problems.append("scripts/tile-gpu-diff/ledger.txt has no entry: nothing has run on a device")
    elif len(entries[-1]) != 6:
        problems.append("the last line of scripts/tile-gpu-diff/ledger.txt does not parse")
    elif entries[-1][5] != "pass":
        problems.append(
            f"the last layer-2 run recorded {entries[-1][5]!r}, not `pass`: a problem is listed here only "
            f"while a device has agreed with the reference")
    return listed, problems


def gather():
    files = {}
    for path in [
        "scripts/tile-golden/run.sh",
        "scripts/tile-golden/kernels.dawn",
        "std/gpu.dawn",
        "scripts/tile-gpu-diff/mask_diff.dawn",
        "scripts/tile-gpu-diff/vadd_diff.dawn",
        "scripts/tile-gpu-diff/red_diff.dawn",
        "scripts/tile-gpu-diff/mm_diff.dawn",
        "scripts/tile-gpu-diff/stride_diff.dawn",
    ]:
        files[path] = read(ROOT / path)
    for golden in GOLDEN.glob("*"):
        if golden.suffix in (".mlir", ".tilebc"):
            files[f"scripts/tile-golden/{golden.name}"] = ""
    return files


def self_test():
    """Every verdict above, on a table built to trip it, and a clean control."""
    files = gather()
    good = TABLE.read_text()
    ledger = read(LEDGER)
    listed, problems = check(good, files, ledger)
    if problems:
        print("FAIL: --self-test needs the real table to be clean first:")
        for p in problems:
            print("  " + p)
        return 1

    cases = [
        ("a row with too few fields", good + "\n99 | Nope | k | m.f\n", "fields, not 6"),
        ("a problem id that is not a number", good + "\nxx | Nope | relu | std/gpu.relu_ref | mask_diff:relu | exact\n",
         "is not a number"),
        ("the same problem twice", good + "\n1 | Vector Addition | vadd_tail | std/gpu.masked_vadd_ref"
         " | mask_diff:vadd_tail | exact\n", "is already listed"),
        ("a tier nobody defined", good + "\n99 | Nope | relu | std/gpu.relu_ref | mask_diff:relu | eyeball\n",
         "is not one of"),
        ("a kernel with no golden", good + "\n99 | Nope | ghost | std/gpu.relu_ref | mask_diff:relu | exact\n",
         "has no .mlir golden"),
        ("a reference that does not exist", good + "\n99 | Nope | relu | std/gpu.no_such_ref | mask_diff:relu | exact\n",
         "has no public function"),
        ("a corpus case the layer-2 program does not run",
         good + "\n99 | Nope | relu | std/gpu.relu_ref | mask_diff:ghost | exact\n", "has no case named ghost"),
        ("a row claiming a tier the layer-2 program does not compare under",
         good.replace("| red_diff:softmax | tolerance", "| red_diff:softmax | exact"),
         "compares softmax under 'tolerance'"),
        ("an empty table", "# nothing\n", "lists no problems at all"),
    ]
    bad = 0
    for name, table, want in cases:
        _listed, found = check(table, files, ledger)
        if any(want in p for p in found):
            print(f"PASS  self-test: {name}")
        else:
            print(f"FAIL  self-test: {name} was accepted (wanted {want!r}, got {found})")
            bad += 1

    for name, text, want in [
        ("an empty layer-2 ledger", "# only a comment\n", "has no entry"),
        ("a layer-2 run that was blocked",
         "abc123abc123 2026-09-03 616.56 13.3.36 sm_86 blocked:x@launch\n", "not `pass`"),
    ]:
        _listed, found = check(good, files, text)
        if any(want in p for p in found):
            print(f"PASS  self-test: {name}")
        else:
            print(f"FAIL  self-test: {name} was accepted (wanted {want!r}, got {found})")
            bad += 1

    # the positive control: the real inputs stay clean
    _listed, found = check(good, files, ledger)
    if found:
        print(f"FAIL  self-test: the real table stopped being clean: {found}")
        bad += 1
    else:
        print("PASS  self-test: the real table and ledger are clean (the positive control)")
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ["--self-test"]:
        return self_test()
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 2
    listed, problems = check(TABLE.read_text(), gather(), read(LEDGER))
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    print(f"PASS  leetgpu: {len(listed)} problem(s) listed, each with a golden, a reference, a layer-2 case "
          f"and a passing device run: {', '.join(listed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

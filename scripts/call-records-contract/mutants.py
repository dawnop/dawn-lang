#!/usr/bin/env python3
"""Negative controls for the compiler-written call records.

    mutants.py author      # source mutants of the library and kernels (no rebuild)
    mutants.py compiler    # one change to the compiler per mutant (rebuilds it)

Every mutant must turn run.py red, and red for the reason it names: a mutant
that goes red for some other reason (a crash, an unrelated diff) is reported
as a failure of the control, not a pass. A control that stays green says the
comparison does not look at what the mutant broke.

Author layer: the library or a kernel is changed so that a function is no
longer recorded, which is the new spelling of "delete the hand-written mark". Compiler layer: one insertion the compiler
makes is removed or bent, in a copy-and-restore of the compiler's own source.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

SUBSET = "vadd,sum,softmax,flash_attn_bf16_demo,matmul,staged_if,loop_return"

# (name, relative file, old, new, regex the red output must match)
COMPILER = [
    ("missing-function", "selfhost/src/check/passes.dawn",
     "  let h = match hooks {\n    Some(h) -> h\n    None -> return (cx, None)\n  }\n  if len(caller_params) > 1 {",
     "  let h = match hooks {\n    Some(h) -> h\n    None -> return (cx, None)\n  }\n  if name == \"load_cell\" { return (cx, None) }\n  if len(caller_params) > 1 {",
     r"row count \d+ vs \d+|name load_cell"),
    ("wrong-name", "selfhost/src/check/passes.dawn",
     "(cx, Some(CallPlan { eid = eid, hooks = h, name = name, at = at, bodies = bodies }))",
     "(cx, Some(CallPlan { eid = eid, hooks = h, name = name ++ \"_\", at = at, bodies = bodies }))",
     r"name \w+ vs \w+_"),
    ("wrong-parent", "selfhost/src/ir/lower.dawn",
     "CBlock(entered ++ [CSLet(rv, f.sig.ret, inner), CSDiscard(hook_call(st_in, pl.eid, pl.hooks.exit, []))],",
     "CBlock(entered ++ [CSDiscard(hook_call(st_in, pl.eid, pl.hooks.exit, [])), CSLet(rv, f.sig.ret, inner)],",
     r"parent -?\d+ vs -?\d+|ops_to"),
    ("dropped-closure-bracket", "selfhost/src/check/passes.dawn",
     "if fid == eid && not list.contains(bodies, k) { bodies = bodies ++ [k] }",
     "if false && fid == eid && not list.contains(bodies, k) { bodies = bodies ++ [k] }",
     r"parent -?\d+ vs -?\d+|row count"),
    ("unbalanced-early-return", "selfhost/src/ir/lower.dawn",
     "st_in = LSt { ..stb, on_return = Some(hook_call(stb, pl.eid, pl.hooks.exit, [])) }",
     "st_in = LSt { ..stb, on_return = None }",
     r"transcript differs"),
    ("forwarded-closure-bracketed-twice", "selfhost/src/ir/lower.dawn",
     "if sym == bracketed { swapped = CLocal(raw, lty) }",
     "if sym == bracketed { swapped = a }",
     r"transcript differs|parent -?\d+ vs -?\d+"),
    ("missing-enter", "selfhost/src/ir/lower.dawn",
     "let entered = prologue ++ [CSDiscard(hook_call(st_in, pl.eid, pl.hooks.enter, enter_args(st_in, f, pl)))]",
     "let entered = prologue",
     r"closes nothing|transcript differs|row count"),
]

# source edits at the author layer, each the new spelling of "delete the
# hand-written mark": (name, file, old, new, regex). The effect stops
# declaring `calls(..)`, or an author helper stops being a public function
# with the effect.
AUTHOR = [
    ("recorder-effect-declares-no-calls", "dev",
     "pub effect Dev calls(enter = t_call_enter, exit = t_call_exit,\n  body_enter = t_body_enter, body_exit = t_body_exit) {",
     "pub effect Dev {", r"row count \d+ vs 0|name|rows"),
    ("author-helper-not-public", "kernels", "pub fn fa_exp[", "fn fa_exp[", r"name fa_exp vs \w+"),
]


def run(args):
    r = subprocess.run([sys.executable, str(HERE / "run.py")] + args, capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


def author():
    ok = True
    dev = (ROOT / "packages/tileir/src/dev.dawn").read_text()
    for name, which, old, new, rx in AUTHOR:
        if which == "dev":
            if dev.count(old) != 1:
                print("MUTANT %s: anchor %r not found" % (name, old))
                ok = False
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".dawn", delete=False) as f:
                f.write(dev.replace(old, new, 1))
            args = ["--only", SUBSET, "--no-cases", "--dev", f.name]
        else:
            args = ["--only", SUBSET, "--no-cases", "--kernel-edit", old, new]
        code, out = run(args)
        red = code != 0 and re.search(rx, out)
        print("MUTANT %s: %s" % (name, "red for the right reason" if red else "NOT RED (exit %d)\n%s" % (code, out[-1500:])))
        ok = ok and bool(red)
    return ok


def compiler():
    ok = True
    for name, rel, old, new, rx in COMPILER:
        path = ROOT / rel
        orig = path.read_text()
        if orig.count(old) != 1:
            print("MUTANT %s: anchor found %d times in %s" % (name, orig.count(old), rel))
            ok = False
            continue
        backup = Path(tempfile.mkdtemp()) / "orig"
        shutil.copy(path, backup)
        try:
            path.write_text(orig.replace(old, new, 1))
            code, out = run(["--only", SUBSET])
        finally:
            shutil.copy(backup, path)
        red = code != 0 and re.search(rx, out)
        print("MUTANT %s: %s" % (name, "red for the right reason" if red else "NOT RED (exit %d)\n%s" % (code, out[-1500:])))
        ok = ok and bool(red)
    return ok


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "author"
    sys.exit(0 if (author() if which == "author" else compiler()) else 1)

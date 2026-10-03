#!/usr/bin/env bash
# Prove the panic barrier in ir/interp `eval_closed` is load-bearing.
#
# `eval_closed` folds one expression for an editor, inside a language server
# that must outlive every fold. Lowering and the interpreter report a broken
# invariant by panicking (ARC-06), so the entry runs the fold under
# `catch_panic`. The unit test "a lowering panic inside an editor fold comes
# back as an Err" checks the barrier holds; on its own that is a green with no
# information, since it would also be green if nothing ever panicked. This
# script removes the barrier from a private copy of selfhost and requires the
# same test to fail on the raw lowering panic: the panic that, in a server,
# ends the process. The test runner catches it per test, which is why the
# evidence is the panic text under that test's FAIL line rather than an exit.
#
# It is one more compiling mutant of the comptime-trace-contract kind and
# costs what one of those costs: a copy of selfhost compiled and tested once.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work=$(mktemp -d "${TMPDIR:-/tmp}/comptime-eval-closed-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test_name='a lowering panic inside an editor fold comes back as an Err'
# the escaped panic's message and the file of its call site; not the line and
# column, which move with every edit to lowering
panic_text='lower: XError reached lowering at src/ir/lower.dawn:'

mutant="$work/selfhost"
cp -R "$root/selfhost" "$mutant"
cp -R "$root/compiler-plan" "$work/compiler-plan"
ln -s "$root/packages" "$work/packages"

python3 - "$mutant/src/ir/interp.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
start = text.index("pub(pkg) fn eval_closed(")
end = text.index("\nfn closed_reason(", start)
section = text[start:end]
old = """  match catch_panic(() => fold_expr(icx, opts.fuel, empty_cache(), e, 0, 0)) {
    Ok(pr) -> {
      let (_, r) = pr
      match r {
        Ok(v) -> Ok(v)
        Err(d) -> Err(closed_reason(d.msg))
      }
    }
    Err(fault) -> Err("panic: " ++ first_line(fault.message))
  }"""
new = """  let (_, r) = fold_expr(icx, opts.fuel, empty_cache(), e, 0, 0)
  match r {
    Ok(v) -> Ok(v)
    Err(d) -> Err(closed_reason(d.msg))
  }"""
if section.count(old) != 1:
    raise SystemExit("FAIL: the eval_closed barrier anchor drifted; update this mutation")
path.write_text(text[:start] + section.replace(old, new) + text[end:])
PY

if "$dawn" test "$mutant" > "$work/mutant.out" 2>&1; then
  fail "selfhost without the eval_closed barrier stayed green"
fi
# the test's FAIL line, then the panic it let through, indented under it
python3 - "$work/mutant.out" "$test_name" "$panic_text" <<'PY'
import sys
from pathlib import Path

out, name, panic = sys.argv[1:]
lines = Path(out).read_text().splitlines()
hits = [i for i, l in enumerate(lines) if l == "FAIL  ir/interp_test :: " + name]
if len(hits) != 1:
    sys.stdout.write("\n".join(l for l in lines if l.startswith("FAIL")) + "\n")
    raise SystemExit("FAIL: the mutant missed its intended selfhost test")
at = hits[0]
below = []
for line in lines[at + 1:]:
    if not line.startswith("      "):
        break
    below.append(line.strip())
if not any(panic in line for line in below):
    raise SystemExit(f"FAIL: the test failed, but not on the escaped panic: {below!r}")
failed = [l for l in lines if l.startswith("FAIL  ")]
if len(failed) != 1:
    raise SystemExit(f"FAIL: the mutant reddened more than its own test: {failed!r}")
PY
echo "PASS  without catch_panic, a lowering panic escapes eval_closed"

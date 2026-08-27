#!/usr/bin/env bash
# `selfhost/builtins.dawn` is the builtin table as declarations. This holds it
# level with the table itself, in both directions, on every push.
#
#   ./scripts/builtin-decl-contract/run.sh
#
# Three steps, in this order:
#
#   1. the checker's own judgements are made to fail, against a synthetic
#      table (`--self-test`). A judgement whose red has never been observed is
#      a judgement nobody can rely on.
#   2. the real comparison: dump the table out of the compiler and compare.
#   3. nine mutants (matrix.txt), each a perturbation of the real inputs held
#      in memory. The self-test proves the judgements *can* be red; these
#      prove they are red about this repository, which a synthetic table
#      cannot show -- a checker reading the wrong file passes every synthetic
#      case. Nothing is written: the working tree never holds a mutant.
#
# The dump is an ordinary Dawn project (`dump/`) with a path dependency on
# `selfhost`. The builtin table is a Dawn value in a Dawn module, so reading it
# needs no compiler API and no subcommand of its own.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/builtin-decl-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
case "$dawn" in /*) ;; *) dawn="$root/$dawn" ;; esac
work=$(mktemp -d "${TMPDIR:-/tmp}/builtin-decl-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The executable mutant list, in run order. It lives in check.py, which is what
# runs them; this reads it back and holds it equal to matrix.txt in both
# directions, so a mutant added to one and not the other is named here rather
# than silently dropped.
python3 - "$here/check.py" > "$work/matrix.executable" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("check", sys.argv[1])
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
for name, _, _ in check.MUTANTS:
    print(name)
PY
grep -v '^#' "$here/matrix.txt" | grep -v '^$' > "$work/matrix.recorded" || true
cmp -s "$work/matrix.executable" "$work/matrix.recorded" || {
  diff -u "$work/matrix.recorded" "$work/matrix.executable" >&2 || true
  fail "matrix.txt and check.py's executable mutant list disagree"
}

python3 "$here/check.py" --self-test

"$dawn" --version > /dev/null
"$dawn" run "$here/dump" > "$work/dump.tsv"

python3 "$here/check.py" --dump "$work/dump.tsv" --root "$root"
python3 "$here/check.py" --dump "$work/dump.tsv" --root "$root" --mutants

echo "PASS  the builtin mirror and the builtin table say the same thing"

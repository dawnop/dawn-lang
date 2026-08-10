#!/usr/bin/env bash
# The two halves of SYN-05 that the corpora cannot see.
#
#   lsp  The pipe writes ordinary calls, so the editor has to map their typed
#        children like any other call's. Two shapes did not: a module-qualified
#        call (`m.f(a)`) whose typed argument list has no receiver in it, and a
#        qualified construction (`m.C(a)`), which is an XCtor rather than an
#        XApply. Both walked parse-only, and hover inside them answered with the
#        *enclosing call's* type -- a wrong answer, not a missing one, which is
#        why nobody noticed. The probe hovers a lambda and a constructor name in
#        both the written and the piped spelling; before the fix all four say
#        `List[Int]` / `Box`.
#
#   fmt  The formatter is lexical and was expected not to move. "Expected" is
#        not a check: the pipe now admits shapes it never saw, and a formatter
#        that reflows one of them differently on the second pass would corrupt
#        source on the second save. Idempotence over the general-pipe corpus is
#        the assertion that expectation was standing in for.
#
# Both legs are on the accept corpus so the three files stay in step.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
DAWN=${DAWN_BIN:-"$ROOT/bin/dawn"}
case "$DAWN" in /*) ;; *) DAWN="$ROOT/$DAWN" ;; esac

WORK=$(mktemp -d "${TMPDIR:-/tmp}/pipe-contract.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

fail=0
check() { # label, expected, actual
  if [ "$2" = "$3" ]; then
    echo "OK   $1"
  else
    echo "FAIL $1" >&2
    echo "     want: $2" >&2
    echo "     got:  $3" >&2
    fail=1
  fi
}

# ---- lsp: typed children under a qualified call and a qualified construction

mkdir -p "$WORK/proj/src"
cat > "$WORK/proj/dawn.toml" <<'EOF'
schema = 1
name = "pipe_contract"
EOF
cat > "$WORK/proj/src/val.dawn" <<'EOF'
pub type Box = One(v: Int)
EOF
# Every hovered node below is a *child* of a call whose callee is dotted. The
# lambda is unannotated on purpose: its type exists only in the typed tree, so
# an unmapped walk cannot invent it, and the constructor's signature is offered
# at the name's own span by one code path and no other.
cat > "$WORK/proj/src/main.dawn" <<'EOF'
use std/list
use val.{Box}
use val as v

pub fn main() -> Unit !io = {
  let xs = [1, 2, 3]
  let written = list.map(xs, y => y + 1)
  let piped = xs |> list.map(z => z + 1)
  let wbox = v.One(7)
  let pbox = 7 |> v.One()
  println("${len(written)} ${len(piped)} ${unbox(wbox)} ${unbox(pbox)}")
}

fn unbox(b: Box) -> Int =
  match b {
    v.One(n) -> n
  }
EOF

"$DAWN" run "$WORK/proj" > "$WORK/run.out"
check "the probe project runs" "3 3 7 7" "$(cat "$WORK/run.out")"

python3 "$ROOT/scripts/pipe-contract/hover.py" "$DAWN" "$WORK/proj" \
  "$WORK/proj/src/main.dawn" \
  'qualified call, written=y => y + 1' \
  'qualified call, piped=z => z + 1' \
  'qualified ctor, written=v.One(7)+2' \
  'qualified ctor, piped=v.One()+2' \
  'qualified ctor argument=One(7)+4' > "$WORK/hover.out"

want_hover() { # label, type text
  check "hover: $1" "$1	\`\`\`dawn $2 \`\`\`" "$(grep -F "$1	" "$WORK/hover.out")"
}
want_hover "qualified call, written" "fn(Int) -> Int"
want_hover "qualified call, piped" "fn(Int) -> Int"
want_hover "qualified ctor, written" "One(v: Int): Box"
want_hover "qualified ctor, piped" "One(v: Int): Box"
want_hover "qualified ctor argument" "Int"

# ---- fmt: the general-pipe corpus is a formatter fixpoint

CORPUS="$ROOT/scripts/grammar-corpus/accept/pipe_general.dawn"
cp "$CORPUS" "$WORK/once.dawn"
"$DAWN" fmt "$WORK/once.dawn" > /dev/null
cp "$WORK/once.dawn" "$WORK/twice.dawn"
"$DAWN" fmt "$WORK/twice.dawn" > /dev/null
if cmp -s "$WORK/once.dawn" "$WORK/twice.dawn"; then
  echo "OK   fmt is idempotent over the general-pipe forms"
else
  echo "FAIL fmt is not idempotent over the general-pipe forms" >&2
  diff -u "$WORK/once.dawn" "$WORK/twice.dawn" >&2 || true
  fail=1
fi
if "$DAWN" fmt --check "$WORK/once.dawn" > /dev/null; then
  echo "OK   the formatted general-pipe corpus satisfies --check"
else
  echo "FAIL the formatted general-pipe corpus does not satisfy --check" >&2
  fail=1
fi

exit "$fail"

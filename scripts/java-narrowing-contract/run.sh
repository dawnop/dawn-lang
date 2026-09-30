#!/usr/bin/env bash
# Java Object may widen to Object, but it may narrow only through checked cast.
#
# The public legs pin checker rejection and the interop paths that remain. Two
# source mutants then compile and execute private selfhost copies: restoring
# the checker exception fails its unit test, while restoring an unreachable
# backend CHECKCAST is caught by the structural half of this contract.
#
#   ./scripts/java-narrowing-contract/run.sh
#
# `rejected.expected` is one `D` line: the diagnostic the checker must produce,
# span and candidate list included. No `--record`; when the wording moves on
# purpose, copy the line the failure prints into the file.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
here="$root/scripts/java-narrowing-contract"
work=$(mktemp -d "${TMPDIR:-/tmp}/java-narrowing-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

"$dawn" __check "$here/rejected.dawn" > "$work/rejected.raw"
grep '^D' "$work/rejected.raw" |
  sed 's|\t[^\t]*/\([^\t/]*\)\t|\t\1\t|' > "$work/rejected.got" || true
diff -u "$here/rejected.expected" "$work/rejected.got" ||
  fail "Object-to-reference rejection changed"

accepted=$("$dawn" run "$here/accepted.dawn")
[ "$accepted" = "ok" ] || fail "accepted interop paths printed: $accepted"

check_backend_shape() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
start = text.index("pub fn adapt_java_arg(")
end = text.index("\n}\n\n## `new C[n]`", start) + 2
body = text[start:end]
forbidden = ("TyJava", "OP_CHECKCAST", "visitTypeInsn", "is_assignable", "internal_of")
found = [token for token in forbidden if token in body]
if found:
    raise SystemExit("hidden reference cast in adapt_java_arg: " + ", ".join(found))
PY
}

check_backend_shape "$root/selfhost/src/jvm/help.dawn"
echo "PASS  Object narrowing is rejected; checked cast and safe bridges run"

# The anchors live in mutate.py, one registered mutation per private copy, so
# mutation-anchor-preflight.py proves each one matches exactly once before any
# build, not only when this contract runs.
mutate() { # mutation, selfhost-copy
  python3 "$here/mutate.py" "$1" "$2"
}

ln -s "$root/packages" "$work/packages"
cp -R "$root/compiler-plan" "$work/compiler-plan"

checker_mutant="$work/checker-mutant"
cp -R "$root/selfhost" "$checker_mutant"
mutate object-scorer-exception "$checker_mutant"
if "$dawn" test "$checker_mutant" > "$work/checker-mutant.out" 2>&1; then
  fail "restored Object scorer exception stayed green"
fi
grep -Fq 'Java Object arguments require checked narrowing' "$work/checker-mutant.out" || {
  cat "$work/checker-mutant.out" >&2
  fail "checker mutant missed its owning test"
}
echo "PASS  restored Object scorer exception turns its unit test red"

backend_mutant="$work/backend-mutant"
cp -R "$root/selfhost" "$backend_mutant"
mutate backend-checkcast "$backend_mutant"
if ! "$dawn" test "$backend_mutant" > "$work/backend-mutant.out" 2>&1; then
  cat "$work/backend-mutant.out" >&2
  fail "backend CHECKCAST mutant did not compile and run"
fi
if check_backend_shape "$backend_mutant/src/jvm/help.dawn" > "$work/backend-shape.out" 2>&1; then
  fail "backend CHECKCAST mutant passed the structural gate"
fi
grep -Fq 'hidden reference cast in adapt_java_arg' "$work/backend-shape.out" || {
  cat "$work/backend-shape.out" >&2
  fail "backend mutant failed for the wrong structural reason"
}
echo "PASS  compilable backend CHECKCAST mutant turns the structure gate red"

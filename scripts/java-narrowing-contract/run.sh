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

mutate_checker() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '''          } else if cx.jsig.is_assignable(p, fq) {
            Some(1)
          } else {
            None
          }'''
new = '''          } else if cx.jsig.is_assignable(p, fq) {
            Some(1)
          } else if fq == "java.lang.Object" && not is_prim_name(p) {
            Some(1)
          } else {
            None
          }'''
if text.count(old) != 1:
    raise SystemExit("checker mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
}

mutate_backend() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

def replace_once(old: str, new: str) -> None:
    global text
    if text.count(old) != 1:
        raise SystemExit(f"backend mutation anchor drifted: {old!r}")
    text = text.replace(old, new)

replace_once(
    "use check/types.{Ty, TyInt, TyFloat, TyBool, TyString, TyBytes}",
    "use check/types.{Ty, TyInt, TyFloat, TyBool, TyString, TyBytes, TyJava}",
)
replace_once(
    "OP_ANEWARRAY, OP_ASTORE, OP_ATHROW, OP_BIPUSH, OP_D2F",
    "OP_ANEWARRAY, OP_ASTORE, OP_ATHROW, OP_BIPUSH, OP_CHECKCAST, OP_D2F",
)
replace_once(
    '''  } else if dawn_ty == TyFloat && param_cls == "float" {
    m.visitInsn(OP_D2F)
  }
  ()''',
    '''  } else if dawn_ty == TyFloat && param_cls == "float" {
    m.visitInsn(OP_D2F)
  } else {
    match dawn_ty {
      TyJava(fqcn, _) ->
        if fqcn == "java.lang.Object" && not is_prim_name(param_cls) {
          m.visitTypeInsn(OP_CHECKCAST, internal_of(param_cls))
        }
      _ -> ()
    }
  }
  ()''',
)
path.write_text(text)
PY
}

ln -s "$root/packages" "$work/packages"
cp -R "$root/compiler-plan" "$work/compiler-plan"

checker_mutant="$work/checker-mutant"
cp -R "$root/selfhost" "$checker_mutant"
mutate_checker "$checker_mutant/src/check/checker.dawn"
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
mutate_backend "$backend_mutant/src/jvm/help.dawn"
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

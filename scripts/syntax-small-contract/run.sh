#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
fixture="$root/scripts/grammar-corpus/reject/declaration_recovery_opaque.dawn"
return_fixture="$root/scripts/grammar-corpus/accept/bare_return_delimiters.dawn"
builtin_hint_fixture="$root/scripts/checker-corpus/cases/builtin_alias_hint.dawn"
builtin_hint_expected="$root/scripts/checker-corpus/cases/builtin_alias_hint.expected"
builtin_boundary_fixture="$root/scripts/checker-corpus/cases/builtin_alias_boundary.dawn"
builtin_boundary_expected="$root/scripts/checker-corpus/cases/builtin_alias_boundary.expected"
work=$(mktemp -d "${TMPDIR:-/tmp}/syntax-small-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

capture_checker_cli() {
  local fixture_path=$1
  local output_path=$2
  "$dawn" __check "$fixture_path" | grep '^D' |
    sed 's|\t[^\t]*/\([^\t/]*\)\t|\t\1\t|' > "$output_path"
}

capture_checker_jar() {
  local jar_path=$1
  local fixture_path=$2
  local output_path=$3
  java -Xss512m -Xmx2g -jar "$jar_path" __check "$fixture_path" | grep '^D' |
    sed 's|\t[^\t]*/\([^\t/]*\)\t|\t\1\t|' > "$output_path"
}

assert_parser_neutral() {
  local output_path=$1
  if grep -q '^!' "$output_path"; then
    echo 'ASSERT: bare TYPEIDENT builtin aliases must stay parser-neutral' >&2
    return 1
  fi
}

assert_checker_exact() {
  local actual_path=$1
  local expected_path=$2
  local message=$3
  if ! cmp -s "$expected_path" "$actual_path"; then
    echo "ASSERT: $message" >&2
    return 1
  fi
}

assertion_failed_exactly() {
  local actual_path=$1
  local message=$2
  local expected_path=$3
  printf 'ASSERT: %s\n' "$message" > "$expected_path"
  cmp -s "$expected_path" "$actual_path"
}

"$dawn" --version > /dev/null
"$dawn" __parse "$fixture" > "$work/fixture.out"
diagnostic_count=$(grep -c '^!' "$work/fixture.out" || true)
if [ "$diagnostic_count" -ne 1 ]; then
  cat "$work/fixture.out" >&2
  fail "opaque recovery fixture reported $diagnostic_count diagnostics instead of one"
fi
diagnostic=$(grep '^!' "$work/fixture.out" || true)
case "$diagnostic" in
  *'expected a parameter name, found `=`'*) ;;
  *)
    cat "$work/fixture.out" >&2
    fail "opaque recovery lost the original declaration diagnostic"
    ;;
esac
grep -Fq 'Type UserId tparams=_ record=false alias=true opaque=true' "$work/fixture.out" || {
  cat "$work/fixture.out" >&2
  fail "opaque recovery did not retain UserId as an opaque declaration"
}
echo "PASS  contextual opaque recovery retains one diagnostic and one declaration"

"$dawn" __parse "$return_fixture" > "$work/return-fixture.out"
if grep -q '^!' "$work/return-fixture.out"; then
  cat "$work/return-fixture.out" >&2
  fail "bare return delimiter fixture did not parse"
fi
return_count=$(grep -c 'Return has=false' "$work/return-fixture.out" || true)
if [ "$return_count" -ne 5 ]; then
  cat "$work/return-fixture.out" >&2
  fail "bare return delimiter fixture retained $return_count bare returns instead of five"
fi

printf '%s\n' 'fn wrong() -> Int = [return]' > "$work/return_type.dawn"
if "$dawn" check "$work/return_type.dawn" > "$work/return-type.out" 2>&1; then
  fail "bare return escaped the function return-type check"
fi
grep -Fq '`return` type mismatch: this function returns Int, got Unit' \
  "$work/return-type.out" || {
    cat "$work/return-type.out" >&2
    fail "bare return failed outside its checker-owned return-type rule"
  }
echo "PASS  bare return delimiters parse and remain checker-constrained"

"$dawn" __parse "$builtin_hint_fixture" > "$work/builtin-parser.out"
assert_parser_neutral "$work/builtin-parser.out" || {
  cat "$work/builtin-parser.out" >&2
  fail "builtin alias fixture escaped parser ownership"
}
capture_checker_cli "$builtin_hint_fixture" "$work/builtin-hint.out"
assert_checker_exact "$work/builtin-hint.out" "$builtin_hint_expected" \
  "all compiler-owned nongeneric aliases must share the checker hint" || {
    diff -u "$builtin_hint_expected" "$work/builtin-hint.out" >&2 || true
    fail "builtin alias hint fixture changed"
  }
capture_checker_cli "$builtin_boundary_fixture" "$work/builtin-boundary.out"
assert_checker_exact "$work/builtin-boundary.out" "$builtin_boundary_expected" \
  "only singleton nullary builtin constructors get the alias hint" || {
    diff -u "$builtin_boundary_expected" "$work/builtin-boundary.out" >&2 || true
    fail "builtin alias boundary fixture changed"
  }
echo "PASS  builtin alias ownership, uniform hints, and nominal boundaries"

mutant="$work/drop-opaque-anchor"
mkdir -p "$mutant"
cp -R "$root/selfhost" "$mutant/selfhost"
cp -R "$root/compiler-plan" "$mutant/compiler-plan"
ln -s "$root/packages" "$mutant/packages"

python3 - "$mutant/selfhost/src/front/parser.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """    Some(head) -> match head.kind {
      HBadOpaque -> false
      _ -> true
    }
"""
new = """    Some(head) -> match head.kind {
      HBadOpaque -> false
      HOpaqueType -> false
      _ -> true
    }
"""
if text.count(old) != 1:
    raise SystemExit("drop-opaque-anchor mutation anchor drifted")
path.write_text(text.replace(old, new))
PY

if ! "$dawn" build "$mutant/selfhost" -o "$mutant/compiler.jar" \
    > "$mutant/build.out" 2>&1; then
  cat "$mutant/build.out" >&2
  fail "drop-opaque-anchor mutant did not compile"
fi

if "$dawn" test "$mutant/selfhost" > "$mutant/test.out" 2>&1; then
  fail "drop-opaque-anchor mutant stayed green"
fi
if ! grep -Fxq 'FAIL  front/parser_test :: declaration recovery anchors at contextual opaque type' \
    "$mutant/test.out"; then
  cat "$mutant/test.out" >&2
  fail "drop-opaque-anchor mutant missed its owning recovery test"
fi
echo "PASS  drop-opaque-anchor compiles, then turns the owning recovery test red"

return_mutant="$work/drop-rbracket-return-boundary"
mkdir -p "$return_mutant"
cp -R "$root/selfhost" "$return_mutant/selfhost"
cp -R "$root/compiler-plan" "$return_mutant/compiler-plan"
ln -s "$root/packages" "$return_mutant/packages"

python3 - "$return_mutant/selfhost/src/front/parser.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "  k == NEWLINE || k == RBRACE || k == RPAREN || k == RBRACKET || k == COMMA || k == EOF\n"
new = "  k == NEWLINE || k == RBRACE || k == RPAREN || k == COMMA || k == EOF\n"
if text.count(old) != 1:
    raise SystemExit("drop-rbracket-return-boundary mutation anchor drifted")
path.write_text(text.replace(old, new))
PY

if ! "$dawn" build "$return_mutant/selfhost" -o "$return_mutant/compiler.jar" \
    > "$return_mutant/build.out" 2>&1; then
  cat "$return_mutant/build.out" >&2
  fail "drop-rbracket-return-boundary mutant did not compile"
fi

if "$dawn" test "$return_mutant/selfhost" > "$return_mutant/test.out" 2>&1; then
  fail "drop-rbracket-return-boundary mutant stayed green"
fi
if ! grep -Fxq 'FAIL  front/parser_test :: bare return stops at every delimiter boundary' \
    "$return_mutant/test.out"; then
  cat "$return_mutant/test.out" >&2
  fail "drop-rbracket-return-boundary mutant missed its owning parser test"
fi
echo "PASS  drop-rbracket-return-boundary compiles, then turns its owning parser test red"

parser_mutant="$work/restore-parser-builtin-branch"
mkdir -p "$parser_mutant"
cp -R "$root/selfhost" "$parser_mutant/selfhost"
cp -R "$root/compiler-plan" "$parser_mutant/compiler-plan"
ln -s "$root/packages" "$parser_mutant/packages"

python3 - "$parser_mutant/selfhost/src/front/parser.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
type_decl = "fn type_decl(p: P, st: St, is_pub: Bool) -> PR[Decl] = {\n"
builtin_table = """fn is_builtin_scalar(name: String) -> Bool =
  match name {
    "Int" | "Float" | "Bool" | "String" | "Unit" -> true
    _ -> false
  }

"""
old = """  let aliasish = at_kind(p, st4, FN) || at_kind(p, st4, LPAREN) ||
    (at_kind(p, st4, TYPEIDENT) && kind_ahead(p, st4, 1) == LBRACKET)
"""
new = """  let builtin_scalar = at_kind(p, st4, TYPEIDENT) && is_builtin_scalar(cur(p, st4).text) &&
    kind_ahead(p, st4, 1) != LPAREN
  let aliasish = at_kind(p, st4, FN) || at_kind(p, st4, LPAREN) ||
    (at_kind(p, st4, TYPEIDENT) && kind_ahead(p, st4, 1) == LBRACKET) || builtin_scalar
"""
if text.count(type_decl) != 1 or text.count(old) != 1:
    raise SystemExit("restore-parser-builtin-branch mutation anchor drifted")
path.write_text(text.replace(type_decl, builtin_table + type_decl).replace(old, new))
PY

if ! "$dawn" build "$parser_mutant/selfhost" -o "$parser_mutant/compiler.jar" \
    > "$parser_mutant/build.out" 2>&1; then
  cat "$parser_mutant/build.out" >&2
  fail "restore-parser-builtin-branch mutant did not compile"
fi

java -Xss512m -Xmx2g -jar "$parser_mutant/compiler.jar" __parse "$builtin_hint_fixture" \
  > "$parser_mutant/parser.out"
if assert_parser_neutral "$parser_mutant/parser.out" \
    > "$parser_mutant/assert.out" 2>&1; then
  fail "restore-parser-builtin-branch mutant stayed green"
fi
if ! assertion_failed_exactly "$parser_mutant/assert.out" \
    "bare TYPEIDENT builtin aliases must stay parser-neutral" \
    "$parser_mutant/assert.expected"; then
  cat "$parser_mutant/assert.out" >&2
  fail "restore-parser-builtin-branch mutant missed its owning assertion"
fi
capture_checker_jar "$parser_mutant/compiler.jar" "$builtin_boundary_fixture" \
  "$parser_mutant/boundary.out"
assert_checker_exact "$parser_mutant/boundary.out" "$builtin_boundary_expected" \
  "only singleton nullary builtin constructors get the alias hint" ||
  fail "restore-parser-builtin-branch mutant crossed the checker boundary assertion"
echo "PASS  restore-parser-builtin-branch compiles, then turns only parser ownership red"

narrow_mutant="$work/narrow-checker-builtin-hint"
mkdir -p "$narrow_mutant"
cp -R "$root/selfhost" "$narrow_mutant/selfhost"
cp -R "$root/compiler-plan" "$narrow_mutant/compiler-plan"
ln -s "$root/packages" "$narrow_mutant/packages"

python3 - "$narrow_mutant/selfhost/src/check/passes.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "        let builtin_alias = len(d.ctors) == 1 && len(c.fields) == 0\n"
new = """        let builtin_alias = len(d.ctors) == 1 && len(c.fields) == 0 &&
          c.name != "Char" && c.name != "Bytes"
"""
if text.count(old) != 1:
    raise SystemExit("narrow-checker-builtin-hint mutation anchor drifted")
path.write_text(text.replace(old, new))
PY

if ! "$dawn" build "$narrow_mutant/selfhost" -o "$narrow_mutant/compiler.jar" \
    > "$narrow_mutant/build.out" 2>&1; then
  cat "$narrow_mutant/build.out" >&2
  fail "narrow-checker-builtin-hint mutant did not compile"
fi

capture_checker_jar "$narrow_mutant/compiler.jar" "$builtin_boundary_fixture" \
  "$narrow_mutant/boundary.out"
assert_checker_exact "$narrow_mutant/boundary.out" "$builtin_boundary_expected" \
  "only singleton nullary builtin constructors get the alias hint" ||
  fail "narrow-checker-builtin-hint mutant crossed the boundary assertion"
capture_checker_jar "$narrow_mutant/compiler.jar" "$builtin_hint_fixture" \
  "$narrow_mutant/hint.out"
if assert_checker_exact "$narrow_mutant/hint.out" "$builtin_hint_expected" \
    "all compiler-owned nongeneric aliases must share the checker hint" \
    > "$narrow_mutant/assert.out" 2>&1; then
  fail "narrow-checker-builtin-hint mutant stayed green"
fi
if ! assertion_failed_exactly "$narrow_mutant/assert.out" \
    "all compiler-owned nongeneric aliases must share the checker hint" \
    "$narrow_mutant/assert.expected"; then
  cat "$narrow_mutant/assert.out" >&2
  fail "narrow-checker-builtin-hint mutant missed its owning assertion"
fi
echo "PASS  narrow-checker-builtin-hint compiles, then turns only uniform hints red"

boundary_mutant="$work/drop-builtin-alias-boundary"
mkdir -p "$boundary_mutant"
cp -R "$root/selfhost" "$boundary_mutant/selfhost"
cp -R "$root/compiler-plan" "$boundary_mutant/compiler-plan"
ln -s "$root/packages" "$boundary_mutant/packages"

python3 - "$boundary_mutant/selfhost/src/check/passes.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "        let builtin_alias = len(d.ctors) == 1 && len(c.fields) == 0\n"
new = "        let builtin_alias = true\n"
if text.count(old) != 1:
    raise SystemExit("drop-builtin-alias-boundary mutation anchor drifted")
path.write_text(text.replace(old, new))
PY

if ! "$dawn" build "$boundary_mutant/selfhost" -o "$boundary_mutant/compiler.jar" \
    > "$boundary_mutant/build.out" 2>&1; then
  cat "$boundary_mutant/build.out" >&2
  fail "drop-builtin-alias-boundary mutant did not compile"
fi

capture_checker_jar "$boundary_mutant/compiler.jar" "$builtin_hint_fixture" \
  "$boundary_mutant/hint.out"
assert_checker_exact "$boundary_mutant/hint.out" "$builtin_hint_expected" \
  "all compiler-owned nongeneric aliases must share the checker hint" ||
  fail "drop-builtin-alias-boundary mutant crossed the uniform-hint assertion"
capture_checker_jar "$boundary_mutant/compiler.jar" "$builtin_boundary_fixture" \
  "$boundary_mutant/boundary.out"
if assert_checker_exact "$boundary_mutant/boundary.out" "$builtin_boundary_expected" \
    "only singleton nullary builtin constructors get the alias hint" \
    > "$boundary_mutant/assert.out" 2>&1; then
  fail "drop-builtin-alias-boundary mutant stayed green"
fi
if ! assertion_failed_exactly "$boundary_mutant/assert.out" \
    "only singleton nullary builtin constructors get the alias hint" \
    "$boundary_mutant/assert.expected"; then
  cat "$boundary_mutant/assert.out" >&2
  fail "drop-builtin-alias-boundary mutant missed its owning assertion"
fi
echo "PASS  drop-builtin-alias-boundary compiles, then turns only nominal boundaries red"

"$root/scripts/pattern-or-contract/run.sh"
"$root/scripts/for-pattern-contract/run.sh"

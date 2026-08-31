#!/usr/bin/env bash
# Parser ownership, checker-owned builtin alias hints, and the nominal
# singleton/nullary boundary, each held by a compiling production mutant.
#
#   ./scripts/syntax-small-contract/run.sh                      # everything
#   ./scripts/syntax-small-contract/run.sh --shard 2/3          # fixtures + a third
#   ./scripts/syntax-small-contract/run.sh --only <mutant>      # one mutant, no children
#
# This runner also drives the pattern-or and for-pattern matrices, forwarding
# its own --shard so one CI job carries one slice of the whole syntax family.
# Every shard runs every fixture assertion of all three harnesses (seconds
# each), so no shard is a partial verdict about what the contracts assert;
# only the compiling mutants -- one whole compiler build each -- are divided
# round-robin. Each shard records what it ran, and
# scripts/mutant-coverage/check.py holds the union to the matrices.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
fixture="$root/scripts/grammar-corpus/reject/declaration_recovery_opaque.dawn"
return_fixture="$root/scripts/grammar-corpus/accept/bare_return_delimiters.dawn"
builtin_hint_fixture="$root/scripts/checker-corpus/cases/builtin_alias_hint.dawn"
builtin_hint_expected="$root/scripts/checker-corpus/cases/builtin_alias_hint.expected"
builtin_boundary_fixture="$root/scripts/checker-corpus/cases/builtin_alias_boundary.dawn"
builtin_boundary_expected="$root/scripts/checker-corpus/cases/builtin_alias_boundary.expected"
matrix="$root/scripts/syntax-small-contract/matrix.txt"
work=$(mktemp -d "${TMPDIR:-/tmp}/syntax-small-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
only=
if [ "${#shard_rest[@]}" -gt 0 ]; then
  case "${shard_rest[0]}" in
    --only)
      [ "${#shard_rest[@]}" -eq 2 ] || { echo "--only needs a mutant name" >&2; exit 2; }
      only=${shard_rest[1]}
      ;;
    *)
      echo "syntax-small-contract: unknown argument(s): ${shard_rest[*]}" >&2
      exit 2
      ;;
  esac
fi

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The executable mutant list, in run order. matrix.txt is the persistent
# record the coverage checker reads; the two are held equal in both
# directions below, so a mutant added to one place cannot go missing from
# the other.
mutants=(
  drop-opaque-anchor
  drop-rbracket-return-boundary
  restore-parser-builtin-branch
  narrow-checker-builtin-hint
  drop-builtin-alias-boundary
)

printf '%s\n' "${mutants[@]}" > "$work/matrix.executable"
grep -v '^#' "$matrix" | grep -v '^$' > "$work/matrix.recorded" || true
cmp -s "$work/matrix.executable" "$work/matrix.recorded" || {
  diff -u "$work/matrix.recorded" "$work/matrix.executable" >&2 || true
  fail "matrix.txt and the runner's executable mutant list disagree"
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

new_syntax_mutant() {
  mdir="$work/$1"
  mkdir -p "$mdir"
  cp -R "$root/selfhost" "$mdir/selfhost"
  cp -R "$root/compiler-plan" "$mdir/compiler-plan"
  ln -s "$root/packages" "$mdir/packages"
}

build_syntax_mutant() {
  if ! "$dawn" build "$mdir/selfhost" -o "$mdir/compiler.jar" \
      > "$mdir/build.out" 2>&1; then
    cat "$mdir/build.out" >&2
    fail "$1 mutant did not compile"
  fi
}

expect_owning_test_red() {
  local name=$1 owning_test=$2
  if "$dawn" test "$mdir/selfhost" > "$mdir/test.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  if ! grep -Fxq "$owning_test" "$mdir/test.out"; then
    cat "$mdir/test.out" >&2
    fail "$name mutant missed its owning test"
  fi
}

run_syntax_mutant() {
  new_syntax_mutant "$1"
  case "$1" in
    drop-opaque-anchor)
      python3 - "$mdir/selfhost/src/front/parser.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """    Some(head) -> match head.kind {
      HBadOpaque -> false
      HBadCtl -> false
      _ -> true
    }
"""
new = """    Some(head) -> match head.kind {
      HBadOpaque -> false
      HBadCtl -> false
      HOpaqueType -> false
      _ -> true
    }
"""
if text.count(old) != 1:
    raise SystemExit("drop-opaque-anchor mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
      build_syntax_mutant "$1"
      expect_owning_test_red "$1" \
        'FAIL  front/parser_test :: declaration recovery anchors at contextual opaque type'
      echo "PASS  drop-opaque-anchor compiles, then turns the owning recovery test red"
      ;;

    drop-rbracket-return-boundary)
      python3 - "$mdir/selfhost/src/front/parser.dawn" <<'PY'
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
      build_syntax_mutant "$1"
      expect_owning_test_red "$1" \
        'FAIL  front/parser_test :: bare return stops at every delimiter boundary'
      echo "PASS  drop-rbracket-return-boundary compiles, then turns its owning parser test red"
      ;;

    restore-parser-builtin-branch)
      python3 - "$mdir/selfhost/src/front/parser.dawn" <<'PY'
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
      build_syntax_mutant "$1"
      java -Xss512m -Xmx2g -jar "$mdir/compiler.jar" __parse "$builtin_hint_fixture" \
        > "$mdir/parser.out"
      if assert_parser_neutral "$mdir/parser.out" \
          > "$mdir/assert.out" 2>&1; then
        fail "restore-parser-builtin-branch mutant stayed green"
      fi
      if ! assertion_failed_exactly "$mdir/assert.out" \
          "bare TYPEIDENT builtin aliases must stay parser-neutral" \
          "$mdir/assert.expected"; then
        cat "$mdir/assert.out" >&2
        fail "restore-parser-builtin-branch mutant missed its owning assertion"
      fi
      capture_checker_jar "$mdir/compiler.jar" "$builtin_boundary_fixture" \
        "$mdir/boundary.out"
      assert_checker_exact "$mdir/boundary.out" "$builtin_boundary_expected" \
        "only singleton nullary builtin constructors get the alias hint" ||
        fail "restore-parser-builtin-branch mutant crossed the checker boundary assertion"
      echo "PASS  restore-parser-builtin-branch compiles, then turns only parser ownership red"
      ;;

    narrow-checker-builtin-hint)
      python3 - "$mdir/selfhost/src/check/passes.dawn" <<'PY'
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
      build_syntax_mutant "$1"
      capture_checker_jar "$mdir/compiler.jar" "$builtin_boundary_fixture" \
        "$mdir/boundary.out"
      assert_checker_exact "$mdir/boundary.out" "$builtin_boundary_expected" \
        "only singleton nullary builtin constructors get the alias hint" ||
        fail "narrow-checker-builtin-hint mutant crossed the boundary assertion"
      capture_checker_jar "$mdir/compiler.jar" "$builtin_hint_fixture" \
        "$mdir/hint.out"
      if assert_checker_exact "$mdir/hint.out" "$builtin_hint_expected" \
          "all compiler-owned nongeneric aliases must share the checker hint" \
          > "$mdir/assert.out" 2>&1; then
        fail "narrow-checker-builtin-hint mutant stayed green"
      fi
      if ! assertion_failed_exactly "$mdir/assert.out" \
          "all compiler-owned nongeneric aliases must share the checker hint" \
          "$mdir/assert.expected"; then
        cat "$mdir/assert.out" >&2
        fail "narrow-checker-builtin-hint mutant missed its owning assertion"
      fi
      echo "PASS  narrow-checker-builtin-hint compiles, then turns only uniform hints red"
      ;;

    drop-builtin-alias-boundary)
      python3 - "$mdir/selfhost/src/check/passes.dawn" <<'PY'
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
      build_syntax_mutant "$1"
      capture_checker_jar "$mdir/compiler.jar" "$builtin_hint_fixture" \
        "$mdir/hint.out"
      assert_checker_exact "$mdir/hint.out" "$builtin_hint_expected" \
        "all compiler-owned nongeneric aliases must share the checker hint" ||
        fail "drop-builtin-alias-boundary mutant crossed the uniform-hint assertion"
      capture_checker_jar "$mdir/compiler.jar" "$builtin_boundary_fixture" \
        "$mdir/boundary.out"
      if assert_checker_exact "$mdir/boundary.out" "$builtin_boundary_expected" \
          "only singleton nullary builtin constructors get the alias hint" \
          > "$mdir/assert.out" 2>&1; then
        fail "drop-builtin-alias-boundary mutant stayed green"
      fi
      if ! assertion_failed_exactly "$mdir/assert.out" \
          "only singleton nullary builtin constructors get the alias hint" \
          "$mdir/assert.expected"; then
        cat "$mdir/assert.out" >&2
        fail "drop-builtin-alias-boundary mutant missed its owning assertion"
      fi
      echo "PASS  drop-builtin-alias-boundary compiles, then turns only nominal boundaries red"
      ;;

    *) fail "no assertion for mutant $1" ;;
  esac
}

if [ -n "$only" ]; then
  found=0
  for name in "${mutants[@]}"; do
    if [ "$name" = "$only" ]; then
      run_syntax_mutant "$name"
      found=1
    fi
  done
  [ "$found" -eq 1 ] || fail "no mutant named $only"
else
  shard_begin syntax-small-contract
  position=0
  for name in "${mutants[@]}"; do
    if ! shard_skips "$position"; then
      shard_record "$name"
      run_syntax_mutant "$name"
    fi
    position=$((position + 1))
  done
  shard_report "${#mutants[@]}"

  "$root/scripts/pattern-or-contract/run.sh" --shard "$shard_index/$shard_total"
  "$root/scripts/for-pattern-contract/run.sh" --shard "$shard_index/$shard_total"
fi

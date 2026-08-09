#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
fixture="$root/scripts/grammar-corpus/reject/declaration_recovery_opaque.dawn"
work=$(mktemp -d "${TMPDIR:-/tmp}/syntax-small-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
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

mutant="$work/drop-opaque-anchor"
mkdir -p "$mutant"
cp -R "$root/selfhost" "$mutant/selfhost"
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

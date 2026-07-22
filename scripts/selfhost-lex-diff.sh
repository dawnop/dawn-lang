#!/usr/bin/env bash
# Golden diff for the self-hosted lexer (P1): lex every .dawn file in the repo
# with both the Kotlin lexer (`dawn __lex`) and the Dawn one (selfhost/), and
# require byte-identical dumps. Extra corpus directories may be passed as
# arguments (e.g. a checkout of dawnop-site/backend-dawn).
set -euo pipefail
cd "$(dirname "$0")/.."

# the Kotlin reference CLI (bin/dawn runs selfhost since M8 phase 3)
DAWN=${DAWN_BIN:-./bin/dawn-kotlin}
OUT=${TMPDIR:-/tmp}/selfhost-lex-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# the whole repo is the corpus: std sources, examples, site, playground,
# selfhost itself, and every golden test file (error goldens included — lex
# errors are values, both lexers must report them identically)
mapfile -t files < <(find compiler/src/main/resources/std compiler/src/test/resources \
  examples site playground selfhost "$@" -name '*.dawn' -type f 2>/dev/null | sort)
echo "corpus: ${#files[@]} files"

"$DAWN" __lex "${files[@]}" > "$OUT/kotlin.dump"

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null
java -jar "$OUT/selfhost.jar" lex "${files[@]}" > "$OUT/dawn.dump"

if diff -u "$OUT/kotlin.dump" "$OUT/dawn.dump" > "$OUT/diff.txt"; then
  echo "OK: token streams are byte-identical"
else
  head -40 "$OUT/diff.txt"
  total=$(grep -c '^[+-]' "$OUT/diff.txt" || true)
  echo "FAIL: dumps differ ($total diff lines; full diff was at $OUT/diff.txt)"
  exit 1
fi

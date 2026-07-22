#!/usr/bin/env bash
# N vs N-1 differential (M8 phase 3) — the main oracle once Kotlin retires:
# the previous release's toolchain and HEAD compile the same corpus and every
# byte difference must be declared. Also the machine enforcement of the seed
# feature discipline: the N-1 jar must be able to compile HEAD selfhost/src.
#
#   corpus     — every in-repo Dawn target emits byte-identically under both
#                compilers; backend-dawn (the production ecosystem corpus) is
#                swept with lex/parse dumps and the formatter, which need no
#                third-party class path
#   declaring  — an intentional output change lands with an `Emit-Change:`
#                line in its commit message; the script scans the commits
#                since the N-1 tag and turns a declared diff into a pass
#
# The N-1 jar downloads from the GitHub release named in
# scripts/seed-release.txt (dawn-selfhost.jar preferred, the Kotlin dawn.jar
# for releases predating the dual publish) and caches under .dawn/seeds/.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=$(tr -d ' \n' < scripts/seed-release.txt)
CACHE=${DAWN_SEED_CACHE:-.dawn/seeds}/$TAG
mkdir -p "$CACHE"
if [ ! -f "$CACHE/seed.jar" ]; then
  base="https://github.com/dawnop/dawn-lang/releases/download/$TAG"
  echo "fetching $TAG seed jar..."
  curl -fsSL -o "$CACHE/seed.jar.tmp" "$base/dawn-selfhost.jar" \
    || curl -fsSL -o "$CACHE/seed.jar.tmp" "$base/dawn.jar"
  mv "$CACHE/seed.jar.tmp" "$CACHE/seed.jar"
fi
PREV=(java -Xss512m -jar "$CACHE/seed.jar")

OUT=${TMPDIR:-/tmp}/selfhost-prev-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# feature discipline: the previous release must compile today's selfhost
"${PREV[@]}" build selfhost -o "$OUT/head-by-prev.jar" > /dev/null
echo "OK   $TAG compiles HEAD selfhost (seed feature discipline)"

# HEAD toolchain (bin/dawn builds it on demand)
./bin/dawn --version > /dev/null
HEAD_BIN=(./bin/dawn)

declared() {
  git log "$TAG..HEAD" --format=%B 2>/dev/null | grep -E '^Emit-Change:' || true
}

fail=0
report_diff() { # target
  local decls
  decls=$(declared)
  if [ -n "$decls" ]; then
    echo "NOTE $1 differs vs $TAG — declared since the tag:"
    echo "$decls" | sed 's/^/       /'
  else
    echo "FAIL $1 differs vs $TAG and no commit since the tag declares it"
    echo "     (declare intentional output changes with an 'Emit-Change:' line)"
    fail=1
  fi
}

for t in site playground packages/web packages/json selfhost examples/calc.dawn; do
  mkdir -p "$OUT/prev/$t" "$OUT/head/$t"
  "${PREV[@]}" __emit "$t" -o "$OUT/prev/$t" > /dev/null
  "${HEAD_BIN[@]}" __emit "$t" -o "$OUT/head/$t" > /dev/null
  if diff -rq "$OUT/prev/$t" "$OUT/head/$t" > /dev/null; then
    echo "OK   emit $t"
  else
    report_diff "emit $t"
  fi
done

# the production ecosystem corpus: front-end dumps + formatter over
# backend-dawn (its java-deps are not on this class path, so no emit)
ECO="$OUT/eco"
if git clone --depth 1 https://github.com/dawnop/dawnop-site "$ECO" > /dev/null 2>&1; then
  files=$(find "$ECO/backend-dawn/src" -name '*.dawn' | sort)
  # shellcheck disable=SC2086
  "${PREV[@]}" __lex $files > "$OUT/eco-lex-prev.txt"
  # shellcheck disable=SC2086
  "${HEAD_BIN[@]}" __lex $files > "$OUT/eco-lex-head.txt"
  diff "$OUT/eco-lex-prev.txt" "$OUT/eco-lex-head.txt" > /dev/null \
    && echo "OK   lex backend-dawn" || report_diff "lex backend-dawn"
  # shellcheck disable=SC2086
  "${PREV[@]}" __parse $files > "$OUT/eco-parse-prev.txt"
  # shellcheck disable=SC2086
  "${HEAD_BIN[@]}" __parse $files > "$OUT/eco-parse-head.txt"
  diff "$OUT/eco-parse-prev.txt" "$OUT/eco-parse-head.txt" > /dev/null \
    && echo "OK   parse backend-dawn" || report_diff "parse backend-dawn"
  cp -r "$ECO/backend-dawn/src" "$OUT/fmt-prev"
  cp -r "$ECO/backend-dawn/src" "$OUT/fmt-head"
  "${PREV[@]}" fmt "$OUT/fmt-prev" > /dev/null
  "${HEAD_BIN[@]}" fmt "$OUT/fmt-head" > /dev/null
  diff -r "$OUT/fmt-prev" "$OUT/fmt-head" > /dev/null \
    && echo "OK   fmt backend-dawn" || report_diff "fmt backend-dawn"
else
  # never let a network hiccup read as coverage
  echo "SKIP backend-dawn corpus (clone failed — no network?)"
fi

[ "$fail" = 0 ] || exit 1
echo "OK: HEAD agrees with $TAG on the corpus (undeclared-diff check passed)"

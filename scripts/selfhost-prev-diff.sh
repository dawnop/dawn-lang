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
#   declaring  — an intentional output change lands with an
#                `Emit-Change(<label>):` line in its commit message, one line
#                per check label it moves; the script scans the commits since
#                the N-1 tag and turns a declared diff into a pass. The
#                declaration language, and what it refuses, is documented at
#                the top of scripts/emitchange.sh
#
# The N-1 jar downloads from the GitHub release named in
# scripts/seed-release.txt (dawn-selfhost.jar preferred, the Kotlin dawn.jar
# for releases predating the dual publish) and caches under .dawn/seeds/.
set -euo pipefail
cd "$(dirname "$0")/.."

ROOT=$(pwd)
. scripts/seedjar.sh
TAG=$(tr -d ' \n' < scripts/seed-release.txt)
PREV=(java -Xss512m -jar "$(seed_jar)")
# the seed compiles against the std it released with, not today's std/ --
# the repo std may use prelude machinery one generation ahead of the seed's
# checker (seedjar.sh seed_std_dir). Std-source changes therefore show up in
# the emit diffs below like any other emit change, and are declared the same
# way.
PREV_STD=(--std "$(seed_std_dir)")

OUT=${TMPDIR:-/tmp}/selfhost-prev-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# feature discipline: the previous release must compile today's selfhost
"${PREV[@]}" build selfhost "${PREV_STD[@]}" -o "$OUT/head-by-prev.jar" > /dev/null
echo "OK   $TAG compiles HEAD selfhost (seed feature discipline)"

# HEAD toolchain (bin/dawn builds it on demand)
./bin/dawn --version > /dev/null
HEAD_BIN=(./bin/dawn)

. scripts/emitchange.sh
# read and validate every declaration in the window up front: a gate that
# cannot parse its own exemptions has no business granting them, and finding
# that out before the first diff keeps the message legible
emitchange_load

fail=0
gate() { # label, differs (0 identical, 1 differs)
  emit_gate "$1" "$2" || fail=1
}

for t in site playground packages/web packages/json selfhost examples/calc.dawn; do
  mkdir -p "$OUT/prev/$t" "$OUT/head/$t"
  "${PREV[@]}" __emit "${PREV_STD[@]}" "$t" -o "$OUT/prev/$t" > /dev/null
  "${HEAD_BIN[@]}" __emit "$t" -o "$OUT/head/$t" > /dev/null
  if diff -rq "$OUT/prev/$t" "$OUT/head/$t" > /dev/null; then
    gate "emit $t" 0
  else
    gate "emit $t" 1
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
  if diff "$OUT/eco-lex-prev.txt" "$OUT/eco-lex-head.txt" > /dev/null
  then gate "lex backend-dawn" 0; else gate "lex backend-dawn" 1; fi
  # shellcheck disable=SC2086
  "${PREV[@]}" __parse $files > "$OUT/eco-parse-prev.txt"
  # shellcheck disable=SC2086
  "${HEAD_BIN[@]}" __parse $files > "$OUT/eco-parse-head.txt"
  if diff "$OUT/eco-parse-prev.txt" "$OUT/eco-parse-head.txt" > /dev/null
  then gate "parse backend-dawn" 0; else gate "parse backend-dawn" 1; fi
  cp -r "$ECO/backend-dawn/src" "$OUT/fmt-prev"
  cp -r "$ECO/backend-dawn/src" "$OUT/fmt-head"
  "${PREV[@]}" fmt "$OUT/fmt-prev" > /dev/null
  "${HEAD_BIN[@]}" fmt "$OUT/fmt-head" > /dev/null
  if diff -r "$OUT/fmt-prev" "$OUT/fmt-head" > /dev/null
  then gate "fmt backend-dawn" 0; else gate "fmt backend-dawn" 1; fi
else
  # never let a network hiccup read as coverage
  echo "SKIP backend-dawn corpus (clone failed — no network?)"
fi

[ "$fail" = 0 ] || exit 1
echo "OK: HEAD agrees with $TAG on the corpus (undeclared-diff check passed)"

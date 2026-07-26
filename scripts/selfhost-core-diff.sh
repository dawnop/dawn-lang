#!/usr/bin/env bash
# Core IR golden. docs/native-backend-plan.md 11.4 S0.4.
#
#   ./scripts/selfhost-core-diff.sh            # compare against the golden
#   ./scripts/selfhost-core-diff.sh --record   # regenerate it
#
# ## Why this exists when `__emit` already compares bytes
#
# Change Core and the class files change -- for the parts a shipping backend
# reads. Two parts it does not:
#
#   * `CParam.mode` -- always COwned until Perceus, and ignored by both.
#   * `CSDup` / `CSDrop` -- never emitted until Perceus, and ignored by both.
#
# Those are what Phase 4 will change first. A golden that predates the change
# is what makes "Perceus touched nothing else" checkable.
#
# `CModule.dicts` was the third, and the reason this golden exists: the JVM
# emitter re-derived dictionary class names from the checker's `impl_table`,
# so the table lowering built had one consumer and it was the unfinished C
# backend -- it could be emptied, renamed, or filled with slots naming
# functions that do not exist, and every gate stayed green. It *was* wrong,
# and this diff is where the repair was read. The JVM now builds its
# dictionaries from the table too, so the golden is no longer the only
# witness; it is still the one that shows the table itself.
#
# ## Two goldens, for two questions
#
#   golden/*.core        three programs, in full. Answers *what* changed --
#                        the diff is readable, and dictionary tables are right
#                        at the top of each file.
#   golden/selfhost.sha  one line per module of the compiler itself. Answers
#                        *whether* anything changed across all 52 modules,
#                        without carrying 7MB in the repository. Regenerate
#                        locally to see the content.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

golden="$ROOT/scripts/core-golden"
mode=check
[ "${1:-}" = "--record" ] && mode=record

# Programs chosen for coverage, not size: calc has closures, `?` and list
# work; traits has dictionaries with both slot kinds and a derived Ord; eqhash
# has the Eq/Hash bounds, which are the only construct that forwards a
# dictionary at runtime.
PROGS=(calc traits eqhash)

OUT=${TMPDIR:-/tmp}/core-golden.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

"$ROOT/bin/dawn" --version > /dev/null

for p in "${PROGS[@]}"; do
  mkdir -p "$OUT/$p"
  "$ROOT/bin/dawn" __lower --dump "$OUT/$p" "examples/$p.dawn" > "$OUT/$p.log"
  if ! grep -q ', 0 failed' "$OUT/$p.log"; then
    echo "FAIL: lowering $p left gaps" >&2
    cat "$OUT/$p.log" >&2
    exit 1
  fi
done

# std is lowered once per program. The dumps must agree: std's Core is
# supposed to be a property of std, but `program_tables` unions the *user*
# program's impls into the tables lowering consults, so "independent of the
# target" is an assumption and not a theorem. Check it rather than assume it,
# and store one copy.
first="${PROGS[0]}"
for f in "$OUT/$first"/std.*.core; do
  base=$(basename "$f")
  for p in "${PROGS[@]:1}"; do
    if ! cmp -s "$f" "$OUT/$p/$base"; then
      echo "FAIL: $base lowers differently under $first and $p." >&2
      echo "      std's Core has become target-dependent -- that is the news," >&2
      echo "      not the golden mismatch." >&2
      diff -u "$f" "$OUT/$p/$base" | head -40 >&2
      exit 1
    fi
  done
done

mkdir -p "$OUT/flat"
cp "$OUT/$first"/std.*.core "$OUT/flat/"
for p in "${PROGS[@]}"; do cp "$OUT/$p/$p.core" "$OUT/flat/"; done

# the compiler itself: hashes only
mkdir -p "$OUT/self"
"$ROOT/bin/dawn" __lower --dump "$OUT/self" selfhost > "$OUT/self.log"
if ! grep -q ', 0 failed' "$OUT/self.log"; then
  echo "FAIL: lowering selfhost left gaps" >&2
  cat "$OUT/self.log" >&2
  exit 1
fi
( cd "$OUT/self" && sha256sum ./*.core | sort -k2 ) > "$OUT/selfhost.sha"
# The same hashes over content with every ADT id erased. A module whose exact
# hash moved but whose normalised hash did not changed only in the id embedded
# in a generated symbol name (structeq$Adt307, and its cmp/show siblings): no
# instruction differs. That happens on any edit to an early module, because
# type inference allocates from the same counter ADT declarations do, so adding
# a function to types.dawn shifts every id after it.
#
# Measured 2026-07-26: one added function to types.dawn moves 6 of 52 modules
# and 5 of the 6 are drift. Splitting the counter would rename every generated
# symbol in the language -- a far larger Emit-Change than the noise it removes,
# so the answer is to name the noise rather than to stop making it.
norm_sha() {
  ( cd "$1" && for f in ./*.core; do
      printf '%s  %s\n' "$(sed -E 's/Adt[0-9]+/AdtN/g' "$f" | sha256sum | cut -d' ' -f1)" "$f"
    done | sort -k2 )
}
norm_sha "$OUT/self" > "$OUT/selfhost.norm.sha"

if [ "$mode" = record ]; then
  rm -rf "$golden"
  mkdir -p "$golden"
  cp "$OUT/flat"/*.core "$golden/"
  cp "$OUT/selfhost.sha" "$golden/"
  cp "$OUT/selfhost.norm.sha" "$golden/"
  echo "recorded $(ls "$golden"/*.core | wc -l | tr -d ' ') dumps + $(wc -l < "$golden/selfhost.sha" | tr -d ' ') module hashes"
  exit 0
fi

if [ ! -d "$golden" ]; then
  echo "FAIL: no golden at $golden; run --record" >&2
  exit 1
fi

fail=0
if ! diff -ru "$golden" "$OUT/flat" -x 'selfhost*.sha' > "$OUT/d.txt"; then
  # every changed line, with ADT ids erased: if the two sides then agree, the
  # only thing that moved is an id inside a generated name
  added=$(grep -E '^\+' "$OUT/d.txt" | grep -v '^+++' | sed -E 's/Adt[0-9]+/AdtN/g')
  removed=$(grep -E '^-' "$OUT/d.txt" | grep -v '^---' | sed -E 's/Adt[0-9]+/AdtN/g')
  if [ -n "$added" ] && [ "${added#+}" = "${removed#-}" ]; then
    echo "Core IR changed, but only in ADT ids -- no instruction differs:"
    grep -E '^[+-]' "$OUT/d.txt" | grep -Ev '^(\+\+\+|---)' | head -6
    echo "  (re-record with --record; see the note in this script)"
  else
    echo "Core IR changed:"
    head -80 "$OUT/d.txt"
    n=$(wc -l < "$OUT/d.txt" | tr -d ' ')
    [ "$n" -gt 80 ] && echo "... ($n diff lines total)"
  fi
  fail=1
fi

if ! diff -u "$golden/selfhost.sha" "$OUT/selfhost.sha" > "$OUT/s.txt"; then
  echo
  moved=$(grep -E '^[+-][0-9a-f]{64} ' "$OUT/s.txt" \
    | sed -E 's|^.*  \./(.*)\.core$|\1|' | sort -u)
  # split them: a module whose normalised hash also moved really changed
  drifted=""
  changed=""
  for m in $moved; do
    if [ -f "$golden/selfhost.norm.sha" ] && \
       diff -q <(grep " \./$m\.core\$" "$golden/selfhost.norm.sha") \
               <(grep " \./$m\.core\$" "$OUT/selfhost.norm.sha") > /dev/null 2>&1; then
      drifted="$drifted $m"
    else
      changed="$changed $m"
    fi
  done
  if [ -n "$changed" ]; then
    echo "Core IR of the compiler changed in these modules:"
    for m in $changed; do echo "  $m"; done
  fi
  if [ -n "$drifted" ]; then
    echo "ADT ids shifted in these, with no instruction changed:"
    for m in $drifted; do echo "  $m"; done
  fi
  echo "  (rerun with --dump to see the content: bin/dawn __lower --dump <dir> selfhost)"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "If the change is intended, review the diff above and re-record:"
  echo "  ./scripts/selfhost-core-diff.sh --record"
  exit 1
fi

echo "core golden ok ($(ls "$golden"/*.core | wc -l | tr -d ' ') dumps, $(wc -l < "$golden/selfhost.sha" | tr -d ' ') module hashes)"

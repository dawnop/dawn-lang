#!/usr/bin/env bash
# Core IR golden. docs/native-backend-plan.md 11.4 S0.4.
#
#   ./scripts/selfhost-core-diff.sh            # compare against the golden
#   ./scripts/selfhost-core-diff.sh --record   # regenerate it
#
# ## Why this exists when `__emit` already compares bytes
#
# Change Core and the class files change -- for the parts a shipping backend
# reads. Two parts the JVM emitter does not read:
#
#   * `CParam.mode` -- stamped by the borrowed inference (`c/infer`,
#     docs/perceus-design.md 6.4) and consumed only on the C path.
#   * `CDup` / `CSDrop` -- built by `rc.dawn` on the way into the C backend
#     only, so `__emit`, which is the JVM emitter, walks past both.
#
# Those were what Perceus changed first, and this golden predating it is what
# made "Perceus touched nothing else" checkable.
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
#                        *whether* anything changed across every module there
#                        is -- the file is the count, so it is not restated
#                        here -- without carrying 7MB in the repository.
#                        Regenerate locally to see the content. Exact: it moves
#                        for anything at all, noise included.
#   golden/selfhost.norm.sha
#                        the same, with the compiler's own noise filtered out
#                        (see NORM below). Equality preserves string contents
#                        and generated-name identity relationships.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

golden="$ROOT/scripts/core-golden"
mode=check
[ "${1:-}" = "--record" ] && mode=record

# ## The noise filter -- one definition, both readers
#
# `selfhost.sha` is exact. `selfhost.norm.sha` filters only generated-name IDs.
# Type inference and ADT declarations share a counter, so unrelated additions
# can renumber generated names such as structeq$Adt307. Normalize whole modules
# in both readers, retaining the relationship between definitions and uses.
# Whole-line substitution erased user strings, and erasing every ID to AdtN
# also erased distinctions between generated entities. Strings now stay exact,
# including panic sites; generated-name IDs are consistently alpha-renamed.
# Trait IDs stay exact until Core carries their stable identities.
NORM="$ROOT/scripts/core-normalize.py"
python3 scripts/core-normalize.py --self-test

# Programs chosen for coverage, not size: calc has closures, `?` and list
# work; traits has dictionaries with both slot kinds and a derived Ord; eqhash
# has the Eq/Hash bounds, which are the only construct that forwards a
# dictionary at runtime.
#
# A program is named twice: once by its module name, which is what the dump
# file is called and therefore what the golden is called, and once by the path
# it lives at. The two stopped coinciding when the examples were grouped by
# topic, and the module name is the half that must not move -- renaming a
# golden would make a reshuffle of directories look like a change in Core.
PROGS=(calc traits eqhash)
PROG_PATHS=(examples/projects/calc.dawn examples/traits/traits.dawn examples/traits/eqhash.dawn)

OUT=${TMPDIR:-/tmp}/core-golden.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

"$ROOT/bin/dawn" --version > /dev/null

for i in "${!PROGS[@]}"; do
  p="${PROGS[$i]}"
  mkdir -p "$OUT/$p"
  "$ROOT/bin/dawn" __lower --dump "$OUT/$p" "${PROG_PATHS[$i]}" > "$OUT/$p.log"
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

# the compiler itself: hashes only.
#
# `selfhost` here is relative, and must stay relative: NORM keeps the *path* in
# a baked panic site (see above) and the driver bakes whatever path it was
# handed. Measured 2026-08-04 -- `__lower --dump D /abs/path/to/selfhost` puts
#
#   str "unwrapped None at /home/dawn/workspace/dawn-lang/selfhost/src/main.dawn:164"
#
# in main.core where the relative form puts `selfhost/src/main.dawn:164`, so
# "$ROOT/selfhost" would make this golden differ on every machine and in every
# worktree. (`bin/dawn build` does hand an absolute root, which is why the
# built jar carries the absolute string and two worktrees' class files differ.)
mkdir -p "$OUT/self"
"$ROOT/bin/dawn" __lower --dump "$OUT/self" selfhost > "$OUT/self.log"
if ! grep -q ', 0 failed' "$OUT/self.log"; then
  echo "FAIL: lowering selfhost left gaps" >&2
  cat "$OUT/self.log" >&2
  exit 1
fi
( cd "$OUT/self" && sha256sum ./*.core | sort -k2 ) > "$OUT/selfhost.sha"
# The same hashes with generated-name IDs normalized, but all strings exact.
norm_sha() {
  ( cd "$1" && for f in ./*.core; do
      printf '%s  %s\n' "$(python3 "$NORM" < "$f" | sha256sum | cut -d' ' -f1)" "$f"
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
  # Whole modules are required: normalizing just changed lines can miss a
  # changed reference to a definition on an unchanged line.
  if python3 "$NORM" --equal "$golden" "$OUT/flat"; then
    echo "Core IR changed, but only in generated ADT ids -- no other content differs:"
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
    echo "Only generated ADT ids shifted in these -- no other content changed:"
    for m in $drifted; do echo "  $m"; done
  fi
  echo "  (rerun with --dump to see the content: bin/dawn __lower --dump <dir> selfhost)"
  fail=1
elif ! diff -q "$golden/selfhost.norm.sha" "$OUT/selfhost.norm.sha" > /dev/null; then
  # The normalised hashes are only *read* when the exact ones moved, so a
  # golden recorded under a different NORM sits there unnoticed and answers
  # every future question wrongly -- it would put a really-changed module in
  # the drifted bucket. They can only disagree while the exact ones agree if
  # NORM itself changed, so say exactly that. (Proved red 2026-08-04 by the
  # #143 commit before its re-record: same tree, new filter.)
  echo
  echo "selfhost.norm.sha is stale: the exact hashes all agree, so nothing the"
  echo "  compiler emits moved -- the noise filter (NORM) changed since the"
  echo "  golden was recorded. Re-record."
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "If the change is intended, review the diff above and re-record:"
  echo "  ./scripts/selfhost-core-diff.sh --record"
  exit 1
fi

echo "core golden ok ($(ls "$golden"/*.core | wc -l | tr -d ' ') dumps, $(wc -l < "$golden/selfhost.sha" | tr -d ' ') module hashes)"

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
#                        *whether* anything changed across every module there
#                        is -- the file is the count, so it is not restated
#                        here -- without carrying 7MB in the repository.
#                        Regenerate locally to see the content. Exact: it moves
#                        for anything at all, noise included.
#   golden/selfhost.norm.sha
#                        the same, with the compiler's own noise filtered out
#                        (see NORM below). This is the one that means "not one
#                        instruction differs", so it is the one to trust when a
#                        refactor claims to have moved code without changing it.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

golden="$ROOT/scripts/core-golden"
mode=check
[ "${1:-}" = "--record" ] && mode=record

# ## The noise filter -- one definition, both readers
#
# `selfhost.sha` is exact. `selfhost.norm.sha` is the same hashes over content
# with everything below erased, and it is the one that carries the claim "not
# one instruction differs". Anything added here is a claim that a difference in
# it cannot change what runs, so the list is short and each entry is argued.
# The `*.core` diff below runs the same program over its changed lines, so the
# filter and the verdict it licenses cannot drift apart.
#
#   Adt[0-9]+   The id embedded in a generated symbol name (structeq$Adt307,
#               and its cmp/show siblings). Type inference allocates from the
#               same counter ADT declarations do, so adding a function to
#               types.dawn shifts every id after it. Measured 2026-07-26: one
#               added function to types.dawn moves 6 of 52 modules and 5 of the
#               6 are that. Splitting the counter would rename every generated
#               symbol in the language -- a far larger Emit-Change than the
#               noise it removes, so the answer is to name the noise rather
#               than to stop making it.
#
#   at F.dawn:N `e!` lowers to `panic(<message>)` and the checker builds that
#               message with the site baked in: "unwrapped None[ from f()] at
#               <path>:<line>" (checker.dawn unwrap_msg). A *string constant*,
#               so it is Core, so every line below an `e!` moves both hashes.
#               Added 2026-08-04 (#143), on this measurement: two comment lines
#               added to selfhost/src/main.dawn, nothing else --
#
#                 582c582
#                 <   str "unwrapped None at selfhost/src/main.dawn:164"
#                 ---
#                 >   str "unwrapped None at selfhost/src/main.dawn:166"
#
#               -- and both hashes moved. The danger is not the noise, it is
#               the habit: pure code movement is exactly when this golden is
#               the identity proof, and a reviewer trained to skim past line
#               numbers will skim past the one real instruction in with them.
#               The line goes; the *path* stays, because a site moving between
#               files is real. `?` does not do this (EPropagate carries no
#               message) and `assert` bakes the source text but not the line,
#               so this is the only shape -- confirmed by grepping every
#               selfhost dump for a `<file>:<line>` literal: 3 hits, all this
#               one. The pattern is anchored on " at " rather than on ".dawn:"
#               alone so that a `.dawn:12` occurring inside embedded source
#               text (stdsrc/rtsrc carry whole std files as constants) is
#               still compared exactly.
#
# Both are noise the *compiler chooses to make*. Neither is a reason to stop
# checking; a filter here is cheaper than the alternative, which is renaming
# every generated symbol / dropping the panic site from the message.
NORM='s/Adt[0-9]+/AdtN/g; s/ at ([^" ]*\.dawn):[0-9]+/ at \1:L/g'

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
# The same hashes over content with the two known noise sources erased -- see
# NORM below. A module whose exact hash moved but whose normalised hash did not
# carries no instruction difference.
norm_sha() {
  ( cd "$1" && for f in ./*.core; do
      printf '%s  %s\n' "$(sed -E "$NORM" "$f" | sha256sum | cut -d' ' -f1)" "$f"
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
  # every changed line, through the same filter norm.sha uses: if the two sides
  # then agree, nothing that runs moved
  added=$(grep -E '^\+' "$OUT/d.txt" | grep -v '^+++' | sed -E "$NORM")
  removed=$(grep -E '^-' "$OUT/d.txt" | grep -v '^---' | sed -E "$NORM")
  if [ -n "$added" ] && [ "${added#+}" = "${removed#-}" ]; then
    echo "Core IR changed, but only in ids and panic-site lines -- no instruction differs:"
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
    echo "Only ids and panic-site lines shifted in these -- no instruction changed:"
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

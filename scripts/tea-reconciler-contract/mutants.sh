#!/usr/bin/env bash
# The negative control for the tea reconciler contract.
#
#   ./scripts/tea-reconciler-contract/mutants.sh
#
# A differential that is green over 484 pairs proves nothing unless a wrong
# reconciler would have turned it red, and that is not hypothetical here: the
# `setself-keeps-donor-kids` mutant below survived the first version of the
# corpus, because every in-place update in it happened to be followed only by
# idempotent `Replace` patches. The corpus grew a pair to kill it. Nothing but a
# mutant would have said so.
#
# Each mutant breaks one production line and the run must fail. A mutant that
# stays green is a hole in the corpus and is reported as one; an edit that does
# not apply is reported too, since a mutant that never applied is a green run
# that means nothing at all -- the failure mode this file exists to catch,
# arriving through the back door. The edits live in mutate.py, one registered
# mutation per name below, each a literal that must match exactly once, so
# mutation-anchor-preflight.py proves them before any build as well.
#
# Every file is restored after every mutant, including on failure. The restore
# is from a copy taken here rather than from git, so running this over a dirty
# tree gives the tree back as it was and not as it was last committed.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root" || exit 1

targets=(
  packages/tea-core/src/diff.dawn
  packages/tea-core/src/walk.dawn
  packages/tea-term/src/widget.dawn
  packages/tea-dom/src/node.dawn
)

pristine="$(mktemp -d)"
for t in "${targets[@]}"; do
  mkdir -p "$pristine/$(dirname "$t")"
  cp "$t" "$pristine/$t"
done

restore() {
  for f in "${targets[@]}"; do cp "$pristine/$f" "$f"; done
}
cleanup() {
  restore
  rm -rf "$pristine"
}
trap cleanup EXIT

# The suites a mutant has to get past: the packages' own blocks, and the
# differential against the pre-split reconciler. Neither alone is enough --
# the differential never reaches route/step, and the package blocks have no
# oracle but themselves.
#
# The differential cannot reach the keyed path, and this is worth writing down
# rather than leaving to be discovered: the pre-split reconciler has no keyed
# ops to compare against, and the corpus is the terminal vocabulary, which
# does not implement `key` and so answers the default `None` for every node.
# What kills the keyed mutants below is the inline suites.
#
# One caution about reading a red command as an attribution: `dawn test` on
# the oracle project also runs `tea_core/diff`'s own blocks, since it depends
# on the package. So that command going red says the mutant was seen, not that
# the 484 pairs saw it. Measured over all 30 mutants here, the oracle command
# reds for 26 and the inline suites red for all 30.
#
# Ordered so that a mutant the terminal already sees still costs one run.
check() {
  ./bin/dawn test packages/tea-term > /dev/null 2>&1 \
    && ./bin/dawn test scripts/tea-reconciler-contract/oracle > /dev/null 2>&1 \
    && ./bin/dawn test packages/tea-dom > /dev/null 2>&1
}

# The mutants, by their names in mutate.py, in run order.
mutants=(
  # The reconciler: order, the three answers of `relate`, the tail ops, the
  # equality shortcut, and the descent.
  patch-order-swapped
  unrelated-becomes-inplace
  common-prefix-off-by-one
  no-equality-shortcut
  setself-keeps-donor-kids
  setself-args-swapped
  append-drops-existing
  truncate-off-by-one
  descend-wrong-index
  descend-loses-siblings

  # The walk, which routing is written on.
  walk-visits-children-first
  walk-path-not-extended

  # The vocabulary's side of the contract. Core is only ever as right as the
  # three functions it delegates to, so they get mutants of their own.
  kids-drops-the-styled-child
  rekid-styled-loses-its-style
  rekid-styled-not-total
  relate-ignores-the-style
  relate-restyles-instead-of-recursing
  relate-diffs-rows-against-columns
  relate-descends-into-a-leaf

  # Keyed pairing. Every one of these is a wrong answer that still type
  # checks and still terminates, and most of them still round-trip on some
  # inputs -- which is why the corpus has hand-picked shapes as well as a
  # generated sweep.
  keyed-never-pairs
  keyed-allows-duplicates
  keyed-drops-ascending
  keyed-place-skips-moves
  keyed-move-ends-swapped
  keyed-descends-at-the-old-index
  keyed-phases-swapped
  keyed-insert-ignores-its-position
  keyed-move-is-not-total

  # The vocabulary's half of keying: the key is part of a pair's fate, or a
  # list that fell back to indices pairs two different elements as one.
  relate-ignores-the-key
  key-is-not-carried-through-rekid
)

# The list and the registry are one set in one order, so a mutant cannot be
# registered and never run, nor listed and never registered.
registered="$(python3 -c 'import runpy, sys; print("\n".join(runpy.run_path(sys.argv[1])["MUTATIONS"]))' \
  scripts/tea-reconciler-contract/mutate.py)"
if [ "$registered" != "$(printf '%s\n' "${mutants[@]}")" ]; then
  echo "FAIL: mutants.sh's list and mutate.py's registry disagree" >&2
  exit 1
fi

holes=0
killed=0
for name in "${mutants[@]}"; do
  restore
  if ! reason="$(python3 scripts/tea-reconciler-contract/mutate.py "$name" . 2>&1)"; then
    echo "NOT APPLIED: $name ($reason; the mutant is vacuous)"
    holes=$((holes + 1))
    continue
  fi
  if check; then
    echo "HOLE: $name survived, the suites do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

restore
if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} mutant(s) unaccounted for" >&2
  exit 1
fi
echo "PASS  $killed/${#mutants[@]} mutant(s) killed"

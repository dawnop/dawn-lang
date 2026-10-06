#!/usr/bin/env bash
# Why this is a file of its own: run.sh's ledger line records ONE verdict for
# the tree, and for a long time the fold that makes it from the per-family
# verdicts simply never read the sequence family's (`seq_verdict`). A driver
# that refused the sequence program printed `BLOCKED  native: ...` and the
# script still ended on `tile-gpu-diff: pass`, so the ledger recorded a pass
# for a family nobody had run. The fold now lives here as a function so the
# one rule can be tested without a GPU:
#
#   a family that did not say `pass` (and was not skipped on purpose) cannot
#   leave the tree's verdict `pass`; the first thing that stopped a run wins.
#
# run.sh sources this file and runs the selftest before it folds, so every
# recorded ledger line comes from a run in which the negative control held.
# `bash scripts/tile-gpu-diff/fold_verdict.sh --selftest` runs it alone.

# fold_family_verdict <tree verdict so far> <family verdict>
fold_family_verdict() {
  if [ "$1" = pass ] && [ "$2" != pass ] && [ "$2" != skipped ]; then
    printf '%s\n' "$2"
  else
    printf '%s\n' "$1"
  fi
}

fold_verdict_selftest() {
  local got
  got="$(fold_family_verdict pass pass)"
  [ "$got" = pass ] || { echo "fold_verdict: pass + pass gave '$got'" >&2; return 1; }
  # THE NEGATIVE CONTROL: a blocked family must not leave the tree a pass.
  got="$(fold_family_verdict pass blocked:launch@init)"
  [ "$got" = blocked:launch@init ] || { echo "fold_verdict: pass + blocked family gave '$got', not the blocked verdict" >&2; return 1; }
  got="$(fold_family_verdict pass fail)"
  [ "$got" = fail ] || { echo "fold_verdict: pass + failed family gave '$got'" >&2; return 1; }
  # The first stop wins, and a skipped family is not a stop.
  got="$(fold_family_verdict blocked:alloc@init blocked:launch@init)"
  [ "$got" = blocked:alloc@init ] || { echo "fold_verdict: an earlier stop was overwritten: '$got'" >&2; return 1; }
  got="$(fold_family_verdict pass skipped)"
  [ "$got" = pass ] || { echo "fold_verdict: a skipped family changed the verdict: '$got'" >&2; return 1; }
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  if [ "${1:-}" = --selftest ]; then
    fold_verdict_selftest && echo "fold_verdict: selftest ok"
  else
    echo "usage: fold_verdict.sh --selftest" >&2
    exit 2
  fi
fi

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
# The fold used to be an if/elif ladder that grew one rung per family and was
# never extended past atom_diff, so fourteen later families (erf ... seq) could
# end blocked and the tree still recorded `pass` (#575, after #574 fixed the
# sequence family alone). It is now ONE ordered list, `verdict_families` in
# run.sh, folded by fold_named_verdicts, and the selftest reads run.sh to check
# that every `<name>_verdict=` it assigns is in that list: a new family cannot
# be added without being read, and a family dropped from the list is caught
# without a GPU.
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

# fold_named_verdicts <variable name>...: the tree's verdict from the named
# variables, in order. An unset or empty one is an error, not a pass.
fold_named_verdicts() {
  local acc=pass n v
  for n in "$@"; do
    v="${!n-}"
    [ -n "$v" ] || { echo "fold_verdict: family verdict '$n' is unset or empty" >&2; return 1; }
    acc="$(fold_family_verdict "$acc" "$v")"
  done
  printf '%s\n' "$acc"
}

# fold_coverage_check <run.sh> <family name>...: every `*verdict=` variable
# run.sh assigns above the list (the mutants below it are not families) is in
# the list, except the two control corpora that re-run a
# family already in it and are compared to it with an equality check.
fold_coverage_check() {
  local script="$1" v bad=0
  shift
  while read -r v; do
    case "$v" in erf_positive_verdict|atom_unique_verdict) continue ;; esac
    case " $* " in *" $v "*) ;; *) echo "fold_verdict: $v is assigned in run.sh but is not in verdict_families" >&2; bad=1 ;; esac
  done < <(sed -n '/^verdict_families=(/q;s/^[[:space:]]*\([a-z_]*verdict\)=.*/\1/p' "$script" | sort -u)
  return "$bad"
}

# fold_script_selftest <run.sh>: the same checks against the list as written.
# shellcheck disable=SC2034
fold_script_selftest() {
  local script="$1" names
  names="$(sed -n '/^verdict_families=(/,/^)/p' "$script" | sed '1d;$d' | tr -s ' \n' ' ')"
  [ -n "$names" ] || { echo "fold_verdict: no verdict_families list in $script" >&2; return 1; }
  # shellcheck disable=SC2086
  fold_coverage_check "$script" $names || return 1
  # The negative control on the list as written: with every family passing
  # (the arch family skipped, as on a small card), blocking any ONE of them
  # must give that family's verdict. A fold that stops reading at some index
  # fails here for every family past it.
  local n m got
  for n in $names; do
    for m in $names; do printf -v "$m" '%s' pass; done
    printf -v "$n" '%s' blocked:launch@init
    # shellcheck disable=SC2086
    got="$(fold_named_verdicts $names)"
    [ "$got" = blocked:launch@init ] || { echo "fold_verdict: blocking $n gave '$got': the fold does not read it" >&2; return 1; }
  done
  for m in $names; do printf -v "$m" '%s' pass; done
  arch_verdict=skipped
  # shellcheck disable=SC2086
  got="$(fold_named_verdicts $names)"
  [ "$got" = pass ] || { echo "fold_verdict: all families pass, one skipped, gave '$got'" >&2; return 1; }
}

# The fa..fe variables are read by name through ${!n} in fold_named_verdicts.
# shellcheck disable=SC2034
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
  # The list, every position: a blocked family at any index (first, middle,
  # last) must come out, the first stop wins, skipped is invisible.
  local fa=pass fb=pass fc=pass fd=skipped fe=pass
  got="$(fold_named_verdicts fa fb fc fd fe)"
  [ "$got" = pass ] || { echo "fold_verdict: all-pass list gave '$got'" >&2; return 1; }
  local pos names=(fa fb fc fd fe)
  for pos in 0 1 2 4; do
    fa=pass fb=pass fc=pass fd=skipped fe=pass
    printf -v "${names[$pos]}" '%s' blocked:launch@init
    got="$(fold_named_verdicts "${names[@]}")"
    [ "$got" = blocked:launch@init ] || { echo "fold_verdict: blocked family at index $pos gave '$got'" >&2; return 1; }
  done
  fb=blocked:alloc@init fe=blocked:launch@init
  got="$(fold_named_verdicts "${names[@]}")"
  [ "$got" = blocked:alloc@init ] || { echo "fold_verdict: the list did not keep the first stop: '$got'" >&2; return 1; }
  fe=
  ! fold_named_verdicts "${names[@]}" > /dev/null 2>&1 || { echo "fold_verdict: an empty family verdict was accepted" >&2; return 1; }
  # The coverage check itself: a family assigned in a script but absent from
  # the list must be named.
  local tmp
  tmp="$(mktemp)"
  # shellcheck disable=SC2016
  printf 'x_verdict="$(f)"\n  y_verdict=skipped\n' > "$tmp"
  if fold_coverage_check "$tmp" x_verdict > /dev/null 2>&1; then rm -f "$tmp"; echo "fold_verdict: coverage check accepted a family missing from the list" >&2; return 1; fi
  fold_coverage_check "$tmp" x_verdict y_verdict || { rm -f "$tmp"; echo "fold_verdict: coverage check rejected a complete list" >&2; return 1; }
  rm -f "$tmp"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  if [ "${1:-}" = --selftest ]; then
    fold_verdict_selftest && fold_script_selftest "$(dirname "$0")/run.sh" && echo "fold_verdict: selftest ok"
  else
    echo "usage: fold_verdict.sh --selftest" >&2
    exit 2
  fi
fi

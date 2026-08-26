#!/usr/bin/env bash
# The gate for tea_core's reconciler: a corpus differential against the
# reconciler it replaced, plus the mutants that give the differential teeth.
#
#   ./scripts/tea-reconciler-contract/run.sh
#
# Why a gate and not a consumer. `tea_core/diff` has no production caller and
# cannot get one on a terminal: the presenter's increment is a screen row, not a
# node (packages/tea-term/src/present.dawn says why in its own first lines), a
# row-mode layout shifts every line below a height change so partial repaint
# does not exist, and a driver deciding *whether* to repaint needs `==` rather
# than a patch list. The real consumer is a host with addressable nodes, which
# this tree does not have yet. So the tree diff would ship untested by anything
# that runs -- around 250 lines of a contract nobody exercises -- and this is
# what is put in its place instead: an oracle that says what the answers must
# be, and mutants that say the oracle is looking.
#
# oracle/ holds the pre-split reconciler verbatim, the corpus, and the
# translation between the two op sets. mutants.sh breaks one production line at
# a time and requires each break to be seen.
#
# What each half is worth, measured rather than assumed. Of the 30 mutants, the
# packages' own suites kill all 30 and the oracle project's command reds for 26
# (it never reaches the walk, which routing rather than reconciling uses, nor
# the DOM vocabulary, which it does not depend on). So the differential buys no
# mutant coverage, and that is not the claim being made for it: the package
# suites were written next to the implementation and could have been written to
# agree with a mistake in it, while the pre-split reconciler was written before
# any of this and cannot have been. The differential is the migration oracle;
# the mutants are the suites' oracle. Neither replaces the other, and the day
# the differential also kills something is the day it was doing two jobs.
#
# Read that 26 narrowly. `dawn test` on the oracle project runs `tea_core/diff`
# own blocks too, so the number counts commands that went red and not pairs
# that disagreed. Eleven of the 30 are about keyed pairing, which the
# differential cannot reach at all: mutants.sh says why.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/tea-reconciler-contract"
cd "$root"

# warm the toolchain first: bin/dawn announces a rebuild on stderr
./bin/dawn --version > /dev/null

# The positive control. A mutant run whose baseline was already red would
# report every mutant killed and mean nothing.
if ! ./bin/dawn test "$here/oracle"; then
  echo "FAIL: the differential is red before any mutant was applied" >&2
  exit 1
fi

"$here/mutants.sh"

#!/usr/bin/env bash
# The numbers the front page prints, each from the one thing that makes it
# true, as `key=value` lines on stdout.
#
# Why a script and not numbers in the copy: an outward-facing figure is the
# shape of sentence that goes stale without anybody noticing (doc-check.py's
# OUTWARD_CORPUS_COUNTS exists because README advertised 59 corpus programs
# long after there were more than a hundred). So no figure is written down
# anywhere: site/build.sh runs this, exports every line as
# DAWN_SITE_FIG_<KEY>, and the generator refuses to build when one is missing
# or empty (gen/home.read_figure). This script deliberately does not check its
# own values; an empty producer has to reach the generator's guard, which is
# what the guard's negative control drives.
#
# Why environment and not a file the generator reads: scripts/site-dist-diff.sh
# runs the generator over a snapshot that holds neither selfhost/ nor .git,
# and both of its legs inherit one environment, so both backends see the same
# numbers (the same reason gen/pages.build_stamp reads DAWN_SITE_VERSION).
#
# Each producer is the logic of the thing it counts, not a re-derivation:
#
#   selfhost_lines  the measure docs/design.md states for the self-hosted
#                   compiler: every .dawn file under selfhost/src except the
#                   generated embed/, concatenated, counted by wc -l.
#   native_corpus   the entries of scripts/spike-native/matrix.txt, read with
#                   the filter scripts/spike-native/run.sh applies to it. run.sh
#                   holds that list equal to the corpus on disk at the start of
#                   every run and then compiles each entry with both backends
#                   and compares stdout, stderr and the exit code, which is the
#                   sentence the figure stands under.
#
#   ./scripts/site-figures.sh
set -euo pipefail
cd "$(dirname "$0")/.."

selfhost_lines() {
  find selfhost/src -name '*.dawn' -not -path '*/embed/*' -print0 \
    | xargs -0 cat | wc -l | tr -d ' '
}

native_corpus() {
  { grep -v '^[[:space:]]*#' scripts/spike-native/matrix.txt \
      | grep -v '^[[:space:]]*$' || true; } | wc -l | tr -d ' '
}

printf 'selfhost_lines=%s\n' "$(selfhost_lines)"
printf 'native_corpus=%s\n' "$(native_corpus)"

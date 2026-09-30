#!/usr/bin/env bash
# The "removing a pub std function must say so" gate (issue #211,
# docs/std-moved-design.md §3), against the previous release's std.
#
# The baseline is the seed's released std, from scripts/seedjar.sh: extracted
# from the seed tag and checked against scripts/seed-std-checksums.txt before
# it is handed out, and the previous release by construction, because a
# release advances the seed to itself. Asking for it here rather than taking a
# path keeps CI and a local run on the same answer. No compiler is involved;
# a job that has already run bin/dawn finds the directory cached.
#
#   ./scripts/std-moved-check/run.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
. scripts/seedjar.sh

python3 scripts/std-moved-check/check.py --self-test > /dev/null
old=$(seed_std_dir)
exec python3 scripts/std-moved-check/check.py --old "$old" --new std

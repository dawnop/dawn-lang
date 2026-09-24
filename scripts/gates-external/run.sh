#!/usr/bin/env bash
#
# Run every gate job of .github/workflows/gates.yml, as it stands at one
# commit, somewhere other than GitHub, and leave a bundle that says so.
#
# Why this exists: a maintainer who wants the full gate set on a commit
# without spending the hosted runners (or while they are down) had no way to
# run it that was not a hand-picked subset, and no way to show afterwards what
# was run. This script derives the job and step list from gates.yml at the
# commit (gatesplan.py), runs each job in a fresh worktree of that commit
# (backend_local.py), and writes bundle.json (bundle.py), whose `complete` is
# true only when every run step gates.yml has was executed and exited 0.
#
# Usage:
#   run.sh --sha <sha> --backend local --out <dir> [--jobs N] [--keep-going]
#          [--only job1,job2] [--backend-opt KEY=VALUE ...] [--repo DIR]
#   run.sh --sha <sha> --backend local --out <dir> --dry-run   # the plan only
#   run.sh --sha <sha> --backend local --prefix DIR [--only ...]   # inside a prefix
#   run.sh --sha <sha> --backend crun --prefix DIR --jobs 16       # on the cluster
#   run.sh --resume <out> [--jobs N]   # continue a crun run whose controller died
#
# --resume reads <out>/invocation.json, which every run writes, so it takes no
# other option but --jobs. Jobs the cluster finished meanwhile are collected,
# jobs still running are waited for, and jobs never started are launched; a
# job that ended without a result fragment stays red (runner.py, backend_crun.py).
#
# --prefix DIR runs every job inside the prefix prefix.py lays out and
# inputs.py fills: its JDK, python, node and seed, an environment built from
# nothing, and every write under DIR. --out then defaults to DIR/out/<sha>.
#
# Local backend options (--backend-opt):
#   workdir=DIR        where per-job worktrees go (default: a sibling
#                      gates-external-jobs/ of the repository)
#   seed-cache=DIR     the shared seed cache copied into each worktree
#                      (default: .dawn/seeds of the main checkout)
#   jdk=DIR            the JDK 21 to use (default: ~/tools/graalvm-*)
#   timeout-scale=F    job timeout multiplier over gates.yml's (default 2)
#   keep-worktrees=1   leave the worktrees in place after the run
#
# --keep-going runs the remaining steps of a job after one fails, which
# GitHub does not do. The failure still makes the bundle incomplete; the
# option only buys knowing what else would have failed.
#
# Exit status: 0 complete, 1 ran but not complete, 2 refused to plan,
# 3 the bundle was refused (a leak or schema error), nothing written.
set -euo pipefail

here=$(cd -- "$(dirname -- "$0")" && pwd)
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --keep-going) args+=(--backend-opt keep-going=1); shift ;;
    --dry-run) args+=(--dry-run); shift ;;
    --sha|--backend|--out|--jobs|--only|--backend-opt|--repo|--prefix|--resume)
      [ $# -ge 2 ] || { echo "run.sh: $1 needs a value" >&2; exit 2; }
      args+=("$1" "$2"); shift 2 ;;
    -h|--help)
      awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
    *) echo "run.sh: unknown argument $1" >&2; exit 2 ;;
  esac
done
# -B: the runner's own bytecode would otherwise land in this directory, which is
# outside a prefix and would fail check-isolation for a reason not the run's.
exec python3 -B "$here/runner.py" "${args[@]}"

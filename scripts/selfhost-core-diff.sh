#!/usr/bin/env bash
# Core IR diff between two revisions: which modules' Core moved, and how.
# docs/native-backend-plan.md 11.4 S0.4; on demand since 2026-09-25
# (docs/recorded-numbers-design.md).
#
#   ./scripts/selfhost-core-diff.sh                    # merge-base(origin/main, HEAD) vs HEAD
#   ./scripts/selfhost-core-diff.sh --base <rev>       # <rev> vs HEAD
#   ./scripts/selfhost-core-diff.sh --base A --head B  # A vs B
#   ./scripts/selfhost-core-diff.sh --out <dir> ...    # keep both dumps and the full diff
#
# Exit 0: no module's Core differs. Exit 1: some did, and they are listed.
# Exit 2: the comparison could not be made.
#
# ## What it is for
#
# The identity proof of a pure-refactoring batch: "nothing moved except the
# modules this batch declares". #88's twelve knives, Perceus and the
# `CModule.dicts` repair were each read off this diff. Paste its output into
# the PR body; that is where the evidence lives.
#
# It used to be a per-commit CI gate against a golden recorded in the tree
# (scripts/core-golden/). That turned it into a ritual: every commit touching
# the compiler re-recorded the golden without reading it, and every rebase of
# a parallel branch re-recorded it again. The question it answers is a
# question about two revisions, so it now takes two revisions.
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
# `CModule.dicts` was the third: the JVM emitter used to re-derive dictionary
# class names from the checker's `impl_table`, so the table lowering built had
# one consumer, the then-unfinished C backend, and it could be wrong with every
# gate green. It *was* wrong, and this diff is where the repair was read. The
# JVM builds its dictionaries from the table now; this is still the one place
# that shows the table itself.
#
# ## What is dumped
#
# Every module of the compiler (`__lower --dump D selfhost`, which includes the
# std modules and source packages the compiler uses), and three programs with
# the std modules they reach. Programs chosen for coverage, not size: calc has
# closures, `?` and list work; traits has dictionaries with both slot kinds
# and a derived Ord; eqhash has the Eq/Hash bounds, which are the only
# construct that forwards a dictionary at runtime.
#
# ## One directory, used twice
#
# Each side is checked out with `git worktree add` at the *same* path, one
# after the other, and bootstrapped from its own seed there. Not two
# directories side by side: a panic site bakes the path it was compiled from.
# Measured 2026-08-04 -- `__lower --dump D /abs/path/to/selfhost` puts
#
#   str "unwrapped None at /home/dawn/workspace/dawn-lang/selfhost/src/main.dawn:164"
#
# in main.core where the relative form puts `selfhost/src/main.dawn:164`. The
# lowering below is always handed the relative `selfhost`, and the directory
# is the same on both sides anyway, so no module differs for where it was
# built. No normalisation is applied: line numbers left Core with #142, and
# generated names are derived from declarations, not from a global counter
# (the note beside `ty_key` in `selfhost/src/ir/core.dawn`).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

usage() {
  echo "usage: $0 [--base <rev>] [--head <rev>] [--out <dir>]" >&2
  exit 2
}

base="" head=HEAD out=""
while [ $# -gt 0 ]; do
  case $1 in
    --base) [ $# -ge 2 ] || usage; base=$2; shift 2 ;;
    --head) [ $# -ge 2 ] || usage; head=$2; shift 2 ;;
    --out) [ $# -ge 2 ] || usage; out=$2; shift 2 ;;
    *) usage ;;
  esac
done

commit_of() {
  git -C "$ROOT" rev-parse --verify -q "$1^{commit}" || {
    echo "error: $1 names no commit" >&2
    exit 2
  }
}
if [ -z "$base" ]; then
  base=$(git -C "$ROOT" merge-base origin/main "$head") || {
    echo "error: no merge-base of origin/main and $head; pass --base" >&2
    exit 2
  }
fi
base_sha=$(commit_of "$base")
head_sha=$(commit_of "$head")

# A module is named by its dump file; a program by the module name its dump
# file carries, and separately by the path it lives at.
PROGS=(calc traits eqhash)
PROG_PATHS=(examples/projects/calc.dawn examples/traits/traits.dawn examples/traits/eqhash.dawn)

WORK=$(mktemp -d "${TMPDIR:-/tmp}/dawn-core-diff.XXXXXX")
TREE="$WORK/tree"
cleanup() {
  git -C "$ROOT" worktree remove --force "$TREE" > /dev/null 2>&1 || true
  git -C "$ROOT" worktree prune > /dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# Both sides share one seed cache, the caller's, so each seed is fetched once.
# Each side's own std: an inherited DAWN_STD would hand both sides one std.
export DAWN_SEED_CACHE="${DAWN_SEED_CACHE:-$ROOT/.dawn/seeds}"
unset DAWN_STD

lower_into() { # <dump dir> <log> <target>
  mkdir -p "$1"
  if ! ./bin/dawn __lower --dump "$1" "$3" > "$2" 2>&1 \
      || ! grep -q ', 0 failed' "$2"; then
    echo "error: lowering $3 failed or left gaps at $(git rev-parse --short HEAD)" >&2
    cat "$2" >&2
    exit 2
  fi
}

dump_side() { # <rev> <side>
  local dest="$WORK/$2"
  git -C "$ROOT" worktree add -q --detach "$TREE" "$1"
  (
    cd "$TREE"
    echo "[$2] $(git rev-parse --short HEAD): bootstrapping" >&2
    ./bin/dawn --version > "$WORK/$2.version.log" 2>&1 || {
      echo "error: the toolchain at $1 did not build" >&2
      cat "$WORK/$2.version.log" >&2
      exit 2
    }
    for i in "${!PROGS[@]}"; do
      if [ ! -f "${PROG_PATHS[$i]}" ]; then
        echo "[$2] ${PROG_PATHS[$i]} is not in this revision; ${PROGS[$i]} skipped" >&2
        continue
      fi
      lower_into "$dest/${PROGS[$i]}" "$WORK/$2.${PROGS[$i]}.log" "${PROG_PATHS[$i]}"
    done
    # relative, and it must stay relative: see "One directory, used twice"
    lower_into "$dest/selfhost" "$WORK/$2.selfhost.log" selfhost
  )
  git -C "$ROOT" worktree remove --force "$TREE"

  # std is lowered once per program. The dumps must agree: std's Core is
  # supposed to be a property of std, but `program_tables` unions the *user*
  # program's impls into the tables lowering consults, so "independent of the
  # target" is an assumption and not a theorem. Checked, not assumed.
  local first="" p f
  for p in "${PROGS[@]}"; do
    [ -d "$dest/$p" ] || continue
    if [ -z "$first" ]; then first=$p; continue; fi
    for f in "$dest/$first"/std.*.core; do
      [ -f "$dest/$p/$(basename "$f")" ] || continue
      if ! cmp -s "$f" "$dest/$p/$(basename "$f")"; then
        echo "error: [$2] $(basename "$f") lowers differently under $first and $p." >&2
        echo "       std's Core has become target-dependent -- that is the news." >&2
        diff -u "$f" "$dest/$p/$(basename "$f")" | head -40 >&2
        exit 2
      fi
    done
  done
}

dump_side "$base_sha" base
dump_side "$head_sha" head

# Compare dump by dump. A module appears once per target that reaches it
# (std.list under every program and under selfhost); it is listed once, with
# the targets it moved under.
( cd "$WORK/base" && find . -name '*.core' | sort ) > "$WORK/base.list"
( cd "$WORK/head" && find . -name '*.core' | sort ) > "$WORK/head.list"
: > "$WORK/moved"
: > "$WORK/full.diff"
while read -r rel; do
  b="$WORK/base/$rel" h="$WORK/head/$rel"
  target=${rel#./}; target=${target%%/*}
  module=$(basename "$rel" .core)
  if [ ! -f "$b" ]; then
    printf '%s\t%s\tadded\n' "$module" "$target" >> "$WORK/moved"
  elif [ ! -f "$h" ]; then
    printf '%s\t%s\tremoved\n' "$module" "$target" >> "$WORK/moved"
  elif ! cmp -s "$b" "$h"; then
    printf '%s\t%s\tchanged\n' "$module" "$target" >> "$WORK/moved"
    diff -u --label "base/$rel" --label "head/$rel" "$b" "$h" >> "$WORK/full.diff" || true
  fi
done < <(sort -u "$WORK/base.list" "$WORK/head.list")

compared=$(sort -u "$WORK/base.list" "$WORK/head.list" | wc -l | tr -d ' ')
echo "Core IR: base $(git -C "$ROOT" rev-parse --short "$base_sha") vs head $(git -C "$ROOT" rev-parse --short "$head_sha"), $compared dump(s) compared"

if [ -n "$out" ]; then
  mkdir -p "$out"
  rm -rf "$out/base" "$out/head"
  cp -r "$WORK/base" "$WORK/head" "$out/"
  cp "$WORK/full.diff" "$out/core.diff"
fi

if [ ! -s "$WORK/moved" ]; then
  echo "Core unchanged: 0 module(s) differ"
  exit 0
fi

n=$(cut -f1 "$WORK/moved" | sort -u | wc -l | tr -d ' ')
echo "Core changed in $n module(s):"
sort "$WORK/moved" | awk -F'\t' '
  $1 != m { if (m != "") printf "  %-40s %s [%s]\n", m, k, t; m = $1; k = $3; t = $2; next }
  { t = t " " $2; if ($3 != k) k = k "/" $3 }
  END { printf "  %-40s %s [%s]\n", m, k, t }'
echo
lines=$(wc -l < "$WORK/full.diff" | tr -d ' ')
head -200 "$WORK/full.diff"
if [ "$lines" -gt 200 ]; then
  if [ -n "$out" ]; then
    echo "... ($lines diff lines in all; the rest is in $out/core.diff)"
  else
    echo "... ($lines diff lines in all; rerun with --out <dir> to keep them)"
  fi
fi
exit 1

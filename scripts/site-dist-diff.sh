#!/usr/bin/env bash
# The site generator's second-backend differential: JVM and C must write the
# same site/dist, byte for byte. site/README.md has called that a project
# tradition since M5; this script is the first thing that enforces it.
#
# Two things were wrong with the way it used to be done by hand.
#
# 1. `dawn run site` twice with a `diff -r` between the runs reads the *working
#    tree* both times. On 2026-08-04 another agent edited docs/spec.md between
#    the two builds: `diff -r` reported ~40 lines and not one of them was a
#    backend disagreement. A tree diff run over live inputs cannot tell "the
#    two backends disagree" from "the input moved" -- and the same structure
#    fails the other way round too, silently: two edits that cancel out leave
#    both builds wrong and still identical.
#
#    So the inputs are snapshotted first, and both backends are pointed at the
#    snapshot. Nothing anybody does to the working tree while this runs can
#    reach either build, in either direction. The snapshot needs no manifest to
#    be complete: the generator is fail-fast on every read (`must_read`), so a
#    file left out of it fails the build rather than changing the answer.
#
#    Not a git worktree, which was the other candidate. #143 measured that
#    `unwrapped None at <path>:<line>` bakes absolute paths into products, so
#    two worktrees are guaranteed to differ; and selfhost-core-diff.sh's
#    cross-machine reproducibility rests on a *relative* path argument, so
#    moving the tree is exactly the thing this repository has learned not to
#    do. A snapshot in one fixed directory has neither problem.
#
# 2. The comparison had quietly stopped being possible at all. Two `use java`
#    lines entered site/src/gen/pages.dawn with the favicon (286610d) and one
#    `use java` anywhere makes the whole program uncompilable on the C backend
#    ("`use java` cannot be compiled to native"), so for a milestone there was
#    no native side to compare against and README still advertised the
#    comparison. Those two lines are gone; if they come back this script says
#    so at the emit step instead of the claim rotting again.
#
# What is snapshotted and what is not: the generator's *data* -- docs/,
# examples/, site/, packages/ -- is copied. The toolchain (bin/dawn,
# selfhost/src, std/, runtime/c) cannot be, because the JVM leg runs through
# `bin/dawn`, which rebuilds itself from the recursive Planner source closure on
# demand. So the toolchain is fingerprinted instead, before and after; a change there aborts
# with "toolchain moved" rather than being reported as a backend divergence.
# That is the residual hole, named rather than papered over.
#
#   ./scripts/site-dist-diff.sh          # emits and builds the native generator
#   KEEP=1 ./scripts/site-dist-diff.sh   # keep the work directory
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

OUT=${TMPDIR:-/tmp}/site-dist-diff.$$
mkdir -p "$OUT"
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

# Everything the *compiler* is made of. bin/dawn's source stamp consumes the
# Planner's recursive source-input manifest, so compiler-plan and its local
# dependencies move this fingerprint without another hand-maintained package
# list. runtime/c is added separately because the native leg links it after the
# compiler has emitted C.
toolchain_fingerprint() {
  local source_fingerprint
  source_fingerprint=$(DAWN_PRINT_STAMP=1 "$ROOT/bin/dawn") || return 1
  {
    printf 'source\t%s\n' "$source_fingerprint"
    while IFS= read -r -d '' f; do
      if [ -f "$f" ]; then
        sha256sum "$f"
      elif ! git ls-files --deleted --error-unmatch -- "$f" > /dev/null 2>&1; then
        echo "ERROR: tracked toolchain input is unreadable: $f" >&2
        return 1
      fi
    done < <(git ls-files -z runtime/c)
  } | sha256sum | cut -d' ' -f1
}

FP_BEFORE=$(toolchain_fingerprint)

# ---- the snapshot ----
SNAP="$OUT/snap"
mkdir -p "$SNAP"
# site/dist is the product, not an input; node_modules is npm's, and the
# generator only ever reads site/play-ui/dist.
tar -cf - --exclude='site/dist' --exclude='site/play-ui/node_modules' \
  docs examples site packages | tar -xf - -C "$SNAP"
# site/build/stdlib.json is generated, not tracked (site/build.sh makes it).
# Regenerating it into the snapshot keeps the run self-contained and keeps this
# script from writing anything into the working tree.
mkdir -p "$SNAP/site/build"
./bin/dawn doc --stdlib > "$SNAP/site/build/stdlib.json"

echo "snapshot: $(find "$SNAP" -type f | wc -l) input file(s)"

# ---- leg 1: the JVM backend ----
echo "== JVM =="
(cd "$SNAP" && "$ROOT/bin/dawn" run site) > "$OUT/jvm.log" 2>&1 || {
  echo "FAIL: the JVM generator did not finish"; tail -20 "$OUT/jvm.log"; exit 1
}
mv "$SNAP/site/dist" "$OUT/dist-jvm"

# ---- leg 2: the C backend ----
# Emitted from the snapshot too, so the program compiled here is the program
# the JVM leg just ran, whatever the working tree is doing.
echo "== native =="
"$ROOT/bin/dawn" __emitc "$SNAP/site" -o "$OUT/site.c" > "$OUT/emitc.log" 2>&1 || {
  echo "FAIL: the site generator does not emit to C"; tail -20 "$OUT/emitc.log"; exit 1
}
"${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$ROOT/runtime/c" -o "$OUT/sitegen" "$OUT/site.c" \
  "$ROOT/runtime/c/dawn_rt.c" -lm
(cd "$SNAP" && "$OUT/sitegen") > "$OUT/native.log" 2>&1 || {
  echo "FAIL: the native generator did not finish"; tail -20 "$OUT/native.log"; exit 1
}
mv "$SNAP/site/dist" "$OUT/dist-native"

# ---- the toolchain has to have held still ----
FP_AFTER=$(toolchain_fingerprint)
if [ "$FP_BEFORE" != "$FP_AFTER" ]; then
  echo "ABORT: the toolchain moved while this ran ($FP_BEFORE -> $FP_AFTER)."
  echo "       The two legs were built by two different compilers, so a"
  echo "       difference between them would prove nothing. Re-run on a"
  echo "       quiet tree; this is not a backend divergence."
  exit 2
fi

# ---- the comparison ----
if diff -r "$OUT/dist-jvm" "$OUT/dist-native" > "$OUT/dist.diff" 2>&1; then
  echo "OK: $(find "$OUT/dist-jvm" -type f | wc -l) generated file(s) identical on both backends"
else
  echo "FAIL: site/dist differs between the JVM and C backends"
  head -40 "$OUT/dist.diff"
  exit 1
fi

#!/usr/bin/env bash
# The std parameter-name freeze (#210): every parameter name the previous
# release documented must be the same at HEAD, or a commit since that release
# says `Param-Change(<item>): <old> -> <new>`. The comparison and the
# declaration language live in scripts/param-change.py, whose header has the
# rules and the reasons; this file only produces its two inputs and proves the
# older one is what it claims to be.
#
# THE TRAP THIS IS BUILT AROUND. `dawn doc --stdlib` documents the std it
# loads, and it loads `--std <dir>`, defaulting to `std` under the cwd. Run the
# seed from the repository root without `--std` and it documents HEAD's std:
# the two dumps then differ only in the prelude (compiled into each jar), and a
# renamed std parameter is invisible to the one gate that exists to see it,
# green forever. The audit's prototype (research-std-param-names-20261001.md)
# only found the real difference once it ran the seed in an empty directory.
# So the seed runs here with an explicit `--std` naming the seed's released std
# (seedjar.sh seed_std_dir, which verifies that tree against
# scripts/seed-std-checksums.txt), from an empty working directory, and the
# same invocation is then pointed at a canary directory whose index names a
# module that does not exist: it must fail, naming that module. If it
# succeeds, the invocation is not reading the std it is handed, and the gate
# refuses to report anything.
#
# Why a canary and not "the two dumps must differ". That rule is what the
# audit proposed, and on the tree it was written for it holds. It stops
# holding at the one moment that is guaranteed to come: the commit that
# advances the seed to a release makes the seed's std HEAD's std, the two
# dumps are the same bytes, and the rule reds main on the release itself (and
# on every later commit until some pub std doc comment moves). Identical dumps
# are reported, never refused; what refuses is the direct proof.
#
# What moves the dumps: std/** on each side, and the prelude and builtin
# tables, which are compiled into each toolchain from the checker (that is why
# the HEAD side is ./bin/dawn and not a read of the sources).
#
# Runs as the fifth step of gates.yml's prev-diff job, after run-diff has
# built ./bin/dawn, so the HEAD side costs one `doc --stdlib`.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
. scripts/seedjar.sh

OUT=${TMPDIR:-/tmp}/selfhost-param-diff.$$
mkdir -p "$OUT/seed-cwd" "$OUT/canary"
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

TAG=$(tr -d ' \n' < scripts/seed-release.txt)
SEEDJAR="$(seed_jar)"
SEEDJAVA="$(seed_java)"
SEED_STD="$(seed_std_dir)"
# seed_std_dir fetches the tag when the clone lacks it; the window below is
# read from that tag, and an unreadable window would read as "declared
# nothing", so its absence is an error here rather than an empty log.
git rev-parse -q --verify "refs/tags/$TAG^{commit}" > /dev/null || {
  echo "FAIL the seed tag $TAG is not in this clone; the declaration window $TAG..HEAD cannot be read"
  exit 1
}

# The one seed invocation, used for the dump and the canary alike, so the
# canary tests the very command line that produced the dump.
seed_doc() { # std-dir
  (cd "$OUT/seed-cwd" && "$SEEDJAVA" -Xss512m -jar "$SEEDJAR" doc --stdlib --std "$1")
}

seed_doc "$SEED_STD" > "$OUT/seed.json"

printf 'param_diff_canary_missing\n' > "$OUT/canary/modules.txt"
if seed_doc "$OUT/canary" > "$OUT/canary.txt" 2>&1; then
  echo "FAIL the seed documented a std without reading the one it was handed:"
  echo "     \`doc --stdlib --std $OUT/canary\` succeeded, and that directory's"
  echo "     index names a module that does not exist. The N-1 dump cannot be"
  echo "     trusted to be $TAG's std, so nothing is compared."
  exit 1
fi
if ! grep -Fq param_diff_canary_missing "$OUT/canary.txt"; then
  echo "FAIL the canary run failed, but not on the canary's missing module:"
  sed 's/^/     /' "$OUT/canary.txt" | sed -n '1,10p'
  exit 1
fi

./bin/dawn --version > /dev/null
./bin/dawn doc --stdlib > "$OUT/head.json"

if cmp -s "$OUT/seed.json" "$OUT/head.json"; then
  echo "NOTE the N-1 and HEAD dumps are the same bytes; the canary above proved"
  echo "     the seed read $TAG's std, so this is no change, not a misread"
fi

python3 scripts/param-change.py compare --old "$OUT/seed.json" --new "$OUT/head.json" \
  --range "$TAG..HEAD"
echo "OK: every std parameter-name change since $TAG is declared"

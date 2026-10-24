#!/usr/bin/env bash
# N vs N-1 differential (M8 phase 3) — the main oracle once Kotlin retires:
# the previous release's toolchain and HEAD compile the same corpus and every
# byte difference must be declared. Also the machine enforcement of the seed
# feature discipline: the N-1 jar must be able to compile HEAD selfhost/src.
#
#   corpus     — every in-repo Dawn target emits byte-identically under both
#                compilers. backend-dawn, the production ecosystem corpus, is
#                swept the same way under `--corpus site`, with lex/parse dumps
#                and the formatter, which need no third-party class path; it is
#                off by default, and the section below says why
#   declaring  — an intentional output change lands with an
#                `Emit-Change(<label>):` line in its commit message, one line
#                per check label it moves; the script scans the commits since
#                the N-1 tag and turns a declared diff into a pass. The
#                declaration language, and what it refuses, is documented at
#                the top of scripts/emitchange.sh
#
# The N-1 jar downloads from the GitHub release named in
# scripts/seed-release.txt (dawn-selfhost.jar preferred, the Kotlin dawn.jar
# for releases predating the dual publish) and caches under .dawn/seeds/.
#
# ---- why the ecosystem corpus is opt-in ----
#
# It is fetched over the network from another repository at a pinned commit, so
# while it ran by default this gate could go red for GitHub being unreachable,
# for a force-push over there, or for that repository turning private. None of
# those is a statement about this compiler, and all of them landed on the path
# every push has to pass. The pin was stale by construction as well: nothing
# advanced it, so the "ecosystem user" it stood for was written against an
# older language version and answered a smaller question every week
# (ARCH-N07, 2026-09-07). `--check-pin` below is what advances it now.
#
# So: gates.yml's `prev-diff` job runs this script with no arguments and gets
# the in-repo corpus only, while .github/workflows/nightly.yml passes
# `--corpus site` once a day. The three labels the ecosystem corpus supplies
# (`lex backend-dawn`, `parse backend-dawn`, `fmt backend-dawn`) are therefore
# still checked, a day later rather than a push later. Nothing else moved: with
# `--corpus site` this script does exactly what it did before.
#
#   ./scripts/selfhost-prev-diff.sh                  # in-repo corpus (CI push)
#   ./scripts/selfhost-prev-diff.sh --corpus site    # + backend-dawn (nightly)
#   ./scripts/selfhost-prev-diff.sh --check-pin      # is the pin stale? (nightly)
#   ./scripts/selfhost-prev-diff.sh --pack-corpus F  # write the corpus to tar F
#   DAWN_ECO_CORPUS=F ./scripts/selfhost-prev-diff.sh --corpus site   # offline
#
# ---- the corpus without a network (2026-10-19) ----
#
# The seed jar and its std already work offline: a cached copy is used without
# a download and checked against a recorded digest on every use. The corpus
# had no such form, so `--corpus site` could not run on a machine with no
# route to GitHub. It has one now, on the same terms. ECO_TREES pairs each
# production source root with its tree hash (seedjar.sh's seed_tree_sha, the
# hash the seed's std is held to), beside the commit it came from.
# `--pack-corpus F` fetches the pinned commit where there is a network, checks
# every root, writes those subtrees to the tar F and exits; DAWN_ECO_CORPUS=F
# makes `--corpus site` read the tar instead of fetching, and refuse it unless
# every root matches its pin. Packing, verification and scanning read this
# one list. Unset, the fetch checks the hashes too, silently on success, so a
# pin advanced without its digests goes red at the next nightly rather than
# at the next offline run. Missing roots and roots with no Dawn sources are
# refused. Either way a symbolic link or any other non-regular entry is
# refused: the hash covers regular files only and the sweep below would hand
# a link to the compiler unhashed.
#
# The other inputs that reach outside are not changed. The declaration scan
# reads `git log` since the seed tag, so this script needs a real repository
# with that tag reachable; that is what the gate checks, and whoever runs it
# elsewhere provides one. The seed jar and std come from .dawn/seeds when
# present. docs/prevdiff-offline-corpus-design.md lists every dependency.
#
# ---- when the pin is stale (ruling 9(c), 2026-09-24) ----
#
# The corpus answers "would this change break the ecosystem's code as it is
# now", and dawnop-site defines "now", not this repository's release cadence:
# it pins a Dawn release in `.dawn-version` and moves it only for a
# significant improvement (CLAUDE.md, cross-repository contract). So the rule
# is: the pinned commit must not be older than dawnop-site's latest commit on
# its default branch that changed `.dawn-version`. When dawnop-site bumps, the
# pin here follows within a nightly cycle or the check is red; while it does
# not bump, nothing is red however many releases this repository makes. The
# rule "pin more than one release behind this repository" was the first
# draft and is not used: dawnop-site is behind by design, so it would have
# been red on its first day and every day after.
#
# `--check-pin` reads the answer with three `gh api` calls against the public
# repository and exits; it clones nothing and builds nothing. It also prints
# which release the pin declares against this repository's seed, for a person
# to read; that line decides nothing. The pin sat at a72bfc9 (v0.59.0) from
# 2026-08 until this check existed, three bumps behind.
set -euo pipefail
cd "$(dirname "$0")/.."

CORPUS=none
CHECK_PIN=0
PACK=
while [ $# -gt 0 ]; do
  case $1 in
    --corpus) CORPUS=$2; shift 2 ;;
    --check-pin) CHECK_PIN=1; shift ;;
    --pack-corpus) PACK=${2:?--pack-corpus needs a file}; shift 2 ;;
    *) echo "usage: $0 [--corpus site|none] [--check-pin] [--pack-corpus FILE]" >&2; exit 2 ;;
  esac
done
case $CORPUS in
  site | none) ;;
  *) echo "error: --corpus takes 'site' or 'none', not '$CORPUS'" >&2; exit 2 ;;
esac

ROOT=$(pwd)
TAG=$(tr -d ' \n' < scripts/seed-release.txt)

# Keep the ecosystem oracle immutable: a release tag must run against the same
# source tree every time. Mirrors may override the transport URL, but not the
# revision whose bytes define this gate.
ECO_URL=${DAWNOP_SITE_URL:-https://github.com/dawnop/dawnop-site.git}
ECO_REPO=dawnop/dawnop-site
ECO_REV=94fbd9450b07823969f19fc0a3aff61f9a474812
# seed_tree_sha per production source root at ECO_REV; advance them together
ECO_TREES=(
  'backend-dawn/core/src 8e7131235a47e922c0b7602804b3c1c268b416e4ca18e87e0202c61a41365852'
  'backend-dawn/app/jvm/src c2708c9f2820df68ee80678dcc1189204cc084520ccbe204081687e19a2006f0'
  'backend-dawn/app/native/src 6e8a08db15d37f33119426e1edcc290d66857b9c94d8a8c4e1f3d4ebc5f01b6f'
)
ECO_ROOTS=()
for pin in "${ECO_TREES[@]}"; do
  ECO_ROOTS+=("${pin%% *}")
done
if [ "${#ECO_ROOTS[@]}" = 0 ]; then
  echo "ERROR: no ecosystem source roots declared" >&2
  exit 1
fi

if [ "$CHECK_PIN" = 1 ]; then
  bump=$(gh api "repos/$ECO_REPO/commits?path=.dawn-version&per_page=1" --jq '.[0].sha')
  if [ -z "$bump" ]; then
    echo "ERROR: $ECO_REPO has no commit that changed .dawn-version" >&2
    exit 1
  fi
  bump_version=$(gh api "repos/$ECO_REPO/contents/.dawn-version?ref=$bump" \
    --jq .content | base64 -d | tr -d ' \n')
  pin_version=$(gh api "repos/$ECO_REPO/contents/.dawn-version?ref=$ECO_REV" \
    --jq .content | base64 -d | tr -d ' \n')
  # compare/<base>...<head>: `ahead` means the pin contains the bump.
  status=$(gh api "repos/$ECO_REPO/compare/$bump...$ECO_REV" --jq .status)
  echo "INFO pin $ECO_REV declares $pin_version; this repository's seed is $TAG"
  case $status in
    identical | ahead)
      echo "OK   pin contains $ECO_REPO's last .dawn-version change $bump ($bump_version)"
      exit 0 ;;
    *)
      echo "STALE pin $ECO_REV ($pin_version) is $status relative to $ECO_REPO's last" \
        ".dawn-version change $bump ($bump_version). Advance ECO_REV in" \
        "scripts/selfhost-prev-diff.sh to $bump or later and run --corpus site;" \
        "its failure identifies any missing root or mismatched tree hash." >&2
      exit 1 ;;
  esac
fi

. scripts/seedjar.sh

# Fetch ECO_REV into the directory $1 (a fresh git repository).
eco_fetch() {
  git init --quiet "$1"
  git -C "$1" remote add origin "$ECO_URL"
  if ! git -C "$1" fetch --quiet --depth 1 origin "$ECO_REV"; then
    echo "ERROR: failed to fetch pinned backend-dawn corpus $ECO_REV" >&2
    return 1
  fi
  if ! git -C "$1" checkout --quiet --detach FETCH_HEAD; then
    echo "ERROR: failed to check out pinned backend-dawn corpus $ECO_REV" >&2
    return 1
  fi
  local head
  head=$(git -C "$1" rev-parse HEAD)
  if [ "$head" != "$ECO_REV" ]; then
    echo "ERROR: backend-dawn corpus resolved to $head, expected $ECO_REV" >&2
    return 1
  fi
}

# Hold each declared source root under $1 to its hash; $2 names the transport.
eco_verify() {
  local pin rel expected src odd got
  for pin in "${ECO_TREES[@]}"; do
    rel=${pin%% *}
    expected=${pin#* }
    src=$1/$rel
    if [ ! -d "$src" ]; then
      echo "ERROR: $2 holds no $rel" >&2
      return 1
    fi
    odd=$(find "$src" ! -type f ! -type d | sed -n '1,3p')
    if [ -n "$odd" ]; then
      echo "ERROR: $2 holds entries in $rel that are neither files nor directories," >&2
      echo "  which the tree hash does not cover:" >&2
      printf '%s\n' "$odd" | sed 's/^/  /' >&2
      return 1
    fi
    if [ -z "$(find "$src" -type f -name '*.dawn' -print -quit)" ]; then
      echo "ERROR: $2 holds no Dawn source files in $rel" >&2
      return 1
    fi
    got=$(seed_tree_sha "$src")
    if [ "$got" != "$expected" ]; then
      echo "ERROR: backend-dawn corpus from $2 failed verification for $rel" >&2
      echo "  expected $expected (ECO_TREES)" >&2
      echo "  actual   ${got:-<no sha256sum or shasum on PATH>}" >&2
      return 1
    fi
  done
}

if [ -n "$PACK" ]; then
  PACK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/selfhost-prev-diff-pack.XXXXXX")
  trap 'rm -rf "$PACK_DIR"' EXIT
  eco_fetch "$PACK_DIR/eco" || exit 1
  eco_verify "$PACK_DIR/eco" "the pinned commit $ECO_REV" || exit 1
  git -C "$PACK_DIR/eco" archive --format=tar HEAD "${ECO_ROOTS[@]}" > "$PACK_DIR/corpus.tar"
  mv "$PACK_DIR/corpus.tar" "$PACK"
  echo "OK   packed backend-dawn corpus $ECO_REV (${#ECO_ROOTS[@]} verified source roots) into $PACK"
  exit 0
fi

# EMITCHANGE_MODE=range turns "the seed" into the change's base toolchain
# (scripts/emitrange.sh); the rest of the script is unchanged.
. scripts/emitrange.sh
range_enter
TAG=${RANGE_TAG:-$TAG}
# on bin/dawn's JDK, not PATH's java (seedjar.sh seed_java, issue #267)
PREV=("$(seed_java)" -XX:-UsePerfData -Xss512m -jar "$(seed_jar)")
# the seed compiles against the std it released with, not today's std/ --
# the repo std may use prelude machinery one generation ahead of the seed's
# checker (seedjar.sh seed_std_dir). Std-source changes therefore show up in
# the emit diffs below like any other emit change, and are declared the same
# way.
PREV_STD=(--std "$(seed_std_dir)")

OUT=${TMPDIR:-/tmp}/selfhost-prev-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

ECO="$OUT/eco"
if [ "$CORPUS" = site ] && [ -n "${DAWN_ECO_CORPUS:-}" ]; then
  mkdir -p "$ECO"
  if ! tar -xf "$DAWN_ECO_CORPUS" -C "$ECO"; then
    echo "ERROR: cannot unpack DAWN_ECO_CORPUS=$DAWN_ECO_CORPUS" >&2
    exit 1
  fi
  eco_verify "$ECO" "DAWN_ECO_CORPUS=$DAWN_ECO_CORPUS" || exit 1
  echo "OK   pinned backend-dawn corpus $ECO_REV (prepared archive, ${#ECO_ROOTS[@]} verified source roots)"
elif [ "$CORPUS" = site ]; then
  eco_fetch "$ECO" || exit 1
  eco_verify "$ECO" "the pinned commit $ECO_REV" || exit 1
  echo "OK   pinned backend-dawn corpus $ECO_REV"
else
  echo "SKIP backend-dawn corpus (--corpus site enables it; nightly.yml passes it)"
fi

# feature discipline: the previous release must compile today's selfhost.
# The window leg owns it; the base of a change is not a seed.
if [ "${EMITCHANGE_MODE:-}" != range ]; then
  "${PREV[@]}" build selfhost "${PREV_STD[@]}" -o "$OUT/head-by-prev.jar" > /dev/null
  echo "OK   $TAG compiles HEAD selfhost (seed feature discipline)"
fi

# HEAD toolchain (bin/dawn builds it on demand)
./bin/dawn --version > /dev/null
HEAD_BIN=(./bin/dawn)

. scripts/emitchange.sh
# read and validate every declaration in the window up front: a gate that
# cannot parse its own exemptions has no business granting them, and finding
# that out before the first diff keeps the message legible
emitchange_load

fail=0
gate() { # label, differs (0 identical, 1 differs)
  emit_gate "$1" "$2" || fail=1
}

for t in site playground packages/web packages/web-jvm packages/json selfhost examples/projects/calc.dawn \
    examples/interop/interop.dawn examples/effects/handlers.dawn \
    examples/text/chars.dawn examples/errors/barriers.dawn; do
  mkdir -p "$OUT/prev/$t" "$OUT/head/$t"
  "${PREV[@]}" __emit "${PREV_STD[@]}" "$t" -o "$OUT/prev/$t" > /dev/null
  "${HEAD_BIN[@]}" __emit "$t" -o "$OUT/head/$t" > /dev/null
  if diff -rq "$OUT/prev/$t" "$OUT/head/$t" > /dev/null; then
    gate "emit $t" 0
  else
    gate "emit $t" 1
  fi
done

# the production ecosystem corpus: front-end dumps + formatter over
# backend-dawn (its java-deps are not on this class path, so no emit)
if [ "$CORPUS" = site ]; then
  sources=()
  for rel in "${ECO_ROOTS[@]}"; do
    sources+=("$ECO/$rel")
  done
  files=$(find "${sources[@]}" -type f -name '*.dawn' | LC_ALL=C sort)
  # shellcheck disable=SC2086
  "${PREV[@]}" __lex $files > "$OUT/eco-lex-prev.txt"
  # shellcheck disable=SC2086
  "${HEAD_BIN[@]}" __lex $files > "$OUT/eco-lex-head.txt"
  if diff "$OUT/eco-lex-prev.txt" "$OUT/eco-lex-head.txt" > /dev/null
  then gate "lex backend-dawn" 0; else gate "lex backend-dawn" 1; fi
  # shellcheck disable=SC2086
  "${PREV[@]}" __parse $files > "$OUT/eco-parse-prev.txt"
  # shellcheck disable=SC2086
  "${HEAD_BIN[@]}" __parse $files > "$OUT/eco-parse-head.txt"
  if diff "$OUT/eco-parse-prev.txt" "$OUT/eco-parse-head.txt" > /dev/null
  then gate "parse backend-dawn" 0; else gate "parse backend-dawn" 1; fi
  for rel in "${ECO_ROOTS[@]}"; do
    mkdir -p "$OUT/fmt-prev/$(dirname "$rel")" "$OUT/fmt-head/$(dirname "$rel")"
    cp -r "$ECO/$rel" "$OUT/fmt-prev/$rel"
    cp -r "$ECO/$rel" "$OUT/fmt-head/$rel"
  done
  "${PREV[@]}" fmt "$OUT/fmt-prev" > /dev/null
  "${HEAD_BIN[@]}" fmt "$OUT/fmt-head" > /dev/null
  if diff -r "$OUT/fmt-prev" "$OUT/fmt-head" > /dev/null
  then gate "fmt backend-dawn" 0; else gate "fmt backend-dawn" 1; fi
fi

[ "$fail" = 0 ] || exit 1
echo "OK: HEAD agrees with $TAG on the corpus (undeclared-diff check passed)"

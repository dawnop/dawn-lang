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
while [ $# -gt 0 ]; do
  case $1 in
    --corpus) CORPUS=$2; shift 2 ;;
    --check-pin) CHECK_PIN=1; shift ;;
    *) echo "usage: $0 [--corpus site|none] [--check-pin]" >&2; exit 2 ;;
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
ECO_REV=ec8186cecae52c776fa976cf01a83d75795ce47d

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
        "scripts/selfhost-prev-diff.sh to $bump or later and run --corpus site." >&2
      exit 1 ;;
  esac
fi

. scripts/seedjar.sh
PREV=(java -Xss512m -jar "$(seed_jar)")
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
if [ "$CORPUS" = site ]; then
  git init --quiet "$ECO"
  git -C "$ECO" remote add origin "$ECO_URL"
  if ! git -C "$ECO" fetch --quiet --depth 1 origin "$ECO_REV"; then
    echo "ERROR: failed to fetch pinned backend-dawn corpus $ECO_REV" >&2
    exit 1
  fi
  if ! git -C "$ECO" checkout --quiet --detach FETCH_HEAD; then
    echo "ERROR: failed to check out pinned backend-dawn corpus $ECO_REV" >&2
    exit 1
  fi
  ECO_HEAD=$(git -C "$ECO" rev-parse HEAD)
  if [ "$ECO_HEAD" != "$ECO_REV" ]; then
    echo "ERROR: backend-dawn corpus resolved to $ECO_HEAD, expected $ECO_REV" >&2
    exit 1
  fi
  echo "OK   pinned backend-dawn corpus $ECO_REV"
else
  echo "SKIP backend-dawn corpus (--corpus site enables it; nightly.yml passes it)"
fi

# feature discipline: the previous release must compile today's selfhost
"${PREV[@]}" build selfhost "${PREV_STD[@]}" -o "$OUT/head-by-prev.jar" > /dev/null
echo "OK   $TAG compiles HEAD selfhost (seed feature discipline)"

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

for t in site playground packages/web packages/json selfhost examples/projects/calc.dawn \
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
  files=$(find "$ECO/backend-dawn/src" -name '*.dawn' | sort)
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
  cp -r "$ECO/backend-dawn/src" "$OUT/fmt-prev"
  cp -r "$ECO/backend-dawn/src" "$OUT/fmt-head"
  "${PREV[@]}" fmt "$OUT/fmt-prev" > /dev/null
  "${HEAD_BIN[@]}" fmt "$OUT/fmt-head" > /dev/null
  if diff -r "$OUT/fmt-prev" "$OUT/fmt-head" > /dev/null
  then gate "fmt backend-dawn" 0; else gate "fmt backend-dawn" 1; fi
fi

[ "$fail" = 0 ] || exit 1
echo "OK: HEAD agrees with $TAG on the corpus (undeclared-diff check passed)"

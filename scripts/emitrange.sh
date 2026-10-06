# shellcheck shell=bash
#
# The second baseline of the differential gates (docs/emitchange-range-design.md).
#
# WHY A SECOND BASELINE. The four differentials (prev, run, fmt, lsp; and the
# std parameter freeze) compare HEAD with the previous release, and an
# `Emit-Change(<label>)` line anywhere in the commits since that release's tag
# approves the label until the next release. Once any commit has declared
# `lsp`, every later commit in the window can change the LSP output unseen: the
# gate prints NOTE and passes. #124 rejected "a declaration only covers the
# commit that wrote it" because the differential compares N-1 with HEAD, and
# the approved difference is still present at HEAD, so the next commit would
# have gone red. That reasoning holds for one baseline. It does not hold for
# two.
#
# So the window check stays exactly as it was (it also carries the seed feature
# discipline and the cumulative account), and a second leg is added: the
# compiler at the change's own base, against the compiler at HEAD, over HEAD's
# corpus. Both sides compile the same corpus source, so source edits cannot
# produce a difference; only a change to the compiler or the std can. A
# difference is approved only by an Emit-Change line in the commits between
# that base and HEAD, the change's own. The window leg runs the same scripts
# with EMITCHANGE_MODE unset; this leg runs them with EMITCHANGE_MODE=range.
#
# WHICH BASE (the shape of the change differs by event):
#   pull_request   the checkout is a merge ref. base = HEAD^1 (main's tip),
#                  declarations = HEAD^1..HEAD^2 (the PR's own commits). Not
#                  the merge-base: the merge ref holds main commits the PR did
#                  not write, and comparing against the merge-base would charge
#                  their changes to this PR.
#   push           base = the event's `before` (EMITCHANGE_PUSH_BEFORE),
#                  declarations = before..HEAD. A rebase merge keeps messages,
#                  so declarations travel with the commits. A `before` that is
#                  zero or not an ancestor falls back to HEAD^ and says so.
#   anything else  (cluster evidence, a developer's checkout) base =
#                  merge-base(origin/main, HEAD), declarations = base..HEAD.
#   EMITCHANGE_BASE_REF=<rev> overrides all three.
#
# SHORT-CIRCUIT. When the base and HEAD toolchains have the same source and
# bootstrap digests (the launcher's own content stamp, bin/dawn
# DAWN_PRINT_STAMP) the base leg is skipped and says so, printing both
# digests: "looked and identical", not "did not look". The skip is cross-checked
# against git: equal digests while selfhost/, compiler-plan/ or std/ differ
# between the two commits means the digest or the wiring is blind, and that is
# a failure, never a skip.
#
# FAIL-CLOSED WIRING. This leg fails silently if the base is wired to HEAD (it
# would be identical forever) so range_enter refuses a base equal to HEAD and a
# base root whose checked-out commit is not the named base. The self-test (emitchange-selftest.sh) drives each.
#
# NOT COVERED, and said here so it is not a surprise: a push cancelled by a
# later push (ci.yml cancel-in-progress) is never judged by this leg; a PR is
# judged before it lands. Two commits in one PR that declare, change, and then
# change again the same label are one range; the later change rides the
# earlier declaration. Native-backed fmt/lsp differentials (native-cli-diff)
# keep the window leg only.

_er_root() { git rev-parse --show-toplevel; }

# Digest pair of a toolchain root, as one line: "source=<d> bootstrap=<d>".
_er_sig() { # root
  DAWN_PRINT_STAMP=1 "$1/bin/dawn" 2> /dev/null \
    | awk -F= '$1 == "source" { s = $2 } $1 == "bootstrap" { b = $2 }
               END { if (s != "" && b != "") print "source=" s " bootstrap=" b }'
}

# Whether the compiler's own inputs differ between two commits (0 = same).
_er_inputs_changed() { # base head
  git diff --quiet "$1" "$2" -- selfhost compiler-plan std
}

# Pure decision: print "skip" or "run"; return 1 (with a message) when the
# digests and git disagree. Equal digests with changed inputs is the blind case.
range_decide() { # base-sig head-sig inputs-changed(0|1)
  if [ -z "$1" ] || [ -z "$2" ]; then
    echo "FAIL range: a toolchain digest could not be read (base='$1' head='$2')" >&2
    return 1
  fi
  if [ "$1" = "$2" ]; then
    if [ "$3" != 0 ]; then
      echo "FAIL range: the toolchain digests are equal but selfhost/, compiler-plan/ or std/ differ" >&2
      echo "     between the base and HEAD, so the digest is blind or the base is mis-wired" >&2
      echo "     base: $1" >&2
      echo "     head: $2" >&2
      return 1
    fi
    echo skip
    return 0
  fi
  echo run
}

# A base that is HEAD makes the leg an identity test that can never fail.
range_check_base() { # base-sha head-sha base-root-head-sha
  if [ "$1" = "$2" ]; then
    echo "FAIL range: the base is HEAD ($1); the range is empty and every label would read identical" >&2
    return 1
  fi
  if [ "$3" != "$1" ]; then
    echo "FAIL range: the base toolchain root is at ${3:-<unknown>}, not at the named base $1" >&2
    return 1
  fi
  return 0
}

# Resolve EMITCHANGE_BASE (a commit) and EMITCHANGE_RANGE (a git rev range of
# the change's own commits) and say which rule picked them.
range_resolve() {
  local head base parents note=
  head=$(git rev-parse HEAD)
  parents=$(git rev-list --parents -n 1 HEAD | awk '{ print NF - 1 }')
  if [ -n "${EMITCHANGE_BASE_REF:-}" ]; then
    base=$(git rev-parse --verify -q "$EMITCHANGE_BASE_REF^{commit}") || {
      echo "FAIL range: EMITCHANGE_BASE_REF=$EMITCHANGE_BASE_REF is not a commit here" >&2
      return 1
    }
    EMITCHANGE_RANGE="$base..HEAD"
    RANGE_BASIS="explicit base"
  elif [ "${GITHUB_EVENT_NAME:-}" = pull_request ] && [ "$parents" = 2 ]; then
    base=$(git rev-parse HEAD^1)
    EMITCHANGE_RANGE="HEAD^1..HEAD^2"
    RANGE_BASIS="pull_request merge ref: base = first parent, declarations = the PR's commits"
  elif [ "${GITHUB_EVENT_NAME:-}" = push ]; then
    # `github.event.before` cannot be passed in through the workflow (the
    # external runner models no expression in a run: or env:), so read it from
    # the event payload the runner already put on disk.
    local before=${EMITCHANGE_PUSH_BEFORE:-}
    if [ -z "$before" ] && [ -n "${GITHUB_EVENT_PATH:-}" ] && [ -r "$GITHUB_EVENT_PATH" ]; then
      before=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("before",""))' \
        "$GITHUB_EVENT_PATH" 2> /dev/null || true)
    fi
    if [ -n "$before" ] && ! [[ $before =~ ^0+$ ]] \
        && git cat-file -e "$before^{commit}" 2> /dev/null \
        && git merge-base --is-ancestor "$before" HEAD 2> /dev/null; then
      base=$before
      RANGE_BASIS="push: base = the event's before"
    else
      base=$(git rev-parse HEAD^ 2> /dev/null) || {
        echo "FAIL range: push has no usable before and HEAD has no parent" >&2
        return 1
      }
      note="delta base fell back to HEAD^ (before='${before:-}' is zero, missing or not an ancestor)"
      RANGE_BASIS="push: $note"
      echo "NOTE range: $note" >&2
    fi
    EMITCHANGE_RANGE="$base..HEAD"
  else
    local main
    for main in origin/main main; do
      git rev-parse --verify -q "$main^{commit}" > /dev/null && break
      main=
    done
    [ -n "$main" ] || {
      echo "FAIL range: no origin/main or main to take a merge-base with; set EMITCHANGE_BASE_REF" >&2
      return 1
    }
    base=$(git merge-base "$main" HEAD) || {
      echo "FAIL range: no merge-base of $main and HEAD" >&2
      return 1
    }
    if [ "$base" = "$head" ]; then
      base=$(git rev-parse HEAD^)
      RANGE_BASIS="HEAD is already in $main: base = HEAD^"
    else
      RANGE_BASIS="merge-base of $main and HEAD"
    fi
    EMITCHANGE_RANGE="$base..HEAD"
  fi
  EMITCHANGE_BASE=$base
  export EMITCHANGE_BASE EMITCHANGE_RANGE
}

# Build (or reuse) the base toolchain: a detached worktree of the base commit
# whose own bin/dawn builds its own jar from its own sources and seed.
# Idempotent per (checkout, base) so the leg's five scripts build it once.
range_prepare() {
  local root key
  root=$(_er_root)
  key=$(printf '%s %s' "$root" "$EMITCHANGE_BASE" | cksum | cut -d' ' -f1)
  RANGE_DIR=${EMITCHANGE_RANGE_DIR:-${TMPDIR:-/tmp}/emitrange-$key}
  RANGE_BASE_ROOT=$RANGE_DIR/base
  if [ ! -d "$RANGE_BASE_ROOT/.git" ] && [ ! -f "$RANGE_BASE_ROOT/.git" ]; then
    mkdir -p "$RANGE_DIR"
    git worktree prune
    git worktree add --detach --quiet "$RANGE_BASE_ROOT" "$EMITCHANGE_BASE" || return 1
  fi
  # the base is built against the same seed cache, so a seed it shares with
  # HEAD is not downloaded twice
  DAWN_SEED_CACHE=${DAWN_SEED_CACHE:-$root/.dawn/seeds} "$RANGE_BASE_ROOT/bin/dawn" --version > /dev/null \
    || { echo "FAIL range: the base toolchain at $EMITCHANGE_BASE did not build" >&2; return 1; }
  RANGE_BASE_SIG=$(DAWN_SEED_CACHE=${DAWN_SEED_CACHE:-$root/.dawn/seeds} _er_sig "$RANGE_BASE_ROOT")
  "$root/bin/dawn" --version > /dev/null
  RANGE_HEAD_SIG=$(_er_sig "$root")
}

# Entry point for a differential script: after sourcing seedjar.sh, in range
# mode make "the seed" mean the base toolchain, or stop with a skip.
range_enter() {
  [ "${EMITCHANGE_MODE:-}" = range ] || return 0
  local head base_head decision changed
  range_resolve || exit 1
  head=$(git rev-parse HEAD)
  # refuse before paying for a build that could not tell anything
  range_check_base "$EMITCHANGE_BASE" "$head" "$EMITCHANGE_BASE" || exit 1
  range_prepare || exit 1
  base_head=$(git -C "$RANGE_BASE_ROOT" rev-parse HEAD)
  range_check_base "$EMITCHANGE_BASE" "$head" "$base_head" || exit 1
  if _er_inputs_changed "$EMITCHANGE_BASE" "$head"; then changed=0; else changed=1; fi
  decision=$(range_decide "$RANGE_BASE_SIG" "$RANGE_HEAD_SIG" "$changed") || exit 1
  # Acceptance knob (FP-1): run the leg even where the digests say it cannot
  # differ, to show a source-only change does not turn it red. Never set in CI.
  if [ "$decision" = skip ] && [ -n "${EMITCHANGE_RANGE_FORCE:-}" ]; then
    echo "NOTE range: EMITCHANGE_RANGE_FORCE is set; running although the digests are equal"
    decision=run
  fi
  echo "RANGE base ${EMITCHANGE_BASE:0:12} ($RANGE_BASIS); declarations from $EMITCHANGE_RANGE"
  if [ "$decision" = skip ]; then
    echo "SKIP range leg: the base and HEAD toolchains are identical (short-circuit)"
    echo "     base: $RANGE_BASE_SIG"
    echo "     head: $RANGE_HEAD_SIG"
    exit 0
  fi
  echo "     base: $RANGE_BASE_SIG"
  echo "     head: $RANGE_HEAD_SIG"
  export RANGE_TAG=$EMITCHANGE_BASE
  # shellcheck disable=SC2317  # called by the scripts that source this file
  seed_jar() { printf '%s\n' "$RANGE_BASE_ROOT/build/dawn-selfhost.jar"; }
  # shellcheck disable=SC2317
  seed_std_dir() { printf '%s\n' "$RANGE_BASE_ROOT/std"; }
}

# The worktree is registered in .git; remove it when a caller asks (CI discards
# the checkout, a developer runs this after).
range_clean() {
  local d
  for d in "${EMITCHANGE_RANGE_DIR:-}" "${TMPDIR:-/tmp}"/emitrange-*; do
    if [ -z "$d" ] || [ ! -d "$d/base" ]; then continue; fi
    git worktree remove --force "$d/base" 2> /dev/null || true
    rm -rf "$d"
  done
  git worktree prune
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  cd "$(dirname "$0")/.."
  case ${1:-} in
    clean) range_clean ;;
    *) echo "usage: $0 clean   (the leg itself runs inside the differential scripts)" >&2; exit 2 ;;
  esac
fi

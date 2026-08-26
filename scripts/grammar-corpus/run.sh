#!/usr/bin/env bash
# Grammar accept/reject corpus (TEST-04). See README.md in this directory for
# what it does and does not claim.
#
#   ./scripts/grammar-corpus/run.sh
#
# Nothing to re-record: a case carries its own expectation in its header, so
# there is no golden file and no `--record`. checker-corpus, which does have
# one, is the neighbour to reach for when the expectation is a diagnostic
# stream rather than a verdict.
#
# accept/ must parse with no diagnostics. reject/ must be rejected, and for the
# reason its header declares: the leading `# expect: <substring>` lines pin the
# diagnostic sequence, one line per diagnostic, in order. `dawn __parse` prints
# diagnostics as `!`-led lines and exits 0 either way, so the verdict is read
# from the output, not the status.
#
# The sequence is the expectation, not "some line matched" (GOV-06). The old
# harness accepted a case when *any* diagnostic contained the substring, which
# meant a fixture could grow an unrelated leading syntax error, or a precise
# diagnostic could decay into three noisy ones, and the case stayed green --
# the two regressions a reject corpus exists to catch. So a case declares every
# diagnostic it expects: extra ones are a failure, a missing one is a failure,
# and the order is part of the claim.
#
# `--selftest` (and the pass that runs by default) checks the harness itself
# against mutations of a passing case. A checker that has never been shown to
# fail is indistinguishable from one that cannot.
set -euo pipefail
cd "$(dirname "$0")/../.."
here=${GRAMMAR_CORPUS_DIR:-scripts/grammar-corpus}

./bin/dawn --version > /dev/null

# The leading run of `# expect: ` lines, in order. It stops at the first line
# that is not one, so the prose comment every fixture carries below the header
# cannot be mistaken for an expectation.
read_expectations() { # file -> lines on stdout
  while IFS= read -r line; do
    case "$line" in
      "# expect: "*) printf '%s\n' "${line#\# expect: }" ;;
      *) break ;;
    esac
  done < "$1"
}

fail=0
n_ok=0
for f in "$here"/accept/*.dawn; do
  [ -e "$f" ] || continue
  out=$(./bin/dawn __parse "$f" 2>&1)
  if printf '%s\n' "$out" | grep -q '^!'; then
    echo "FAIL accept $(basename "$f") did not parse:" >&2
    printf '%s\n' "$out" | grep '^!' | head -5 >&2
    fail=1
  else
    n_ok=$((n_ok + 1))
  fi
done

n_rej=0
for f in "$here"/reject/*.dawn; do
  [ -e "$f" ] || continue
  name=$(basename "$f")
  mapfile -t want < <(read_expectations "$f")
  if [ "${#want[@]}" -eq 0 ]; then
    echo "FAIL reject $name has no leading '# expect: <substring>' line" >&2
    fail=1
    continue
  fi
  mapfile -t got < <(./bin/dawn __parse "$f" 2>&1 | grep '^!' || true)
  if [ "${#got[@]}" -eq 0 ]; then
    echo "FAIL reject $name parsed cleanly; it must be rejected" >&2
    fail=1
    continue
  fi
  if [ "${#got[@]}" -ne "${#want[@]}" ]; then
    echo "FAIL reject $name reported ${#got[@]} diagnostic(s), the header declares ${#want[@]}" >&2
    echo "     a cascade or a new error is a change to what this case claims; declare every" >&2
    echo "     diagnostic with its own '# expect:' line, in order, or fix the parser" >&2
    printf '     got: %s\n' "${got[@]}" >&2
    fail=1
    continue
  fi
  mismatch=0
  i=0
  while [ "$i" -lt "${#want[@]}" ]; do
    case "${got[$i]}" in
      *"${want[$i]}"*) ;;
      *)
        echo "FAIL reject $name diagnostic $((i + 1)) is not the one declared" >&2
        echo "     want a diagnostic containing: ${want[$i]}" >&2
        echo "     got: ${got[$i]}" >&2
        mismatch=1
        ;;
    esac
    i=$((i + 1))
  done
  if [ "$mismatch" != 0 ]; then
    fail=1
  else
    n_rej=$((n_rej + 1))
  fi
done

if [ "$fail" != 0 ]; then
  echo "FAIL: grammar corpus" >&2
  exit 1
fi
echo "OK: grammar corpus -- $n_ok accepted, $n_rej rejected for the stated reason"

# ---- the harness against itself ----------------------------------------------
# Four mutations of one passing case. Each is a way the corpus could rot, and
# each was green under the pre-GOV-06 harness except the last.
if [ -n "${GRAMMAR_CORPUS_DIR:-}" ]; then
  exit 0
fi

st=$(mktemp -d)
trap 'rm -rf "$st"' EXIT

# The body: `alias` is a keyword, so this reports two diagnostics in a fixed
# order -- a name error, then a cascade at the use of the same word.
body='fn f() -> Int = {
  let alias = 1
  alias
}'
d1='expected a variable name'
d2='expected an expression, found `alias`'

case_dir() { # name; echoes the corpus root
  mkdir -p "$st/$1/accept" "$st/$1/reject"
  printf '%s' "$st/$1"
}

expect_verdict() { # name, want-exit, why
  local root want why status
  root="$st/$1"; want=$2; why=$3
  status=0
  GRAMMAR_CORPUS_DIR="$root" "$0" > "$st/$1.log" 2>&1 || status=$?
  if [ "$status" != "$want" ]; then
    echo "FAIL selftest: $why (harness exited $status, expected $want)" >&2
    sed -n '1,10p' "$st/$1.log" >&2
    fail=1
  else
    echo "OK   selftest: $why"
  fi
}

root=$(case_dir declared)
printf '# expect: %s\n# expect: %s\n%s\n' "$d1" "$d2" "$body" > "$root/reject/c.dawn"
expect_verdict declared 0 "a case that declares both of its diagnostics passes"

root=$(case_dir undeclared)
printf '# expect: %s\n%s\n' "$d1" "$body" > "$root/reject/c.dawn"
expect_verdict undeclared 1 "an undeclared extra diagnostic fails"

root=$(case_dir reordered)
printf '# expect: %s\n# expect: %s\n%s\n' "$d2" "$d1" "$body" > "$root/reject/c.dawn"
expect_verdict reordered 1 "the declared order is part of the claim"

root=$(case_dir unparsable_accept)
printf '%s\n' "$body" > "$root/accept/c.dawn"
expect_verdict unparsable_accept 1 "an accept case that does not parse fails"

[ "$fail" = 0 ] || { echo "FAIL: the grammar corpus harness does not catch what it claims to" >&2; exit 1; }

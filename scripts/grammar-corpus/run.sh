#!/usr/bin/env bash
# Grammar accept/reject corpus (TEST-04). See README.md in this directory for
# what it does and does not claim.
#
#   ./scripts/grammar-corpus/run.sh
#
# accept/ must parse with no diagnostics. reject/ must be rejected, and for the
# reason its first line declares -- `# expect: <substring>` against the
# diagnostic text, so a case that starts failing for a different reason is a
# failure, not a pass. `dawn __parse` prints diagnostics as `!`-led lines and
# exits 0 either way, so the verdict is read from the output, not the status.
set -euo pipefail
cd "$(dirname "$0")/../.."
here=scripts/grammar-corpus

./bin/dawn --version > /dev/null

fail=0
n_ok=0
for f in "$here"/accept/*.dawn; do
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
  want=$(sed -n '1s/^# expect: //p' "$f")
  if [ -z "$want" ]; then
    echo "FAIL reject $(basename "$f") has no '# expect: <substring>' first line" >&2
    fail=1
    continue
  fi
  out=$(./bin/dawn __parse "$f" 2>&1 | grep '^!' || true)
  if [ -z "$out" ]; then
    echo "FAIL reject $(basename "$f") parsed cleanly; it must be rejected" >&2
    fail=1
  elif ! printf '%s\n' "$out" | grep -qF "$want"; then
    echo "FAIL reject $(basename "$f") rejected for the wrong reason" >&2
    echo "     want a diagnostic containing: $want" >&2
    printf '%s\n' "$out" | head -3 | sed 's/^/     got: /' >&2
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

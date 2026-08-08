#!/usr/bin/env bash
# Checker diagnostic golden corpus. See README.md in this directory for what it
# does and does not claim.
#
#   ./scripts/checker-corpus/run.sh            # compare against the goldens
#   ./scripts/checker-corpus/run.sh --record   # regenerate them
#
# Each cases/<name>.dawn (or cases/<name>.d/entry.dawn, for the few that need a
# second module) is checked with `dawn __check`, whose `D` lines carry span,
# text and hint for every diagnostic in emission order. (`dawn check` is the
# human-facing command and stopped printing the dump when it learned to exit
# non-zero; the dump lives only under the hidden name now.)
# cases/<name>.expected holds
# those lines verbatim, minus the directory part of the path. Order is the
# point: `cerr` appends, so the golden fails on a reordering that no assertion
# about individual messages would see.
set -euo pipefail
cd "$(dirname "$0")/../.."
here=scripts/checker-corpus

mode=check
[ "${1:-}" = "--record" ] && mode=record

./bin/dawn --version > /dev/null

TMP=${TMPDIR:-/tmp}/checker-corpus.$$
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

targets=()
for f in "$here"/cases/*.dawn; do
  [ -e "$f" ] || continue
  targets+=("$f")
done
for d in "$here"/cases/*.d; do
  [ -d "$d" ] || continue
  if [ ! -f "$d/entry.dawn" ]; then
    echo "FAIL: $d is a multi-module case with no entry.dawn" >&2
    exit 1
  fi
  targets+=("$d/entry.dawn")
done

fail=0
n=0
n_diags=0
for f in "${targets[@]}"; do
  case "$f" in
    */*.d/entry.dawn) name=$(basename "$(dirname "$f")" .d) ;;
    *)                name=$(basename "$f" .dawn) ;;
  esac
  want="$here/cases/$name.expected"

  # A case that does not parse never reaches the checker (analyze.dawn skips
  # check_module when the module has parse diagnostics), so its golden would
  # silently be a *parser* golden. This corpus is about the checker; a case
  # that stops parsing is a broken case, not a new expectation.
  if ./bin/dawn __parse "$f" 2>&1 | grep -q '^!'; then
    echo "FAIL: $name does not parse -- this corpus only records checker diagnostics" >&2
    ./bin/dawn __parse "$f" 2>&1 | grep '^!' | head -3 >&2
    fail=1
    continue
  fi

  # `D <path> <lo> <hi> <msg> <hint>`; drop the directory so the golden does not
  # depend on where the repository sits.
  ./bin/dawn __check "$f" | grep '^D' | sed 's|\t[^\t]*/\([^\t/]*\)\t|\t\1\t|' > "$TMP/$name.got" || true

  if [ "$mode" = record ]; then
    cp "$TMP/$name.got" "$want"
    n_diags=$((n_diags + $(wc -l < "$want")))
    n=$((n + 1))
    continue
  fi

  if [ ! -f "$want" ]; then
    echo "FAIL: $name has no golden at $want; run --record" >&2
    fail=1
    continue
  fi
  if ! diff -u "$want" "$TMP/$name.got" > "$TMP/$name.d"; then
    echo "FAIL: $name diagnostics changed (- golden, + now):" >&2
    sed -n '3,40p' "$TMP/$name.d" >&2
    fail=1
  else
    n=$((n + 1))
    n_diags=$((n_diags + $(wc -l < "$want")))
  fi
done

# Coverage against the `cerr` call sites themselves: a message that no case
# reaches is invisible to every golden above, so the set of unreached sites is
# a ratchet in both directions -- adding one fails the build, and so does
# covering one without striking it off uncovered.txt.
if [ "$mode" = record ]; then
  echo "recorded $n cases, $n_diags diagnostics"
  ./scripts/checker-corpus/coverage.py --record
  exit 0
fi

[ "$fail" = 0 ] || { echo "FAIL: checker corpus" >&2; exit 1; }

./scripts/checker-corpus/coverage.py
echo "OK: checker corpus -- $n cases, $n_diags diagnostics in the recorded order"

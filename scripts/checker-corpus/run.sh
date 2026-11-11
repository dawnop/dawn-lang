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
selector=
case "${1:-}" in
  --execute-selector)
    selector=${CHECKER_CORPUS_SELECTOR:?missing checker selector}
    case "$selector" in 0|1) ;; *) echo 'FAIL: checker selector out of range' >&2; exit 1 ;; esac
    [ -f "${CHECKER_CORPUS_CASES:?missing checker cases}" ]
    [ -n "${CHECKER_CORPUS_COMPLETED:?missing checker completion log}" ]
    ;;
  --record) mode=record ;;
  '') ;;
  *) exec python3 -I -B "$here/shards.py" "$@" ;;
esac

# Every Cx field says why it is not frame state (#204). The isolated_* cases
# below hold the fields that are; this holds the rest to having an answer.
# No build needed, so it runs first.
if [ "$selector" != 1 ]; then
  ./scripts/checker-corpus/frame-triage.py --selftest
  ./scripts/checker-corpus/frame-triage.py
fi

if [ "$selector" != 1 ]; then ./bin/dawn --version > /dev/null; fi

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
if [ -n "$selector" ]; then
  targets=()
  while IFS= read -r f; do targets+=("$f"); done < "$CHECKER_CORPUS_CASES"
  [ "${#targets[@]}" -gt 0 ] || { echo 'FAIL: empty checker selector' >&2; exit 1; }
fi

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
  if ./bin/dawn __parse "$f" 2>&1 | grep '^!' >/dev/null; then
    echo "FAIL: $name does not parse -- this corpus only records checker diagnostics" >&2
    ./bin/dawn __parse "$f" 2>&1 | grep '^!' | sed -n '1,3p' >&2
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
    if [ -n "$selector" ]; then printf '%s\n' "$name" >> "$CHECKER_CORPUS_COMPLETED"; fi
    echo "PASS checker case $name"
  fi
done

# Coverage against the `cerr` call sites themselves: a message that no case
# reaches is invisible to every golden above, so the set of unreached sites is
# a ratchet in both directions -- adding one fails the build, and so does
# covering one without striking it off uncovered.txt.
if [ -z "$selector" ]; then ./scripts/checker-corpus/coverage.py --selftest; fi
if [ "$mode" = record ]; then
  echo "recorded $n cases, $n_diags diagnostics"
  ./scripts/checker-corpus/coverage.py --record
  exit 0
fi

[ "$fail" = 0 ] || { echo "FAIL: checker corpus" >&2; exit 1; }

if [ -z "$selector" ]; then
  ./scripts/checker-corpus/coverage.py
  echo "OK: checker corpus -- $n cases, $n_diags diagnostics in the recorded order"
else
  echo "OK: checker selector $selector -- $n cases, $n_diags diagnostics in the recorded order; global coverage awaits the complete union"
fi

# Diagnostic bytes alone cannot prove the Int route or finite-width semantics.
if [ "$selector" != 1 ]; then
  if [ -n "$selector" ]; then
    python3 scripts/bitwise-contract/check.py | tee "${CHECKER_CORPUS_BITWISE_LOG:?missing bitwise transcript}"
  else
    python3 scripts/bitwise-contract/check.py
  fi
  if [ -n "$selector" ]; then printf '%s\n' '@bitwise' >> "$CHECKER_CORPUS_COMPLETED"; fi
fi

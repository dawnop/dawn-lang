#!/usr/bin/env bash
# The alias twin: spec 2.6 says `opaque type N = T` and `alias N = T` differ in
# exactly one thing -- 「谁被允许看穿它」 -- and 2.7 says that at run time an
# opaque type *is* its target: same representation, same equality, hash, order
# and rendering. So the two spellings must produce the same output, and that is
# a property a script can check.
#
#   ./scripts/opaque-twin/run.sh              # every case
#   ./scripts/opaque-twin/run.sh str bytes    # just these
#
# Each <case>.dawn is compiled and run twice: once as written, and once with
# `opaque type` textually replaced by `alias`. The two runs must agree.
#
# A compile *error* counts as output, so "rejected both ways" passes -- which
# is the point for the cases that must stay rejected (a Float key, say). The
# one thing allowed to differ is a type *name* inside a diagnostic, since which
# name to print is the identity question opacity exists to answer; those cases
# carry a `# twin-normalise: <opaque name>=<target name>` line.
#
# Why this exists: eleven defects were found on 2026-07-27 by doing this by
# hand, including an `opaque type D = Bytes` whose `==` answered `false` where
# the dictionary answered `true`, and an `opaque type N = String` that rendered
# `"bob"` where a String renders `bob`. Every one of them was a function that
# asked a question about the representation and got the wrapper's answer. The
# rule is easy to state and was demonstrably not transferring: `gen_equality`
# repeated the mistake thirty lines below a comment describing it.
set -uo pipefail
cd "$(dirname "$0")/../.."
DAWN=${DAWN_BIN:-./bin/dawn}
DIR=scripts/opaque-twin
OUT=${TMPDIR:-/tmp}/opaque-twin.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

if [ $# -gt 0 ]; then
  cases=("$@")
else
  cases=()
  for f in "$DIR"/*.dawn; do
    [ -f "$f" ] || continue
    cases+=("$(basename "$f" .dawn)")
  done
  if [ ${#cases[@]} -eq 0 ]; then
    echo "opaque-twin: no cases in $DIR"
    exit 1
  fi
fi

fail=0
for c in "${cases[@]}"; do
  src="$DIR/$c.dawn"
  if [ ! -f "$src" ]; then
    echo "FAIL $c: no such case ($src)"
    fail=1
    continue
  fi

  # the twin, by textual substitution so the two can never drift apart
  sed 's/^opaque type /alias /' "$src" > "$OUT/$c.twin.dawn"

  "$DAWN" run "$src" > "$OUT/$c.opaque" 2>&1
  "$DAWN" run "$OUT/$c.twin.dawn" > "$OUT/$c.alias" 2>&1

  # paths differ between the two runs, and a diagnostic may legitimately name
  # the opaque type where the twin names its target
  norm() {
    local f=$1
    sed -e "s#$OUT/##g" -e "s#$DIR/##g" -e "s#$c\.twin#$c#g" "$f" > "$f.n"
    while read -r line; do
      case "$line" in
        *"# twin-normalise:"*)
          local pair=${line##*# twin-normalise: }
          sed -i "s/\b${pair%%=*}\b/${pair##*=}/g" "$f.n"
          ;;
      esac
    done < "$src"
  }
  norm "$OUT/$c.opaque"
  norm "$OUT/$c.alias"

  if diff -q "$OUT/$c.opaque.n" "$OUT/$c.alias.n" > /dev/null; then
    printf 'ok   %s\n' "$c"
  else
    printf 'FAIL %s -- the opaque and its alias twin disagree\n' "$c"
    diff -u "$OUT/$c.alias.n" "$OUT/$c.opaque.n" | sed 's/^/       /' | head -20
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "OK: every opaque type behaves as its target (${#cases[@]} case(s))"
else
  echo "opaque-twin FAILED"
fi
exit "$fail"

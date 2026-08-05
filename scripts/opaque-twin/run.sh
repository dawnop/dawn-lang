#!/usr/bin/env bash
# The alias twin: spec 2.6 says `opaque type N = T` and `alias N = T` differ in
# exactly one thing -- 「谁被允许看穿它」 -- and 2.7 says that at run time an
# opaque type *is* its target: same representation, same equality, hash, order
# and rendering. So the two spellings must produce the same output, and that is
# a property a script can check.
#
#   ./scripts/opaque-twin/run.sh              # every case
#   ./scripts/opaque-twin/run.sh str bytes    # just these
#   ./scripts/opaque-twin/run.sh --self-check # prove the liveness checks fire
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
# ## Liveness, and why the comparison alone is not a check
#
# Both sides capture stderr, so *any* failure that lands identically on both is
# an empty diff and an `ok`. That is deliberate for a rejection, and it was also
# true of a missing compiler: `DAWN_BIN=/bin/false ./run.sh` printed `ok` five
# times and exited 0. The same hole swallowed a case -- `generic.dawn` called a
# `list.head` that RD-06 removed, so from that rename onwards it compared two
# copies of the same "no exported function" error and reported success.
#
# So agreement is only evidence once the toolchain is known to work, and a case
# is only evidence once its own verdict is known:
#
#   1. `--version` must answer. Catches an absent or unrunnable toolchain.
#   2. A canary program must compile, run and print what it was written to
#      print. Catches a toolchain that answers `--version` and nothing else --
#      the first check is a probe, this one is the thing under test.
#   3. Every case declares whether it runs or is rejected: a case that must stay
#      rejected carries `# twin-rejected: <why>`, and every other case must exit
#      0 on the opaque side. A ratchet both ways, so a case cannot quietly stop
#      compiling *or* quietly start.
#
# `--self-check` drives 1 and 2 with deliberately broken toolchains and requires
# a non-zero exit, since a liveness check nobody has seen fail is a comment.
#
# Why this exists: eleven defects were found on 2026-07-27 by doing this by
# hand, including an `opaque type D = Bytes` whose `==` answered `false` where
# the dictionary answered `true`, and an `opaque type N = String` that rendered
# `"bob"` where a String renders `bob`. Every one of them was a function that
# asked a question about the representation and got the wrapper's answer. The
# rule is easy to state and was demonstrably not transferring: `gen_equality`
# repeated the mistake thirty lines below a comment describing it.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
DAWN=${DAWN_BIN:-./bin/dawn}
DIR=scripts/opaque-twin
OUT=${TMPDIR:-/tmp}/opaque-twin.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# ## --self-check: the broken toolchains this script must refuse
#
# Each stub is a compiler that fails one layer later than the last, so passing
# one stub is not passing the next. No case runs a real compilation here, so
# this costs milliseconds and can sit in the gate list beside the real run.
if [ "${1:-}" = "--self-check" ]; then
  sc_fail=0
  mkdir -p "$OUT/stubs"

  # dead: no output, just a failing exit -- what a missing jar looks like
  cat > "$OUT/stubs/dead" <<'STUB'
#!/bin/sh
exit 1
STUB
  # mute: answers --version, cannot compile anything
  cat > "$OUT/stubs/mute" <<'STUB'
#!/bin/sh
case "$1" in --version) echo "dawn 0.0.0 (stub)" ;; *) echo boom >&2; exit 1 ;; esac
STUB
  # hollow: answers --version, and every run "succeeds" printing nothing --
  # the shape that defeats a liveness check made of exit codes alone
  cat > "$OUT/stubs/hollow" <<'STUB'
#!/bin/sh
case "$1" in --version) echo "dawn 0.0.0 (stub)" ;; *) exit 0 ;; esac
STUB
  chmod +x "$OUT/stubs"/*

  for stub in dead mute hollow; do
    DAWN_BIN="$OUT/stubs/$stub" "$0" > "$OUT/sc.$stub" 2>&1
    rc=$?
    if [ "$rc" -eq 0 ]; then
      printf 'FAIL self-check: a %s toolchain passed opaque-twin (exit 0)\n' "$stub"
      sed 's/^/       /' "$OUT/sc.$stub" | head -10
      sc_fail=1
    else
      printf 'ok   self-check: a %s toolchain is refused (exit %d)\n' "$stub" "$rc"
    fi
  done

  if [ "$sc_fail" -eq 0 ]; then
    echo "OK: opaque-twin refuses a toolchain that cannot compile and run"
  else
    echo "opaque-twin --self-check FAILED"
  fi
  exit "$sc_fail"
fi

# ## Liveness, before any comparison is allowed to mean anything (see header)
if ! "$DAWN" --version > "$OUT/version" 2>&1 || [ ! -s "$OUT/version" ]; then
  echo "opaque-twin: ABORT -- \`$DAWN --version\` did not answer; nothing below would notice" >&2
  sed 's/^/  /' "$OUT/version" >&2
  exit 2
fi

cat > "$OUT/canary.dawn" <<'CANARY'
use std/io

pub fn main() -> Unit !io = println("twin-canary")
CANARY
"$DAWN" run "$OUT/canary.dawn" > "$OUT/canary.out" 2>&1
if [ "$(cat "$OUT/canary.out")" != "twin-canary" ]; then
  echo "opaque-twin: ABORT -- the toolchain cannot compile and run a trivial program," >&2
  echo "  so two identical failures below would read as agreement:" >&2
  sed 's/^/  /' "$OUT/canary.out" >&2
  exit 2
fi

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
  opaque_rc=$?
  "$DAWN" run "$OUT/$c.twin.dawn" > "$OUT/$c.alias" 2>&1

  # The case's own verdict, declared in the case. Without this a case that
  # stops compiling keeps agreeing with itself forever; with it, "rejected" is
  # something a case claims rather than something it drifts into.
  if grep -q '^# twin-rejected' "$src"; then
    if [ "$opaque_rc" -eq 0 ]; then
      printf 'FAIL %s -- declares twin-rejected, but it compiles and runs now\n' "$c"
      printf '       (drop the declaration if that is the intent)\n'
      fail=1
      continue
    fi
  elif [ "$opaque_rc" -ne 0 ]; then
    printf 'FAIL %s -- does not compile and run (exit %d), so its twin proves nothing\n' "$c" "$opaque_rc"
    printf '       (a case that must stay rejected declares: # twin-rejected: <why>)\n'
    sed 's/^/       /' "$OUT/$c.opaque" | head -10
    fail=1
    continue
  fi

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

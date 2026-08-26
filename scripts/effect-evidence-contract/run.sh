#!/usr/bin/env bash
# The end-to-end evidence gate: run the effect corpus on the JVM and hold every
# program to its written answer.
#
#   ./scripts/effect-evidence-contract/run.sh
#   ./scripts/effect-evidence-contract/run.sh --self-test
#
# The golden files are not here: this script runs the programs named in
# roster.txt out of scripts/spike-native/ and holds each to that directory's
# `<name>.expect`. So there is nothing to re-record here either, and the
# hand-written expectation is the one in spike-native. Adding a program to the
# gate is a line in roster.txt.
#
# ## What this owns that nothing else did
#
# Three defects landed on 2026-08-25 (#335, #345, #346) with the same shape:
# `dawn check` accepts the program, and the run panics with `effect evidence
# missing`. A checker corpus cannot see any of them -- the checker is the thing
# that said yes. Only running the program can.
#
# The programs that catch them live in scripts/spike-native/, and until this
# script the *only* gate that ran them was the native differential: a job that
# needs a C compiler and AddressSanitizer, whose own note records observations
# of 281s, 365s, 533s and 557s for an unchanged script, and whose subject is
# whether two backends agree rather than whether the answer is right. An
# evidence regression was therefore visible in exactly one place, late, behind
# a toolchain that has nothing to do with evidence.
#
# This runs the same corpus on the JVM alone: no `cc`, no sanitizer, no second
# backend, about twenty seconds. It is not a replacement for the differential
# -- that gate still owns "the two backends agree", and it is the only one that
# compiles the C -- it is the fast lane for "the answer is right", which is the
# property the three defects broke.
#
# ## And the roster
#
# roster.txt names every entry and says which lane it is in. It is a ratchet in
# both directions: a listed entry that has been deleted fails, and an
# `effect_*.dawn` that is not listed fails. Before it, deleting a corpus file
# was green -- the differential globs its directory, so a corpus that shrinks
# and a corpus that never had the case look exactly alike from inside it.
#
# ## The two lanes
#
# `dawn run` against `<name>.expect` is byte comparison of a transcript, and it
# is the only thing here that can see the *order* two closures ran in: a
# `bracket` release that reads an operation on the way out prints between the
# use closure's line and the value, and no assertion on a returned value can
# tell that apart from a release that never ran.
#
# `dawn test` runs the inline `test` blocks, where an `assert` says what a
# number means. A transcript is a wall of integers whose only witness is the
# transcript it was recorded from; an assertion is written down by a person.
#
# ## Negative controls
#
# `--self-test` puts a synthetic corpus in a temp directory and checks that
# each judgement below can actually go red. The production mutants -- the
# compiler edits that must red this gate, measured -- are in README.md, because
# they change files this script is not allowed to touch.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/effect-evidence-contract"
dawn="$root/bin/dawn"

# The self-test points these at a synthetic tree; nothing else should.
corpus="${EV_CORPUS_DIR:-$root/scripts/spike-native}"
roster="${EV_ROSTER:-$here/roster.txt}"

fail=0

say_fail() {
  printf '  %-34s FAIL\n' "$1"
  shift
  if [ "$#" -gt 0 ]; then printf '%s\n' "$@" | head -30; fi
  fail=1
}

# Run the corpus once. Returns non-zero if anything failed; prints only
# failures, so a green run is quiet.
check_corpus() {
  local work names kinds n name kind prog expect out rc listed f base

  [ -f "$roster" ] || {
    say_fail "roster:present" "no roster at $roster"
    return 1
  }

  work="$(mktemp -d)"
  # shellcheck disable=SC2064 -- $work is wanted at trap-setting time
  trap "rm -rf '$work'" RETURN

  names=()
  kinds=()
  while read -r name kind rest; do
    case "$name" in '' | '#'*) continue ;; esac
    if [ -n "$rest" ]; then
      say_fail "roster:$name" "a roster line is two fields, got: $name $kind $rest"
      continue
    fi
    case "$kind" in
      assertions | transcript) ;;
      *)
        say_fail "roster:$name" "unknown lane \`$kind\` (want assertions or transcript)"
        continue
        ;;
    esac
    for n in ${names[@]+"${names[@]}"}; do
      if [ "$n" = "$name" ]; then say_fail "roster:$name" "listed twice"; fi
    done
    names+=("$name")
    kinds+=("$kind")
  done < "$roster"

  if [ "${#names[@]}" -lt 1 ]; then
    say_fail "roster:nonempty" "the roster names no entries"
    return 1
  fi

  # Every `effect_*.dawn` in the corpus is on the roster. The differential
  # globs this directory, so without this a new evidence program joins it
  # unclassified -- and the point of the roster is that somebody said which
  # lane each case is in.
  for f in "$corpus"/effect_*.dawn; do
    [ -e "$f" ] || continue
    base="$(basename "$f" .dawn)"
    listed=0
    for n in "${names[@]}"; do
      if [ "$n" = "$base" ]; then listed=1; fi
    done
    if [ "$listed" -eq 0 ]; then
      say_fail "roster:$base" "$f is not on the roster; add it as assertions or transcript"
    fi
  done

  n=0
  while [ "$n" -lt "${#names[@]}" ]; do
    name="${names[$n]}"
    kind="${kinds[$n]}"
    n=$((n + 1))
    prog="$corpus/$name.dawn"
    expect="$corpus/$name.expect"

    if [ ! -f "$prog" ]; then
      say_fail "$name:present" "$prog is on the roster and does not exist"
      continue
    fi
    if [ ! -f "$expect" ]; then
      say_fail "$name:expect-file" "$expect does not exist"
      continue
    fi

    # The transcript. stdin is /dev/null for the reason the differential gives:
    # a program that reads the terminal hangs a developer's shell and reads
    # something else in CI.
    out="$work/$name.out"
    rc=0
    "$dawn" run "$prog" > "$out" 2> "$work/$name.err" < /dev/null || rc=$?
    if [ "$rc" -ne 0 ]; then
      say_fail "$name:run" "exit $rc" "$(head -20 "$work/$name.err")"
    elif ! diff -q "$expect" "$out" > /dev/null; then
      say_fail "$name:transcript" \
        "$(diff -u --label expect "$expect" --label actual "$out" | head -25)"
    fi
    # A failed `main` blocks only the transcript, which is the thing that reads
    # its output; the assertions below are a separate program run and answer
    # for themselves. The differential learned this the hard way -- blocking
    # every check on one failed stage hid a whole backend defect behind a JVM
    # crash (#51) -- and the two lanes here are worth keeping independent for
    # the same reason: an evidence hole that panics in `main` and an evidence
    # hole that answers the wrong number are different reports.

    # The assertion lane, and the roster's claim about it. A file that grew
    # `test` blocks while the roster still calls it `transcript` is the roster
    # going stale, which is the one thing a roster may not do.
    if grep -qE '^test[[:space:]]' "$prog"; then
      if [ "$kind" != assertions ]; then
        say_fail "$name:lane" "carries test blocks but the roster calls it $kind"
      fi
      if ! "$dawn" test "$prog" > "$work/$name.test" 2>&1 < /dev/null; then
        say_fail "$name:assertions" "$(tail -20 "$work/$name.test")"
      fi
    elif [ "$kind" = assertions ]; then
      say_fail "$name:lane" "the roster calls it assertions and it has no test block"
    fi
  done

  return 0
}

# ------------------------------------------------------------------ self-test
#
# Each probe below is one judgement in check_corpus, broken on purpose in a
# synthetic corpus. A gate whose checks cannot be shown to fire is a gate that
# reports "I looked" and "there was nothing there" with the same output.
st_tmp=""
self_test() {
  local probe_fail probes tmp
  st_tmp="$(mktemp -d)"
  tmp="$st_tmp"
  trap 'rm -rf "$st_tmp"' EXIT
  probe_fail=0
  probes=0

  seed_corpus() {
    local d="$1"
    mkdir -p "$d/corpus"
    cat > "$d/corpus/effect_probe.dawn" <<'EOF'
use std/io

effect Ask {
  fn ask() -> Int
}

fn thru(f: fn() -> Int !e) -> Int !e = f()

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 41 }
  println(to_string(thru(() => ask() + 1)))
}

test "the probe answers through the slot" {
  with handle Ask { ask() => 41 }
  assert thru(() => ask() + 1) == 42
}
EOF
    printf '42\n' > "$d/corpus/effect_probe.expect"
    printf 'effect_probe assertions\n' > "$d/roster.txt"
  }

  # probe <name> <expected: green|red> <mutation command...>
  probe() {
    local name="$1" want="$2" d rc
    shift 2
    probes=$((probes + 1))
    d="$tmp/$name"
    mkdir -p "$d"
    seed_corpus "$d"
    ( cd "$d" && "$@" )
    rc=0
    (
      corpus="$d/corpus"
      roster="$d/roster.txt"
      fail=0
      check_corpus > "$d/log" 2>&1
      exit "$fail"
    ) || rc=$?
    if [ "$want" = green ] && [ "$rc" -ne 0 ]; then
      printf '  %-34s SELF-TEST FAIL (wanted green, got red)\n' "$name"
      head -20 "$d/log"
      probe_fail=1
    elif [ "$want" = red ] && [ "$rc" -eq 0 ]; then
      printf '  %-34s SELF-TEST FAIL (wanted red, stayed green)\n' "$name"
      probe_fail=1
    fi
  }

  # The positive control. Without it every probe below could be passing for
  # the wrong reason -- a harness that reds on everything reds on mutants too.
  probe clean green true

  probe deleted-entry red rm corpus/effect_probe.dawn
  probe deleted-expect red rm corpus/effect_probe.expect
  probe wrong-answer red sh -c 'printf "43\n" > corpus/effect_probe.expect'
  probe unrostered-file red sh -c 'cp corpus/effect_probe.dawn corpus/effect_other.dawn'
  probe lane-downgraded red sh -c 'printf "effect_probe transcript\n" > roster.txt'
  probe unknown-lane red sh -c 'printf "effect_probe maybe\n" > roster.txt'
  probe assertions-without-tests red \
    sh -c 'sed "/^test /,\$d" corpus/effect_probe.dawn > t && mv t corpus/effect_probe.dawn'

  # The two lanes' own verdicts, each broken where the other cannot see it: an
  # `assert` that is false while the transcript still matches, and a `main`
  # that dies while every assertion still passes. If either lane could be
  # deleted without this self-test noticing, the roster's two words would mean
  # nothing.
  probe failing-assertion red \
    sh -c 'sed "s/== 42/== 43/" corpus/effect_probe.dawn > t && mv t corpus/effect_probe.dawn'
  probe dying-main red \
    sh -c 'sed "s/println(to_string(thru(() => ask() + 1)))/panic(\"gone\")/" corpus/effect_probe.dawn > t && mv t corpus/effect_probe.dawn'

  if [ "$probe_fail" -ne 0 ]; then
    echo "effect evidence self-test FAILED"
    return 1
  fi
  echo "effect evidence self-test ok ($probes probes)"
  return 0
}

if [ "${1:-}" = --self-test ]; then
  self_test
  exit $?
fi

if [ "$#" -gt 0 ]; then
  echo "usage: $0 [--self-test]" >&2
  exit 2
fi

check_corpus || true

if [ "$fail" -ne 0 ]; then
  echo "effect evidence contract FAILED"
  exit 1
fi
echo "effect evidence contract ok"

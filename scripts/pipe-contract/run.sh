#!/usr/bin/env bash
# SYN-05's general pipe: `|>` inserts an argument into whatever call the right
# side already is, and does nothing else.
#
# One assertion set, run against two kinds of compiler. Against the real one
# every assertion must pass: that is the fixture contract, plus the two legs no
# corpus can see (the editor's typed-child mapping under a dotted callee, and
# formatter idempotence over the shapes the pipe newly admits). Against each
# mutant the same set produces a *red set*, which is compared with the recorded
# `matrix.txt`.
#
# Running the whole set against every mutant, rather than just its owner, is
# the point. An assertion two mutants can redden is owned by neither, and that
# property rots silently unless the matrix that established it is the gate.
# `matrix.py` checks it in both directions; see its docstring.
#
# A mutant must compile and answer `--version` before any of this counts:
# "the mutant did not build" proves nothing about a rule.
#
#   ./scripts/pipe-contract/run.sh                        # everything
#   ./scripts/pipe-contract/run.sh --shard 1/2            # CI's split
#   ./scripts/pipe-contract/run.sh --only append-left-argument
#   ./scripts/pipe-contract/run.sh --record               # re-record matrix.txt
#
# Sharding exists because a mutant costs one whole compiler build. Every shard
# runs the fixture contract and validates the whole ownership structure, which
# reads the record and needs no build; the mutants are divided round-robin.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
case "$dawn" in /*) ;; *) dawn="$root/$dawn" ;; esac
here="$root/scripts/pipe-contract"
cases="$here/cases"
record="$here/matrix.txt"
work=$(mktemp -d "${TMPDIR:-/tmp}/pipe-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

shard_i=1
shard_n=1
only=
recording=
case "${1:-}" in
  --shard) shard_i=${2%%/*}; shard_n=${2##*/} ;;
  --only) only=$2 ;;
  --record) recording=1 ;;
esac

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# ---- the assertion set ----------------------------------------------------
#
# `assess <compiler>` prints one `<assertion> PASS|FAIL` line per assertion.
# The real compiler must pass all of them; a mutant's FAIL lines are its red
# set. Every assertion is named, because a red set is only diffable if the
# things in it have names.

# a value case: one shape per file, because a parse error takes its whole file
# down with it and shapes sharing a file cannot own separate assertions
VALUE_CASES=(
  "bare_ctor 7"
  "applied_ctor 7"
  "qualified true"
  "method Some(20)"
  "field_fn 50"
  "nested 3"
  "nullary 42"
  "order ab"
  "assoc 6"
)

EVAL_TRACE='eval callee
eval lhs
eval arg
total=3'

# `same <name> <got> <want>`. Written as an if rather than as a bare `[ ]`
# because this file runs under `set -e`, where a failing test is not a verdict
# but the end of the script.
same() {
  if [ "$2" = "$3" ]; then echo "$1 PASS"; else echo "$1 FAIL"; fi
}

assess() { # compiler
  local c=$1 pair name want got n hover

  for pair in "${VALUE_CASES[@]}"; do
    name=${pair%% *}
    want=${pair#* }
    got=$("$c" run "$cases/$name.dawn" 2>&1 || true)
    same "$name" "$got" "$want"
  done

  # evaluation order, which no type checker can see: the target first, then the
  # arguments in written order, with the left side as the first argument
  got=$("$c" run "$cases/eval_order.dawn" 2>&1 || true)
  same eval_trace "$got" "$EVAL_TRACE"
  same eval_callee_first "$(printf '%s\n' "$got" | head -1)" "eval callee"

  # `f(a: 2)` names the parameter the pipe already filled. Asserted as
  # "refused" and pointedly not by message: see README, the message is what two
  # mutants would share.
  got=$("$c" __check "$cases/named_arg.dawn" 2>&1 | grep -c '^D' || true)
  if [ "$got" -gt 0 ]; then echo "named_arg_refused PASS"; else echo "named_arg_refused FAIL"; fi

  # the right side is a whole or_expr, so `b |> id() || true` pipes into a
  # Bool. Pinned by message: parsed one level tighter the file is still
  # refused, because `|| true` is left dangling.
  got=$("$c" __check "$cases/or_rhs.dawn" 2>&1 |
    grep -cF 'cannot call a value of type Bool' || true)
  same or_rhs_message "$got" 1

  got=$("$c" __check "$cases/module_member.dawn" 2>&1 |
    grep -cF 'has no exported value `starts_with`' || true)
  same module_member "$got" 1

  # both spellings, the written one and the one the pipe writes for you
  got=$("$c" __check "$cases/record_apply.dawn" 2>&1 |
    grep -cF 'must be built with braces' || true)
  same record_apply "$got" 2

  got=$("$c" run "$here/probe" 2>&1 || true)
  same probe_runs "$got" "3 3 7 7"

  hover=$(python3 "$here/hover.py" "$c" "$here/probe" "$here/probe/src/main.dawn" \
    'hover_qcall_written=y => y + 1' \
    'hover_qcall_piped=z => z + 1' \
    'hover_qctor_written=v.One(7)+2' \
    'hover_qctor_piped=v.One()+2' \
    'hover_qctor_arg=One(7)+4' 2>/dev/null || true)
  for pair in "hover_qcall_written=fn(Int) -> Int" \
              "hover_qcall_piped=fn(Int) -> Int" \
              "hover_qctor_written=One(v: Int): Box" \
              "hover_qctor_piped=One(v: Int): Box" \
              "hover_qctor_arg=Int"; do
    name=${pair%%=*}
    want=${pair#*=}
    got=$(printf '%s\n' "$hover" | grep -F "$name	" | cut -f2- || true)
    same "$name" "$got" "\`\`\`dawn $want \`\`\`"
  done

  # The formatter is lexical and was expected not to move. "Expected" is not a
  # check: the pipe admits shapes it never saw, and a formatter that reflows one
  # of them differently on the second pass corrupts source on the second save.
  n=$work/fmt.$RANDOM
  mkdir -p "$n"
  cp "$root/scripts/grammar-corpus/accept/pipe_general.dawn" "$n/once.dawn"
  "$c" fmt "$n/once.dawn" > /dev/null 2>&1 || true
  cp "$n/once.dawn" "$n/twice.dawn"
  "$c" fmt "$n/twice.dawn" > /dev/null 2>&1 || true
  if cmp -s "$n/once.dawn" "$n/twice.dawn" &&
     "$c" fmt --check "$n/once.dawn" > /dev/null 2>&1; then
    echo "fmt_fixpoint PASS"
  else
    echo "fmt_fixpoint FAIL"
  fi
}

reds_of() { # compiler, mutation -> `red <mutation> <assertion>` lines
  local name state
  assess "$1" | while read -r name state; do
    if [ "$state" = FAIL ]; then printf 'red\t%s\t%s\n' "$2" "$name"; fi
  done
}

# ---- the real compiler ----------------------------------------------------

"$dawn" --version > /dev/null

python3 "$here/matrix.py" --selftest > "$work/selftest.out" || {
  cat "$work/selftest.out" >&2
  fail "the matrix checker's own perturbations no longer fail it"
}
echo "OK   matrix.py refuses each perturbation of a record"

baseline=$(assess "$dawn")
printf '%s\n' "$baseline" | while read -r name state; do
  [ "$state" = PASS ] || fail "$name: the real compiler does not satisfy its own contract"
done
printf '%s\n' "$baseline" | sed 's/ PASS$//;s/^/OK   /'

# rules 1 and 2 read the record alone, so a shard that builds four mutants
# still checks the whole ownership structure. Skipped while recording, where
# the record is the thing being rebuilt and `--check` validates it at the end.
if [ -z "$recording" ]; then
  python3 "$here/matrix.py" --validate "$record"
fi

echo "PASS  the pipe inserts an argument into whatever call the right side is"

# ---- mutants --------------------------------------------------------------

build_mutant() { # mutation -> path to a driver that runs the mutant
  local mutation=$1
  local dir="$work/$mutation"
  mkdir -p "$dir"
  cp -R "$root/selfhost" "$dir/selfhost"
  ln -s "$root/packages" "$dir/packages"
  ln -s "$root/compiler-plan" "$dir/compiler-plan"
  python3 "$here/mutate.py" "$mutation" "$dir"
  if ! "$dawn" build "$dir/selfhost" -o "$dir/compiler.jar" > "$dir/build.out" 2>&1; then
    cat "$dir/build.out" >&2
    fail "$mutation mutant did not compile"
  fi
  if ! java -jar "$dir/compiler.jar" --version > "$dir/version.out" 2>&1; then
    cat "$dir/version.out" >&2
    fail "$mutation mutant compiled but could not run"
  fi
  # hover.py execs its first argument, so hand the mutant over as a driver
  printf '#!/bin/sh\nexec java -jar %s/compiler.jar "$@"\n' "$dir" > "$dir/dawn"
  chmod +x "$dir/dawn"
  printf '%s\n' "$dir/dawn"
}

mutants=(
  "refuse-constructor-rhs"
  "drop-method-prepend"
  "append-left-argument"
  "wrap-nested-call"
  "rebuild-arguments-positionally"
  "parse-rhs-at-pipe-level"
  "parse-rhs-one-level-tighter"
  "hoist-left-before-callee"
  "allow-record-apply"
  "route-qualified-name-into-call"
  "drop-lsp-qualified-ctor"
  "drop-lsp-qualified-call-children"
  "negative-control-tighter-than-or"
)

observed="$work/observed.txt"
: > "$observed"

run_mutant() { # mutation
  local mutation=$1 mutant reds
  mutant=$(build_mutant "$mutation")
  reds=$(reds_of "$mutant" "$mutation")
  printf '%s\n' "$reds" >> "$observed"

  if [ "$mutation" = negative-control-tighter-than-or ]; then
    # Recorded, not counted. It builds and answers `--version`, but the bundled
    # std stops parsing, so every assertion is red for a reason that has nothing
    # to do with the pipe. Pinned here so that "it does not build" is a fact on
    # the record rather than a mutant quietly dropped from the list.
    if "$mutant" __check "$cases/nullary.dawn" > "$work/nc.out" 2>&1; then
      cat "$work/nc.out" >&2
      fail "$mutation: the negative control compiled a program after all"
    fi
    # Match the substance, not one release's wording: which module stopped
    # parsing. The surrounding sentence is the std loader's, and that loader
    # says where the std came from, so it changes when the loader learns to.
    grep -Fq 'module `std/cursor` does not parse' "$work/nc.out" || {
      cat "$work/nc.out" >&2
      fail "$mutation: the negative control failed for another reason"
    }
    echo "NOTE  $mutation builds and runs, but compiles nothing: recorded, not counted"
    return 0
  fi

  [ -n "$reds" ] || fail "$mutation: compiled, but reddens nothing at all"
  echo "PASS  $mutation compiles, then reddens $(printf '%s\n' "$reds" | wc -l | tr -d ' ') assertion(s)"
}

n=0
ran=0
for mutation in "${mutants[@]}"; do
  if [ -n "$only" ]; then
    if [ "$mutation" = "$only" ]; then
      run_mutant "$mutation"
      ran=$((ran + 1))
    fi
    n=$((n + 1))
    continue
  fi
  if [ -n "$recording" ] || [ $(( n % shard_n )) -eq $(( shard_i - 1 )) ]; then
    run_mutant "$mutation"
    ran=$((ran + 1))
  fi
  n=$((n + 1))
done

if [ -n "$recording" ]; then
  # only the red sets are re-recorded. Which assertion *owns* a mutant is a
  # design decision and stays a hand edit in matrix.txt, so a recorder can
  # never quietly reassign an owner to whatever the new measurement made
  # convenient.
  python3 "$here/matrix.py" --record "$observed" "$record"
fi

python3 "$here/matrix.py" --check "$observed" "$record"

echo "OK: ${ran} mutant(s) of ${#mutants[@]}, each red set as recorded"

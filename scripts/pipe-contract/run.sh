#!/usr/bin/env bash
# SYN-05's general pipe: `|>` inserts an argument into whatever call the right
# side already is, and does nothing else.
#
# Three halves. The first is the fixture contract, which pins one shape per
# file (a parse error takes its whole file down with it, so shapes that share
# a file cannot own separate assertions). The second is the pair of legs no
# corpus can see: the editor's typed-child mapping under a dotted callee, and
# formatter idempotence over the shapes the pipe newly admits. The third builds
# one mutant compiler per sentence, each of which must *compile and run* before
# its assertion counts; "the mutant did not build" proves nothing about a
# rule.
#
#   ./scripts/pipe-contract/run.sh                        # everything
#   ./scripts/pipe-contract/run.sh --shard 1/2            # CI's split
#   ./scripts/pipe-contract/run.sh --only append-left-argument
#
# Sharding exists because a mutant costs one whole compiler build. Every shard
# runs the fixture and editor contracts; the mutants are divided round-robin.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
case "$dawn" in /*) ;; *) dawn="$root/$dawn" ;; esac
here="$root/scripts/pipe-contract"
cases="$here/cases"
work=$(mktemp -d "${TMPDIR:-/tmp}/pipe-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

shard_i=1
shard_n=1
only=
case "${1:-}" in
  --shard) shard_i=${2%%/*}; shard_n=${2##*/} ;;
  --only) only=$2 ;;
esac

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# ---- reading a compiler ---------------------------------------------------

# stdout of `run`, which is the whole assertion for a value case
run_out() { # compiler, case
  "$1" run "$cases/$2.dawn" 2>&1 || true
}

# every `D` line of a single-file check
diags_of() { # compiler, case
  "$1" __check "$cases/$2.dawn" 2>&1 | grep '^D' || true
}

hover_of() { # compiler
  python3 "$here/hover.py" "$1" "$here/probe" "$here/probe/src/main.dawn" \
    'qualified call, written=y => y + 1' \
    'qualified call, piped=z => z + 1' \
    'qualified ctor, written=v.One(7)+2' \
    'qualified ctor, piped=v.One()+2' \
    'qualified ctor argument=One(7)+4'
}

hover_line() { # hover output, label
  printf '%s\n' "$1" | grep -F "$2	" | cut -f2-
}

# ---- assertions on the real compiler --------------------------------------

expect_run() { # case, expected stdout
  local got
  got=$(run_out "$dawn" "$1")
  [ "$got" = "$2" ] || {
    printf '%s\n' "$got" >&2
    fail "$1: printed something else (wanted \"$2\")"
  }
  echo "OK   $1"
}

expect_diag() { # case, count, message...
  local name=$1 count=$2 got n message
  got=$(diags_of "$dawn" "$name")
  n=$(printf '%s' "$got" | grep -c '^D' || true)
  [ "$n" -eq "$count" ] || {
    printf '%s\n' "$got" >&2
    fail "$name: expected $count diagnostic(s), got $n"
  }
  shift 2
  for message in "$@"; do
    printf '%s\n' "$got" | grep -Fq "$message" || {
      printf '%s\n' "$got" >&2
      fail "$name: missing expected diagnostic: $message"
    }
  done
  echo "OK   $name"
}

"$dawn" --version > /dev/null

# the shapes the pipe admits now that it stopped keeping its own list of them
expect_run bare_ctor 7
expect_run applied_ctor 7
expect_run qualified true
expect_run method "Some(20)"
expect_run field_fn 50
expect_run nested 3
expect_run nullary 42

# where the left side lands, and which expression the right side is
expect_run order ab
expect_run assoc 6

# evaluation order, which the type checker cannot see: target first, then the
# arguments in written order, with the left side as the first argument
eval_trace=$(run_out "$dawn" eval_order)
want_trace='eval callee
eval lhs
eval arg
total=3'
[ "$eval_trace" = "$want_trace" ] || {
  printf '%s\n' "$eval_trace" >&2
  fail "eval_order: the piped call no longer evaluates in the written-out order"
}
echo "OK   eval_order"

# the refusals, which are ordinary call diagnostics reached through a pipe
# rather than a second rulebook living in the parser
expect_diag record_apply 2 'record `Rec` must be built with braces: Rec { ... }'
expect_diag module_member 1 'module `std/str` has no exported value `starts_with`'
expect_diag or_rhs 2 'cannot call a value of type Bool'

# `f(a: 2)` names the parameter the pipe already filled. Asserted as "refused",
# deliberately not by message: see README, the message is what two mutants
# would share.
[ -n "$(diags_of "$dawn" named_arg)" ] ||
  fail "named_arg: a piped call that names a filled parameter was accepted"
echo "OK   named_arg"

# ---- the editor and the formatter -----------------------------------------

probe_out=$("$dawn" run "$here/probe" 2>&1 || true)
[ "$probe_out" = "3 3 7 7" ] || fail "the hover probe project no longer runs: $probe_out"
echo "OK   the hover probe project runs"

hover=$(hover_of "$dawn")
want_hover() { # label, type text
  local got
  got=$(hover_line "$hover" "$1")
  [ "$got" = "\`\`\`dawn $2 \`\`\`" ] || {
    printf '%s\n' "$hover" >&2
    fail "hover: $1 answered [$got], wanted [$2]"
  }
  echo "OK   hover: $1"
}
want_hover "qualified call, written" "fn(Int) -> Int"
want_hover "qualified call, piped" "fn(Int) -> Int"
want_hover "qualified ctor, written" "One(v: Int): Box"
want_hover "qualified ctor, piped" "One(v: Int): Box"
want_hover "qualified ctor argument" "Int"

# The formatter is lexical and was expected not to move. "Expected" is not a
# check: the pipe admits shapes it never saw, and a formatter that reflows one
# of them differently on the second pass corrupts source on the second save.
CORPUS="$root/scripts/grammar-corpus/accept/pipe_general.dawn"
cp "$CORPUS" "$work/once.dawn"
"$dawn" fmt "$work/once.dawn" > /dev/null
cp "$work/once.dawn" "$work/twice.dawn"
"$dawn" fmt "$work/twice.dawn" > /dev/null
cmp -s "$work/once.dawn" "$work/twice.dawn" || {
  diff -u "$work/once.dawn" "$work/twice.dawn" >&2 || true
  fail "fmt is not idempotent over the general-pipe forms"
}
echo "OK   fmt is idempotent over the general-pipe forms"
"$dawn" fmt --check "$work/once.dawn" > /dev/null ||
  fail "the formatted general-pipe corpus does not satisfy --check"
echo "OK   the formatted general-pipe corpus satisfies --check"

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

mutant_run_differs() { # mutation, case, the output it must no longer print
  local mutant got
  mutant=$(build_mutant "$1")
  got=$(run_out "$mutant" "$2")
  [ "$got" != "$3" ] || fail "$1: $2 still prints \"$3\""
  echo "PASS  $1 compiles, then turns $2 red"
}

mutant_drops_diag() { # mutation, case, the diagnostic it must no longer report
  local mutant got
  mutant=$(build_mutant "$1")
  got=$(diags_of "$mutant" "$2")
  if printf '%s' "$got" | grep -Fq "$3"; then
    printf '%s\n' "$got" >&2
    fail "$1: $2 still reports its owning diagnostic"
  fi
  echo "PASS  $1 compiles, then turns $2 red"
}

mutant_accepts() { # mutation, case; a refused program becomes accepted
  local mutant got
  mutant=$(build_mutant "$1")
  got=$(diags_of "$mutant" "$2")
  [ -z "$got" ] || {
    printf '%s\n' "$got" >&2
    fail "$1: $2 is still refused"
  }
  echo "PASS  $1 compiles, then turns $2 red"
}

mutant_hover_differs() { # mutation, label, the answer it must no longer give
  local mutant got
  mutant=$(build_mutant "$1")
  got=$(hover_line "$(hover_of "$mutant")" "$2")
  [ "$got" != "\`\`\`dawn $3 \`\`\`" ] || fail "$1: hover $2 still answers [$3]"
  echo "PASS  $1 compiles, then turns hover \"$2\" red"
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
  "drop-lsp-qualified-call-children"
  "drop-lsp-qualified-ctor"
  "negative-control-tighter-than-or"
)

run_mutant() {
  local mutant first
  case "$1" in
    refuse-constructor-rhs)
      mutant_run_differs "$1" bare_ctor 7 ;;
    drop-method-prepend)
      # `method` and not `qualified`: a module-qualified call is an EMethod
      # too, so both go red here, but only one of them has to be the owner,
      # and `method` is the shape the sentence is about.
      mutant_run_differs "$1" method "Some(20)" ;;
    append-left-argument)
      mutant_run_differs "$1" order ab ;;
    wrap-nested-call)
      mutant_run_differs "$1" nested 3 ;;
    rebuild-arguments-positionally)
      mutant_accepts "$1" named_arg ;;
    parse-rhs-at-pipe-level)
      mutant_run_differs "$1" assoc 6 ;;
    parse-rhs-one-level-tighter)
      # still refused, for an unrelated reason: `|| true` is left dangling and
      # the file stops being a module. So the owner is the *message*, and
      # `named_arg` is the case that has to go the other way.
      mutant_drops_diag "$1" or_rhs 'cannot call a value of type Bool' ;;
    hoist-left-before-callee)
      # only the first line: `append-left-argument` also reorders the trace,
      # and an assertion two mutants can redden is owned by neither.
      mutant=$(build_mutant "$1")
      first=$(run_out "$mutant" eval_order | head -1)
      [ "$first" != "eval callee" ] ||
        fail "$1: the callee is still evaluated before the left side"
      echo "PASS  $1 compiles, then turns the evaluation order red" ;;
    allow-record-apply)
      mutant_drops_diag "$1" record_apply 'record `Rec` must be built with braces' ;;
    route-qualified-name-into-call)
      mutant_drops_diag "$1" module_member 'has no exported value `starts_with`' ;;
    drop-lsp-qualified-call-children)
      # `written` and not `piped`: `drop-method-prepend` reddens the piped
      # spelling as well, because it stops the file from compiling.
      mutant_hover_differs "$1" "qualified call, written" "fn(Int) -> Int" ;;
    drop-lsp-qualified-ctor)
      mutant_hover_differs "$1" "qualified ctor, written" "One(v: Int): Box" ;;
    negative-control-tighter-than-or)
      # Recorded, not counted. It builds and answers `--version`, but the
      # bundled std stops parsing, so every assertion is red for a reason that
      # has nothing to do with the pipe. A mutant only counts if it can compile
      # a program first.
      mutant=$(build_mutant "$1")
      if "$mutant" __check "$cases/nullary.dawn" > "$work/nc.out" 2>&1; then
        cat "$work/nc.out" >&2
        fail "$1: the negative control compiled a program after all"
      fi
      grep -Fq 'bundled std module `std/cursor` does not parse' "$work/nc.out" || {
        cat "$work/nc.out" >&2
        fail "$1: the negative control failed for another reason"
      }
      echo "NOTE  $1 builds and runs, but compiles nothing: recorded, not counted" ;;
    *) fail "no assertion for mutant $1" ;;
  esac
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
  if [ $(( n % shard_n )) -eq $(( shard_i - 1 )) ]; then
    run_mutant "$mutation"
    ran=$((ran + 1))
  fi
  n=$((n + 1))
done

echo "OK: ${ran} mutant(s) of ${#mutants[@]}, each red on its own contract"

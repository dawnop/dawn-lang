#!/usr/bin/env bash
# The DOM bridge, end to end, with no browser.
#
# `dawnc build --target wasm --reactor` produces a reactor: no `_start`, one
# exported `dawn_turn` the host calls per message. This script builds
# examples/projects/tea_dom_counter that way, drives it through a scripted
# session against a recording document stub
# (scripts/wasm-dom-contract/domstub.mjs), and holds the whole transcript --
# what crossed the boundary, which patches came back, what the bridge did to
# the document, and what the document then was -- to expected.txt.
#
# Then it does the same for examples/projects/tea_dom_todo against
# transcript-todo.mjs and expected-todo.txt. Two applications and not one,
# because the counter's child list varies only in length: pairing children by
# index is always right for it, so the cost of unkeyed pairing and the cost
# of lifting a widget's private draft into the model are both invisible
# there. The todo transcript is where those two are numbers. Each case has
# its own mutants, listed at its own section below.
#
# What the counter transcript covers, and why each is there:
#
#   init            the only turn where the whole document crosses
#   two clicks up   one `replace` deep in the tree and one `append` at the
#                   bar; nothing else is mentioned
#   three down      the `truncate` half of the tail ops, and then a
#                   `set-self` at the root when the count crosses zero,
#                   whose payload must not carry the document under it
#   boom            the guest's `update` panics on purpose. The wasm failure
#                   runtime lands it (scripts/wasm-contract is what says that
#                   landing is honest), `serve` answers with an error, the
#                   document is untouched, and the turn after it works
#   stray event     an address that listens for nothing is an error rather
#                   than a silent no-op
#
# The addresses in the request lines are *recovered by the bridge* from the
# element the click landed on -- the script clicks a button it found by its
# label -- so wrong routing shows up as a wrong request line.
#
# Then the mutants, each a real wrong build of a production file, each held
# to the transcript of its case. A mutant that passes means the transcript
# has no teeth about the thing it broke, and this script says so.
#
# Before any of that, two node-only checks driven straight at the bridge, each
# with its own mutants and its own head explaining why it is not a transcript:
# keyed-ops.sh for the three ops neither application here reaches, and props.sh
# for the attribute/property split, whose failure a transcript cannot see.
#
#   ./scripts/wasm-dom-contract/run.sh
#   ./scripts/wasm-dom-contract/run.sh --record        # re-record both transcripts
#   DAWNC_BIN=/path/to/dawnc ./scripts/wasm-dom-contract/run.sh
#
# Needs the same toolchain as scripts/wasm-contract (clang with wasm32-wasi,
# lld, wasi-libc, wasm32 compiler-rt) plus node >= 20. In CI both come from
# the pinned wasi-sdk; see .github/workflows/gates.yml.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

record=0
[ "${1:-}" = "--record" ] && record=1

# ---- the node-only checks, first, because they need nothing but node ------
# Neither application below keys its children, so `insert`/`remove`/`move`
# never appear in either transcript. keyed-ops.sh drives the bridge with the
# patch lists a keyed application would produce, and carries its own mutants.
# props.sh does the same for `value`/`checked`, whose failure mode is a live
# value that has stopped following the model while every byte in the transcript
# stays right.
"$(dirname "${BASH_SOURCE[0]}")/keyed-ops.sh"
"$(dirname "${BASH_SOURCE[0]}")/props.sh"

fail=0
demo="$root/examples/projects/tea_dom_counter"
expected="$here/expected.txt"
todo_demo="$root/examples/projects/tea_dom_todo"
todo_expected="$here/expected-todo.txt"

# ---- toolchain preflight: missing pieces are named, never silent ----------
wasm_cc="${DAWN_WASM_CC:-clang}"
if ! command -v "$wasm_cc" >/dev/null; then
  echo "MISSING: $wasm_cc is not on PATH." >&2
  echo "  Debian/Ubuntu: apt install clang lld wasi-libc libclang-rt-18-dev-wasm32" >&2
  exit 1
fi
if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (it is the wasm host and the bridge's runtime)." >&2
  exit 1
fi

# ---- the driver under test ------------------------------------------------
DAWNC="${DAWNC_BIN:-}"
if [ -z "$DAWNC" ]; then
  echo "building the native driver from selfhost/src/nmain.dawn..."
  "$root/bin/dawn" __emitc "$root/selfhost/src/nmain.dawn" -o "$work/nmain.c"
  "${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" \
    -o "$work/dawnc" "$work/nmain.c" "$root/runtime/c/dawn_rt.c" -lm
  DAWNC="$work/dawnc"
fi
case "$DAWNC" in /*) ;; *) DAWNC="$root/$DAWNC" ;; esac

build() { # <project> <out.wasm>
  "$DAWNC" build --target wasm --reactor "$1" -o "$2" 2>"$work/build.err" || {
    echo "FAIL: the reactor build broke for $1:" >&2
    cat "$work/build.err" >&2
    exit 1
  }
}

# ---- the reactor is a reactor --------------------------------------------
# A command module would export `_start` and abort after one turn. This is
# what makes the whole session below possible, so it is checked rather than
# assumed: nothing else in the transcript can tell the two apart.
build "$demo" "$work/counter.wasm"
build "$todo_demo" "$work/todo.wasm"
exports="$(node --no-warnings -e '
  const fs = require("fs");
  WebAssembly.compile(fs.readFileSync(process.argv[1])).then((m) => {
    console.log(WebAssembly.Module.exports(m).map((e) => e.name).sort().join(","));
  });
' "$work/counter.wasm")"
if [ "$exports" = "_initialize,dawn_turn,memory" ]; then
  echo "OK   reactor: exports are $exports (no _start)"
else
  echo "FAIL: expected a reactor exporting _initialize,dawn_turn,memory; got $exports" >&2
  fail=1
fi

# ---- the transcripts ------------------------------------------------------
node --no-warnings "$here/transcript.mjs" "$work/counter.wasm" >"$work/actual.txt"
node --no-warnings "$here/transcript-todo.mjs" "$work/todo.wasm" >"$work/todo-actual.txt"

if [ "$record" = 1 ]; then
  cp "$work/actual.txt" "$expected"
  cp "$work/todo-actual.txt" "$todo_expected"
  echo "recorded $(wc -l <"$expected") lines into ${expected#"$root"/}"
  echo "recorded $(wc -l <"$todo_expected") lines into ${todo_expected#"$root"/}"
  exit 0
fi

check_transcript() { # <label> <expected> <actual>
  if diff -u "$2" "$3" >"$work/transcript.diff"; then
    echo "OK   $1 transcript: $(wc -l <"$2") lines, byte for byte"
  else
    echo "FAIL: the $1 transcript changed:" >&2
    head -40 "$work/transcript.diff" >&2
    fail=1
  fi
}

check_transcript counter "$expected" "$work/actual.txt"
check_transcript todo "$todo_expected" "$work/todo-actual.txt"

# ---- mutants --------------------------------------------------------------
# Each one edits a copy of the tree, rebuilds what needs rebuilding, and must
# fail the transcript. The edit is checked for having applied: a sed that
# matched nothing would otherwise report a clean tree as a killed mutant,
# which is the way a mutant harness goes quietly blind.
mutant_tree="$work/tree"

reset_tree() {
  rm -rf "$mutant_tree"
  mkdir -p "$mutant_tree"
  # Only what a build and a run read. Copying rather than editing in place is
  # what keeps a killed mutant from being left behind in the working tree.
  cp -r "$root/packages" "$root/examples" "$root/scripts" "$root/std" \
    "$root/selfhost" "$root/runtime" "$root/bin" "$mutant_tree/"
}

# Which case the mutants below are held to. `case_of` switches all four at
# once, because a mutant driven with one case's wasm and another case's
# transcript reds for the wrong reason and reports a covered assertion.
case_project="examples/projects/tea_dom_counter"
case_script="transcript.mjs"
case_expected="$expected"
case_wasm="$work/counter.wasm"

case_of() { # <counter|todo>
  case "$1" in
    counter)
      case_project="examples/projects/tea_dom_counter"
      case_script="transcript.mjs"
      case_expected="$expected"
      case_wasm="$work/counter.wasm"
      ;;
    todo)
      case_project="examples/projects/tea_dom_todo"
      case_script="transcript-todo.mjs"
      case_expected="$todo_expected"
      case_wasm="$work/todo.wasm"
      ;;
    *)
      echo "FAIL: no such transcript case: $1" >&2
      exit 1
      ;;
  esac
}

run_mutant() { # <name> <needs-rebuild: yes|no> <what it breaks>
  local name="$1" rebuild="$2" what="$3" out rc
  if [ "$rebuild" = yes ]; then
    "$DAWNC" build --target wasm --reactor "$mutant_tree/$case_project" \
      -o "$work/$name.wasm" 2>"$work/$name.build-err" || {
      echo "OK   mutant $name goes red (it does not even build): $what"
      return
    }
  else
    cp "$case_wasm" "$work/$name.wasm"
  fi
  set +e
  out="$(node --no-warnings "$mutant_tree/scripts/wasm-dom-contract/$case_script" \
    "$work/$name.wasm" 2>"$work/$name.err")"
  rc=$?
  set -e
  if [ "$rc" != 0 ]; then
    echo "OK   mutant $name goes red (it fails to run): $what"
  elif [ "$out" = "$(cat "$case_expected")" ]; then
    echo "FAIL: mutant $name produced the expected transcript -- $what is not covered" >&2
    fail=1
  else
    echo "OK   mutant $name goes red: $what"
  fi
}

edited() { # <file> -- the sed above must have changed something
  if cmp -s "$root/${1#"$mutant_tree"/}" "$1"; then
    echo "FAIL: a mutant is stale -- its edit matched nothing in ${1#"$mutant_tree"/}" >&2
    fail=1
    return 1
  fi
}

# A1: the patch interpreter gets one op slightly wrong. `truncate` keeps one
# child too many, which no crash and no exception reports: the document is
# simply not the one the model describes, and only the tree line says so.
reset_tree
sed -i 's/while (el.childNodes.length > p.keep)/while (el.childNodes.length > p.keep + 1)/' \
  "$mutant_tree/packages/tea-dom/js/dom.mjs"
edited "$mutant_tree/packages/tea-dom/js/dom.mjs" &&
  run_mutant truncate-off-by-one no "truncate keeps one child too many"

# A2: the patch interpreter loses one op kind outright. `set-self` becomes a
# whole `replace`, which is what a bridge that never read `apply`'s definition
# would do: every element under the address rebuilt, every listener and every
# piece of element state thrown away.
reset_tree
sed -i "s/'set-self': (host, p) => host.setSelf(host.at(p.path), p.node),/'set-self': (host, p) => host.replaceAt(p.path, p.node),/" \
  "$mutant_tree/packages/tea-dom/js/dom.mjs"
edited "$mutant_tree/packages/tea-dom/js/dom.mjs" &&
  run_mutant patch-kind no "set-self interpreted as replace"

# B: the patch interpreter reorders. `diff` emits patches in an order that
# applies without index fixups, and reversing that order is the mutant the
# "in-order application" paragraph of tea_core/diff.dawn is about.
reset_tree
sed -i 's/    for (const patch of patches) {/    for (const patch of patches.slice().reverse()) {/' \
  "$mutant_tree/packages/tea-dom/js/dom.mjs"
edited "$mutant_tree/packages/tea-dom/js/dom.mjs" &&
  run_mutant patch-order no "patches applied in reverse"

# C: events routed to the wrong handler. The address walk pushes instead of
# unshifting, so a click reports its path root-last: the wrong element, and
# for a nested button an address that resolves to nothing at all.
reset_tree
sed -i 's/      path.unshift(i);/      path.push(i);/' \
  "$mutant_tree/packages/tea-dom/js/dom.mjs"
edited "$mutant_tree/packages/tea-dom/js/dom.mjs" &&
  run_mutant event-address no "the recovered address is reversed"

# D: the wire stops honouring locality. `set-self` ships the whole subtree
# instead of the node's own data. Nothing about the *document* changes -- the
# bridge ignores what it is not supposed to read -- so only the reply line
# moves, which is exactly why the reply lines are in the transcript.
reset_tree
sed -i 's|        ("node", enc_self(w)),|        ("node", enc_node(w)),|' \
  "$mutant_tree/packages/tea-dom/src/wire.dawn"
edited "$mutant_tree/packages/tea-dom/src/wire.dawn" &&
  run_mutant setself-payload yes "set-self ships its children"

# E: the failure landing is taken away. `serve` calls `turn` directly, so the
# application's deliberate panic is nobody's to catch: on wasm it unwinds out
# of `dawn_turn` and the host is left holding an aborted instance. This is the
# run-level mutant, and the one that says knife 3's failure runtime is what
# the `boom` line depends on.
reset_tree
python3 - "$mutant_tree/packages/tea-dom/src/reactor.dawn" <<'MUTANT_E'
import sys

path = sys.argv[1]
lines = open(path).read().split("\n")
start = next(
    i for i, l in enumerate(lines) if l.strip().startswith("match catch_panic(() => turn(")
)
indent = " " * (len(lines[start]) - len(lines[start].lstrip()))
end = next(i for i in range(start + 1, len(lines)) if lines[i] == indent + "}")
lines[start : end + 1] = [
    indent + "io.println(turn(line, init, encode, decode, update, view))"
]
open(path, "w").write("\n".join(lines))
MUTANT_E
edited "$mutant_tree/packages/tea-dom/src/reactor.dawn" &&
  run_mutant no-catch yes "the panic catch at the boundary is removed"

# ---- mutants for the todo case -------------------------------------------
# Both live in the application rather than in the bridge, because what the
# second transcript adds is application shape the counter has none of: a
# focus that decides where a keystroke lands, and a filter that decides which
# rows exist. A bridge mutant is already covered above and would red both
# transcripts; these red only this one, which is the evidence that the second
# case is carrying assertions of its own.
case_of todo

# F: the lifted local state stops being routed. Every keystroke feeds the
# composer's draft, so the row editor can never be typed into -- the exact
# failure that having no local state at all is supposed to make impossible,
# and the reason `focus` is a field.
reset_tree
sed -i 's/edit: m.edit ++ c/draft: m.draft ++ c/' \
  "$mutant_tree/examples/projects/tea_dom_todo/src/todo.dawn"
edited "$mutant_tree/examples/projects/tea_dom_todo/src/todo.dawn" &&
  run_mutant todo-focus yes "a keystroke ignores the focus"

# G: the filter stops filtering. `done` shows every row, so the list the
# reconciler is handed is the wrong length and the turn that empties it never
# empties it.
reset_tree
sed -i 's/    Done -> list.filter(m.todos, t => t.done)/    Done -> m.todos/' \
  "$mutant_tree/examples/projects/tea_dom_todo/src/todo.dawn"
edited "$mutant_tree/examples/projects/tea_dom_todo/src/todo.dawn" &&
  run_mutant todo-filter yes "the done filter admits everything"

if [ "$fail" != 0 ]; then exit 1; fi
echo "wasm dom contract ok (2 transcripts + 8 mutants, plus the keyed ops and the props)"

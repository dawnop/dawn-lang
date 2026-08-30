#!/usr/bin/env bash
# The direct-style collector, and the mutants that say its assertions are
# looking.
#
#   ./scripts/wasm-dom-contract/collect.sh
#
# A `Node`'s child list can be built by a collector: a body performs `emit`
# once per child and a `with handle` with a state cell accumulates them
# (docs/handler-state-design.md). scripts/wasm-dom-contract/collect is the
# fixture that does it, and this script holds it to the three verdicts §7.3 of
# that document pins.
#
# It is here rather than in a gate of its own because it is about the trees
# the transcripts are made of, and it runs *before* run.sh builds anything
# because it needs bin/dawn and nothing else: no wasm toolchain, no node. The
# three verdicts are asserted on pure `tea_core` values.
#
# Why the transcripts cannot stand in for it: a transcript records what
# crossed the boundary, and the boundary is handed a finished node. How that
# node's children were *constructed* is invisible to the encoder
# (tea-block-children-design.md §7 says exactly this), so a collector that
# reverses its children, or lets an inner container's children leak into its
# parent, is caught by the transcripts only on the shapes the two applications
# happen to build, and by nothing at all on the shapes they do not.
#
# Each mutant edits a copy of the fixture's collector and must turn the
# assertions red. The edit is checked for having applied: a sed that matched
# nothing would report a clean tree as a killed mutant, which is how a mutant
# harness goes quietly blind.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

dawn="${DAWN_BIN:-$root/bin/dawn}"
if [ ! -x "$dawn" ]; then
  echo "MISSING: $dawn is not executable (this leg compiles Dawn, not wasm)." >&2
  exit 1
fi

# The fixture is copied rather than run in place, because every mutant below
# is an edit to it. Its `[deps]` are relative to where it sits, so they are
# rewritten to absolute paths into the real tree: the packages are read, never
# edited, and copying them too would make bin/dawn rebuild the toolchain once
# per mutant.
plant() { # <dir>
  rm -rf "$1"
  mkdir -p "$(dirname "$1")"
  cp -r "$here/collect" "$1"
  sed -i "s|\"\.\./\.\./\.\./packages/|\"$root/packages/|" "$1/dawn.toml"
}

fixture="$work/base"
plant "$fixture"

if "$dawn" test "$fixture" >"$work/base.txt" 2>&1; then
  echo "OK   collector: $(grep -c '^PASS  collect ::' "$work/base.txt") assertions"
else
  echo "FAIL: the collector assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

fail=0

# name | sed program over the fixture's src/collect.dawn
mutants=(
  # Verdict two, "emit order is child order": the cell prepends instead of
  # appending. Every child is still there and the element is still one
  # element, so nothing about the shape of the tree moves; only the order
  # does, and only an assertion that compares whole lists sees it.
  'emit-order-reversed|s|acc = acc ++ \[w\]|acc = [w] ++ acc|'
  # Verdict one, "a nested container collects its own children": the
  # container stops installing a collector of its own and forwards its body's
  # children to whoever installed the outer one. The inner children arrive in
  # the parent, flattened, and the `ul` that should have held them is empty.
  'nested-leaks-into-outer|s|  emit(el(tag, kids: kids))|  for w in kids { emit(w) }|'
  # The other half of the same verdict: the container installs its collector,
  # reads it, and then drops what it read. Nothing leaks upward this time,
  # the children simply cease to exist -- which is what an assertion on the
  # outer list alone would not distinguish from the mutant above.
  'nested-drops-its-kids|s|  emit(el(tag, kids: kids))|  emit(el(tag, kids: []))|'
  # Verdict three, "a false condition emits nothing at all": the branch runs
  # whatever the condition said. This is the mutant that says the assertion
  # on the false case has teeth, since a collector that emitted a placeholder
  # for an untaken branch would look identical from inside the true case.
  'false-branch-emits|s|    if show {|    if true {|'
  # And the cell itself: a collector that starts from something nobody
  # emitted. Held separately because the three verdicts above are all about
  # what a body says, and this one is about the cell answering with more than
  # it was told.
  'cell-seeded|s|var acc: List\[Node\[Int\]\] = \[\]|var acc: List[Node[Int]] = [text("ghost")]|'
)

holes=0
killed=0
for m in "${mutants[@]}"; do
  name="${m%%|*}"
  prog="${m#*|}"
  tree="$work/$name"
  plant "$tree"
  target="$tree/src/collect.dawn"
  before="$(md5sum "$target")"
  sed -i "$prog" "$target"
  if [ "$before" = "$(md5sum "$target")" ]; then
    echo "NOT APPLIED: $name (the sed matched nothing; the mutant is vacuous)"
    holes=$((holes + 1))
    continue
  fi
  if "$dawn" test "$tree" >"$work/$name.txt" 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} collector mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "collector ok ($killed/${#mutants[@]} mutants killed)"

#!/usr/bin/env bash
# Which module's copy of a dictionary a program links against (issue #69).
#
#   ./scripts/dict-owner-contract/run.sh
#
# A translation unit defines a dictionary once, and every module that needs
# `Eq[String]` lowered its own copy of the slot bridge -- identical but for the
# owner the symbol is mangled from. The emitter used to keep whichever copy it
# met first, and it meets them in the order `std/modules.txt` lists modules in.
# The first std module to materialise `Eq[String]` is `std/gpu`, so a user
# program's `==` on strings linked against `std/gpu`'s bridge and, once std is
# pruned per program (docs/std-pruning-design.md), pinned an 8,000-line module.
#
# `reach.dict_owners` picks the smallest owner instead. Arbitrary, but the same
# arbitrary answer every time, and no reordering of `modules.txt` can move it.
#
# Two checks, because either one alone can be satisfied by giving up:
#
#   * the dictionary table is byte-identical with `gpu` moved earlier in
#     `modules.txt` -- load order does not decide the owner;
#   * that table is not empty, and the owner it names is the program's own
#     module rather than a std module -- pruning did not simply drop every
#     dictionary, and the defect's own symptom is gone.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/dict-owner-contract"
prog="$here/eq_string.dawn"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# `gpu` last is the tree's order; `gpu` straight after `map` is the earliest
# position its own dependencies (bytes, list, map, narrow) allow. Anything
# illegal makes `__emitc` fail below rather than pass quietly.
mkdir -p "$work/std-late" "$work/std-early"
cp "$root"/std/*.dawn "$work/std-late/"
cp "$root"/std/*.dawn "$work/std-early/"
cp "$root/std/modules.txt" "$work/std-late/modules.txt"
awk '
  { line = $0 }
  line == "gpu" { next }
  { print line }
  line == "map" { print "gpu" }
' "$root/std/modules.txt" > "$work/std-early/modules.txt"

if cmp -s "$work/std-late/modules.txt" "$work/std-early/modules.txt"; then
  echo "FAIL: the reordered module list is the original one; this gate would prove nothing" >&2
  exit 1
fi

for order in late early; do
  "$root/bin/dawn" __emitc --std "$work/std-$order" "$prog" -o "$work/$order.c" > /dev/null
  grep '^static dawn_dict ' "$work/$order.c" > "$work/$order.dicts" || true
done

if ! diff -u "$work/late.dicts" "$work/early.dicts" > "$work/d.txt"; then
  cat "$work/d.txt" >&2
  echo "FAIL: moving std/gpu in modules.txt changed the emitted dictionary table" >&2
  exit 1
fi

if [ ! -s "$work/late.dicts" ]; then
  echo "FAIL: the program emitted no dictionary at all, so the check above is vacuous" >&2
  exit 1
fi

if grep -q 'dawn_std_2' "$work/late.dicts"; then
  cat "$work/late.dicts" >&2
  echo "FAIL: the dictionary is filled from a std module's copy of the bridge" >&2
  echo "      (issue #69: the program's own copy is the one to keep)" >&2
  exit 1
fi

echo "PASS  dictionary owner: $(wc -l < "$work/late.dicts" | tr -d ' ') dictionary line(s), unmoved by std/gpu's position"

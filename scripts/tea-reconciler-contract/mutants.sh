#!/usr/bin/env bash
# The negative control for the tea reconciler contract.
#
#   ./scripts/tea-reconciler-contract/mutants.sh
#
# A differential that is green over 484 pairs proves nothing unless a wrong
# reconciler would have turned it red, and that is not hypothetical here: the
# `setself-keeps-donor-kids` mutant below survived the first version of the
# corpus, because every in-place update in it happened to be followed only by
# idempotent `Replace` patches. The corpus grew a pair to kill it. Nothing but a
# mutant would have said so.
#
# Each mutant breaks one production line and the run must fail. A mutant that
# stays green is a hole in the corpus and is reported as one; a `sed` that
# matches nothing is reported too, since a mutant that never applied is a green
# run that means nothing at all -- the failure mode this file exists to catch,
# arriving through the back door.
#
# Every file is restored after every mutant, including on failure. The restore
# is from a copy taken here rather than from git, so running this over a dirty
# tree gives the tree back as it was and not as it was last committed.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root" || exit 1

targets=(
  packages/tea-core/src/diff.dawn
  packages/tea-core/src/walk.dawn
  packages/tea-term/src/widget.dawn
)

pristine="$(mktemp -d)"
for t in "${targets[@]}"; do
  mkdir -p "$pristine/$(dirname "$t")"
  cp "$t" "$pristine/$t"
done

restore() {
  for f in "${targets[@]}"; do cp "$pristine/$f" "$f"; done
}
cleanup() {
  restore
  rm -rf "$pristine"
}
trap cleanup EXIT

# The suites a mutant has to get past: the two packages' own blocks, and the
# differential against the pre-split reconciler. Neither alone is enough --
# the differential never reaches route/step, and the package blocks have no
# oracle but themselves.
check() {
  ./bin/dawn test packages/tea-term > /dev/null 2>&1 \
    && ./bin/dawn test scripts/tea-reconciler-contract/oracle > /dev/null 2>&1
}

# name | file | sed program
mutants=(
  # The reconciler: order, the three answers of `relate`, the tail ops, the
  # equality shortcut, and the descent.
  'patch-order-swapped|packages/tea-core/src/diff.dawn|s|\[sp\] ++ diff_kids(kids(old), kids(new), path, 0, \[\])|diff_kids(kids(old), kids(new), path, 0, []) ++ [sp]|'
  'unrelated-becomes-inplace|packages/tea-core/src/diff.dawn|s|op: Replace(w: new)|op: SetSelf(w: new)|'
  'common-prefix-off-by-one|packages/tea-core/src/diff.dawn|s|if i < common {|if i < common - 1 {|'
  'no-equality-shortcut|packages/tea-core/src/diff.dawn|s|if old == new {|if false {|'
  'setself-keeps-donor-kids|packages/tea-core/src/diff.dawn|s|SetSelf(d) -> rekid(d, kids(w))|SetSelf(d) -> d|'
  'setself-args-swapped|packages/tea-core/src/diff.dawn|s|SetSelf(d) -> rekid(d, kids(w))|SetSelf(d) -> rekid(w, kids(d))|'
  'append-drops-existing|packages/tea-core/src/diff.dawn|s|AppendKids(ws) -> rekid(w, kids(w) ++ ws)|AppendKids(ws) -> rekid(w, ws)|'
  'truncate-off-by-one|packages/tea-core/src/diff.dawn|s|TruncateKids(keep) -> rekid(w, list.take(kids(w), keep))|TruncateKids(keep) -> rekid(w, list.take(kids(w), keep + 1))|'
  'descend-wrong-index|packages/tea-core/src/diff.dawn|s|let i = path\[0\]|let i = path[0] + 1|'
  'descend-loses-siblings|packages/tea-core/src/diff.dawn|s|rekid(w, list.take(ks, i) ++ \[patched\] ++ list.drop(ks, i + 1))|rekid(w, [patched])|'

  # The walk, which routing is written on.
  'walk-visits-children-first|packages/tea-core/src/walk.dawn|s|kids_go(kids(w), path, 0, f(acc, w, path), f)|f(kids_go(kids(w), path, 0, acc, f), w, path)|'
  'walk-path-not-extended|packages/tea-core/src/walk.dawn|s|go(ks\[i\], path ++ \[i\], acc, f)|go(ks[i], path, acc, f)|'

  # The vocabulary's side of the contract. Core is only ever as right as the
  # three functions it delegates to, so they get mutants of their own.
  'kids-drops-the-styled-child|packages/tea-term/src/widget.dawn|s|      Styled(_, c) -> \[c\]|      Styled(_, c) -> []|'
  'rekid-styled-loses-its-style|packages/tea-term/src/widget.dawn|s|Styled(style: s, child: ks\[0\])|Styled(style: Plain, child: ks[0])|'
  'rekid-styled-not-total|packages/tea-term/src/widget.dawn|s|Styled(s, _) -> if list.is_empty(ks) { w } else { Styled(style: s, child: ks\[0\]) }|Styled(s, _) -> Styled(style: s, child: ks[0])|'
  'relate-ignores-the-style|packages/tea-term/src/widget.dawn|s|Styled(s2, _) -> if s1 == s2 { Same } else { SelfDiffers }|Styled(s2, _) -> Same|'
  'relate-restyles-instead-of-recursing|packages/tea-term/src/widget.dawn|s|Styled(s2, _) -> if s1 == s2 { Same } else { SelfDiffers }|Styled(s2, _) -> if s1 == s2 { SelfDiffers } else { Same }|'
  'relate-diffs-rows-against-columns|packages/tea-term/src/widget.dawn|s|          Row(_) -> Same|          Row(_) -> Same\n          Column(_) -> Same|'
  'relate-descends-into-a-leaf|packages/tea-term/src/widget.dawn|s|      Text(_) -> Unrelated|      Text(_) -> Same|'
)

holes=0
killed=0
for m in "${mutants[@]}"; do
  name="${m%%|*}"
  rest="${m#*|}"
  file="${rest%%|*}"
  prog="${rest#*|}"
  restore
  before="$(md5sum "$file")"
  sed -i "$prog" "$file"
  after="$(md5sum "$file")"
  if [ "$before" = "$after" ]; then
    echo "NOT APPLIED: $name (the sed matched nothing; the mutant is vacuous)"
    holes=$((holes + 1))
    continue
  fi
  if check; then
    echo "HOLE: $name survived, the suites do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

restore
if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} mutant(s) unaccounted for" >&2
  exit 1
fi
echo "PASS  $killed/${#mutants[@]} mutant(s) killed"

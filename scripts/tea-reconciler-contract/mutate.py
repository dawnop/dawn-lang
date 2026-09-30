#!/usr/bin/env python3
"""Apply one tea reconciler mutant's edit to a repository tree.

    scripts/tea-reconciler-contract/mutate.py <mutant> <tree-root>

mutants.sh used to carry each mutant as a sed program and count it applied
when the file's md5 changed: at least one match, not exactly one. A pattern
that came to match twice would mutate both copies, and a respelled line was
noticed only when contracts-2 reached that mutant (#277). Declared here, in
the registry shape mutation-anchor-preflight.py discovers, the same edits
are literal and exactly-once: mutants.sh applies one mutant at a time to the
checkout it restores afterwards, and the preflight proves every anchor before
any build.

Each literal is its sed pattern with the bracket escapes dropped; `.` in
those patterns only ever stood for itself, and the one replacement with a
`\\n` is a real newline here. The keys are mutants.sh's names, in its order;
why each mutant exists stays beside it below. A mutant is an ordered tuple of
edits, each applied to the text the previous one left, with paths relative
to the tree root.
"""

from pathlib import Path
import sys

DIFF = "packages/tea-core/src/diff.dawn"
WALK = "packages/tea-core/src/walk.dawn"
WIDGET = "packages/tea-term/src/widget.dawn"
NODE = "packages/tea-dom/src/node.dawn"

MUTATIONS = {
    # The reconciler: order, the three answers of `relate`, the tail ops, the
    # equality shortcut, and the descent.
    "patch-order-swapped": ((
        DIFF,
        '[sp] ++ diff_kids(kids(old), kids(new), path, 0, [])',
        'diff_kids(kids(old), kids(new), path, 0, []) ++ [sp]',
    ),),
    "unrelated-becomes-inplace": ((
        DIFF,
        'op: Replace(w: new)',
        'op: SetSelf(w: new)',
    ),),
    "common-prefix-off-by-one": ((
        DIFF,
        'if i < common {',
        'if i < common - 1 {',
    ),),
    "no-equality-shortcut": ((
        DIFF,
        'if old == new {',
        'if false {',
    ),),
    "setself-keeps-donor-kids": ((
        DIFF,
        'SetSelf(d) -> rekid(d, kids(w))',
        'SetSelf(d) -> d',
    ),),
    "setself-args-swapped": ((
        DIFF,
        'SetSelf(d) -> rekid(d, kids(w))',
        'SetSelf(d) -> rekid(w, kids(d))',
    ),),
    "append-drops-existing": ((
        DIFF,
        'AppendKids(ws) -> rekid(w, kids(w) ++ ws)',
        'AppendKids(ws) -> rekid(w, ws)',
    ),),
    "truncate-off-by-one": ((
        DIFF,
        'TruncateKids(keep) -> rekid(w, list.take(kids(w), keep))',
        'TruncateKids(keep) -> rekid(w, list.take(kids(w), keep + 1))',
    ),),
    "descend-wrong-index": ((
        DIFF,
        'let i = path[0]',
        'let i = path[0] + 1',
    ),),
    "descend-loses-siblings": ((
        DIFF,
        'rekid(w, list.take(ks, i) ++ [patched] ++ list.drop(ks, i + 1))',
        'rekid(w, [patched])',
    ),),

    # The walk, which routing is written on.
    "walk-visits-children-first": ((
        WALK,
        'kids_go(kids(w), path, 0, f(acc, w, path), f)',
        'f(kids_go(kids(w), path, 0, acc, f), w, path)',
    ),),
    "walk-path-not-extended": ((
        WALK,
        'go(ks[i], path ++ [i], acc, f)',
        'go(ks[i], path, acc, f)',
    ),),

    # The vocabulary's side of the contract. Core is only ever as right as the
    # three functions it delegates to, so they get mutants of their own.
    "kids-drops-the-styled-child": ((
        WIDGET,
        '      Styled(_, c) -> [c]',
        '      Styled(_, c) -> []',
    ),),
    "rekid-styled-loses-its-style": ((
        WIDGET,
        'Styled(style: s, child: ks[0])',
        'Styled(style: Plain, child: ks[0])',
    ),),
    "rekid-styled-not-total": ((
        WIDGET,
        'Styled(s, _) -> if list.is_empty(ks) { w } else { Styled(style: s, child: ks[0]) }',
        'Styled(s, _) -> Styled(style: s, child: ks[0])',
    ),),
    "relate-ignores-the-style": ((
        WIDGET,
        'Styled(s2, _) -> if s1 == s2 { Same } else { SelfDiffers }',
        'Styled(s2, _) -> Same',
    ),),
    "relate-restyles-instead-of-recursing": ((
        WIDGET,
        'Styled(s2, _) -> if s1 == s2 { Same } else { SelfDiffers }',
        'Styled(s2, _) -> if s1 == s2 { SelfDiffers } else { Same }',
    ),),
    "relate-diffs-rows-against-columns": ((
        WIDGET,
        '          Row(_) -> Same',
        '          Row(_) -> Same\n          Column(_) -> Same',
    ),),
    "relate-descends-into-a-leaf": ((
        WIDGET,
        '      Text(_) -> Unrelated',
        '      Text(_) -> Same',
    ),),

    # Keyed pairing. Every one of these is a wrong answer that still type
    # checks and still terminates, and most of them still round-trip on some
    # inputs -- which is why the corpus has hand-picked shapes as well as a
    # generated sweep.
    "keyed-never-pairs": ((
        DIFF,
        '  if list.is_empty(xs) { unkeyable } else { keys_go(xs, 0, []) }',
        '  unkeyable',
    ),),
    "keyed-allows-duplicates": ((
        DIFF,
        '    if len(list.unique(acc)) == len(acc) { Some(acc) } else { None }',
        '    Some(acc)',
    ),),
    "keyed-drops-ascending": ((
        DIFF,
        '      drops(ok, nk, j - 1, acc ++ [rm])',
        '      drops(ok, nk, j - 1, [rm] ++ acc)',
    ),),
    "keyed-place-skips-moves": ((
        DIFF,
        '        if p == t {',
        '        if p >= t {',
    ),),
    "keyed-move-ends-swapped": ((
        DIFF,
        '          let mv: Op[W] = MoveKid(from: p, to: t)',
        '          let mv: Op[W] = MoveKid(from: t, to: p)',
    ),),
    "keyed-descends-at-the-old-index": ((
        DIFF,
        '        descend(old, ok, new, nk, t + 1, acc ++ diff_at(old[o], new[t], path ++ [t]), path)',
        '        descend(old, ok, new, nk, t + 1, acc ++ diff_at(old[o], new[t], path ++ [o]), path)',
    ),),
    "keyed-phases-swapped": ((
        DIFF,
        '  structural ++ descend(old, ok, new, nk, 0, [], path)',
        '  descend(old, ok, new, nk, 0, [], path) ++ structural',
    ),),
    "keyed-insert-ignores-its-position": ((
        DIFF,
        '      let i = if at < 0 { 0 } else if at > len(ks) { len(ks) } else { at }',
        '      let i = 0',
    ),),
    # A different delimiter for the two whose subject contains `||`.
    "keyed-move-is-not-total": ((
        DIFF,
        '      if from < 0 || from >= len(ks) || to < 0 || to >= len(ks) {',
        '      if false {',
    ),),

    # The vocabulary's half of keying: the key is part of a pair's fate, or a
    # list that fell back to indices pairs two different elements as one.
    "relate-ignores-the-key": ((
        NODE,
        '            if t1 != t2 || k1 != k2 {',
        '            if t1 != t2 {',
    ),),
    "key-is-not-carried-through-rekid": ((
        NODE,
        '      Elem(t, p, o, _, k) -> Elem(tag: t, props: p, on: o, kids: ks, key: k)',
        '      Elem(t, p, o, _, _) -> Elem(tag: t, props: p, on: o, kids: ks, key: None)',
    ),),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutant> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()

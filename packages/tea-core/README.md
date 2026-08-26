# packages/tea-core

The vocabulary-free half of the Elm architecture: what a tree owes a
reconciler, the reconciler, the walk, `trait App`, and subscriptions. Nothing
here names a widget, a style, a tag or a terminal, and nothing here performs an
effect: the one row written in this package is `update`'s `!M.E`, which is the
impl's to bind and is `!()` in every impl there is today. The terminal's
vocabulary is `packages/tea-term`.

```dawn
use tea_core/tree.{Tree, Rel, Unrelated, Same, SelfDiffers}
use tea_core/diff.{diff, apply}

impl[M] Tree[Widget[M]] {
  fn kids(w: Widget[M]) -> List[Widget[M]] = ...
  fn rekid(w: Widget[M], ks: List[Widget[M]]) -> Widget[M] = ...
  fn relate(old: Widget[M], new: Widget[M]) -> Rel = ...
}
```

## The contract

`Tree[W]` has three members and no associated types. `kids` gives a node's
children in order and thereby defines addressing, since a `path` index is an
index into that list. `rekid` puts a node back together around new children and
must be total, which is what makes `apply` total. `relate` says whether a pair
may be diffed in place (`Same`), whether the node's own data changed as well
(`SelfDiffers`), or whether the pair is unrelated and the subtree is replaced
(`Unrelated`).

`relate` is only ever asked about a pair the reconciler already found unequal,
so a vocabulary never re-compares fields that `==` settled. That structural
`==` is a `Eq` bound on the reconciler rather than a member of `Tree`, which
means "a node holds no callbacks" is enforced where a tree meets the
reconciler.

`fn key(w) -> Option[String]` is the fourth member and the only one with a
default. It names a node among its siblings, and the default `None` is what
lets a vocabulary with no notion of identity keep the pairing it had before the
member existed. The type is `String` for the same reason there is no `type
Attr`: a type declaration cannot constrain its parameters and an unbounded
projection cannot be resolved, so an identity has to be built out of a type
core already knows. That wall is also why the in-place op carries a whole
replacement node rather than attributes.

The impl belongs to the module declaring the vocabulary, not to this package:
the orphan rule is per module and core must not know that widgets exist. One
impl covers every message type (`impl[M] Tree[Widget[M]]`); a ground head is
not something the language accepts.

## Diffing

`diff(old, new)` computes the difference between two trees as a list of
patches, and `apply(old, patches)` replays it; the contract is
`apply(old, diff(old, new)) == new`, and equal trees diff to the empty list. A
patch is an address (`path`, the chain of child indices) plus one of four ops:
`Replace`, `SetSelf`, `AppendKids`, `TruncateKids`. Locality is the point: an
unchanged sibling is never mentioned by any patch.

`SetSelf(w)` is the in-place update, and it carries a whole node where an
attribute op would carry attributes. The applier reads only the node's own
data: `rekid(donor, kids(target))`, the donor's self-data over the children
already in place. The payload is not a copy, and it cannot be reduced to "the
node without its children" either, because a one-child wrapper has no spelling
for "no child".

A child list pairs one of two ways, and the list decides. When every child
answers a `key` and no two answer the same one, children pair by key:
`InsertKid`, `RemoveKid` and `MoveKid` edit the list in the middle, so a
deletion costs one op whatever the length and a child that changed position is
moved rather than rebuilt. Otherwise children pair by index, Elm-style, with
one tail append or truncate, and a middle deletion rewrites the tail pairwise;
that cost is pinned by a test rather than hidden.

Index pairing is the fallback, not the failure case. `diff` is total and has no
channel for a complaint, so a repeated key or one unkeyable sibling gets the
answer it would have had before keys existed. The keyed path emits in two
phases -- every structural op at the parent's address, then the descents into
the pairs that survived -- which is what keeps the invariant the four original
ops had: patches apply in emission order with no index fixups.

## Walking

`fold_preorder(w, init, f)` visits parents before children, left to right, and
hands `f` the accumulator, the node, and the node's address from the root. It
touches only `kids`, so it asks a vocabulary for nothing the reconciler does
not already ask for. Event routing is written on it in the vocabulary rather
than behind a second trait here, which is what lets a router keep payloads core
has no way to name -- the terminal's button labels, for instance.

## The App contract

`trait App[M]` names `type Msg`, `type View`, `effect E`, and the two
functions `update` and `view`. `type View` is bare because an associated type
cannot declare bounds, and the consequence reaches further than the missing
bound: a generic function over `A: App` can do nothing with an `A.View` but
return it. So a driver takes the view as an ordinary function parameter over
its own bounded tree type, and what is lost is the machine checking that the
tree it gets is the one the trait names. `type View` stays as the documented
truth.

`effect E` is what lets one app's `update` do io while another's stays pure.
The method's row is the projection `!M.E`, not an effect variable of its own,
because a method's effect variable is the *caller's* to instantiate and this
row is the impl's. The member defaults to `!()`, so an impl that says nothing
gets a turn that is still a pure function and `==` still tests one; an app
that needs more binds its own row (`effect E = !io`), and the member is here
so that an app which grows a `Cmd` does not make every other app pay for it.

## Subscriptions

`Sub[M]` is data, the same discipline as a tree: `Tick(every_ms, msg)` names
the message a timer firing means, never a callback. The model declares what it
wants (`subs(m)`), a driver owns all timing state, and the declaration is
re-read after every update; timers re-arm only when the declared intervals
change, and a due timer's message is looked up in the declaration current at
fire time, never from the armed state. This module names no tree at all and did
not have to change to be here.

## The reconciler has no production consumer, and has a gate instead

Nothing in this tree calls `diff` outside its tests. It cannot get a caller on
a terminal: the presenter's increment is a screen row rather than a node, a
row-mode layout shifts every line below a height change so partial repaint does
not exist, and a driver deciding *whether* to repaint needs `==` rather than a
patch list. The consumer this is for is a host with addressable nodes.

`scripts/tea-reconciler-contract` is what stands in for one: the pre-split
concrete reconciler, kept runnable as an oracle, compared over every ordered
pair of a corpus, plus mutants that break one production line at a time and
must each be seen. The mutants are not decoration -- one of them survived the
first version of that corpus, and the corpus grew a case to kill it.

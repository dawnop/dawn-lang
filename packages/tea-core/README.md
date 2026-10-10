# packages/tea-core

The vocabulary-free half of the Elm architecture: what a tree owes a reconciler, the reconciler, the walk, `trait App`, and subscriptions.

Nothing here names a widget, a tag or a terminal. A vocabulary (`packages/tea-term`,
`packages/tea-dom`) implements `Tree` for its node type and gets the rest:

```dawn
use tea_core/tree.{Tree, Rel, Unrelated, Same, SelfDiffers}
use tea_core/diff.{diff, apply}

impl[M] Tree[Widget[M]] {
  fn kids(w: Widget[M]) -> List[Widget[M]] = ...
  fn rekid(w: Widget[M], ks: List[Widget[M]]) -> Widget[M] = ...
  fn relate(old: Widget[M], new: Widget[M]) -> Rel = ...
}
```

The impl lives in the module that declares the vocabulary (the orphan rule is
per module), and one impl covers every message type.

## The `Tree` contract

- `kids(w)` is a node's children in order; a patch's `path` indexes into it.
- `rekid(w, ks)` rebuilds a node around new children and must be total.
- `relate(old, new)` is asked only about a pair already found unequal by `==`
  (an `Eq` bound on the reconciler): `Same` to diff the children in place,
  `SelfDiffers` when the node's own data changed too, `Unrelated` to replace
  the subtree. It must account for every difference between the pair.
- `key(w) -> Option[String]` names a node among its siblings. It defaults to
  `None`.

## Diffing

`diff(old, new)` is a list of patches and `apply(old, patches)` replays it:
`apply(old, diff(old, new)) == new`, and equal trees diff to `[]`. A patch is
an address (`path`) and an op: `Replace`, `SetSelf` (a whole node whose own
data replaces the target's, children kept), `AppendKids`, `TruncateKids`,
and for keyed lists `InsertKid`, `RemoveKid`, `MoveKid`. An unchanged sibling
is never mentioned, and patches apply in emission order.

Children pair by key when every child has one and no two share it, so a
deletion in the middle is one op and a moved child is moved, not rebuilt.
Otherwise they pair by index, and a middle deletion rewrites the tail.

## Walking

`fold_preorder(w, init, f)` visits parents before children, left to right,
passing `f` the accumulator, the node and its address. Event routing in a
vocabulary is written on it.

## `trait App`

`trait App[M]` has `type Msg`, `type View`, `effect E`, `update` and `view`.
`update` answers `(M, Cmd[M.Msg])` and its row is `!M.E`, which defaults to
`!()`: an impl that says nothing has a pure `update`, and one that needs io
writes `effect E = !io`. A generic driver can do nothing with an `A.View`, so
drivers take the view function as a parameter.

## Commands

A `Cmd` is data: `NoCmd`, `SendMsg(msg)` (one more message in this same turn),
`BatchCmd(cmds)` and `Fetch(url, tag)`. `cmd.fold_msg(m, msg, update)` runs a
turn: the message, then every commanded message first in, first out. More than
`CMD_FOLD_LIMIT` commanded messages or fetches in one turn panics rather than
truncating.

`Fetch` only describes a request: the host does the getting and answers in a
later turn, with the same `tag`, as `Ok(body)` or `Err(reason)` (a network
failure or a non-2xx status is an `Err`, not a crash). A driver that can fetch
calls `cmd.fold_cmds`, which answers the model and the requested `FetchReq`s;
`fold_msg` has no host to ask and panics on a turn that commanded one.

## Subscriptions

`Sub[M]` is data too: `Tick(every_ms, msg)` names the message a timer means.
The model declares its subscriptions (`subs(m)`), the driver owns all timing
and re-reads the declaration after every update, and a due timer's message is
taken from the declaration current when it fires. `elapse` is handed the
milliseconds the driver measured; a timer that missed whole periods fires once
and keeps its phase.

Changes between versions: [CHANGELOG.md](CHANGELOG.md). Design background:
[`docs/dom-bridge-design.md`](../../docs/dom-bridge-design.md) (in Chinese).

# packages/tea-dom

The DOM half of the Elm architecture: a second vocabulary over `packages/tea-core`'s
reconciler contract, the wire format that carries a patch list out of a wasm
module, and the reactor turn that answers one host message. Nothing here
depends on `packages/tea-term`, and nothing here knows what a browser is; the
JavaScript that does is in `js/`.

```dawn
use tea_dom/dsl.{button, div_of, text}
use tea_dom/reactor.{serve}

pub fn main() -> Unit !io = serve(init(), encode, decode, update, view)
```

## A second consumer, not a second contract

`tea_core` says a reconcilable tree owes three functions (`kids`, `rekid`,
`relate`), and `diff`/`apply`/`fold_preorder` are written against those and
nothing else. The terminal is one consumer of that contract; this package is
the other, and the reconciler arrives unchanged. What differs is the
vocabulary: `Text` and `Elem(tag, props, on, kids)` instead of the terminal's
five constructors, because a browser element is one shape with a tag where a
terminal has no tag to vary.

One thing the DOM needed that the terminal did not. `relate` must see every
difference between a pair, or `apply(old, diff(old, new)) == new` fails; two
elements that agree on tag, props and event names but disagree on what a click
*means* are unequal, and the vocabulary has to say so. That makes the impl
`impl[M: Eq] Tree[Node[M]]` rather than `impl[M] ...`. The terminal never met
this because its message-carrying node is a leaf that answers `Unrelated`.

## The boundary

One JSON object per line each way, and nothing else crosses. `src/wire.dawn`
has the full argument; the three properties worth repeating:

- **A message never crosses.** Outward, the only listener information is the
  *name* of the events an element wants; inward, an address and an event name.
  `route.at` resolves the pair against the tree the model produces right now,
  so the application's message type needs no encoding and the host has never
  heard of it.
- **The model crosses, as opaque text.** Dawn has no module-level mutable
  state, so a reactor holds nothing between turns. The consequence is worth
  more than the cost: a turn is a function of its inputs, so one transcript
  replays identically on the JVM, on native and on wasm.
- **`SetSelf` ships a node without its children.** `apply` performs
  `rekid(donor, kids(target))` and reads nothing of the donor but its own
  data, so shipping the subtree would make an attribute change at the root
  cost the whole document. The locality `diff` buys is kept across the wire.

## Failure

`serve` wraps each turn in `catch_panic`. An application that panics gets an
error reply, the host keeps the model it already had, and the next message is
answered normally. That is the consumer for the wasm failure runtime: without
a landing, a panic on wasm32-wasi aborts the module and the page is dead.

The reply's `kind` is normalised to `panic` rather than passed through,
because `e.kind` is `dawn.rt.PanicError` on the JVM and `panic` on the C
runtime, and a boundary that varies by backend cannot have one transcript.

## Modules

| module | what it is |
|---|---|
| `node` | the vocabulary and `impl Tree` -- the orphan rule puts the impl here |
| `dsl` | lowercase wrappers over the constructors, `tea_term/dsl`'s counterpart |
| `route` | an address plus an event name to a message, on `fold_preorder` |
| `wire` | the JSON encoding of nodes, patches and replies; request decoding |
| `reactor` | `turn` (pure) and `serve` (the package's only `!io`) |

## The host half

`js/` is the JavaScript side: a WASI shim, the reactor driver, and the patch
interpreter that turns the four ops into DOM mutations. Zero dependencies, one
`<script type="module">`. `js/README.md` is its entry point.

`examples/projects/tea_dom_counter` is a complete app over this package, and
`scripts/wasm-dom-contract` drives it end to end without a browser.

## What the reconciler contract does not have for a DOM host

Recorded rather than worked around, since a second consumer is exactly what
finds these:

- **Keyed children.** `diff` pairs children by index, so a deletion in the
  middle rewrites the tail. In a terminal that is a redraw; in a DOM it
  discards element state (focus, selection, a playing video) for every node
  after the deletion. `tea_core/diff`'s header already names the ops keying
  would need and says their payloads fit; this is the consumer that wants
  them.
- **`diff_step`.** `tea_term/step.diff_step` is "one turn as a patch list" and
  is written over `W: Tree + Eq` with nothing terminal in it, but it lives in
  the terminal's package. `reactor.turn` restates its three lines rather than
  depending on `tea_term` for them.

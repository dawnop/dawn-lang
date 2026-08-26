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
vocabulary: `Text` and `Elem(tag, props, on, kids, key)` instead of the
terminal's five constructors, because a browser element is one shape with a tag
where a terminal has no tag to vary.

One thing the DOM needed that the terminal did not. `relate` must see every
difference between a pair, or `apply(old, diff(old, new)) == new` fails; two
elements that agree on tag, props and event names but disagree on what a click
*means*, or on what it should bring back, are unequal, and the vocabulary has
to say so. That makes the impl
`impl[M: Eq] Tree[Node[M]]` rather than `impl[M] ...`. The terminal never met
this because its message-carrying node is a leaf that answers `Unrelated`.

## Event payloads

A listener is `On { event, payload, msg }`, and `payload` is a closed set:
`NoData`, `Value` (the element's value, with a checkbox normalised by the host
to `"true"`/`"false"`), `Key` (`ev.key`). The host brings back that one string
and nothing else, and `dsl.on_click` / `on_value` / `on_key` are the three
spellings a view wants.

The merge cannot live in the tree. Elm's `on : String -> Decoder msg` is a
function from the event to a message, and a tree holding a function has no
structural `==` -- the compiler says so in as many words. So the tree holds a
message with a hole in it and the fold happens outside it, in a trait with a
default body:

```dawn
pub trait Fill[T] { fn fill(m: T, payload: String) -> T = m }
```

An application that declares no payloads writes `impl Fill[Msg] { }` and is
done; `tea_dom_counter` is that case and `tea_dom_todo` is the other.

Three consequences worth stating. The kind is data in the tree, so `relate`
sees a listener whose *reading* changed exactly as it sees one whose meaning
changed, and the host is told to reattach. A misspelling is a type error rather
than a runtime `no-handler`. And a payload that does not match what the
listener declared -- present where none was asked for, missing where one was,
or not a string -- is refused with `bad-request` rather than defaulted, for the
reason `route.at` answering `None` is refused: it means the host is holding a
tree this model does not produce.

The invariant survives all of it. The host still cannot name a message: it
hands over text, and which constructor that text lands in was decided in the
guest. What it gives up is that a message's *value* is enumerable from the
tree, which was never the invariant, only a side effect of there being no way
to type into the page at all.

## Keyed children

`key` is a field of `Elem` and never leaves the guest. `dsl.keyed(tag, props,
on, kids)` takes `List[(String, Node[M])]`, the shape Elm's `Html.Keyed.node`
has, so a forgotten key is a type error rather than a silent return to index
pairing; `node.with_key` is the one-node form underneath it.

What it buys, priced on the shape `tea_dom_todo` has. Deleting the middle row
of fifty costs 98 patches unkeyed, over 24 rewritten rows, and 2 keyed;
deleting the *first* row costs 198 unkeyed and 2 keyed; deleting the last costs
2 either way. Those numbers are assertions in `src/node.dawn`, not prose. What
the rewrite discards in a browser and not in a terminal is element state --
focus, a caret, a selection, a scroll offset, a playing video -- which is the
reason this is a DOM concern before it is a performance one.

`relate` answers `Unrelated` for two elements whose keys differ, which matters
only where the list fell back to index pairing: there a shared position is the
only evidence of identity, and a key that disagrees says the position is
lying.

## Third-party mounts

A widget that owns its own DOM -- an editor, a chart, anything driven by
third-party JavaScript -- goes behind a custom element. This is Elm's answer
and the only one that keeps the tree a pure value: lifecycle hooks in the tree
are functions in the tree, and a tree holding a function has no structural
`==`. A custom element puts the lifecycle on the platform instead. The page
registers the tag (`customElements.define`), the class does its mount work in
`connectedCallback` and its cleanup in `disconnectedCallback`, and the browser
fires those exactly when the reconciler's `replace`/`remove`/`truncate` land.
Tearing a widget down is never this package's business.

`dsl.foreign(tag, props, on)` builds the node. The signature has no `kids`
parameter, because a foreign element has no guest children and that rule is
worth a spelling rather than a warning: with the guest-side list empty, `diff`
never emits an address into the element, so whatever the library builds inside
is invisible to the reconciler and untouched by every patch. On the wire it is
a plain `elem`; the bridge cannot tell it from one, and the seven ops stay
seven.

The division of labour across the boundary:

- **The guest owns the attributes and nothing else.** Data goes in as
  attributes; a changed prop arrives as `set-self`, and the element hears it
  with `observedAttributes`/`attributeChangedCallback`. Events come out as DOM
  events the element dispatches on itself, with a `value` property exposed for
  a listener that declared `Value`. Both halves ride the existing machinery.
- **The element must not write attributes onto its own host tag.** `set-self`
  enforces "the props the guest declared and no others" and sweeps away
  anything else it finds there. Library state lives inside the element, shadow
  DOM preferred; a light-DOM inside is equally safe so long as the guest-side
  kids stay empty.
- **Never give a foreign tag children in the view.** A child in the view puts
  guest patches and library DOM in the same index space, and the patches land
  inside the widget -- appended after its private nodes, truncated across
  them. `foreign` makes the safe spelling the easy one; `el` with a kid list
  is the hole.
- **In a list, key it** (`with_key`, or a `keyed` container). Index pairing
  can pair a foreign element against an ordinary node when a sibling is
  inserted or removed, and the failure is patches aimed at the wrong element.
  Keyed, the worst case is a clean `replace`: disconnect, then connect, never
  a patch inside it.

One consequence to design for: `move` is `insertBefore`, and moving a
connected custom element fires `disconnectedCallback` and `connectedCallback`
again. A widget that builds itself in `connectedCallback` should guard against
re-entry or be cheap to rebuild.

`scripts/wasm-dom-contract/foreign.sh` holds all of this at the bridge:
connect once on mount in tree order, disconnect on `remove`/`truncate`/
`replace`, library DOM untouched by `set-self` and by sibling churn, and an
event out carrying the value the element chose to expose.

## The boundary

One JSON object per line each way, and nothing else crosses. `src/wire.dawn`
has the full argument; the three properties worth repeating:

- **A message never crosses.** Outward, the only listener information is the
  *name* of each event an element wants and, where the listener asked for one,
  the *kind* of data to bring back; inward, an address, an event name and at
  most one string. `route.at` resolves the address against the tree the model
  produces right now and `Fill` folds the string into the message on this side,
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
| `reactor` | `turn` (pure), `serve` (the package's only `!io`), `trait Fill` |

## The host half

`js/` is the JavaScript side: a WASI shim, the reactor driver, and the patch
interpreter that turns the seven ops into DOM mutations. Zero dependencies, one
`<script type="module">`. `js/README.md` is its entry point.

`examples/projects/tea_dom_counter` is a complete app over this package and
`examples/projects/tea_dom_todo` is the one a tier above it (rows with
identity, a draft, a mode). `scripts/wasm-dom-contract` drives both end to
end without a browser.

## What the reconciler contract does not have for a DOM host

Recorded rather than worked around, since a second consumer is exactly what
finds these:

- **`diff_step`.** `tea_term/step.diff_step` is "one turn as a patch list" and
  is written over `W: Tree + Eq` with nothing terminal in it, but it lives in
  the terminal's package. `reactor.turn` restates its three lines rather than
  depending on `tea_term` for them. The two still agree, but they are not the
  same function: `diff_step(m, msg, vw)` computes `vw(m)` itself, and a
  reactor already holds that tree because `route.at` needed it to resolve the
  address. Moving `diff_step` to core would not make it usable here.
- **Capability bits and predicates.** A listener declares what data it wants
  and cannot yet declare anything else: whether the host should call
  `preventDefault`, whether to register the listener as passive, whether to
  debounce, whether a predicate the host evaluates locally should stop the
  event crossing at all. Elm, Blazor, Vaadin and LiveView each have some of
  these, and for a boundary that ships the whole model per turn a predicate
  that keeps a turn from happening is worth more than anything a turn can
  carry. `On` is a record so that adding one is a field rather than a second
  break of the listener's shape; today it holds `payload` and nothing else.

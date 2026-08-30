# packages/tea-dom

The DOM half of the Elm architecture: a second vocabulary over `packages/tea-core`'s
reconciler contract, the wire format that carries a patch list out of a wasm
module, and the reactor turn that answers one host message. Nothing here
depends on `packages/tea-term`, and nothing here knows what a browser is; the
JavaScript that does is in `js/`.

```dawn
use tea_dom/dsl.{button, div, text}
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
elements that agree on tag and props but disagree on which events they listen
for, or on what those events should bring back, are unequal, and the
vocabulary has to say so. The terminal never met this because its
message-carrying node is a leaf that answers `Unrelated`.

## The view vocabulary

`src/dsl.dawn` is lowercase wrappers over the two constructors and nothing
deeper. Every parameter but the tag has a default, so a call names what it has:

```dawn
el("li", class: "row", kids: [
  button(if t.done { "[x]" } else { "[ ]" }, Toggle(id: t.id), class: "box"),
  el("span", class: "title", on: [on_click(Edit(id: t.id))], kids: [text(t.title)]),
  button("x", Drop(id: t.id), class: "kill"),
])
```

`el(tag, props, on, kids, class)` is the general spelling and the first four
are in the constructor's order, so a positional call still reads. The helpers
are `text`, `div(kids, class)`, `span(s, class)`, `button(label, msg, class)`,
`input(class, value, on)`, `keyed`, `foreign`, and there are deliberately no
others: a per-tag wrapper would buy nothing over `el("section", class: "x",
kids: [...])` and would be one more thing to keep in step with `Elem`.

`class:` is the one piece of sugar. It expands to exactly one prop, **prepended**:
`el("li", [("id", "a")], class: "row")` has props `[("class", "row"), ("id", "a")]`.
Prepending is what keeps the order a hand-written list already had, and props
travel in order on the wire, so appending would move a byte in every
transcript. An empty class adds no prop, which is what lets it be the default.
Nothing is deduplicated: a call passing both a `class:` and a `("class", ..)`
inside `props` produces both pairs, in that order, and what a browser does with
a repeated attribute is the browser's rule.

`input` has no `kids` parameter, for the reason `foreign` has none. Its `value`
prop is rendered always, the empty string included: a field this builds is
controlled, so a message that clears the model has to be able to clear the box.

## Event payloads

A listener is `On { event, payload, to_msg }`, and `payload` is a closed set:
`NoData`, `Value` (the element's value, with a checkbox normalised by the host
to `"true"`/`"false"`), `Key` (`ev.key`). The host brings back that one string
and nothing else, and `dsl.on_click` / `on_value` / `on_key` are the three
spellings a view wants.

`to_msg` is `fn(String) -> M`: the payload in, the message out. Elm's
`on : String -> Decoder msg` is the same shape. A bare constructor name is
already a `fn(String) -> M`, so a value-carrying listener is
`on_value("input", SetDraft)` and there is nothing else to write. A `NoData`
listener is handed `""` and ignores it; `on_click(msg)` takes the message and
builds the constant function itself.

A tree holding a function ordinarily has no structural `==`, and the compiler
says so in as many words. `On` keeps `==` by declaring its identity to be
`(event, payload)`, in a hand-written `impl Eq` (with the paired `impl Hash`)
rather than a derive. That pair is exactly what the host is told about a
listener and exactly what a patch can carry, so two listeners equal under it
are indistinguishable to the host, to the patch stream and to dispatch, which
resolves the address against the tree the *current* model produces. This is not
`Eq` for functions: `to_msg` is excluded from identity, not compared. What it
gives up is that a message's *value* is visible to tree `==`, and
`node.deliver(listener, payload)` is the replacement:

```dawn
assert deliver(on_value("input", SetDraft), "buy milk") == SetDraft(text: "buy milk")
```

`docs/dom-bridge-design.md` section 9 is the full argument and its boundary.

Three consequences worth stating. The kind is data in the tree, so `relate`
sees a listener whose *reading* changed and the host is told to reattach; a
listener whose *meaning* changed is not a difference, because there is nothing
to tell the host. A misspelling is a type error rather than a runtime
`no-handler`. And a payload that does not match what the listener declared,
present where none was asked for, missing where one was, or not a string, is
refused with `bad-request` rather than defaulted, for the reason `route.at`
answering `None` is refused: it means the host is holding a tree this model
does not produce.

The invariant survives all of it. The host still cannot name a message: it
hands over text, and which constructor that text lands in was decided in the
guest.

## Keyed children

`key` is a field of `Elem` and never leaves the guest. `dsl.keyed`'s `kids`
takes `List[(String, Node[M])]`, the shape Elm's `Html.Keyed.node` has, so a
forgotten key is a type error rather than a silent return to index pairing;
`node.with_key` is the one-node form underneath it. It defaults like `el` does,
so the usual call is `keyed("ul", class: "list", kids: rows)`.

What it buys, priced on the shape `tea_dom_todo` has. Deleting the middle row
of fifty costs 26 patches unkeyed, over 24 relabelled rows, and 2 keyed;
deleting the *first* row costs 51 unkeyed and 2 keyed; deleting the last costs
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

`dsl.foreign(tag, props, on, class)` builds the node. The signature has no
`kids` parameter, because a foreign element has no guest children and that rule is
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

That is a standing choice, not an oversight. `moveBefore` is the DOM's
state-preserving move and would drop the callback pair; it stays unadopted
because Safari has no implementation, it cannot be polyfilled, and what it buys
is preserved state (animation progress, an `iframe`, a `popover` or `dialog`)
rather than speed. Any one of these reopens the question:

- WebKit bug 281223 moves to RESOLVED.
- React's `enableMoveBefore` flag ships on.
- A consumer keys a list whose items hold an `iframe`, a long-running
  animation, or a `popover`/`dialog`.
- A consumer ships a widget that implements `connectedMoveCallback`.

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
  produces right now and that listener's own `to_msg` turns the string into a
  message on this side, so the application's message type needs no encoding and
  the host has never heard of it.
- **The model crosses, as opaque text.** The mutable model is the only thing
  a reactor carries between turns; the one exception is the read-only root a
  `_with_state` entry installs at init (`std/reactor`), which never rides the
  wire again. The consequence is worth more than the cost: a turn is a
  function of its inputs and that root, so one transcript replays identically
  on the JVM, on native and on wasm.
- **`SetSelf` ships a node without its children.** `apply` performs
  `rekid(donor, kids(target))` and reads nothing of the donor but its own
  data, so shipping the subtree would make an attribute change at the root
  cost the whole document. The locality `diff` buys is kept across the wire.

## Flags

An application whose initial model depends on what the page already knew
takes `serve_with_flags` rather than `serve`:

```dawn
use tea_dom/reactor.{serve_with_flags}

pub fn main() -> Unit !io = serve_with_flags(init, encode, decode, update, view)

fn init(flags: Option[String]) -> Model = ...
```

`init` is `fn(Option[String]) -> Model` instead of a `Model`, and it is called
once, with the `flags` field of the init line. That field is optional and is a
string: the page sends `JSON.stringify(...)` and the guest parses it, so what
may cross is the guest's decoder rather than the browser's idea of a value.
Elm's `init : flags -> model` is the same call for the same reason -- a model
built from flags often has no meaningful value without them, and a "build the
default, then patch it" shape forces one into existence and hopes every field
gets overwritten.

`None` is a line with no `flags` field, which is every line every host writes
today. So `serve` is unchanged, `turn(line, m, ..)` is `turn_with_flags(line,
_ => m, ..)`, and an application that never asked for flags cannot be given
any: its `init` is a value with nowhere to put a string. Absent and empty stay
different answers, as they are for a payload.

`examples/projects/tea_dom_flags` is the smallest application on this path,
and `scripts/wasm-dom-contract/flags.sh` is what says the session it is pinned
to would notice flags being dropped on the floor.

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
| `node` | the vocabulary, `impl Tree`, `impl Eq`/`Hash`, and `deliver` -- the orphan rule puts the impls here |
| `dsl` | lowercase wrappers over the constructors, `tea_term/dsl`'s counterpart |
| `route` | an address plus an event name to a message, on `fold_preorder` |
| `wire` | the JSON encoding of nodes, patches and replies; request decoding |
| `reactor` | `turn` (pure), `serve` (the package's only `!io`), and the `_with_flags` / `_with_state` pairs of each |

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

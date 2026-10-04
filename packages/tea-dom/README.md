# packages/tea-dom

The DOM half of the Elm architecture: a second vocabulary over `packages/tea-core`'s reconciler contract, the wire format that carries a patch list out of a wasm module, and the reactor turn that answers one host message.

```dawn
use tea_dom/dsl.{button, div, text}
use tea_dom/reactor.{serve}

pub fn main() -> Unit !io = serve(init(), encode, decode, update, view)
```

The guest is Dawn compiled to wasm; `js/` is the host side (a WASI shim, the
reactor driver and the patch interpreter, no dependencies, one
`<script type="module">`; start at `js/README.md`).
`examples/projects/tea_dom_counter` is the smallest app and
`examples/projects/tea_dom_todo` the next one up.

| module | what it is |
|---|---|
| `node` | the vocabulary (`Text`, `Elem`), its `Tree` and `Eq` impls, `deliver` |
| `dsl` | lowercase wrappers over the constructors |
| `route` | an address and an event name to a message |
| `wire` | the JSON encoding of nodes, patches and replies |
| `render` | the tree as HTML text |
| `reactor` | `turn` (pure) and `serve` (the only `!io`), with `_with_flags` and `_with_state` variants |

## Views

```dawn
el("li", class: "row", kids: [
  button(if t.done { "[x]" } else { "[ ]" }, Toggle(id: t.id)),
  el("span", on: [on_click(Edit(id: t.id))], kids: [text(t.title)]),
  button("x", Drop(id: t.id), class: "kill"),
])
```

`el(tag, props, on, kids, class)` is the general form; every parameter after
the tag has a default. The other helpers are `text`, `div`, `span`, `button`,
`input`, `keyed` and `foreign`.

- `class:` adds one `("class", ..)` prop in front of `props`; an empty class
  adds none. Nothing is deduplicated.
- `input` always renders its `value`, the empty string included, so clearing
  the model clears the box.

## Events

A listener is `On { event, payload, to_msg }`. `payload` says what the host
brings back: `NoData`, `Value` (the element's value; a checkbox gives
`"true"` / `"false"`) or `Key` (`ev.key`). `to_msg: fn(String) -> M` turns that
string into a message, so a constructor is enough:

```dawn
on_click(Save)                    # NoData
on_value("input", SetDraft)       # Value
on_key("keydown", KeyPressed)     # Key
```

Two listeners are equal when their `event` and `payload` are; `to_msg` is not
compared. A test that wants the message a listener produces calls `deliver`:

```dawn
let l = on_value("input", SetDraft)
assert deliver(l, "buy milk") == SetDraft(text: "buy milk")
```

A payload that does not match what the listener declared is refused with
`bad-request`.

## Keyed children

`keyed(tag, kids: rows)` takes `List[(String, Node[M])]`, so a forgotten key
is a type error; `node.with_key` keys one node. Keyed rows keep their DOM
elements, and with them focus, caret, selection and scroll, when a row is
inserted, removed or moved. Deleting a middle row of fifty is 2 patches keyed
and 26 unkeyed.

## Third-party mounts

A widget that owns its own DOM (an editor, a chart) goes behind a custom
element. The page registers the tag; the element mounts in
`connectedCallback` and cleans up in `disconnectedCallback`, which the browser
fires when a patch adds or removes it. Build the node with
`dsl.foreign(tag, props, on, class)`, which has no `kids`.

- The guest owns the element's attributes and nothing else. A changed prop
  arrives through `attributeChangedCallback`; events go out as DOM events the
  element dispatches on itself, with a `value` property for a `Value`
  listener.
- The element must not set attributes on its own tag: the next `set-self`
  removes any the guest did not declare. Keep library state inside, in a
  shadow root preferably.
- Never give a foreign tag children in the view, or patches land inside the
  widget.
- Key it in a list. Unkeyed, a sibling insert can pair it against another
  node; keyed, the worst case is a clean replace.
- A `move` patch is `insertBefore`, which fires `disconnectedCallback` and
  `connectedCallback` again; build so that a reconnect is safe.

## The wire

One JSON object per line in each direction. A message never crosses: the host
is told event names and payload kinds, and sends back an address, an event
name and at most one string, which the guest resolves against the current
tree. The model crosses as opaque text, so a turn is a function of its inputs
and one transcript replays alike on the JVM, natively and on wasm. A `Cmd`
adds updates inside the turn and nothing on the wire.

## HTML

`render.to_html(w)` prints a tree as HTML and `to_document(w)` prefixes
`<!DOCTYPE html>`:

```dawn
let p = el("p", class: "count", kids: [text("0")])
assert to_html(p) == "<p class=\"count\">0</p>"
```

The output parses to the DOM the bridge would build for the same tree:

- Listeners and keys are dropped; a printed button is dead.
- Text escapes `& < >`; an attribute value is double-quoted and escapes
  `& < > "`. `script` and `style` text is raw, and text holding the element's
  own end tag panics.
- `checked` prints as a bare attribute unless it is `""` or `"false"`.
  `value` on a `textarea` is its content; on a `select` it selects nothing
  (put `selected` on the `option`).
- A repeated prop prints once, at its first position with its last value.
- The 13 void elements print as `<br>`, children dropped. A tag or prop name
  with whitespace, a control character or one of `" ' > / =` panics.

## Flags

```dawn
use tea_dom/reactor.{serve_with_flags}

pub fn main() -> Unit !io =
  serve_with_flags(init, encode, decode, update, view)

fn init(flags: Option[String]) -> Model = ...
```

`init` is called once with the init line's optional `flags` string (the page
sends `JSON.stringify(...)`; the guest parses it). `None` means the line had
no `flags` field. `examples/projects/tea_dom_flags` is the smallest example.

## Failure

`serve` catches a panic in a turn: the host gets an error reply with `kind`
`panic`, keeps the model it had, and the next message is answered normally.

Changes between versions: [CHANGELOG.md](CHANGELOG.md). Design:
[`docs/dom-bridge-design.md`](../../docs/dom-bridge-design.md) (in Chinese).

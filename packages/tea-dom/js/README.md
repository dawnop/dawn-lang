# packages/tea-dom/js

The host half of the DOM bridge: vanilla ES modules, zero dependencies, the
same four files in a browser and in node.

```html
<script type="module">
  import { mount } from './packages/tea-dom/js/app.mjs';
  await mount(await fetch('./counter.wasm'), document.getElementById('app'));
</script>
```

| file | what it is |
|---|---|
| `wasi.mjs` | the eight WASI preview1 functions the guest imports, over a byte queue |
| `reactor.mjs` | instantiate once, `dawn_turn` per message, one JSON line each way |
| `dom.mjs` | the seven patch ops as DOM mutations, and the address walk both ways |
| `app.mjs` | the loop: init, render, wait, dispatch, patch, wait |

## The boundary

One JSON object per line each way. `packages/tea-dom/src/wire.dawn` is the
authority on the shape; the two things a reader of this directory needs are
that a *message* never crosses (an address, an event name and at most one
string go in; event names and payload kinds come out) and that the *model*
does, as opaque text this code carries between turns without ever reading it.

```
-> {"op":"init"}
<- {"ok":true,"model":"0","patches":[{"path":[],"op":"replace","node":{…}}]}

-> {"op":"event","model":"0","path":[3,1],"event":"click"}
<- {"ok":true,"model":"1","patches":[
     {"path":[1,0],"op":"replace","node":{"t":"text","s":"1"}},
     {"path":[2],"op":"append","nodes":[{…}]}]}

-> {"op":"event","model":"…","path":[1,0],"event":"input","payload":"buy mil"}

<- {"ok":false,"kind":"panic","error":"…"}
```

A node is `{"t":"text","s":…}` or
`{"t":"elem","tag":…,"props":[[k,v],…],"on":[…],"kids":[…]}`, and a
`set-self` payload is the same object with no `kids` -- `apply` reads only a
donor's own data, so the subtree is not shipped and a class change at the root
costs one `setAttribute`.

## Listeners and payloads

An entry of `on` is either a bare event name, or `[name, kind]` where `kind`
is `"value"` or `"key"`:

```
"on":["click"]
"on":[["input","value"],"blur"]
```

A bare name is a listener that wants nothing back, which is what every listener
was before payloads existed and is still the common case; the two encodings
are what keeps a document full of buttons byte-identical to the one this bridge
carried before.

The kind decides three things, all of them in `dom.mjs`:

- **what is read.** `"value"` is `ev.target.value`, with a checkbox or a radio
  normalised to `"true"`/`"false"` so that one slot covers all three; `"key"`
  is `ev.key`. Never anything the guest did not ask for.
- **whether `preventDefault` is called.** It is, except for `"key"`:
  cancelling a `keydown` is how a page stops the character reaching the
  element, and a listener that asked which key was pressed did not ask for it
  to be swallowed.
- **when a listener is reattached.** A handler closes over the kind, so a
  listener whose kind changed is removed and added rather than left in place.
  The guest makes that reachable by comparing the kind in `relate`.

The payload field is *omitted* from the request when there is none. Absent and
empty are different answers: the guest refuses a turn whose payload does not
match what its listener declared, with `{"ok":false,"kind":"bad-request"}`, so
a host that sends `""` where nothing was asked for gets an error rather than a
shrug. That refusal is the same policy an address that listens for nothing
gets, and for the same reason: it means the two sides are looking at different
trees.

## The seven ops

`replace`, `set-self`, `append` and `truncate` address a node or its tail.
The other three edit a child list in the middle:

```
{"path":[3],"op":"insert","at":1,"node":{…}}
{"path":[3],"op":"remove","at":1}
{"path":[3],"op":"move","from":4,"to":1}
```

`move` must move the node the document already has, with `insertBefore`, and
never remove and rebuild it. Everything a browser keeps inside an element --
focus, a caret, a selection, a scroll offset, a half-typed IME composition --
is state no tree describes and a fresh element does not have, and moving is
the only way it survives a reordering.

One trap in `move`. `to` counts positions in the list as it will be, while the
reference child is read from the list as it is, with the moving node still in
it. A node travelling right therefore skips over itself and takes `to + 1`; a
node travelling left does not. The wrong choice puts the element one place off
and raises nothing.

The guest settles the pairing, so no key ever crosses: the host is told where
a child goes and never why. `scripts/wasm-dom-contract/keyed-ops.mjs` drives
these three straight at the bridge, since neither demo application keys its
children.

## Props: attributes, and two properties

A prop is a pair of strings and reaches the element with `setAttribute`, with
two exceptions: `value` and `checked` are written as *properties*.

An `<input>` keeps a live value beside its `value` content attribute, and
WHATWG HTML says the attribute writes through to the live one only while the
control's dirty value flag is false, which the first keystroke sets for good.
A bridge that only ever calls `setAttribute` therefore renders the model into a
field exactly once: afterwards the field is the user's and the model can never
correct it, and nothing raises. `checked` has the same split.

`checked` is a boolean and a prop is a string, so presence means checked, which
is the content attribute's own rule; `""` and `"false"` are the two spellings
of unchecked. A prop that leaves the list is removed from the element either
way, and the property half of that reset is skipped on elements that have no
such property, so a `<div>` never acquires one.

`scripts/wasm-dom-contract/props.mjs` drives this straight at the bridge
against a stub that carries the dirty value flag, because a document whose
attribute is right and whose live value is stale is one a transcript cannot
tell from a correct one.

## Why a WASI shim rather than `node:wasi`

There is no `node:wasi` in a browser, and a harness running on a different
host than the page tests something the page does not do. The module imports
eight functions, all stdio or environment; `wasi.mjs` is all eight.

## Addresses

A `path` is a chain of child indices and `kids` in the DOM vocabulary is an
element's children in order, so `path` walks `childNodes` and nothing has to
be stored on a node to address it. The reverse walk is the load-bearing one:
when an event fires, the address is *recovered* by walking up from the target
counting siblings. Recording it on the element instead would be stale the
moment a sibling is inserted, and a handler firing with a stale address
dispatches the wrong message.

## Failure

An error reply carries no patches, so there is nothing half-applied to undo:
`app.mjs` leaves the document alone and calls `onError`. The guest catches its
own application's panics (`tea_dom/reactor.serve`), which is what the wasm
failure runtime is for; if a failure gets past that, the guest calls
`proc_exit`, `wasi.mjs` throws, and the reply is
`{"ok":false,"kind":"aborted"}`. That instance is finished -- a reactor whose
libc has torn itself down has no way back in.

## Running the demo

```sh
dawnc build --target wasm --reactor examples/projects/tea_dom_counter \
  -o examples/projects/tea_dom_counter/web/counter.wasm
python3 -m http.server 8000
# then open
#   http://localhost:8000/examples/projects/tea_dom_counter/web/
```

Serve the repository root, not the `web/` directory: the page imports back
into `packages/`, and a document root at `web/` would put that outside it.

`scripts/wasm-dom-contract` is the same loop with a recording document stub
in place of a browser, held to a transcript.

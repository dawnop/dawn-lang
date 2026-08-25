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
| `dom.mjs` | the four patch ops as DOM mutations, and the address walk both ways |
| `app.mjs` | the loop: init, render, wait, dispatch, patch, wait |

## The boundary

One JSON object per line each way. `packages/tea-dom/src/wire.dawn` is the
authority on the shape; the two things a reader of this directory needs are
that a *message* never crosses (only an address and an event name go in, only
event *names* come out) and that the *model* does, as opaque text this code
carries between turns without ever reading it.

```
-> {"op":"init"}
<- {"ok":true,"model":"0","patches":[{"path":[],"op":"replace","node":{…}}]}

-> {"op":"event","model":"0","path":[3,1],"event":"click"}
<- {"ok":true,"model":"1","patches":[
     {"path":[1,0],"op":"replace","node":{"t":"text","s":"1"}},
     {"path":[2],"op":"append","nodes":[{…}]}]}

<- {"ok":false,"kind":"panic","error":"…"}
```

A node is `{"t":"text","s":…}` or
`{"t":"elem","tag":…,"props":[[k,v],…],"on":[event,…],"kids":[…]}`, and a
`set-self` payload is the same object with no `kids` -- `apply` reads only a
donor's own data, so the subtree is not shipped and a class change at the root
costs one `setAttribute`.

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

# tea_dom changelog

Newest first.

## 0.5.0 (2026-10-11)

A fetched resource can join the retained state.

- Guest: `reactor.turn_with_state`, `turn_shown` and `serve_with_state` take a
  further trailing `absorbed: Option[fn(S, String, Result[String, String]) -> S]
  = None`. On a `supply` it runs first, with the retained state, the tag and the
  outcome, and its result is the state that `update` and `view` receive in that
  turn and afterwards (the first component of the answer is `Some` for it, as it
  is after an `init`). The application's own messages still cannot replace the
  retained state; only the host's answer to a request it made can. Without it
  nothing changes. Reason: a resource fetched after `init` is read-only data of
  the same kind as the flags, and carrying it in the model would put it back on
  the wire with every event.

No wire change; JS hosts are untouched.

## 0.4.0 (2026-10-10)

The host side of tea_core 0.2.0's `Fetch` command.

- Wire: a reply may carry `"fetch":[{"url","tag"}]` after its patches (absent
  when empty, so every reply that asked for nothing is byte-identical), and a
  new `supply` request returns the outcome: `{"op":"supply","model","tag",
  "ok":true,"body"}` or `"ok":false,"error"`. `wire.Supply` and
  `wire.reply_ok_asking` are new.
- Guest: `reactor.turn_with_state`, `turn_shown` and `serve_with_state` take a
  trailing `supplied: Option[fn(String, Result[String, String]) -> M] = None`,
  the application's reading of an outcome. Without it a `supply` is a
  `bad-request`. The stateless `turn`, `turn_with_flags`, `serve` and
  `serve_with_flags` answer a `supply` the same way and panic on a commanded
  `Fetch`.
- Host (`js/`): `Reactor.supply(tag, outcome)` and `runFetch(url)`, which
  answers `{ok, body}` or `{ok: false, error}` and never rejects. `worker.mjs`
  runs a reply's fetches after posting the reply and reports each as
  `{fetched: {tag, outcome}}`; `Remote` queues it as a turn like an event, so a
  result never overtakes an event already in flight; `app.mjs` supplies the
  guest directly. Relative urls resolve against the host's base (a worker's is
  its script), so applications name resources by absolute path.

Breaking only for code that matches `wire.Request` exhaustively. In 0.x the
minor is the compatibility class, hence 0.4.0.

## 0.3.0 (2026-10-05)

`render.to_html` and `render.to_document` take `at: Loc = caller()`, and a
refused tree (a bad tag or prop name, a `script` or `style` holding its own
end tag) panics with the caller's location instead of a line inside
`render.dawn`.

Breaking only where either function is used as a value: a function value
drops defaults, so its type gains a `Loc` parameter. Every direct call
compiles unchanged. In 0.x the minor is the compatibility class, hence 0.3.0.

## 0.2.1 (2026-10-03)

Doc comments and published examples. No behaviour change.

Changed since, without a version change:

- 2026-10-05: the browser WASI shim (`js/wasi.mjs`) answers `clock_time_get`,
  so a reactor that reads std/io's `Clock` gets a reading instead of a stub.

## 0.2.0 (2026-10-01)

`render.to_html` and `render.to_document`: a tree printed as HTML.

Changed since, without a version change:

- 2026-10-02: `serve_with_state` keeps the tree the last reply described and
  routes the next event through it when the host hands back that reply's
  model (`reactor.turn_shown`).

## 0.1.0 (2026-08-26)

The DOM vocabulary over the `tea_core` reconciler, the wire format and the
reactor turn.

Changed during 0.1.0, without a version change:

- 2026-09-07: `update` answers `(model, Cmd)`.
- 2026-08-30: init flags (`serve_with_flags`) and init state kept across
  turns (`_with_state`).
- 2026-08-29: the DSL takes named and defaulted parameters (`class:`,
  `kids:`); a listener holds its `to_msg` function and the `Fill` trait is
  gone.
- 2026-08-27: `dsl.foreign` for custom-element mounts.
- 2026-08-26: declared event payloads (`NoData`, `Value`, `Key`) and keyed
  children.

# tea_dom changelog

Newest first.

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

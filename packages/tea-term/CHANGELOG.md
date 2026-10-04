# tea_term changelog

## 0.3.0 (2026-08-22)

The terminal half of `packages/tea` (0.2.0): the widget vocabulary, its DSL,
`render`, `present`, routing and `runtime.run`. The `Tree` contract, the
reconciler, `trait App` and subscriptions moved to `tea_core`.

Changed since, without a version change:

- 2026-09-07: `update` answers `(model, Cmd)`, and `step` and the driver fold
  commands with `tea_core/cmd.fold_msg`.
- 2026-08-26: impls of `App` no longer bind `effect E`; it defaults to `!()`.

## 0.2.0 (2026-08-20)

`packages/tea`: the widget tree diff and patch.

## 0.1.0 (2026-08-20)

`packages/tea`: the Elm architecture with a pure widget tree.

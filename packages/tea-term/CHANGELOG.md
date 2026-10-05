# tea_term changelog

## 0.4.0 (2026-10-05)

`runtime.run` times subscriptions on the monotonic clock (std/io's `Clock`).

- `Tick(every_ms, msg)` fires every `every_ms` of elapsed time. Before, the
  loop counted only full poll timeouts, so time spent reading, updating and
  painting was invisible, and input arriving faster than the interval held a
  timer off: a 100 ms tick under a line every 20 ms for 2.5 s fired 2 times,
  and now fires 24.
- An early `false` from `stdin_ready` (a closed stream, on the native
  backend) is told apart from a timeout by the clock, and the loop reads. The
  session ends at end of input instead of firing every timer at CPU speed
  (577,741 ticks in 3 s, never ending, in the same measurement).
- A timer that a slow turn made late fires once and keeps its phase.
- The signature of `run` is unchanged: it installs `io.with_clock_real`
  itself.

A minor under the 0.x compatibility-class rule (docs/package-design.md, in
Chinese), because it is a break: the meaning of a tick, as the README
documented it, was "every n ms of waiting", and an app's tick count under
input changes by an order of magnitude. Needs a toolchain whose std/io has
`Clock`, and tea_core 0.1.1.

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

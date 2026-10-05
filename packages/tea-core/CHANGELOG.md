# tea_core changelog

## 0.1.1 (2026-10-05)

- `sub.elapse` keeps `waited % every_ms` past a boundary instead of
  `waited - every_ms`, so a timer handed several periods at once fires once
  and keeps its phase. Before, it stayed owed the rest and fired again on
  every following call until it caught up. No result changes for an `ms`
  within each timer's remaining wait, which is all a driver without a clock
  could hand it; tea_term 0.4.0 measures time and can hand more. A patch: the
  doc comment already promised that a late poll "drifts rather than bursts".
- `Tick` is documented as milliseconds as the driver counts them, not as
  milliseconds of waiting.

## 0.1.0 (2026-08-22)

The vocabulary-free half of `packages/tea` (0.2.0) as a package of its own:
`Tree`, `diff` / `apply`, `fold_preorder`, `trait App` and `Sub`. Why two
packages: [`docs/package-design.md`](../../docs/package-design.md), section 9
(in Chinese).

Changed since, without a version change:

- 2026-09-07: `update` answers `(M, Cmd[M.Msg])`; `Cmd`, `cmd.fold_msg` and
  `CMD_FOLD_LIMIT` are new.
- 2026-08-26: `trait App` has `effect E`, defaulting to `!()`.
- 2026-08-26: `Tree.key` and keyed pairing of child lists (`InsertKid`,
  `RemoveKid`, `MoveKid`).

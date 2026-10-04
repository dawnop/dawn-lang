# tea_core changelog

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

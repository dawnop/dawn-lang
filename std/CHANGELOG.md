# Standard library changelog

The standard library ships with the compiler release. Source package versions
are recorded separately in their own changelogs.

## Bitwise operator migration (2026-10-22)

- Implement `BitAnd`, `BitOr`, `BitXor`, `BitNot`, `Shl`, `Shr` and `Ushr` for all seven fixed-width integer types. Shift Amounts are `Int`; each associated effect is pure.
- Mask counts with `width - 1`, including negative counts. Left shifts wrap, `>>` follows subject signedness, and `>>>` zero fills within the subject width. A zero count preserves the original bit pattern.
- Remove the 42 named `and`, `or`, `xor`, `complement`, `shl` and `shr` exports without compatibility wrappers. Keep rotations, checked arithmetic, conversions and device format witnesses.
- The matching [tileir migration](../packages/tileir/CHANGELOG.md) uses same-type Tile Amounts and `!Dev`, supports signed integer Tiles for all seven operators, and Bool Tiles for `& | ^ ~`. Both libraries use the same masked-count semantics.
- Share independent integer expectations across runtime, comptime, LSP, tileinterp and tileref checks. Preserve the native C unsigned shift path and verify GCC and Clang at O0 and O2 under UBSan.

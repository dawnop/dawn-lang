# tileref changelog

## 0.1.3 (2026-10-22)

- Add exact independent references for pure staged-if Unit, value, nested loop and single-write branches, including untouched output tails.

## 0.1.2 (2026-10-22)

- Add finite-width shift references with masked signed counts and a typed Int oracle for complete i64 bit patterns.

## 0.1.1 (2026-10-22)

Add finite-width bitwise reference segments and a full-width Int oracle for tile operators.

## 0.1.0 (2026-10-01)

The host references moved here from `std/gpu`, which keeps only the device
model and `vadd_ref` / `sum_ref`. Why: `src/ref.dawn`'s header and
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5.3 (in
Chinese).

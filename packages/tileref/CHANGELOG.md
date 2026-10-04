# tileref changelog

## 0.1.0 (2026-10-01)

The host references moved here from `std/gpu`, which keeps only the device
model and `vadd_ref` / `sum_ref`. Why: `src/ref.dawn`'s header and
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5.3 (in
Chinese).

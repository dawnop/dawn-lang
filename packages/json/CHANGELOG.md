# json changelog

Newest first. The manifest name is `json2` from 2.0.0 on; consumers keep
`use json/...` by aliasing the dependency as `json`.

## 2.0.1 (2026-10-03)

Doc comments on the remaining public declarations. No behaviour change.

## 2.0.0 (2026-08-11)

Next major, published as `json2`: errors are a `JsonError` with a
`JsonErrorKind` and an offset rather than a string.

## 1.0.0 (2026-07-22)

The library backend-dawn had vendored, adopted as a package so that its four
copies became one ([`docs/package-design.md`](../../docs/package-design.md),
in Chinese).

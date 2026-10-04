# inflate changelog

Newest first. The manifest name carries the major from 2 on (`inflate2`,
`inflate3`); consumers keep `use inflate/...` through their alias.

## 3.0.1 (2026-10-05)

Decoding time is linear in the input again. The fixed Huffman tables are
built once per stream instead of once per fixed block, and a table build is
linear in the number of symbols instead of quadratic. A stream of empty fixed
blocks writes no output, so the ceiling never stopped it: 50 KB of them took
about 100 s and now take well under a second. No API or output change.

## 3.0.0 (2026-10-03)

Every entry point has a finite default ceiling, `deflate.DEFAULT_CAP`
(16 MiB of output). No signature changed; only what an omitted `cap` means.
`zip.entries` gained `cap`, applied to all entries together. A refusal by the
default names the default and both ways out. Rationale:
[`docs/inflate-default-cap-design.md`](../../docs/inflate-default-cap-design.md)
(in Chinese).

| 2.x call | 2.x meaning | 3.0.0 meaning | 2.x meaning, spelled in 3.0.0 |
| --- | --- | --- | --- |
| `deflate.inflate(src)` | no ceiling | 16 MiB | `cap: None` |
| `deflate.inflate_from(src, from)` | no ceiling | 16 MiB | `cap: None` |
| `gzip.gunzip(src)` | no ceiling | 16 MiB over all members | `cap: None` |
| `zip.read(src, m)` | no ceiling | 16 MiB | `cap: None` |
| `zip.entries(src)` | no ceiling | 16 MiB over all entries | `cap: None` |

Calls that already pass `cap: Some(n)` behave as in 2.x.

## 2.0.0 (2026-10-02)

Each `_bounded` twin is folded into its base function as a defaulted `cap`.
Rationale: [`docs/std-defaults-design.md`](../../docs/std-defaults-design.md)
(in Chinese).

| 1.x | 2.0.0 |
| --- | --- |
| `deflate.inflate_bounded(src, Some(n))` | `deflate.inflate(src, cap: Some(n))` |
| `deflate.inflate_end(src, cap)` | `deflate.inflate_from(src, cap: cap)` |
| `gzip.gunzip_bounded(src, Some(n))` | `gzip.gunzip(src, cap: Some(n))` |
| `zip.read_bounded(src, m, Some(n))` | `zip.read(src, m, cap: Some(n))` |

## 1.1.0 (2026-08-09)

`gzip.gunzip` reads concatenated members, checks every member's trailer and
applies one ceiling to the aggregate output.

## 1.0.0 (2026-07-28)

DEFLATE, gzip, ZIP and CRC-32 in Dawn, replacing the package fetcher's
`use java` archive path.

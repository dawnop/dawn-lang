# packages/inflate

Pure Dawn readers for raw DEFLATE, gzip and ZIP, plus CRC-32.

The package manager uses them for downloaded source archives; no module
imports Java.

Package version **3.0.0** gives every entry point a finite default ceiling,
`deflate.DEFAULT_CAP`, 16 MiB of output. `cap: None` is now the explicit way to
have no ceiling, and `cap: Some(n)` any other one. No signature changed shape;
only what an omitted `cap` means did, which is why this is a major release:

| 2.x call | 2.x meaning | 3.0.0 meaning | 3.0.0 spelling of the 2.x meaning |
| --- | --- | --- | --- |
| `deflate.inflate(src)` | no ceiling | 16 MiB | `deflate.inflate(src, cap: None)` |
| `deflate.inflate_from(src, from)` | no ceiling | 16 MiB | `deflate.inflate_from(src, from, cap: None)` |
| `gzip.gunzip(src)` | no ceiling | 16 MiB over all members | `gzip.gunzip(src, cap: None)` |
| `zip.read(src, m)` | no ceiling | 16 MiB | `zip.read(src, m, cap: None)` |
| `zip.entries(src)` | no ceiling, and no way to set one | 16 MiB over all entries | `zip.entries(src, cap: None)` |

Calls that already pass `cap: Some(n)` behave exactly as in 2.x.

**The default ceiling (decided).** This package has only one-shot entry
points, so a caller who forgets a ceiling does not read slowly, it runs out of
memory: DEFLATE expands up to about 1032:1, so a megabyte of input can become a
gigabyte. The default is 16 MiB rather than 64 or 256 because the ceiling
counts output bytes, and the output buffer (`bytes.Buf`) costs well over one
byte of memory per output byte today; 16 MiB is the size measured to stay
inside the toolchain's own `-Xmx2g` for any input. A caller with a known larger
budget, like the package fetcher, passes it. A refusal by the default names it
and both ways out:

```
deflate: the output exceeds the 16777216 byte limit (stopped at 16776967 bytes); the default cap is 16777216 bytes: pass cap: Some(n) for a larger limit, or cap: None for no limit
```

The default is recognised by value, so an explicit `cap: Some(DEFAULT_CAP)`
gets the same note. Only ceiling refusals carry it; a damaged stream is not
fixed by a larger limit.

`zip.entries` applies its `cap` to all entries together, not to each. A
central directory may point many records at the same compressed bytes, so a
per-entry ceiling times the entry count is no ceiling; each entry is read
against what the earlier ones left, as `gzip.gunzip` does for members.

### 2.0.0

Package version 2.0.0 folded each `_bounded` twin into its base function as a
defaulted parameter:

| 1.x | 2.0.0 |
| --- | --- |
| `deflate.inflate_bounded(src, Some(n))` | `deflate.inflate(src, cap: Some(n))` |
| `deflate.inflate_end(src, cap)` | `deflate.inflate_from(src, cap: cap)` |
| `gzip.gunzip_bounded(src, Some(n))` | `gzip.gunzip(src, cap: Some(n))` |
| `zip.read_bounded(src, m, Some(n))` | `zip.read(src, m, cap: Some(n))` |

Every unsuffixed 1.x function only forwarded `None` to its twin, so the pair
said nothing one function with a default cannot; Kotlin's and Swift's API
guidelines both prefer the default to a family of variants. The version is
raised in the same change as the API so MVS never sees different package
contents under the same name/version.

## Gzip contract

`gzip.gunzip` reads the complete RFC 1952 stream:

- concatenated members are accepted and their payloads are concatenated in
  member order;
- every member has its own header, DEFLATE end offset, CRC-32 and ISIZE check;
- reserved flag bits are rejected, and FHCRC is verified when present;
- optional fields must be complete and NUL-terminated where required;
- bytes after a trailer must begin another complete member, so trailing garbage
  is rejected rather than ignored.

A `cap` is one limit on the aggregate output. A later member receives only the
budget left by earlier members. The DEFLATE reader starts at an offset in the
original `Bytes`, and the aggregate uses `bytes.Buf`,
so many small members neither recurse nor repeatedly copy the remaining input
or the accumulated output. One member's output is materialised long enough to
verify its trailer, then appended once to the aggregate buffer.

## Raw DEFLATE API

The `deflate` module exposes two entry points:

- `inflate(src, cap: Option[Int] = Some(DEFAULT_CAP))` decodes a stream
  beginning at byte zero;
- `inflate_from(src, from: Int = 0, cap: Option[Int] = Some(DEFAULT_CAP))` is
  the cursor form used by containers, and also returns the end offset.

`inflate_from` decodes directly from `from` in the original `Bytes` and returns
the absolute byte index immediately after that DEFLATE stream, not a length
relative to `from`. It rejects negative starts and starts beyond the input.
`cap` limits only the output produced by that call; it does not count prefix
bytes. A container implementing an aggregate limit must pass its remaining
budget, as `gzip.gunzip` does for each member.

Keeping the cursor in the single `deflate` module is deliberate: Dawn has
module-private visibility but no package-private visibility, so a separately
exported “internal” module would still be user-reachable API without admitting
it.

`scripts/inflate-contract/run.sh` checks ordinary streams against
`java.util.zip`, runs the member-boundary corpus on both JVM and native, and
carries behavioral mutants for the member loop, trailer cursor, aggregate cap,
reserved flags, FHCRC verification and the per-member FHCRC checksum origin.
Its last two legs run a 512 MB bomb inside a 256 MB heap: once with an
explicit ceiling, and once with none passed, through `deflate.inflate`,
`gzip.gunzip` (alone and after a small member) and `zip.entries`, so that
putting the default back to `None` is an OutOfMemoryError, not a pass.

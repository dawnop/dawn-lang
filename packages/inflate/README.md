# packages/inflate

Pure Dawn readers for raw DEFLATE, gzip and ZIP, plus CRC-32.

The package manager uses them for downloaded source archives; no module
imports Java.

Package version **2.0.0** folds each `_bounded` twin into its base function as
a defaulted parameter, `cap: Option[Int] = None`. It is a major release because
four public functions are gone:

| 1.x | 2.0.0 |
| --- | --- |
| `deflate.inflate_bounded(src, Some(n))` | `deflate.inflate(src, cap: Some(n))` |
| `deflate.inflate_end(src, cap)` | `deflate.inflate_from(src, cap: cap)` |
| `gzip.gunzip_bounded(src, Some(n))` | `gzip.gunzip(src, cap: Some(n))` |
| `zip.read_bounded(src, m, Some(n))` | `zip.read(src, m, cap: Some(n))` |

Calls without a ceiling (`inflate(src)`, `gunzip(src)`, `read(src, m)`) are
unchanged. Every unsuffixed 1.x function only forwarded `None` to its twin, so
the pair said nothing one function with a default cannot; Kotlin's and Swift's
API guidelines both prefer the default to a family of variants. The version is
raised in the same change as the API so MVS never sees different package
contents under the same name/version.

**Open: the default ceiling.** `cap` defaults to `None`, no ceiling, because
that is what the unsuffixed names always did, and this release changes only
how a ceiling is spelled. Whether a decompressor should instead default to a
finite ceiling, so that a caller who forgets one is not exposed to a
decompression bomb, is a separate safety decision that has not been made.

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

- `inflate(src, cap: Option[Int] = None)` decodes a stream beginning at byte
  zero;
- `inflate_from(src, from: Int = 0, cap: Option[Int] = None)` is the cursor
  form used by containers, and also returns the end offset.

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

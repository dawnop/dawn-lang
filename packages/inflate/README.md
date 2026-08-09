# packages/inflate

Pure Dawn readers for raw DEFLATE, gzip and ZIP, plus CRC-32. The package
manager uses them for downloaded source archives; no module imports Java.

Package version **1.1.0** adds the public `deflate.inflate_from` cursor API.
This is a backward-compatible minor release: every 1.0.0 entry point retains
its signature and semantics. The version is raised in the same change as the
API so MVS never sees different package contents under the same name/version.

## Gzip contract

`gzip.gunzip` and `gzip.gunzip_bounded` read the complete RFC 1952 stream:

- concatenated members are accepted and their payloads are concatenated in
  member order;
- every member has its own header, DEFLATE end offset, CRC-32 and ISIZE check;
- reserved flag bits are rejected, and FHCRC is verified when present;
- optional fields must be complete and NUL-terminated where required;
- bytes after a trailer must begin another complete member, so trailing garbage
  is rejected rather than ignored.

The bounded entry point applies one limit to the aggregate output. A later
member receives only the budget left by earlier members. The DEFLATE reader
starts at an offset in the original `Bytes`, and the aggregate uses `bytes.Buf`,
so many small members neither recurse nor repeatedly copy the remaining input
or the accumulated output. One member's output is materialised long enough to
verify its trailer, then appended once to the aggregate buffer.

## Raw DEFLATE API

The `deflate` module exposes four entry points:

- `inflate(src)` decodes a stream beginning at byte zero;
- `inflate_bounded(src, cap)` does the same under an output-size ceiling;
- `inflate_end(src, cap)` additionally returns the end offset measured from
  byte zero;
- `inflate_from(src, from, cap)` is the low-level cursor API used by containers.

`inflate_from` decodes directly from `from` in the original `Bytes` and returns
the absolute byte index immediately after that DEFLATE stream, not a length
relative to `from`. It rejects negative starts and starts beyond the input.
`cap` limits only the output produced by that call; it does not count prefix
bytes. A container implementing an aggregate limit must pass its remaining
budget, as `gzip.gunzip_bounded` does for each member.

The three existing raw-DEFLATE signatures and semantics are unchanged;
`inflate_from` is the non-breaking public addition in version 1.1.0. Keeping
the cursor in the single `deflate` module is deliberate: Dawn has
module-private visibility but no package-private visibility, so a separately
exported “internal” module would still be user-reachable API without admitting
it.

`scripts/inflate-contract/run.sh` checks ordinary streams against
`java.util.zip`, runs the member-boundary corpus on both JVM and native, and
carries behavioral mutants for the member loop, trailer cursor, aggregate cap,
reserved flags, FHCRC verification and the per-member FHCRC checksum origin.

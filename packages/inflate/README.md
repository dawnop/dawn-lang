# packages/inflate

Pure Dawn readers for raw DEFLATE, gzip and ZIP, plus CRC-32.

```dawn
use inflate/gzip
use inflate/zip

let data = gzip.gunzip(src)?                       # at most 16 MiB out
let big = gzip.gunzip(src, cap: Some(268435456))?  # a larger ceiling
let files = zip.entries(archive)?                  # name, is_dir, data
```

## Output ceiling

Every entry point takes `cap: Option[Int]`, a ceiling on the bytes it may
write. It defaults to `deflate.DEFAULT_CAP`, 16 MiB. Pass `cap: Some(n)` for
another ceiling and `cap: None` for none. A refusal by the default says it
was the default and ends with `pass cap: Some(n) for a larger limit, or cap:
None for no limit`. `gzip.gunzip` applies its `cap` to all members
together and `zip.entries` to all entries together: a later member or entry
gets only what the earlier ones left.

## Gzip

`gzip.gunzip` reads the complete RFC 1952 stream. Concatenated members are
accepted and their payloads concatenated in order; each member's CRC-32 and
ISIZE are checked, FHCRC is verified when present, reserved flag bits are
rejected, and bytes after a trailer must begin another complete member, so
trailing garbage is an error rather than ignored.

## Raw DEFLATE

`deflate.inflate(src)` decodes a stream that starts at byte zero.
`deflate.inflate_from(src, from: k)` starts at offset `k` and also answers the
absolute offset just past the stream, which is what a container needs to find
its trailer. Its `cap` counts only the output of that call.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

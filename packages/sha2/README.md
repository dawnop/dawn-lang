# packages/sha2

SHA-256 (FIPS 180-4) in pure Dawn, with an incremental digest and a one-shot hex helper.

```dawn
use sha2/sha256

let one = sha256.hex(bytes)                       # 64 lower-case hex digits
let d = sha256.new() |> sha256.update(a) |> sha256.update(b)
let both = sha256.finish(d)                       # the digest of a then b
```

`Digest` is an opaque, immutable value: `update` answers a new one, and
`finish` does not consume it, so feeding can go on after a `finish`.

It is not fast, about 25 to 30 MB/s on either backend; the header of
`src/sha256.dawn` has the numbers.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

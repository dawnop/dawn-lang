# packages/sha2

SHA-256 (FIPS 180-4) in pure Dawn, with an incremental digest and a one-shot hex helper.

Manifest name **`sha2`**, version **2.0.0**. One module, `sha2/sha256`. The
name does not move at major 2: the v2-in-name rule asks a major of 2 or more to
end in its major, and the `2` already there (the SHA-2 family) satisfies it by
coincidence. A major 3 would have to decide the name again.

## Why it is a package

The package manager's content addressing, the `d1:` tree hash that makes the
package cache trustworthy, is computed with this code. `selfhost/dawn.toml`
and `compiler-plan/dawn.toml` both list it under `[deps]`, so sha2 is part of
the bootstrap closure: every change has to compile under the pinned seed
(`scripts/seed-release.txt`), and a wrong digest would break every locked
package. Ask `scripts/gate-map/gatemap.py` for the gates a change here
reaches; they include `scripts/selfhost-run-diff.sh` and
`scripts/selfhost-prev-diff.sh`.

It was written to stop the package manager reaching `java.security`: a hash is
arithmetic over bytes, so there is no reason for the trust root to be a host
service. Two faster options are closed on purpose: `MessageDigest` (about 150x
faster, and it puts the trust root back on the host) and a `sha256` runtime
intrinsic (the same objection one layer down, plus one more contract for every
backend). It is not in std because std is the small set of things the
language itself leans on, and nothing in the language leans on SHA-256.

It is slow, about 7.7 MB/s; the header of `src/sha256.dawn` has the numbers
and what has been done about them.

## Depending on it

Inside this repository, as a path dependency (the form `selfhost/dawn.toml`
uses):

```toml
[deps]
sha2 = "../packages/sha2"
```

From another repository, as a tag archive with a `subdir` (the form
dawnop-site uses). The hash is the `d1:` tree hash of the unpacked archive;
`dawn add <url> --subdir packages/sha2` fetches the archive and writes the
entry with it, and a mismatch error prints the actual value:

```toml
[deps.sha2]
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.82.0.zip"
version = "2.0.0"
hash = "d1:..."
subdir = "packages/sha2"
```

## Public API

All in `sha2/sha256`:

| Item | What it is |
|---|---|
| `Digest` | an opaque, immutable hashing state |
| `new()` | the empty state |
| `update(d, b)` | `d` with the bytes `b` fed in; call it any number of times |
| `finish(d)` | the digest as 64 lower-case hex digits; `d` is a value, so feeding can go on |
| `hex(b)` | the digest of `b` alone |

```dawn
use sha2/sha256

let d = sha256.update(sha256.update(sha256.new(), a), b)
let digest = sha256.finish(d)
```

The API is incremental because its caller is: a tree hash feeds one file after
another, and a one-shot digest would have to concatenate the whole tree first.

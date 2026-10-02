# packages/fspath

String functions over POSIX paths: normalize, resolve, join and split them without touching the filesystem.

Manifest name **`fspath`**, version **1.0.0**. One module, `fspath/fspath`.

## Why it is a package

The compiler is built from this source. `selfhost/dawn.toml` and
`compiler-plan/dawn.toml` both list it under `[deps]`, so fspath is part of
the bootstrap closure: every change has to compile under the pinned seed
(`scripts/seed-release.txt`), and a change to what a function returns shows
up in the compiler's own behaviour. `scripts/path-contract/run.sh` checks the
functions against `java.nio.file.Path.normalize`, which the compiler used
before this package existed. Ask `scripts/gate-map/gatemap.py` for the full
list of gates a change here reaches; it includes `scripts/selfhost-run-diff.sh`
and `scripts/selfhost-prev-diff.sh`.

It is not in std because nothing in the language is defined in terms of a
path and nothing here needs an intrinsic, while a std module is carried by
every program (audit RD-09 in `docs/audit/re-audit-2026-07-30.md`). It is
named `fspath` and not `path` because an imported module's alias shares the
namespace of local names, and `path` is one of the most common local names
there is.

The separator is `/`. The C runtime already spells `/` in its own filesystem
primitives, so the language's filesystem contract is POSIX-shaped.

## Depending on it

Inside this repository, as a path dependency (the form `selfhost/dawn.toml`
uses):

```toml
[deps]
fspath = "../packages/fspath"
```

From another repository, as a tag archive with a `subdir`. The hash is the
`d1:` tree hash of the unpacked archive; `dawn add <url> --subdir
packages/fspath` fetches the archive and writes the entry with it, and a
mismatch error prints the actual value:

```toml
[deps.fspath]
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.82.0.zip"
version = "1.0.0"
hash = "d1:..."
subdir = "packages/fspath"
```

```dawn
use fspath/fspath
```

## Public functions

All in `fspath/fspath`, subject first:

| Function | What it answers |
|---|---|
| `is_absolute(p)` | whether `p` starts at the root |
| `normalize(p)` | `p` without empty segments, `.` segments and `name/..` pairs; a `..` above the root is dropped, a leading `..` on a relative path is kept |
| `absolute(p, base)` | `p` resolved against `base` when relative, then normalized; `base` is passed in because reading the working directory is an effect |
| `parent(p)` | everything above `p`, or `None` for a bare name or the root |
| `join(base, p)` | `p` under `base`; an absolute `p` ignores `base` |
| `basename(p)` | the last segment, `""` for the root and the empty path |
| `extension(p)` | the extension without its dot, or `None`; `.gitignore` has none |
| `with_extension(p, ext)` | `p` with its extension replaced; an empty `ext` removes it |

# packages/fspath

String functions over POSIX paths: normalize, resolve, join and split them without touching the filesystem.

```dawn
use fspath/fspath

let p = fspath.normalize("a/./b/../c")             # "a/c"
let abs = fspath.absolute("src/main.dawn", "/srv")  # "/srv/src/main.dawn"
let dir = fspath.parent(abs)                       # Some("/srv/src")
let ext = fspath.extension("main.dawn")            # Some("dawn")
```

The separator is `/`. Nothing here reads the filesystem or the working
directory: `absolute` takes its base as an argument.

| Function | What it answers |
|---|---|
| `is_absolute(p)` | whether `p` starts at the root |
| `normalize(p)` | `p` without empty segments, `.` segments and `name/..` pairs; a `..` above the root is dropped, a leading `..` on a relative path is kept |
| `absolute(p, base)` | `p` resolved against `base` when relative, then normalized |
| `parent(p)` | everything above `p`, or `None` for a bare name or the root |
| `join(base, p)` | `p` under `base`; an absolute `p` ignores `base` |
| `basename(p)` | the last segment, `""` for the root and the empty path |
| `extension(p)` | the extension without its dot, or `None`; `.gitignore` has none |
| `with_extension(p, ext)` | `p` with its extension replaced; an empty `ext` removes it |

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

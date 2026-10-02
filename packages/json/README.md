# packages/json

A JSON (RFC 8259) parser and renderer in pure Dawn that keeps integers exact and reports errors a caller can branch on.

Manifest name **`json2`**, version **2.0.0**. Consumers keep writing
`use json/...` by aliasing the dependency as `json`; the name ends in its
major because of the v2-in-name rule.

## Why it is a package

The language server in the compiler reads and writes JSON-RPC with this code
(`selfhost/src/lsp/server.dawn`), and `selfhost/dawn.toml` lists it under
`[deps]`, so json is part of the bootstrap closure: every change has to
compile under the pinned seed (`scripts/seed-release.txt`), and the compiler's
LSP sessions, compared by `scripts/selfhost-lsp-diff.sh`, move with it. The
site, the playground, `packages/web` and `packages/tea-dom` depend on it too.
`scripts/json-suite.sh` runs the JSONTestSuite fixtures (accepted cases must
also survive parse, render, parse unchanged). Ask
`scripts/gate-map/gatemap.py` for the full list of gates a change reaches; it
includes `scripts/selfhost-run-diff.sh` and `scripts/selfhost-prev-diff.sh`,
whose corpus compiles this package (`emit packages/json`).

It is not in std because nothing in the language is defined in terms of JSON
and nothing here needs an intrinsic, while a std module is carried by every
program. It became a package to end the copies: before `[deps]` existed the
library was vendored four times, in three different versions
(`docs/package-design.md`).

## Depending on it

Inside this repository, as a path dependency (the form `selfhost/dawn.toml`
uses):

```toml
[deps]
json = "../packages/json"
```

From another repository, as a tag archive with a `subdir` (the form
dawnop-site uses). The hash is the `d1:` tree hash of the unpacked archive;
`dawn add <url> --subdir packages/json --as json` fetches the archive and
writes the entry with it, and a mismatch error prints the actual value:

```toml
[deps.json]
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.82.0.zip"
version = "2.0.0"
hash = "d1:..."
subdir = "packages/json"
```

## Public modules

| Module | Main items |
|---|---|
| `json/value` | `Json` (`JNull`, `JBool`, `JNum`, `JInt`, `JStr`, `JArr`, `JObj`), `JsonErrorKind` (`Syntax`, `Truncated`, `Trailing`, `Depth`, `NumberRange`), `JsonError` (`kind`, `offset`, `message`), `error_text` |
| `json/parser` | `parse(input) -> Result[Json, JsonError]`, `MAX_DEPTH` (512) |
| `json/render` | `render(j) -> String`, compact output |
| `json/lexer` | the scanner `parse` is built on (`scan_string`, `scan_number`, `skip_ws`, ...); public because the parser imports it, not because callers need it |

```dawn
use json/parser.{parse}
use json/render.{render}
use json/value.{Json, JObj, error_text}

match parse(text) {
  Ok(j) -> render(j)
  Err(e) -> error_text(e)
}
```

A number literal with no `.`, `e` or `E` becomes `JInt`, so ids, money in
minor units and epoch millis above 2^53 are not rounded; anything else becomes
`JNum`. Integers wider than 64 bits are rejected as `NumberRange`, which
carries the literal. Objects keep insertion order. Nesting deeper than
`MAX_DEPTH` is a `Depth` error, not a blown stack, and the parser never panics.

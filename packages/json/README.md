# packages/json

A JSON (RFC 8259) parser and renderer in pure Dawn that keeps integers exact and reports errors a caller can branch on.

```dawn
use json/parser.{parse}
use json/render.{render}
use json/value.{error_text}

fn reformat(text: String) -> String =
  match parse(text) {
    Ok(j) -> render(j)
    Err(e) -> error_text(e)
  }
```

## Contract

- A number with no `.`, `e` or `E` is a `JInt`, so ids, money in minor units
  and epoch milliseconds above 2^53 are not rounded; any other number is a
  `JNum`. An integer wider than 64 bits is a `NumberRange` error that carries
  the literal.
- Objects keep insertion order. `render` writes compact output.
- `parse` never panics. A `JsonError` has a `kind` to branch on (`Syntax`,
  `Truncated`, `Trailing`, `Depth`, `NumberRange`), a code-point `offset` and
  a `message`; nesting deeper than `MAX_DEPTH` (512) is a `Depth` error.
- `json/lexer` is public because the parser imports it; callers do not need it.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

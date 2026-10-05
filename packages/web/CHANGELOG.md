# web changelog

Newest first. From 2.0.0 the manifest name carries the major (`web2` ...
`web6`, the v2-in-name rule); consumers keep `use web/...` through a
`web = ...` alias. Design background: `docs/web5-design.md`,
`docs/std-defaults-design.md` and `docs/audit/web-api-v2-design.md` (in
Chinese).

## 6.2.1 (2026-10-05)

- `with_logging` times a request with std/io's `Clock` (`now` and
  `elapsed_ns`) instead of calling `System.nanoTime` through `use java`. The
  reading is the same monotonic clock, so the logged milliseconds do not
  change; the middleware module no longer binds a Java class. The clock
  handler is installed inside the handler `with_logging` returns, so
  `Handler` keeps its `!io` row and no application installs anything. A
  patch: no signature or log line changed. Needs a toolchain whose std/io
  has `Clock`.

## 6.2.0 (2026-10-05)

- `safe_rel(segs)` turns captured segments into a relative file path, or a
  `400` if any segment is empty, `.` or `..`, or contains `/`, `\` or NUL.
  The server's dot-segment `400` only sees a segment that *is* `.` or `..`,
  and a segment is decoded on its own, so `..%2F..` reached a handler as the
  single segment `../..`. Routing is unchanged: an encoded slash still stays
  inside its segment, and handlers that join captures into a path should
  call `safe_rel`. A minor: one new function, no behaviour changed.

## 6.1.1 (2026-10-05)

- The access log writes the path as the client sent it, percent-encoded, in
  `with_logging` and in the server's own refusal lines. Before, it wrote the
  decoded path, so `%0D%0A` in a request path broke the line and the rest of
  the path became a log line of the client's choosing. A path with non-ASCII
  text now logs as its `%XX` escapes.

## 6.1.0 (2026-10-04)

- Header values are ASCII only (SP, HTAB, `!` to `~`), for `with_header`,
  `redirect`, `error_response`'s headers and every content type. Before,
  jdk.httpserver wrote the low byte of each character, so U+010A and U+010D
  reached the wire as LF and CR. Percent-encode a `Location`; `attachment`
  encodes a filename itself. `escape_field` now escapes non-ASCII as `\u{...}`.
- A JVM `Error` in a handler (an `OutOfMemoryError`, a `StackOverflowError`)
  gets the neutral `500` when nothing was sent yet, and the exchange is
  closed; before, the client got no response.
- A minor: no signature changed, and what is refused now never reached the
  wire as written.

## 6.0.0 (2026-10-03)

Three suffixed pairs become one function each, the extra argument defaulted
and last. The suffixed names are gone, with no aliases.

| 5.x | 6.0 |
|---|---|
| `error_response_with(fmt, e)` | `error_response(e, fmt: fmt)` |
| `query_int_bounded_with(fmt, req, name, default, lo, hi)` | `query_int_bounded(req, name, default, lo, hi, fmt: fmt)` |
| `streaming_sized(status, ct, stream, n)` | `streaming(status, ct, stream, length: Some(n))` |

```dawn
# 5.x
let page = query_int_bounded_with(site_errors(), req, "page", 1, 1, -1)?
let r = error_response_with(site_errors(), e)
let s = streaming_sized(200, ct, stream, n)
# 6.0
let page = query_int_bounded(req, "page", 1, 1, -1, fmt: site_errors())?
let r = error_response(e, fmt: site_errors())
let s = streaming(200, ct, stream, length: Some(n))
```

Calls without a format or a length are unchanged. `serve_app` /
`serve_app_with` and `json_ok` stay as they were.

## 5.2.0 (2026-10-01)

`ErrorFormat` gains `body_too_large`, `not_found`, `method_not_allowed` and
`dot_segment`, so the server's own `413`, `404`, `405` and dot-segment `400`
are worded by the application too. `ErrorFormat` no longer derives `Show`.
Code using `default_errors()` or `..default_errors()` is unaffected; a record
literal naming every field has to add the four.

## 5.1.0 (2026-10-01)

`body_limit(route, n)` and `guarded(route, g)`: a per-route body ceiling and a
guard that runs before the body is read. Before, a `stream-body` route spilled
the whole body to disk before any handler code ran, with no ceiling of its
own.

## 5.0.0 (2026-09-25)

- `Response` is opaque: build it with the constructors, read it with
  `response_status` and the other readers.
- `ServerHandle` is opaque, with `join`, `stop` and `handle_port`.
- A body ceiling must be positive: `start` panics on a non-positive
  `max_body`, and so does `with_body_limit`. `0` used to mean unbounded; a
  route that needs more says so with `raw-body`, `stream-body` or
  `body_limit`. `serve_app_bounded` is gone; set `max_body` in the
  `ServerConfig` given to `serve_app_with`.
- `dispatch_segs`, `validate_routes`, `route_meta` and `Dispatch` are
  package-private.

## 4.0.0 (2026-08-20)

`Request.body` is the wire bytes (`Bytes`; the old `raw` renamed onto it), and
`body_text(req)?` is the checked UTF-8 view, a `400` on a malformed body.
The lossy `body: String` is gone; `bytes.decode_utf8_lossy(req.body)` is the
one-line replacement for a caller that wants it.

## 3.2.0 (2026-08-17)

A refused header is escaped (`escape_field`) before the refusal names it, in
the log line and in the `400` body.

## 3.1.0 (2026-08-16)

The server checks the content type and every header again where it writes a
response. A streaming body's upstream failure, a client hang-up and a panic
are logged as three outcomes. A `205` no longer carries a body.

## 3.0.0 (2026-08-11)

- `Request.query` and `parse_form`'s result are multimaps; `query_all`,
  `form_value` and `form_all` are new, and the single-value readers return the
  first value.
- `Request.params` holds the segments a capture matched; `param_segs` reads a
  tail capture and `param` refuses one. Until 3.0 a tail capture was joined
  with `/`, so `/dav/a%2Fb/c` and `/dav/a/b/c` reached the handler as the same
  path.
- `with_header` refuses an illegal name or value instead of deleting
  characters; `header_value` is gone, `valid_header_name` and
  `valid_header_value` replace it; `try_with_header` and `try_redirect` answer
  `400` for input-derived values.
- The dot-segment `400` and the body-limit `413` run under the middleware
  chain, so `with_cors` stamps them.

## 2.2.1 (2026-08-09)

Deleting a spilled body file distinguishes a file that was already gone from
one that could not be deleted. No API change.

## 2.2.0 (2026-08-08)

`with_cors` stamps error responses too; before, a cross-origin `4xx`/`5xx`
had no `Access-Control-*` headers and the page could not read the error body.

## 2.1.0 (2026-08-06)

`ErrorFormat` and `ServerConfig.errors`: the error body's key, the `500`
message and the `422` separator are configuration rather than one consumer's
strings. `with_cors` answers only a real preflight (both `Origin` and
`Access-Control-Request-Method`); any other `OPTIONS` reaches the
application's route.

## 2.0.0 (2026-08-05)

`start`, `join` and `stop` on a `ServerHandle`. Published as `web2`.

## 1.0.0 (2026-07-22)

backend-dawn's framework adopted as a package.

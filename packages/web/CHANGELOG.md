# web changelog

## 9.0.0

- **Breaking:** the package identity is `web9`. `text`, `json_response`, `raw`,
  `binary`, `streaming`, `with_header`, `redirect`, `try_redirect`, `attachment`
  and `error_response` gain a trailing `at: Loc = caller()`. A refusal now
  names the application's constructor call instead of a framework line.
  Status, stream-length and framing refusals use the same location.
- Direct calls can omit `at`. Function values gain a required `Loc` argument;
  wrappers that report on behalf of their caller declare and forward `at`.
  No compatibility entry points are provided. `json_ok` and `try_with_header`
  keep their signatures. Returned 400 errors keep their existing wording.
- `error_response` attributes an illegal HttpError header to its rendering
  call; the public error record does not store its construction location.
- See [the migration guide](MIGRATION.md) for the downstream dependency bump.

## 8.0.0

- **Breaking:** `BodySource.read(n)` becomes `read(pos, n)`. Each server pump
  starts at byte offset zero and advances by the actual length returned,
  including short reads. A source is consumed once, sequentially. Every
  custom source literal and direct read call must accept/pass both arguments.
- Add `web/source.bytes_source` and `file_source`, pure Dawn adapters on both
  backends. Files use `read_range` without an open handle or mutable cursor.
  A read failure terminates the transfer and still closes the source.
- The package identity is `web8`; use `web_jvm2` 2.0.0 from the same tag for
  the JVM server. Dependency aliases and import paths stay `web`/`web_jvm`.
  `input_source` ignores the supplied offset because InputStream owns its
  sequential cursor. Its ready-byte behavior is unchanged.
- HEAD and no-body statuses still close without reading. Fixed and chunked
  framing, short/long stream detection and close ownership are unchanged.
- See [the migration guide](MIGRATION.md), including the dawnop-site S7 impact.

Newest first. From 2.0.0 the manifest name carries the major (`web2` ...
`web9`, the v2-in-name rule); consumers keep `use web/...` through a
`web = ...` alias. Design background: `docs/web5-design.md`,
`docs/std-defaults-design.md`, `docs/audit/web-api-v2-design.md` and
`docs/web-core-split-design.md` (in Chinese).

## 7.2.0 (2026-10-21)

Added, nothing removed or changed for a caller of 7.1:

- **`web/exchange.stdio_transport()`**, the `Transport` of a process handed one
  accepted connection as stdin and stdout: `read` takes the next `n` bytes of
  stdin (the position is ignored), `write` puts the bytes on stdout and flushes
  them, so each piece of a streamed body reaches the peer when it is written.
  Stdout is the wire, so the process logs to stderr
  (`with_logging_to_stderr`). It rides std's `write_stdout` and `flush_stdout`
  (docs/io-prims-design.md).
- **A "stream-body" upload no longer passes through memory in `web/exchange`.**
  The temp file is made first and the body is read, appended
  (`std/io.append_bytes`) and dropped 64 KiB at a time, for a counted and a
  chunked body alike. A 256 MiB PUT peaks at 16 MiB resident where it peaked
  at the size of the body; the `Request` a handler sees, the statuses and the
  ceilings are unchanged, and a body that ends early, is malformed or crosses
  the ceiling still leaves no file behind. `web_jvm/server` already streamed.

## 7.1.0 (2026-10-21)

Added, nothing removed or changed for a caller of 7.0:

- **`web/exchange`: a server that serves one request.** `serve_exchange(cfg,
  routes, middleware, transport)` reads one HTTP/1.1 request through a
  `Transport` (`read(pos, n)` and `write(bytes)`, no backend named), runs the
  application and writes the response, `Connection: close`, and returns. It is
  pure Dawn, so the native compiler builds it: a process handed one accepted
  connection as stdin and stdout serves its request with it and exits. It
  decodes `Content-Length` and chunked request bodies (extensions read, trailers
  dropped), answers a malformed body with a 400, applies the body ceilings
  (`ExchangeConfig.max_body`, a route's `body_limit`, the `raw-body` and
  `stream-body` tags), runs a route's guard before the body is read, refuses a
  dot segment, frames the response (exact length, chunked for a stream of unknown
  length, no body for 1xx, 204, 205, 304 and for HEAD) and writes a streaming
  body piece by piece. `exchange_config()` is the neutral configuration.
  docs/web-core-split-design.md section 9 has the semantics list and the
  contract that holds it byte for byte to `web_jvm/server`.
- **`with_logging_to_stderr`**, `with_logging` with the line on stderr. On a
  single-exchange transport stdout is the response, so a log line there is bytes
  of it.
- **The decisions a server makes after the parse are public** because both
  servers now call the same ones: `meta_of`, `meta_has_tag`, `guard_of`,
  `run_guard`, `body_ceiling`, `run_dispatch` and `serve_through` (dispatch, the
  guard, the body ceiling, the middleware chain and what a panic answers), and
  `framing` with `Framing` (`Withheld`, `Sized`, `Chunked`), `drop_body`,
  `close_source`, `pump_with`, `PumpOutcome` and `pump_report` (response framing
  and how a streaming body ends). They are for authors of servers.

## 7.0.0 (2026-10-20)

The package is pure Dawn now: the JVM server moved to its own package,
`web-jvm` (manifest name `web_jvm`, starting at 1.0.0), and a response body that
streams no longer carries a Java type. The native compiler checks, documents
and tests `web` as a whole package. The package is `web7`; keep `use web/...`
through the `web = ...` alias as before.

Breaking, and how to migrate:

- **`web/server` is gone; its server is `web_jvm/server`, in a new package.**
  `start`, `join`, `stop`, `serve_app`, `serve_app_with`, `ServerConfig`,
  `ServerHandle` and `handle_port` have the same signatures there. Add
  `web_jvm = "<path or url>/web-jvm"` to `[deps]` beside `web`, and change
  `use web/server.{...}` to `use web_jvm/server.{...}`. The two packages must be
  the same checkout or release.
- **`parse_form`, `form_value` and `form_all` moved to `web/wire`.** Change the
  import. `parse_form` is a pure function now, so it has no `!io` row.
- **`DEFAULT_MAX_BODY` moved to `web/types`**, since every server starts from it.
- **`streaming` takes a `BodySource`, not an `InputStream`**, and the
  `ResponseBody` variant is `Stream(source: BodySource, length: Option[Int])`.
  A `BodySource` is `{ read: fn(Int) -> Bytes !io, close: fn() -> Unit !io }`:
  `read(n)` returns at most `n` bytes and an empty `Bytes` at the end, and the
  server calls `close` exactly once, read or not. For an `InputStream`, pass
  `web_jvm/server.input_source(stream)`:
  `streaming(200, "video/mp4", input_source(stream), length: Some(n))`.
  `input_source` hands the server what the stream has ready, as the old pump
  did, rather than waiting to fill a chunk.
- **A `ResponseBody` and a `Response` have no `==`.** A stream holds
  functions, and a function has no equality, so `response_body(r) == Text("x")`
  is now a type error. Match on the body instead.
- **Percent decoding is the standard library's, not `URLDecoder`'s.** A
  malformed escape still leaves the whole component as written, and a byte
  sequence that is not UTF-8 still becomes U+FFFD. One difference: the JDK
  decoder accepted a sign in an escape, so `%+1` decoded to byte 1; it is now
  malformed, as RFC 3986 has it.

Added to the public surface, because a server in another package needs them
(web5 had kept them package-private while the server lived inside): `Dispatch`
with `dispatch_segs`, `validate_routes`, `route_meta` in `web/router`;
`raw_segs`, `decode_path_seg`, `has_dot_segment`, `parse_query`, `multimap`,
`join_with` in `web/wire`; `log_request` in `web/types`. They are for authors
of servers; `Response` stays opaque and a server reads one through
`response_status`, `response_content_type`, `response_headers` and
`response_body`.

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

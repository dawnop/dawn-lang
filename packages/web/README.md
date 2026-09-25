# packages/web

A small HTTP/1.1 framework over `jdk.httpserver`: routes are data, handlers
are `fn(Request) -> Result[Response, HttpError] !io`, middleware are handler
transformers. nginx (or similar) terminates TLS in front.

## Path handling (WEB-03)

Routing runs on the **raw** request path (`Request.raw_path`): it is split on
`/` first, then each segment is percent-decoded on its own. An encoded slash
(`%2F`) therefore stays inside its segment and never creates a route
boundary — `/files/a%2Fb` reaches `/files/{name}` with `name = "a/b"`. The
decoded `Request.path` is kept for logs and display only.

| Case | Policy |
|---|---|
| Dot segments (`/a/../b`, `/a/./b`, encoded spellings like `%2e%2e`) | Rejected with `400` in the server, before routing, on every path — 404 paths included. The framework never normalizes a path; normalizing in front of a router is a classic traversal-bypass source. |
| Duplicate slash (`/a//b`) | The empty segment is kept: `/a//b` has three segments and does not match `/a/b`. A capture matches an empty segment; a literal never does. Merging slashes is path rewriting — the application's business. |
| Trailing slash (`/a/`) | Tolerated, as the router always has: it matches the same route as `/a`. |

Captures are held as the **segments** they matched (`Request.params` is
`Map[String, List[String]]`): one for a `{name}` capture, however many remain
for a trailing `{name*}`. Read them with `param` and `param_segs`.

Until 3.0 a tail capture was handed over as `join(segments, "/")`, which put
back exactly the ambiguity the raw-path split removes: a `/` that arrived
percent-encoded inside one segment became a separator again, so a WebDAV
handler could not tell `/dav/a%2Fb/c` from `/dav/a/b/c` and resolved both to the
same file. `param` refuses to read a tail capture (500, naming `param_segs`)
rather than silently picking one segment; a caller that does want a joined path
joins them itself, and thereby says so.

## Request headers (WEB-04)

`Request.headers` is a lowercase-keyed multimap (`Map[String, List[String]]`):
every value of a repeated name (`Cookie`, `Forwarded`, ...) survives in wire
order. `header(req, name)` returns the first value — the one the old
single-value map held — and `headers_all(req, name)` returns them all. Both
lowercase the name they are given, and the server lowercases keys when it
builds the map; that pair of lowercasings is the whole case-insensitivity
contract.

## Query strings and form bodies (3.0)

`Request.query` is a multimap (`Map[String, List[String]]`), the same shape as
`Request.headers`, and so is what `parse_form` returns. A query string is a list
of pairs rather than a mapping, and `?tag=a&tag=b` is how a client spells a set;
`<select multiple>` submits the same way. Both used to be
`Map[String, String]`, where the last value silently won and nothing recorded
that anything had been dropped.

| read | one value | all of them |
|---|---|---|
| query | `query(req, name)` | `query_all(req, name)` |
| form | `form_value(f, name)` | `form_all(f, name)` |
| header | `header(req, name)` | `headers_all(req, name)` |

The single-value readers return the **first** value, which is what the
single-value map effectively held for a caller that never repeats a name.
`query_int_bounded` reads through `query`, so it is unaffected.

`Request.params` is a list for a different reason (see "Path handling" above):
it holds the *segments* a capture matched, not repeated values. A duplicate
capture name is a route-table error that `validate_routes` refuses at startup,
so no path parameter ever has two values.

## Request body (4.0)

`Request.body` is the wire bytes (`Bytes`), exactly as they arrived. The UTF-8
view is an accessor:

```dawn
let source = body_text(req)?   # 400 on a malformed body, naming the byte offset
```

Binary handlers (multipart upload) parse `req.body` directly; routes tagged
`stream-body` still get a temp-file path in `body_file` and an empty `body`.

Until 4.0 a `body: String` field sat next to the bytes (then named `raw`),
filled by an unconditional `decode_utf8_lossy` every request paid for, upload
routes included. Lossy is the wrong default at a trust boundary: a malformed
body reached the handler silently rewritten, and a `U+FFFD` in it was
indistinguishable from one the client sent. Refusing with `400` is what axum
and actix-web do on the same input; a caller that truly wants the lossy view
still has `bytes.decode_utf8_lossy(req.body)`, one line, stated at the call
site.

## Responses (5.0)

`Response` is opaque. It comes from the constructors (`text`, `json_response`,
`json_ok`, `raw`, `binary`, `streaming`, `streaming_sized`, `redirect`,
`attachment`, `error_response`) and from `with_header`, and it is read with
`response_status`, `response_content_type`, `response_headers` and
`response_body`. There is no literal, so there is no response that skipped the
checks the constructors make, and those checks are the only ones: the server
writes what it is given. (Until 5.0 a record literal could build anything, and
3.1 re-checked headers at the write boundary to catch it.)

What a constructor refuses, it refuses with a panic, which the per-request
isolation renders as a `500`, the same verdict `with_header` has always given a
header the program built out of its own strings:

| Check | Rule |
|---|---|
| status | `200..599`. jdk.httpserver sends any number as written (`99`, `600`, `-5`), and a final `100` leaves the client waiting for a response that never comes. There is no `1xx` here: nothing in this framework sends an interim response. |
| content type | A legal header value, like any other: `raw`/`binary`/`streaming` pass it straight to `Content-Type`. |
| `Transfer-Encoding` | Never accepted from a handler. The body kind decides the framing; a handler's copy used to go out next to the JDK's own `Content-length`, which RFC 9112 §6.1 forbids. |
| `Content-Length` | A decimal byte count, once, equal to the body's length when the body has content. Any count is accepted on a body with no content, because that is how a `HEAD` answer states the length of what it does not carry. Never on a stream of unknown length. |

An `HttpError` stays a plain record. Its status is checked where it is rendered:
out of range, it becomes the neutral `500` (`ErrorFormat.internal_message`),
with its headers kept so a CORS stamp still reaches the browser.

The status check is a range, not a closed enumeration. `docs/audit/web-api-v2-design.md`
(section 4) turned down a `Method`/`Status` type because a closed set needs an
`Other(String)` escape hatch, which is a `String` with extra steps. That argument
does not apply here: the status is still an `Int`, any code in `200..599` is
accepted, and what is refused was never valid HTTP. Route methods get the same
treatment at startup: `validate_routes` refuses a method that is not an
uppercase token (`route_method_of("get", ...)` used to be accepted and then never
matched anything, since methods are compared exactly).

Checked `HeaderName`/`HeaderValue` types are deliberately absent. With `Response`
opaque, `with_header` is the one way a header gets in, and it already checks
the name, the value and the framing rules; a second type would state the same
invariant twice. WAI, Plug, http4s and Ktor draw the line the same way.

### Streams of a known length

`streaming(status, content_type, stream)` is chunked: the length is unknown,
and so an upstream that ends early with a clean EOF looks exactly like one that
delivered everything. When the length is known (an object store's
`Content-Length`), `streaming_sized(status, content_type, stream, length)` sends
it as an exact `Content-Length`. The server counts what it pumps; a short
upstream is logged as a truncation, and the connection ends before the promised
length, so the client can tell as well.

## Server lifecycle and limits (5.0)

`start` returns an opaque `ServerHandle`: `join` blocks on it, `stop` ends it,
`handle_port` reads the port it bound (the point of `port: 0`). It used to be a
public record, which let a caller hand `stop` an executor it never owned.

A body ceiling is a positive byte count. `start` panics on a non-positive
`ServerConfig.max_body` before binding, and `with_body_limit` panics when it is
built with one. Until 5.0, `0` meant unbounded, which made the value most likely
to be a slip the one that switched the guard off. Routes that legitimately take
more say so with a tag: `raw-body` (bounded by nginx in front) or `stream-body`
(spilled to disk, never held in memory). `serve_app_bounded` is gone; set
`max_body` in the `ServerConfig` passed to `serve_app_with`.

The router's dispatch machinery (`dispatch_segs`, `validate_routes`,
`route_meta`, `Dispatch`) is package-private since 5.0: `start` is what runs
it.

## CORS and OPTIONS (2.1)

`with_cors` answers a **preflight** itself and lets everything else through to
the routes. A preflight is an `OPTIONS` carrying *both* `Origin` and
`Access-Control-Request-Method` — the pair the Fetch standard says a browser
sends before a non-simple cross-origin request. Either header alone names
something else: a bare `OPTIONS` is a client asking what the server supports (a
WebDAV client reading `DAV`/`Allow`, `curl -X OPTIONS`), and `Origin` without
the request-method header is an ordinary cross-origin `OPTIONS`. Both reach the
application's own `OPTIONS` route and are stamped like any other response.

Until 2.1 every untagged `OPTIONS` was answered with a `204` and the handler was
never called, so an application's `OPTIONS` route was unreachable unless it
opted out of CORS entirely (the `no-cors` tag, which also drops the
`Access-Control-*` stamping).

The stamp covers the `Err` branch as well: an `HttpError` gets the same headers,
and `error_response_with` renders them onto the response. Until 2.2 the error
branch was written `next(req)?`, which handed the `Err` past the stamp — a
cross-origin `4xx`/`5xx` arrived with no `Access-Control-*` at all and the
browser refused to let the page read the error body.

Since 3.0 it covers the server's own two early refusals too: the `400` for a
dot segment and the `413` for an oversized body. Both are decided before the
body is read, and used to be rendered before the middleware chain on the grounds
that there was no `Request` yet. There is: everything a `Request` holds apart
from the body comes off the request line and the headers. What the middleware
sees on those paths is honest but partial. `body` is empty, because
not reading the body is the whole point of refusing this early;
`with_body_limit`, which reads `body`, passes. The dot-segment check runs after
dispatch so that its `400` carries the matched route's tags: a WebDAV path is
`no-cors` whether or not it contains a dot segment.

## Response headers (3.0)

A field value is one line by definition (RFC 9110 §5.5) and a field name is a
token, so neither a `CR`/`LF` nor a `:` can travel inside one. `with_header`
**refuses** what cannot travel: an illegal name or value panics, which the
per-request isolation renders as a `500`.

Until 3.0 it deleted the offending characters instead. That closed the
response-splitting injection and opened a quieter hole in its place:
`?next=/a%0d%0aX:%201` came back as `Location: /aX: 1`, a redirect to a URL the
application never named, with no error anywhere and no way for the caller to
learn that the value it handed over is not the value that went on the wire.
`pub fn header_value(v) -> String` is gone; `valid_header_name` and
`valid_header_value` are the predicates it should have been.

For a name or value derived from request input there is `try_with_header` /
`try_redirect`, which answer `400` instead of panicking:

```dawn
let r = try_redirect(302, next_from_query)?
```

`attachment` needs neither: `filename=` is escaped into a quoted-string and
`filename*=` is percent-encoded per RFC 5987, so both parameters are legal by
construction whatever the filename is.

The refusal names what it refused, through `escape_field` (3.2): a value held
back for carrying a `CR` must not carry it into the log line the panic becomes,
or into the `400` body. What that escapes is exactly what `valid_header_value`
refuses, so `SP` and `HTAB` come through untouched.

## Error wording (2.1)

The framework renders three strings of its own: the JSON key of an error body,
the `500` it writes for a failure of its own (a handler panic, a request body it
could not spill to disk), and the separator between a parameter's name and the
complaint in `query_int_bounded`'s `422`. They are
`ErrorFormat`, defaulting to neutral English:

```
{"error": "..."}      "internal server error"      "size: Input should be ..."
```

An application that must reproduce another server's bytes states them once:

```dawn
let fastapi = ErrorFormat {
  detail_key: "detail", internal_message: "...", param_separator: "：",
}
serve_app_with(ServerConfig { host: "127.0.0.1", port: 8001, max_body: DEFAULT_MAX_BODY, errors: fastapi },
  routes, middleware)
```

and passes the same value to `error_response_with` / `query_int_bounded_with`
where it renders errors itself. Before 2.1 those three strings were hardcoded to
what one consumer (dawnop-site, whose frontend was written against FastAPI)
needed — including a Chinese `500` message and pydantic's fullwidth colon — and
`ServerConfig` had no `errors` field.

# packages/web

A small HTTP/1.1 framework over `jdk.httpserver`: routes are data, handlers are `fn(Request) -> Result[Response, HttpError] !io`, middleware are handler transformers.

```dawn
use web/types.{Request, Response, HttpError, text, param}
use web/router.{route_get}
use web/server.{serve_app}
use web/middleware.{with_logging}

fn hello(req: Request) -> Result[Response, HttpError] !io = {
  let name = param(req, "name")?
  Ok(text(200, "hello, ${name}\n"))
}

pub fn main() -> Unit !io =
  serve_app(8001, [route_get("/hello/{name}", hello)], [with_logging])
```

TLS is terminated in front of it (nginx or similar).

## Paths

Routing runs on the raw request path: it is split on `/` first and each
segment is then percent-decoded on its own, so `/files/a%2Fb` reaches
`/files/{name}` with `name = "a/b"`. `Request.path` is the whole path
decoded at once: a decoded `%0A` is a line break, so log `Request.raw_path`,
as `with_logging` does.

| Path | What happens |
|---|---|
| A dot segment (`/a/../b`, `/a/./b`, `%2e%2e`) | `400` before routing, on every path. Nothing is normalized. |
| A doubled slash (`/a//b`) | Kept: three segments, which do not match `/a/b`. A capture matches an empty segment; a literal does not. |
| A trailing slash (`/a/`) | Matches the same route as `/a`. |

`param(req, name)` reads a `{name}` capture. A trailing `{name*}` capture is
a list of segments and is read with `param_segs`; `param` refuses it with a
`500`, so a caller that wants one string joins the segments itself.

A capture is not a file path. The `400` above covers a segment that *is*
`.` or `..`, but each segment is decoded on its own, so `..%2F..` reaches the
handler as the one segment `../..`. To turn captures into a path under some
base directory, use `safe_rel(segs)?`: it refuses (`400`) any segment that is
empty, `.` or `..`, or contains `/`, `\` or NUL, and joins the rest with `/`.
For a single capture, `safe_rel([param(req, name)?])?`. Never locate a file
with `Request.path` or `Request.raw_path`.

## Requests

`Request.headers`, `Request.query` and `parse_form`'s result are multimaps
(`Map[String, List[String]]`) that keep every repeated value in wire order.
Header names are lowercased on both sides.

| read | the first value | all of them |
|---|---|---|
| header | `header(req, name)` | `headers_all(req, name)` |
| query | `query(req, name)` | `query_all(req, name)` |
| form | `form_value(f, name)` | `form_all(f, name)` |

`Request.body` is the bytes as they arrived. `body_text(req)?` is the UTF-8
view, and a malformed body is a `400` naming the byte offset. A route tagged
`stream-body` gets its body spilled to a temp file in `body_file` and an
empty `body`.

## Body ceilings and guards

`ServerConfig.max_body` is the server's ceiling, a positive byte count
(`DEFAULT_MAX_BODY` unless set). A route can change it or check a request
before any of the body is read:

```dawn
let tags = ["raw-body", "no-cors", "stream-body"]
let put = guarded(
  body_limit(tagged(route_put("/dav/{rest*}", put_file), tags), 4294967296),
  check_credentials,
)
```

- `body_limit(route, n)` replaces `max_body` for that route, up or down. It
  bounds a `raw-body` route, which is otherwise unbounded, and on a
  `stream-body` route it refuses an over-long `Content-Length` before the temp
  file exists and stops a spill that counts past it. Over the ceiling is a
  `413`.
- `guarded(route, g)` runs `g: fn(Request) -> Result[Unit, HttpError] !io`
  before the body is read. The request it sees has everything but the body;
  an `Err(e)` is answered as `e` and nothing is read or written to disk.
- Tags: `raw-body` (no ceiling unless `body_limit` sets one), `stream-body`
  (spilled to disk), `no-cors` (left alone by `with_cors`).

## Responses

`Response` is opaque. Build one with `text`, `json_response`, `json_ok`,
`raw`, `binary`, `streaming`, `redirect`, `attachment` or `error_response`,
add headers with `with_header`, and read it back with `response_status`,
`response_content_type`, `response_headers` and `response_body`. A
constructor refuses what HTTP cannot carry with a panic, which the server
answers as a `500`:

| Check | Rule |
|---|---|
| status | `200..599` |
| header names | an HTTP token |
| header values and content types | ASCII only: SP, HTAB and `!` to `~` |
| `Transfer-Encoding` | never set by a handler; the body kind decides the framing |
| `Content-Length` | once, and equal to the body's length when the body has content (a `HEAD` answer may state any length); never on a stream of unknown length |

For a header value built from request input, `try_with_header` and
`try_redirect` answer `400` instead of panicking. Non-ASCII text has to be
encoded first:

```dawn
# a Location: percent-encode the path
let r = try_redirect(302, "/files/caf%C3%A9")?
# a download name: attachment writes filename= and filename*= itself
let d = attachment("text/plain", "\u{4e2d}\u{6587}.txt", body)
```

`streaming(status, content_type, stream)` is chunked. With
`length: Some(n)` it sends `Content-Length: n` instead, and a stream that ends
short is logged and the connection is closed before `n`, so the client can
tell.

An `HttpError` whose status is outside `200..599` is answered as the neutral
`500`, keeping its headers.

## Server

`start(cfg, routes, middleware)` binds and answers a `ServerHandle`: `join`
waits on it, `stop` ends it, `handle_port` reads the bound port (for
`port: 0`). `serve_app(port, routes, middleware)` and `serve_app_with(cfg,
routes, middleware)` start and join in one call. `start` refuses a route
table it cannot dispatch (a method that is not an uppercase token, a bad
pattern, a route an earlier one shadows) and a `max_body` that is not
positive, before it binds. A handler that panics, or fails with a JVM
`Error`, gets a `500` if nothing was sent yet, and the exchange is always
closed.

## CORS

`with_cors` answers a preflight itself: an `OPTIONS` that carries both
`Origin` and `Access-Control-Request-Method`. Any other `OPTIONS` reaches the
application's own route. Every other response is stamped with the
`Access-Control-*` headers, error responses and the server's own early `400`
and `413` included, unless the route is tagged `no-cors`.

## Error wording

Every error body the framework writes itself is worded by an `ErrorFormat`
(`default_errors()` is neutral English):

| field | used for | default |
|---|---|---|
| `detail_key` | the JSON key of every error body | `{"error": "..."}` |
| `internal_message` | its own `500` | `"internal server error"` |
| `param_separator` | between a parameter's name and the complaint in `query_int_bounded`'s `422` | `"size: Input should be ..."` |
| `body_too_large` | the `413`, given the ceiling in bytes | `"request body exceeds N bytes"` |
| `not_found` | the `404` | `"Not Found"` |
| `method_not_allowed` | the `405` | `"Method Not Allowed"` |
| `dot_segment` | the `400` for a dot segment | `"path contains a dot segment"` |

Set the fields to change and spread the rest:

```dawn
let site = ErrorFormat {
  ..default_errors(),
  detail_key: "detail",
  body_too_large: n => "upload limit is ${n} bytes",
}
let cfg = ServerConfig {
  host: "127.0.0.1", port: 8001, max_body: DEFAULT_MAX_BODY, errors: site,
}
serve_app_with(cfg, routes, middleware)
```

and pass the same value as `fmt:` where the application renders errors
itself: `error_response(e, fmt: site)`, `query_int_bounded(req, "page", 1, 1,
-1, fmt: site)`.

Changes between versions, with migration notes: [CHANGELOG.md](CHANGELOG.md).

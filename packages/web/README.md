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

## Request headers (WEB-04)

`Request.headers` is a lowercase-keyed multimap (`Map[String, List[String]]`):
every value of a repeated name (`Cookie`, `Forwarded`, ...) survives in wire
order. `header(req, name)` returns the first value — the one the old
single-value map held — and `headers_all(req, name)` returns them all. Both
lowercase the name they are given, and the server lowercases keys when it
builds the map; that pair of lowercasings is the whole case-insensitivity
contract.

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

## Error wording (2.1)

The framework renders three strings of its own: the JSON key of an error body,
the `500` it writes when a handler panics, and the separator between a
parameter's name and the complaint in `query_int_bounded`'s `422`. They are
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

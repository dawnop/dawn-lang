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

`Request.params` stays `Map[String, String]`: a duplicate capture name is a
route-table error that `validate_routes` refuses at startup, so a path parameter
has exactly one value by construction and there is nothing for a list to hold.

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

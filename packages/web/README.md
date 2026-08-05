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

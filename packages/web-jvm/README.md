# packages/web-jvm

The JVM server for [`packages/web`](../web): `jdk.httpserver` underneath, one virtual thread per request. It is the only part of the web framework with a `use java`; `packages/web` is pure Dawn, so the native compiler can check, document and test it.

```dawn
use web/types.{Request, Response, HttpError, text, param}
use web/router.{route_get}
use web/middleware.{with_logging}
use web_jvm/server.{serve_app}

fn hello(req: Request) -> Result[Response, HttpError] !io = {
  let name = param(req, "name")?
  Ok(text(200, "hello, ${name}\n"))
}

pub fn main() -> Unit !io =
  serve_app(8001, [route_get("/hello/{name}", hello)], [with_logging])
```

```toml
[deps]
web = "../packages/web"
web_jvm = "../packages/web-jvm"
```

## What is in `web_jvm/server`

| | |
|---|---|
| `start(cfg, routes, middleware)` | binds and answers a `ServerHandle`; `join` waits on it, `stop` ends it, `handle_port` reads the bound port (for `port: 0`) |
| `serve_app(port, routes, middleware)`, `serve_app_with(cfg, routes, middleware)` | start and join in one call |
| `ServerConfig` | host, port, `max_body`, and the `ErrorFormat` for the errors the server words itself |
| `input_source(stream)` | a `web/types.BodySource` over a Java `InputStream`, for `streaming(...)` |

`start` refuses a route table it cannot dispatch and a `max_body` that is not positive, before it binds. A handler that panics, or fails with a JVM `Error`, gets a `500` if nothing was sent yet, and the exchange is always closed. Everything else (requests, responses, routing, guards, body ceilings, CORS, error wording) is documented in `packages/web`.

This package starts at 1.0.0 with the server API `web` 6 had in `web/server`; see `packages/web/CHANGELOG.md`, 7.0.0, for the migration.

## 1.1.0

A request body the JDK's stream cannot read (a chunk size that is not hex, a chunk cut short, a body that ends before its `Content-Length`) is answered `400` with `{"error":"malformed request body"}`. It was a `500`: the exception went up as a panic. A temp file for a spilled body is still removed. The same failures get the same answer from `web/exchange` (the single-exchange server of `packages/web`), and `scripts/web-exchange-contract` holds the two servers to the same bytes. The server now calls the shared decisions that `web` 7.1 made public (`serve_through`, `body_ceiling`, `framing`, `pump_with` and the rest) instead of keeping its own copies. Needs `web` 7.1.


## 2.0.0

This major pairs with `web9` 9.0.0 from the same release tag. The package
identity is `web_jvm2`; retain the `web_jvm` dependency alias and imports.
`BodySource.read` now takes `(pos, n)`, and the JVM pump supplies the actual
number of bytes already sent. `input_source(stream)` ignores `pos` because
an InputStream maintains its own sequential cursor: the server consumes it
once, in order, without seeking or replaying reads. The adapter still waits
for one byte and then takes only the bytes already available, up to `n`.
Custom sources must migrate their callbacks; there is no old-signature alias.
Pure Dawn Bytes and file adapters are in `web/source` and also work here.
See [the web migration guide](../web/MIGRATION.md).

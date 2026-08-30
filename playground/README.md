# dawn-play

The Dawn Playground runner: an HTTP service, **written in Dawn**, that compiles
and runs untrusted Dawn source in a throwaway sandbox and streams back the
output. It is the first real server written in Dawn — a warm-up for the M6 blog
backend rewrite, dogfooding the `use java` interop trio (SAM conversion, opaque
arrays, the List bridge; spec §9.4–§9.6).

Zero async in the language: HTTP is `jdk.httpserver` on JVM 21 virtual threads
(thread-per-request), nginx terminates TLS in front, the sandbox is a transient
`systemd-run` unit per request.

Live completion, hover, definition and diagnostics use a separate, bounded
standard-library Python gateway. One WebSocket owns one native `dawnc lsp`
process and one fixed scratch-buffer URI; it does not add shared LSP state to
the Dawn runner. If that optional connection fails, the editor keeps the
existing `/check` diagnostics and static completion paths.

## Layout

- `src/main.dawn` — entry: routes + server start
- `src/http/` — the HTTP layer over `com.sun.net.httpserver`
- `lsp_gateway.py` — loopback `/lsp` WebSocket-to-stdio bridge
- `sandbox/run-lsp-sandboxed.sh` — fixed native-process isolation and limits

## Run locally

```sh
dawn run playground          # listens on 127.0.0.1:8087
curl --noproxy '*' -X POST --data '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  http://127.0.0.1:8087/run
```

`POST /check` takes the same request but only compiles (no run) — the editor's
live diagnostics endpoint. `{"ok":true,"phase":"check","ms":N}` when clean,
otherwise the same `phase:"compile"` shape as `/run`.

For local UI development, start the native gateway explicitly (the unsafe flag
is required outside the production systemd sandbox):

```sh
PLAY_LSP_UNSAFE_LOCAL=1 \
PLAY_LSP_CHILD='./dawnc-linux-x86_64 lsp' \
PLAY_LSP_ORIGINS=http://localhost:5173 \
python3 playground/lsp_gateway.py
```

It listens on `127.0.0.1:8088/lsp`; Vite/nginx exposes that as `/api/lsp` and
must negotiate the `dawn-lsp-v1` WebSocket subprotocol.

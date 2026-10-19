# dawn-play

The Dawn Playground runner: an HTTP service, **written in Dawn**, that compiles
and runs untrusted Dawn source in a throwaway sandbox and streams back the
output. It is a native binary (`dawnc build playground`) that answers one
request per process: systemd accepts each connection on a unix socket
(`deploy/dawn-play-native.socket`, `Accept=yes`) and starts the binary with the
connection as stdin and stdout. nginx terminates TLS in front, the sandbox is a
transient `systemd-run` unit per request, and a flock gate keeps two heavy
requests at a time (`docs/playground-native-runner-design.md`).

It started as the first real server written in Dawn, a long-lived JVM service
on the `web` framework that dogfooded the `use java` interop trio (spec
§9.4–§9.6). That entry was removed in K5 once it had carried no traffic for
ten days; the JVM is still what `/run` compiles and runs a program with, inside
the sandbox.

Live completion, hover, definition and diagnostics use a separate, bounded
standard-library Python gateway. One WebSocket owns one native `dawnc lsp`
process and one fixed scratch-buffer URI; it does not add shared LSP state to
the Dawn runner. If that optional connection fails, the editor keeps the
existing `/check` diagnostics and static completion paths.

## Layout

- `src/main.dawn` — entry: `serve` (one request on stdin/stdout) and `job` (the gate's child)
- `src/play/` — HTTP/1.1 parsing (`http1`), routes, the flock gate, the sandboxed jobs
- `lsp_gateway.py` — loopback `/lsp` WebSocket-to-stdio bridge
- `sandbox/run-lsp-sandboxed.sh` — fixed native-process isolation and limits

## Run locally

```sh
./dawnc-linux-x86_64 build playground -o dawn-play-linux-x86_64
PLAY_UNSAFE_LOCAL=1 DAWN_BIN=$PWD/bin/dawn \
  systemd-socket-activate -l 127.0.0.1:8087 -a --inetd \
  -E PLAY_UNSAFE_LOCAL -E DAWN_BIN -E PATH -E JAVA_HOME -E HOME \
  ./dawn-play-linux-x86_64 serve      # one process per connection on 127.0.0.1:8087
curl --noproxy '*' -X POST --data '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  http://127.0.0.1:8087/run
```

Port 8087 is what `site/play-ui`'s Vite dev proxy expects. Each request logs
one line to stderr: status, method, path, `toolchain=<version>/<build>` and,
for `/run`, `/check` and `/compile`, `src_sha256=<hex>` of the program (never
its text).

`POST /check` takes the same request but only compiles (no run) — the editor's
live diagnostics endpoint. `{"ok":true,"phase":"check","ms":N}` when clean,
otherwise the same `phase:"compile"` shape as `/run`.

`POST /compile` takes `{"code": ..., "target": "c" | "jvm"}` and answers with
the program's own C text or JVM listing and which call wrote which of its
lines (`packages/xmap`), compile-only. A program that does not compile gets
`/check`'s diagnostics. It needs `javap` (a JDK, not only a JRE; `PLAY_JDK`, see `deploy/DEPLOY.md` step 2); without it the
endpoint answers 503. The design is `docs/playground-compile-design.md`.

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

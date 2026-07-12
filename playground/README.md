# dawn-play

The Dawn Playground runner: an HTTP service, **written in Dawn**, that compiles
and runs untrusted Dawn source in a throwaway sandbox and streams back the
output. It is the first real server written in Dawn — a warm-up for the M6 blog
backend rewrite, dogfooding the `use java` interop trio (SAM conversion, opaque
arrays, the List bridge; spec §9.4–§9.6).

Zero async in the language: HTTP is `jdk.httpserver` on JVM 21 virtual threads
(thread-per-request), nginx terminates TLS in front, the sandbox is a transient
`systemd-run` unit per request.

## Layout

- `src/main.dawn` — entry: routes + server start
- `src/http/` — the HTTP layer over `com.sun.net.httpserver`

## Run locally

```sh
dawn run playground          # listens on 127.0.0.1:8087
curl --noproxy '*' -X POST --data 'pub fn main() -> Unit !io = println("hi")' \
  http://127.0.0.1:8087/run
```

# Deploying dawn-play

Two parts: a **one-time server setup**, then the repeatable **`redeploy.sh`**.
Nothing here runs automatically — the runner ships only when you run the script
by hand, with the server reachable.

## One-time server setup (as root on dawnop.com)

1. **Service user** (unprivileged, distinct from the blog backend):
   ```sh
   useradd --system --no-create-home --shell /usr/sbin/nologin dawn-play
   ```

2. **JRE 21 + Python 3** — a headless JRE is enough for `/run` and `/check`;
   the bounded WebSocket gateway uses only Python's standard library. On
   Ubuntu 22.04:
   ```sh
   sudo apt-get install -y openjdk-21-jre-headless python3
   # lands at /usr/lib/jvm/java-21-openjdk-amd64, java at /usr/bin/java
   ```

3. **Layout** under `/opt/dawn` (owned by your deploy user, readable by dawn-play):
   ```
   /opt/dawn/bin/dawn                      # launcher (rsynced)
   /opt/dawn/bin/dawnc                     # static native LSP server (rsynced)
   /opt/dawn/build/dawn-selfhost.jar       # compiler (rsynced)
   /opt/dawn/playground/dawn.toml           # runner manifest — deps web/json (rsynced)
   /opt/dawn/playground/src                 # runner sources (rsynced)
   /opt/dawn/playground/lsp_gateway.py      # loopback WebSocket bridge (rsynced)
   /opt/dawn/playground/sandbox/            # sandbox scripts (rsynced)
   /opt/dawn/playground/deploy/             # systemd/nginx source snippets (rsynced)
   /opt/dawn/packages/                       # path-deps the runner imports (rsynced)
   /opt/dawn/site/play-ui/samples/           # starter samples, read by lsp-measure (rsynced)
   ```
   The runner's `main.dawn` imports the `web`/`json` packages by path
   (`playground/dawn.toml` → `../packages`), so `packages/` must sit beside
   `playground/` — `redeploy.sh` syncs both.

4. **Work root** — per-request dirs live here, NOT under /tmp (DynamicUser
   implies a private /tmp that can't bind a /tmp work dir). Parents are `0711`
   so the sandbox's DynamicUser can traverse in:
   ```sh
   sudo mkdir -p /var/lib/dawn-play/work
   sudo chown -R dawn-play:dawn-play /var/lib/dawn-play
   sudo chmod 0711 /var/lib/dawn-play /var/lib/dawn-play/work
   ```

5. **Sandbox wrapper + sudoers** (the wrapper hardcodes every limit; sudoers
   whitelists only it, with any args — do NOT add a trailing `""`, that means
   "zero args only" and denies every real call):
   ```sh
   chmod 755 /opt/dawn/playground/sandbox/run-sandboxed.sh \
     /opt/dawn/playground/sandbox/run-lsp-sandboxed.sh
   visudo -cf /opt/dawn/playground/sandbox/sudoers.dawn-play   # validate first
   install -m 440 -o root -g root /opt/dawn/playground/sandbox/sudoers.dawn-play \
     /etc/sudoers.d/dawn-play
   ```

6. **systemd units** — `dawn-play.service` owns `/run` and `/check`;
   `dawn-play-lsp.service` owns the loopback WebSocket gateway. Each accepted
   WebSocket owns one transient native LSP service, all held under the
   aggregate `dawn-play-lsp.slice` ceiling:
   ```sh
   install -m 644 /opt/dawn/playground/deploy/dawn-play.service \
     /etc/systemd/system/dawn-play.service
   install -m 644 /opt/dawn/playground/deploy/dawn-play-lsp.service \
     /etc/systemd/system/dawn-play-lsp.service
   install -m 644 /opt/dawn/playground/deploy/dawn-play-lsp.slice \
     /etc/systemd/system/dawn-play-lsp.slice
   systemctl daemon-reload
   systemctl enable --now dawn-play dawn-play-lsp
   curl -s http://127.0.0.1:8087/health   # -> ok
   systemctl is-active dawn-play-lsp       # -> active
   ```

7. **Validate the sandbox** — run every item in `sandbox/SANDBOX.md`'s
   malicious-sample checklist against `http://127.0.0.1:8087/run` **before**
   exposing `/api/run` publicly (results from the first deploy are recorded
   there).

8. **nginx**: add `nginx-play.conf`'s locations into the existing
   `server { server_name dawn-lang.dawnop.com; … }`, and all listed
   `limit_req_zone` / `limit_conn_zone` declarations into `http { … }`. Then
   `nginx -t && systemctl reload nginx`. `/api/lsp` must preserve the browser's
   `Origin` and `Sec-WebSocket-Protocol: dawn-lsp-v1` headers and rewrite to the
   gateway's loopback-only `/lsp` route, as the shipped snippet does.

## Repeatable deploys

```sh
./scripts/release-native.sh -o dawnc-linux-x86_64  # or reuse CI's artifact
playground/deploy/redeploy.sh      # sync jar/native/gateway, restart, health-check
scripts/play-live-check.py         # then verify what is actually deployed
```

The redeploy's LSP health check is an end-to-end smoke, not only a systemd
status: `deploy/lsp-smoke.py` performs the WebSocket handshake, initializes the
real sandboxed native server, opens the fixed scratch buffer, waits for a
diagnostics notification and completes the close handshake.

`redeploy.sh` does **not** install systemd units; when a `.service` or `.slice`
file changes, copy it to `/etc/systemd/system/`, `daemon-reload` and restart by
hand. `DAWN_NATIVE_BIN=/path/to/dawnc-linux-x86_64` selects an already verified
artifact outside the repository root.

Before first exposure, run the fresh-process resource matrix inside the final
parent cgroup with the same release binary. It records ten processes per case,
including all five samples, exact 64 KiB source, one-in-flight burst, semantic
queries, 60-second idle and disconnect cleanup:

```sh
python3 -B playground/deploy/lsp-measure.py \
  --dawnc /opt/dawn/bin/dawnc --iterations 10 \
  --host-label production-cgroup --harness-commit <commit> \
  --output /new/path/lsp-measure.tsv
```

The sample scenario reads the five starter programs from `site/play-ui/samples/`
relative to the harness, which is why the layout above keeps that directory
beside `playground/` on the server. Point `--samples` at another directory to
measure a different set; the failure names the directory it searched.

The checked-in WSL2 run is development evidence only. Apply the admission math
and stop conditions in `docs/playground-lsp-design.md` to production results;
do not infer the host budget from the WSL2 worker.

**Order matters when the samples change.** The starter samples in
`site/play-ui/samples/` are compiled by the deployed runner, so ship the runner
*before* `site/redeploy.sh`. Backwards, the sidebar offers a program its own
runner rejects — which is the state the v0.51.0 upgrade had to unwind, the
runner having sat thirteen days behind the tree with each half self-consistent.

`play-live-check.py` is the check that would have caught it: it runs every
sample against the deployed `/api/run`, compares stdout byte-for-byte with the
`.out` beside it, asserts the compiler version in both directions (the retired
`fn(c) =>` lambda rejected *and* the bare arrow accepted), and confirms the
bundle nginx serves carries the current spelling. Health checks cannot see any
of that — the old runner answered `/health` with `ok` the whole time.

## Rollback

```sh
systemctl disable --now dawn-play dawn-play-lsp
```

takes the dynamic endpoints down and keeps them down; the LSP service's
`ExecStopPost` cleans up per-session transient services. To repeat that cleanup
explicitly, run `sudo /opt/dawn/playground/sandbox/run-lsp-sandboxed.sh cleanup`.

`disable`, not `stop` alone: step 6 installs both units with `enable --now`, so
a `stop` lasts only until the next boot and the endpoint you rolled back comes
up with the machine. Undo it with `systemctl enable --now dawn-play
dawn-play-lsp`.

nginx keeps serving the static site. Neither service has persistent state, so
there is nothing to migrate back.

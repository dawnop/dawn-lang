# Deploying dawn-play

Two parts: a **one-time server setup**, then the repeatable **`redeploy.sh`**.
Nothing here runs automatically — the runner ships only when you run the script
by hand, with the server reachable.

## One-time server setup (as root on dawnop.com)

1. **Service user** (unprivileged, distinct from the blog backend):
   ```sh
   useradd --system --no-create-home --shell /usr/sbin/nologin dawn-play
   ```

2. **A private GraalVM CE 21.0.2, and Python 3.** The runner needs `java` for
   `/run` and `/check` (the compiler and the user's program) and `javap` for
   `/compile` (`docs/playground-compile-design.md` section 6.5), which only a
   JDK has. All of it runs on one pinned GraalVM Community Edition 21.0.2, the
   JDK the dev box and CI test the compiler on, unpacked to
   `/opt/dawn/graalvm-21`. It does **not** come from apt:
   `openjdk-21-jdk-headless` would put `javap` in `/usr/bin` through
   alternatives and move the patch level of the JRE that every other JVM
   service on this host shares. This tree is on no PATH and registered with no
   alternatives; only the sandbox units the runner starts use it (the runner
   process itself is a native binary). It is outside
   `$HOME` because the sandbox units run with `ProtectHome=yes`; they see
   `/opt/dawn` through a read-only bind, and the runner passes absolute paths
   (`PLAY_JDK` in `dawn-play-native@.service`) while `run-sandboxed.sh` sets the units'
   `JAVA_HOME` to the same directory, so their empty environment and systemd's
   default PATH no longer decide which `java` runs. Whatever JRE the host has
   is left as it is. The bounded WebSocket gateway uses only Python's standard
   library and the native `dawnc`, no JVM.
   The language server the gateway starts is the same native `dawnc lsp`, so the
   collector change for the JVM `dawn lsp` (ParallelGC, see
   `docs/audit/lsp-robustness-design.md` section 2.2.7) does not apply here and
   nothing needs to be deployed for it.
   ```sh
   sudo apt-get install -y python3
   ```
   The server cannot reach GitHub, where the tarball
   (`graalvm-community-jdk-21.0.2_linux-x64_bin.tar.gz`, from
   `graalvm/graalvm-ce-builds` release `jdk-21.0.2`) is hosted, so the helper
   runs on **your** machine: it downloads the tarball, checks the pinned
   sha256, rsyncs it to the server and swaps it in atomically (unpacked beside
   the target, then renamed):
   ```sh
   DEPLOY_USER=<server login> ./playground/deploy/install-jdk.sh
   # its last lines on the server: java and javap -version -> 21.0.2
   ```
   `redeploy.sh` asks the server for `/opt/dawn/graalvm-21/bin/java -version`
   and `javap -version` before it syncs anything, and refuses to ship unless
   both report 21.0.2. Without `javap` the runner still starts and
   `POST /compile` answers 503 saying so. To move the pin, change the pinned
   lines in `install-jdk.sh`, the version check in `redeploy.sh` and
   `SANDBOX_JAVA_HOME` in `run-sandboxed.sh` together. (The contract test sets
   `PLAY_JAVA` and `PLAY_JAVAP` to the JDK it runs on; they win over
   `PLAY_JDK`.)

3. **Layout** under `/opt/dawn` (owned by your deploy user, readable by dawn-play):
   ```
   /opt/dawn/bin/dawn                      # launcher (rsynced)
   /opt/dawn/bin/dawnc                     # static native compiler and LSP server (rsynced)
   /opt/dawn/bin/dawn-play                 # the runner binary (rsynced beside it, renamed in after the canary)
   /opt/dawn/build/dawn-selfhost.jar       # compiler (rsynced)
   /opt/dawn/playground/toolchain.env       # PLAY_TOOLCHAIN_ID for the runner unit (written by redeploy.sh)
   /opt/dawn/playground/lsp_gateway.py      # loopback WebSocket bridge (rsynced)
   /opt/dawn/playground/sandbox/            # sandbox scripts (rsynced)
   /opt/dawn/playground/deploy/             # systemd/nginx source snippets (rsynced)
   /opt/dawn/packages/                       # tileir/tileref/tileinterp for the Tile IR view and the LSP's tile project (rsynced)
   /opt/dawn/playground/lsp-tile/            # project a tileir program is opened in by the LSP bridge (rsynced; deps are ../../packages)
   /opt/dawn/site/play-ui/samples/           # starter samples, read by lsp-measure (rsynced)
   /opt/dawn/scripts/repo.env                # the site origin the LSP gateway accepts (rsynced)
   /opt/dawn/scripts/repo_env.py             # its Python reader (rsynced)
   ```
   The runner's own sources are not on the server: the binary is built off
   it (`dawnc build playground`). Until K5 the JVM runner compiled
   `playground/src` at every start, which is why older layouts have it. The
   Tile IR view (`POST /compile` with `target: "tile"`) points a generated
   project at `packages/tileir`, `packages/tileref` and `packages/tileinterp`: `PLAY_PACKAGES` names the directory and
   defaults to `/opt/dawn/packages`, which is where the sync puts it, so the
   unit file needs no new line. The runner checks both manifests exist at start
   and answers that target with 503 when they do not.

4. **Work root** — per-request dirs live here, NOT under /tmp (DynamicUser
   implies a private /tmp that can't bind a /tmp work dir). Parents are `0711`
   so the sandbox's DynamicUser can traverse in:
   ```sh
   sudo mkdir -p /var/lib/dawn-play/work
   sudo chown -R dawn-play:dawn-play /var/lib/dawn-play
   sudo chmod 0711 /var/lib/dawn-play /var/lib/dawn-play/work
   sudo install -m 644 /opt/dawn/playground/deploy/dawn-play.tmpfiles /etc/tmpfiles.d/dawn-play.conf
   ```
   The tmpfiles rule removes request directories older than an hour, the ones
   a killed request left behind (no request lives past the runner unit's
   `RuntimeMaxSec=60`); `systemd-tmpfiles-clean.timer` applies it daily.

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

6. **systemd units** — `dawn-play-native.socket` and the template
   `dawn-play-native@.service` own `/run`, `/check`, `/compile` and
   `/health`: systemd accepts each connection on `/run/dawn-play/http.sock`
   and starts one runner process for it. `redeploy.sh` installs and enables
   these two itself, after its canary has passed (see "The runner canary").
   `dawn-play-lsp.service` owns the loopback WebSocket gateway. Each accepted
   WebSocket owns one transient native LSP service, all held under the
   aggregate `dawn-play-lsp.slice` ceiling. `dawn-play-lsp.service` takes the
   accepted Origin from `/opt/dawn/scripts/repo.env` (`EnvironmentFile=`,
   `DAWN_SITE_ORIGIN`), so run `redeploy.sh` once before installing it; a unit
   installed from an older tree still names the origin itself and keeps
   working until it is reinstalled from this one:
   ```sh
   install -m 644 /opt/dawn/playground/deploy/dawn-play-lsp.service \
     /etc/systemd/system/dawn-play-lsp.service
   install -m 644 /opt/dawn/playground/deploy/dawn-play-lsp.slice \
     /etc/systemd/system/dawn-play-lsp.slice
   systemctl daemon-reload
   systemctl enable --now dawn-play-lsp
   sudo -u dawn-play curl -s --unix-socket /run/dawn-play/http.sock http://localhost/health
                                           # -> {"ok":true,"version":"<release>","build":"b1:..."}
   systemctl is-active dawn-play-lsp       # -> active
   ```

7. **Validate the sandbox** — run every item in `sandbox/SANDBOX.md`'s
   malicious-sample checklist against the runner's socket
   (`sudo -u dawn-play curl --unix-socket /run/dawn-play/http.sock http://localhost/run ...`)
   **before** exposing `/api/run` publicly (results from the first deploy are
   recorded there).

8. **nginx**: add `nginx-play.conf`'s locations into the existing
   `server { server_name dawn-lang.dawnop.com; … }`, and all listed
   `limit_req_zone` / `limit_conn_zone` declarations into `http { … }`. Then
   `nginx -t && systemctl reload nginx`. The shipped snippet routes `/api/run`,
   `/api/check`, `/api/compile` and `/api/health` to the runner's unix socket,
   the three POSTs each with its own zone (`playrun`, `playcheck`,
   `playcompile`) and a 10 s `client_body_timeout`; a missing `/api/compile` location
   answers 404 from the static site, not from the runner. The socket admits
   the group `www-data` (`SocketGroup=` in the socket unit), which is nginx's
   user on this host; where nginx runs as another user, change that line. The `playcompile`
   rate (30r/m, burst 6) is provisional until a week of access-log data.
   When the site page and the API are on different hosts (the live setup:
   the site calls a dedicated play host), also declare the
   `$play_cors` map from the snippet's header in `http { … }`; the REST
   locations then answer preflight and add `Access-Control-Allow-Origin` (with
   `always`, so 413/429 carry it) for that one origin only. `/api/lsp` gets no
   CORS headers, the gateway checks `Origin` itself. Observed on the live
   host (2026-10-12), and what the snippet reproduces: preflight on
   `/api/run`, `/api/check`, `/api/compile` and `/api/health` answers 204 with
   `Access-Control-Allow-Origin` (the site origin), `-Allow-Methods: POST, GET,
   OPTIONS`, `-Allow-Headers: Content-Type`, `-Max-Age: 600` and
   `Vary: Origin`; the actual requests carry `Access-Control-Allow-Origin` and
   `Vary: Origin`, on 400s too. Any other origin gets the same replies minus
   `Access-Control-Allow-Origin`, which the browser then refuses.
   `deploy/nginx-cors-check.py` (run by `test/contract.sh`) fails when a
   runner location loses any of these headers or a runner route has no
   location.
   `/api/lsp` must preserve the browser's
   `Origin` and `Sec-WebSocket-Protocol: dawn-lsp-v1` headers and rewrite to the
   gateway's loopback-only `/lsp` route, as the shipped snippet does.

## Repeatable deploys

```sh
./scripts/release-native.sh -o dawnc-linux-x86_64  # or reuse the release asset
./dawnc-linux-x86_64 build playground -o dawn-play-linux-x86_64
DEPLOY_USER=<server login> DAWN_DEPLOY_COMMIT=$(git rev-parse HEAD) playground/deploy/redeploy.sh
scripts/play-live-check.py         # then verify what is actually deployed
```

`redeploy.sh` syncs the toolchain, the gateway and the runner binary,
restarts the gateway, holds the new runner to the live one (the canary),
swaps it in and checks it through the socket.

The redeploy's LSP health check is an end-to-end smoke, not only a systemd
status: `deploy/lsp-smoke.py` performs the WebSocket handshake, initializes the
real sandboxed native server, opens the fixed scratch buffer, waits for a
diagnostics notification and completes the close handshake.

`systemctl is-active dawn-play-lsp` does not mean the gateway is listening:
the unit is `Type=simple`, so systemd calls it active as soon as `python3` is
started, before `asyncio.start_server()` binds `127.0.0.1:8088`. The v0.95.0
deploy ran the smoke in that window and failed with `ConnectionRefusedError`
(systemd "Started" and the gateway's "listening" line in the same second); a
second redeploy passed. The smoke therefore retries a refused or timed-out
TCP connect with exponential backoff (0.1 s, doubling) for at most 10 s
(`PLAY_LSP_SMOKE_CONNECT_SECONDS`), printing each retry and the final count on
stderr; after the connect, every handshake, child or diagnostics failure is
still fail-fast, and only an explicit HTTP 503 is retried as before. A gateway
that never comes up fails the deploy after those 10 s with
`gateway not accepting on 127.0.0.1:8088 after N connect retries`. This is a
change to `lsp-smoke.py` only, which `redeploy.sh` ships with
`playground/deploy/`: the unit file is unchanged, so no `daemon-reload` is
needed for it.

`redeploy.sh` refuses to run unless `DAWN_DEPLOY_COMMIT` is the full sha of its own
checkout's HEAD and tracked files are clean (before any build or ssh). It
installs the runner's socket and service template itself, when they differ
from the installed ones; it does **not** install `dawn-play-lsp.service` or the
slice: when either changes, copy it to `/etc/systemd/system/`, `daemon-reload`
and restart by hand. `DAWN_NATIVE_BIN=/path/to/dawnc-linux-x86_64` and
`DAWN_PLAY_NATIVE_BIN=/path/to/dawn-play-linux-x86_64` select already built
artifacts outside the repository root.

Before it ships anything it also reads which upstream the live nginx gives
`/api/run` (read-only, over its ssh session) and stops if that is still the
JVM runner's `127.0.0.1:8087`: since K5 there is no JVM runner, and that host
must be switched first ("Retiring the JVM runner" below). A config it cannot read, or an
upstream it does not recognise, is reported and does not stop the deploy.

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

**The site is built on the deploying machine, with a native generator.**
`site/redeploy.sh` runs `site/build.sh`, which runs the site generator and the
search budget probe with `dawnc` (built from the checked-out commit by
`site/dawnc.sh`, cached under `site/build/`, or `DAWNC_BIN` if set), so the
machine needs a C compiler (`cc`) beside the JDK and `clang-20`. The first build
of a new commit pays about 40 seconds to compile `dawnc`; later builds of the
same compiler sources reuse it. Nothing about the server changes: it still only
receives `site/dist`.

`play-live-check.py` is the check that would have caught it: it runs every
sample against the deployed `/api/run`, compares stdout byte-for-byte with the
`.out` beside it, asserts the compiler version in both directions (the retired
`fn(c) =>` lambda rejected *and* the bare arrow accepted), checks that the
`version` in `/health` is the tree's `VERSION`, and confirms the bundle nginx
serves carries the current spelling. Health checks cannot see any
of that — the old runner answered `/health` with `ok` the whole time.

## The native compiler in `/check` and `/compile`

`/check` and the C view of `/compile` run `/opt/dawn/bin/dawnc` (`check` and
`emitc`) inside the same sandbox unit as before; `/run` and the JVM view stay
on the JVM compiler. Nothing new has to be configured: `dawnc` is the one
`redeploy.sh` already ships, and the unit names it (`DAWNC_BIN`). Each such
request asks `dawnc --version` and compares the release number with the
toolchain's; a missing `dawnc` or a different release is logged
(`journalctl -u 'dawn-play-native@*' | grep dawnc`) and that request uses the
JVM compiler only. A program `dawnc` refuses (`use java`) is compiled again
by the JVM compiler within the same request. To switch the native path off,
point `DAWNC_BIN` at a path that does not exist.

## The runner canary

`dawn-play-native.socket` and `dawn-play-native@.service` run the runner
(`docs/playground-native-runner-design.md`): systemd accepts every connection
on `/run/dawn-play/http.sock` (`Accept=yes`) and starts one `dawn-play serve`
process for it, which answers one request and exits. Nothing is resident, so
a deploy changes the runner by renaming a new binary over
`/opt/dawn/bin/dawn-play`; the next connection starts the new one.

The binary is built off the server, next to the compiler (no C compiler on
the server). Before it ships anything `redeploy.sh` asks the binary for
`/health` with this tree's toolchain id (a binary of another release stops the
deploy), and asks the server whether `timeout flock head chmod rm sh` exist on
the default PATH (the runner runs them; a missing one would otherwise show as a
failing `/run` behind a green `/health`).

The new binary is synced to `/opt/dawn/bin/.dawn-play.next` and checked
against the live one before it replaces it, by `canary-check.py` as
`dawn-play`. Both binaries are started per request, the request on stdin, with
the unit's environment and this deploy's toolchain id, on the toolchain the
deploy has just synced, so their jobs go through the real sudo wrapper,
sandbox units and flock slots:

- the candidate's own answers: `/health` names this release and build, hello
  prints hello, a compile error is a diagnostic with no server path in it, the
  refusals (bad JSON, bad UTF-8, oversize, empty body, 404, 405) have their
  statuses; and each request leaves one access line naming the toolchain and,
  for a program, its SHA-256, never its text;
- the same status and body (`ms` aside) as the live runner for every case:
  same toolchain, so a difference is the runner's own. A deploy whose runner
  change is meant to change an answer sets `DAWN_PLAY_CANARY_ACCEPT_DIFF=1`;
  the differences are printed either way;
- the latency gate, the two interleaved: for `/run` hello and `/check` hello
  (20 requests each, spaced out), the candidate's p95 is at most 1.15 times
  the live one's plus 100 ms.

It adds roughly 2 to 4 minutes to a deploy. A failing canary stops the deploy
with the new binary not swapped in: the previous runner binary stays live, on
the toolchain this deploy synced. Fix and redeploy, or restore the rollback
copy.

After it passes, `redeploy.sh` writes `toolchain.env`, renames the binary into
place, installs the two units if they differ from the installed ones (and
restarts the socket only when its own unit changed, since a restart closes the
socket nginx sends every request to), and checks through the socket itself:
`/health` answers this release and build, its p95 over 100 new connections is
at most 25 ms (the real `Accept=yes` start-up; measured 7.7 to 7.9 ms on the
production host), and `/run` hello prints hello.

Until K5 the canary was a comparison of the native runner with the JVM
runner of the same commit; with one runner left, the live binary is the
reference (the design's K5 record says why not a recorded answer set).

The socket is its own directory (`/run/dawn-play`), the flock slots another
(`RuntimeDirectory=dawn-play-slots` in the service, `Preserve=yes`). They must
not be one directory: a `RuntimeDirectory` is removed when its service stops,
and with `Accept=yes` every request is a service that stops.

Watch: `journalctl -u 'dawn-play-native@*'` (one access line per request on
stderr: status, method, path, `toolchain=<version>/<build>` and, for `/run`,
`/check` and `/compile`, `src_sha256=<hex>` of the program, plus the `429`
waits of the flock gate) and `systemctl status dawn-play-native.socket`.

## Retiring the JVM runner (one time, the first deploy after K5)

The JVM runner (`dawn-play.service` on `127.0.0.1:8087`) carried no traffic
after nginx was pointed at the socket on 2026-10-09; it only answered the old
canary. Its unit file is no longer in this tree and `redeploy.sh` no longer
restarts it, so on the server, once, as root, after a deploy of this tree has
passed:

```sh
# nginx must already send /api/* to the socket; redeploy.sh refuses otherwise
nginx -T 2>/dev/null | grep -n 'proxy_pass http://127.0.0.1:8087'   # expect nothing
systemctl disable --now dawn-play.service
rm /etc/systemd/system/dawn-play.service
systemctl daemon-reload
systemctl reset-failed dawn-play.service 2>/dev/null || true
ss -ltnp | grep ':8087 '                                            # expect nothing
# leftovers of the JVM runner's start-up compile, owned by dawn-play
find /tmp -maxdepth 1 -name 'selfhost-run*' -user dawn-play -exec rm -rf {} +
# its sources, which only it compiled
rm -rf /opt/dawn/playground/src /opt/dawn/playground/dawn.toml
# age out request directories the JVM runner's start-up sweep used to remove
install -m 644 /opt/dawn/playground/deploy/dawn-play.tmpfiles /etc/tmpfiles.d/dawn-play.conf
systemd-tmpfiles --clean /etc/tmpfiles.d/dawn-play.conf
```

Do not roll back past K5 by running an older tag's `redeploy.sh`: it restarts
`dawn-play.service`, which is gone, and stops there after its rsyncs. Restore
a rollback copy instead (next section); it holds the runner binary, so it
needs no JVM unit.

## Rollback copies and restoring one

Both `playground/deploy/redeploy.sh` and `site/redeploy.sh` keep a rollback
copy on the server before they replace anything (`scripts/deploy-backup.sh`,
run over ssh). The copies sit in `/opt/dawn` (`DAWN_BACKUP_DIR` overrides it
for the site script) and are named
`.prev-<live version>-<UTC stamp>-<runner|site>`, for example
`.prev-0.88.0-20261014T101500Z-runner`. The version is read from the live
artifact (`bin/dawnc version`, or the `.dawn-version` marker in the site
tree) and is `unknown` when it cannot be read. The newest 3 of each kind are
kept; older ones are removed by exact name, nothing else is touched.

A failed deploy that you run again does not take another copy. Each copy
leaves `.deploy-pending-<runner|site>` beside it, naming the copy and the
deploy's commit (`DAWN_DEPLOY_COMMIT`), and the deploy removes that marker
only once it has finished (for the runner, after the swapped-in binary passed
its check; for the site, after the rsync). A rerun that finds the marker for
the same commit, with its copy still there, keeps that copy and copies
nothing: what is live then is part old release, part new, and the copy from
the first attempt is still the exact state before the deploy began. This is
why: on v0.95.0 the runner deploy failed three times, each attempt copied the
tree it found, and rotation removed the 0.91.0, 0.92.0 and 0.93.0 copies to
keep two of the half-deployed state (labelled 0.95.0, because the first
attempt had already replaced `bin/dawnc`), leaving one clean rollback point.
Of the alternatives, counting distinct versions instead of runs would still
have kept the mislabelled half-deployed copies and dropped clean ones, and
marking them partial afterwards needs the same "did it finish" signal this
marker already is. A different commit, or a marker whose copy is gone, takes
a fresh copy as usual. If the closing step cannot remove the marker the
deploy prints a warning; remove it by hand
(`rm /opt/dawn/.deploy-pending-runner`), or a later rerun of that same commit
would keep the older copy instead of copying the finished one.

The copy fails closed: if it cannot be made (no room, a copy error), the
deploy stops before the first rsync and nothing on the server has changed.
`DAWN_DEPLOY_NO_BACKUP=1` skips it and prints a warning; use it only when the
disk cannot hold a copy, and take one by hand if you can.

The runner copy holds `bin`, `build`, `playground`, `packages`, `scripts` and
`site` as they were under `/opt/dawn`; the site copy holds `dist`. To restore
the runner side, pick the copy and put it back with rsync, then restart:

```sh
ls -d /opt/dawn/.prev-*-runner
B=/opt/dawn/.prev-0.88.0-20261014T101500Z-runner
for d in bin build playground packages scripts site; do
  [ -d "$B/$d" ] && rsync -a --delete "$B/$d/" "/opt/dawn/$d/"
done
sudo systemctl restart dawn-play-lsp
```

The `--delete` makes each directory exactly what it was. The runner needs no
restart: the next connection starts the restored binary with the restored
`toolchain.env`. Check the result with
`sudo -u dawn-play curl -s --unix-socket /run/dawn-play/http.sock http://localhost/health`.
A copy made before K5 also holds `playground/src` and `dawn.toml`; they are
inert without the JVM runner. To restore the site:

```sh
rsync -a --delete /opt/dawn/.prev-0.88.0-20261014T101500Z-site/dist/ /var/www/dawnlang/dist/
```

and then refresh the CDN page cache the way `site/redeploy.sh` does, or wait
ten minutes for it to expire.

## Rollback without a copy

```sh
systemctl disable --now dawn-play-native.socket dawn-play-lsp
```

takes the dynamic endpoints down and keeps them down; the LSP service's
`ExecStopPost` cleans up per-session transient services. To repeat that cleanup
explicitly, run `sudo /opt/dawn/playground/sandbox/run-lsp-sandboxed.sh cleanup`.

`disable`, not `stop` alone: both units are enabled, so a `stop` lasts only
until the next boot and the endpoint you rolled back comes up with the
machine. Undo it with `systemctl enable --now dawn-play-native.socket
dawn-play-lsp`.

nginx keeps serving the static site. Neither service has persistent state, so
there is nothing to migrate back.

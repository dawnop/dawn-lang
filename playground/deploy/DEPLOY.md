# Deploying dawn-play

Two parts: a **one-time server setup**, then the repeatable **`redeploy.sh`**.
Nothing here runs automatically — the runner ships only when you run the script
by hand, with the server reachable.

## One-time server setup (as root on dawnop.com)

1. **Service user** (unprivileged, distinct from the blog backend):
   ```sh
   useradd --system --no-create-home --shell /usr/sbin/nologin dawn-play
   ```

2. **Layout** under `/opt/dawn` (owned by your deploy user, readable by dawn-play):
   ```
   /opt/dawn/bin/dawn                      # launcher (rsynced)
   /opt/dawn/compiler/build/libs/dawn.jar  # compiler (rsynced)
   /opt/dawn/jdk/                           # a JDK 21 (Temurin), installed once
   /opt/dawn/playground/src                 # runner sources (rsynced)
   /opt/dawn/playground/sandbox/            # sandbox scripts (rsynced)
   ```
   Install the JDK once (the server can't reach GitHub reliably; use a mirror):
   ```sh
   # e.g. Temurin 21 from a TUNA/Adoptium mirror, unpacked to /opt/dawn/jdk
   ```

3. **Sandbox wrapper + sudoers**:
   ```sh
   install -m 755 /opt/dawn/playground/sandbox/run-sandboxed.sh \
     /opt/dawn/playground/sandbox/run-sandboxed.sh
   visudo -cf /opt/dawn/playground/sandbox/sudoers.dawn-play   # validate first
   install -m 440 /opt/dawn/playground/sandbox/sudoers.dawn-play \
     /etc/sudoers.d/dawn-play
   ```

4. **systemd unit**:
   ```sh
   install -m 644 /opt/dawn/playground/deploy/dawn-play.service \
     /etc/systemd/system/dawn-play.service
   systemctl daemon-reload && systemctl enable --now dawn-play
   ```

5. **nginx**: add `nginx-play.conf`'s two `location` blocks into the existing
   `server { server_name dawn-lang.dawnop.com; … }`, and the `limit_req_zone`
   line into `http { … }`. Then `nginx -t && systemctl reload nginx`.

6. **Validate the sandbox** — run every item in `sandbox/SANDBOX.md`'s
   malicious-sample checklist against `http://127.0.0.1:8087/run` before exposing
   `/api/run` publicly. Settle the DynamicUser cross-uid temp-dir question there.

## Repeatable deploys

```sh
playground/deploy/redeploy.sh      # build jar, rsync, restart, health-check
```

## Rollback

`systemctl stop dawn-play` takes the endpoint down; nginx keeps serving the
static site. The runner has no database and no persistent state, so there is
nothing to migrate back.

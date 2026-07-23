# Deploying dawn-play

Two parts: a **one-time server setup**, then the repeatable **`redeploy.sh`**.
Nothing here runs automatically — the runner ships only when you run the script
by hand, with the server reachable.

## One-time server setup (as root on dawnop.com)

1. **Service user** (unprivileged, distinct from the blog backend):
   ```sh
   useradd --system --no-create-home --shell /usr/sbin/nologin dawn-play
   ```

2. **JRE 21** — a headless JRE is enough (the compiler is a fat jar; no javac
   needed). On Ubuntu 22.04 it's in apt:
   ```sh
   sudo apt-get install -y openjdk-21-jre-headless
   # lands at /usr/lib/jvm/java-21-openjdk-amd64, java at /usr/bin/java
   ```

3. **Layout** under `/opt/dawn` (owned by your deploy user, readable by dawn-play):
   ```
   /opt/dawn/bin/dawn                      # launcher (rsynced)
   /opt/dawn/build/dawn-selfhost.jar       # compiler (rsynced)
   /opt/dawn/playground/src                 # runner sources (rsynced)
   /opt/dawn/playground/sandbox/            # sandbox scripts (rsynced)
   ```

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
   chmod 755 /opt/dawn/playground/sandbox/run-sandboxed.sh
   visudo -cf /opt/dawn/playground/sandbox/sudoers.dawn-play   # validate first
   install -m 440 -o root -g root /opt/dawn/playground/sandbox/sudoers.dawn-play \
     /etc/sudoers.d/dawn-play
   ```

6. **systemd unit** — the shipped `dawn-play.service` points at the apt JRE
   (`/usr/lib/jvm/java-21-openjdk-amd64`, `/usr/bin/java`) and sets
   `PLAY_WORK_ROOT=/var/lib/dawn-play/work`:
   ```sh
   install -m 644 /opt/dawn/playground/deploy/dawn-play.service \
     /etc/systemd/system/dawn-play.service
   systemctl daemon-reload && systemctl enable --now dawn-play
   curl -s http://127.0.0.1:8087/health   # -> ok
   ```

7. **Validate the sandbox** — run every item in `sandbox/SANDBOX.md`'s
   malicious-sample checklist against `http://127.0.0.1:8087/run` **before**
   exposing `/api/run` publicly (results from the first deploy are recorded
   there).

8. **nginx**: add `nginx-play.conf`'s two `location` blocks into the existing
   `server { server_name dawn-lang.dawnop.com; … }`, and the `limit_req_zone`
   line into `http { … }`. Then `nginx -t && systemctl reload nginx`.

## Repeatable deploys

```sh
playground/deploy/redeploy.sh      # build jar, rsync, restart, health-check
```

## Rollback

`systemctl stop dawn-play` takes the endpoint down; nginx keeps serving the
static site. The runner has no database and no persistent state, so there is
nothing to migrate back.

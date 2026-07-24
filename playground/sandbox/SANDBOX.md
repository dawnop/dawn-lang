# dawn-play sandbox

User code submitted to `/run` is arbitrary Dawn, which compiles to arbitrary JVM
bytecode. Every compile and every run therefore happens inside a throwaway
`systemd-run` transient unit with the network cut, the filesystem read-only
except one temp dir, and hard CPU/RAM/PID/time caps.

## How it fits together

```
dawn-play (unprivileged service user)
  └─ per request: mkdir /tmp/dawn-play-<uuid>, write prog.dawn
  └─ phase 1  sudo -n run-sandboxed.sh <dir>  dawn build prog.dawn -o prog.jar
  └─ phase 2  sudo -n run-sandboxed.sh <dir>  java -jar prog.jar
                └─ systemd-run --wait --pipe  (DynamicUser, PrivateNetwork, …)
                     └─ the untrusted command; stdout piped back to a file
```

- `run-sandboxed.sh` pins every limit; sudoers lets `dawn-play` call *only* that
  script (see `sudoers.dawn-play`). The runner can pass any argv but cannot relax
  a single sandbox property — they are hardcoded in the script, not passed in.
- The sandbox is **on by default**: `config.sandbox_enabled` only lets a command
  run directly when `PLAY_UNSAFE_LOCAL=1`. That is fail-closed on purpose — this
  service's entire job is to compile and run code from strangers, so "nobody set
  the variable" must not mean "no sandbox". Local development and
  `playground/test/contract.sh` are the callers that say so explicitly.
  `PLAY_SANDBOX_SCRIPT` overrides the script path.
  (It used to be the other way round: `PLAY_SANDBOX=1` opted *in*, and the
  default was off. That variable is no longer read.)

## Limits (in `run-sandboxed.sh`)

| Concern            | Property                                            |
|--------------------|-----------------------------------------------------|
| Network            | `PrivateNetwork=yes` (no sockets out at all)        |
| Filesystem         | `ProtectSystem=strict` + `ReadWritePaths=<workdir>` |
| Home dirs          | `ProtectHome=yes`                                   |
| Devices            | `PrivateDevices=yes`                                |
| Privilege          | `NoNewPrivileges`, `CapabilityBoundingSet=` (empty) |
| Syscalls           | `SystemCallFilter=@system-service` minus privileged |
| Memory             | `MemoryMax=512M`, `MemorySwapMax=0`                 |
| Fork bomb          | `TasksMax=64` (the JVM itself needs a few dozen)    |
| CPU                | `CPUQuota=200%` (two cores)                          |
| Wall clock         | `RuntimeMaxSec=15` (a hard backstop over the runner's own `PLAY_TIMEOUT`) |

The runner's `PLAY_TIMEOUT` (default 10s) kills the child first for a clean
"timeout" response; `RuntimeMaxSec` is the belt-and-braces kill if that fails.

## Cross-uid work dir — resolved on first deploy (2026-07-12)

`DynamicUser=yes` gives each invocation a *different* transient uid, so phase 1
(compile) and phase 2 (run) do not share a uid, and neither shares the runner's.
Three things make this work, learned the hard way on the server:

1. **Work dir must NOT be under `/tmp`.** `DynamicUser=yes` *implies*
   `PrivateTmp=yes`, so the sandbox gets a private `/tmp`; a `/tmp/…` work dir
   can't be bind-mounted in (systemd fails NAMESPACE setup, exit 226). The
   runner uses `PLAY_WORK_ROOT=/var/lib/dawn-play/work` instead. Bonus: the
   private `/tmp` is a writable scratch for the JVM (hsperfdata etc.), so no
   `/tmp`-write failures.
2. **Parent dirs need `o+x`.** `/var/lib/dawn-play` and `…/work` are `0711`
   (owner dawn-play rwx, others traverse-only) so the DynamicUser can `chdir`
   into its work dir. `0700` → exit 200/CHDIR "permission denied".
3. **Work dir is `chmod 0777`** by the runner before the phases
   (`make_world_writable`, gated on the sandbox switch). The name is an unguessable
   uuid and the parents are `0711` (unlistable), so world-writable is fine.
   Default `DynamicUser` umask (0022) leaves `prog.jar` world-readable, which is
   what the next phase's different uid needs.

The runner `rm -rf`s each work dir after the run (it owns the `0777` dir, so it
can unlink the DynamicUser-owned files inside). Verified: no accumulation across
runs, including timeouts.

## Malicious-sample checklist (run on the server after wiring)

Each of these must be *contained*, and produce a clean JSON response, never a
hang or a host-level effect:

1. **Infinite loop** — `fn s(n:Int)->Unit !io = s(n+1)` → `phase:"timeout"`.
2. **Fork bomb** — spawn threads/processes in a loop → killed by `TasksMax`, no
   host slowdown.
3. **Memory bomb** — allocate an ever-growing list → OOM-killed at 512M, the host
   stays healthy.
4. **Network exfiltration** — `use java "java.net.Socket"` to dial out → connect
   fails (no network namespace).
5. **Filesystem read** — try to read `/etc/passwd` or the runner's own files →
   denied / not present.
6. **Filesystem write** — try to write outside the temp dir (`/tmp/pwned`, `/opt`)
   → denied (`ProtectSystem=strict`).
7. **Privilege escalation** — attempt `sudo`, setuid → blocked (`NoNewPrivileges`,
   empty capability set).
8. **Huge output** — print megabytes → truncated at 64 KB, no memory blowup on the
   runner (output goes to a file, not a pipe buffer).

Confirm too that after a storm of requests the concurrency gate hasn't leaked
permits (the runner stays responsive). The permit leak this used to warn about
was in the old `run_guarded`; `play/gate.with_gate` replaced it and releases on
the panic path, with a regression test for exactly that ("with_gate releases the
permit even when body panics").

### Results — first production validation (2026-07-12, all contained)

1. Infinite loop → `phase:"timeout"` ✓
2. Fork bomb (threads) → `pthread_create failed (EAGAIN)` at `TasksMax=64`, then
   timeout; host unaffected ✓
3. Memory bomb → capped by `MemoryMax=512M`, timed out before host pressure ✓
4. Network (`java.net.Socket`) → `SocketException: Network is unreachable` ✓
5. Read `/etc/shadow` (0640) and `/opt/dawnop/.env` (InaccessiblePaths) → both
   denied ✓
6. Write `/opt/pwned.txt` → denied (`ProtectSystem=strict`); no file created ✓
7. Read `/etc/passwd` → **readable** (world-readable, usernames only, no
   secrets). Accepted: `ProtectSystem=strict` is read-only, not hidden. Verified
   `.env` / `shadow` / other services' data are not world-readable, and the app
   data dirs are hidden via `InaccessiblePaths`.
8. Huge output → truncated at 64 KB ✓

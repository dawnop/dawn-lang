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
- The runner enables all this by setting `PLAY_SANDBOX=1` (off by default, so
  local dev runs the commands directly). `PLAY_SANDBOX_SCRIPT` overrides the path.

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

## Open question to settle on first deploy — cross-uid temp dir

`DynamicUser=yes` gives each invocation a *different* transient uid, so phase 1
(compile) and phase 2 (run) do not share a uid, and neither shares the runner's.
The per-request dir is therefore `chmod 0777` by the runner before the phases
(`make_world_writable`, gated on `PLAY_SANDBOX`); the dir name is an unguessable
uuid under `/tmp`, so world-writable is acceptable. Default `DynamicUser` umask
(0022) leaves `prog.dawn` / `prog.jar` world-readable, which is what the next
phase needs.

**Validate this actually holds on the server.** If systemd's `ReadWritePaths`
interacts badly with `DynamicUser` (e.g. the compile can't write the jar, or the
JVM can't read it), the fallback is a single sandbox invocation running
`sh -c 'dawn build … && java -jar …'` — one uid for both phases, no sharing — at
the cost of folding the two phases together on the Dawn side.

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
permits (the runner stays responsive) — see the known panic-leak note in the
runner's `run_guarded`.

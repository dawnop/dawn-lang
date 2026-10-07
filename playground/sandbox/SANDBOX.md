# dawn-play sandbox

User code submitted to `/run` is arbitrary Dawn, which compiles to arbitrary JVM
bytecode. Every compile and every run therefore happens inside a throwaway
`systemd-run` transient unit with the network cut, the filesystem read-only
except one temp dir, and hard CPU/RAM/PID/time caps.

## How it fits together

```
dawn-play (unprivileged service user)
  └─ per request: mkdir <root>/dawn-play-<uuid>/box, write box/prog.dawn
  └─ phase 1  sudo -n run-sandboxed.sh run <id> <dir>/box  dawn build prog.dawn -o prog.jar
                 output -> <dir>/build.txt
  └─ phase 2  sudo -n run-sandboxed.sh run <id> <dir>/box  java -Xmx256m -jar prog.jar
                 output -> <dir>/run.txt
                └─ systemd-run --wait --pipe --unit=dawn-play-run-<id>  (DynamicUser, PrivateNetwork, …)
                     └─ the untrusted command; stdout piped back to a file
  └─ POST /compile instead of phases 1 and 2 (compile only, nothing is run):
       sudo -n run-sandboxed.sh run <id> <dir>/box  env LC_ALL=C.UTF-8 dawn __emitc …  (C text + map)
       sudo -n run-sandboxed.sh run <id> <dir>/box  env LC_ALL=C.UTF-8 dawn __emit …   (classes + map), one after the other
       then   run <id> <dir>/box  env LC_ALL=C.UTF-8 javap -c -p -s box/classes/prog.class
  └─ on a timeout: sudo -n run-sandboxed.sh stop <id>, then wait for the phase to end
  └─ rm -rf <dir>, on every way out
```

The unit can write `box/` and nothing else. Its output files are one level
up, opened by the runner before the child starts; the child writes through
that descriptor and cannot rename, replace or link the files themselves.
The runner reads back at most 64 KiB + 1 byte of each, refuses anything but a
regular file and never follows a link. (Until 2026-10-04 the output files sat
inside the writable directory and were read whole by name after the child
exited, so the child could swap one for a link or a FIFO, and a large enough
output exhausted the runner's heap.)

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
| Compiler heap      | `DAWN_JVM_OPTS=-Xss512m -Xmx256m` via `--setenv`    |
| Run-phase heap     | `java -Xmx256m` on the runner's argv (`play/exec.dawn`) |
| Disk, per file     | `LimitFSIZE=32M` (stdout included; writes past it fail) |
| Fork bomb          | `TasksMax=64` (the JVM itself needs a few dozen)    |
| CPU                | `CPUQuota=200%` (two cores)                          |
| Wall clock         | `RuntimeMaxSec=15` (a hard backstop over the runner's own `PLAY_TIMEOUT`) |

The runner's `PLAY_TIMEOUT` (default 10s) kills the child first for a clean
"timeout" response; `RuntimeMaxSec` is the belt-and-braces kill if that fails.

## The environment inside the unit (2026-08-05)

`systemd-run` starts the unit with a **clean environment** — nothing the runner
exports reaches either phase. Two consequences that are easy to get wrong:

- **No JDK is on systemd's default `PATH`** that the server means to use
  (`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin` would give
  whatever JRE the OS packages, which other JVM services share). Before
  2026-10-07 the units ran on that `/usr/bin/java`. Now every JVM the units
  start is the pinned GraalVM CE 21.0.2 at `/opt/dawn/graalvm-21`, the
  toolchain CI tests on, found explicitly: the run phase's `java` and the
  view's `javap` are absolute paths on the argv the runner builds (`PLAY_JDK`),
  and the compiler units get `JAVA_HOME=/opt/dawn/graalvm-21` from
  `run-sandboxed.sh` (`--setenv`, a path fixed in that root-run script), which
  `bin/dawn` honours before any probe. A JDK under `$HOME` cannot work:
  `ProtectHome=yes` hides it, while `/opt/dawn` is bound read-only into every
  unit. The tree is private to the runner (no PATH, no alternatives, no apt) so
  that nothing moves the JRE other services use. This is why
  `bin/dawn`'s `JAVA_HOME` probe is irrelevant here and the launcher falls
  through to plain `java`.
- **Heap ceilings must be passed with `--setenv`**, which is what the
  `DAWN_JVM_OPTS` line above does. Neither thing that looks like a cap is one:
  `bin/dawn` pins `-Xmx2g` (a build-box default, 4× this unit's `MemoryMax`),
  and the JVM does **not** see the cgroup — measured on both boxes,
  `MaxHeapSize` is byte-identical inside and outside a 512M scope despite
  `UseContainerSupport=true`, so ergonomics aim at a quarter of *host* RAM
  (6.3 GB on the dev box). Left alone, the compile JVM aims past `MemoryMax`
  and the kernel SIGKILLs it — contained, but as an opaque kill rather than a
  diagnostic. At `-Xmx256m` it stays inside and reports an `OutOfMemoryError`
  the runner can render.

Measured 2026-10-07 on the dev box (WSL2, other jobs running, so orders and
not promises): `/run` and `/check` of the 11 starter programs through a fresh
runner, outside the sandbox, every request a cold JVM start, median of three
per program, averaged over the programs. Homebrew OpenJDK 21.0.11 (HotSpot, a
stand-in for the apt JDK 21 the server had) against GraalVM CE 21.0.2, each run
twice, alternating: OpenJDK `/run` 1.69 s and 1.86 s, `/check` 1.70 s and
1.84 s; GraalVM CE `/run` 1.69 s and 2.20 s, `/check` 1.65 s and 2.07 s. The
spread between the two runs of the same JDK (0.15 to 0.5 s, load from other
sessions) is larger than the difference between the JDKs, so no latency
difference is shown either way. Runner startup was 3.1 to 4.1 s on both. Not
measured: the sandboxed units' extra systemd cost, and the production host.

The **run** phase gets its ceiling on the argv the runner builds,
`java -Xmx256m -jar prog.jar` (`RUN_HEAP` in `play/exec.dawn`), since
2026-10-04. Before that it had none, aimed at ~25% of host RAM and was
contained by the cgroup as an opaque kill (checklist item 3 below).
`JAVA_TOOL_OPTIONS` was not an option because `redirectErrorStream(true)`
merges its "Picked up …" banner into the program's own output.

## `POST /compile` (2026-10-07)

The compile view runs three kinds of unit and runs none of the user's program:
`dawn __emitc --map` and `dawn __emit --map` (one unit each, one after the other),
then `javap -c -p -s` of the module's class. Each unit is the same
`run-sandboxed.sh` with every limit above, unchanged; nothing was relaxed for
this endpoint. What differs:

- The three units share the compile budget (`PLAY_COMPILE_TIMEOUT`, 30 s), so
  one request holds its permit no longer than a `/check` does. Each unit still
  has its own `RuntimeMaxSec=15` and 512M.
- The compilers write `out.c`, `c.dawnmap`, `jvm.dawnmap` and `classes/` into
  the box. The runner reads them back after the unit has ended with the same
  read as the diagnostics (a regular file, no link followed), up to 8 MiB each
  and no more in memory; a larger one answers 422 "too large to show" and is
  never mapped. The listing is the unit's stdout, so it goes to a file the
  runner opened, like every phase's output. The `javap` argv is fixed and
  names `box/classes/prog.class`, a path the runner chose.
- The commands run under `env LC_ALL=C.UTF-8`. The unit's environment is
  empty, which the JVM reads as the POSIX locale; there `dawn __emit -o`
  cannot write a class file whose name has a non-ASCII character in it, and
  `javap` prints such names as `?`. The wrapper is untouched, so `/run` and
  `/check` keep the environment they have.
- `javap` lives in a JDK, not the JRE: the server's is the private GraalVM CE in
  `/opt/dawn/graalvm-21` (DEPLOY.md step 2); the runner probes it at start and answers `POST /compile` with 503 when it is missing.

Measured on the dev box (WSL2, 16 cores, other jobs running; load 5 to 9, so
the numbers are orders, not promises): a unit with this wrapper's whole
property set running `true` costs 0.08 to 0.14 s of `systemd-run` overhead
over running it bare; `dawn __emitc` and `dawn __emit` take 1.7 to 2.0 s each
and `javap` 0.2 s on their own. The 11 starter programs, a fresh runner, the
commands outside the sandbox: a cold request is 3.9 to 4.9 s (load 8 to 12)
because the compilers run one after the other, which the small production host
asks for (side by side it was 2.0 to 2.2 s, at four compiler JVMs under two
permits). A hit, including the other target of a program just built, is under
30 ms. The sandboxed figure adds three units' overhead, about 0.2 to 0.3 s,
computed from the numbers above and not measured with the real jars, because
the dev box has no `/opt/dawn` for the wrapper to bind.

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
3. **The box is `0777`, its parent `0711`**, set by the runner before the
   phases (`open_box`, gated on the sandbox switch). The name is an unguessable
   uuid and the parents are `0711` (unlistable), so world-writable is fine.
   Default `DynamicUser` umask (0022) leaves `prog.jar` world-readable, which is
   what the next phase's different uid needs. Until 2026-10-04 the whole request
   directory was `0777` and the output files lived in it.

The runner `rm -rf`s each request directory on every way out, a JVM `Error`
included (`bracket`, in `play/exec.dawn`). It owns the directory and the box,
so it can unlink the DynamicUser-owned files inside. Before 2026-10-04 the
removal ran only after a normal return, and an `OutOfMemoryError` on the read
left the directory behind.

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
8. **Huge output**: print for the whole run → truncated at 64 KB, the runner's
   memory does not move, and the output file stops at `LimitFSIZE`.
9. **Output swap**: from inside the unit, try to replace `../run.txt` with a
   link or a FIFO → denied (the request directory is not writable); the
   response arrives within the run budget.
10. **Timeout reclaim**: send the infinite loop from item 1. Within a second of
   the `phase:"timeout"` response, `systemctl list-units --all
   'dawn-play-run-*'` shows no unit. Until 2026-10-05 a timeout only killed
   `sudo`, which does not reach the unit; it ran on to `RuntimeMaxSec` while
   the runner admitted the next request. Each phase's unit is now named
   `dawn-play-run-<id>`, and the runner ends it with `run-sandboxed.sh stop
   <id>` and waits for it before releasing the gate.

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

### Results — revalidation on the v0.51.0 upgrade (2026-08-05)

The runner had been serving `dawn 0.8.0` since 2026-07-23. Re-checked after the
jump, because a sandbox is only known to hold for the compiler it was tested
with:

- **Compatibility**: unchanged. The invocation shape the sandbox depends on —
  `bin/dawn build <src> -o <jar>`, the work-dir layout, `BindReadOnlyPaths=/opt/dawn`,
  `java` off the default `PATH` — is the same at v0.51.0, and the jar is still
  self-contained (no `std/` on disk: std is embedded as a generated module since
  `b72eabd`). No script change was needed for the upgrade itself; the
  `DAWN_JVM_OPTS` line above was added because `bin/dawn` started pinning
  `-Xmx2g`.
- **`MemoryMax=512M` bites, and bites locally**: `dd` of 300 MiB into the
  private tmpfs succeeds; 900 MiB is killed with
  `constraint=CONSTRAINT_MEMCG, oom_memcg=/system.slice/run-uNNNN.service`,
  and systemd records `Failed with result 'oom-kill'`. The kill is scoped to
  the transient unit — the blog backend on the same 3.4 GB box stayed `active`
  and answering 200 throughout, which is the whole point of capping here rather
  than trusting the host to have room.
- **Timeout**: an infinite loop still comes back as `phase:"timeout"` (~11 s).
- **Headroom**: two concurrent `/run`s (the `MAX_CONCURRENT=2` ceiling) moved
  available memory by ~150 MB, from 2297 MB to 2146 MB. Worst case for the
  whole Playground is bounded by construction at broker 1 GB + 2 × 512 MB.

`scripts/play-live-check.py` re-runs the functional half of this against a
deployed instance (samples byte-compared with their `.out`, plus a compiler
version discriminant in both directions).

## Native LSP sessions

`run-lsp-sandboxed.sh` is deliberately separate from the arbitrary-program
wrapper. It accepts only `run <32-lowercase-hex-id>`, `stop <id>`, or `cleanup`;
the executable is always `/opt/dawn/bin/dawnc lsp`. One WebSocket therefore
owns one named transient service and cannot choose an argv or filesystem path.

Each session has `PrivateNetwork=yes`, a read-only host filesystem, 256 MB RAM,
one CPU, 16 tasks and a 31-minute hard lifetime. The gateway's lifetime is 30
minutes, leaving one minute for cleanup. All sessions additionally live under
`dawn-play-lsp.slice` (512 MB, two CPUs, 48 tasks), so the host-level ceiling
survives a gateway crash; service startup and shutdown clean up named orphan
units. These are conservative initial caps and still require validation against
the production native artifact before `/api/lsp` is exposed.

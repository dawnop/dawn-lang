# gates-external

Run every gate job of `.github/workflows/gates.yml`, as that file stands at
one commit, somewhere other than GitHub, and leave a bundle that says what ran
and what it returned; then sign that bundle and have GitHub check it. The
running is local tooling. The one workflow that reads this directory is
`verify-external.yml`, which runs `verify_note.py` when dispatched.

The design and its reasons are in
[docs/gates-external-design.md](../../docs/gates-external-design.md) (Chinese).

```bash
scripts/gates-external/run.sh --sha <sha> --backend local --jobs 8 --out <dir> [--keep-going]
scripts/gates-external/bundle.py verify <dir>/bundle.json   # recompute everything from git
scripts/gates-external/bundle.py --selftest
scripts/gates-external/gatesplan.py --self-test
scripts/gates-external/run.sh --sha <sha> --backend local --out <dir> --dry-run   # the plan only

scripts/gates-external/publish.py <sha> --bundle <dir>/bundle.json   # sign, note, push, dispatch
scripts/gates-external/publish.py <sha> --bundle <dir>/bundle.json --remote <bare> --dry-run-dispatch
scripts/gates-external/verify_note.py --sha <sha>    # what verify-external.yml runs
scripts/gates-external/verify_note.py --selftest
scripts/gates-external/publish.py --selftest

# inside a prefix: the pinned toolchain and inputs, an environment built from nothing
scripts/gates-external/inputs.py build --prefix ~/dawn-gates      # download, check, lay out
scripts/gates-external/inputs.py verify --prefix ~/dawn-gates     # re-hash everything
scripts/gates-external/run.sh --sha <sha> --backend local --prefix ~/dawn-gates [--only ...]
scripts/gates-external/prefix.py check-isolation --prefix ~/dawn-gates \
    --marker ~/dawn-gates/tmp/marker [--readonly-root] -- <command>
scripts/gates-external/prefix.py selftest --prefix ~/dawn-gates [--break-env-i]

# on the cluster, from a local prefix that holds the input pack
scripts/gates-external/run.sh --sha <sha> --backend crun --prefix ~/dawn-gates --jobs 16 \
    --backend-opt remote-prefix=<cluster dir> [--backend-opt isolation=1] [--only ...] \
    [--backend-opt run-as=UID:GID|root] [--backend-opt private-tmp=0]
```

Exit status of `run.sh`: 0 complete, 1 ran but not complete, 2 refused to
plan, 3 the bundle was refused (leak or schema), nothing written.

## Files

| file | role |
|---|---|
| `gatesplan.py` | what runs: every job and `run:` step of gates.yml at the commit, read from git; each `uses:` resolved through the substitution table, anything unmodelled refused |
| `backend_local.py` | where and how: one job at a time on this machine, in a fresh worktree (a fresh clone inside a prefix) |
| `backend_crun.py` | where and how, on the cluster: ships the input pack and the tools once, then one zero-card `crun run` per job, each running `prefix.py run-job` (the local backend in prefix mode) inside the cluster's prefix |
| `bundle.py` | what it means: schema whitelist, leak filter, and `complete` |
| `runner.py` | when: schedules jobs up to `--jobs`, honours `needs:`, writes `summary.json` and `bundle.json` |
| `run.sh` | the entry point |
| `prefix.py` | the prefix layout, the whitelist environment every prefix job gets, `check-isolation`, and `run-job` (a crun job's remote half) |
| `inputs.py` | the offline input pack: download, check against `inputs.lock.json`, lay out, `verify` |
| `inputs.lock.json` | name, version, URL and sha256 of every download the prefix holds |
| `allowed_signers` | the one public key (identity and namespace `dawn-gates`) a signed bundle is verified against |
| `publish.py` | refuses an invalid or incomplete bundle, signs it, writes the note on `refs/notes/gates`, pushes it, dispatches `verify-external.yml` |
| `verify_note.py` | reads the note, checks the signature and then the bundle against the commit through `bundle.check`, the code `bundle.py verify` runs |
| `release_evidence.py` | release.yml's `verified` verdict: a green ci.yml run at the tag's sha triggered by a push to the default branch (a pull request run is a subset and is refused), or a `gates/maintainer` success written by verify-external.yml on the default branch (the header lists every check); `--selftest` runs first on every tag |
| `steps_lock.py`, `steps.lock.json` | the checked-in expectation of every job family's `run:` steps (issue #167); tree-policy runs `check` on every push |

## The steps lock: removing a step has to be said

`bundle.py` compares what an external run executed with gates.yml at the
same commit, so it cannot see gates.yml itself losing a step, and neither
can any check that compares gates.yml with itself. `steps.lock.json` is the
other side of that comparison: for each job family (a job id with one
trailing `-<digits>` removed, so `contracts-1` and `contracts-2` are
`contracts`), the multiset of its `run:` texts, read with `gatesplan.parse`.

```bash
python3 scripts/gates-external/steps_lock.py check     # tree-policy runs this
python3 scripts/gates-external/steps_lock.py selftest  # and this
python3 scripts/gates-external/steps_lock.py record    # by hand, see below
```

`check` is red when a family has a command the lock does not, or lacks one
the lock has, and names the family and the command. Moving a command between
shards of one family is a reshard and stays green; moving it to another
family is red on both sides.

This is a gate you are expected to open on purpose. When a commit removes,
adds or moves a run step across families, that same commit runs `record` and
commits the rewritten lock, and its message says why. The lock's diff is then
where a reviewer reads which command went; a commit that changes gates.yml's
steps without touching the lock is red. A gates.yml that `gatesplan.py`
refuses is red here too, which is also the moment the external runner could
no longer run it.

## The backend contract

Given a tree and inputs, run the command list in order, and return an exit
code and an output digest per command. A backend is a module
`backend_<name>.py` with `create(ctx)`, where `ctx` carries `repo`, `tree`,
`out`, `options` (from `--backend-opt KEY=VALUE`) and `log`. The object it
returns implements:

| method | meaning |
|---|---|
| `prepare()` | once, before any job |
| `run_job(job, artifacts)` | run one planned job (its ordered actions: `run` steps and `use` steps carrying a replacement id, each with an optional step `id` and `if`; plus `needs_results` from the runner). Expressions and step conditions are evaluated with `gatesplan.expand` and `gatesplan.step_condition_holds`; `artifacts` is the run's artifact store. Returns `{"steps": [...], "ok": bool}`, one step dict per `run` action with `executed`, `exit_code`, `stdout_sha256`, `stderr_sha256` |
| `toolchain()` | the bundle's toolchain fields |
| `cleanup()` | once, after every job |

A backend decides where things run and how each replacement id is realised.
It does not decide what runs (`gatesplan.py`) or what counts as complete
(`bundle.py`). Adding a backend adds a file and changes none.

## The prefix

`--prefix DIR` runs every job inside one directory. Its layout is in
`prefix.py`'s docstring: `toolchain/` (GraalVM CE 21.0.2, node 20, wasi-sdk 34,
python 3.12.3, and the C compiler, gcc 13.3.0), `inputs/` (the archives, the seed jar and std, a coursier
cache, `MANIFEST.json`), `jobs/<sha>/`, `home/`, `tmp/`, `cache/`,
`out/<sha>/`. No location is written into the code.

A prefix job's environment is not the caller's minus a drop list; it is built
from nothing (the effect of `env -i`): `PATH` is the toolchain bins (the
compiler's among them) then `/usr/bin:/bin`, `JAVA_HOME` and `GRAALVM_HOME` the prefix's GraalVM, `HOME`,
`TMPDIR`, `RUNNER_TEMP`, `XDG_CACHE_HOME` and `COURSIER_CACHE` under the prefix
(the last two at a runner's defaults below `HOME`, `.cache` and
`.cache/coursier/v1`, because gate scripts read `~/.cache/coursier/v1` directly),
`LANG=C.UTF-8`, `CI=true`, plus the per-job `GITHUB_*` values the local
backend already sets. `DAWN_SEED` is not set: CI does not set it, and it makes
`seedjar.sh` skip its checksum. The seed reaches a job the way the cache
restore does, copied into `.dawn/seeds`. A job's checkout is a
`git clone --shared` under the prefix, not a worktree, because a worktree
writes into the source repository's `.git`.

One change is made to an unpacked toolchain: each GraalVM launcher in `bin/`
(`java`, `javac`, `jar`, ...) is a shim that execs `bin/<name>.real` with
`-XX:-UsePerfData` first (`-J-XX:-UsePerfData` for all but `java`), because
HotSpot writes `/tmp/hsperfdata_<user>` for every JVM whatever `TMPDIR` says,
and the environment variables that could carry the flag print `Picked up ...`
on stderr. The lock entry is the archive and does not change; `verify` checks
each shim's bytes and that each `.real` is the archive's launcher.

The npm cache is the one input whose bytes are not pinned: npm's index
carries times, so two fills differ. The lock pins the lockfile it is filled
from (`npm_caches`), npm checks every tarball it takes from the cache against
that lockfile's integrity fields, and MANIFEST records the tree digest of the
cache that was built, which `verify` holds it to.

The C compiler is what ubuntu-latest's `cc` is: gcc 13.3.0, with the
sanitizer, libgcc_s and libstdc++ runtimes Ubuntu 24.04 builds from gcc
14.2.0. The lock pins it as ten conda-forge packages (`conda_toolchains`,
121 MiB) with a glibc 2.34 sysroot, so what they link starts on a host from
2.34 up (the cluster has 2.35). The 14.2.0 runtime is not cosmetic: gcc
13.3.0's own libasan dies with `AddressSanitizer:DEADLYSIGNAL` on a kernel
with 32-bit mmap randomisation, and `spike-native` fails closed without
ASan. The packages are unpacked by the prefix's python with a pinned
`zstandard` wheel (`.conda` members are zstd tars), checked file by file
against each package's `info/paths.json`, and relocated as `conda install`
does: gcc's specs then add `-rpath <toolchain>/lib` to every link, which is
how an ASan binary finds the pack's libasan and not the host's. The
relocated files are hashed with the placeholder put back, so the tree digest
is the same wherever the prefix lives. Steps reach the compiler only as `cc`
on `PATH`; `CC` and `DAWN_WASM_CC` are not set, as on CI. The compiler's
MANIFEST rows sit under `conda_items`, which verifiers from before it do not
read, because the shared prefixes are verified by other branches' tools too.
It is recorded in `toolchain.cc` (`cc (conda-forge gcc 13.3.0-2) 13.3.0`),
like python, node and java, and has no substitution row: that table is
derived from the commit, and a new unconditional row would invalidate
bundles already published.

`inputs.py` trusts only the digests in `inputs.lock.json`. The seed jar and std
are checked against `scripts/seed-checksums.txt` and `seed-std-checksums.txt`,
the tables `seedjar.sh` reads, and the coursier jars against
`selfhost/dawn.lock`. Downloads are not in the repository; their digests are.

`check-isolation` touches a marker in the prefix, runs the command, then lists
every path outside the prefix (on `/` and on the prefix's filesystem, `-xdev`,
pseudo filesystems pruned) whose mtime or ctime is newer. `--exclude` names
paths other processes write (a shared workstation has several); they are
printed with the result. `--readonly-root` runs the command under bubblewrap
with everything but the prefix read-only, so a write outside fails the
command instead of waiting to be found.

Without `--prefix` nothing changes: the host-environment path of the first
knife is kept as it was.

On the cluster a container gives root and nothing else, while CI runs every
job as an ordinary user, and two contracts refuse root (root reads a
`chmod 000` file and writes an unwritable directory). So `prefix.py run-job`
starts as root, hands the writable part of the prefix (`home/`, `tmp/`,
`cache/`, `repos/<sha>.git`, `jobs/<sha>`, `out/<sha>`) to uid 20000, and
re-executes itself through `setpriv --reuid --regid --clear-groups
--no-new-privs`. `toolchain/` and `inputs/` stay root's, so a job cannot
change what it is measured with. A uid change does not close `/tmp`,
`/var/tmp` and `/dev/shm`, which anyone may write, so the job also gets a
private mount namespace in which each is a per-job directory in the prefix
(what a fresh CI VM gives a job; a JVM's `java.io.tmpdir` ignores `TMPDIR`).
`run-as=root` is the negative control; `private-tmp=0` keeps the shared ones.

## The substitution table

| `uses:` / adjustment | replacement id | local meaning |
|---|---|---|
| `plan` (the #168 job) | `external-all` | not executed: an external run is the full set, so each gate job's condition on the plan's outputs is taken as satisfied. Only the exact wiring #168 wrote is accepted (the job naming itself); any other condition is refused |
| `actions/checkout@v4` | `tree-worktree` | `git worktree add --detach <sha>` in a fresh directory per job. Full history and tags are present even where CI checks out at depth 1 |
| `./.github/actions/dawn-toolchain` | `dawn-toolchain-local` | JDK 21 on `JAVA_HOME` and `PATH`; the seed cache copied in from the shared cache (seedjar.sh re-verifies it); `./bin/dawn --version` unless `build: 'false'`. The composite's `action.yml` is fingerprinted at the same commit and a changed composite is refused |
| `actions/cache@v4` | `noop` | nothing saved; the restore half is the seed-cache copy above, and coursier's cache is the user's own |
| `actions/upload-artifact@v4` | `artifact-store-local` | copied to `<out>/artifacts/<name>`; `if-no-files-found: error` is honoured |
| `actions/download-artifact@v4` | `artifact-fetch-local` | every artifact matching `pattern` copied to `<path>/<name>` |
| `actions/setup-node@v4` | `node-host` | the host's `node` (the prefix's node 20 under `--prefix`), whose version is recorded in the bundle |
| `actions/setup-java@v4` | `jdk21-host` | the same local JDK 21 (GraalVM CE, not Temurin; the prefix's under `--prefix`); only `java-version: '21'` is accepted |
| `adjust:runner-temp` | `per-job-directory` | `RUNNER_TEMP` and `${{ runner.temp }}` point at a per-job directory outside the worktree |
| `adjust:tmpdir` | `per-job-directory` | `TMPDIR` is per job |
| `adjust:literal-tmp-paths` | `machine-wide-lock` | a step naming a literal `/tmp/<name>` path holds a lock on it, so two runs of this script cannot share it |
| `adjust:github-env-files` | `per-step-files` | `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY` are per-step files, and ENV/PATH carry to later steps |
| `adjust:npm-offline-cache` | `input-pack-npm-cache` | under `--prefix`, `npm_config_cache` is a copy of the input pack's npm cache (filled by `npm ci` from the pinned `site/play-ui/package-lock.json`) and `npm_config_offline=true`, so the docs job's `npm install` never reaches a registry. Listed only for a commit that uses `actions/setup-node` |
| `adjust:wasi-sdk-tarball` | `input-pack-tarball` | under `--prefix`, `WASI_SDK_TARBALL` names the input pack's wasi-sdk archive, which wasm-target's step copies instead of downloading; the step's pinned sha256 is checked either way. Listed only for a commit whose gates.yml reads the variable; without `--prefix` it is not set and the step downloads |

A `uses:` reference not in this table (including a version bump of one that
is) makes `run.sh` refuse before any job starts.

## The bundle

Fields: `tree`, `gates_blob`, `substitutions[]` (`subject`, `replacement`),
`steps[]` (`job`, `name`, `command`, `exit_code`, `stdout_sha256`,
`stderr_sha256`, `executed`), `toolchain` (`seed_jar_sha256`, `java`, `cc`,
`python`, `node`), `complete`. Nothing else, at any depth.

`complete` is true only when the multiset of (job, run text) over every run
step of gates.yml at `tree` equals the multiset over executed steps, and every
executed step exited 0. `bundle.py verify` recomputes it from git and ignores
the bundle's own claim.

Logs, timings and the memory peak stay in `<out>/logs` and
`<out>/summary.json`, which are for the person who ran it and are not evidence.

## Signed evidence

The note on a commit in `refs/notes/gates` is an envelope with exactly two
fields, `{"bundle": <bundle>, "signature": "<armored SSH signature>"}`. The
signature is `ssh-keygen -Y sign -n dawn-gates` over the bundle's canonical
bytes, `json.dumps(bundle, sort_keys=True, separators=(",", ":"))` plus a
newline, so the envelope's own formatting does not matter.

`verify-external.yml` takes the verifier and `allowed_signers` from the default
branch and reads the commit under test as objects only, so a commit cannot
vouch for itself. It writes the commit status `gates/maintainer`: `success`
when every item of `verify_note.py`'s checklist holds, `failure` otherwise.
Anyone can repeat the check:

```bash
git fetch origin refs/notes/gates:refs/notes/gates
python3 scripts/gates-external/verify_note.py --sha <sha>
```

What nobody but the key holder can vouch for is that the steps really ran;
the exit codes and output digests are the maintainer's statement. The
protocol and its limits are in [docs/bootstrap.md](../../docs/bootstrap.md)
(Chinese).

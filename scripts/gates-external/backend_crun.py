"""The crun backend: run each gates.yml job on the cluster, inside a prefix.

Why this exists. The local backend needs 80 minutes of a shared 16-core
workstation for the full set; the cluster has 256 cores per container and no
quota. What it lacks is a network (so every input travels from here, once)
and a toolchain we choose (its JAVA_HOME is Hadoop's Java 8, its python and
gcc are whatever the image has). So this backend does not run anything of its
own on the cluster: it ships the prefix's input pack and this directory's
tools, and each job runs as prefix.py run-job, which is the local backend in
prefix mode. What runs a job is then the same code on both sides, and the
bundle's toolchain fields must come out the same as a local prefix run's;
that equality is the check that the backend changed where, not what.

How a run goes (all remote paths under --backend-opt remote-prefix=P, which
is the same path on every machine, each on that machine's own disk):

  machines  `crun status` names the cluster's machines and which of them
            answer; each one that answers becomes a lettered machine (A, B,
            ...; the letters and the addresses behind them are kept in
            <out>/crun/machines.json and never leave this machine)
  prepare   1. a staging directory (not a worktree) holding this directory's
               tools, a git bundle of the commit and every tag, one JSON per
               planned job, and a .crun.yaml whose remote_root is
               P/jobs/<sha>/tree-<tools>, unique per commit and per version
               of these tools (a digest of TOOL_FILES), so no two projects,
               and no two controllers with different tools, ever rsync
               --delete into each other
            2. on every machine at once, `crun run -m <machine>`: the core
               count and load average, then `inputs.py verify`; if the pack
               is missing or red there, a second staging directory (hard
               links to the local prefix's inputs/) goes to P/inputs and
               `inputs.py install` extracts and re-verifies it on that
               machine. Before the pack, the job uid (run-as) must be able
               to start the prefix python there. A machine that does not
               answer, that the job uid cannot use, or whose pack will not
               verify, is dropped for this run; the run fails only when none
               is left
  run_job   `crun run -n 0 --no-build -m <machine> -d -- bash -c <wrapper>`:
            one detached zero-card crun per job, at most --jobs at once, on
            the machine chosen at launch (below). The wrapper claims the job
            (mkdir P/out/<sha>/<run>.ctl/<job>.claim, holding the machine's
            letter, so a second launch of the same job on the same machine is
            a no-op), runs `env -i ... prefix.py run-job` with its stdout and
            stderr in that directory, and writes <job>.exit last. crun pushes
            the staging directory to its primary machine on every call (an
            unchanged tree is a few seconds; crun serialises the pushes
            itself) and from there rsyncs it to the chosen machine
  poll      one thread; every poll=SECONDS (default 30) one short
            `crun run -n 0 --no-sync --no-build -m <machine>` per machine
            that has jobs out, run side by side, which prints that machine's
            core count and load and each of its jobs' state: absent, running
            (claimed), or done with its exit code, fragment, stdout and stderr
  results   run-job writes its result fragment to
            P/out/<sha>/<run>/fragments on its machine; logs and artifacts
            stay there. Only the fragments come back, and the runner builds
            bundle.json from them as for any backend; nothing in a fragment
            names a machine
  artifacts a job that uploads (upload-artifact) has those artifacts tarred
            into the poll that reports it done, and the controller keeps
            them; a job with needs: that is launched on another machine than
            a needed job ran on gets them in the staging directory
            (xfer/<run>/<job>.tar.gz), and its wrapper unpacks them into its
            machine's P/out/<sha>/<run>/artifacts before run-job starts

Why several machines, and why chosen by load (2026-10-04). A zero-card crun
without -m always lands on crun's primary machine. With six writers each
running --jobs 8, that machine's load average sat at 175-205 on 256 cores
while the two others idled at 2-5 on 224 each; a single job went from ~10 to
20+ minutes and a full round from ~20 to ~65. Rotating jobs over the machines
would still send a third of ours to the hottest one, because the other
controllers do not rotate. So each launch goes to the machine with the least
(load + recent) / cores, where load is the 1-minute load average from the
latest poll or prepare, and recent is job-load (default 4) for each job this
controller launched there in the last 90 s, which a 1-minute average does not
show yet; a long run would otherwise pile its first dozen launches on
whichever machine looked idle at prepare. This is no scheduler: it does not
know the other controllers' plans, only what the load says now.

Why job-load is 4. The first full run used 8 and put 13 of 34 jobs on the
primary (load 81 at prepare, 185 at peak) while the idle machine, given 21,
peaked at 75: about 3.6 per job. At 8 the idle machine looked full after
nine quick launches; jobs placed on the primary averaged 585 s, those on the
idle one 386 s, and the five longest all ran on the primary.

Why each machine prepares its own prefix. The prefix sits on a disk local to
each machine, so the input pack, the toolchain, the claims and the fragments of a
job all live where it ran. Shipping goes through crun's own route (push to
the primary, rsync from there, both incremental), so a pack already on the
primary costs nothing from here and the copy to another machine is a
cluster-internal rsync, not another 0.6 MB/s upload.

When a machine goes away mid-run. A machine whose polls or launches fail
dead-after times in a row (default 6, three minutes at the default poll) is
marked down for the rest of the run, and every job out on it is launched
again on another machine. A job that did start there and finishes later is
harmless: its fragment stays on that machine's disk and nothing reads it.

Why artifacts travel instead of pinning jobs together (2026-10-05). Each
machine's prefix is its own disk, so an artifact lives where its job ran. A
full run of a branch came out complete=false for that alone: the fan-in job
mutant-shards-complete ran on one machine, builtin-type-3-3 on another, and
the fan-in found no coverage record from that shard though the shard had
passed. The one dependency gates.yml has (its header lets no job need
another except this fan-in) is eight mutation shards into one seconds-long
job. Pinning the dependency closure to one machine would put those eight,
among the longest jobs of the set, on one machine, which is the
concentration this backend exists to avoid, and would have to choose the
machine when the first shard starts, long before the fan-in. Moving the
artifacts instead costs a few KiB per shard (coverage records) through the
poll that already reports the job and the push every launch already makes,
and leaves every job free to go where the load is. The artifact names come
from the plan (each upload step's literal `name:`); a name that is an
expression is refused in prepare rather than guessed at.

Why detached and polled (2026-09-25). A synchronous crun holds one SSH
session for the length of the job, and crun kills the remote job when that
session drops (its guard exists so that a killed controller does not leave
work behind). Two full runs were lost that way, crun exiting 255 twenty-odd
minutes in, and the retry only covered a crun that failed before the job
started. With -d the job lives in a tmux session on the cluster, which
survives the SSH session that started it (probed before this was written:
a detached `sleep 300` wrote its file five minutes after the launching crun
had returned). A dropped poll costs one poll interval; a dropped launch is
settled by the claim: the next poll says whether the job started, and it is
launched again only if it did not.

Resuming. The run id is kept in <out>/crun/run-id and the machine letters in
<out>/crun/machines.json, and with resume=1 (run.sh --resume) the backend
reads both back instead of making new ones, polls every job once on every
machine in prepare, and hands the runner every job that already finished
(finished()); a job still running is waited for on its machine, not launched
again, and a job with no claim anywhere is launched. Where two machines
answer for one job (it was launched again after its machine stopped
answering), done beats running beats absent, and among equals the machine
dispatch.txt names last wins. A job that finished without a fragment (a
crash, or a fragment deleted since) is a failed job, never re-run silently
and never skipped, so the bundle cannot come out complete.

Why the tree is a git bundle rather than the detached worktree the task sheet
named: jobs need history (tree-policy reads Emit-Change declarations back to
the last tag and replays pinned commits), and every job gets its own fresh
clone, as on CI. A worktree's .git is a pointer into this machine's
repository and means nothing on the cluster.

Options (--backend-opt):
  remote-prefix=DIR   the prefix on the cluster (required; no location is
                      written into this code, and a path on a shared cluster
                      disk names the person who owns it)
  machines=auto|N|primary
                      auto (default): every machine `crun status` lists that
                      answers; N: the N least loaded of those after prepare;
                      primary: no -m at all, every job on crun's primary
                      machine, which is what this backend did before
  job-load=F          the load one fresh launch is assumed to add (default 4)
  dead-after=N        failed polls or launches in a row before a machine is
                      dropped (default 6)
  stage=DIR           local staging root (default <--prefix>/stage)
  crun=CMD            the crun executable (default crun)
  isolation=1         wrap every remote job in prefix.py check-isolation
  run-as=UID:GID      the identity a job runs as (default 20000:20000);
                      run-as=root keeps the container's root, which is
                      the negative control for the two contracts that
                      refuse it. The uid has no passwd entry on purpose:
                      a name borrowed from the image (nobody) is shared
                      with whatever else runs under it
  private-tmp=0       with run-as: keep the container's /tmp, /var/tmp and
                      /dev/shm instead of per-job directories in the prefix
                      (default 1; world-writable, so a uid change alone
                      does not keep a job out of them)
  keep-going=1, timeout-scale=F   passed through to the local backend
  start-gap=SECONDS   minimum spacing between crun starts (default 2)
  poll=SECONDS        interval between polls (default 30)
  wait-scale=F        how long the controller waits for a job, as a multiple
                      of its timeout-minutes (default: timeout-scale + 1, so
                      the job's own timeout inside run-job fires first and is
                      reported as a step result); past it the job is red
  resume=1            reuse <out>/crun/run-id (set by run.sh --resume)
"""

import base64
import concurrent.futures
import hashlib
import json
import re
import shlex
import shutil
import string
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gatesplan  # noqa: E402
import prefix as prefix_mod  # noqa: E402

# A container gives root and nothing else; CI runs jobs as an ordinary user,
# and two contracts refuse root. prefix.py run-job drops to this identity.
DEFAULT_RUN_AS = "20000:20000"

# A launch or a poll is a push and a short command, ~5-15 s; one still going
# after this is a stalled connection, and waiting on it would stall every job.
POLL_TIMEOUT = 300

# How long a launch counts as load the load average has not caught up with.
RECENT_SECONDS = 90

# runner.py --resume asks for this: jobs run detached on the cluster and
# outlive the controller that launched them.
RESUMABLE = True

TOOL_FILES = ("prefix.py", "inputs.py", "backend_local.py", "gatesplan.py", "inputs.lock.json")

# What the remote side prints before anything else: core count and load.
LOAD_PROBE = "echo \"GATES-LOAD $(nproc) $(cut -d' ' -f1 /proc/loadavg)\""


def create(ctx):
    return CrunBackend(ctx)


class Machine:
    """One cluster machine, by letter; `host` is crun's -m value (None: no -m)."""

    def __init__(self, label, host):
        self.label = label
        self.host = host
        self.cores = None
        self.load = None
        self.up = True
        self.failures = 0
        self.recent = []  # monotonic times of this controller's recent launches here

    def flag(self):
        return ["-m", self.host] if self.host else []

    def note_load(self, text):
        """Take a `GATES-LOAD <cores> <load1>` line out of remote output."""
        for line in text.splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[0] == "GATES-LOAD":
                try:
                    self.cores, self.load = int(fields[1]), float(fields[2])
                except ValueError:
                    continue
                return True
        return False

    def score(self, job_load, now):
        self.recent = [t for t in self.recent if now - t < RECENT_SECONDS]
        if not self.cores:
            return float("inf")
        return ((self.load or 0.0) + job_load * len(self.recent)) / self.cores


class CrunBackend:
    def __init__(self, ctx):
        self.repo = Path(ctx["repo"])
        self.tree = ctx["tree"]
        self.out = Path(ctx["out"])
        self.log = ctx["log"]
        opts = ctx["options"]
        if not opts.get("prefix"):
            raise SystemExit("crun backend: --prefix (the local prefix holding the input pack) "
                             "is required")
        self.local_prefix = Path(opts["prefix"]).resolve()
        if not opts.get("remote-prefix"):
            raise SystemExit("crun backend: --backend-opt remote-prefix=DIR is required")
        self.remote = opts["remote-prefix"].rstrip("/")
        self.stage_root = Path(opts.get("stage") or self.local_prefix / "stage")
        self.crun = shlex.split(opts.get("crun", "crun"))
        self.isolation = opts.get("isolation", "0") == "1"
        run_as = opts.get("run-as", DEFAULT_RUN_AS)
        self.run_as = None if run_as == "root" else run_as
        self.private_tmp = opts.get("private-tmp", "1") == "1"
        self.start_gap = float(opts.get("start-gap", "2"))
        self.pass_opts = [f"{k}={opts[k]}" for k in ("keep-going", "timeout-scale") if k in opts]
        self.poll_interval = float(opts.get("poll", "30"))
        self.wait_scale = float(opts.get("wait-scale",
                                         float(opts.get("timeout-scale", "2")) + 1))
        self.machines_opt = opts.get("machines", "auto")
        if not (self.machines_opt in ("auto", "primary") or self.machines_opt.isdigit()):
            raise SystemExit(f"crun backend: machines={self.machines_opt}: want auto, primary "
                             "or a number")
        self.job_load = float(opts.get("job-load", "4"))
        self.dead_after = int(opts.get("dead-after", "6"))
        run_id_file = self.out / "crun" / "run-id"
        self.resuming = opts.get("resume", "0") == "1"
        if self.resuming:
            if not run_id_file.is_file():
                raise SystemExit(f"crun backend: nothing to resume, {run_id_file} is missing")
            self.run_id = run_id_file.read_text().strip()
        else:
            self.run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            run_id_file.parent.mkdir(parents=True, exist_ok=True)
            run_id_file.write_text(self.run_id + "\n")
        self.ctl = f"{self.remote}/out/{self.tree}/{self.run_id}.ctl"
        self.fragments = {}
        self.start_lock = threading.Lock()
        self.ship_lock = threading.Lock()
        self.last_start = 0.0
        # Polling: the jobs still out, the machine each was last launched on,
        # the latest (machine, state) of each, and a round counter the
        # waiting threads block on.
        self.cond = threading.Condition()
        self.watched = set()
        self.assigned = {}
        self.states = {}
        self.round = 0
        self.stopping = False
        self.poller = None
        self.polls = {"ok": 0, "failed": 0}
        self.initial = {}
        self.machines = []
        self.dispatch_log = self.out / "crun" / "dispatch.txt"
        # job id -> the artifact names it uploads (from the plan), and
        # job id -> (machine letter, tar.gz bytes) once it is done
        self.uploads = {}
        self.artifact_tars = {}
        # What a job runs is the commit and these tools, so both name the
        # staging directory and the remote tree. Keyed by the commit alone,
        # two controllers on one commit with different tools (a branch's run
        # of origin/main as its baseline, beside this one) overwrite each
        # other's tools/ between crun pushes, and a job runs whichever landed
        # last: seen as 18 of 39 jobs of one run reporting the cluster's gcc
        # 11.4 instead of the input pack's compiler.
        self.tools_tag = tools_digest()[:12]
        self.tree_remote = f"{self.remote}/jobs/{self.tree}/tree-{self.tools_tag}"

    # ------------------------------------------------------------ helpers

    def _python(self):
        return f"{self.remote}/toolchain/{prefix_mod.download('python')['dir']}/bin/python3"

    def _envi(self):
        """The literal `env -i` every remote command starts from."""
        return ["env", "-i", "PATH=/usr/bin:/bin", f"HOME={self.remote}/home", "LANG=C.UTF-8"]

    def _crun(self, stage, machine, command, label, sync=True, detach=False, timeout=None):
        """One zero-card crun from a staging directory; (exit, stdout, stderr).

        With a timeout, a crun that hangs (an SSH session that stalls rather
        than drops) is killed and reported as exit 124.
        """
        with self.start_lock:
            wait = self.last_start + self.start_gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last_start = time.monotonic()
        argv = list(self.crun) + ["run", "-n", "0", "--no-build"] + machine.flag()
        if not sync:
            argv.append("--no-sync")
        if detach:
            argv.append("-d")
        argv += ["--"] + command
        t0 = time.monotonic()
        try:
            done = subprocess.run(argv, cwd=stage, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as expired:
            done = subprocess.CompletedProcess(
                argv, 124, _text(expired.stdout), _text(expired.stderr) + f"\ntimed out after {timeout}s\n")
        record = self.out / "crun" / f"{label}-{machine.label}.txt"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(f"$ {shlex.join(argv)}\n# exit {done.returncode} after "
                          f"{time.monotonic() - t0:.0f}s\n--- stdout\n{done.stdout}"
                          f"--- stderr\n{done.stderr}")
        return done.returncode, done.stdout, done.stderr

    @staticmethod
    def _write_crun_yaml(stage, remote_root):
        (stage / ".crun.yaml").write_text(
            "# written by scripts/gates-external/backend_crun.py; never committed\n"
            f"remote_root: {remote_root}\n"
            "build: 'true'\n")

    # ------------------------------------------------------------ machines

    def _discover(self):
        """The machines this run may use, lettered; the letters survive --resume."""
        map_file = self.out / "crun" / "machines.json"
        saved = {}
        if self.resuming and map_file.is_file():
            saved = json.loads(map_file.read_text())
        if self.machines_opt == "primary":
            return [Machine("A", None)]
        done = subprocess.run(list(self.crun) + ["status"], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=POLL_TIMEOUT)
        # A machine is a `<host>  (<type>[, primary])` line; it answered when
        # at least one `  GPU <n>: ...` line follows it (an unreachable one
        # gets a one-line reason instead).
        hosts = []
        for line in done.stdout.splitlines():
            head = re.match(r"^(\S+)\s+\(([^)]*)\)\s*$", line)
            if head:
                hosts.append([head.group(1), False])
            elif hosts and re.match(r"^\s+GPU \d+:", line):
                hosts[-1][1] = True
        if not hosts:
            self.log("crun backend: `crun status` named no machine; every job goes to crun's "
                     "primary machine")
            return [Machine("A", None)]
        by_host = {host: label for label, host in saved.items()}
        letters = iter(c for c in string.ascii_uppercase if c not in saved)
        machines = []
        for host, reachable in hosts:
            label = by_host.get(host) or next(letters)
            by_host[host] = label
            machine = Machine(label, host)
            machine.up = reachable
            machines.append(machine)
        map_file.parent.mkdir(parents=True, exist_ok=True)
        map_file.write_text(json.dumps({m.label: m.host for m in machines}, indent=2,
                                       sort_keys=True) + "\n")
        down = [m.label for m in machines if not m.up]
        self.log(f"crun backend: machines {', '.join(m.label for m in machines)}"
                 + (f"; {', '.join(down)} not answering `crun status`" if down else ""))
        return machines

    def _drop(self, machine, why):
        if machine.up:
            machine.up = False
            self.log(f"crun backend: machine {machine.label} dropped from this run: {why}")

    def _failed(self, machine, what):
        """One more failure in a row; dead-after of them drop the machine."""
        machine.failures += 1
        if machine.failures >= self.dead_after:
            self._drop(machine, f"{machine.failures} {what} failures in a row")

    def _up(self):
        return [m for m in self.machines if m.up]

    def _pick(self, avoid=()):
        """The machine for one launch: the least (load + recent) per core."""
        with self.cond:
            now = time.monotonic()
            candidates = [m for m in self._up() if m.label not in avoid] or self._up()
            if not candidates:
                return None
            machine = min(candidates, key=lambda m: (m.score(self.job_load, now), m.label))
            machine.recent.append(now)
            return machine

    # ------------------------------------------------------------ prepare

    def prepare(self):
        plan = gatesplan.plan_at(str(self.repo), self.tree)
        # the seed this commit pins: a pack built for an older one verifies
        # green row by row and then sends every toolchain step to the network
        self.seed_tag = subprocess.run(
            ["git", "-C", str(self.repo), "show", f"{self.tree}:scripts/seed-release.txt"],
            check=True, capture_output=True, text=True).stdout.strip()
        stage = self.stage_root / "jobs" / f"{self.tree}-{self.tools_tag}"
        self.stage = stage
        t0 = time.monotonic()
        tools = stage / "tools"
        shutil.rmtree(tools, ignore_errors=True)
        tools.mkdir(parents=True)
        for name in TOOL_FILES:
            shutil.copy2(HERE / name, tools / name)
        jobs = stage / "jobs"
        shutil.rmtree(jobs, ignore_errors=True)
        jobs.mkdir()
        for job in plan["jobs"]:
            (jobs / f"{job['id']}.json").write_text(json.dumps(job, sort_keys=True) + "\n")
            self.uploads[job["id"]] = upload_names(job)
        bundle = stage / "repo.bundle"
        if not bundle.exists():
            self._make_bundle(bundle)
        self._write_crun_yaml(stage, self.tree_remote)
        self.log(f"crun backend: staged {stage} ({bundle.stat().st_size / 2**20:.1f} MiB bundle) "
                 f"in {time.monotonic() - t0:.0f}s; remote prefix {self.remote}, run {self.run_id}, "
                 f"jobs run as {self.run_as or 'root'}")

        self.machines = self._discover()
        live = self._up()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(live))) as pool:
            list(pool.map(self._prepare_machine, live))
        live = self._up()
        if not live:
            raise SystemExit("crun backend: no machine is left to run on (see the log above "
                             f"and {self.out / 'crun'})")
        if self.machines_opt.isdigit():
            keep = sorted(live, key=lambda m: (m.score(self.job_load, time.monotonic()),
                                               m.label))[:max(1, int(self.machines_opt))]
            for machine in live:
                if machine not in keep:
                    machine.up = False
            live = keep
        self.log("crun backend: running on " + ", ".join(
            f"{m.label} ({m.cores} cores, load {m.load})" for m in live))
        if self.resuming:
            self._resume_states([job["id"] for job in plan["jobs"]])

    def _prepare_machine(self, machine):
        t0 = time.monotonic()
        code, out, err = self._verify_remote(machine, sync=True)
        if not machine.note_load(out):
            self._drop(machine, f"no answer (crun exit {code})")
            return
        if "GATES-NOREACH" in out.splitlines():
            self._drop(machine, f"uid {self.run_as} cannot run the prefix python there")
            return
        self.log(f"crun backend: machine {machine.label}: {machine.cores} cores, load "
                 f"{machine.load}; first push and inputs verify: exit {code} in "
                 f"{time.monotonic() - t0:.0f}s")
        if code != 0:
            try:
                self._ship_inputs(machine)
            except MachineError as error:
                self._drop(machine, str(error))
                return
            code, out, err = self._verify_remote(machine, sync=False)
            if "GATES-NOREACH" in out.splitlines():
                self._drop(machine, f"uid {self.run_as} cannot run the prefix python there")
                return
            if code != 0:
                self._drop(machine, f"the input pack does not verify after shipping: "
                                    f"{(out + err)[-500:]}")
                return
        self.log(f"crun backend: machine {machine.label}: the input pack verifies")

    def _resume_states(self, ids):
        """Every job's state on every machine, merged; the machine each is on."""
        last = {}
        if self.dispatch_log.is_file():
            for line in self.dispatch_log.read_text().splitlines():
                fields = line.split("\t")
                if len(fields) >= 4 and fields[3].startswith("machine "):
                    last[fields[0]] = fields[3].split()[1]
        merged = {}
        rank = {"absent": 0, "running": 1, "done": 2}
        for machine in self._up():
            states = None
            for _ in range(3):
                states = self._poll_once(machine, ids)
                if states is not None:
                    break
                time.sleep(self.poll_interval)
            if states is None:
                self._drop(machine, "cannot read the earlier run's state there (three polls "
                                    "failed)")
                continue
            for jid, state in states.items():
                old = merged.get(jid)
                better = (old is None or rank[state["state"]] > rank[old[1]["state"]]
                          or (rank[state["state"]] == rank[old[1]["state"]]
                              and last.get(jid) == machine.label))
                if better:
                    merged[jid] = (machine, state)
        if not self._up():
            raise SystemExit("crun backend: cannot read the earlier run's state on any machine")
        self.initial = {jid: state for jid, (_, state) in merged.items()}
        for jid, (machine, state) in merged.items():
            if state["state"] == "running":
                self.assigned[jid] = machine
        counts = {}
        for state in self.initial.values():
            counts[state["state"]] = counts.get(state["state"], 0) + 1
        self.log(f"crun backend: resuming run {self.run_id}: "
                 + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))

    def _make_bundle(self, bundle):
        """The commit and every tag, and nothing that names this machine."""
        tmp = bundle.with_suffix(".git")
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "clone", "-q", "--bare", "--shared", str(self.repo), str(tmp)],
                       check=True)
        subprocess.run(["git", "-C", str(tmp), "update-ref", "refs/heads/gates-tree", self.tree],
                       check=True)
        # The range leg of the differentials (scripts/emitrange.sh) takes the
        # change's base as merge-base(main, HEAD), and a bundle with only the
        # commit and tags has no main to take it with. origin/main goes in as
        # refs/heads/main; a source repository without one ships without it
        # and the leg says so, loudly, rather than guessing a base.
        refs = ["refs/heads/gates-tree"]
        main = subprocess.run(["git", "-C", str(tmp), "rev-parse", "--verify", "-q",
                               "refs/remotes/origin/main"], capture_output=True, text=True)
        if main.returncode != 0:
            main = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "-q",
                                   "refs/remotes/origin/main"], capture_output=True, text=True)
        if main.returncode == 0 and main.stdout.strip():
            subprocess.run(["git", "-C", str(tmp), "update-ref", "refs/heads/main",
                            main.stdout.strip()], check=True)
            refs.append("refs/heads/main")
        subprocess.run(["git", "-C", str(tmp), "bundle", "create", "-q", str(bundle),
                        *refs, "--tags"], check=True)
        shutil.rmtree(tmp)

    def _verify_remote(self, machine, sync):
        """Load, then whether the job uid can reach the prefix, then the pack.

        The uid check exists because a prefix can verify green as root and
        still be out of a job's reach: on one machine a directory above the
        prefix, which is not ours to change, is mode 700 to another uid, and
        every job there died at once loading the prefix python's libpython.
        The marker is matched as a whole line: crun echoes the command it
        runs, marker included, on the same stdout.
        """
        py = self._python()
        reach = ""
        if self.run_as:
            uid, gid = self.run_as.split(":")
            reach = (f"setpriv --reuid={uid} --regid={gid} --clear-groups --no-new-privs "
                     f"{py} -B -c pass || {{ echo GATES-NOREACH; exit 3; }}; ")
        script = (f"{LOAD_PROBE}; "
                  f"if [ ! -x {py} ]; then echo 'no prefix python yet'; exit 1; fi; {reach}"
                  f"exec {py} -B {self.tree_remote}/tools/inputs.py verify "
                  f"--prefix {self.remote} --seed-tag {shlex.quote(self.seed_tag)}")
        return self._crun(self.stage, machine, self._envi() + ["bash", "-c", script],
                          "inputs-verify", sync=sync)

    def _ship_inputs(self, machine):
        """Hard links to the local prefix's inputs/, pushed to P/inputs by crun.

        One machine at a time: every ship pushes the same directory to the
        primary first, and two pushes into one remote_root break each other.
        """
        with self.ship_lock:
            self._ship_inputs_locked(machine)

    def _ship_inputs_locked(self, machine):
        local_inputs = self.local_prefix / "inputs"
        if subprocess.run([sys.executable, "-B", str(HERE / "inputs.py"), "verify", "--prefix",
                           str(self.local_prefix), "--seed-tag", self.seed_tag],
                          capture_output=True).returncode != 0:
            raise MachineError(f"the local input pack does not verify for seed "
                               f"{self.seed_tag}; run inputs.py build --repo <a checkout at "
                               f"{self.tree}> first")
        stage = self.stage_root / f"inputs-{self.run_id}-{machine.label}"
        shutil.rmtree(stage, ignore_errors=True)
        subprocess.run(["cp", "-al", str(local_inputs), str(stage)], check=True)
        self._write_crun_yaml(stage, f"{self.remote}/inputs")
        size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
        python = prefix_mod.download("python")
        archive = urllib_name(python["url"])
        pydir = f"{self.remote}/toolchain/{python['dir']}"
        # The one step before a prefix python exists: unpack it with tar.
        script = (f"set -e; mkdir -p {self.remote}/toolchain; "
                  f"if [ ! -x {pydir}/bin/python3 ]; then rm -rf {pydir}.tmp; mkdir -p {pydir}.tmp; "
                  f"tar xzf {self.remote}/inputs/downloads/{shlex.quote(archive)} -C {pydir}.tmp "
                  f"--strip-components=1; mv {pydir}.tmp {pydir}; fi; "
                  f"exec {pydir}/bin/python3 -B {self.tree_remote}/tools/inputs.py install "
                  f"--prefix {self.remote}")
        t0 = time.monotonic()
        self.log(f"crun backend: machine {machine.label}: shipping the input pack "
                 f"({size / 2**20:.0f} MiB) to {self.remote}/inputs")
        code, out, err = self._crun(stage, machine, self._envi() + ["bash", "-c", script],
                                    "inputs-ship")
        shutil.rmtree(stage, ignore_errors=True)  # hard links, one per run and machine
        self.log(f"crun backend: machine {machine.label}: input pack shipped and installed: "
                 f"exit {code} in {time.monotonic() - t0:.0f}s")
        if code != 0:
            raise MachineError(f"shipping the input pack failed (exit {code}); see "
                               f"{self.out / 'crun'}")

    # ------------------------------------------------------------- jobs

    def _inner(self, job):
        """The remote job command, unchanged from the synchronous backend."""
        jid = job["id"]
        needs = ",".join(f"{k}={v}" for k, v in sorted((job.get("needs_results") or {}).items()))
        inner = [self._python(), "-B", f"{self.tree_remote}/tools/prefix.py", "run-job",
                 "--prefix", self.remote, "--sha", self.tree, "--run-id", self.run_id,
                 "--git-bundle", f"{self.tree_remote}/repo.bundle",
                 "--job-file", f"{self.tree_remote}/jobs/{jid}.json"]
        if needs:
            inner += ["--needs", needs]
        for item in self.pass_opts:
            inner += ["--opt", item]
        if self.run_as:
            inner += ["--run-as", self.run_as]
            if self.private_tmp:
                inner += ["--private-tmp"]
        if self.isolation:
            inner = [self._python(), "-B", f"{self.tree_remote}/tools/prefix.py",
                     "check-isolation", "--prefix", self.remote,
                     "--marker", f"{self.remote}/tmp/markers/{self.run_id}-{jid}", "--"] + inner
        return self._envi() + inner

    def _stage_artifacts(self, job, machine):
        """[(needed job, artifact names)] whose artifacts this launch carries.

        Only what a needed job uploaded on another machine travels; on the
        same machine the files are already where run-job's download reads.
        """
        carried = []
        xfer = self.stage / "xfer" / self.run_id
        for need in job.get("needs") or []:
            with self.cond:
                got = self.artifact_tars.get(need)
            if got is None or got[0] == machine.label:
                continue
            xfer.mkdir(parents=True, exist_ok=True)
            (xfer / f"{need}.tar.gz").write_bytes(got[1])
            carried.append((need, self.uploads.get(need) or []))
        if carried:
            self.log(f"{job['id']}: carrying the artifacts of "
                     f"{', '.join(n for n, _ in carried)} to machine {machine.label}")
        return carried

    def _unpack(self, carried):
        """Wrapper text that puts carried artifacts into this run's store.

        Runs as root before run-job. The run directory does not exist yet on a
        machine where this is the run's first job, and one root made would
        lock the job's uid out of writing its fragment, so whatever is made
        here is handed to that uid (its own segment, which the stub test
        replaces, as it cannot change owners).
        """
        if not carried:
            return ""
        run = f"{self.remote}/out/{self.tree}/{self.run_id}"
        xfer = f"{self.tree_remote}/xfer/{self.run_id}"
        text = f"mkdir -p {run}/artifacts || exit 1; "
        for need, _ in carried:
            text += f"tar -xzf {xfer}/{need}.tar.gz -C {run}/artifacts || exit 1; "
        if self.run_as:
            names = " ".join(f"{run}/artifacts/{shlex.quote(n)}"
                             for _, ns in carried for n in ns)
            text += (f"chown {self.run_as} {self.remote}/out/{self.tree} {run} "
                     f"{run}/artifacts; chown -R {self.run_as} {names}; ")
        return text

    def _wrapper(self, job, machine, carried=()):
        """The detached job: claim it, run it, record exit code and times.

        The control directory sits beside the run's own out directory, not in
        it: run-job creates out/<sha>/<run> as the uid it drops to, and a
        directory root made there first would lock that uid out. <job>.exit
        is written last and by rename, so a poll that sees it sees the
        fragment run-job wrote before it exited. The claim holds the
        machine's letter, so a claim read back says where it was made.
        """
        c, jid = self.ctl, job["id"]
        return ["bash", "-c",
                f"mkdir -p {c} || exit 1; "
                f"mkdir {c}/{jid}.claim 2>/dev/null || exit 0; "
                f"echo {machine.label} > {c}/{jid}.claim/machine; "
                f"{self._unpack(carried)}"
                f"s=$(date +%s); {shlex.join(self._inner(job))} "
                f"> {c}/{jid}.stdout 2> {c}/{jid}.stderr; x=$?; "
                f"echo \"$x $s $(date +%s)\" > {c}/{jid}.exit.tmp && "
                f"mv {c}/{jid}.exit.tmp {c}/{jid}.exit"]

    def _poll_script(self, ids):
        c, f = self.ctl, f"{self.remote}/out/{self.tree}/{self.run_id}/fragments"
        parts = [LOAD_PROBE]
        for jid in ids:
            parts.append(
                f"if [ -f {c}/{jid}.exit ]; then "
                f"echo \"GATES-POLL done {jid} $(cat {c}/{jid}.exit)\"; "
                f"for k in stdout stderr; do [ -f {c}/{jid}.$k ] && "
                f"echo \"GATES-POLL $k {jid} $(base64 -w0 < {c}/{jid}.$k)\"; done; "
                f"[ -f {f}/{jid}.json ] && "
                f"echo \"GATES-POLL fragment {jid} $(base64 -w0 < {f}/{jid}.json)\"; "
                + self._artifact_probe(jid) +
                f"elif [ -d {c}/{jid}.claim ]; then echo \"GATES-POLL running {jid}\"; "
                f"else echo \"GATES-POLL absent {jid}\"; fi")
        return "; ".join(parts) + "; echo GATES-POLL-END"

    def _artifact_probe(self, jid):
        """The poll's line carrying a done job's uploaded artifacts, if it has any."""
        names = self.uploads.get(jid) or []
        if not names:
            return ""
        a = f"{self.remote}/out/{self.tree}/{self.run_id}/artifacts"
        quoted = " ".join(shlex.quote(n) for n in names)
        return (f"h=''; for n in {quoted}; do [ -d {a}/$n ] && h=\"$h $n\"; done; "
                f"[ -n \"$h\" ] && echo \"GATES-POLL artifacts {jid} "
                f"$(tar -czf - -C {a} $h | base64 -w0)\"; ")

    def _poll_once(self, machine, ids):
        """{job: state} for these jobs on one machine, or None when the poll did not get through."""
        code, out, _ = self._crun(self.stage, machine,
                                  self._envi() + ["bash", "-c", self._poll_script(ids)],
                                  "poll", sync=False, timeout=POLL_TIMEOUT)
        lines = [line.split(" ", 3) for line in out.splitlines()
                 if line.startswith("GATES-POLL")]
        if code != 0 or ["GATES-POLL-END"] not in lines:
            with self.cond:
                self.polls["failed"] += 1
            return None
        with self.cond:
            self.polls["ok"] += 1
            if machine.note_load(out):
                # local only, for the person who ran it: how loaded each
                # machine was through the run
                with open(self.out / "crun" / "loads.txt", "a") as handle:
                    handle.write(f"{time.strftime('%H:%M:%S')}\t{machine.label}\t"
                                 f"{machine.cores}\t{machine.load}\n")
        states = {}
        for fields in lines:
            if fields[0] != "GATES-POLL" or len(fields) < 3:
                continue
            kind, jid = fields[1], fields[2]
            rest = fields[3] if len(fields) > 3 else ""
            if kind in ("absent", "running"):
                states[jid] = {"state": kind}
            elif kind == "done":
                exit_code, t0, t1 = (rest.split() + ["", "", ""])[:3]
                states[jid] = {"state": "done", "exit": int(exit_code),
                               "remote_seconds": int(t1) - int(t0)}
            elif kind in ("stdout", "stderr", "fragment") and jid in states:
                states[jid][kind] = base64.b64decode(rest).decode("utf-8", "replace")
            elif kind == "artifacts" and jid in states:
                states[jid]["artifacts"] = base64.b64decode(rest)
        for state in states.values():
            state["machine"] = machine.label
        return states

    def _poll_loop(self):
        while True:
            with self.cond:
                if self.stopping:
                    return
                groups = {}
                for jid in sorted(self.watched):
                    machine = self.assigned.get(jid)
                    if machine is not None:
                        groups.setdefault(machine.label, (machine, []))[1].append(jid)
            if groups:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(groups)) as pool:
                    answers = list(pool.map(lambda g: (g[0], g[1], self._poll_once(*g)),
                                            groups.values()))
                with self.cond:
                    for machine, ids, states in answers:
                        if states is None:
                            self._failed(machine, "poll")
                            if not machine.up:
                                for jid in ids:
                                    self.states[jid] = (machine.label, {"state": "lost"})
                            continue
                        machine.failures = 0
                        for jid, state in states.items():
                            self.states[jid] = (machine.label, state)
                    self.round += 1
                    self.cond.notify_all()
            with self.cond:
                self.cond.wait_for(lambda: self.stopping, timeout=self.poll_interval)

    def _next_round(self, jid, seen):
        """Block until a poll round after `seen`; (round, this job's state or None).

        A state from a machine the job has since left is stale and dropped.
        """
        with self.cond:
            self.cond.wait_for(lambda: self.round > seen or self.stopping)
            got = self.states.pop(jid, None)
            machine = self.assigned.get(jid)
            if got is None or machine is None or got[0] != machine.label:
                return self.round, None
            return self.round, got[1]

    def _launch(self, job, avoid=()):
        """(crun job id or None, whether crun said it started); records the machine."""
        jid = job["id"]
        machine = self._pick(avoid)
        if machine is None:
            raise RuntimeError("no machine is left to launch on")
        with self.cond:
            self.assigned[jid] = machine
            self.states.pop(jid, None)
        carried = self._stage_artifacts(job, machine)
        code, out, err = self._crun(self.stage, machine, self._wrapper(job, machine, carried),
                                    f"launch-{jid}", detach=True, timeout=POLL_TIMEOUT)
        match = re.search(r"\bcrun-[a-z0-9]{8}\b", out + err)
        ok = code == 0 and match is not None
        with self.cond:
            if ok:
                machine.failures = 0
            else:
                self._failed(machine, "launch")
            with open(self.dispatch_log, "a") as handle:
                handle.write(f"{jid}\t{match.group(0) if match else '-'}\texit {code}\t"
                             f"machine {machine.label}\n")
        return (match.group(0) if match else None), ok

    def run_job(self, job, artifacts):
        jid = job["id"]
        t0 = time.monotonic()
        deadline = t0 + job["timeout_minutes"] * 60 * self.wait_scale
        with self.cond:
            if self.poller is None:
                self.poller = threading.Thread(target=self._poll_loop, daemon=True)
                self.poller.start()
            seen = self.round
        state = self.initial.pop(jid, None)
        launches, crun_job, absent = 0, None, 0
        if state and state["state"] == "running":
            self.log(f"{jid}: still running from the earlier controller on machine "
                     f"{self.assigned[jid].label}; waiting for it")
            state = None
        elif state is None or state["state"] == "absent":
            crun_job, started = self._launch(job)
            launches = 1
            if not started:
                self.log(f"{jid}: crun did not confirm the launch; the next poll decides")
            state = None
        with self.cond:
            self.watched.add(jid)
        try:
            while state is None or state["state"] != "done":
                if time.monotonic() > deadline:
                    if crun_job:  # best effort; the verdict does not wait on it
                        subprocess.run(list(self.crun) + ["kill", crun_job],
                                       capture_output=True, stdin=subprocess.DEVNULL)
                    raise RuntimeError(f"no result within {self.wait_scale:g} x its "
                                       f"{job['timeout_minutes']} minutes; the job is red")
                seen, state = self._next_round(jid, seen)
                if state is None:
                    continue
                if state["state"] == "lost":
                    # Its machine was dropped: start over elsewhere. Each
                    # machine can be dropped once, so this is bounded.
                    left = self.assigned[jid].label
                    self.log(f"{jid}: machine {left} was dropped; launching again elsewhere")
                    crun_job, _ = self._launch(job, avoid=(left,))
                    launches += 1
                    absent = 0
                    state = None
                elif state["state"] == "absent":
                    absent += 1
                    # Not claimed two polls after a launch: the launch never
                    # reached the cluster. A late one would find the claim
                    # if it lands on the same machine, and on another one it
                    # runs to no purpose and is never read.
                    if absent >= 2:
                        if launches >= 3:
                            raise RuntimeError(f"launched {launches} times and never started "
                                               f"(see {self.dispatch_log})")
                        self.log(f"{jid}: not started {absent} polls after launch "
                                 f"{launches}; launching again")
                        crun_job, _ = self._launch(job, avoid=(self.assigned[jid].label,))
                        launches += 1
                        absent = 0
                elif state["state"] == "running":
                    absent = 0
        finally:
            with self.cond:
                self.watched.discard(jid)
        extra = time.monotonic() - t0 - state["remote_seconds"]
        self.log(f"{jid}: remote {state['remote_seconds']}s on machine "
                 f"{self.assigned[jid].label}, controller {extra:+.0f}s (launches {launches})")
        return self._collect(jid, state)

    def _collect(self, jid, state):
        if "artifacts" in state:
            with self.cond:
                self.artifact_tars[jid] = (state["machine"], state["artifacts"])
            self.log(f"{jid}: {len(state['artifacts'])} bytes of artifacts "
                     f"({', '.join(self.uploads.get(jid) or [])}) kept from machine "
                     f"{state['machine']}")
        out, err = state.get("stdout", ""), state.get("stderr", "")
        record = self.out / "crun" / f"job-{jid}.txt"
        record.write_text(f"# remote exit {state['exit']} after {state['remote_seconds']}s\n"
                          f"--- stdout\n{out}--- stderr\n{err}")
        for line in out.splitlines():
            if line.startswith(("OUTSIDE ", "check-isolation:")):
                self.log(f"{jid}: {line}")
        if "fragment" not in state:
            raise RuntimeError(f"remote exit {state['exit']}, no result fragment "
                               f"(see {record})")
        fragment = json.loads(state["fragment"])
        self.fragments[jid] = fragment
        for line in err.splitlines():
            if line.startswith((f"[{jid}] {jid}#", f"[{jid}] private /tmp", f"[{jid}] run-job")):
                self.log(line[len(f"[{jid}] "):])
        return fragment["result"]

    def finished(self):
        """{job: result} for the jobs an earlier controller of this run saw end.

        A job that ended without a fragment is returned as a failure, the
        same verdict run_job gives it, so a resume cannot turn it green.
        """
        results = {}
        for jid, state in list(self.initial.items()):
            if state["state"] != "done":
                continue
            del self.initial[jid]
            try:
                results[jid] = self._collect(jid, state)
            except (RuntimeError, ValueError, KeyError) as error:
                self.log(f"{jid}: finished in the earlier run without a usable result: {error}")
                results[jid] = {"steps": None, "ok": False}
        return results

    def toolchain(self):
        """Each field as every job reported it; a field jobs disagree on is None."""
        fields = {}
        for fragment in self.fragments.values():
            for key, value in fragment["toolchain"].items():
                if value is not None:
                    fields.setdefault(key, set()).add(value)
        result = {}
        for key in ("seed_jar_sha256", "java", "cc", "python", "node"):
            values = fields.get(key, set())
            if len(values) > 1:
                self.log(f"crun backend: jobs disagree on toolchain.{key}: {sorted(values)}")
            result[key] = next(iter(values)) if len(values) == 1 else None
        return result

    def cleanup(self):
        with self.cond:
            self.stopping = True
            self.cond.notify_all()
        if self.poller is not None:
            self.poller.join(timeout=5)
        per_machine = {}
        for machine in self.assigned.values():
            per_machine[machine.label] = per_machine.get(machine.label, 0) + 1
        self.log(f"crun backend: {self.polls['ok']} poll(s) answered, "
                 f"{self.polls['failed']} dropped; jobs last placed per machine: "
                 + ", ".join(f"{k} {v}" for k, v in sorted(per_machine.items())))


def upload_names(job):
    """The artifact names a planned job uploads, as written in gates.yml."""
    names = []
    for action in job["actions"]:
        if action["kind"] == "use" and action.get("replacement") == "artifact-store-local":
            name = (action.get("with") or {}).get("name", "")
            if "${{" in name or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                raise SystemExit(f"crun backend: {job['id']} uploads an artifact named "
                                 f"{name!r}; only a literal name can be carried between "
                                 "machines")
            names.append(name)
    return names


class MachineError(Exception):
    """One machine cannot take part; the run goes on without it."""


def tools_digest():
    """sha256 over TOOL_FILES, names and bytes: what a remote job executes."""
    digest = hashlib.sha256()
    for name in TOOL_FILES:
        data = (HERE / name).read_bytes()
        digest.update(f"{name} {len(data)}\n".encode())
        digest.update(data)
    return digest.hexdigest()


def _text(data):
    if data is None:
        return ""
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else data


def urllib_name(url):
    import urllib.parse
    return urllib.parse.unquote(url.rsplit("/", 1)[1])

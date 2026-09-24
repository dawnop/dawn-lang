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

How a run goes (all remote paths under --backend-opt remote-prefix=P):

  prepare   1. a staging directory (not a worktree) holding this directory's
               tools, a git bundle of the commit and every tag, one JSON per
               planned job, and a .crun.yaml whose remote_root is
               P/jobs/<sha>/tree-<tools>, unique per commit and per version
               of these tools (a digest of TOOL_FILES), so no two projects,
               and no two controllers with different tools, ever rsync
               --delete into each other
            2. `inputs.py verify` on the cluster; if the pack is missing or
               red, a second staging directory (hard links to the local
               prefix's inputs/) goes to P/inputs and `inputs.py install`
               extracts and re-verifies it there
  run_job   `crun run -n 0 --no-build -d -- bash -c <wrapper>`: one detached
            zero-card crun per job, at most --jobs at once. The wrapper claims
            the job (mkdir P/out/<sha>/<run>.ctl/<job>.claim, so a second
            launch of the same job in the same run is a no-op), runs
            `env -i ... prefix.py run-job` with its stdout and stderr in that
            directory, and writes <job>.exit last. crun pushes the staging
            directory on every call (an unchanged tree is a few seconds; crun
            serialises the pushes itself)
  poll      one thread, one short `crun run -n 0 --no-sync --no-build` every
            poll=SECONDS (default 45) for every job still out, which prints
            each job's state: absent, running (claimed), or done with its
            exit code, fragment, stdout and stderr
  results   run-job writes its result fragment to
            P/out/<sha>/<run>/fragments; logs and artifacts stay in
            P/out/<sha>/<run>/ on the cluster. Only the fragments come back,
            and the runner builds bundle.json from them as for any backend

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

Resuming. The run id is kept in <out>/crun/run-id, and with resume=1 (run.sh
--resume) the backend reads it back instead of making a new one, polls every
job once in prepare, and hands the runner every job that already finished
(finished()); a job still running is waited for, not launched again, and a
job with no claim is launched. A job that finished without a fragment (a
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
  poll=SECONDS        interval between polls (default 45)
  wait-scale=F        how long the controller waits for a job, as a multiple
                      of its timeout-minutes (default: timeout-scale + 1, so
                      the job's own timeout inside run-job fires first and is
                      reported as a step result); past it the job is red
  resume=1            reuse <out>/crun/run-id (set by run.sh --resume)
"""

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
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

# runner.py --resume asks for this: jobs run detached on the cluster and
# outlive the controller that launched them.
RESUMABLE = True

TOOL_FILES = ("prefix.py", "inputs.py", "backend_local.py", "gatesplan.py", "inputs.lock.json")


def create(ctx):
    return CrunBackend(ctx)


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
        self.poll_interval = float(opts.get("poll", "45"))
        self.wait_scale = float(opts.get("wait-scale",
                                         float(opts.get("timeout-scale", "2")) + 1))
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
        self.last_start = 0.0
        # Polling: the jobs still out, the latest state of each, and a round
        # counter the waiting threads block on.
        self.cond = threading.Condition()
        self.watched = set()
        self.states = {}
        self.round = 0
        self.stopping = False
        self.poller = None
        self.polls = {"ok": 0, "failed": 0}
        self.initial = {}
        self.dispatch_log = self.out / "crun" / "dispatch.txt"
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

    def _crun(self, stage, command, label, sync=True, detach=False, timeout=None):
        """One zero-card crun from a staging directory; (exit, stdout, stderr).

        With a timeout, a crun that hangs (an SSH session that stalls rather
        than drops) is killed and reported as exit 124.
        """
        with self.start_lock:
            wait = self.last_start + self.start_gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last_start = time.monotonic()
        argv = list(self.crun) + ["run", "-n", "0", "--no-build"]
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
        record = self.out / "crun" / f"{label}.txt"
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

    # ------------------------------------------------------------ prepare

    def prepare(self):
        plan = gatesplan.plan_at(str(self.repo), self.tree)
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
        bundle = stage / "repo.bundle"
        if not bundle.exists():
            self._make_bundle(bundle)
        self._write_crun_yaml(stage, self.tree_remote)
        self.log(f"crun backend: staged {stage} ({bundle.stat().st_size / 2**20:.1f} MiB bundle) "
                 f"in {time.monotonic() - t0:.0f}s; remote prefix {self.remote}, run {self.run_id}, "
                 f"jobs run as {self.run_as or 'root'}")

        t0 = time.monotonic()
        code, out, err = self._verify_remote(stage, sync=True)
        self.log(f"crun backend: first push and remote inputs verify: exit {code} in "
                 f"{time.monotonic() - t0:.0f}s")
        if code != 0:
            self._ship_inputs()
            code, out, err = self._verify_remote(stage, sync=False)
            if code != 0:
                raise SystemExit(f"crun backend: the input pack does not verify on the cluster "
                                 f"after shipping:\n{out}{err}")
        self.log("crun backend: the input pack verifies on the cluster")
        if self.resuming:
            ids = [job["id"] for job in plan["jobs"]]
            states = None
            for _ in range(3):
                states = self._poll_once(ids)
                if states is not None:
                    break
                time.sleep(self.poll_interval)
            if states is None:
                raise SystemExit("crun backend: cannot read the earlier run's state on the "
                                 "cluster (three polls failed)")
            self.initial = states
            counts = {}
            for state in states.values():
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
        subprocess.run(["git", "-C", str(tmp), "bundle", "create", "-q", str(bundle),
                        "refs/heads/gates-tree", "--tags"], check=True)
        shutil.rmtree(tmp)

    def _verify_remote(self, stage, sync):
        py = self._python()
        script = (f"if [ -x {py} ]; then exec {py} -B {self.tree_remote}/tools/inputs.py verify "
                  f"--prefix {self.remote}; else echo 'no prefix python yet'; exit 1; fi")
        return self._crun(stage, self._envi() + ["bash", "-c", script], "inputs-verify", sync=sync)

    def _ship_inputs(self):
        """Hard links to the local prefix's inputs/, pushed to P/inputs by crun."""
        local_inputs = self.local_prefix / "inputs"
        if subprocess.run([sys.executable, "-B", str(HERE / "inputs.py"), "verify", "--prefix",
                           str(self.local_prefix)], capture_output=True).returncode != 0:
            raise SystemExit("crun backend: the local input pack does not verify; "
                             "run inputs.py build first")
        stage = self.stage_root / f"inputs-{self.run_id}"
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
        self.log(f"crun backend: shipping the input pack ({size / 2**20:.0f} MiB) to "
                 f"{self.remote}/inputs")
        code, out, err = self._crun(stage, self._envi() + ["bash", "-c", script], "inputs-ship")
        shutil.rmtree(stage, ignore_errors=True)  # hard links, one per run
        self.log(f"crun backend: input pack shipped and installed: exit {code} in "
                 f"{time.monotonic() - t0:.0f}s")
        if code != 0:
            raise SystemExit(f"crun backend: shipping the input pack failed:\n{out[-3000:]}"
                             f"{err[-3000:]}")

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

    def _wrapper(self, job):
        """The detached job: claim it, run it, record exit code and times.

        The control directory sits beside the run's own out directory, not in
        it: run-job creates out/<sha>/<run> as the uid it drops to, and a
        directory root made there first would lock that uid out. <job>.exit
        is written last and by rename, so a poll that sees it sees the
        fragment run-job wrote before it exited.
        """
        c, jid = self.ctl, job["id"]
        return ["bash", "-c",
                f"mkdir -p {c} || exit 1; "
                f"mkdir {c}/{jid}.claim 2>/dev/null || exit 0; "
                f"s=$(date +%s); {shlex.join(self._inner(job))} "
                f"> {c}/{jid}.stdout 2> {c}/{jid}.stderr; x=$?; "
                f"echo \"$x $s $(date +%s)\" > {c}/{jid}.exit.tmp && "
                f"mv {c}/{jid}.exit.tmp {c}/{jid}.exit"]

    def _poll_script(self, ids):
        c, f = self.ctl, f"{self.remote}/out/{self.tree}/{self.run_id}/fragments"
        parts = []
        for jid in ids:
            parts.append(
                f"if [ -f {c}/{jid}.exit ]; then "
                f"echo \"GATES-POLL done {jid} $(cat {c}/{jid}.exit)\"; "
                f"for k in stdout stderr; do [ -f {c}/{jid}.$k ] && "
                f"echo \"GATES-POLL $k {jid} $(base64 -w0 < {c}/{jid}.$k)\"; done; "
                f"[ -f {f}/{jid}.json ] && "
                f"echo \"GATES-POLL fragment {jid} $(base64 -w0 < {f}/{jid}.json)\"; "
                f"elif [ -d {c}/{jid}.claim ]; then echo \"GATES-POLL running {jid}\"; "
                f"else echo \"GATES-POLL absent {jid}\"; fi")
        return "; ".join(parts) + "; echo GATES-POLL-END"

    def _poll_once(self, ids):
        """{job: state} for these jobs, or None when the poll did not get through."""
        code, out, _ = self._crun(self.stage, self._envi() + ["bash", "-c",
                                                              self._poll_script(ids)],
                                  "poll", sync=False, timeout=POLL_TIMEOUT)
        lines = [line.split(" ", 3) for line in out.splitlines()
                 if line.startswith("GATES-POLL")]
        if code != 0 or ["GATES-POLL-END"] not in lines:
            self.polls["failed"] += 1
            return None
        self.polls["ok"] += 1
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
        return states

    def _poll_loop(self):
        while True:
            with self.cond:
                if self.stopping:
                    return
                ids = sorted(self.watched)
            if ids:
                states = self._poll_once(ids)
                with self.cond:
                    if states is not None:
                        self.states.update(states)
                    self.round += 1
                    self.cond.notify_all()
            with self.cond:
                self.cond.wait_for(lambda: self.stopping, timeout=self.poll_interval)

    def _next_round(self, jid, seen):
        """Block until a poll round after `seen`; (round, this job's state or None)."""
        with self.cond:
            self.cond.wait_for(lambda: self.round > seen or self.stopping)
            return self.round, self.states.pop(jid, None)

    def _launch(self, job):
        """(crun job id or None, whether crun said it started)."""
        jid = job["id"]
        code, out, err = self._crun(self.stage, self._wrapper(job), f"launch-{jid}",
                                    detach=True, timeout=POLL_TIMEOUT)
        match = re.search(r"\bcrun-[a-z0-9]{8}\b", out + err)
        ok = code == 0 and match is not None
        with open(self.dispatch_log, "a") as handle:
            handle.write(f"{jid}\t{match.group(0) if match else '-'}\texit {code}\n")
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
            self.log(f"{jid}: still running from the earlier controller; waiting for it")
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
                if state["state"] == "absent":
                    absent += 1
                    # Not claimed two polls after a launch: the launch never
                    # reached the cluster. A late one would find the claim.
                    if absent >= 2:
                        if launches >= 3:
                            raise RuntimeError(f"launched {launches} times and never started "
                                               f"(see {self.dispatch_log})")
                        self.log(f"{jid}: not started {absent} polls after launch "
                                 f"{launches}; launching again")
                        crun_job, _ = self._launch(job)
                        launches += 1
                        absent = 0
                elif state["state"] == "running":
                    absent = 0
        finally:
            with self.cond:
                self.watched.discard(jid)
        extra = time.monotonic() - t0 - state["remote_seconds"]
        self.log(f"{jid}: remote {state['remote_seconds']}s, controller {extra:+.0f}s "
                 f"(launches {launches})")
        return self._collect(jid, state)

    def _collect(self, jid, state):
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
        self.log(f"crun backend: {self.polls['ok']} poll(s) answered, "
                 f"{self.polls['failed']} dropped")


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

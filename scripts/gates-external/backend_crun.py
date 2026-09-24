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
  run_job   `crun run -n 0 --no-build -- env -i ... prefix.py run-job`: one
            zero-card crun per job, at most --jobs at once. crun pushes the
            staging directory each time (an unchanged tree is a few seconds;
            crun serialises the pushes itself)
  results   run-job prints its result fragment on one line and keeps it in
            P/out/<sha>/<run>/fragments; logs and artifacts stay in
            P/out/<sha>/<run>/ on the cluster. Only the fragments come back,
            and the runner builds bundle.json from them as for any backend

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
"""

import hashlib
import json
import os
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
        self.run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.fragments = {}
        self.start_lock = threading.Lock()
        self.last_start = 0.0
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

    def _crun(self, stage, command, label, sync=True):
        """One zero-card crun from a staging directory; (exit, stdout, stderr)."""
        with self.start_lock:
            wait = self.last_start + self.start_gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last_start = time.monotonic()
        argv = list(self.crun) + ["run", "-n", "0", "--no-build"]
        if not sync:
            argv.append("--no-sync")
        argv += ["--"] + command
        t0 = time.monotonic()
        done = subprocess.run(argv, cwd=stage, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
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

    def run_job(self, job, artifacts):
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
        for attempt in range(3):
            code, out, err = self._crun(self.stage, self._envi() + inner, f"job-{jid}")
            fragment = None
            for line in out.splitlines():
                if line.startswith("GATES-FRAGMENT "):
                    fragment = json.loads(line[len("GATES-FRAGMENT "):])
            if fragment is not None:
                break
            started = f"[{jid}]" in out or f"[{jid}]" in err
            if started:
                break
            # never reached the job (ssh or crun failed before it): try again
            self.log(f"{jid}: crun exit {code} before the job started; retrying")
            time.sleep(10)
        for line in out.splitlines():
            if line.startswith(("OUTSIDE ", "check-isolation:")):
                self.log(f"{jid}: {line}")
        if fragment is None:
            raise RuntimeError(f"crun exit {code}, no result fragment "
                               f"(see {self.out / 'crun' / f'job-{jid}.txt'})")
        self.fragments[jid] = fragment
        for line in err.splitlines():
            if line.startswith((f"[{jid}] {jid}#", f"[{jid}] private /tmp", f"[{jid}] run-job")):
                self.log(line[len(f"[{jid}] "):])
        return fragment["result"]

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
        pass


def tools_digest():
    """sha256 over TOOL_FILES, names and bytes: what a remote job executes."""
    digest = hashlib.sha256()
    for name in TOOL_FILES:
        data = (HERE / name).read_bytes()
        digest.update(f"{name} {len(data)}\n".encode())
        digest.update(data)
    return digest.hexdigest()


def urllib_name(url):
    import urllib.parse
    return urllib.parse.unquote(url.rsplit("/", 1)[1])

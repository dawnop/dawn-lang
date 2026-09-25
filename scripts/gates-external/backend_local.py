"""The local backend: run one gates.yml job on this machine.

THE BACKEND CONTRACT (every backend module implements exactly this):

    create(ctx) -> backend object, where ctx is a dict with
        repo      Path   the repository whose object store holds the tree
        tree      str    the full commit sha every job runs on
        out       Path   a local directory for logs and artifacts
        options   dict   `--backend-opt key=value` pairs, backend-defined
        log       callable(str) for progress lines

    backend.prepare()                 once, before any job
    backend.run_job(job, artifacts)   once per job, possibly concurrently
        job        one entry of gatesplan's plan: id, timeout_minutes, the
                   ordered actions ({"kind": "run", ...} or
                   {"kind": "use", "replacement": <id>, ...}, each with an
                   optional step `id` and `if`), and needs_results, the
                   runner's "success"/"failure" for each job in `needs`.
                   Expressions and step conditions are evaluated with
                   gatesplan.expand and gatesplan.step_condition_holds, so
                   every backend reads them the same way.
        artifacts  Path, the run's artifact store (upload writes a directory
                   per artifact name there, download reads from it)
        returns    {"steps": [one dict per run action, in order, with
                    executed, exit_code, stdout_sha256, stderr_sha256],
                    "ok": bool}
    backend.toolchain()               the bundle's toolchain fields
    backend.cleanup()                 once, after every job

In words: given a tree and inputs, run the command list in order, and hand
back an exit code and an output digest per command. A backend decides WHERE
things run and HOW each replacement id is realised; it does not decide WHAT
runs (gatesplan does) or what counts as complete (bundle.py does). A second
backend (crun) is a new backend_<name>.py beside this one, selected with
`--backend <name>`, and changes no existing file.

Why every job gets its own worktree: CI gives every job a fresh checkout, and
running several jobs in one tree collides on things gates.yml writes to fixed
places (`/tmp/gate-emit`). The only
things shared between jobs here are the toolchain caches: the seed cache is
copied in, as actions/cache would restore it (seedjar.sh re-verifies it on
every hit), and coursier's cache is the user's own, as on a runner.

Run steps run as GitHub runs a step with no `shell:`: `bash -e <file>`, in the
job's workspace, with GITHUB_ENV and GITHUB_PATH honoured between steps. Each
step is its own session so that whatever it leaves running is killed when it
ends, which is what the runner does at the end of a job and what a shared
machine needs sooner.

With `--backend-opt prefix=DIR` (run.sh --prefix DIR) the same backend runs
inside a prefix (prefix.py): the JDK, python, node and the seed come from the
prefix's input pack, a job's environment is prefix.job_env (nothing inherited
from the caller), its checkout is a `git clone --shared` under
prefix/jobs/<sha> rather than a worktree (a worktree writes into the source
repository's .git), and the lock files for literal /tmp paths live under
prefix/tmp/locks. Without the option nothing changes: the #171 acceptance ran
the host-environment path and still does.
"""

import fcntl
import fnmatch
import hashlib
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gatesplan  # noqa: E402
import prefix as prefix_mod  # noqa: E402

TMP_LITERAL = re.compile(r"/tmp/[A-Za-z0-9._-]+")
HOST_ENV_DROP = re.compile(r"^(GITHUB_|RUNNER_|DAWN_|ACTIONS_)")
HOST_ENV_DROP_EXACT = {"JAVA_HOME", "GRAALVM_HOME", "TMPDIR", "CI", "PLAY_TEST_PORT",
                       "PLAY_PORT", "MUTANT_COVERAGE_DIR", "DAWNC_BIN"}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def java_major(java):
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True,
                             timeout=60).stderr
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    match = re.search(r'version "(\d+)', out)
    return (int(match.group(1)) if match else None), out


def create(ctx):
    return LocalBackend(ctx)


class LocalBackend:
    def __init__(self, ctx):
        self.repo = Path(ctx["repo"])
        self.tree = ctx["tree"]
        self.out = Path(ctx["out"])
        self.log = ctx["log"]
        opts = ctx["options"]
        self.prefix = Path(opts["prefix"]).resolve() if opts.get("prefix") else None
        # Where checkouts clone from in prefix mode: the repository itself here,
        # a bare repository made from a shipped bundle on a cluster.
        self.git_source = Path(opts.get("git-source") or self.repo)
        default_workdir = (self.prefix / "jobs" / self.tree if self.prefix
                           else self.repo.parent / "gates-external-jobs")
        self.workdir = Path(opts.get("workdir") or default_workdir)
        self.keep_going = opts.get("keep-going", "0") == "1"
        self.keep_worktrees = opts.get("keep-worktrees", "0") == "1"
        self.timeout_scale = float(opts.get("timeout-scale", "2"))
        self.seed_cache = opts.get("seed-cache")
        self.jdk = opts.get("jdk")
        self.run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.seed_hashes = set()
        self.lock = threading.Lock()
        self.base_env = None

    # ------------------------------------------------------------- lifecycle

    def prepare(self):
        if self.prefix:
            return self._prepare_prefix()
        self.workdir.mkdir(parents=True, exist_ok=True)
        if self.seed_cache is None:
            common = subprocess.run(
                ["git", "-C", str(self.repo), "rev-parse", "--path-format=absolute",
                 "--git-common-dir"], check=True, capture_output=True, text=True).stdout.strip()
            self.seed_cache = str(Path(common).parent / ".dawn" / "seeds")
        self.jdk = self._find_jdk()
        env = {k: v for k, v in os.environ.items()
               if not HOST_ENV_DROP.match(k) and k not in HOST_ENV_DROP_EXACT}
        env["CI"] = "true"
        # PLAY_TEST_PORT stays in the drop list and is not set: since #173
        # playground/test/contract.sh asks the kernel for a free port itself,
        # and a developer's pinned value must not reach it.
        self.base_env = env
        self.log(f"local backend: run {self.run_id}, workdir {self.workdir}, "
                 f"seed cache {self.seed_cache}, JDK {self.jdk}")

    def _prepare_prefix(self):
        prefix = self.prefix
        prefix_mod.ensure_layout(prefix)
        self.workdir.mkdir(parents=True, exist_ok=True)
        missing = [item["dir"] for item in prefix_mod.load_lock()["downloads"]
                   if not (prefix / "toolchain" / item["dir"]).is_dir()]
        if missing:
            raise SystemExit(f"local backend: the prefix {prefix} lacks toolchain/"
                             f"{', toolchain/'.join(missing)}; run inputs.py build first")
        self.jdk = str(prefix_mod.java_home(prefix))
        self.seed_cache = None  # the prefix's inputs/seeds and inputs/std-seeds
        prefix_mod.restore_coursier(prefix)
        prefix_mod.restore_npm(prefix)
        self.base_env = prefix_mod.job_env(prefix)
        self.log(f"local backend (prefix {prefix}): run {self.run_id}, JDK {self.jdk}")

    def _find_jdk(self):
        candidates = [self.jdk] if self.jdk else []
        home = Path.home() / "tools"
        candidates += sorted(str(p) for p in home.glob("graalvm-*") if (p / "bin/java").exists())
        candidates += sorted(str(p / "Contents/Home") for p in home.glob("graalvm-*")
                             if (p / "Contents/Home/bin/java").exists())
        for candidate in candidates:
            major, _ = java_major(str(Path(candidate) / "bin/java"))
            if major == 21:
                return candidate
        raise SystemExit("local backend: no JDK 21 found (pass --backend-opt jdk=<JAVA_HOME>)")

    def cleanup(self):
        if self.prefix:
            return
        subprocess.run(["git", "-C", str(self.repo), "worktree", "prune"],
                       capture_output=True)

    def toolchain(self):
        env = dict(self.base_env)
        if not self.prefix:
            env["PATH"] = f"{self.jdk}/bin:{env.get('PATH', '')}"

        def first_line(args, stream="stdout"):
            try:
                done = subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                return None
            text = (done.stdout if stream == "stdout" else done.stderr).strip()
            return text.splitlines()[0].strip() if text else None

        # In a prefix, bin/java is inputs.py's shim, which turns off the
        # /tmp/hsperfdata_<user> HotSpot would otherwise write for this probe.
        _, java_out = java_major(f"{self.jdk}/bin/java")
        build = re.search(r"Runtime Environment.*\(build ([^)]+)\)", java_out)
        python = first_line(["python3", "--version"])
        seeds = sorted(self.seed_hashes)
        return {
            "seed_jar_sha256": seeds[0] if len(seeds) == 1 else None,
            "java": build.group(1) if build else None,
            "cc": first_line(["cc", "--version"]),
            "python": python.split()[-1] if python else None,
            "node": first_line(["node", "--version"]),
        }

    # ------------------------------------------------------------------ jobs

    def run_job(self, job, artifacts):
        jid = job["id"]
        base = self.workdir / f"{self.run_id}-{jid}"
        ws = base / "ws"
        tmp = base / "tmp"
        logs = self.out / "logs" / jid
        for d in (ws, tmp / "runner", tmp / "tmp", logs):
            d.mkdir(parents=True, exist_ok=True)
        env = dict(self.base_env)
        env.update(GITHUB_WORKSPACE=str(ws), RUNNER_TEMP=str(tmp / "runner"),
                   TMPDIR=str(tmp / "tmp"))
        state = {"env": env, "ws": ws, "tmp": tmp, "logs": logs, "checked_out": False,
                 "deadline": time.monotonic() + job["timeout_minutes"] * 60 * self.timeout_scale,
                 "artifacts": Path(artifacts), "job": jid, "outputs": {},
                 "needs_results": dict(job.get("needs_results") or {})}
        steps, failed, index = [], False, 0
        try:
            for number, action in enumerate(job["actions"], 1):
                label = f"{jid}#{number}"
                if not gatesplan.step_condition_holds(action.get("if"), state["outputs"]):
                    # A false step condition is a skip, and a skipped run step
                    # is recorded as not executed: complete will say so.
                    self.log(f"{label} skipped: its condition is false")
                    if action["kind"] == "run":
                        steps.append({"executed": False, "exit_code": None,
                                      "stdout_sha256": None, "stderr_sha256": None})
                    continue
                if action["kind"] == "run":
                    if failed and not self.keep_going:
                        steps.append({"executed": False, "exit_code": None,
                                      "stdout_sha256": None, "stderr_sha256": None})
                        continue
                    result = self._run_step(state, action, number)
                    steps.append(result)
                    index += 1
                    self.log(f"{label} exit {result['exit_code']}: "
                             f"{(action['name'] or action['command'].strip().splitlines()[0])[:70]}")
                    if result["exit_code"] != 0:
                        failed = True
                    continue
                if failed and not self.keep_going:
                    continue
                ok, why = self._substitute(state, action, number)
                self.log(f"{label} {action['replacement']}: {'ok' if ok else 'FAILED ' + why}")
                if not ok:
                    failed = True
        finally:
            self._finish(state)
        return {"steps": steps, "ok": not failed}

    def _finish(self, state):
        ws = state["ws"]
        if state["checked_out"]:
            tag_file = ws / "scripts/seed-release.txt"
            if tag_file.exists():
                seed = ws / ".dawn/seeds" / tag_file.read_text().strip() / "seed.jar"
                if seed.exists():
                    with self.lock:
                        self.seed_hashes.add(sha256_file(seed))
        if self.keep_worktrees:
            return
        if state["checked_out"] and not self.prefix:
            subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force",
                            str(ws)], capture_output=True)
        shutil.rmtree(ws.parent, ignore_errors=True)

    # ------------------------------------------------------------- run steps

    def _expand(self, state, value):
        return gatesplan.expand(value, state["env"]["RUNNER_TEMP"], state["needs_results"],
                                state["outputs"])

    def _run_process(self, state, argv, env, stem, lock_paths=()):
        """Run one process in its own session; (exit code, out sha, err sha)."""
        out_path = state["logs"] / f"{stem}.out"
        err_path = state["logs"] / f"{stem}.err"
        held = []
        try:
            # Literal /tmp paths in a step are shared by every checkout on the
            # machine. A lock per path serialises two runs of this script on
            # it; it cannot protect against anything else using that path.
            for literal in sorted(set(lock_paths)):
                name = literal.strip("/").replace("/", "-")
                lock_dir = self.prefix / "tmp" / "locks" if self.prefix else Path("/tmp")
                handle = open(lock_dir / f"gates-external-{name}.lock", "w")
                fcntl.flock(handle, fcntl.LOCK_EX)
                held.append(handle)
            remaining = state["deadline"] - time.monotonic()
            if remaining <= 0:
                out_path.write_bytes(b"")
                err_path.write_bytes(b"gates-external: job timeout reached before this step\n")
                return 124, sha256_file(out_path), sha256_file(err_path)
            with open(out_path, "wb") as out, open(err_path, "wb") as err:
                proc = subprocess.Popen(argv, cwd=state["ws"], env=env, stdout=out,
                                        stderr=err, stdin=subprocess.DEVNULL,
                                        start_new_session=True)
                try:
                    code = proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    self._kill_group(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        pass
                    self._kill_group(proc.pid, signal.SIGKILL)
                    proc.wait()
                    code = 124
                    err.write(b"\ngates-external: job timeout reached, step killed\n")
                self._kill_group(proc.pid, signal.SIGKILL)
        finally:
            for handle in held:
                handle.close()
        return code, sha256_file(out_path), sha256_file(err_path)

    @staticmethod
    def _kill_group(pgid, sig):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _run_step(self, state, action, number):
        tmp = state["tmp"]
        script = tmp / f"step-{number}.sh"
        script.write_text(action["command"])
        files = {}
        for key in ("GITHUB_ENV", "GITHUB_PATH", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
            path = tmp / f"{key.lower()}-{number}"
            path.write_text("")
            files[key] = path
        env = dict(state["env"])
        env.update({k: self._expand(state, v) for k, v in action["env"].items()})
        env.update({k: str(v) for k, v in files.items()})
        code, out_sha, err_sha = self._run_process(
            state, ["bash", "-e", str(script)], env, f"step-{number}",
            TMP_LITERAL.findall(action["command"]))
        self._apply_env_files(state, files)
        if action.get("id"):
            state["outputs"][action["id"]] = self._read_kv(files["GITHUB_OUTPUT"])
        return {"executed": True, "exit_code": code,
                "stdout_sha256": out_sha, "stderr_sha256": err_sha}

    @staticmethod
    def _read_kv(path):
        """A GITHUB_ENV / GITHUB_OUTPUT file: `K=V` lines and `K<<DELIM` blocks."""
        found = {}
        lines = path.read_text().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if "<<" in line and ("=" not in line or line.index("<<") < line.index("=")):
                key, delim = line.split("<<", 1)
                body = []
                i += 1
                while i < len(lines) and lines[i] != delim:
                    body.append(lines[i])
                    i += 1
                found[key] = "\n".join(body)
            elif "=" in line:
                key, value = line.split("=", 1)
                found[key] = value
            i += 1
        return found

    def _apply_env_files(self, state, files):
        """GITHUB_ENV and GITHUB_PATH carry into later steps, as the runner does."""
        state["env"].update(self._read_kv(files["GITHUB_ENV"]))
        for entry in reversed(files["GITHUB_PATH"].read_text().splitlines()):
            if entry.strip():
                state["env"]["PATH"] = f"{entry.strip()}:{state['env']['PATH']}"

    # --------------------------------------------------------- substitutions

    def _substitute(self, state, action, number):
        handler = {
            "tree-worktree": self._checkout,
            "dawn-toolchain-local": self._toolchain,
            "noop": lambda s, a, n: (True, ""),
            "artifact-store-local": self._upload,
            "artifact-fetch-local": self._download,
            "node-host": self._node,
            "jdk21-host": self._jdk,
        }.get(action["replacement"])
        if handler is None:
            return False, f"the local backend does not implement {action['replacement']}"
        try:
            return handler(state, action, number)
        except Exception as error:  # a failed substitution fails the job, visibly
            return False, f"{type(error).__name__}: {error}"

    def _checkout(self, state, action, number):
        if state["checked_out"]:
            return False, "a second checkout in one job is not modelled"
        ws = state["ws"]
        ws.rmdir()
        if self.prefix:
            # Everything the clone writes is under ws; the source's objects are
            # borrowed through alternates, read-only. Tags come along, as with
            # a worktree; origin is the source path, not GitHub.
            env = state["env"]
            done = subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout",
                                   str(self.git_source), str(ws)],
                                  capture_output=True, text=True, env=env)
            if done.returncode == 0:
                more = subprocess.run(["git", "-C", str(ws), "checkout", "-q", "--detach",
                                       self.tree], capture_output=True, text=True, env=env)
                done = subprocess.CompletedProcess(more.args, more.returncode,
                                                   done.stdout + more.stdout,
                                                   done.stderr + more.stderr)
        else:
            done = subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "--detach",
                                   str(ws), self.tree], capture_output=True, text=True)
        (state["logs"] / f"step-{number}.checkout").write_text(done.stdout + done.stderr)
        if done.returncode != 0:
            ws.mkdir(exist_ok=True)
            return False, done.stderr.strip()
        state["checked_out"] = True
        return True, ""

    def _use_jdk(self, state):
        env = state["env"]
        env["JAVA_HOME"] = self.jdk
        env["GRAALVM_HOME"] = self.jdk
        env["PATH"] = f"{self.jdk}/bin:{env['PATH']}"

    def _jdk(self, state, action, number):
        self._use_jdk(state)
        return True, ""

    def _node(self, state, action, number):
        if shutil.which("node", path=state["env"]["PATH"]) is None:
            return False, "no node on PATH"
        return True, ""

    def _toolchain(self, state, action, number):
        self._use_jdk(state)
        ws = state["ws"]
        tag = (ws / "scripts/seed-release.txt").read_text().strip()
        if self.prefix:
            pairs = [(self.prefix / "inputs/seeds" / tag, tag),
                     (self.prefix / "inputs/std-seeds" / tag, f"std-{tag}")]
            # inside a prefix the network is not an input: a missing seed is
            # a stale pack, and fetching it would fail later and less clearly
            for src, _ in pairs:
                if not src.is_dir():
                    return False, f"the prefix has no {src.name} under {src.parent.name}; rebuild it with inputs.py build"
        else:
            pairs = [(Path(self.seed_cache) / name, name) for name in (tag, f"std-{tag}")]
        for src, name in pairs:
            dst = ws / ".dawn/seeds" / name
            if src.is_dir() and not dst.exists():
                shutil.copytree(src, dst, symlinks=True)
        if action["with"].get("build", "true") == "false":
            return True, ""
        code, _, _ = self._run_process(state, ["./bin/dawn", "--version"], dict(state["env"]),
                                       f"step-{number}.toolchain")
        return code == 0, f"./bin/dawn --version exited {code}"

    def _upload(self, state, action, number):
        name = action["with"]["name"]
        src = Path(self._expand(state, action["with"]["path"]))
        if not src.is_absolute():
            src = state["ws"] / src
        dst = state["artifacts"] / name
        empty = not src.exists() or (src.is_dir() and not any(src.rglob("*")))
        if empty:
            policy = action["with"].get("if-no-files-found", "warn")
            return (policy != "error"), f"no files at the upload path for {name}"
        if dst.exists():
            return False, f"artifact {name} was already uploaded in this run"
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.mkdir(parents=True)
            shutil.copy2(src, dst / src.name)
        return True, ""

    def _download(self, state, action, number):
        pattern = action["with"].get("pattern", "*")
        dest = state["ws"] / self._expand(state, action["with"].get("path", "."))
        found = sorted(p for p in state["artifacts"].iterdir()
                       if p.is_dir() and fnmatch.fnmatchcase(p.name, pattern)) \
            if state["artifacts"].exists() else []
        # download-artifact@v4 with a pattern and no merge-multiple puts each
        # artifact in a directory of its own name under `path`.
        for artifact in found:
            shutil.copytree(artifact, dest / artifact.name, dirs_exist_ok=True)
        (state["logs"] / f"step-{number}.download").write_text(
            "\n".join(p.name for p in found) + "\n")
        return True, ""

#!/usr/bin/env python3
"""The crun backend's resume and disconnect behaviour, against a stub crun.

Why a stub: the property under test is that a dropped SSH session or a dead
controller changes nothing in the bundle, and the only way to drop one on a
chosen call is to own the crun that makes it. So this file is also that crun
(`stub-crun`), which runs commands on this machine with a directory standing
in for the cluster prefix, and the prefix's python3 (`stub-python`), which
answers `prefix.py run-job` with a fixed fragment computed from the job file
instead of running the job. Everything between them is the real code:
runner.py plans the real gates.yml at a real commit, backend_crun.py builds
its real launch wrapper and poll script, bundle.py writes the real bundle.

Faults are injected per kind of call, counted from 1 in the order the stub
sees them: `launch#2:after` runs the second launch and then reports 255 as
if the connection dropped on the way back, `poll#3:before` drops the third
poll before it runs, `poll#4:kill` SIGKILLs the controller (the stub's
parent) during the fourth poll while the launched jobs keep running.

    crun_stub_selftest.py [--repo DIR] [--sha REV]
        every case below; exit 0 when each holds
    crun_stub_selftest.py stub-crun ... / stub-python ...   (internal)

Cases: a clean run is the reference bundle; dropped polls and dropped
launches (before and after the launch reached the cluster) give the same
bytes; a controller killed mid-run and then --resume'd gives the same bytes;
and the negative control: a fragment deleted on the cluster after its job
ended, then --resume, gives complete=false with that job failed.
"""

import argparse
import fcntl
import hashlib
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# ------------------------------------------------------------- stub crun

def _count(state, kind):
    """This call's number among calls of its kind (and overall), under a lock."""
    path = Path(state) / "counts.json"
    with open(Path(state) / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        counts = json.loads(path.read_text()) if path.exists() else {}
        counts[kind] = counts.get(kind, 0) + 1
        path.write_text(json.dumps(counts))
        return counts[kind]


def _fault(kind, number):
    for item in filter(None, os.environ.get("STUB_FAULTS", "").split(",")):
        where, _, mode = item.partition(":")
        name, _, n = where.partition("#")
        if name == kind and int(n) == number:
            return mode
    return None


def _push(state):
    """What crun does first on every run: mirror this directory to remote_root.

    Serialised, and each file replaced by rename, so a job reading its job
    file while another call pushes never sees half of it.
    """
    config = Path(".crun.yaml")
    if not config.exists():
        return
    remote = next(line.split(":", 1)[1].strip() for line in config.read_text().splitlines()
                  if line.startswith("remote_root:"))
    with open(Path(state) / "push.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in Path(".").rglob("*"):
            target = Path(remote) / path
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".push")
            shutil.copy2(path, tmp)
            os.replace(tmp, target)


def stub_crun(argv):
    if argv[:1] == ["kill"]:
        return 0
    if argv[:1] != ["run"] or "--" not in argv:
        print(f"stub crun: unsupported {argv}", file=sys.stderr)
        return 2
    split = argv.index("--")
    flags, command = argv[1:split], argv[split + 1:]
    detach = "-d" in flags
    script = command[-1] if command else ""
    kind = ("launch" if detach else "poll" if "GATES-POLL-END" in script
            else "other")
    number = _count(os.environ["STUB_STATE"], kind)
    mode = _fault(kind, number)
    if mode == "before":
        print("stub crun: connection closed (before)", file=sys.stderr)
        return 255
    if mode == "kill":
        os.kill(os.getppid(), signal.SIGKILL)
        return 255
    _push(os.environ["STUB_STATE"])
    if detach:
        jid = "crun-" + "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=8))
        subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if mode == "after":
            return 255
        print(f"[crun] stub pipeline job started: {jid}")
        return 0
    done = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if mode == "after":
        return 255
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return done.returncode


# ------------------------------------------------------------ stub python

def stub_python(argv):
    """`python3 -B <tools>/X.py ...` as the prefix's interpreter would run it."""
    args = [a for a in argv if a != "-B"]
    tool = Path(args[0]).name
    if tool == "inputs.py":
        return 0
    if tool != "prefix.py" or args[1] != "run-job":
        print(f"stub python: unsupported {args}", file=sys.stderr)
        return 2
    opts, rest = {}, args[2:]
    while rest:
        key = rest.pop(0)
        if key == "--private-tmp":
            continue
        opts[key] = rest.pop(0)
    job = json.loads(Path(opts["--job-file"]).read_text())
    # env -i keeps the environment out, so the job lengths are a file:
    # "SHORT LONG", LONG for the jobs whose id has an odd length.
    lengths = Path(opts["--prefix"]) / "stub-job-seconds"
    short, long = (lengths.read_text().split() if lengths.exists() else ("0.3", "0.3"))
    time.sleep(float(long if len(job["id"]) % 2 else short))
    steps = []
    for action in job["actions"]:
        if action["kind"] != "run":
            continue
        digest = hashlib.sha256(action["command"].encode()).hexdigest()
        steps.append({"executed": True, "exit_code": 0, "stdout_sha256": digest,
                      "stderr_sha256": hashlib.sha256(digest.encode()).hexdigest()})
    fragment = {"job": job["id"], "result": {"steps": steps, "ok": True},
                "toolchain": {"seed_jar_sha256": "0" * 64, "java": "stub 21",
                              "cc": "stub cc", "python": "stub 3.12", "node": "stub 20"}}
    out = Path(opts["--prefix"]) / "out" / opts["--sha"] / opts["--run-id"] / "fragments"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fragment, sort_keys=True)
    (out / f"{job['id']}.json").write_text(text + "\n")
    print(f"[{job['id']}] {job['id']}#stub ran {len(steps)} step(s)", file=sys.stderr)
    print(f"GATES-FRAGMENT {text}", flush=True)
    return 0


# ------------------------------------------------------------- the cases

class World:
    def __init__(self, root, repo, sha):
        import backend_crun
        import prefix as prefix_mod
        self.root, self.repo, self.sha = Path(root), repo, sha
        self.remote = self.root / "remote"
        self.local = self.root / "local"
        pydir = self.remote / "toolchain" / prefix_mod.download("python")["dir"] / "bin"
        pydir.mkdir(parents=True)
        python = pydir / "python3"
        python.write_text(f"#!/bin/sh\nexec {sys.executable} -B {Path(__file__).resolve()} "
                          f"stub-python \"$@\"\n")
        python.chmod(0o755)
        crun = self.root / "crun"
        crun.write_text(f"#!/bin/sh\nexec {sys.executable} -B {Path(__file__).resolve()} "
                        f"stub-crun \"$@\"\n")
        crun.chmod(0o755)
        self.crun = crun
        # The staged git bundle is only read by the real run-job; an empty
        # file keeps prepare from cloning the repository for nothing.
        stage = self.local / "stage" / "jobs" / f"{sha}-{backend_crun.tools_digest()[:12]}"
        stage.mkdir(parents=True)
        (stage / "repo.bundle").write_text("")

    def run(self, name, faults="", resume=None, expect_killed=False):
        state = self.root / f"state-{name}"
        state.mkdir(exist_ok=True)
        env = dict(os.environ, STUB_STATE=str(state), STUB_FAULTS=faults)
        if resume:
            argv = ["--resume", str(resume), "--jobs", "16"]
        else:
            argv = ["--sha", self.sha, "--backend", "crun", "--repo", self.repo,
                    "--prefix", str(self.local), "--out", str(self.root / f"out-{name}"),
                    "--jobs", "16",
                    "--backend-opt", f"remote-prefix={self.remote}",
                    "--backend-opt", f"crun={self.crun}",
                    "--backend-opt", "poll=0.3", "--backend-opt", "start-gap=0"]
        done = subprocess.run([sys.executable, "-B", str(HERE / "runner.py")] + argv,
                              capture_output=True, text=True, env=env)
        (self.root / f"log-{name}.txt").write_text(done.stdout + done.stderr)
        if expect_killed:
            if done.returncode != -signal.SIGKILL:
                raise AssertionError(f"{name}: controller exit {done.returncode}, wanted SIGKILL")
            return done
        return done

    def bundle(self, name):
        return (self.root / f"out-{name}" / "bundle.json").read_bytes()


def self_test(repo, sha):
    failures = []
    root = Path(tempfile.mkdtemp(prefix="crun-stub-"))
    try:
        world = World(root, repo, sha)
        base = world.run("clean")
        if base.returncode != 0:
            raise AssertionError(f"clean run exit {base.returncode}; see {root}/log-clean.txt")
        reference = world.bundle("clean")
        if not json.loads(reference)["complete"]:
            raise AssertionError("the clean run is not complete")

        faults = {
            "dropped polls": "poll#2:before,poll#3:after,poll#5:before",
            "launch dropped before it ran": "launch#1:before,launch#7:before",
            "launch dropped after it ran": "launch#2:after,launch#9:after",
        }
        for name, spec in faults.items():
            label = name.replace(" ", "-")
            done = world.run(label, spec)
            if done.returncode != 0 or world.bundle(label) != reference:
                failures.append(f"{name}: exit {done.returncode}, bundle "
                                f"{'differs' if (root / f'out-{label}' / 'bundle.json').exists() else 'missing'}")
            log = (root / f"log-{label}.txt").read_text()
            launches = log.count("(launches 2)")
            if "before it ran" in name and launches < 2:
                failures.append(f"{name}: expected two relaunched jobs, saw {launches}")
            if "after it ran" in name and launches:
                failures.append(f"{name}: a launch that reached the cluster was repeated")

        # Jobs of 0.2s and 6s and a kill at the third poll: when the resumed
        # controller looks, some jobs have ended, some are still running and
        # some were never launched, and it must handle each kind.
        (world.remote / "stub-job-seconds").write_text("0.2 6")
        world.run("killed", "poll#3:kill", expect_killed=True)
        run_id = (root / "out-killed" / "crun" / "run-id").read_text().strip()
        resumed = world.run("killed-resume", resume=root / "out-killed")
        (world.remote / "stub-job-seconds").unlink()
        log = (root / "log-killed-resume.txt").read_text()
        counts = {"collected": log.count("collected "),
                  "adopted": log.count("still running from the earlier controller"),
                  "launched": log.count("(launches 1)")}
        if resumed.returncode != 0 or world.bundle("killed") != reference:
            failures.append(f"resume after a killed controller: exit {resumed.returncode}, "
                            "bundle differs")
        if not counts["collected"] or not counts["adopted"] or not counts["launched"]:
            failures.append(f"resume after a killed controller did not meet every kind of "
                            f"job: {counts}")
        print(f"  killed controller, then --resume: {counts['collected']} collected, "
              f"{counts['adopted']} still running and waited for, {counts['launched']} "
              "launched by the resumed controller; bundle identical")

        # Negative control: a fragment gone from the cluster after its job
        # ended must not come back green.
        victim = "test"
        fragment = root / "remote" / "out" / sha / run_id / "fragments" / f"{victim}.json"
        fragment.unlink()
        again = world.run("deleted-fragment", resume=root / "out-killed")
        bundle = json.loads(world.bundle("killed"))
        red = [s for s in bundle["steps"] if s["job"] == victim and not s["executed"]]
        if again.returncode != 1 or bundle["complete"] or not red:
            failures.append(f"deleted fragment: exit {again.returncode}, complete "
                            f"{bundle['complete']}, {len(red)} unexecuted step(s) of {victim}")
        else:
            print(f"  negative control: {victim}'s fragment deleted, resume exit 1, "
                  f"complete=false")
    except AssertionError as error:
        failures.append(str(error))
    for line in failures:
        print(f"FAIL crun stub self-test: {line} (logs in {root})", file=sys.stderr)
    if failures:
        return 1
    shutil.rmtree(root, ignore_errors=True)
    print("OK: crun stub self-test, clean, 3 fault kinds, killed and resumed, deleted fragment")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "stub-crun":
        return stub_crun(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "stub-python":
        return stub_python(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=str(HERE.parents[1]))
    parser.add_argument("--sha", default="HEAD")
    args = parser.parse_args()
    sha = subprocess.run(["git", "-C", args.repo, "rev-parse", args.sha], check=True,
                         capture_output=True, text=True).stdout.strip()
    return self_test(args.repo, sha)


if __name__ == "__main__":
    sys.exit(main())

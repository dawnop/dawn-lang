#!/usr/bin/env python3
"""The crun backend's resume and disconnect behaviour, against a stub crun.

Why a stub: the property under test is that a dropped SSH session, a dead
controller or a machine that stops answering changes nothing in the bundle,
and the only way to drop one on a chosen call is to own the crun that makes
it. So this file is also that crun (`stub-crun`), which runs commands on this
machine with one directory per stub machine standing in for that machine's
copy of the cluster prefix (the primary's is the prefix itself, another's is
a sibling; a command for `-m <machine>` has the prefix rewritten to it, as if
it ran on that machine's own disk), and the prefix's python3 (`stub-python`), which
answers `prefix.py run-job` with a fixed fragment computed from the job file
instead of running the job. Everything between them is the real code:
runner.py plans the real gates.yml at a real commit, backend_crun.py builds
its real launch wrapper and poll script, bundle.py writes the real bundle.

Faults are injected per kind of call, counted from 1 in the order the stub
sees them: `launch#2:after` runs the second launch and then reports 255 as
if the connection dropped on the way back, `poll#3:before` drops the third
poll before it runs, `poll#4:kill` SIGKILLs the controller (the stub's
parent) during the fourth poll while the launched jobs keep running. A
machine fault is `down=<machine>@N`: every call for that machine after its
N-th fails as a dropped connection (N=0: it never answers, though `crun
status` lists it). `noreach=<machine>`: the job uid cannot use the prefix
there.

    crun_stub_selftest.py [--repo DIR] [--sha REV]
        every case below; exit 0 when each holds
    crun_stub_selftest.py stub-crun ... / stub-python ...   (internal)

Cases: a clean run is the reference bundle, and it spreads its jobs over
more than one machine; machines=primary (every job on one machine) gives the
same bytes; dropped polls and dropped launches (before and after the launch
reached the cluster) give the same bytes; a machine the job uid cannot use,
one that never answers, and one that stops answering mid-run, give the same
bytes; a controller killed
mid-run and then --resume'd gives the same bytes; and the negative control:
a fragment deleted on the cluster after its job ended, then --resume, gives
complete=false with that job failed.
"""

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import shlex
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


STUB_MACHINES = ("stub-a", "stub-b", "stub-c")  # stub-a is the primary


def _fault(kind, number):
    for item in filter(None, os.environ.get("STUB_FAULTS", "").split(",")):
        if item.startswith(("down=", "noreach=")):
            continue
        where, _, mode = item.partition(":")
        name, _, n = where.partition("#")
        if name == kind and int(n) == number:
            return mode
    return None


def _machine_root(host):
    """Where the stub machine `host` keeps the prefix (None: the primary)."""
    prefix = os.environ["STUB_REMOTE"]
    return prefix if host in (None, STUB_MACHINES[0]) else f"{prefix}-{host}"


def _on_machine(text, host):
    """`text` with the cluster prefix moved to `host`'s copy of it."""
    prefix = os.environ["STUB_REMOTE"]
    return re.sub(re.escape(prefix) + r"(?![\w.-])", lambda _: _machine_root(host), text)


def _machine_down(state, host):
    """Whether this call for `host` fails: after its N-th call, under down=."""
    for item in os.environ.get("STUB_FAULTS", "").split(","):
        if item.startswith("down="):
            name, _, after = item[len("down="):].partition("@")
            if name == host:
                return _count(state, f"machine-{host}") > int(after or 0)
    return False


def _push(state, host=None):
    """What crun does first on every run: mirror this directory to remote_root.

    Serialised, and each file replaced by rename, so a job reading its job
    file while another call pushes never sees half of it.
    """
    config = Path(".crun.yaml")
    if not config.exists():
        return
    remote = next(line.split(":", 1)[1].strip() for line in config.read_text().splitlines()
                  if line.startswith("remote_root:"))
    remote = _on_machine(remote, host)
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


def stub_status():
    """`crun status` as the backend reads it: a header per machine, GPU lines."""
    for host in STUB_MACHINES:
        print(f"{host}  (b200{', primary' if host == STUB_MACHINES[0] else ''})")
        print("  GPU 0: free")
    return 0


def stub_crun(argv):
    if argv[:1] == ["kill"]:
        return 0
    if argv[:1] == ["status"]:
        return stub_status()
    if argv[:1] != ["run"] or "--" not in argv:
        print(f"stub crun: unsupported {argv}", file=sys.stderr)
        return 2
    split = argv.index("--")
    flags, command = argv[1:split], argv[split + 1:]
    host = flags[flags.index("-m") + 1] if "-m" in flags else None
    if host is not None and host not in STUB_MACHINES:
        print(f"stub crun: no machine {host}", file=sys.stderr)
        return 1
    detach = "-d" in flags
    script = command[-1] if command else ""
    kind = ("launch" if detach else "poll" if "GATES-POLL-END" in script
            else "other")
    state = os.environ["STUB_STATE"]
    if host is not None and _machine_down(state, host):
        print(f"stub crun: connection to {host} closed", file=sys.stderr)
        return 255
    number = _count(state, kind)
    mode = _fault(kind, number)
    if mode == "before":
        print("stub crun: connection closed (before)", file=sys.stderr)
        return 255
    if mode == "kill":
        os.kill(os.getppid(), signal.SIGKILL)
        return 255
    # crun pushes to its primary on every call, then (without --no-sync)
    # rsyncs from there to the machine the command runs on
    _push(state)
    if host not in (None, STUB_MACHINES[0]) and "--no-sync" not in flags:
        _push(state, host)
    command = [_on_machine(part, host) for part in command]
    # crun echoes what it runs on the same stdout; so does the stub, so a
    # marker the backend looks for must not be found in the echo
    print(f"[stub crun] run: {shlex.join(command)}")
    # The stub runs as whoever runs the test and cannot change uid, so the
    # job-uid check answers what that machine's fault list says.
    reach = "false" if f"noreach={host}" in os.environ.get("STUB_FAULTS", "").split(",") else "true"
    command = [re.sub(r"setpriv .*? -c pass \|\|", f"{reach} ||", part) for part in command]
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
        # one copy of the prefix per stub machine, each with its python
        self.roots = [self.remote] + [Path(f"{self.remote}-{h}") for h in STUB_MACHINES[1:]]
        for root_dir in self.roots:
            pydir = root_dir / "toolchain" / prefix_mod.download("python")["dir"] / "bin"
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

    def job_seconds(self, text):
        """Every stub machine's job lengths ("SHORT LONG"), or None to reset."""
        for root_dir in self.roots:
            path = root_dir / "stub-job-seconds"
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text)

    def run(self, name, faults="", resume=None, expect_killed=False, opts=()):
        state = self.root / f"state-{name}"
        state.mkdir(exist_ok=True)
        env = dict(os.environ, STUB_STATE=str(state), STUB_FAULTS=faults,
                   STUB_REMOTE=str(self.remote))
        if resume:
            argv = ["--resume", str(resume), "--jobs", "16"]
        else:
            argv = ["--sha", self.sha, "--backend", "crun", "--repo", self.repo,
                    "--prefix", str(self.local), "--out", str(self.root / f"out-{name}"),
                    "--jobs", "16",
                    "--backend-opt", f"remote-prefix={self.remote}",
                    "--backend-opt", f"crun={self.crun}",
                    "--backend-opt", "poll=0.3", "--backend-opt", "start-gap=0"]
            for item in opts:
                argv += ["--backend-opt", item]
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
        if b"stub-" in reference:
            failures.append("the bundle names a machine")
        used = {line.split("\t")[3] for line in
                (root / "out-clean" / "crun" / "dispatch.txt").read_text().splitlines()}
        if len(used) < 2:
            failures.append(f"the clean run used one machine only: {sorted(used)}")
        print(f"  clean run: jobs placed on {len(used)} machines")

        done = world.run("primary-only", opts=("machines=primary",))
        if done.returncode != 0 or world.bundle("primary-only") != reference:
            failures.append(f"machines=primary: exit {done.returncode}, bundle differs")

        done = world.run("machine-out-of-reach", "noreach=stub-b")
        log = (root / "log-machine-out-of-reach.txt").read_text()
        if done.returncode != 0 or world.bundle("machine-out-of-reach") != reference:
            failures.append(f"a machine the job uid cannot use: exit {done.returncode}, "
                            "bundle differs")
        running = next((line for line in log.splitlines() if "running on" in line), "")
        if "machine B dropped from this run: uid" not in log or " B (" in running:
            failures.append("a machine the job uid cannot use was not dropped")

        done = world.run("machine-never-answers", "down=stub-c@0")
        log = (root / "log-machine-never-answers.txt").read_text()
        if done.returncode != 0 or world.bundle("machine-never-answers") != reference:
            failures.append(f"a machine that never answers: exit {done.returncode}, "
                            "bundle differs")
        if "machine C dropped" not in log:
            failures.append("a machine that never answers was not dropped")

        # stub-b answers prepare and a few launches, then nothing: its jobs
        # (some started, some not) are launched again elsewhere.
        world.job_seconds("0.3 2")
        done = world.run("machine-lost-mid-run", "down=stub-b@4", opts=("dead-after=2",))
        world.job_seconds(None)
        log = (root / "log-machine-lost-mid-run.txt").read_text()
        if done.returncode != 0 or world.bundle("machine-lost-mid-run") != reference:
            failures.append(f"a machine lost mid-run: exit {done.returncode}, bundle differs")
        relaunched = log.count("launching again elsewhere")
        if "machine B dropped" not in log or not relaunched:
            failures.append(f"a machine lost mid-run: dropped "
                            f"{'machine B dropped' in log}, {relaunched} job(s) moved")
        else:
            print(f"  machine lost mid-run: dropped, {relaunched} job(s) launched again "
                  "elsewhere; bundle identical")

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
        world.job_seconds("0.2 6")
        world.run("killed", "poll#3:kill", expect_killed=True)
        run_id = (root / "out-killed" / "crun" / "run-id").read_text().strip()
        resumed = world.run("killed-resume", resume=root / "out-killed")
        world.job_seconds(None)
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
        victim = "test-compiler"
        gone = 0
        for root_dir in world.roots:
            fragment = root_dir / "out" / sha / run_id / "fragments" / f"{victim}.json"
            if fragment.exists():
                fragment.unlink()
                gone += 1
        if not gone:
            failures.append(f"negative control: no fragment of {victim} to delete")
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
    print("OK: crun stub self-test, clean, one machine, 3 fault kinds, 3 machine faults, "
          "killed and resumed, deleted fragment")
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

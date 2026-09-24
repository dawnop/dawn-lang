#!/usr/bin/env python3
"""The prefix: one directory that holds everything a gate run reads or writes.

Why this exists. The first knife ran each job with the host's environment
minus a drop list, so the toolchain was whatever the machine happened to have:
the host's python3 (3.14 here, and 3.14 turns the playground contract red),
the host's node, and a cluster container whose JAVA_HOME is a Java 8 exported
for Hadoop. A drop list only removes what someone thought of. This module
turns it around: a job sees exactly the environment built here (the effect of
`env -i` plus a whitelist) and every path in it points into one prefix, whose
toolchain and inputs were fetched and hashed by inputs.py. Where the prefix
lives is always an argument; no location is written into the code, because
the same layout is ~/dawn-gates on a workstation and a directory on a cluster's
persistent disk.

Layout (created by `layout`):

    toolchain/<dir>/     one per download in inputs.lock.json, and one per
                         conda toolchain (the C compiler, gcc-13.3.0/)
    inputs/downloads/    the archives, as downloaded
    inputs/seeds/<tag>/  inputs/std-seeds/<tag>/  inputs/coursier/
    inputs/MANIFEST.json what inputs.py put there, with a sha256 per item
    jobs/<sha>/          per-job checkouts and temp directories
    repos/<sha>.git      a bare repository made from a shipped git bundle (crun)
    home/ tmp/ cache/    HOME (with the coursier cache where CI has it,
                         home/.cache/coursier/v1), lock files, npm's cache
    out/<sha>/           bundle.json, summary.json, logs/, artifacts/

The claim that a run stays inside the prefix is checked, not asserted:
`check-isolation` touches a marker, runs the command, and lists every file
outside the prefix whose mtime or ctime is newer than the marker.

Subcommands:
    layout --prefix P
    env --prefix P                          print the whitelist environment
    exec --prefix P [--break-env-i] -- CMD  run CMD in that environment
    check-isolation --prefix P --marker M [--root R] [--exclude X] -- CMD
    run-job ... [--run-as UID:GID]          the crun backend's remote half
    selftest --prefix P [--break-env-i]     the JAVA_HOME leak control
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK_FILE = HERE / "inputs.lock.json"
LAYOUT = ("toolchain", "inputs/downloads", "inputs/seeds", "inputs/std-seeds",
          "inputs/coursier", "jobs", "repos", "home", "tmp/locks", "cache", "out")
# Never walked by check-isolation: kernel and runtime filesystems whose
# entries change on their own.
PSEUDO = ("/proc", "/sys", "/dev", "/run")


def load_lock():
    return json.loads(LOCK_FILE.read_text())


def download(name):
    for item in load_lock()["downloads"]:
        if item["name"] == name:
            return item
    raise KeyError(name)


def archive_name(item):
    return urllib.parse.unquote(item["url"].rsplit("/", 1)[1])


def toolchain_dir(prefix, name):
    return Path(prefix) / "toolchain" / download(name)["dir"]


def java_home(prefix):
    return toolchain_dir(prefix, "graalvm")


def ensure_layout(prefix):
    for sub in LAYOUT:
        (Path(prefix) / sub).mkdir(parents=True, exist_ok=True)


def job_env(prefix, *, tmpdir=None, runner_temp=None, inherit_host=False):
    """The complete environment a job sees: nothing from the caller.

    PATH is the prefix's toolchain bins, then /usr/bin:/bin for git, bash,
    curl and coreutils, which the prefix does not carry. The C compiler is
    one of the toolchain bins: the steps find it only as `cc` on PATH (bare
    in wasm-target's driver step and the classpath contract, `${CC:-cc}` in
    the scripts, and the native driver's own default), so PATH is the one
    place to inject it. CC is not set, since CI does not set it, and neither
    is DAWN_WASM_CC, which wasm-target's own step writes. LANG is ubuntu-latest's
    value: without any locale the JVM's file-name encoding falls back to ASCII.
    DAWN_SEED is deliberately absent: CI does not set it, and set it would
    make seedjar.sh skip its checksum and print a warning CI never prints; the
    seed reaches a job as the cache restore does, copied into .dawn/seeds.

    inherit_host=True is the broken shell the leak self-test must catch: the
    host environment underneath, as if `env -i` had been dropped.
    """
    prefix = Path(prefix)
    bins = []
    lock = load_lock()
    for item in lock["downloads"] + lock.get("conda_toolchains", []):
        if item["bin"]:
            bins.append(str(prefix / "toolchain" / item["dir"] / item["bin"]))
    env = dict(os.environ) if inherit_host else {}
    base = {
        "PATH": ":".join(bins + ["/usr/bin", "/bin"]),
        "JAVA_HOME": str(java_home(prefix)),
        "GRAALVM_HOME": str(java_home(prefix)),
        "HOME": str(prefix / "home"),
        "TMPDIR": str(tmpdir or prefix / "tmp"),
        "RUNNER_TEMP": str(runner_temp or prefix / "tmp"),
        # Where they are on a runner, which sets neither: HOME/.cache and
        # coursier's default under it. Not a separate cache/ directory,
        # because gate scripts read ~/.cache/coursier/v1 directly
        # (configured-lsp-contract.py and source-parse-counts.py find the
        # ASM jar there, as the toolchain action's cache restores it).
        "XDG_CACHE_HOME": str(coursier_home(prefix).parents[1]),
        "COURSIER_CACHE": str(coursier_home(prefix)),
        "LANG": "C.UTF-8",
        "CI": "true",
        # wasm-target's wasi-sdk step copies this instead of downloading it
        # and checks the same pinned sha256 (the adjust:wasi-sdk-tarball row).
        "WASI_SDK_TARBALL": str(prefix / "inputs" / "downloads" / archive_name(download("wasi-sdk"))),
        # site/build.sh's `npm install` resolves from the input pack's cache
        # and never from the registry (the adjust:npm-offline-cache row).
        "npm_config_cache": str(prefix / "cache" / "npm"),
        "npm_config_offline": "true",
    }
    if inherit_host:
        # The broken variant keeps whatever the host had for these, which is
        # exactly what dropping `env -i` would do for a variable the host sets.
        for key, value in base.items():
            env.setdefault(key, value)
        return env
    env.update(base)
    return env


def locked(prefix, name):
    """An exclusive flock under prefix/tmp/locks, as a context manager."""
    class _Lock:
        def __enter__(self):
            path = Path(prefix) / "tmp" / "locks" / f"{name}.lock"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(path, "w")
            fcntl.flock(self.handle, fcntl.LOCK_EX)
            return self

        def __exit__(self, *exc):
            self.handle.close()
    return _Lock()


def coursier_home(prefix):
    return Path(prefix) / "home" / ".cache" / "coursier" / "v1"


def restore_coursier(prefix):
    """home/.cache/coursier/v1 from inputs/coursier, once: the actions/cache
    restore of ~/.cache/coursier.

    Jobs write to the cache (coursier keeps lock and last-check files); the
    inputs copy stays as inputs.py hashed it.
    """
    import shutil
    prefix = Path(prefix)
    cache = coursier_home(prefix)
    source = prefix / "inputs" / "coursier"
    with locked(prefix, "coursier-restore"):
        if not cache.exists() and source.is_dir():
            shutil.copytree(source, cache, symlinks=True)


def restore_npm(prefix):
    """cache/npm from inputs/npm-cache: what setup-node's `cache: npm` restores.

    npm writes into its cache even offline (_logs, index touches), so jobs
    get a copy and the input pack stays as inputs.py hashed it. The copy is
    replaced when the pack's cache is not the one it was made from.
    """
    import shutil
    prefix = Path(prefix)
    cache = prefix / "cache" / "npm"
    stamp = prefix / "cache" / "npm.source"
    manifest = prefix / "inputs" / "MANIFEST.json"
    if not manifest.exists():
        return
    rows = [row for row in json.loads(manifest.read_text())["items"] if row["kind"] == "npm-cache"]
    if not rows:
        return
    source = prefix / rows[0]["path"]
    want = rows[0]["tree_sha256"]
    with locked(prefix, "npm-restore"):
        if cache.exists() and stamp.exists() and stamp.read_text().strip() == want:
            return
        shutil.rmtree(cache, ignore_errors=True)
        shutil.copytree(source, cache, symlinks=True)
        stamp.write_text(want + "\n")


# ------------------------------------------------------------ isolation

def mount_root(path):
    path = Path(path).resolve()
    dev = path.stat().st_dev
    while path.parent != path and path.parent.stat().st_dev == dev:
        path = path.parent
    return path


def newer_than(marker, roots, excluded):
    """Every path under roots (same filesystem) changed after marker."""
    found = []
    for root in roots:
        prune = []
        for path in list(PSEUDO) + list(excluded):
            prune += ["-path", path, "-o"]
        argv = ["find", root, "-xdev", "("] + prune[:-1] + [")", "-prune", "-o",
                "(", "-newer", marker, "-o", "-cnewer", marker, ")", "-print"]
        done = subprocess.run(argv, capture_output=True, text=True)
        found += [line for line in done.stdout.splitlines()
                  if line and line not in excluded and line != marker]
    return sorted(set(found))


def check_isolation(args):
    prefix = str(Path(args.prefix).resolve())
    marker = str(Path(args.marker).resolve())
    if not marker.startswith(prefix + "/"):
        print(f"check-isolation: the marker should live in the prefix; {marker} is outside",
              file=sys.stderr)
        return 2
    Path(marker).parent.mkdir(parents=True, exist_ok=True)
    Path(marker).write_text(f"{time.time()}\n")
    time.sleep(0.05)
    roots = args.root or ["/"]
    extra = str(mount_root(prefix))
    if extra not in roots and not any(extra == r for r in roots):
        roots = roots + [extra]
    excluded = [prefix] + [str(Path(x)) for x in args.exclude]
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.readonly_root and command:
        # The stronger form, where bubblewrap exists: the command sees every
        # filesystem read-only except the prefix, so a write outside it fails
        # the command instead of waiting to be found. What find still lists
        # was then written by processes outside the sandbox.
        command = ["bwrap", "--ro-bind", "/", "/", "--bind", prefix, prefix,
                   "--dev", "/dev", "--proc", "/proc", "--"] + command
    code = subprocess.run(command).returncode if command else 0
    found = newer_than(marker, roots, excluded)
    print(f"check-isolation: command exit {code}; roots {' '.join(roots)}; "
          f"excluded {' '.join(excluded)}"
          f"{'; command ran with / read-only except the prefix' if args.readonly_root else ''}")
    for path in found:
        print(f"OUTSIDE {path}")
    print(f"check-isolation: {len(found)} path(s) outside the prefix changed "
          f"{'(isolated)' if not found else '(NOT isolated)'}")
    if found:
        return 1
    return 0 if code == 0 else 3


# ------------------------------------------------------------- commands

def cmd_exec(args):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    env = job_env(args.prefix, inherit_host=args.break_env_i)
    return subprocess.run(command, env=env, cwd=str(Path(args.prefix) / "home")).returncode


def cmd_selftest(args):
    """A host JAVA_HOME, PATH entry or C compiler must not reach a job's shell."""
    prefix = Path(args.prefix).resolve()
    ensure_layout(prefix)
    want = str(java_home(prefix))
    leak = "/leaked/host/jdk"
    probe = ('printf "%s\\n%s\\n%s\\n%s\\n" "$JAVA_HOME" "$PATH" '
             '"${HOST_ONLY_VARIABLE:-unset}" "$(command -v cc || echo none)"')
    saved = {k: os.environ.get(k) for k in ("JAVA_HOME", "HOST_ONLY_VARIABLE", "PATH")}
    os.environ["JAVA_HOME"] = leak
    os.environ["HOST_ONLY_VARIABLE"] = "leaked"
    os.environ["PATH"] = f"{leak}/bin:{os.environ.get('PATH', '')}"
    try:
        env = job_env(prefix, inherit_host=args.break_env_i)
        out = subprocess.run(["bash", "-c", probe], env=env, capture_output=True,
                             text=True).stdout.splitlines()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    checks = [
        ("JAVA_HOME is the prefix's", out[0] == want, out[0]),
        ("no host PATH entry", leak not in out[1], out[1]),
        ("no host-only variable", out[2] == "unset", out[2]),
    ]
    compilers = [str(prefix / "toolchain" / entry["dir"] / entry["bin"] / "cc")
                 for entry in load_lock().get("conda_toolchains", [])]
    if compilers:
        checks.append(("cc is the input pack's", out[3] in compilers, out[3]))
    ok = True
    for name, good, seen in checks:
        print(f"{'ok  ' if good else 'FAIL'} {name}: {seen}")
        ok &= good
    print(f"selftest: {'green' if ok else 'RED'}"
          f"{' (env -i deliberately broken)' if args.break_env_i else ''}")
    return 0 if ok else 1


# ------------------------------------------------------------ identity

def parse_identity(text):
    uid, _, gid = text.partition(":")
    uid, gid = int(uid), int(gid or uid)
    if uid == 0 or gid == 0:
        raise SystemExit("run-job: --run-as must name a non-root uid and gid")
    return uid, gid


def writable_paths(prefix, sha):
    """What a job may write: everything else in the prefix stays root's.

    toolchain/ and inputs/ are not in the list, so a job cannot change the
    toolchain it is measured with; jobs/<sha>/tree-<tools> is crun's mirror of the
    staging directory and is only read.
    """
    prefix = Path(prefix)
    flat = [prefix / "jobs", prefix / "jobs" / sha, prefix / "repos", prefix / "out",
            prefix / "out" / sha]
    deep = [prefix / "home", prefix / "tmp", prefix / "cache", prefix / "repos" / f"{sha}.git"]
    return flat, deep


def hand_over(prefix, sha, uid, gid):
    """As root: give the writable part of the prefix to uid:gid.

    Only entries that are not already theirs are changed, so a second job of
    the same run walks the trees and changes nothing. A previous run as root
    (the negative control) leaves root-owned files behind; they are handed
    over here rather than failing the job.
    """
    flat, deep = writable_paths(prefix, sha)
    for path in flat:
        path.mkdir(parents=True, exist_ok=True)
    changed = 0

    def own(path):
        nonlocal changed
        st = os.lstat(path)
        if st.st_uid != uid or st.st_gid != gid:
            os.lchown(path, uid, gid)
            changed += 1
    for path in flat:
        own(path)
    for root in deep:
        if not root.exists():
            continue
        own(root)
        for dirpath, dirnames, filenames in os.walk(root):
            for name in dirnames + filenames:
                own(os.path.join(dirpath, name))
    return changed


# The world-writable places a non-root job could still write outside the
# prefix, each replaced by a per-job directory inside it.
SHARED_TMP = ("/tmp", "/var/tmp", "/dev/shm")


def private_tmp_dirs(prefix, sha, run_id, job_id, uid, gid):
    base = Path(prefix) / "jobs" / sha / f"{run_id or 'run'}-{job_id}-shared-tmp"
    dirs = {}
    for target in SHARED_TMP:
        path = base / target.strip("/").replace("/", "-")
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, uid, gid)
        path.chmod(0o1777)
        dirs[target] = path
    os.chown(base, uid, gid)
    return dirs


def drop_to(uid, gid, argv, private_tmp):
    """exec argv as uid:gid with no supplementary groups and no way back up.

    setpriv rather than `unshare -U`: a user namespace that maps the job's
    uid onto real root makes every root-owned file outside the prefix the
    job's own, so it could write them; a real uid change leaves them root's.
    --no-new-privs stops a setuid binary from undoing the drop.

    A uid change does not close /tmp, /var/tmp and /dev/shm, which anyone
    may write. With private_tmp ({target: dir}) the job gets a private mount
    namespace in which each is a bind mount of a per-job directory in the
    prefix: what CI gives a job (a fresh VM's /tmp), and a JVM's
    java.io.tmpdir, which ignores TMPDIR, then lands in the prefix too.
    """
    drop = ["setpriv", f"--reuid={uid}", f"--regid={gid}", "--clear-groups", "--no-new-privs",
            "--"] + argv
    if not private_tmp:
        os.execvp(drop[0], drop)
    binds = " && ".join(f'mount --bind "{src}" {target}' for target, src in private_tmp.items())
    os.execvp("unshare", ["unshare", "--mount", "--propagation", "private", "--", "sh", "-c",
                          f'{binds} && exec "$@"', "sh"] + drop)


def shared_tmp_state():
    """What a job's /tmp looks like now: (mtime_ns, entries)."""
    try:
        st = os.stat("/tmp")
        return st.st_mtime_ns, sorted(os.listdir("/tmp"))
    except OSError:
        return None, []


FAILED_LOG_TAIL = 80


def report_failed_logs(logs, log):
    """Echo the tail of the failing step's output to the controller.

    The logs stay under the remote prefix, which the controller never reads
    back, so a red job on the crun backend used to say which step failed and
    nothing about why: finding out meant opening a shell on the cluster, which
    the backend's contract rules out. The failing step is the last one that
    ran (a job stops at its first failure unless keep-going is set, and then
    the tail of the last is still the most useful single answer), so its two
    streams are the newest files here. Printed to stderr, which the controller
    keeps in out/crun/job-<id>.txt and does not put into the bundle.
    """
    if not logs.is_dir():
        return
    newest = sorted((f for f in logs.iterdir() if f.suffix in (".out", ".err")),
                    key=lambda f: f.stat().st_mtime_ns)[-2:]
    for f in sorted(newest):
        every = f.read_text(errors="replace").splitlines()
        # A test runner's verdict lines are rarely in its last lines: `dawn test`
        # ends with a summary after hundreds of PASS lines. So the lines naming
        # a failure come first, wherever they are, and then the tail.
        failing = [line for line in every if "FAIL" in line][:FAILED_LOG_TAIL]
        if failing:
            log(f"failed step log {f.name}: {len(failing)} line(s) naming a failure:")
            for line in failing:
                log(f"  ! {line}")
        lines = every[-FAILED_LOG_TAIL:]
        log(f"failed step log {f.name} (last {len(lines)} lines):")
        for line in lines:
            log(f"  | {line}")


def cmd_run_job(args):
    """Run one planned job inside the prefix: the crun backend's remote half.

    The job comes as JSON written by the controller (so this side needs no
    PyYAML and never re-plans), the commit's objects as a git bundle. The
    result is one fragment, written under out/<sha>/fragments and printed on
    one line for the controller to parse; logs stay in out/<sha>/logs.

    With --run-as UID:GID and started as root (a cluster container gives
    nothing else), the writable part of the prefix is handed to UID:GID and
    this command re-executes itself as that identity, without --run-as.
    Two contracts refuse root outright (atomic-write, unreadable-lock),
    because root reads a chmod 000 file and writes an unwritable directory,
    and CI runs every job as an ordinary user.
    """
    sys.path.insert(0, str(HERE))
    import backend_local
    prefix = Path(args.prefix).resolve()
    ensure_layout(prefix)
    sha = args.sha
    if args.run_as:
        uid, gid = parse_identity(args.run_as)
        if os.getuid() != uid:
            if os.getuid() != 0:
                raise SystemExit(f"run-job: --run-as {uid}:{gid} needs root to start from; "
                                 f"running as uid {os.getuid()}")
            changed = hand_over(prefix, sha, uid, gid)
            job_id = Path(args.job_file).stem
            private = (private_tmp_dirs(prefix, sha, args.run_id, job_id, uid, gid)
                       if args.private_tmp else None)
            print(f"[{job_id}] run-job: handed {changed} prefix entr(ies) to {uid}:{gid}; "
                  f"dropping root{'; /tmp, /var/tmp, /dev/shm private' if private else ''}",
                  file=sys.stderr, flush=True)
            drop_to(uid, gid, [sys.executable] + sys.orig_argv[1:], private)
    elif os.getuid() == 0:
        # Root without --run-as (the negative control): what a run as another
        # uid left behind goes back to root, or git refuses the repository
        # as of dubious ownership before any step runs.
        hand_over(prefix, sha, 0, 0)
    repo = prefix / "repos" / f"{sha}.git"
    with locked(prefix, f"repo-{sha}"):
        if not repo.exists():
            env = job_env(prefix)
            tmp = repo.with_name(repo.name + ".tmp")
            subprocess.run(["rm", "-rf", str(tmp)], check=True)
            subprocess.run(["git", "clone", "-q", "--bare", args.git_bundle, str(tmp)],
                           check=True, env=env)
            got = subprocess.run(["git", "-C", str(tmp), "rev-parse", "gates-tree"],
                                 check=True, capture_output=True, text=True, env=env).stdout.strip()
            if got != sha:
                raise SystemExit(f"run-job: the bundle carries {got}, not {sha}")
            tmp.rename(repo)
    job = json.loads(Path(args.job_file).read_text())
    job["needs_results"] = dict(kv.split("=", 1) for kv in args.needs.split(",") if kv)
    # One directory per controller run: a second run of the same commit must
    # not find the first one's artifacts (upload refuses a duplicate name).
    out = prefix / "out" / sha / args.run_id if args.run_id else prefix / "out" / sha

    def log(message):
        print(f"[{job['id']}] {message}", file=sys.stderr, flush=True)

    options = {"prefix": str(prefix), "git-source": str(repo)}
    for item in args.opt:
        key, _, value = item.partition("=")
        options[key] = value
    backend = backend_local.create({"repo": repo, "tree": sha, "out": out,
                                    "options": options, "log": log})
    backend.prepare()
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    tmp_before = shared_tmp_state()
    try:
        result = backend.run_job(job, out / "artifacts")
    finally:
        backend.cleanup()
    if args.private_tmp:
        # The job's /tmp is a directory in the prefix here, so whether the
        # job itself used /tmp is visible, apart from other tenants' writes
        # to the real one, which check-isolation (outside) still sees.
        tmp_after = shared_tmp_state()
        log(f"private /tmp: {'modified' if tmp_after[0] != tmp_before[0] else 'untouched'} "
            f"during the job, {len(tmp_after[1])} entr(ies) left "
            f"{' '.join(tmp_after[1][:8])}")
    if not result.get("ok"):
        report_failed_logs(out / "logs" / job["id"], log)
    fragment = {"job": job["id"], "result": result, "toolchain": backend.toolchain()}
    fragments = out / "fragments"
    fragments.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fragment, sort_keys=True)
    (fragments / f"{job['id']}.json").write_text(text + "\n")
    print(f"GATES-FRAGMENT {text}", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("layout")
    p.add_argument("--prefix", required=True)
    p = sub.add_parser("env")
    p.add_argument("--prefix", required=True)
    p = sub.add_parser("exec")
    p.add_argument("--prefix", required=True)
    p.add_argument("--break-env-i", action="store_true")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("check-isolation")
    p.add_argument("--prefix", required=True)
    p.add_argument("--marker", required=True)
    p.add_argument("--root", action="append", default=[])
    p.add_argument("--exclude", action="append", default=[],
                   help="a path written by something other than the command; printed with the result")
    p.add_argument("--readonly-root", action="store_true",
                   help="run the command under bwrap with / read-only except the prefix")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("selftest")
    p.add_argument("--prefix", required=True)
    p.add_argument("--break-env-i", action="store_true")
    p = sub.add_parser("run-job")
    p.add_argument("--prefix", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--git-bundle", required=True)
    p.add_argument("--job-file", required=True)
    p.add_argument("--needs", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--opt", action="append", default=[])
    p.add_argument("--run-as", default="",
                   help="UID:GID to run the job as, dropped to from root with setpriv")
    p.add_argument("--private-tmp", action="store_true",
                   help="with --run-as: /tmp, /var/tmp and /dev/shm are per-job directories "
                        "in the prefix (a private mount namespace)")
    args = parser.parse_args()
    if args.cmd == "layout":
        ensure_layout(args.prefix)
        return 0
    if args.cmd == "env":
        for key, value in sorted(job_env(args.prefix).items()):
            print(f"{key}={value}")
        return 0
    return {"exec": cmd_exec, "check-isolation": check_isolation, "selftest": cmd_selftest,
            "run-job": cmd_run_job}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

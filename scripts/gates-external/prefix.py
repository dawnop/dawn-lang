#!/usr/bin/env python3
"""The prefix: one directory that holds everything a gate run reads or writes.

Why this exists. The first knife ran each job with the host's environment
minus a drop list, so the toolchain was whatever the machine happened to have:
the host's python3 (3.14 here, and 3.14 turns the playground contract red),
the host's node, and a remote container whose JAVA_HOME is a Java 8 exported
for Hadoop. A drop list only removes what someone thought of. This module
turns it around: a job sees exactly the environment built here (the effect of
`env -i` plus a whitelist) and every path in it points into one prefix, whose
toolchain and inputs were fetched and hashed by inputs.py. Where the prefix
lives is always an argument; no location is written into the code, because
the same layout is ~/dawn-gates on a workstation and a directory on a remote
runner's
persistent disk.

Layout (created by `layout`):

    toolchain/<dir>/     one per download in inputs.lock.json, and one per
                         conda toolchain (the C compiler, gcc-13.3.0/, and the
                         pinned clang CI's C jobs take as CC, clang-18.1.3/)
    inputs/downloads/    the archives, as downloaded
    inputs/seeds/<tag>/  inputs/std-seeds/<tag>/  inputs/coursier/
    inputs/MANIFEST.json what inputs.py put there, with a sha256 per item
    jobs/<sha>/          per-job checkouts and temp directories
    repos/<sha>.git      a bare repository made from a shipped git bundle (a plugin backend)
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

    DAWN_PINNED_CC names the pack's clang 18.1.3 (a conda toolchain with a
    `pinned_cc` path and no bin on PATH). On CI, scripts/pinned-cc.sh finds
    the runner image's clang-18 because GITHUB_ACTIONS is true and appends
    CC to GITHUB_ENV; this runner does not pretend to be GitHub, so it names
    the compiler instead, and the same script then checks its version and
    writes CC the same way. Bare `cc` stays gcc, as on the runner. clang is
    kept off PATH because its directory's bin/ also holds icu, xz and zstd
    tools that would shadow /usr/bin for every step.

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
    for item in lock.get("conda_toolchains", []):
        if item.get("pinned_cc"):
            base["DAWN_PINNED_CC"] = str(prefix / "toolchain" / item["dir"] / item["pinned_cc"])
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
    probe = ('printf "%s\\n%s\\n%s\\n%s\\n%s\\n" "$JAVA_HOME" "$PATH" '
             '"${HOST_ONLY_VARIABLE:-unset}" "$(command -v cc || echo none)" '
             '"${DAWN_PINNED_CC:-unset}"')
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
                 for entry in load_lock().get("conda_toolchains", []) if entry["bin"]]
    if compilers:
        checks.append(("cc is the input pack's", out[3] in compilers, out[3]))
    pinned = [str(prefix / "toolchain" / entry["dir"] / entry["pinned_cc"])
              for entry in load_lock().get("conda_toolchains", []) if entry.get("pinned_cc")]
    if pinned:
        checks.append(("DAWN_PINNED_CC is the input pack's clang", out[4] in pinned, out[4]))
    ok = True
    for name, good, seen in checks:
        print(f"{'ok  ' if good else 'FAIL'} {name}: {seen}")
        ok &= good
    print(f"selftest: {'green' if ok else 'RED'}"
          f"{' (env -i deliberately broken)' if args.break_env_i else ''}")
    return 0 if ok else 1


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
    args = parser.parse_args()
    if args.cmd == "layout":
        ensure_layout(args.prefix)
        return 0
    if args.cmd == "env":
        for key, value in sorted(job_env(args.prefix).items()):
            print(f"{key}={value}")
        return 0
    return {"exec": cmd_exec, "check-isolation": check_isolation,
            "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

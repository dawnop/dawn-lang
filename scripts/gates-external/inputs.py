#!/usr/bin/env python3
"""The offline input pack: every byte a gate run needs from the network.

Why this exists. A cluster container with no route to the internet cannot run
setup-graalvm, download node, fetch the seed or ask Maven Central for asm, and
a workstation that can should not be trusted to fetch the same bytes twice.
So the downloads happen once, on a machine with a network, into a prefix
(prefix.py describes its layout); each one is checked against a digest that
lives in the repository, inputs.lock.json, and never against a checksum served
next to the file. The prefix then travels as a directory, and `verify` re-hashes
everything wherever it lands.

What the lock pins and what it does not:
  - downloads (GraalVM, node, wasi-sdk, python): URL and sha256, in the lock;
  - the bootstrap seed jar and its std: checked against the repository's own
    scripts/seed-checksums.txt and seed-std-checksums.txt, the tables seedjar.sh
    reads. A copy in the lock would be a second table to advance at every
    release, and advance-seed.sh does not know about it;
  - the coursier cache: produced by running `./bin/dawn --version` once with
    the cache pointed into the prefix; its jars are checked against
    selfhost/dawn.lock, and the whole tree's digest goes into MANIFEST.json;
  - the npm cache (lock key npm_caches): filled by `npm ci` from a lockfile
    whose sha256 the lock pins. The cache's own bytes are not reproducible
    (npm's index carries times), so the lock pins the lockfile, whose
    integrity fields npm checks on every tarball it takes from the cache,
    and MANIFEST records the tree digest of the cache that was built;
  - the C compiler (lock key conda_toolchains): conda-forge packages, each
    pinned by URL and sha256, unpacked together into one toolchain directory
    the way `conda install` lays out an environment. A .conda package is a
    zip of zstd-compressed tars, and the prefix's python 3.12 has no zstd,
    so the unpacking runs in that interpreter with a pinned zstandard wheel
    (lock key wheels) on its path: the same code on every machine, and no
    host tool deciding what gets unpacked.

Why the compiler is in the pack at all: it was the one tool the steps took
from /usr/bin, so an external run's bundle said `cc` = gcc 11.4 on the
cluster and gcc 13.3 on a workstation for the same commit. What CI runs is
ubuntu-latest's `cc`, gcc 13.3.0, whose sanitizer, libgcc_s and libstdc++
runtimes Ubuntu 24.04 builds from gcc 14.2.0; the lock pins conda-forge
builds of exactly that pairing. The pairing is not cosmetic: gcc 13.3's own
libasan dies with AddressSanitizer:DEADLYSIGNAL on a kernel with 32 bits of
mmap randomisation (9 of 50 runs here), 14.2's does not (0 of 100), and
scripts/spike-native/run.sh fails closed without ASan. conda-forge rather
than LLVM's release tarball: those are clang, not what CI runs, and 1 to
2 GB, where these packages are 121 MiB.

Relocation. conda records, per package, the files that carry the build
prefix as a text placeholder (info/paths.json) and rewrites it to the
install location. So does this module; gcc's specs are one of those files,
and the `-rpath <toolchain>/lib` they add to every non-static link is how
an ASan binary finds the pack's libasan instead of the host's (or none, on
the cluster, which has only gcc 11's). Those files then name the prefix, so
their digest is taken with the location put back to the placeholder: the
same tree digest on every machine, as with the java shims.

One change is made to an unpacked toolchain, and it is part of the layout,
not of the download: each GraalVM launcher in bin/ (java, javac, jar, ...)
becomes a shim that execs the real one, renamed bin/<name>.real, with
-XX:-UsePerfData (-J-XX:-UsePerfData for all but java) in front of the
caller's arguments. HotSpot writes /tmp/hsperfdata_<user>/<pid> for every
JVM, in a /tmp it hardcodes whatever TMPDIR says, so every gate step that
starts a JVM wrote outside the prefix. The only switch that turns it off is
that flag, and the environment variables that could carry it
(JAVA_TOOL_OPTIONS, JDK_JAVA_OPTIONS) make each JVM print "Picked up ..." on
stderr, which changes the output under test. The lock entry is untouched:
the archive is the same bytes, the shim is written after unpacking (build,
install), and MANIFEST records each launcher's digest as the archive has it,
which verify holds bin/<name>.real to, with the shim's exact bytes.

MANIFEST.json (in the prefix, not the repository) records what build put
there: per item the prefix-relative path, bytes, and a file sha256 or a tree
digest. `verify` recomputes every one of them and, for downloads, also checks
the lock, so an edited MANIFEST cannot vouch for an edited archive.

Subcommands:
    build   --prefix P [--repo R] [--seed-cache DIR]
    install --prefix P      extract toolchains from inputs/downloads (a shipped
                            pack) and verify
    verify  --prefix P [--repo R]
    conda-unpack ...        internal: what build and install run under the
                            prefix's python to unpack the compiler
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prefix as prefix_mod  # noqa: E402


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root, relocated=None):
    """A digest of a directory's names, contents, executable bits and links.

    Modes other than the executable bit and owners are left out: tar applies
    the umask for an ordinary user and keeps the archive's modes for root, and
    the same pack must verify on both. `__pycache__` directories are left out
    as well: python-build-standalone ships no bytecode, the interpreter writes
    it beside the stdlib on first import, and it validates each file against
    its source itself. `relocated` ({relative path: placeholder}) names files
    whose placeholder was rewritten to `root`; they are hashed with `root`
    put back, so the digest does not depend on where the prefix lives.
    Returns (digest, bytes, files).
    """
    root = Path(root)
    relocated = relocated or {}
    location = str(root).encode()
    digest = hashlib.sha256()
    total = files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        rel_dir = Path(dirpath).relative_to(root)
        for name in sorted(filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]):
            path = Path(dirpath) / name
            rel = (rel_dir / name).as_posix()
            if path.is_symlink():
                digest.update(f"L {rel} {os.readlink(path)}\n".encode())
            elif path.is_file():
                size = path.stat().st_size
                x = "x" if path.stat().st_mode & 0o100 else "-"
                if rel in relocated:
                    data = path.read_bytes().replace(location, relocated[rel].encode())
                    size, content = len(data), hashlib.sha256(data).hexdigest()
                else:
                    content = sha256_file(path)
                digest.update(f"F {rel} {x} {size} {content}\n".encode())
                total += size
                files += 1
        # a symlinked directory was recorded as a link; do not walk into it
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
    return digest.hexdigest(), total, files


def seed_tree_sha(root):
    """seedjar.sh's seed_tree_sha: files sorted by `./path`, each contributing
    `<bytes> ./<path>\\n` then its content, the whole through SHA-256."""
    root = Path(root)
    names = sorted(("./" + p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()),
                   key=lambda s: s.encode())
    digest = hashlib.sha256()
    for name in names:
        data = (root / name[2:]).read_bytes()
        digest.update(f"{len(data)} {name}\n".encode())
        digest.update(data)
    return digest.hexdigest()


def table_value(path, tag):
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and not line.startswith("#") and fields[1] == tag:
            return fields[0]
    return None


def archive_name(item):
    return urllib.parse.unquote(item["url"].rsplit("/", 1)[1])


def git_common_dir(repo):
    return Path(subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute",
                                "--git-common-dir"], check=True, capture_output=True,
                               text=True).stdout.strip())


# The shims are the same bytes in every prefix: each finds its .real beside
# itself, so no path is written into them and the toolchain's tree digest
# does not depend on where the prefix lives. `java` takes the flag as it is;
# every other launcher (javac, jar, ...) starts its JVM from options it is
# given as -J<option>. argv[0] is kept (bash's exec -a; dash has no such
# option) because scripts/selfhost-bench.py and its contracts recognise a JVM by
# argv[0]'s basename being `java`; the launcher finds its home through
# /proc/self/exe, not argv[0], so java.home is unchanged. The shim forks
# nothing (no dirname, no readlink): until its exec the process is bash, and
# the bench samples /proc every 2ms. bash is given the script's own path
# when it is run through PATH or by path; nothing links to these launchers.
SHIM = """#!/bin/bash
# Written by scripts/gates-external/inputs.py, not part of GraalVM: every JVM
# of a gate run starts without hsperfdata, which HotSpot would write to /tmp.
# argv[0] stays the caller's, so the process still reads as {name}.
exec -a "$0" "${{0%/*}}/{name}.real" {flag} "$@"
"""


def shim_text(name):
    return SHIM.format(name=name, flag="-XX:-UsePerfData" if name == "java"
                       else "-J-XX:-UsePerfData")


def archive_launchers(archive):
    """{name: sha256} of every regular file in the archive's bin/.

    Read from the archive, not the unpacked tree, so verify holds each
    .real to the bytes GraalVM shipped.
    """
    work = Path(archive).parent / f".{Path(archive).name}.bin"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        subprocess.run(["tar", "xzf", str(archive), "-C", str(work), "--strip-components=1",
                        "--wildcards", "*/bin/*"], check=True)
        return {p.name: sha256_file(p) for p in sorted((work / "bin").iterdir())
                if p.is_file() and not p.is_symlink()}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def launchers(target):
    """The launchers a shim wraps: regular files in bin/ (symlinks such as
    native-image point into lib/ and are left alone)."""
    names = set()
    for p in (Path(target) / "bin").iterdir():
        if p.is_symlink() or not p.is_file():
            continue
        names.add(p.name[:-len(".real")] if p.name.endswith(".real") else p.name)
    return sorted(names)


def install_shims(target):
    """bin/<x> -> bin/<x>.real and the shim at bin/<x>, for every launcher;
    idempotent."""
    for name in launchers(target):
        exe = Path(target) / "bin" / name
        real = exe.with_name(name + ".real")
        if not real.exists():
            exe.rename(real)
        text = shim_text(name)
        if not exe.exists() or exe.read_text(errors="replace") != text:
            tmp = exe.with_name(name + ".shim.tmp")
            tmp.write_text(text)
            tmp.chmod(0o755)
            tmp.rename(exe)


def check_shims(target, want):
    """What verify holds a GraalVM toolchain to; a list of problems."""
    if not want:
        return ["MANIFEST records no launcher digests (a prefix from before the shims; "
                "run inputs.py build or install)"]
    problems = []
    for name, digest in sorted(want.items()):
        exe = Path(target) / "bin" / name
        real = exe.with_name(name + ".real")
        if not exe.is_file() or exe.read_text(errors="replace") != shim_text(name):
            problems.append(f"bin/{name} is not the -XX:-UsePerfData shim")
        if not real.is_file():
            problems.append(f"bin/{name}.real is missing")
        elif sha256_file(real) != digest:
            problems.append(f"bin/{name}.real is not the archive's bin/{name}")
    extra = set(launchers(target)) - set(want)
    if extra:
        problems.append(f"launchers the archive does not have: {sorted(extra)}")
    return problems


def mib(n):
    return f"{n / 2**20:.1f} MiB"


# ------------------------------------------------------------- downloads

def fetch(item, prefix, log):
    dst = prefix / "inputs" / "downloads" / archive_name(item)
    if dst.exists() and sha256_file(dst) == item["sha256"]:
        log(f"{item['name']}: {dst.name} already present and matches the lock")
        return dst, 0.0
    part = dst.with_name(dst.name + ".part")
    t0 = time.monotonic()
    subprocess.run(["curl", "-fL", "--retry", "3", "-sS", "-o", str(part), item["url"]], check=True)
    seconds = time.monotonic() - t0
    got = sha256_file(part)
    if got != item["sha256"]:
        part.unlink()
        raise SystemExit(f"inputs: {item['name']} {item['url']} has sha256 {got}, "
                         f"the lock says {item['sha256']}; refusing it")
    part.rename(dst)
    log(f"{item['name']}: downloaded {mib(dst.stat().st_size)} in {seconds:.1f}s")
    return dst, seconds


def extract(item, prefix, archive, log):
    target = prefix / "toolchain" / item["dir"]
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    t0 = time.monotonic()
    subprocess.run(["tar", "xf", str(archive), "-C", str(tmp), "--strip-components=1"],
                   check=True)
    if item["name"] == "graalvm":
        install_shims(tmp)
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    log(f"{item['name']}: extracted into toolchain/{item['dir']} in {time.monotonic() - t0:.1f}s")
    return target


# ----------------------------------------------------- conda toolchains

def package_item(url, sha256):
    """A conda package as a download: named by its file, which is unique."""
    name = urllib.parse.unquote(url.rsplit("/", 1)[1])
    return {"name": name.removesuffix(".conda"), "version": "conda", "url": url, "sha256": sha256}


def pinned_archives(lock):
    """Every archive the lock pins, as download items: {name: item}."""
    items = list(lock["downloads"]) + list(lock.get("wheels", []))
    for entry in lock.get("conda_toolchains", []):
        items += [package_item(p["url"], p["sha256"]) for p in entry["packages"]]
    return {item["name"]: item for item in items}


def prefix_python(prefix):
    return prefix_mod.toolchain_dir(prefix, "python") / "bin" / "python3"


def conda_unpack(args):
    """Unpack .conda packages into one directory; run by the prefix's python.

    Prints {relative path: placeholder} for the text files that carry the
    build prefix. Unpacks what conda links into an environment, the files
    info/paths.json lists (a payload's own info/ files stay out, as conda
    keeps them in its package cache), and refuses a package with any other
    file or missing one, a file whose bytes are not the ones it records,
    a file two packages both ship, and a binary-mode placeholder (conda pads
    those with NULs inside compiled code; none of the pinned packages has one,
    and this module does not pretend to do it).
    """
    import io
    import tarfile
    import zipfile
    sys.path.insert(0, args.wheel_dir)
    import zstandard
    into = Path(args.into)
    owner, relocate = {}, {}

    def member(zf, prefix):
        found = [n for n in zf.namelist() if n.startswith(prefix) and n.endswith(".tar.zst")]
        if len(found) != 1:
            raise SystemExit(f"inputs: {zf.filename} has {len(found)} {prefix}*.tar.zst members")
        return found[0]

    for archive in args.archives:
        label = Path(archive).name
        with zipfile.ZipFile(archive) as zf:
            with zf.open(member(zf, "info-")) as raw:
                info = zstandard.ZstdDecompressor().stream_reader(raw).read()
            with tarfile.open(fileobj=io.BytesIO(info)) as tar:
                paths = json.load(tar.extractfile("info/paths.json"))["paths"]
            record = {p["_path"]: p for p in paths}
            shipped = set()
            with zf.open(member(zf, "pkg-")) as raw, \
                    zstandard.ZstdDecompressor().stream_reader(raw) as stream, \
                    tarfile.open(fileobj=stream, mode="r|") as tar:
                for entry in tar:
                    if entry.name not in record and entry.name.startswith("info/"):
                        # package metadata that conda keeps in its package
                        # cache and never links into an environment
                        continue
                    if not entry.isdir():
                        if entry.name in owner:
                            raise SystemExit(f"inputs: {label} and {owner[entry.name]} both ship "
                                             f"{entry.name}")
                        owner[entry.name] = label
                        shipped.add(entry.name)
                    tar.extract(entry, into, filter="tar")
        if shipped != set(record):
            raise SystemExit(f"inputs: {label} unpacked {sorted(shipped ^ set(record))[:5]} "
                             f"differently from its info/paths.json")
        for rel, p in record.items():
            path = into / rel
            if p.get("path_type") == "hardlink" and not path.is_symlink() \
                    and sha256_file(path) != p.get("sha256"):
                raise SystemExit(f"inputs: {label}: {rel} is not the file its paths.json records")
            if "prefix_placeholder" in p:
                if p.get("file_mode") != "text":
                    raise SystemExit(f"inputs: {label}: {rel} has a {p.get('file_mode')} "
                                     f"placeholder, which this unpacker does not relocate")
                relocate[rel] = p["prefix_placeholder"]
    print(json.dumps(relocate, sort_keys=True))
    return 0


def extract_conda(entry, prefix, log):
    """Unpack every package of one conda toolchain and relocate it.

    Returns {relative path: placeholder} for MANIFEST, which verify needs to
    take the tree digest independently of the location.
    """
    lock = prefix_mod.load_lock()
    target = prefix / "toolchain" / entry["dir"]
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    wheel = next(item for item in lock["wheels"] if item["name"] == "zstandard")
    wheel_dir = prefix / "tmp" / "inputs-wheels" / f"zstandard-{wheel['version']}"
    shutil.rmtree(wheel_dir, ignore_errors=True)
    wheel_dir.mkdir(parents=True)
    import zipfile
    with zipfile.ZipFile(prefix / "inputs" / "downloads" / archive_name(wheel)) as zf:
        zf.extractall(wheel_dir)
    archives = [str(prefix / "inputs" / "downloads" / archive_name(package_item(**p)))
                for p in entry["packages"]]
    t0 = time.monotonic()
    done = subprocess.run([str(prefix_python(prefix)), "-B", str(Path(__file__).resolve()),
                           "conda-unpack", "--wheel-dir", str(wheel_dir), "--into", str(tmp)]
                          + archives, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    shutil.rmtree(wheel_dir, ignore_errors=True)
    if done.returncode != 0:
        raise SystemExit(f"inputs: unpacking {entry['name']} failed:\n{done.stdout}{done.stderr}")
    relocated = json.loads(done.stdout)
    # conda's text relocation: the placeholder becomes the install location,
    # which is `target` (the directory is renamed there below)
    for rel, placeholder in relocated.items():
        path = tmp / rel
        path.write_bytes(path.read_bytes().replace(placeholder.encode(), str(target).encode()))
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    log(f"{entry['name']}: {len(archives)} conda packages unpacked into toolchain/{entry['dir']}, "
        f"{len(relocated)} file(s) relocated, in {time.monotonic() - t0:.1f}s")
    return relocated


# -------------------------------------------------------------- commands

def build(args):
    prefix = Path(args.prefix).resolve()
    repo = Path(args.repo).resolve()
    prefix_mod.ensure_layout(prefix)
    log = lambda m: print(f"inputs: {m}", flush=True)  # noqa: E731
    items = []
    for item in prefix_mod.load_lock()["downloads"]:
        archive, seconds = fetch(item, prefix, log)
        target = prefix / "toolchain" / item["dir"]
        if not target.exists():
            extract(item, prefix, archive, log)
        extra = {}
        if item["name"] == "graalvm":
            install_shims(target)
            extra["launcher_sha256"] = archive_launchers(archive)
        tree, size, files = tree_digest(target)
        items.append(download_row(item, archive, seconds, prefix))
        items.append({"name": item["name"], "version": item["version"], "kind": "toolchain",
                      "path": target.relative_to(prefix).as_posix(), "bytes": size,
                      "files": files, "tree_sha256": tree,
                      "source": f"extracted from {archive.name}", **extra})
    # The compiler's rows go under their own key, conda_items: verifiers from
    # before it entered the pack read only `items`, index every download row
    # there by the lock they carry, and hash every toolchain without
    # relocation, so a row of these in `items` would turn them red. The local
    # and cluster prefixes are verified by several branches' tools at once.
    lock = prefix_mod.load_lock()
    conda_items = []
    for item in lock.get("wheels", []):
        archive, seconds = fetch(item, prefix, log)
        conda_items.append(download_row(item, archive, seconds, prefix))
    for entry in lock.get("conda_toolchains", []):
        packages = [package_item(**p) for p in entry["packages"]]
        for item in packages:
            archive, seconds = fetch(item, prefix, log)
            conda_items.append(download_row(item, archive, seconds, prefix))
        # always unpacked afresh: the relocated files are only known from the
        # packages, and unpacking takes seconds
        relocated = extract_conda(entry, prefix, log)
        target = prefix / "toolchain" / entry["dir"]
        tree, size, files = tree_digest(target, relocated)
        conda_items.append({"name": entry["name"], "version": entry["version"], "kind": "toolchain",
                      "path": target.relative_to(prefix).as_posix(), "bytes": size,
                      "files": files, "tree_sha256": tree,
                      "source": f"{len(packages)} conda packages",
                      "packages": [item["name"] for item in packages], "relocated": relocated})

    tag = (repo / "scripts/seed-release.txt").read_text().strip()
    seed_cache = Path(args.seed_cache) if args.seed_cache else git_common_dir(repo).parent / ".dawn/seeds"
    jar_want = table_value(repo / "scripts/seed-checksums.txt", tag)
    std_want = table_value(repo / "scripts/seed-std-checksums.txt", tag)
    seed_dir = prefix / "inputs" / "seeds" / tag
    seed_dir.mkdir(parents=True, exist_ok=True)
    jar = seed_dir / "seed.jar"
    if not jar.exists() or sha256_file(jar) != jar_want:
        shutil.copy2(seed_cache / tag / "seed.jar", jar)
    if sha256_file(jar) != jar_want:
        raise SystemExit(f"inputs: the {tag} seed jar does not match scripts/seed-checksums.txt")
    std_dir = prefix / "inputs" / "std-seeds" / tag
    if not std_dir.exists() or seed_tree_sha(std_dir) != std_want:
        shutil.rmtree(std_dir, ignore_errors=True)
        shutil.copytree(seed_cache / f"std-{tag}", std_dir)
    if seed_tree_sha(std_dir) != std_want:
        raise SystemExit(f"inputs: the {tag} std does not match scripts/seed-std-checksums.txt")
    items.append({"name": "seed", "version": tag, "kind": "seed",
                  "path": jar.relative_to(prefix).as_posix(), "bytes": jar.stat().st_size,
                  "sha256": jar_want, "source": "scripts/seed-checksums.txt"})
    items.append({"name": "std-seed", "version": tag, "kind": "std-seed",
                  "path": std_dir.relative_to(prefix).as_posix(),
                  "bytes": sum(p.stat().st_size for p in std_dir.rglob("*") if p.is_file()),
                  "seed_tree_sha256": std_want, "tree_sha256": tree_digest(std_dir)[0],
                  "source": "scripts/seed-std-checksums.txt"})
    log(f"seed {tag}: jar and std match the repository's tables")

    coursier = prefix / "inputs" / "coursier"
    if args.refresh_coursier or not any(coursier.rglob("*.jar")):
        prime_coursier(prefix, repo, tag, coursier, log)
    check_coursier_against_lock(repo, coursier)
    tree, size, files = tree_digest(coursier)
    items.append({"name": "coursier", "version": "selfhost/dawn.lock", "kind": "coursier",
                  "path": "inputs/coursier", "bytes": size, "files": files, "tree_sha256": tree,
                  "source": "./bin/dawn --version with COURSIER_CACHE in the prefix"})

    manifest_path = prefix / "inputs" / "MANIFEST.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"items": []}
    for entry in prefix_mod.load_lock().get("npm_caches", []):
        items.append(reuse_npm_cache(prefix, entry, previous, log)
                     or build_npm_cache(prefix, repo, entry, log))

    manifest = {"schema": 1, "items": items, "conda_items": conda_items}
    # written whole and renamed: other runs may be reading it
    tmp_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    tmp_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    tmp_manifest.rename(manifest_path)
    shutil.copy2(prefix_mod.LOCK_FILE, prefix / "inputs" / "inputs.lock.json")
    for row in items + conda_items:
        print(f"  {row['kind']:10} {row['name']:9} {row['version']:20} {mib(row['bytes']):>11}  {row['path']}")
    return verify(argparse.Namespace(prefix=str(prefix), repo=str(repo)))


def download_row(item, archive, seconds, prefix):
    return {"name": item["name"], "version": item["version"], "kind": "download",
            "path": archive.relative_to(prefix).as_posix(),
            "bytes": archive.stat().st_size, "sha256": item["sha256"],
            "source": item["url"], "download_seconds": round(seconds, 1)}


def prime_coursier(prefix, repo, tag, coursier, log):
    """Run `./bin/dawn --version` once, in the prefix, with the cache there."""
    work = prefix / "tmp" / "inputs-build"
    shutil.rmtree(work, ignore_errors=True)
    (work / "tmp").mkdir(parents=True)
    tree = work / "tree"
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    env = prefix_mod.job_env(prefix, tmpdir=work / "tmp", runner_temp=work / "tmp")
    env["COURSIER_CACHE"] = str(coursier)
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(repo), str(tree)],
                   check=True, env=env)
    subprocess.run(["git", "-C", str(tree), "checkout", "-q", "--detach", head], check=True, env=env)
    (tree / ".dawn/seeds").mkdir(parents=True)
    shutil.copytree(prefix / "inputs/seeds" / tag, tree / ".dawn/seeds" / tag)
    shutil.copytree(prefix / "inputs/std-seeds" / tag, tree / ".dawn/seeds" / f"std-{tag}")
    shutil.rmtree(coursier, ignore_errors=True)
    coursier.mkdir(parents=True)
    t0 = time.monotonic()
    done = subprocess.run(["./bin/dawn", "--version"], cwd=tree, env=env,
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"inputs: ./bin/dawn --version failed while priming coursier:\n"
                         f"{done.stdout}{done.stderr}")
    log(f"coursier: primed by ./bin/dawn --version ({done.stdout.strip()}) in "
        f"{time.monotonic() - t0:.0f}s")
    shutil.rmtree(work, ignore_errors=True)


def reuse_npm_cache(prefix, entry, previous, log):
    """The previous build's npm cache row, when that cache is still intact.

    A refill is never the same bytes (npm's index carries times), so
    rebuilding it would change the cache, and the digest in MANIFEST, under
    anyone using the prefix at that moment; `build` for some other input
    (the compiler) must not do that.
    """
    cache = prefix / entry["dir"]
    for row in previous.get("items", []):
        if row["kind"] == "npm-cache" and row["name"] == entry["name"] \
                and row.get("lockfile_sha256") == entry["lockfile_sha256"] \
                and cache.is_dir() and tree_digest(cache)[0] == row["tree_sha256"]:
            log(f"{entry['name']}: {entry['dir']} is the cache the last build filled; kept")
            return row
    return None


def build_npm_cache(prefix, repo, entry, log):
    """`npm ci` against the pinned lockfile, with the cache in the prefix."""
    lockfile = repo / entry["lockfile"]
    if sha256_file(lockfile) != entry["lockfile_sha256"]:
        raise SystemExit(f"inputs: {entry['lockfile']} is not the lockfile inputs.lock.json pins "
                         f"({entry['lockfile_sha256']}); update the lock entry with the cache")
    cache = prefix / entry["dir"]
    work = prefix / "tmp" / f"inputs-{entry['name']}"
    shutil.rmtree(work, ignore_errors=True)
    (work / "tmp").mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(lockfile.parent / name, work / name)
    env = prefix_mod.job_env(prefix, tmpdir=work / "tmp", runner_temp=work / "tmp")
    env["npm_config_cache"] = str(cache)
    env.pop("npm_config_offline", None)
    # This is a download, like fetch(): it reaches the registry the way this
    # machine reaches the network. A job never gets these variables.
    env.update({k: v for k, v in os.environ.items() if k.lower().endswith("_proxy")})
    shutil.rmtree(cache, ignore_errors=True)
    t0 = time.monotonic()
    # --ignore-scripts: filling a cache needs nothing executed
    done = subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                          cwd=work, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"inputs: npm ci failed while filling {entry['dir']}:\n"
                         f"{done.stdout}{done.stderr}")
    # npm's own logs and notifier state are not inputs
    shutil.rmtree(cache / "_logs", ignore_errors=True)
    (cache / "_update-notifier-last-checked").unlink(missing_ok=True)
    shutil.rmtree(work, ignore_errors=True)
    tree, size, files = tree_digest(cache)
    log(f"{entry['name']}: npm ci filled {entry['dir']} ({files} files, {mib(size)}) in "
        f"{time.monotonic() - t0:.0f}s")
    return {"name": entry["name"], "version": entry["lockfile_sha256"][:12], "kind": "npm-cache",
            "path": entry["dir"], "bytes": size, "files": files, "tree_sha256": tree,
            "lockfile": entry["lockfile"], "lockfile_sha256": entry["lockfile_sha256"],
            "source": f"npm ci of {entry['lockfile']}"}


def check_coursier_against_lock(repo, coursier):
    want = {}
    for line in (repo / "selfhost/dawn.lock").read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "artifact":
            want[fields[2]] = fields[1]
    have = {}
    for jar in coursier.rglob("*.jar"):
        have.setdefault(jar.name, set()).add(sha256_file(jar))
    for name, digest in want.items():
        if digest not in have.get(name, set()):
            raise SystemExit(f"inputs: the coursier cache has no {name} with the sha256 "
                             f"selfhost/dawn.lock records")


def install(args):
    """Extract every toolchain from a shipped inputs/downloads, then verify."""
    prefix = Path(args.prefix).resolve()
    prefix_mod.ensure_layout(prefix)
    log = lambda m: print(f"inputs: {m}", flush=True)  # noqa: E731
    manifest = json.loads((prefix / "inputs" / "MANIFEST.json").read_text())
    trees = {row["name"]: row["tree_sha256"] for row in manifest["items"] if row["kind"] == "toolchain"}
    for item in prefix_mod.load_lock()["downloads"]:
        archive = prefix / "inputs" / "downloads" / archive_name(item)
        if sha256_file(archive) != item["sha256"]:
            raise SystemExit(f"inputs: {archive.name} does not match the lock")
        target = prefix / "toolchain" / item["dir"]
        if target.exists() and tree_digest(target)[0] == trees.get(item["name"]):
            log(f"{item['name']}: toolchain/{item['dir']} already matches")
            continue
        extract(item, prefix, archive, log)
    lock = prefix_mod.load_lock()
    for item in lock.get("wheels", []):
        if sha256_file(prefix / "inputs" / "downloads" / archive_name(item)) != item["sha256"]:
            raise SystemExit(f"inputs: {archive_name(item)} does not match the lock")
    rows = {row["name"]: row for row in manifest.get("conda_items", [])
            if row["kind"] == "toolchain"}
    for entry in lock.get("conda_toolchains", []):
        for item in (package_item(**p) for p in entry["packages"]):
            if sha256_file(prefix / "inputs" / "downloads" / archive_name(item)) != item["sha256"]:
                raise SystemExit(f"inputs: {archive_name(item)} does not match the lock")
        target = prefix / "toolchain" / entry["dir"]
        row = rows.get(entry["name"], {})
        if target.exists() and tree_digest(target, row.get("relocated"))[0] == row.get("tree_sha256"):
            log(f"{entry['name']}: toolchain/{entry['dir']} already matches")
            continue
        extract_conda(entry, prefix, log)
    return verify(argparse.Namespace(prefix=str(prefix), repo=None))


def verify(args):
    prefix = Path(args.prefix).resolve()
    manifest_path = prefix / "inputs" / "MANIFEST.json"
    if not manifest_path.exists():
        print(f"inputs verify: no {manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text())
    lock = pinned_archives(prefix_mod.load_lock())
    npm_lock = {item["name"]: item for item in prefix_mod.load_lock().get("npm_caches", [])}
    bad = 0
    t0 = time.monotonic()
    for row in manifest["items"] + manifest.get("conda_items", []):
        path = prefix / row["path"]
        problems = []
        if not path.exists():
            problems.append("missing")
        elif row["kind"] == "download":
            got = sha256_file(path)
            if got != lock[row["name"]]["sha256"]:
                problems.append(f"sha256 {got} is not the lock's {lock[row['name']]['sha256']}")
            if got != row["sha256"]:
                problems.append("sha256 differs from MANIFEST")
        elif row["kind"] == "seed":
            got = sha256_file(path)
            if got != row["sha256"]:
                problems.append(f"sha256 {got} differs from MANIFEST")
            if args.repo:
                want = table_value(Path(args.repo) / "scripts/seed-checksums.txt", row["version"])
                if got != want:
                    problems.append("not the digest scripts/seed-checksums.txt records")
        else:
            got = tree_digest(path, row.get("relocated"))[0]
            if got != row["tree_sha256"]:
                problems.append(f"tree digest {got} differs from MANIFEST")
            if row["kind"] == "toolchain" and row["name"] == "graalvm":
                problems += check_shims(path, row.get("launcher_sha256"))
            if row["kind"] == "std-seed":
                seed_sha = seed_tree_sha(path)
                if seed_sha != row["seed_tree_sha256"]:
                    problems.append("seed_tree_sha differs from MANIFEST")
                if args.repo and seed_sha != table_value(
                        Path(args.repo) / "scripts/seed-std-checksums.txt", row["version"]):
                    problems.append("not the digest scripts/seed-std-checksums.txt records")
        if row["kind"] == "npm-cache":
            want = npm_lock.get(row["name"], {}).get("lockfile_sha256")
            if row.get("lockfile_sha256") != want:
                problems.append(f"built from lockfile {row.get('lockfile_sha256')}, the lock pins {want}")
            if args.repo and want and sha256_file(Path(args.repo) / row["lockfile"]) != want:
                problems.append(f"{row['lockfile']} in the repository is not the pinned lockfile")
        if row["kind"] == "download" and row["name"] not in lock:
            problems.append("not in inputs.lock.json")
        status = "ok  " if not problems else "FAIL"
        print(f"{status} {row['kind']:10} {row['name']:9} {row['version']:20} "
              f"{mib(row['bytes']):>11}  {row['path']}{'  ' + '; '.join(problems) if problems else ''}")
        bad += bool(problems)
    missing = set(lock) - {r["name"] for r in manifest["items"] + manifest.get("conda_items", [])
                           if r["kind"] == "download"}
    conda_lock = {entry["name"] for entry in prefix_mod.load_lock().get("conda_toolchains", [])}
    for name in sorted(conda_lock - {r["name"] for r in manifest.get("conda_items", [])
                                     if r["kind"] == "toolchain"}):
        print(f"FAIL toolchain  {name} in inputs.lock.json but not in MANIFEST")
        bad += 1
    for name in sorted(missing):
        print(f"FAIL download   {name:9} in inputs.lock.json but not in MANIFEST")
        bad += 1
    for name in sorted(set(npm_lock) - {r["name"] for r in manifest["items"]
                                         if r["kind"] == "npm-cache"}):
        print(f"FAIL npm-cache  {name} in inputs.lock.json but not in MANIFEST")
        bad += 1
    print(f"inputs verify: {'green' if not bad else f'RED, {bad} item(s)'} "
          f"({time.monotonic() - t0:.1f}s)")
    return 0 if not bad else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--prefix", required=True)
    p.add_argument("--repo", default=str(HERE.parents[1]))
    p.add_argument("--seed-cache")
    p.add_argument("--refresh-coursier", action="store_true")
    p = sub.add_parser("install")
    p.add_argument("--prefix", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--prefix", required=True)
    p.add_argument("--repo")
    # internal: what extract_conda runs under the prefix's python
    p = sub.add_parser("conda-unpack")
    p.add_argument("--wheel-dir", required=True)
    p.add_argument("--into", required=True)
    p.add_argument("archives", nargs="+")
    args = parser.parse_args()
    return {"build": build, "install": install, "verify": verify,
            "conda-unpack": conda_unpack}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

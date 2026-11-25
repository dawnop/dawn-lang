#!/usr/bin/env python3
"""The schema 2 release protocol: native chain, nine-asset producer, aggregate check.

Why this is one module and not release.yml shell: a release step runs on tags
only, so it is the least-executed code in the repository. As a module the same
code runs in gates (through release-native.sh's contract package), in tests and
in the release workflow.

Why the identity rules are not written twice: install-native.py is the single
file a consumer downloads, so it cannot import anything from this repository.
It therefore owns the metadata and payload rules (`metadata_for`, `verify_payload`),
and this module loads that file and reuses them. A rule exists once, in the
file that must stand alone.

Subcommands:

  chain      seed S -> A -> B -> C, compared byte for byte (B == C)
  produce    the nine release assets from a chain's A and B plus the JVM jar
  aggregate  re-check a directory of nine assets (producer end and consumer end)

There is no schema 1 path, no ignore-the-digest switch and no fallback between
the native and the JVM chain: either an identity matches or the command stops.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import native_seed.contract as c  # noqa: E402
from native_seed import lockchain  # noqa: E402

spec = importlib.util.spec_from_file_location("install_native", HERE / "install-native.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

ASSET = installer.ASSET
JAR = "dawn-selfhost.jar"
PROOF = "native-bootstrap.json"
INSTALLER = "install-native.py"
API = "dawn-pub-api.json"
API_DIFF = "dawn-pub-api-diff.md"
# Upload order is part of the protocol (scripts/release-publish.py): the
# metadata is the seal and is therefore last.
INSTALL_ASSETS = (JAR, JAR + ".sha256", ASSET, ASSET + ".sha256", installer.METADATA, INSTALLER)
REPORT_ASSETS = (API, API_DIFF, PROOF)
UPLOAD_ORDER = (JAR, JAR + ".sha256", ASSET, ASSET + ".sha256", INSTALLER, API, API_DIFF, PROOF,
                installer.METADATA)
assert sorted(UPLOAD_ORDER) == sorted(INSTALL_ASSETS + REPORT_ASSETS)
PROOF_FIELDS = ("schema kind source_commit lock_sha256 qualification_sha256 cold_sha256 "
                "builder_sha256 native_sha256 identities_sha256")


def canonical(value):
    return c.canonical(value)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def identity_digest(info):
    """Digest of the metadata without its proof reference: no circular digest."""
    return sha256(canonical({key: item for key, item in info.items() if key != "proof"}))


def compiler_identity(binary, version=None):
    """(version, full build id) of a native compiler, read by running it twice."""
    with tempfile.TemporaryDirectory(prefix="native-release-probe-") as home:
        env = {"PATH": "/nonexistent", "HOME": home, "LANG": "C.UTF-8"}
        said = subprocess.run([str(binary), "--version"], env=env, capture_output=True, timeout=60)
        listed = subprocess.run([str(binary), "version", "-m", str(binary)], env=env,
                                capture_output=True, timeout=60)
    ids = re.findall(rb"^\tbuild\t(b1:[0-9a-f]{64})$", listed.stdout, re.M)
    c.require(said.returncode == listed.returncode == 0 and not said.stderr and not listed.stderr and
              len(ids) == 1, "release-identity", f"cannot read the identity of {binary}")
    match = re.fullmatch(rb"dawnc ([0-9]+\.[0-9]+\.[0-9]+) \(native\) (b1:[0-9a-f]{12})\n", said.stdout)
    c.require(match and match[2] == ids[0][:15], "release-identity", "short and full build ids differ")
    c.require(version is None or match[1].decode() == version, "release-identity",
              f"{binary} says {match[1].decode()}, expected {version}")
    return match[1].decode(), ids[0].decode()


# ---------------------------------------------------------------- aggregate

def aggregate(directory, tag, lock=None):
    """The nine-asset set is complete, every cross reference holds, nothing else."""
    directory = Path(directory)
    names = sorted(p.name for p in directory.iterdir())
    c.require(names == sorted(UPLOAD_ORDER), "release-assets",
              f"expected exactly the nine release assets, found {names}")
    for name in names:
        c.require((directory / name).is_file() and not (directory / name).is_symlink(),
                  "release-assets", f"{name} is not a regular file")
    raw = (directory / installer.METADATA).read_bytes()
    try:
        info = installer.metadata_for(raw, tag)
    except (ValueError, KeyError, TypeError) as exc:
        raise c.Rejected(f"release-metadata: {exc}") from exc
    c.require(raw == canonical(info), "release-metadata", "metadata is not in canonical form")
    payload = (directory / ASSET).read_bytes()
    try:
        installer.verify_payload(payload, (directory / (ASSET + ".sha256")).read_bytes(), info)
    except ValueError as exc:
        raise c.Rejected(f"release-payload: {exc}") from exc
    jar = (directory / JAR).read_bytes()
    reference = info["jvm_reference"]
    c.require(sha256(jar) == reference["sha256"] and
              (directory / (JAR + ".sha256")).read_bytes() == f"{sha256(jar)}  {JAR}\n".encode(),
              "release-jar", "JVM reference bytes differ from metadata or sidecar")
    proof_bytes = (directory / PROOF).read_bytes()
    try:
        proof = json.loads(proof_bytes, object_pairs_hook=installer.no_duplicate_keys)
    except ValueError as exc:
        raise c.Rejected(f"release-proof: {exc}") from exc
    c.require(type(proof) is dict and set(proof) == set(PROOF_FIELDS.split()), "release-proof",
              "proof must carry exactly its declared fields")
    c.require(proof["schema"] == 2 and type(proof["schema"]) is int and proof["kind"] == "native-bootstrap" and
              proof["source_commit"] == info["release"]["commit"] and
              proof["builder_sha256"] == info["builder"]["sha256"] and
              proof["native_sha256"] == info["native"]["sha256"] and
              proof["identities_sha256"] == identity_digest(info) and
              proof_bytes == canonical(proof) and sha256(proof_bytes) == info["proof"]["sha256"],
              "release-proof", "proof does not describe this metadata")
    for key in ("lock_sha256", "cold_sha256"):
        c.sha(proof[key], key)
    # A release says which qualification receipt its seed rests on. There is no
    # spelling for "none": that was the state before the qualified lock existed.
    c.require(proof["qualification_sha256"] is not None, "release-qualification",
              "the release does not name a qualification receipt")
    c.sha(proof["qualification_sha256"], "qualification")
    if lock is not None:
        lock = Path(lock)
        value = lockchain.release_lock(lock)
        c.require(proof["lock_sha256"] == sha256(lock.read_bytes()) and
                  info["bootstrap"]["seed"] == value["seed"] and info["bootstrap"]["std"] == value["std"] and
                  info["bootstrap"]["runtime"] == value["runtime"] and
                  info["bootstrap"]["parent_receipt_sha256"] == value["lineage"]["parent_receipt_sha256"] and
                  proof["qualification_sha256"] == value["lineage"]["qualification_sha256"],
                  "release-lineage", "bootstrap identity differs from the checked-out seed lock")
    try:
        json.loads((directory / API).read_bytes(), object_pairs_hook=installer.no_duplicate_keys)
    except ValueError as exc:
        raise c.Rejected(f"release-report: {API} is not JSON: {exc}") from exc
    c.require((directory / API_DIFF).stat().st_size > 0, "release-report", f"{API_DIFF} is empty")
    return info


# ------------------------------------------------------------------ produce

def smoke(binary):
    """B is a compiler: it builds and runs a program from a bare directory."""
    program = ("use std/str\n\npub fn main() -> Unit !io = {\n"
               "  println(join(map(sort([3, 1, 2]), x => \"${x}\"), \",\"))\n"
               "  println(str.to_upper(\"release\"))\n}\n")
    with tempfile.TemporaryDirectory(prefix="native-release-smoke-") as work:
        (Path(work) / "hello.dawn").write_text(program)
        # `run` compiles the program's C, so the C compiler stays on PATH.
        run = subprocess.run([str(binary), "run", "hello.dawn"], cwd=work, capture_output=True, timeout=300,
                             env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": work,
                                  "LANG": "C.UTF-8", "CC": os.environ.get("CC", "cc")})
    c.require(run.returncode == 0 and run.stdout == b"1,2,3\nRELEASE\n", "release-smoke",
              "the native binary did not compile and run a one-file program")


def source_version():
    found = re.findall(r'^pub const VERSION: String = "([^"]+)"$',
                       (ROOT / "selfhost/src/version.dawn").read_text(), re.M)
    c.require(len(found) == 1, "release-version", "selfhost/src/version.dawn must declare one VERSION")
    return found[0]


def toolchain_identity():
    cc = os.environ.get("CC") or shutil.which("cc") or ""
    if not cc:
        return sha256(canonical({"cc": None}))
    version = subprocess.run([cc, "--version"], capture_output=True, timeout=60).stdout
    return sha256(canonical({"cc_version_sha256": sha256(version),
                             "cc_binary_sha256": sha256(Path(shutil.which(cc) or cc).read_bytes())}))


def produce(args):
    version = source_version()
    tag = "v" + version
    commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    tree = subprocess.run(["git", "rev-parse", "--verify", "HEAD^{tree}"], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()
    c.oid(commit, "source commit")
    if args.expect_tag:
        c.require(args.expect_tag == tag, "release-version",
                  f"tag {args.expect_tag} does not name source version {version}")
    out = c.safe_destination(args.out)
    c.require(not out.exists(), "destination", "producer requires a new output directory")
    lock_path = Path(args.lock)
    lock = lockchain.release_lock(lock_path)
    native, builder = Path(args.native).absolute(), Path(args.builder).absolute()
    c.verify_elf(native.read_bytes())
    c.verify_elf(builder.read_bytes())
    _, b_id = compiler_identity(native, version)
    _, a_id = compiler_identity(builder, version)
    jdk21, jdk26 = Path(args.jdk21_jar).read_bytes(), Path(args.jdk26_jar).read_bytes()
    c.require(jdk21 == jdk26, "release-jar", "the JDK 21 and JDK 26 candidates differ")
    if not args.skip_smoke:
        smoke(native)
    out.mkdir(parents=True, mode=0o755)
    native_bytes, builder_bytes = native.read_bytes(), builder.read_bytes()
    (out / ASSET).write_bytes(native_bytes)
    (out / ASSET).chmod(0o755)
    (out / JAR).write_bytes(jdk21)
    for name in (ASSET, JAR):
        (out / (name + ".sha256")).write_text(f"{sha256((out / name).read_bytes())}  {name}\n")
    source = (ROOT / "scripts/install-native.py").read_text()
    sys.path.insert(0, str(HERE))
    import repo_env  # noqa: E402
    (out / INSTALLER).write_text(source.replace("@REPOSITORY@", "https://github.com/" + repo_env.github_repo()))
    shutil.copyfile(args.pub_api, out / API)
    shutil.copyfile(args.pub_api_diff, out / API_DIFF)
    cold = args.cold_sha256 or sha256(canonical({"stages": "unrecorded"}))
    c.sha(cold, "cold receipt")
    info = {
        "schema": 2,
        "release": {"tag": tag, "version": version, "commit": commit},
        "native": {"name": ASSET, "kind": "native-elf", "stage": "B", "sha256": sha256(native_bytes),
                   "size": len(native_bytes), "build_id": b_id, "target": installer.TARGET},
        "builder": {"name": "dawnc-stage-a", "kind": "native-elf", "stage": "A",
                    "sha256": sha256(builder_bytes), "version": version, "build_id": a_id},
        "bootstrap": {"seed": lock["seed"], "std": lock["std"], "runtime": lock["runtime"],
                      "parent_receipt_sha256": lock["lineage"]["parent_receipt_sha256"]},
        "recipe": {"inputs_sha256": sha256(canonical({"commit": commit, "tree": tree})),
                   "toolchain_sha256": toolchain_identity(),
                   "recipe_sha256": sha256((ROOT / "scripts/cc-units.sh").read_bytes())},
        "proof": {"name": PROOF, "sha256": "0" * 64},
        "jvm_reference": {"name": JAR, "kind": "jvm-jar", "sha256": sha256(jdk21), "commit": commit,
                          "jdk_equivalence_sha256": sha256(canonical(
                              {"jdk21": sha256(jdk21), "jdk26": sha256(jdk26)}))},
    }
    proof = {"schema": 2, "kind": "native-bootstrap", "source_commit": commit,
             "lock_sha256": sha256(lock_path.read_bytes()),
             "qualification_sha256": lock["lineage"]["qualification_sha256"],
             "cold_sha256": cold, "builder_sha256": info["builder"]["sha256"],
             "native_sha256": info["native"]["sha256"], "identities_sha256": identity_digest(info)}
    proof_bytes = canonical(proof)
    (out / PROOF).write_bytes(proof_bytes)
    info["proof"]["sha256"] = sha256(proof_bytes)
    (out / installer.METADATA).write_bytes(canonical(info))
    aggregate(out, tag, lock_path)
    with tempfile.TemporaryDirectory(prefix="native-release-install-") as prefix:
        installed = installer.install(tag, prefix, str(out))
        c.require(installed.read_bytes() == native_bytes, "release-install", "installer wrote different bytes")
    return out


# -------------------------------------------------------------------- chain

def tree_digest(directory):
    return c.inventory_sha(c.inventory(c.scan(Path(directory))))


def emit_and_link(emitter, entry, std, runtime, out, jobs):
    out.mkdir(parents=True)
    t0 = time.monotonic()
    subprocess.run([str(emitter), "emitc", "--std", str(std), str(entry), "-o", str(out / "whole.c"),
                    "--build-info", str(out / "info.c"), "--split", str(out / "units")], check=True)
    t1 = time.monotonic()
    env = dict(os.environ, CC_JOBS=str(jobs))
    subprocess.run([str(ROOT / "scripts/cc-units.sh"), "--static", "--inline-rc", "--runtime", str(runtime),
                    "-o", str(out / "dawnc"), str(out / "units"), str(out / "info.c")], check=True, env=env)
    t2 = time.monotonic()
    print(f"timing emit {t1 - t0:.1f}s cc {t2 - t1:.1f}s", flush=True)
    return {"whole_sha256": sha256((out / "whole.c").read_bytes()),
            "info_sha256": sha256((out / "info.c").read_bytes()),
            "units_sha256": tree_digest(out / "units"),
            "elf_sha256": sha256((out / "dawnc").read_bytes())}


def chain(args):
    lock = lockchain.release_lock(args.lock)
    seed = Path(args.seed_elf)
    lockchain.verify_seed_bytes(c.regular_bytes(seed), lock)
    out = c.safe_destination(args.out)
    c.require(not out.exists(), "destination", "chain requires a new output directory")
    out.mkdir(parents=True)
    seed_tree = Path(args.seed_tree)
    c.verify_seed_tree(ROOT, lock, seed_tree)
    entry = subprocess.run([sys.executable, str(HERE / "native-source-tree.py"), str(out / "source")],
                           check=True, capture_output=True, text=True).stdout.strip()
    t0 = time.monotonic()
    stages = {}
    for name, emitter, std, runtime in (
            ("A", seed, seed_tree / "std", seed_tree / "runtime/c"),
            ("B", out / "A/dawnc", ROOT / "std", ROOT / "runtime/c"),
            ("C", out / "B/dawnc", ROOT / "std", ROOT / "runtime/c")):
        print(f"stage {name}", flush=True)
        stages[name] = emit_and_link(emitter, entry, std, runtime, out / name, args.jobs)
    for key in ("whole_sha256", "info_sha256", "units_sha256", "elf_sha256"):
        c.require(stages["B"][key] == stages["C"][key], "fixpoint", f"B and C differ in {key}")
    print(f"timing chain {time.monotonic() - t0:.1f}s; B == C", flush=True)
    receipt = {"schema": 1, "kind": "native-release-chain", "seed_sha256": lock["seed"]["sha256"],
               "stages": stages}
    (out / "chain-receipt.json").write_bytes(canonical(receipt))
    print(sha256(canonical(receipt)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("chain")
    p.add_argument("--lock", required=True)
    p.add_argument("--seed-elf", required=True)
    p.add_argument("--seed-tree", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    p = sub.add_parser("produce")
    p.add_argument("--lock", required=True)
    p.add_argument("--native", required=True)
    p.add_argument("--builder", required=True)
    p.add_argument("--jdk21-jar", required=True)
    p.add_argument("--jdk26-jar", required=True)
    p.add_argument("--pub-api", required=True)
    p.add_argument("--pub-api-diff", required=True)
    p.add_argument("--cold-sha256")
    p.add_argument("--expect-tag")
    p.add_argument("--skip-smoke", action="store_true")
    p.add_argument("--out", required=True)
    p = sub.add_parser("aggregate")
    p.add_argument("directory")
    p.add_argument("tag")
    p.add_argument("--lock")
    args = parser.parse_args()
    try:
        if args.command == "chain":
            chain(args)
        elif args.command == "produce":
            produce(args)
        else:
            aggregate(args.directory, args.tag, args.lock)
            print("OK: nine-asset aggregate")
    except (c.Rejected, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"REJECT {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

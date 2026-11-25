#!/usr/bin/env python3
"""Install the Linux x86_64 release as bin/dawn, without a runtime launcher."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import tempfile
import urllib.request

REPOSITORY = "@REPOSITORY@"
if REPOSITORY.startswith("@"):
    # Source checkouts read the central coordinate; the release embeds it so
    # that the downloaded installer remains a single file.
    import repo_env
    REPOSITORY = "https://github.com/" + repo_env.github_repo()
ASSET = "dawnc-linux-x86_64"
TARGET = "x86_64-unknown-linux-gnu"
METADATA = "dawn-toolchain.json"
INSTALL_INPUTS = (ASSET, ASSET + ".sha256", METADATA)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_tag(tag):
    require(isinstance(tag, str) and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag),
            "expected a release tag such as v0.104.0")
    return tag


def download(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def resolve_tag(tag):
    if tag:
        return release_tag(tag)
    # Resolve latest once. Every subsequent request names this concrete tag.
    with urllib.request.urlopen(REPOSITORY + "/releases/latest", timeout=60) as response:
        url = response.geturl()
    prefix = REPOSITORY + "/releases/tag/"
    require(url.startswith(prefix), "latest did not resolve to a release tag")
    return release_tag(url[len(prefix):])


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(name):
    raise ValueError(f"invalid JSON constant {name}")


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=no_duplicate_keys, parse_constant=reject_constant)


def shape(value, names, label):
    require(type(value) is dict and set(value) == set(names.split()),
            f"{label}: expected exactly the fields {names}")


def is_sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def is_build_id(value):
    return type(value) is str and re.fullmatch(r"b1:[0-9a-f]{64}", value) is not None


def is_version(value):
    return type(value) is str and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is not None


def version_key(version):
    return tuple(int(part) for part in version.split("."))


def metadata_for(raw, tag):
    """Validate dawn-toolchain.json, schema 2. There is no schema 1 path."""
    info = parse_json(raw)
    shape(info, "schema release native builder bootstrap recipe proof jvm_reference", "metadata")
    require(type(info["schema"]) is int and info["schema"] == 2,
            "unsupported toolchain metadata schema: schema 2 is required")
    release = info["release"]
    shape(release, "tag version commit", "release")
    require(release["tag"] == tag and release["version"] == tag[1:], "metadata tag/version mismatch")
    require(type(release["commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", release["commit"]),
            "metadata needs a full source commit")
    native = info["native"]
    shape(native, "name kind stage sha256 size build_id target", "native")
    require((native["name"], native["kind"], native["stage"], native["target"]) ==
            (ASSET, "native-elf", "B", TARGET), "native identity differs")
    require(is_sha(native["sha256"]) and type(native["size"]) is int and native["size"] > 0 and
            is_build_id(native["build_id"]), "native digest, size or build id is invalid")
    builder = info["builder"]
    shape(builder, "name kind stage sha256 version build_id", "builder")
    require((builder["name"], builder["kind"], builder["stage"]) == ("dawnc-stage-a", "native-elf", "A"),
            "builder must be the native stage A")
    require(builder["version"] == release["version"], "builder version differs from the release")
    require(is_sha(builder["sha256"]) and is_build_id(builder["build_id"]), "builder identity is invalid")
    bootstrap = info["bootstrap"]
    shape(bootstrap, "seed std runtime parent_receipt_sha256", "bootstrap")
    seed = bootstrap["seed"]
    shape(seed, "kind tag commit asset sha256 size target version build_id", "bootstrap seed")
    require(seed["kind"] == "native-elf" and seed["asset"] == ASSET and seed["target"] == TARGET and
            type(seed["tag"]) is str and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", seed["tag"]) and
            seed["version"] == f"dawnc {seed['tag'][1:]} (native)" and
            version_key(seed["tag"][1:]) <= version_key(release["version"]),
            "invalid bootstrap seed identity")
    require(type(seed["commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", seed["commit"]) and
            is_sha(seed["sha256"]) and type(seed["size"]) is int and seed["size"] > 0 and
            is_build_id(seed["build_id"]), "invalid bootstrap seed identity")
    for name in ("std", "runtime"):
        item = bootstrap[name]
        shape(item, "algorithm commit sha256", "bootstrap " + name)
        require(type(item["algorithm"]) is str and is_sha(item["sha256"]) and
                item["commit"] == seed["commit"], "bootstrap seed pair differs")
    parent = bootstrap["parent_receipt_sha256"]
    require(parent is None or is_sha(parent), "invalid parent receipt digest")
    recipe = info["recipe"]
    shape(recipe, "inputs_sha256 toolchain_sha256 recipe_sha256", "recipe")
    require(all(is_sha(value) for value in recipe.values()), "invalid recipe digest")
    proof = info["proof"]
    shape(proof, "name sha256", "proof")
    require(proof["name"] == "native-bootstrap.json" and is_sha(proof["sha256"]), "invalid proof reference")
    reference = info["jvm_reference"]
    shape(reference, "name kind sha256 commit jdk_equivalence_sha256", "JVM reference")
    require((reference["name"], reference["kind"]) == ("dawn-selfhost.jar", "jvm-jar") and
            reference["commit"] == release["commit"] and is_sha(reference["sha256"]) and
            is_sha(reference["jdk_equivalence_sha256"]), "JVM reference identity differs")
    return info


def verify_elf(data):
    require(len(data) >= 64 and data[:7] == b"\x7fELF\x02\x01\x01",
            "expected a little-endian ELF64 executable")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    kind, machine, version, _, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, _ = header
    require(kind in (2, 3) and machine == 62 and version == 1 and ehsize == 64,
            "expected a Linux x86_64 ELF executable")
    require(phnum > 0 and phsize == 56 and phoff + phsize * phnum <= len(data),
            "truncated ELF program headers")
    require(shnum > 0 and shsize == 64 and shoff + shsize * shnum <= len(data),
            "truncated ELF section headers")
    for index in range(phnum):
        ptype, _, offset, _, _, size, _, _ = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phsize)
        require(offset + size <= len(data), "truncated ELF segment")
        require(ptype != 3, "native release must not have an ELF interpreter")
        if ptype == 2:
            require(size % 16 == 0, "invalid ELF dynamic section")
            for pos in range(offset, offset + size, 16):
                require(struct.unpack_from("<qQ", data, pos)[0] != 1,
                        "native release must not need shared libraries")
    for index in range(shnum):
        _, stype, _, _, offset, size, _, _, _, _ = struct.unpack_from("<IIQQQQIIQQ", data, shoff + index * shsize)
        require(stype == 8 or offset + size <= len(data), "truncated ELF section")


def verify_payload(payload, checksum, info):
    digest = hashlib.sha256(payload).hexdigest()
    require(checksum.decode("ascii") == f"{digest}  {ASSET}\n", "native checksum mismatch")
    require(info["native"]["sha256"] == digest and info["native"]["size"] == len(payload),
            "metadata native SHA-256 or size mismatch")
    verify_elf(payload)


def install(tag=None, prefix=None, from_dir=None):
    require((platform.system(), platform.machine()) == ("Linux", "x86_64"),
            "unsupported platform: native installation requires Linux x86_64; "
            "select the explicit JVM toolchain for other platforms")
    require(not from_dir or tag, "--from-dir requires --tag")
    tag = resolve_tag(tag)
    base = REPOSITORY + "/releases/download/" + tag

    def fetch(name):
        return (Path(from_dir) / name).read_bytes() if from_dir else download(base + "/" + name)

    info = metadata_for(fetch(METADATA), tag)
    payload, checksum = fetch(ASSET), fetch(ASSET + ".sha256")
    verify_payload(payload, checksum, info)
    destination = Path(prefix or Path.home() / ".local").absolute() / "bin"
    destination.mkdir(parents=True, exist_ok=True)
    # Refuse a bin symlink. Replacing a dawn symlink below replaces its directory
    # entry, leaving the old link's target (including a checkout) untouched.
    directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with tempfile.TemporaryDirectory(prefix=".dawn-install-", dir=destination) as work:
            candidate = Path(work) / "dawn"
            with candidate.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fchmod(stream.fileno(), 0o755)
                os.fsync(stream.fileno())
            env = {"PATH": "/nonexistent", "HOME": work, "LANG": "C.UTF-8"}
            version = subprocess.run([str(candidate), "--version"], env=env,
                                     capture_output=True, timeout=30, check=True)
            expected = f"dawnc {info['release']['version']} (native) {info['native']['build_id'][:15]}\n"
            require(version.stdout.decode() == expected and not version.stderr,
                    "native version does not match metadata")
            listing = subprocess.run([str(candidate), "version", "-m", str(candidate)], env=env,
                                     capture_output=True, timeout=30, check=True)
            digests = re.findall(rb"^\tbuild\t(b1:[0-9a-f]{64})$", listing.stdout, re.M)
            require(digests == [info["native"]["build_id"].encode()] and not listing.stderr,
                    "native build id does not match metadata")
            os.replace(candidate, "dawn", dst_dir_fd=directory_fd)
        return destination / "dawn"
    finally:
        os.close(directory_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="fixed release tag; omitted resolves latest once")
    parser.add_argument("--prefix", help="install prefix (default: ~/.local)")
    parser.add_argument("--from-dir", help="use an already downloaded release set with --tag")
    args = parser.parse_args()
    try:
        target = install(args.tag, args.prefix, args.from_dir)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Installed {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

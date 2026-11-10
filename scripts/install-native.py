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


def metadata_for(raw, tag):
    info = json.loads(raw)
    require(info["schema"] == 1, "unsupported toolchain metadata schema")
    require(info["tag"] == tag and info["version"] == tag[1:], "metadata tag/version mismatch")
    require(re.fullmatch(r"[0-9a-f]{40}", info["commit"]) is not None,
            "metadata needs a full source commit")
    require(info["host_target"] == "linux-x86_64" and info["install_path"] == "bin/dawn",
            "metadata target/install path mismatch")
    native, builder = info["native"], info["builder"]
    require(native["name"] == ASSET and builder["name"] == "dawn-selfhost.jar",
            "metadata asset name mismatch")
    for item in (native, builder):
        require(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None,
                "metadata needs a SHA-256")
        require(re.fullmatch(r"b1:[0-9a-f]{64}", item["source_manifest"]) is not None,
                "metadata needs a source manifest digest")
    require(builder["version"] == info["version"], "metadata builder version mismatch")
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
    require(info["native"]["sha256"] == digest, "metadata native SHA-256 mismatch")
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
            expected = f"dawnc {info['version']} (native) {info['native']['source_manifest'][:15]}\n"
            require(version.stdout.decode() == expected and not version.stderr,
                    "native version does not match metadata")
            listing = subprocess.run([str(candidate), "version", "-m", str(candidate)], env=env,
                                     capture_output=True, timeout=30, check=True)
            digests = re.findall(rb"^\tbuild\t(b1:[0-9a-f]{64})$", listing.stdout, re.M)
            require(digests == [info["native"]["source_manifest"].encode()] and not listing.stderr,
                    "native source manifest does not match metadata")
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

#!/usr/bin/env python3
"""Hold the cache boundary with tiny wheels, without downloading CUDA or a GPU.

The fixture is installed by real pip into real virtual environments. An empty
index makes a successful warm install evidence that downloads were unnecessary;
altered pins, wheel bytes and installed metadata must all fail even with a stamp.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
NAMES = ("nvidia-cuda-tileiras", "nvidia-nvvm", "nvidia-cuda-nvcc")
VERSION = "1.2.3"


def wheel(directory: Path, name: str) -> Path:
    package = name.replace("-", "_")
    result = directory / f"{package}-{VERSION}-py3-none-any.whl"
    info = f"{package}-{VERSION}.dist-info"
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr(f"{info}/METADATA", (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {VERSION}\n"
        ))
        archive.writestr(f"{info}/WHEEL", (
            "Wheel-Version: 1.0\nGenerator: cache-contract\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n"
        ))
        archive.writestr(f"{info}/RECORD", "")
        if name == NAMES[0]:
            binary = zipfile.ZipInfo("nvidia/cu13/bin/tileiras")
            binary.external_attr = 0o100755 << 16
            archive.writestr(binary, f"#!/bin/sh\necho 'fixture tileiras V{VERSION}'\n")
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tileiras cache contract ") as temporary:
        root = Path(temporary)
        installer = root / "install-tileiras.sh"
        shutil.copyfile(HERE / "install-tileiras.sh", installer)
        source = root / "index"
        source.mkdir()
        wheels = [wheel(source, name) for name in NAMES]
        pin = f"tileiras {VERSION}\n" + "".join(
            f"wheel {name}=={VERSION} sha256={hashlib.sha256(path.read_bytes()).hexdigest()}\n"
            for name, path in zip(NAMES, wheels)
        )
        toolchain = root / "toolchain.txt"
        toolchain.write_text(pin)
        cache = root / "wheels"
        dest = root / "cold"
        env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_CONFIG_FILE": os.devnull,
               "PIP_INDEX_URL": "https://network-must-not-be-used.invalid"}
        env.pop("PIP_FIND_LINKS", None)
        env.pop("PIP_EXTRA_INDEX_URL", None)

        def run(label: str, target: Path = dest, *, succeeds: bool = True,
                find_links: bool = False, default_cache: bool = False,
                diagnostic: str = "") -> None:
            command = ["bash", str(installer), str(target)]
            if not default_cache:
                command.append(str(cache))
            settings = {**env}
            if find_links:
                settings["PIP_FIND_LINKS"] = source.as_uri()
            result = subprocess.run(command, env=settings, text=True,
                                    capture_output=True, timeout=90)
            if (result.returncode == 0) != succeeds:
                raise AssertionError(f"{label}: exit {result.returncode}\n{result.stderr}")
            if diagnostic and diagnostic not in result.stderr:
                raise AssertionError(f"{label}: wrong refusal\n{result.stderr}")
            if succeeds:
                binary = Path(result.stdout.strip())
                assert binary.is_file(), (label, result.stdout)
            print(f"PASS {label}", flush=True)

        run("cold download from fixture index", find_links=True)
        assert len(list(cache.glob("*.whl"))) == 3
        run("warm wheel cache into fresh venv without an index", root / "warm")
        run("reuse installed venv after revalidation")

        cached = cache / wheels[0].name
        original = cached.read_bytes()
        cached.write_bytes(original + b"corrupted")
        run("cached bytes corruption overrides matching stamp", succeeds=False,
            diagnostic="not the one toolchain.txt pins")
        cached.write_bytes(original)

        digest = hashlib.sha256(original).hexdigest()
        toolchain.write_text(pin.replace(digest, "0" * 64))
        run("altered pinned hash", succeeds=False,
            diagnostic="not the one toolchain.txt pins")
        toolchain.write_text(pin.replace(f"{NAMES[0]}=={VERSION}", f"{NAMES[0]}==9.9.9"))
        run("altered pinned wheel version", succeeds=False,
            diagnostic="No matching distribution found")
        toolchain.write_text(pin.replace(f"tileiras {VERSION}\n", "tileiras 1.2.4\n"))
        run("altered assembler version", succeeds=False,
            diagnostic="tileiras is not the pinned 1.2.4")
        toolchain.write_text(pin)

        metadata = next(dest.glob("lib/python*/site-packages/nvidia_cuda_tileiras-*/METADATA"))
        original_metadata = metadata.read_text()
        metadata.write_text(original_metadata.replace(f"Version: {VERSION}", "Version: 9.9.9"))
        run("installed version corruption overrides matching stamp", succeeds=False,
            diagnostic=f"is 9.9.9, expected {VERSION}")
        metadata.write_text(original_metadata)

        local = root / "local"
        shutil.copytree(cache, local / ".wheels")
        run("one-argument local interface retains its wheel cache", local, default_cache=True)
        assert len(list((local / ".wheels").glob("*.whl"))) == 3
        print("OK: tileiras cache contract (9 cases)")


if __name__ == "__main__":
    main()

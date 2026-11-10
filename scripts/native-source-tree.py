#!/usr/bin/env python3
"""Capture the compiler's portable source project for native bootstrap checks.

The JVM compiler project declares ASM and Coursier. Native self-compilation
uses the same source files and source dependencies in an explicit project
without Java dependencies; it must not bypass native capability checks.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
import tomllib


def capture(destination):
    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / "selfhost/dawn.toml").read_text())
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(root / "selfhost/src", destination / "src")
    (destination / "deps").mkdir()
    lines = ['schema = 1', 'name = "selfhost"', '', '[deps]']
    for name, path in manifest["deps"].items():
        assert isinstance(path, str) and (root / "selfhost" / path).is_dir(), (name, path)
        (destination / "deps" / name).symlink_to((root / "selfhost" / path).resolve(),
                                                target_is_directory=True)
        lines.append(f'{name} = {json.dumps("deps/" + name)}')
    (destination / "dawn.toml").write_text("\n".join(lines) + "\n")
    return destination / "src/nmain.dawn"


def selftest():
    manifests = []
    with tempfile.TemporaryDirectory(prefix="native-source-capture-") as work:
        for name in ("first", "second"):
            root = Path(work) / name
            (root / "fixture_helper_tools").mkdir(parents=True)
            (root / "selfhost/src").mkdir(parents=True)
            (root / "dep").mkdir()
            source = b"pub fn main() -> Unit !io = ()\n"
            (root / "selfhost/src/nmain.dawn").write_bytes(source)
            (root / "selfhost/dawn.toml").write_text(
                'schema = 1\nname = "selfhost"\n[deps]\np = "../dep"\n')
            script = root / "fixture_helper_tools/capture.py"
            with patch.dict(capture.__globals__, {"__file__": str(script)}):
                entry = capture(Path(work) / ("captured-" + name))
            assert entry.read_bytes() == source
            manifests.append((entry.parents[1] / "dawn.toml").read_bytes())
        assert manifests[0] == manifests[1], "captured manifest depends on checkout location"
    print("OK portable compiler source capture is independent of checkout location")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        print(capture(sys.argv[1]))

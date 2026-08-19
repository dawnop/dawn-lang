#!/usr/bin/env python3
"""Negative controls for gallery discovery, compiler authority, and cleanup."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = Path(__file__).resolve().parent
FIXTURES = CONTRACT / "fixtures"
TARGET = "examples/regression/entry.dawn"


def registry(stdout: str) -> dict[str, object]:
    return {
        "schema": 1,
        "targets": [
            {
                "target": TARGET,
                "cases": [
                    {
                        "name": "selftest",
                        "argv": [],
                        "stdin": "",
                        "stdout": stdout,
                        "stderr": "",
                        "exit": 0,
                    }
                ],
            }
        ],
    }


def install_contract(root: Path, stdout: str) -> Path:
    target_dir = root / "scripts/example-main-contract"
    target_dir.mkdir(parents=True)
    shutil.copy2(CONTRACT / "run.py", target_dir / "run.py")
    (target_dir / "registry.json").write_text(
        json.dumps(registry(stdout), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source = root / TARGET
    source.parent.mkdir(parents=True)
    return source


def install_real_toolchain(root: Path) -> None:
    jar = ROOT / "build/dawn-selfhost.jar"
    if not jar.is_file():
        raise AssertionError(f"missing selfhost toolchain: {jar}")
    (root / "bin").mkdir()
    shutil.copy2(ROOT / "bin/dawn", root / "bin/dawn")
    (root / "build").mkdir()
    (root / "build/dawn-selfhost.jar").symlink_to(jar)
    (root / "std").symlink_to(ROOT / "std", target_is_directory=True)


def run_contract(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "scripts/example-main-contract/run.py", *argv],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )


def require_green(name: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise AssertionError(
            f"{name} should pass; stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    print(f"PASS  {name}")


def require_red(
    name: str, result: subprocess.CompletedProcess[str], fragment: str
) -> None:
    output = result.stdout + result.stderr
    if result.returncode == 0 or fragment not in output:
        raise AssertionError(
            f"{name} should fail with {fragment!r}; exit={result.returncode}; "
            f"output={output!r}"
        )
    print(f"PASS  {name} turns the contract red")


def compiler_controls() -> None:
    with tempfile.TemporaryDirectory(prefix="dawn-example-main-compiler-") as raw:
        root = Path(raw)
        source = install_contract(root, "pub fn main(|inner 7\n")
        install_real_toolchain(root)

        shutil.copy2(FIXTURES / "literals.dawn", source)
        require_green("raw string and nested interpolation", run_contract(root))

        shutil.copy2(FIXTURES / "no_main.dawn", source)
        require_red("missing main", run_contract(root), "has no pub fn main()")

        shutil.copy2(FIXTURES / "multiple_main.dawn", source)
        require_red(
            "multiple main declarations",
            run_contract(root),
            "function `main` is defined twice",
        )


def targeted_mode_controls() -> None:
    """`--target` is how run-diff settlement holds a declaration to the pin.

    The shape that must red is the ab116b1 incident: the example's output
    changed (and the transcript diff was declared), but registry.json still
    pins the old output. The clean shape -- pin matches the head output --
    must stay green, and a target the registry does not know must be named
    rather than silently skipped.
    """
    with tempfile.TemporaryDirectory(prefix="dawn-example-main-target-") as raw:
        root = Path(raw)
        source = install_contract(root, "pub fn main(|inner 7\n")
        install_real_toolchain(root)
        shutil.copy2(FIXTURES / "literals.dawn", source)

        require_green("targeted run of a current pin", run_contract(root, "--target", TARGET))

        require_red(
            "targeted run of an unregistered target",
            run_contract(root, "--target", "examples/regression/other.dawn"),
            "no registry entry pins",
        )

        require_red(
            "targeted mode usage error",
            run_contract(root, "--bogus"),
            "usage:",
        )

    with tempfile.TemporaryDirectory(prefix="dawn-example-main-stale-") as raw:
        root = Path(raw)
        source = install_contract(root, "the output this example printed last release\n")
        install_real_toolchain(root)
        shutil.copy2(FIXTURES / "literals.dawn", source)

        require_red(
            "targeted run against a stale pin (the ab116b1 shape)",
            run_contract(root, "--target", TARGET),
            "stdout expected",
        )


def process_alive(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


def background_cleanup_control() -> None:
    with tempfile.TemporaryDirectory(prefix="dawn-example-main-background-") as raw:
        root = Path(raw)
        source = install_contract(root, "ok\n")
        shutil.copy2(FIXTURES / "literals.dawn", source)
        (root / "bin").mkdir()
        launcher = root / "bin/dawn"
        shutil.copy2(FIXTURES / "background_launcher.py", launcher)
        launcher.chmod(0o755)

        require_green("normal-exit launcher with a background descendant", run_contract(root))
        pid_file = root / "background.pid"
        if not pid_file.is_file():
            raise AssertionError("background launcher did not record its child")
        process_id = int(pid_file.read_text(encoding="ascii"))
        deadline = time.monotonic() + 2
        while process_alive(process_id) and time.monotonic() < deadline:
            time.sleep(0.01)
        if process_alive(process_id):
            raise AssertionError(f"background descendant {process_id} survived cleanup")
        print("PASS  normal-return cleanup leaves no background descendant")


def main() -> int:
    compiler_controls()
    targeted_mode_controls()
    background_cleanup_control()
    print("OK: example main contract self-test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

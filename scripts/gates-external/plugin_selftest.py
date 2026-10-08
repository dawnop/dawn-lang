#!/usr/bin/env python3
"""Self-test of the external backend plugin loading in runner.py.

Why this exists: only the local backend ships in this repository; any other
backend is a plugin loaded from DAWN_GATES_BACKENDS or the gitignored
backends.local. Nothing else in the repository exercises that path, and a
loader that silently fell back to the local backend would send a run to the
wrong place. A fake backend in a temp directory proves: it is found through
the environment variable and through the config file, a name without a file is
refused, a name that is not a plain identifier is refused, and a full runner
invocation reaches its create()/run_job().
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAKE = '''
RESUMABLE = False

class Fake:
    def __init__(self, ctx):
        self.ctx = ctx
    def prepare(self): pass
    def cleanup(self): pass
    def toolchain(self): return {}
    def finished(self): return {}
    def run_job(self, job, artifacts):
        (self.ctx["out"] / "fake-ran.txt").open("a").write(job["id"] + "\\n")
        return {"steps": None, "ok": False}

def create(ctx):
    return Fake(ctx)
'''


def main():
    failures = []
    with tempfile.TemporaryDirectory(prefix="gates-plugin-") as tmp:
        plugins = Path(tmp) / "plugins"
        plugins.mkdir()
        (plugins / "backend_fake.py").write_text(FAKE)
        os.environ.pop("DAWN_GATES_BACKENDS", None)
        import runner

        # 1. not found without any configuration
        try:
            runner.load_backend("fake")
            failures.append("a plugin was found with no DAWN_GATES_BACKENDS")
        except ImportError:
            pass
        # 2. found through the environment variable
        os.environ["DAWN_GATES_BACKENDS"] = f"{Path(tmp) / 'nothing'}{os.pathsep}{plugins}"
        module = runner.load_backend("fake")
        if not hasattr(module, "create"):
            failures.append("the plugin module has no create()")
        # 3. the shipped backend still wins and loads
        if runner.load_backend("local").__name__ != "backend_local":
            failures.append("the local backend did not load")
        # 4. names that are not plain identifiers never reach the filesystem
        for bad in ("../x", "Fake", "a/b", ""):
            try:
                runner.load_backend(bad)
                failures.append(f"backend name {bad!r} was accepted")
            except ImportError:
                pass
        # 5. a missing name is refused
        try:
            runner.load_backend("absent")
            failures.append("a backend with no file was found")
        except ImportError:
            pass
        # 6. the config file route, in a copy of the loader's directory
        os.environ.pop("DAWN_GATES_BACKENDS")
        config = HERE / "backends.local"
        if config.exists():
            print("skip config-file case: backends.local exists")
        else:
            config.write_text(f"# local\n{plugins}\n")
            try:
                sys.modules.pop("backend_fake", None)
                runner.load_backend("fake")
            except ImportError:
                failures.append("the plugin was not found through backends.local")
            finally:
                config.unlink()
        # 7. end to end: runner.py with --backend fake reaches the plugin
        repo = HERE.parents[1]
        out = Path(tmp) / "out"
        env = dict(os.environ, DAWN_GATES_BACKENDS=str(plugins))
        done = subprocess.run(
            [sys.executable, "-B", str(HERE / "runner.py"), "--sha", "HEAD", "--backend", "fake",
             "--out", str(out), "--repo", str(repo), "--only", "tree-policy", "--jobs", "1"],
            capture_output=True, text=True, env=env)
        ran = (out / "fake-ran.txt")
        if not ran.is_file() or "tree-policy" not in ran.read_text():
            failures.append(f"runner.py did not reach the fake backend (exit {done.returncode}): "
                            f"{(done.stdout + done.stderr)[-400:]}")
        done = subprocess.run(
            [sys.executable, "-B", str(HERE / "runner.py"), "--sha", "HEAD", "--backend", "absent",
             "--out", str(Path(tmp) / "out2"), "--repo", str(repo)],
            capture_output=True, text=True, env=env)
        if done.returncode != 2 or "no backend" not in done.stderr:
            failures.append(f"an unknown backend was not refused with exit 2 (got {done.returncode})")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print("OK: plugin loading self-test, env var, config file, refusals, end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())

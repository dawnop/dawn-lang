#!/usr/bin/env python3
"""Pin test-only engines and extensions; production always loads the system soname.

Every cache hit is verified. Missing or corrupt assets fail, never skip. The
external gate input pack supplies the same archives without network access.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.parse
import zipfile

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "fixtures.lock.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(key, cache):
    item = LOCK[key]
    name = urllib.parse.unquote(item["url"].rsplit("/", 1)[1])
    packed = os.environ.get("DAWN_TEST_DOWNLOADS")
    path = Path(packed) / name if packed else cache / name
    if not path.exists() and not packed:
        cache.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        subprocess.run(["curl", "-fsSL", "--retry", "3", item["url"], "-o", partial], check=True)
        assert digest(partial) == item["sha256"], "fixture archive checksum"
        partial.replace(path)
    assert path.is_file(), f"required {key} fixture unavailable: {path}"
    assert digest(path) == item["sha256"], f"{key} fixture checksum"
    return path


def prepare_engine(cache, work, key):
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive(key, cache)) as z:
        for name in ["sqlite3.c", "sqlite3.h", "sqlite3ext.h"]:
            member = next(n for n in z.namelist() if n.endswith("/" + name))
            (work / name).write_bytes(z.read(member))
    assert digest(work / "sqlite3.c") == LOCK[key]["source_sha256"], "SQLite source digest"


def prepare(cache, work):
    prepare_engine(cache, work, "sqlite")
    with zipfile.ZipFile(archive("simple", cache)) as z:
        member = next(n for n in z.namelist() if n.endswith("/libsimple.so") or n == "libsimple.so")
        (work / "libsimple.so").write_bytes(z.read(member))
    return work / "libsimple.so"

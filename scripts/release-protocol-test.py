#!/usr/bin/env python3
"""Contract tests for the schema 2 release protocol.

Why a fake `gh` and a fake compiler: the protocol's interesting behaviour is
what happens when an upload is cut off, when a name already exists with other
bytes, when a release is sealed and incomplete. None of that can be provoked on
demand against the real service, and none of it needs a real compiler. The fake
compiler is a tiny static ELF that answers `--version` and `version -m` like
dawnc does; everything the protocol checks (digests, sizes, build ids, ELF
shape) is a property of those bytes.

Every refusal below is a control: it must fail with the named rejection, and
the pristine package must pass first, so a green run cannot mean "nothing was
looked at".
"""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import native_release as nr  # noqa: E402
import native_seed.contract as c  # noqa: E402
import release_publish as rp  # noqa: E402

installer = nr.installer
ROOT = HERE.parent
LOCK = ROOT / "scripts/native-seed-candidate-v0.104.0.json"
passed = 0


def ok(condition, name):
    global passed
    if not condition:
        raise AssertionError(name)
    passed += 1
    print("OK  " + name, flush=True)


def refuses(name, code, thunk):
    try:
        thunk()
    except (c.Rejected, ValueError, KeyError, TypeError) as exc:
        ok(code in str(exc), f"{name} is refused ({code})")
        return
    raise AssertionError(f"{name} was accepted")


FAKE = r'''
#include <stdio.h>
#include <string.h>
int main(int n, char **v) {
  if (n == 2 && !strcmp(v[1], "--version")) { puts("dawnc " VERSION " (native) " SHORT); return 0; }
  if (n == 4 && !strcmp(v[1], "version") && !strcmp(v[2], "-m")) { printf("\tbuild\t" FULL "\n"); return 0; }
  return 2;
}
'''


def fake_compiler(work, name, version, build):
    source = work / (name + ".c")
    source.write_text(FAKE)
    binary = work / name
    subprocess.run(["cc", "-static", "-O0", f'-DVERSION="{version}"',
                    f'-DSHORT="{build[:15]}"', f'-DFULL="{build}"', str(source), "-o", str(binary)],
                   check=True, capture_output=True)
    return binary


class FakeGh:
    """A release store. It can create, list, download and upload, and nothing else:
    there is deliberately no delete and no replace, so no code path can use one."""

    def __init__(self):
        self.releases = {}
        self.uploads = []
        self.fail_at = None
        self.cut_off = False
        self.late = {}

    def exists(self, tag):
        return tag in self.releases

    def create(self, tag):
        assert tag not in self.releases
        self.releases[tag] = {}

    def assets(self, tag):
        return sorted(self.releases[tag]) + sorted(self.late.get(tag, {}))

    def download(self, tag, name):
        store = {**self.releases[tag], **self.late.get(tag, {})}
        return store[name]

    def upload(self, tag, path):
        name = Path(path).name
        assert name not in self.releases[tag], "an upload would replace an existing asset"
        self.uploads.append(name)
        if self.fail_at is not None and len(self.uploads) == self.fail_at:
            if self.cut_off:
                self.late.setdefault(tag, {})[name] = Path(path).read_bytes()
            raise subprocess.CalledProcessError(1, "gh release upload")
        self.releases[tag][name] = Path(path).read_bytes()


def build_package(work):
    version = nr.source_version()
    tag = "v" + version
    a = fake_compiler(work, "stage-a", version, "b1:" + "a" * 64)
    b = fake_compiler(work, "stage-b", version, "b1:" + "b" * 64)
    jar = work / "dawn-selfhost.jar"
    jar.write_bytes(b"PK jar bytes for the contract test\n")
    api = work / "api.json"
    api.write_text('{"modules": []}\n')
    diff = work / "diff.md"
    diff.write_text("# diff\n")
    out = work / "package"
    nr.produce(type("A", (), dict(lock=str(LOCK), native=str(b), builder=str(a), jdk21_jar=str(jar),
                                  jdk26_jar=str(jar), pub_api=str(api), pub_api_diff=str(diff),
                                  cold_sha256="c" * 64, expect_tag=tag, skip_smoke=True, out=str(out))))
    return tag, out


def read(directory, name):
    return (directory / name).read_bytes()


def write_info(directory, info, fix_proof=True):
    """Rewrite metadata the way an attacker with a perfect printer would: still canonical."""
    (directory / installer.METADATA).write_bytes(nr.canonical(info))


def main():
    with tempfile.TemporaryDirectory(prefix="release-protocol-") as temporary:
        work = Path(temporary)
        tag, good = build_package(work)
        info = json.loads(read(good, installer.METADATA))
        ok(info["schema"] == 2 and sorted(p.name for p in good.iterdir()) == sorted(nr.UPLOAD_ORDER),
           "the producer writes schema 2 and exactly the nine assets")
        ok(nr.UPLOAD_ORDER[-1] == installer.METADATA, "the metadata is the last asset to be uploaded")
        nr.aggregate(good, tag, LOCK)
        ok(True, "the pristine package passes the aggregate check against the seed lock")

        # The workflow passes relative paths; the producer runs the binaries with
        # an empty PATH, so a relative name must not be looked up there.
        previous = os.getcwd()
        os.chdir(work)
        try:
            nr.produce(type("A", (), dict(
                lock=str(LOCK), native="stage-b", builder="stage-a", jdk21_jar="dawn-selfhost.jar",
                jdk26_jar="dawn-selfhost.jar", pub_api="api.json", pub_api_diff="diff.md",
                cold_sha256="c" * 64, expect_tag=tag, skip_smoke=True, out="relative-package")))
        finally:
            os.chdir(previous)
        ok(read(work / "relative-package", installer.METADATA) == read(good, installer.METADATA),
           "the producer accepts relative paths and writes the same metadata")

        def mutated(name, change, code, lock=None, rewrite_proof=False):
            directory = work / ("m-" + name.replace(" ", "-").replace("/", "-"))
            shutil.copytree(good, directory)
            change(directory)
            refuses(name, code, lambda: nr.aggregate(directory, tag, lock))

        def meta(key, value, then=None):
            def change(directory):
                value_info = copy.deepcopy(info)
                target = value_info
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                write_info(directory, value_info)
            return change

        for key, value, code in (
                ("schema", 1, "release-metadata"), ("schema", 999, "release-metadata"),
                ("schema", True, "release-metadata"),
                ("native.kind", "jvm-jar", "release-metadata"),
                ("native.stage", "C", "release-metadata"),
                ("native.target", "aarch64-unknown-linux-gnu", "release-metadata"),
                ("native.name", "dawn-selfhost.jar", "release-metadata"),
                ("builder.name", "dawn-selfhost.jar", "release-metadata"),
                ("builder.kind", "jvm-jar", "release-metadata"),
                ("builder.kind", "unknown", "release-metadata"),
                ("builder.stage", "S", "release-metadata"),
                ("builder.version", "0.0.1", "release-metadata"),
                ("bootstrap.parent_receipt_sha256", "bad", "release-metadata"),
                ("bootstrap.std.commit", "0" * 40, "release-metadata"),
                ("jvm_reference.commit", "0" * 40, "release-metadata"),
                ("release.tag", "v0.0.1", "release-metadata"),
                ("release.commit", "abc", "release-metadata"),
                ("native.size", info["native"]["size"] + 1, "release-payload"),
                ("native.sha256", "0" * 64, "release-payload"),
                ("native.build_id", "b1:" + "0" * 64, "release-proof"),
                ("bootstrap.seed.sha256", "0" * 64, "release-proof"),
                ("bootstrap.parent_receipt_sha256", "0" * 64, "release-proof"),
                ("builder.sha256", "0" * 64, "release-proof"),
                ("recipe.recipe_sha256", "0" * 64, "release-proof"),
                ("proof.sha256", "0" * 64, "release-proof")):
            mutated(f"metadata {key}={value!r}"[:70], meta(key, value), code)

        mutated("duplicate JSON key", lambda d: (d / installer.METADATA).write_bytes(
            read(d, installer.METADATA).rstrip()[:-1] + b',"schema":2}'), "release-metadata")
        mutated("non-canonical metadata", lambda d: (d / installer.METADATA).write_bytes(
            json.dumps(info, indent=2).encode()), "release-metadata")
        for name, code in ((nr.ASSET, "release-payload"), (nr.ASSET + ".sha256", "release-payload"),
                           (nr.JAR, "release-jar"), (nr.JAR + ".sha256", "release-jar"),
                           (nr.PROOF, "release-proof")):
            mutated("tampered " + name, lambda d, n=name: (d / n).write_bytes(read(d, n) + b" "), code)
        for name in nr.UPLOAD_ORDER:
            mutated("missing " + name, lambda d, n=name: (d / n).unlink(), "release-assets")
        mutated("an extra asset", lambda d: (d / "extra.txt").write_text("x"), "release-assets")
        mutated("the seed lock differs", lambda d: None, "release-lineage",
                lock=_other_lock(work, "sequence-free"))

        # ---- the installer consumes the same package and refuses the same lies
        with tempfile.TemporaryDirectory(prefix="release-install-") as prefix:
            installed = installer.install(tag, prefix, str(good))
            ok(installed.read_bytes() == read(good, nr.ASSET), "the installer takes the nine-asset package")
            old = installed.read_bytes()
            for name, change in (("schema 1", meta("schema", 1)), ("build id", meta("native.build_id", "b1:" + "0" * 64))):
                bad = work / ("i-" + name.replace(" ", "-"))
                shutil.copytree(good, bad)
                change(bad)
                try:
                    installer.install(tag, prefix, str(bad))
                except (ValueError, KeyError, TypeError, subprocess.SubprocessError):
                    ok(installed.read_bytes() == old, f"the installer refuses {name} and keeps the old binary")
                else:
                    raise AssertionError("installer accepted " + name)

        # ---- the publisher: states, interruption points, no replacement
        def stage(gh, directory=good):
            logs = []
            rp.publish(gh, tag, directory, patience=1, delay=0, log=logs.append)
            return logs

        gh = FakeGh()
        logs = stage(gh)
        ok(gh.uploads == list(nr.UPLOAD_ORDER) and any(line.startswith("R0") for line in logs),
           "R0: creates the release and uploads in the fixed order, metadata last")
        before = dict(gh.releases[tag])
        gh.uploads.clear()
        logs = stage(gh)
        ok(gh.uploads == [] and any(line.startswith("R2") for line in logs) and gh.releases[tag] == before,
           "R2: a sealed, complete release is only verified; nothing is uploaded")

        for k in range(1, len(nr.UPLOAD_ORDER) + 1):
            gh = FakeGh()
            gh.fail_at = k
            try:
                stage(gh)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("an upload failure was swallowed")
            partial = set(gh.releases[tag])
            ok(installer.METADATA not in partial, f"interruption at upload {k} never leaves a sealed release")
            gh.fail_at = None
            gh.uploads.clear()
            stage(gh)
            ok(gh.releases[tag] == before and len(set(gh.uploads)) == len(gh.uploads) and
               set(gh.uploads).isdisjoint(partial),
               f"re-run after interruption at upload {k} converges to the same assets without re-uploading any")

        gh = FakeGh()
        gh.fail_at, gh.cut_off = 3, True
        stage(gh)
        ok(gh.releases[tag] == before or {**gh.releases[tag], **gh.late[tag]} == before,
           "a cut-off upload that completes late is recognised and compared, not re-uploaded")

        gh = FakeGh()
        gh.fail_at = 2
        try:
            stage(gh)
        except subprocess.CalledProcessError:
            ok(True, "a failed upload that never appears fails the run")

        gh = FakeGh()
        stage(gh)
        gh.releases[tag][nr.ASSET] = b"different bytes"
        refuses("E2 a published asset with other bytes", "published-differs", lambda: stage(gh))
        ok(gh.releases[tag][nr.ASSET] == b"different bytes", "E2 leaves the published bytes untouched")

        gh = FakeGh()
        stage(gh)
        del gh.releases[tag][nr.PROOF]
        refuses("E1 a sealed release with a missing asset", "published-sealed-incomplete", lambda: stage(gh))
        ok(nr.PROOF not in gh.releases[tag], "E1 does not mint the missing asset")

        gh = FakeGh()
        stage(gh)
        gh.late[tag] = {nr.ASSET: read(good, nr.ASSET)}
        refuses("E3 a contract name published twice", "published-duplicate", lambda: stage(gh))

        gh = FakeGh()
        gh.create(tag)
        gh.releases[tag]["historical-extra.txt"] = b"older release carried it"
        stage(gh)
        ok("historical-extra.txt" in gh.releases[tag], "E4 an unrelated historical asset is tolerated and kept")

        gh = FakeGh()
        gh.create(tag)
        gh.releases[tag][nr.API] = b'{"modules": ["newer"]}\n'
        gh.releases[tag][nr.API_DIFF] = b"# newer diff\n"
        stage(gh)
        ok(gh.releases[tag][nr.API] == b'{"modules": ["newer"]}\n', "the published pub-API report is adopted, not replaced")

        gh = FakeGh()
        gh.create(tag)
        gh.releases[tag][nr.API] = b"not json"
        refuses("an adopted report that is not JSON", "published-report", lambda: stage(gh))

        tampered = work / "tampered-package"
        shutil.copytree(good, tampered)
        (tampered / nr.PROOF).write_bytes(b"{}")
        gh = FakeGh()
        refuses("publishing a package that fails the aggregate check", "release-", lambda: stage(gh, tampered))
        ok(not gh.releases, "nothing is created for a package that does not pass the aggregate check")
    print(f"OK: {passed} release protocol assertions")


def _other_lock(work, label):
    value = json.loads(LOCK.read_bytes())
    value["registration"]["evidence_sha256"] = "0" * 64
    path = work / f"lock-{label}.json"
    path.write_bytes(nr.canonical(value))
    return path


if __name__ == "__main__":
    main()

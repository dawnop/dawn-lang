#!/usr/bin/env python3
"""Publish the nine release assets without ever overwriting or deleting one.

Why this exists: the publish step used to be one batch upload with the
overwrite flag, so a re-run converged by replacing every asset, including the
bytes a seed lock or an installer may already trust. Now an asset that exists
is compared, never replaced, and nothing here deletes anything. The state
machine is docs/native-seed-cutover-design.md section 2.5.

The pivot is the order. `dawn-toolchain.json` is uploaded last and is the seal:
before it exists every consumer refuses the release (no metadata), so a
half-published release is invisible to the trust chain. After it exists the
release is sealed and this tool can only verify it.

States on entry, from the release's asset listing:
  R0  no release            create it, then R1
  R1  not sealed            per asset, in the fixed order: missing -> upload;
                            present -> compare; all present -> verify
  R2  sealed and complete   verify only, upload nothing
  E1  sealed, name missing  fail (re-uploading would mint a trusted asset)
  E2  bytes differ          fail; the maintainer decides, usually a new tag
  E3  a contract name twice fail

Two asset classes. The identity assets (all but the two reports) must equal
the bytes this run rebuilt. The reports are adopted: the pub-API diff is taken
against "the previous release", which can change between two runs of one tag,
and neither the metadata nor the proof references them, so keeping the
published bytes cannot disturb the identity chain.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import native_release as nr  # noqa: E402
import native_seed.contract as c  # noqa: E402

ADOPTED = (nr.API, nr.API_DIFF)
SEAL = nr.installer.METADATA


class Gh:
    """The only place this tool touches GitHub. Tests substitute a fake."""

    def __init__(self, repo=None):
        self.repo = repo

    def run(self, *args, check=True):
        command = ["gh", *args] + (["--repo", self.repo] if self.repo else [])
        return subprocess.run(command, capture_output=True, text=False, check=check)

    def exists(self, tag):
        return self.run("release", "view", tag, check=False).returncode == 0

    def create(self, tag):
        self.run("release", "create", tag, "--title", tag, "--generate-notes")

    def assets(self, tag):
        out = self.run("release", "view", tag, "--json", "assets", "--jq", ".assets[].name").stdout
        return out.decode().split()

    def download(self, tag, name):
        with tempfile.TemporaryDirectory(prefix="release-download-") as work:
            self.run("release", "download", tag, "--pattern", name, "--dir", work)
            return (Path(work) / name).read_bytes()

    def upload(self, tag, path):
        self.run("release", "upload", tag, str(path))


class Mismatch(c.Rejected):
    pass


def validate_report(name, data):
    if name == nr.API:
        try:
            json.loads(data, object_pairs_hook=nr.installer.no_duplicate_keys)
        except ValueError as exc:
            raise Mismatch(f"published-report: {name} is not JSON: {exc}") from exc
    else:
        c.require(len(data) > 0, "published-report", f"{name} is empty")


def publish(gh, tag, directory, patience=3, delay=5.0, log=print):
    directory = Path(directory)
    nr.aggregate(directory, tag)
    with tempfile.TemporaryDirectory(prefix="release-publish-") as scratch:
        local = Path(scratch) / "assets"
        shutil.copytree(directory, local)
        if not gh.exists(tag):
            log(f"R0: no release {tag}; creating it")
            gh.create(tag)
        names = gh.assets(tag)
        for name in nr.UPLOAD_ORDER:
            c.require(names.count(name) <= 1, "published-duplicate", f"{name} appears {names.count(name)} times")
        sealed = SEAL in names
        if sealed:
            missing = [name for name in nr.UPLOAD_ORDER if name not in names]
            c.require(not missing, "published-sealed-incomplete",
                      f"{tag} is sealed but lacks {missing}; publish a new tag")
            log(f"R2: {tag} is sealed and complete; verifying only")
        else:
            log(f"R1: {tag} is not sealed; {len(names)} of {len(nr.UPLOAD_ORDER)} assets present")

        def settle(name):
            """An asset that exists must agree with what this run built."""
            published = gh.download(tag, name)
            if name in ADOPTED:
                validate_report(name, published)
                (local / name).write_bytes(published)
                log(f"adopted the published {name}")
                return
            if published != (local / name).read_bytes():
                raise Mismatch(f"published-differs: {name} on {tag} differs from the rebuilt bytes; "
                               "nothing was replaced; publish a new tag")
            log(f"{name}: identical to the published bytes")

        for name in nr.UPLOAD_ORDER:
            if name in names:
                settle(name)
                continue
            assert not sealed
            try:
                gh.upload(tag, local / name)
            except subprocess.CalledProcessError:
                # A client that was cut off can still leave a complete asset a
                # moment later. Look again before calling it a failure.
                for _ in range(patience):
                    time.sleep(delay)
                    if name in gh.assets(tag):
                        break
                else:
                    raise
                settle(name)
                continue
            log(f"{name}: uploaded")
        # Final check on what is actually published, not on what we meant to publish.
        final = Path(scratch) / "published"
        final.mkdir()
        listing = gh.assets(tag)
        for name in nr.UPLOAD_ORDER:
            c.require(listing.count(name) == 1, "published-count",
                      f"release asset {name} appears {listing.count(name)} times; expected exactly once")
            (final / name).write_bytes(gh.download(tag, name))
        nr.aggregate(final, tag)
        log(f"verified: {tag} carries the nine assets and they agree")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dir", required=True)
    args = parser.parse_args()
    try:
        publish(Gh(), args.tag, args.dir)
    except (c.Rejected, OSError, subprocess.SubprocessError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

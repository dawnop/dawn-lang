#!/usr/bin/env python3
"""Build a private LSP with module-order and execution-count traces on stderr.

Production has no additional wire method or logging switch. The source root
may be a frozen cold worktree or the candidate; both get the same input trace.
The probes are the lsp-observe group of mutate.py, where the preflight proves
their anchors against HEAD; a frozen tree without an incremental workspace
still skips the prefix-stats probe, as it always did.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

from cold import DAWN, HERE, ROOT, apply, owned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cold", action="store_true",
                        help="force eviction before each analysis in the private candidate")
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fingerprints = {}
    for directory in ("selfhost", "compiler-plan"):
        shutil.copytree(source / directory, output / directory,
                        ignore=shutil.ignore_patterns("build", ".dawn"))
        for path in sorted((source / directory).rglob("*")):
            if path.is_file() and path.suffix in (".dawn", ".toml", ".lock"):
                fingerprints[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "packages").symlink_to(source / "packages", target_is_directory=True)
    probes = owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"], "lsp-observe")
    rel = "selfhost/src/lsp/server.dawn"
    server = output / rel
    text = apply(server.read_text(), probes["inputs"], rel)
    (_, incremental, _), = probes["prefix-stats"]
    if incremental in text:
        text = apply(text, probes["prefix-stats"], rel)
        if args.cold:
            text = apply(text, probes["cold"], rel)
    elif args.cold:
        raise RuntimeError("--cold requires a candidate with an incremental workspace")
    server.write_text(text)
    with (output / "build.log").open("w") as log:
        subprocess.run([DAWN, "build", str(output / "selfhost"), "-o", str(output / "compiler.jar"),
                        "--vendor", "org/objectweb/asm", "--vendor", "coursierapi"],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    (output / "metadata.json").write_text(json.dumps({
        "source": str(source), "sources": fingerprints, "forced_cold": args.cold,
        "instrumented_server_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "compiler_sha256": hashlib.sha256((output / "compiler.jar").read_bytes()).hexdigest(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()

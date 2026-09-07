#!/usr/bin/env python3
"""Survey body state in an isolated compiler, preserving production header order.

The extracted header prefix is private test instrumentation, not a replacement
checker. Failing anchors stop the experiment instead of silently probing a
different phase order. No production source or emission contract is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from cold import ROOT, HERE, DAWN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--java-home", required=True, type=Path)
    variants = ["skip-symbol", "skip-captures", "skip-spans", "skip-operator-spans", "ambiguous-key",
                "skip-cx-symbols", "skip-diagnostics", "skip-symbol-location"]
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--mutant", choices=variants)
    modes.add_argument("--all", action="store_true", help="run the positive and all eight compiling negative controls")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.all:
        started = time.monotonic()
        for name in ["positive", *variants]:
            command = [sys.executable, str(Path(__file__).resolve()), "--java-home", str(args.java_home.resolve()),
                       "--output", str(output / name)]
            if name != "positive":
                command += ["--mutant", name]
            subprocess.run(command, check=True, timeout=900)
        elapsed = time.monotonic() - started
        (output / "summary.json").write_text(json.dumps({"variants": ["positive", *variants],
                                                         "elapsed_seconds": elapsed}, indent=2) + "\n")
        print(f"OK: complete body identity/relocation prototype, {elapsed:.2f}s")
        return
    java = args.java_home.resolve() / "bin/java"
    javac = args.java_home.resolve() / "bin/javac"
    for directory in ("selfhost", "compiler-plan"):
        shutil.copytree(ROOT / directory, output / directory,
                        ignore=shutil.ignore_patterns("build", ".dawn"))
    (output / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
    checker = output / "selfhost/src/check/checker.dawn"
    source = checker.read_text()
    start = "pub fn check_module(cx: Cx, m: Module, env: Map[String, ModExports]) -> (Cx, TModule) !io = {\n"
    end = "  # 5. inferred functions first, in call-dependency order"
    if source.count(start) != 1 or source.count(end) != 1:
        raise RuntimeError("Header probe anchors drifted")
    prefix = source.split(start, 1)[1].split(end, 1)[0]
    checker.write_text(source + "\npub fn headers_for_body_probe(cx: Cx, m: Module, env: Map[String, ModExports]) -> (Cx, List[Sig]) !io = {\n"
                       + prefix + "  (cx1, sigs)\n}\n")
    fixture = output / "scripts/body-probe"
    (fixture / "src").mkdir(parents=True)
    (fixture / "dawn.toml").write_text((HERE / "dawn.toml").read_text())
    (fixture / "src/bodyprobe.dawn").write_text((HERE / "body-probe.dawn.txt").read_text())
    identity = (HERE / "body-identity.dawn.txt").read_text()
    relocation = (HERE / "body-relocate.dawn.txt").read_text()
    mutations = {
        "skip-symbol": ("{ id + m.delta }", "{ id }"),
        "skip-captures": ("ids(captures, m), position(lo, m), position(hi, m), ty)", "captures, position(lo, m), position(hi, m), ty)"),
        "skip-spans": ("p + m.span", "p"),
        "skip-operator-spans": ("moved, position(olo, m), position(ohi, m)", "moved, olo, ohi"),
        "skip-cx-symbols": ("..cx, syms: syms", "..cx, syms: cx.syms"),
        "skip-diagnostics": ("cx.diags ++ diagnostics", "cx.diags"),
        "skip-symbol-location": ("dlo: position(s.dlo, m), dhi: position(s.dhi, m)", "dlo: s.dlo, dhi: s.dhi"),
    }
    expected_failure = "relocated body differs from shifted cold check"
    if args.mutant in ("skip-cx-symbols", "skip-diagnostics", "skip-symbol-location"):
        expected_failure = "replayed Cx differs from cold body boundary"
    if args.mutant == "ambiguous-key":
        if identity.count("count == 1") != 1:
            raise RuntimeError("Identity mutation anchor drifted")
        identity = identity.replace("count == 1", "count > 0")
        expected_failure = "duplicate declarations received a reusable identity"
    elif args.mutant:
        old, new = mutations[args.mutant]
        if relocation.count(old) != 1:
            raise RuntimeError("Relocation mutation anchor drifted")
        relocation = relocation.replace(old, new)
    (fixture / "src/relocation.dawn").write_text(relocation)
    (fixture / "src/identity.dawn").write_text(identity)
    classes = output / "classes"
    classes.mkdir()
    subprocess.run([str(javac), "--release", "21", "-d", str(classes),
                    str(HERE / "SemanticSnapshot.java"), str(HERE / "BodyProbe.java")], check=True)
    with (output / "build.log").open("w") as log:
        subprocess.run([DAWN, "build", str(fixture), "-o", str(output / "subject.jar")],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    result = subprocess.run([str(java), "-Xss512m", "-cp", str(classes) + ":" + str(output / "subject.jar"),
                             "contract.BodyProbe"], cwd=ROOT, timeout=120,
                            text=True, capture_output=True)
    (output / "run.log").write_text(result.stdout + result.stderr)
    if args.mutant:
        if result.returncode == 0 or expected_failure not in result.stderr or "NoSuchMethodError" in result.stderr:
            raise RuntimeError("Mutation did not reach its owning semantic comparison: " + result.stderr)
        print("OK: compiling relocation mutant rejected: " + args.mutant)
        return
    if result.returncode != 0:
        raise RuntimeError("Body probe failed: " + result.stderr)
    (output / "state-writes.tsv").write_text(result.stdout)
    version = subprocess.run([str(java), "-version"], text=True, capture_output=True, check=True)
    (output / "metadata.json").write_text(json.dumps({
        "java": version.stdout + version.stderr,
        "production_checker_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "probe_sha256": hashlib.sha256((HERE / "body-probe.dawn.txt").read_bytes()).hexdigest(),
        "relocation_sha256": hashlib.sha256(relocation.encode()).hexdigest(),
        "identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
        "note": "Eleven illustrative bodies and ten real-edit replays; fixed-header symbol and uniform code-point relocation, not general product relocation",
    }, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate named LSP memo selectors and the receipts of their complete run.

A subject is one whole check/test pair, including its stateful assertions.
Only the union of successful receipts establishes global coverage. The plan
is held to mutate.py, and receipts are held to this checkout and this plan.
"""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile

from cold import HERE, ROOT, owned

PLAN = HERE / "lsp-module-memo-plan.json"


def subject_names():
    return ["positive", *owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"],
                               "lsp-module-memo")]


def read_plan(path, names, total):
    plan = json.loads(path.read_text())
    if not isinstance(plan, dict) or set(plan) != {"schema", "shards"} or plan["schema"] != 1:
        raise ValueError("Invalid LSP memo plan schema")
    shards = plan["shards"]
    if not isinstance(shards, list) or len(shards) != total:
        raise ValueError("LSP memo plan shard count disagrees with --shards")
    if any(not isinstance(shard, list) or not shard or
           any(not isinstance(name, str) for name in shard) for shard in shards):
        raise ValueError("LSP memo selectors must be nonempty lists of subject names")
    covered = [name for shard in shards for name in shard]
    if collections.Counter(covered) != collections.Counter(names):
        raise ValueError("LSP memo selectors omit, duplicate or invent subjects")
    if any(not any(name != "positive" for name in shard) for shard in shards):
        raise ValueError("Every LSP memo selector must contain a mutant")
    return shards


def input_identity(plan):
    # The commit identifies every tracked input. Hash the actual producer and
    # harness bytes too, so a modified checkout cannot donate a clean receipt.
    plan = plan.resolve()
    paths = ["selfhost/src/lsp/server.dawn", "selfhost/src/check/checker.dawn",
             "selfhost/src/driver/analyze.dawn"]
    paths += [str(path.relative_to(ROOT)) for path in
              (HERE / "mutate.py", HERE / "cold.py", HERE / "lsp-module-memo.py",
               Path(__file__), plan)]
    digest = hashlib.sha256()
    for name in sorted(paths):
        digest.update(name.encode() + b"\0" + (ROOT / name).read_bytes() + b"\0")
    return {"commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "inputs": digest.hexdigest(),
            "plan": hashlib.sha256(plan.read_bytes()).hexdigest()}


def receipt(index, total, ran, identity):
    return dict(schema=1, shard=index, shards=total, ran=ran, identity=identity)


def record(directory, index, total, ran, plan):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"lsp-memo-{index}.json"
    # Refuse a second selector writing the same receipt in a job.
    with path.open("x") as stream:
        json.dump(receipt(index, total, ran, input_identity(plan)), stream, indent=2)
        stream.write("\n")


def check(directory, shards, identity):
    records = [json.loads(path.read_text()) for path in sorted(directory.rglob("lsp-memo-*.json"))]
    indices = []
    covered = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {
                "schema", "shard", "shards", "ran", "identity"}:
            raise ValueError("Invalid LSP memo receipt schema")
        index = record["shard"]
        if (record["schema"] != 1 or type(index) is not int or
                not 0 <= index < len(shards) or record["shards"] != len(shards)):
            raise ValueError("Wrong LSP memo shard number or count")
        if record["identity"] != identity:
            raise ValueError("Wrong LSP memo input or plan identity")
        if record["ran"] != shards[index]:
            raise ValueError("LSP memo receipt differs from its complete selector")
        indices.append(index)
        covered.extend(record["ran"])
    if collections.Counter(indices) != collections.Counter(range(len(shards))):
        raise ValueError("Missing or repeated LSP memo shard")
    if collections.Counter(covered) != collections.Counter(name for shard in shards for name in shard):
        raise ValueError("Missing or repeated LSP memo subject in the union")
    print(f"OK: complete LSP memo union, {len(shards)} shards and {len(covered)} subjects")


def selftest():
    names = subject_names()
    shards = read_plan(PLAN, names, 3)
    identity = {"commit": "a" * 40, "inputs": "b" * 64, "plan": "c" * 64}
    base = [receipt(i, len(shards), shard, identity) for i, shard in enumerate(shards)]
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-memo-coverage-") as temp:
        root = Path(temp)
        def verify(records):
            for path in root.glob("*.json"):
                path.unlink()
            for i, record in enumerate(records):
                (root / f"lsp-memo-{i}.json").write_text(json.dumps(record))
            check(root, shards, identity)
        verify(base)
        controls = {"missing shard": base[:-1], "repeated shard": [*base, base[0]]}
        for label, field, value in [
                ("wrong number", "shard", 4), ("wrong count", "shards", 5),
                ("wrong input", "identity", dict(identity, commit="d" * 40)),
                ("wrong producer", "identity", dict(identity, inputs="e" * 64)),
                ("wrong plan", "identity", dict(identity, plan="f" * 64)),
                ("missing mutant", "ran", base[0]["ran"][:-1]),
                ("repeated subject", "ran", [*base[0]["ran"], base[0]["ran"][0]])]:
            records = copy.deepcopy(base)
            records[0][field] = value
            controls[label] = records
        for label, records in controls.items():
            try:
                verify(records)
            except ValueError:
                continue
            raise RuntimeError(f"LSP memo coverage accepted {label}")
        bad_plans = [shards[:-1], [[], *shards[1:]],
                     [[*shards[0], shards[1][0]], *shards[1:]],
                     [shards[0][:-1], *shards[1:]], [["unknown"], *shards[1:]]]
        plan = root / "plan.json"
        for bad in bad_plans:
            plan.write_text(json.dumps(dict(schema=1, shards=bad)))
            try:
                read_plan(plan, names, 3)
            except ValueError:
                continue
            raise RuntimeError("LSP memo selector accepted an invalid plan")
    print(f"OK: LSP memo coverage refused {len(controls)} receipt and {len(bad_plans)} selector controls")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        selftest()
        return
    if args.coverage_dir is None:
        parser.error("require --coverage-dir")
    try:
        shards = read_plan(PLAN, subject_names(), 3)
        check(args.coverage_dir, shards, input_identity(PLAN))
    except (ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

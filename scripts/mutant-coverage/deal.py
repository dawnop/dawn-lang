#!/usr/bin/env python3
"""Deal a sharded harness's matrix by measured cost into a `--plan` file.

Round robin (shard.sh's default) deals by position, which is fair only while
the items cost about the same. tile-golden's do not: a mutant there costs
about two and a half kernels, one mutant costs three, and shard 1 carries the
ledger gates and a full-history checkout on top of its items. Dealing by
position left its eight shards between 755s and 785s modelled on 2026-10-10,
and the observed spread was wider than that. Packing longest first onto the
lightest shard (LPT; within 4/3 of the optimum, and in practice within one
kernel of even on a list this long) is the standard answer and needs nothing
but a cost per item.

The costs are the input, so they are written into the plan next to the deal
(`<item> <shard> <seconds>`): a later re-deal reads them back from the plan
itself, and a reviewer can see what the deal was computed from. Any file of
`<item> <seconds>` lines also works, which is the format
`ITEM_TIMES=<file> ./scripts/tile-golden/run.sh` appends; given several files
an item's cost is its median over them. An item with no cost gets the median
of the others and is named on stderr, so a new kernel is dealt as an average
item rather than refused.

    deal.py --harness tile-golden --shards 11 --costs PLAN_OR_TIMES... \\
            [--head-start 1:17] [--out PLAN]
    deal.py --self-test

`--head-start I:S` starts shard I with S seconds of load already on it, for
fixed work only that shard does. Without `--out` the plan goes to stdout.
The per-shard loads go to stderr either way.
"""

import argparse
import pathlib
import statistics
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]


def read_matrix(root, harness):
    path = root / "scripts" / harness / "matrix.txt"
    if not path.is_file():
        raise SystemExit(f"deal.py: no matrix.txt for harness {harness} at {path}")
    names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if len(set(names)) != len(names):
        raise SystemExit(f"deal.py: {path} lists a name twice")
    return names


def read_costs(paths):
    """item -> median seconds over every file that names it."""
    seen = {}
    for path in paths:
        text = pathlib.Path(path).read_text(encoding="utf-8")
        is_plan = any(line.startswith("harness=") for line in text.splitlines())
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#") or "=" in line.split()[0]:
                continue
            fields = line.split()
            if is_plan:
                if len(fields) != 3:
                    raise SystemExit(f"deal.py: {path}:{lineno}: a plan line read as costs needs <item> <shard> <seconds>")
                name, value = fields[0], fields[2]
            else:
                if len(fields) != 2:
                    raise SystemExit(f"deal.py: {path}:{lineno}: want <item> <seconds>")
                name, value = fields
            try:
                seconds = float(value)
            except ValueError:
                raise SystemExit(f"deal.py: {path}:{lineno}: {value!r} is not a number of seconds")
            if seconds < 0:
                raise SystemExit(f"deal.py: {path}:{lineno}: negative cost")
            seen.setdefault(name, []).append(seconds)
    return {name: statistics.median(values) for name, values in seen.items()}


def deal(names, costs, shards, head_start):
    """LPT: dearest first, each onto the lightest shard (lowest index on a tie)."""
    known = [costs[n] for n in names if n in costs]
    if not known:
        raise SystemExit("deal.py: no item of the matrix has a cost")
    default = statistics.median(known)
    missing = [n for n in names if n not in costs]
    cost = {n: costs.get(n, default) for n in names}
    load = [0.0] * (shards + 1)
    for index, seconds in head_start.items():
        load[index] += seconds
    position = {n: i for i, n in enumerate(names)}
    shard_of = {}
    for name in sorted(names, key=lambda n: (-cost[n], position[n])):
        target = min(range(1, shards + 1), key=lambda i: (load[i], i))
        shard_of[name] = target
        load[target] += cost[name]
    return shard_of, cost, load[1:], missing


def render(harness, shards, names, shard_of, cost, load, head_start, sources):
    out = [
        f"# Written by scripts/mutant-coverage/deal.py: {harness}'s matrix dealt",
        f"# {shards} ways by measured cost, longest first onto the lightest shard.",
        "# Columns: item, shard, seconds (the cost the deal used). Re-deal with",
        f"#   scripts/mutant-coverage/deal.py --harness {harness} --shards {shards} \\",
        f"#     --costs <this file> {' '.join(f'--head-start {i}:{s:g}' for i, s in sorted(head_start.items()))}".rstrip(),
        "# rather than editing by hand; shard.sh refuses a plan that names an item",
        "# twice or one the matrix does not carry.",
        f"# Costs from: {', '.join(sources)}",
        "# Load per shard (seconds, head start included): "
        + " / ".join(f"{x:.0f}" for x in load),
        f"harness={harness}",
        f"shards={shards}",
    ]
    out += [f"{n} {shard_of[n]} {cost[n]:.2f}" for n in names]
    return "\n".join(out) + "\n"


def parse_head_start(values, shards):
    head = {}
    for value in values:
        index, sep, seconds = value.partition(":")
        if not sep or not index.isdigit():
            raise SystemExit(f"deal.py: --head-start wants I:S, got {value!r}")
        if not 1 <= int(index) <= shards:
            raise SystemExit(f"deal.py: --head-start shard {index} is out of range for {shards}")
        head[int(index)] = head.get(int(index), 0.0) + float(seconds)
    return head


def self_test():
    names = ["a", "b", "c", "d", "e", "f", "g"]
    costs = {"a": 30, "b": 30, "c": 10, "d": 10, "e": 10, "f": 10}  # g has none
    shard_of, cost, load, missing = deal(names, costs, 3, {1: 15})
    assert missing == ["g"], missing
    assert cost["g"] == 10, cost
    assert sorted(shard_of) == sorted(names), "every item is dealt exactly once"
    assert max(load) - min(load) <= max(cost.values()), load
    assert shard_of["a"] == 2 and shard_of["b"] == 3, "the head start keeps shard 1 off the dear items"
    with tempfile.TemporaryDirectory() as tmp:
        plan = pathlib.Path(tmp) / "plan"
        plan.write_text(render("h", 3, names, shard_of, cost, load, {1: 15}, ["test"]))
        again = read_costs([plan])
        assert again == {n: float(cost[n]) for n in names}, "a plan reads back as its own costs"
        times = pathlib.Path(tmp) / "times"
        times.write_text("a 1\na 3\nb 2\n")
        assert read_costs([times]) == {"a": 2.0, "b": 2.0}, "median over repeated lines"
        bad = pathlib.Path(tmp) / "bad"
        bad.write_text("a x\n")
        try:
            read_costs([bad])
        except SystemExit:
            pass
        else:
            raise AssertionError("a non-numeric cost was accepted")
    print("OK: deal.py self-test")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    ap.add_argument("--shards", type=int)
    ap.add_argument("--costs", nargs="+", default=[])
    ap.add_argument("--head-start", action="append", default=[])
    ap.add_argument("--out")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.harness or not args.shards or not args.costs:
        ap.error("--harness, --shards and --costs are required")
    if args.shards < 1:
        ap.error("--shards must be at least 1")
    names = read_matrix(pathlib.Path(args.root), args.harness)
    costs = read_costs(args.costs)
    head = parse_head_start(args.head_start, args.shards)
    shard_of, cost, load, missing = deal(names, costs, args.shards, head)
    for name in missing:
        print(f"deal.py: no cost for {name}; dealt at the median", file=sys.stderr)
    text = render(args.harness, args.shards, names, shard_of, cost, load, head,
                  [pathlib.Path(p).name for p in args.costs])
    print("loads: " + " / ".join(f"{x:.0f}" for x in load), file=sys.stderr)
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()

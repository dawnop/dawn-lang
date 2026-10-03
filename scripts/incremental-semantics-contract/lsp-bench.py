#!/usr/bin/env python3
"""Measure real overlay edits and ready-snapshot queries without changing files.

The barrier forces pending sync to flush, so edit latency excludes the idle
debounce timer. Query timings are subsequent requests against that snapshot.
Linux RSS is process memory, not a claim about retained semantic-cache bytes.

Two inlay columns (docs/lsp-hover-design.md §A4.5): `inlay` asks for the
whole entry buffer, the acceptance case of the A4 cut; `inlay_view` asks for
the INLAY_VIEW_LINES lines from the needle's, the way an editor asks for what
is on screen.

`resolve` (docs/lsp-hover-design.md §D7) sends `completionItem/resolve` for
one item of that round's completion list: the one labelled with the needle's
identifier when the list has it with `data`, else the first item with `data`.
Its time is the doc lookup alone; `completion` stays the list, which carries
no docs. `--item-defaults` initializes as a client that applies
`CompletionList.itemDefaults.data`, so the list names the document once
rather than on every item; without it every item carries its own `data`.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import sys
import time

from lsp_stats import FIELDS, decode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lsp-workspace-contract"))
from workspace import LspClient, did_open, did_change, position


QUERIES = ("hover", "definition", "completion", "inlay", "inlay_view", "resolve")

# An editor viewport's worth of lines, for `inlay_view`.
INLAY_VIEW_LINES = 60


def inlay_ranges(text, target):
    """The whole-buffer range and the viewport range starting at the target's line."""
    last = text.count("\n") + 1
    start = target["line"]
    return {"inlay": {"start": {"line": 0, "character": 0}, "end": {"line": last, "character": 0}},
            "inlay_view": {"start": {"line": start, "character": 0},
                           "end": {"line": start + INLAY_VIEW_LINES, "character": 0}}}


def resolve_item(items, needle):
    """The completion item `resolve` asks about: the needle's own name if the
    list offers it with data, else the first item that has data, else None.
    A list with `itemDefaults.data` gives that data to every item lacking
    its own, the way a client applies it."""
    default = None
    if isinstance(items, dict):
        default = (items.get("itemDefaults") or {}).get("data")
        items = items.get("items")
    if not isinstance(items, list):
        return None
    if default is not None:
        items = [item if not isinstance(item, dict) or "data" in item else {**item, "data": default}
                 for item in items]
    with_data = [item for item in items if isinstance(item, dict) and "data" in item]
    word = re.match(r"[A-Za-z_][A-Za-z0-9_]*", needle)
    for item in with_data:
        if word and item.get("label") == word.group(0):
            return item
    return with_data[0] if with_data else None


def rss(pid):
    path = Path(f"/proc/{pid}/status")
    if not path.exists():
        return None
    return {line.split(":")[0]: line.split(":", 1)[1].strip()
            for line in path.read_text().splitlines() if line.startswith(("VmRSS:", "VmHWM:"))}


def latency_summary(values):
    """Keep the raw sample count beside an explicitly defined tail estimate."""
    values = sorted(values)
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("latency samples must be finite, nonnegative and nonempty")
    return {"samples": len(values), "median_ms": statistics.median(values) / 1e6,
            "p95_ms": values[math.ceil(0.95 * len(values)) - 1] / 1e6}


def validate_diagnostics(publishes, uri, version, expected_error, error_line):
    own = [item for item in publishes if item.get("uri") == uri]
    if not own or own[-1].get("version") != version:
        raise RuntimeError("edited buffer did not publish its current version")
    diagnostics = own[-1].get("diagnostics", [])
    if expected_error:
        if not any("benchmark_type_error" in item.get("message", "")
                   and item.get("range", {}).get("start", {}).get("line") == error_line
                   for item in diagnostics):
            raise RuntimeError("injected type error was not diagnosed at its own source location")
    elif any(item.get("diagnostics") for item in publishes):
        raise RuntimeError("clean edit did not clear diagnostics")


def selftest():
    assert decode("LSP_BODY_STATS\tstandalone\tunobserved") == {
        "scope": "standalone", "observed": False, "counts": None}
    assert decode("LSP_BODY_STATS\tproject\t" + "\t".join(["0"] * len(FIELDS))) == {
        "scope": "project", "observed": True, "counts": dict.fromkeys(FIELDS, 0)}
    for invalid in ("", "LSP_BODY_STATS\tunknown\tunobserved",
                    "LSP_BODY_STATS\tproject\t0", "LSP_BODY_STATS\tproject\tunobserved\t0",
                    "LSP_BODY_STATS\tproject\t" + "\t".join(["-1"] * len(FIELDS)),
                    "LSP_BODY_STATS\tproject\t" + "\t".join(["NaN"] * len(FIELDS))):
        try:
            decode(invalid)
        except ValueError:
            continue
        raise AssertionError("analysis trace accepted invalid counters")
    assert latency_summary([1_000_000]) == {
        "samples": 1, "median_ms": 1.0, "p95_ms": 1.0}
    assert latency_summary(reversed([n * 1_000_000 for n in range(1, 21)])) == {
        "samples": 20, "median_ms": 10.5, "p95_ms": 19.0}
    assert latency_summary([0, 0, 0])["p95_ms"] == 0
    assert latency_summary([n * 1_000_000 for n in range(1, 22)])["p95_ms"] == 20
    for invalid in ([], [-1], [float("nan")], [float("inf")]):
        try:
            latency_summary(invalid)
        except ValueError:
            continue
        raise AssertionError("latency summary accepted invalid samples")
    clean = {"uri": "untitled:test", "version": 2, "diagnostics": []}
    error = {"uri": "untitled:test", "version": 2, "diagnostics": [{
        "message": "benchmark_type_error returns Bool, expected Int",
        "range": {"start": {"line": 7}}}]}
    validate_diagnostics([clean], "untitled:test", 2, False, 7)
    validate_diagnostics([error], "untitled:test", 2, True, 7)
    rejected = [
        ([], 2, False, 7),
        ([clean], 3, False, 7),
        ([error], 2, False, 7),
        ([clean], 2, True, 7),
        ([error], 2, True, 8),
        ([clean, {**error, "uri": "untitled:other"}], 2, False, 7),
    ]
    for publishes, version, expected, line in rejected:
        try:
            validate_diagnostics(publishes, "untitled:test", version, expected, line)
        except RuntimeError:
            continue
        raise AssertionError("diagnostic validation accepted a negative control")
    ranges = inlay_ranges("a\nb\n", {"line": 1, "character": 0})
    assert ranges["inlay"]["end"] == {"line": 3, "character": 0}
    assert ranges["inlay_view"]["start"]["line"] == 1
    assert ranges["inlay_view"]["end"]["line"] == 1 + INLAY_VIEW_LINES
    items = [{"label": "let", "kind": 14}, {"label": "a", "kind": 3, "data": {}},
             {"label": "helper", "kind": 3, "data": {}}]
    assert resolve_item(items, "helper(n)")["label"] == "helper"
    assert resolve_item(items, "other")["label"] == "a"
    assert resolve_item({"items": items}, "helper")["label"] == "helper"
    assert resolve_item(items[:1], "let") is None
    assert resolve_item(None, "x") is None
    listed = {"itemDefaults": {"data": {"uri": "u"}}, "items": [{"label": "helper", "kind": 3}]}
    assert resolve_item(listed, "helper") == {"label": "helper", "kind": 3, "data": {"uri": "u"}}
    print("OK: benchmark diagnostics (6 controls), latency percentiles (4 controls), analysis traces (6 controls), inlay ranges, resolve item (6 controls)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", required=True, type=Path)
    parser.add_argument("--edit", action="append", required=True, type=Path)
    parser.add_argument("--needle", required=True, help="hover/definition target in entry source")
    parser.add_argument("--output", required=True, type=Path, help="new directory")
    parser.add_argument("--rounds", type=int, default=11)
    parser.add_argument("--uri", help="non-file URI for a single standalone buffer")
    parser.add_argument("--error-round", type=int,
                        help="append a type error in this round, then restore clean input")
    parser.add_argument("--item-defaults", action="store_true",
                        help="advertise completionList.itemDefaults [\"data\"] at initialize")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.rounds < 4:
        parser.error("provide a server command after -- and at least four rounds")
    files = list(dict.fromkeys(path.resolve() for path in [args.entry, *args.edit]))
    if args.uri and (len(files) != 1 or args.uri.startswith("file:")):
        parser.error("--uri requires one buffer and a non-file URI")
    if args.error_round is not None and not 0 <= args.error_round < args.rounds - 1:
        parser.error("--error-round must leave a subsequent clean recovery round")
    if args.error_round is not None and len(args.edit) != 1:
        parser.error("--error-round requires one edited buffer")
    texts = {path: path.read_text() for path in files}
    entry = args.entry.resolve()
    uris = {path: args.uri or path.as_uri() for path in files}
    target_position = position(texts[entry], args.needle)
    ranges = inlay_ranges(texts[entry], target_position)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "command": command, "cwd": str(ROOT), "platform": platform.platform(),
        "warmup_rounds": 3, "rounds": args.rounds,
        "latency_percentiles": "median; p95 nearest rank ceil(0.95*n); post-warmup clean samples only",
        "uri": args.uri, "error_round": args.error_round, "item_defaults": args.item_defaults,
        "sources": {str(path): hashlib.sha256(text.encode()).hexdigest() for path, text in texts.items()},
        "note": "overlay-only comment edits and optional type-error recovery; barrier excludes debounce; RSS is process-wide",
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    client = LspClient(command, ROOT)
    rows = []
    try:
        client.initialize({"textDocument": {"completion": {"completionList": {"itemDefaults": ["data"]}}}}
                          if args.item_defaults else None)
        mark = client.mark()
        for path in files:
            client.send(did_open(uris[path], texts[path]))
        initial = client.barrier(mark)
        if any(item.get("params", {}).get("diagnostics") for item in initial
               if item.get("method") == "textDocument/publishDiagnostics"):
            raise RuntimeError(f"baseline contains diagnostics: {initial!r}")
        for round_index in range(args.rounds):
            for path in args.edit:
                path = path.resolve()
                mark = client.mark()
                stderr_mark = len(client.stderr_text())
                start = time.perf_counter_ns()
                edited_text = texts[path] + f"\n# benchmark edit {round_index}\n"
                error_line = edited_text.count("\n")
                expected_error = round_index == args.error_round
                if expected_error:
                    edited_text += "pub fn benchmark_type_error() -> Int = false\n"
                client.send(did_change(uris[path], edited_text,
                                       round_index + 2))
                frames = client.barrier(mark)
                elapsed = time.perf_counter_ns() - start
                publishes = [item["params"] for item in frames
                             if item.get("method") == "textDocument/publishDiagnostics"]
                validate_diagnostics(publishes, uris[path], round_index + 2, expected_error, error_line)
                row = {"round": round_index, "edited": str(path), "sync_ns": elapsed,
                       "expected_error": expected_error, "diagnostics": publishes,
                       "rss": rss(client.proc.pid), "replies": {}, "query_ns": {},
                       "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None}
                trace = client.stderr_text()[stderr_mark:].splitlines()
                orders = [line.split("\t")[1:] for line in trace if line.startswith("LSP_INPUTS\t")]
                counts = [line.split("\t")[1:] for line in trace if line.startswith("LSP_PREFIX_STATS\t")]
                body_counts = [decode(line) for line in trace if line.startswith("LSP_BODY_STATS\t")]
                if body_counts:
                    if len(body_counts) != 1:
                        raise RuntimeError("expected one analysis-count trace per edit")
                    row["analysis_counts"] = body_counts[0]
                if orders:
                    if len(orders) != 1:
                        raise RuntimeError("expected one analysis input trace per edit")
                    row["module_order"] = orders[0]
                    row["edited_module_index"] = orders[0].index(str(path))
                if counts:
                    if len(counts) != 1 or len(counts[0]) != 3:
                        raise RuntimeError("invalid prefix execution trace")
                    row["prefix_counts"] = dict(zip(("reused", "checked", "retained"), map(int, counts[0])))
                for method in QUERIES:
                    if method == "resolve":
                        item = resolve_item(row["replies"]["completion"], args.needle)
                        if item is None:
                            raise RuntimeError("completion offered no item with data to resolve")
                        start = time.perf_counter_ns()
                        reply = client.result("completionItem/resolve", item)
                        row["query_ns"][method] = time.perf_counter_ns() - start
                        row["replies"][method] = {"label": item["label"],
                                                  "documentation": isinstance(reply, dict) and "documentation" in reply}
                        continue
                    if method in ranges:
                        params = {"textDocument": {"uri": uris[entry]}, "range": ranges[method]}
                        wire = "textDocument/inlayHint"
                    else:
                        params = {"textDocument": {"uri": uris[entry]}, "position": target_position}
                        wire = "textDocument/" + method
                    start = time.perf_counter_ns()
                    reply = client.result(wire, params)
                    row["query_ns"][method] = time.perf_counter_ns() - start
                    row["replies"][method] = len(reply) if method in ranges and isinstance(reply, list) else reply
                if row["replies"]["hover"] is None:
                    raise RuntimeError("hover target did not resolve; choose a real reference")
                rows.append(row)
                (output / "samples.json").write_text(json.dumps(rows, indent=2) + "\n")
        client.shutdown_exit()
    finally:
        (output / "stderr.txt").write_text(client.stderr_text())
        client.close()
    summary = []
    for path in args.edit:
        samples = [row for row in rows if row["edited"] == str(path.resolve())
                   and row["round"] >= 3 and not row["expected_error"]]
        sync = latency_summary(row["sync_ns"] for row in samples)
        queries = {method: latency_summary(row["query_ns"][method] for row in samples)
                   for method in QUERIES}
        summary.append({
            "edited": str(path.resolve()), "samples": len(samples),
            "error_sync_ms": [row["sync_ns"] / 1e6 for row in rows
                              if row["edited"] == str(path.resolve()) and row["expected_error"]],
            "sync_median_ms": sync["median_ms"],
            "sync_p95_ms": sync["p95_ms"],
            "query_median_ms": {method: value["median_ms"] for method, value in queries.items()},
            "query_p95_ms": {method: value["p95_ms"] for method, value in queries.items()},
        })
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        selftest()
    else:
        main()

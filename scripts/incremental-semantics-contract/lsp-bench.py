#!/usr/bin/env python3
"""Measure real overlay edits and ready-snapshot queries without changing files.

The barrier forces pending sync to flush, so edit latency excludes the idle
debounce timer. Query timings are subsequent requests against that snapshot.
Linux RSS is process memory, not a claim about retained semantic-cache bytes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lsp-workspace-contract"))
from workspace import LspClient, did_open, did_change, position


def rss(pid):
    path = Path(f"/proc/{pid}/status")
    if not path.exists():
        return None
    return {line.split(":")[0]: line.split(":", 1)[1].strip()
            for line in path.read_text().splitlines() if line.startswith(("VmRSS:", "VmHWM:"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", required=True, type=Path)
    parser.add_argument("--edit", action="append", required=True, type=Path)
    parser.add_argument("--needle", required=True, help="hover/definition target in entry source")
    parser.add_argument("--output", required=True, type=Path, help="new directory")
    parser.add_argument("--rounds", type=int, default=11)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.rounds < 4:
        parser.error("provide a server command after -- and at least four rounds")
    files = list(dict.fromkeys(path.resolve() for path in [args.entry, *args.edit]))
    texts = {path: path.read_text() for path in files}
    entry = args.entry.resolve()
    target_position = position(texts[entry], args.needle)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "command": command, "cwd": str(ROOT), "platform": platform.platform(),
        "warmup_rounds": 3, "rounds": args.rounds,
        "sources": {str(path): hashlib.sha256(text.encode()).hexdigest() for path, text in texts.items()},
        "note": "overlay-only comment edits; barrier excludes debounce; RSS is process-wide",
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    client = LspClient(command, ROOT)
    rows = []
    try:
        client.initialize()
        mark = client.mark()
        for path in files:
            client.send(did_open(path.as_uri(), texts[path]))
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
                client.send(did_change(path.as_uri(), texts[path] + f"\n# benchmark edit {round_index}\n",
                                       round_index + 2))
                frames = client.barrier(mark)
                elapsed = time.perf_counter_ns() - start
                if any(item.get("params", {}).get("diagnostics") for item in frames
                       if item.get("method") == "textDocument/publishDiagnostics"):
                    raise RuntimeError(f"edit produced diagnostics: {frames!r}")
                row = {"round": round_index, "edited": str(path), "sync_ns": elapsed,
                       "rss": rss(client.proc.pid), "replies": {}, "query_ns": {},
                       "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None}
                trace = client.stderr_text()[stderr_mark:].splitlines()
                orders = [line.split("\t")[1:] for line in trace if line.startswith("LSP_INPUTS\t")]
                counts = [line.split("\t")[1:] for line in trace if line.startswith("LSP_PREFIX_STATS\t")]
                if orders:
                    if len(orders) != 1:
                        raise RuntimeError("expected one analysis input trace per edit")
                    row["module_order"] = orders[0]
                    row["edited_module_index"] = orders[0].index(str(path))
                if counts:
                    if len(counts) != 1 or len(counts[0]) != 3:
                        raise RuntimeError("invalid prefix execution trace")
                    row["prefix_counts"] = dict(zip(("reused", "checked", "retained"), map(int, counts[0])))
                for method in ("hover", "definition", "completion"):
                    start = time.perf_counter_ns()
                    reply = client.result("textDocument/" + method, {
                        "textDocument": {"uri": entry.as_uri()}, "position": target_position})
                    row["query_ns"][method] = time.perf_counter_ns() - start
                    row["replies"][method] = reply
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
        samples = [row for row in rows if row["edited"] == str(path.resolve()) and row["round"] >= 3]
        summary.append({
            "edited": str(path.resolve()), "samples": len(samples),
            "sync_median_ms": statistics.median(row["sync_ns"] for row in samples) / 1e6,
            "query_median_ms": {method: statistics.median(row["query_ns"][method] for row in samples) / 1e6
                                for method in ("hover", "definition", "completion")},
        })
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

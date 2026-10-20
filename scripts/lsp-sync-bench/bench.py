#!/usr/bin/env python3
"""LSP sync latency on the selfhost workspace, judged against the accepted lines.

Why this file exists: the 2026-10-19 ruling gave LSP sync its first absolute
lines (L-edit 100 ms; L-ws 300 ms for signature and body edits, 1 s for type
definitions) and asked for one sampled run before every release. Until now the
method lived in throwaway scratchpad scripts that each re-measurement rewrote,
and the details drifted between rewrites (which quantile, warm-up or not,
interleaved or one after the other). docs/lsp-sync-bench-design.md fixes the
method; this script only carries it out.

Choices that are not obvious:

- It is NOT a CI gate. The numbers are load-sensitive (the same server's
  signature edit moved by 34 ms between passes at load 2 to 4, and full GCs
  push single samples past 1.4 s); on a shared runner it would only produce
  noise. It belongs to the release checklist in docs/bootstrap.md.
- It drives the server as an editor would and measures from the client: the
  jar under test is the jar users run, so no timing probes are patched in.
  Each didChange is followed by an unknown request; the server must finish the
  pending analysis before answering MethodNotFound, so `sync` excludes the
  debounce window and includes workspace convergence (L-ws). `edit` is when
  the edited file's publishDiagnostics arrives (L-edit). Until 2026-10-20 the
  server published every URI after the workspace converged and the two were
  nearly equal; it now publishes an open document when its module is analysed
  (docs/audit/lsp-robustness-design.md §2.2.6), and the column moved by itself.
- It has its own twenty-line LSP client instead of importing the workspace
  contract's: it needs the arrival time of every frame, and a measurement
  should not change because a contract harness changed.
- In comparison mode both servers run at once and take turns edit by edit,
  swapping who goes first every round, so a pair of samples shares one stretch
  of machine load. Interleaving whole sessions (about a minute each) lets the
  load drift inside a pair.
- Edits locate their site by spelling it (`fn seg_ok(`, the `pub fn` list of
  selfhost/src/check/types.dawn, ...). Every literal must match exactly once or
  the run stops with status 2 naming it; scripts/anchor-readers.txt records
  why that check lives here and not in mutation-anchor-preflight.

Exit status: 0 every judged line holds, 1 a line was crossed, 2 usage or
harness error (missing anchor, server died), 3 the load guard timed out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
# bin/dawn's DAWN_LSP_JVM_OPTS; the language server an editor starts through
# the launcher runs with exactly these (scripts/check-launcher-jvm-opts.py).
JVM_OPTS = ["-Xss512m", "-Xmx2g", "-XX:+UseParallelGC"]
OPEN = ["main", "front/ast", "check/checker", "check/types", "driver/analyze", "jvm/emit"]
TYPES = "check/types"
PROBE_PARAM = "l1_probe: Int = 0"
PROBE_TYPE = "\npub type L1ProbeType =\n  | L1ProbeA\n  | L1ProbeB\n"
BARRIER = "dawn/syncBenchBarrier"
TIMEOUT_S = 180.0

# Scenario -> (module, kind, locator). `body` inserts a fresh `let` at the top
# of the function's body; `sig` toggles a defaulted trailing parameter; `type`
# toggles a new ADT at the end of the module.
SCENARIOS = {
    "a": ("driver/analyze", "body", "seg_ok"),
    "b": (TYPES, "sig", "eff_suffix"),
    "c": ("front/ast", "body", "arg_exprs"),
    "d": (TYPES, "type", None),
}
# The ruling's lines: (name, scenario or "sample", metric, limit in ms).
LINES = [
    ("L-edit", "a", "edit", 100), ("L-edit", "b", "edit", 100),
    ("L-edit", "c", "edit", 100), ("L-edit", "d", "edit", 100),
    ("L-edit", "sample", "edit", 100),
    ("L-ws-body", "a", "sync", 300), ("L-ws-body", "c", "sync", 300),
    ("L-ws-sig", "b", "sync", 300), ("L-ws-sig", "sample", "sync", 300),
    ("L-ws-type", "d", "sync", 1000),
]


class Harness(Exception):
    """A broken run (status 2), as opposed to a crossed line (status 1)."""


class LoadTimeout(Exception):
    pass


# ------------------------------------------------------------------ numbers

def quantile(values: list[float], q: float) -> float:
    """Nearest rank: always an observed sample, the same rank pool.py took at n=42."""
    if not values:
        raise ValueError("quantile of nothing")
    v = sorted(values)
    return v[max(0, math.ceil(q * len(v)) - 1)]


def summary(values: list[float]) -> dict:
    return {"n": len(values), "median": round(statistics.median(values), 1),
            "p90": round(quantile(values, 0.9), 1),
            "min": round(min(values), 1), "max": round(max(values), 1)}


# -------------------------------------------------------------------- edits

def fn_head(text: str, name: str) -> int:
    """Offset just past `fn name` at the start of a line (any pub form)."""
    found = list(re.finditer(r"^(?:pub(?:\([a-z]+\))? )?fn " + re.escape(name) + r"\b", text, re.M))
    if len(found) != 1:
        raise Harness(f"anchor 'fn {name}': {len(found)} matches, expected 1 "
                      f"(update scripts/lsp-sync-bench/bench.py)")
    return found[0].end()


def closing(text: str, i: int) -> int:
    """Index of the bracket closing the one at text[i]."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] in "([":
            depth += 1
        elif text[j] in ")]":
            depth -= 1
            if depth == 0:
                return j
    raise Harness(f"unbalanced brackets from offset {i}")


def with_param(text: str, name: str) -> str:
    """`name`'s parameter list with PROBE_PARAM appended."""
    i = fn_head(text, name)
    if text[i] == "[":
        i = closing(text, i) + 1
    if text[i] != "(":
        raise Harness(f"fn {name}: expected '(' after the name, found {text[i:i + 20]!r}")
    j = closing(text, i)
    inner = text[i + 1:j].rstrip()
    k = i + 1 + len(inner)
    if inner == "":
        return text[:j] + PROBE_PARAM + text[j:]
    if inner.endswith(","):
        return text[:k] + " " + PROBE_PARAM + "," + text[k:]
    return text[:k] + ", " + PROBE_PARAM + text[k:]


def with_let(text: str, name: str, n: int) -> str:
    """A `let` inserted as the first statement of `name`'s block body."""
    i = fn_head(text, name)
    if text[i] == "[":
        i = closing(text, i) + 1
    if text[i] != "(":
        raise Harness(f"fn {name}: expected '(' after the name, found {text[i:i + 20]!r}")
    eol = text.find("\n", closing(text, i))
    if eol < 0 or not text[i:eol].rstrip().endswith("= {"):
        raise Harness(f"fn {name}: its header does not end in a block body `= {{`")
    return text[:eol + 1] + f"  let l1_probe_edit = {n}\n" + text[eol + 1:]


def pub_fns(text: str) -> list[str]:
    return re.findall(r"^pub(?:\(pkg\))? fn ([a-z_0-9]+)", text, re.M)


def edit_text(base: str, kind: str, locator, n: int) -> str:
    """One scenario's n-th revision (n >= 1) of base; toggles are off on even n."""
    if kind == "body":
        return with_let(base, locator, n)
    if n % 2 == 0:
        return base
    if kind == "sig":
        return with_param(base, locator)
    return base + PROBE_TYPE


def compose(base: str, mod: str, revs: dict) -> str:
    """The module's text with every scenario's current revision applied.

    (b) and (d) both edit check/types. Deriving each from the pristine text
    would let one scenario's revision silently undo the other's, and an
    "edit" that sends the text the server already has measures nothing.
    """
    text = base
    for e, (m, kind, loc) in SCENARIOS.items():
        if m == mod and revs.get(e, 0) > 0:
            text = edit_text(text, kind, loc, revs[e])
    return text


def pick(fns: list[str], count: int) -> list[str]:
    """`count` functions spread evenly over the declaration order (0 = all)."""
    if count <= 0 or count >= len(fns):
        return list(fns)
    return [fns[(i * len(fns)) // count] for i in range(count)]


# ------------------------------------------------------------------- client

def frame(message: dict) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


class Server:
    """One language server process and the arrival time of every frame it sent."""

    def __init__(self, name: str, jar: Path, std: Path | None, cwd: Path, jvm: list[str]):
        env = os.environ.copy()
        env.pop("DAWN_STD", None)
        if std is not None:
            env["DAWN_STD"] = str(std)
        self.name = name
        self.err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(["java", *jvm, "-jar", str(jar), "lsp"], cwd=cwd, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.err, start_new_session=True)
        self.buf = bytearray()
        self.frames: list[tuple[int, dict]] = []
        self.next_id = 1
        self.version = 1

    def send(self, message: dict) -> None:
        try:
            self.proc.stdin.write(frame(message))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise Harness(f"{self.name}: server closed its input: {e}; {self.stderr_tail()}")

    def notify(self, method: str, params) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params) -> tuple[int, dict]:
        rid = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + TIMEOUT_S
        seen = 0
        while True:
            for k in range(seen, len(self.frames)):
                if self.frames[k][1].get("id") == rid:
                    return k, self.frames[k][1]
            seen = len(self.frames)
            self.read(deadline)

    def read(self, deadline: float) -> None:
        left = deadline - time.monotonic()
        ready = select.select([self.proc.stdout], [], [], max(0.0, left))[0] if left > 0 else []
        if not ready:
            raise Harness(f"{self.name}: no answer in {TIMEOUT_S:.0f} s; {self.stderr_tail()}")
        chunk = os.read(self.proc.stdout.fileno(), 1 << 16)
        now = time.perf_counter_ns()
        if not chunk:
            raise Harness(f"{self.name}: server exited; {self.stderr_tail()}")
        self.buf.extend(chunk)
        while True:
            end = self.buf.find(b"\r\n\r\n")
            if end < 0:
                return
            m = re.search(rb"Content-Length:\s*(\d+)", bytes(self.buf[:end]), re.I)
            if m is None:
                raise Harness(f"{self.name}: frame without Content-Length")
            stop = end + 4 + int(m.group(1))
            if len(self.buf) < stop:
                return
            self.frames.append((now, json.loads(bytes(self.buf[end + 4:stop]))))
            del self.buf[:stop]

    def barrier(self) -> int:
        k, response = self.request(BARRIER, {})
        if response.get("error", {}).get("code") != -32601:
            raise Harness(f"{self.name}: barrier answered {response!r}")
        return k

    def initialize(self, uris: dict, texts: dict) -> float:
        self.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
        self.notify("initialized", {})
        t0 = time.perf_counter_ns()
        for m in OPEN:
            self.notify("textDocument/didOpen", {"textDocument": {
                "uri": uris[m], "languageId": "dawn", "version": 1, "text": texts[m]}})
        self.barrier()
        return (time.perf_counter_ns() - t0) / 1e6

    def change(self, uri: str, text: str) -> dict:
        """Send one full-text revision; return its sync and edit times in ms."""
        self.version += 1
        mark = len(self.frames)
        t0 = time.perf_counter_ns()
        self.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": self.version},
            "contentChanges": [{"text": text}]})
        k = self.barrier()
        sync_ns = self.frames[k][0] - t0
        edit_ns, diags, own = sync_ns, 0, False
        for at, f in self.frames[mark:k]:
            if f.get("method") != "textDocument/publishDiagnostics":
                continue
            diags += len(f["params"]["diagnostics"])
            if f["params"]["uri"] == uri and not own:
                edit_ns, own = at - t0, True
        del self.frames[:]
        return {"sync_ms": round(sync_ns / 1e6, 2), "edit_ms": round(edit_ns / 1e6, 2),
                "own_publish": own, "diags": diags, "rss_mb": self.memory("VmRSS")}

    def memory(self, field: str) -> float | None:
        """VmRSS or VmHWM of the server in MiB, or None off Linux."""
        try:
            for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
                if line.startswith(field + ":"):
                    return round(int(line.split()[1]) / 1024, 1)
        except OSError:
            pass
        return None

    def stderr_tail(self) -> str:
        self.err.seek(0)
        return "stderr: " + self.err.read().decode("utf-8", "replace")[-600:]

    def close(self) -> None:
        self.peak_mb = self.memory("VmHWM")
        try:
            self.request("shutdown", None)
            self.notify("exit", None)
            self.proc.wait(timeout=20)
        except (Harness, subprocess.TimeoutExpired):
            pass
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, 9)
            except ProcessLookupError:
                pass
            self.proc.wait()
        self.err.close()


# ---------------------------------------------------------------- the bench

class Bench:
    def __init__(self, args):
        self.args = args
        self.src = args.root / "selfhost" / "src"
        self.texts = {m: (self.src / f"{m}.dawn").read_text() for m in OPEN}
        self.uris = {m: (self.src / f"{m}.dawn").resolve().as_uri() for m in OPEN}
        self.rows: list[dict] = []
        self.opens: list[dict] = []
        self.waited = 0.0
        self.sides = [("subject", args.jar, args.std, args.jvm)]
        if args.baseline:
            self.sides.append(("baseline", args.baseline, args.baseline_std,
                               args.baseline_jvm or args.jvm))
        self.peaks: list[dict] = []
        self.limits = limits(args.line)
        self.log_file = args.log.open("a") if args.log else None
        # Fail on a moved anchor before any JVM starts.
        for e in args.scenarios:
            mod, kind, loc = SCENARIOS[e]
            edit_text(self.texts[mod], kind, loc, 1)
        self.fns = pick(pub_fns(self.texts[TYPES]), args.sample) if args.sample >= 0 else []
        for fn in self.fns:
            with_param(self.texts[TYPES], fn)

    def log(self, line: str) -> None:
        line = time.strftime("%H:%M:%S ") + line
        print(line, file=sys.stderr, flush=True)
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def guard(self) -> float:
        waited = 0.0
        while os.getloadavg()[0] > self.args.load_max:
            if waited == 0:
                self.log(f"loadavg {os.getloadavg()[0]:.2f} > {self.args.load_max}, pausing")
            if self.waited + waited >= self.args.load_timeout:
                raise LoadTimeout(f"loadavg stayed above {self.args.load_max} for "
                                  f"{self.waited + waited:.0f} s in total")
            time.sleep(self.args.load_poll)
            waited += self.args.load_poll
        self.waited += waited
        return waited

    def start(self, phase: str, n: int) -> list[Server]:
        servers = []
        try:
            for name, jar, std, jvm in self.sides:
                self.guard()
                s = Server(name, jar, std, self.args.root / "selfhost", jvm)
                servers.append(s)
                ms = s.initialize(self.uris, self.texts)
                self.opens.append({"server": name, "phase": phase, "session": n, "open_ms": round(ms, 1)})
        except BaseException:
            for s in servers:
                s.close()
            raise
        return servers

    def record(self, s: Server, base: dict, mod: str, text: str) -> None:
        load = os.getloadavg()[0]
        row = {"server": s.name, **base, **s.change(self.uris[mod], text), "load": round(load, 2)}
        self.rows.append(row)

    def scenarios(self) -> None:
        a = self.args
        for p in range(a.passes):
            servers = self.start("scenarios", p)
            try:
                count = {e: 0 for e in a.scenarios}
                revs: dict[str, int] = {}
                for rnd in range(a.warm + a.rounds):
                    waited = self.guard()
                    k = rnd % len(a.scenarios)
                    order = a.scenarios[k:] + a.scenarios[:k]
                    turn = servers if (p + rnd) % 2 == 0 else servers[::-1]
                    for e in order:
                        mod, kind, loc = SCENARIOS[e]
                        count[e] += 1
                        revs[e] = count[e] if kind != "body" else p * 1000 + count[e]
                        text = compose(self.texts[mod], mod, revs)
                        for s in turn:
                            self.record(s, {"phase": "scenarios", "pass": p, "round": rnd,
                                            "warm": rnd < a.warm, "edit": e, "waited": waited},
                                        mod, text)
                    if rnd >= a.warm:
                        last = [r for r in self.rows[-len(order) * len(servers):]]
                        self.log(f"pass {p} round {rnd - a.warm}: " + " ".join(
                            f"{r['server'][0]}{r['edit']}={r['sync_ms']:.0f}" for r in last))
            finally:
                self.close_all(servers, "scenarios", p)

    def sample(self) -> None:
        a = self.args
        base = self.texts[TYPES]
        servers = self.start("sample", 0)
        try:
            warm = with_param(base, self.fns[0])
            for _ in range(a.warm):
                for t in (warm, base):
                    for s in servers:
                        s.change(self.uris[TYPES], t)
            for idx, fn in enumerate(self.fns):
                waited = self.guard()
                edited = with_param(base, fn)
                turn = servers if idx % 2 == 0 else servers[::-1]
                for rep in range(a.sample_reps):
                    for kind, t in (("add", edited), ("remove", base)):
                        for s in turn:
                            self.record(s, {"phase": "sample", "fn": fn, "rep": rep, "kind": kind,
                                            "waited": waited}, TYPES, t)
                if idx % 10 == 0 or idx == len(self.fns) - 1:
                    mine = [r["sync_ms"] for r in self.rows if r.get("fn") == fn]
                    self.log(f"sample {idx + 1}/{len(self.fns)} {fn}: "
                             f"{statistics.median(mine):.0f} ms load {os.getloadavg()[0]:.1f}")
        finally:
            self.close_all(servers, "sample", 0)

    def close_all(self, servers: list[Server], phase: str, n: int) -> None:
        for s in servers:
            s.close()
            self.peaks.append({"server": s.name, "phase": phase, "session": n,
                               "peak_mb": s.peak_mb})

    def memory(self, server: str) -> dict | None:
        """Resident set: after every recorded edit (steady) and each session's high-water mark."""
        rss = [r["rss_mb"] for r in self.rows if r["server"] == server
               and r.get("rss_mb") is not None and not r.get("warm")]
        peaks = [p["peak_mb"] for p in self.peaks if p["server"] == server and p["peak_mb"]]
        if not rss:
            return None
        return {"steady_median_mb": round(statistics.median(rss), 1),
                "steady_p90_mb": round(quantile(rss, 0.9), 1),
                "peak_mb": max(peaks) if peaks else None}

    # ---------------------------------------------------------- reporting

    def per_fn(self, server: str, metric: str) -> dict[str, float]:
        out: dict[str, list[float]] = {}
        for r in self.rows:
            if r["server"] == server and r["phase"] == "sample":
                out.setdefault(r["fn"], []).append(r[metric + "_ms"])
        return {fn: statistics.median(v) for fn, v in out.items()}

    def values(self, server: str, scenario: str, metric: str) -> list[float]:
        if scenario == "sample":
            return list(self.per_fn(server, metric).values())
        return [r[metric + "_ms"] for r in self.rows if r["server"] == server
                and r["phase"] == "scenarios" and not r["warm"] and r["edit"] == scenario]

    def paired(self, scenario: str, metric: str) -> dict | None:
        if scenario == "sample":
            sub, bas = self.per_fn("subject", metric), self.per_fn("baseline", metric)
            diffs = [sub[fn] - bas[fn] for fn in sub if fn in bas]
        else:
            key = lambda r: (r["pass"], r["round"])  # noqa: E731
            pick_ = lambda name: {key(r): r[metric + "_ms"] for r in self.rows  # noqa: E731
                                  if r["server"] == name and r["phase"] == "scenarios"
                                  and not r["warm"] and r["edit"] == scenario}
            sub, bas = pick_("subject"), pick_("baseline")
            diffs = [sub[k] - bas[k] for k in sub if k in bas]
        if not diffs:
            return None
        return {"n": len(diffs), "median_diff": round(statistics.median(diffs), 1),
                "subject_faster": sum(d < 0 for d in diffs)}

    def report(self) -> dict:
        a = self.args
        groups = list(a.scenarios) + (["sample"] if self.fns else [])
        results = {}
        for name, *_ in self.sides:
            results[name] = {"rss": self.memory(name)}
            for g in groups:
                results[name][g] = {m: summary(self.values(name, g, m)) for m in ("sync", "edit")}
            if self.fns:
                per = self.per_fn(name, "sync")
                worst = sorted(per.items(), key=lambda kv: -kv[1])[:8]
                results[name]["sample"]["worst"] = [[fn, round(v, 1)] for fn, v in worst]
        lines = judge(results["subject"], self.limits)
        paired = None
        if a.baseline:
            paired = {g: {m: self.paired(g, m) for m in ("sync", "edit")} for g in groups}
        loads = [r["load"] for r in self.rows]
        own = sum(r["own_publish"] for r in self.rows)
        return {
            "schema": SCHEMA, "tool": "lsp-sync-bench",
            "started": self.started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "root": str(a.root), "head": git_head(a.root),
            "servers": {name: {"jar": str(jar), "sha256": sha256(jar),
                               "std": str(std) if std else "embedded", "jvm": jvm}
                        for name, jar, std, jvm in self.sides},
            "config": {"scenarios": a.scenarios, "passes": a.passes, "warm": a.warm,
                       "rounds": a.rounds, "sample_fns": len(self.fns),
                       "sample_reps": a.sample_reps, "jvm": a.jvm, "open": OPEN,
                       "load_max": a.load_max},
            "load": {"min": min(loads), "median": statistics.median(loads), "max": max(loads),
                     "waited_s": self.waited} if loads else None,
            "edited_file_published": f"{own}/{len(self.rows)}",
            "opens": self.opens, "peaks": self.peaks, "results": results, "paired": paired, "lines": lines,
            "ok": all(x["ok"] for x in lines), "rows": self.rows,
        }

    def run(self) -> dict:
        self.started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if self.args.scenarios and self.args.passes > 0:
            self.scenarios()
        if self.fns:
            self.sample()
        return self.report()


def limits(overrides: list[str]) -> dict:
    """The ruling's lines with any `NAME=MS` override applied to every use of NAME."""
    out = {(n, s, m): v for n, s, m, v in LINES}
    for over in overrides:
        name, _, ms = over.partition("=")
        hit = [k for k in out if k[0] == name]
        if not hit or not ms.strip().isdigit():
            raise Harness(f"--line {over!r}: expected NAME=MS with NAME one of "
                          f"{sorted({k[0] for k in out})}")
        for k in hit:
            out[k] = int(ms)
    return out


def judge(subject: dict, lims: dict) -> list[dict]:
    """Each line that applies to a measured group, held against the subject's p90."""
    lines = []
    for (name, scen, metric), limit in lims.items():
        if scen not in subject:
            continue
        value = subject[scen][metric]["p90"]
        lines.append({"line": name, "scenario": scen, "metric": metric, "quantity": "p90",
                      "limit_ms": limit, "value_ms": value, "ok": value <= limit})
    return lines


def one_line(rep: dict) -> str:
    """The human-readable summary: verdict, each group's median/p90, load."""
    parts = []
    for g, r in rep["results"]["subject"].items():
        if g == "rss":
            continue
        cell = f"{g} {r['sync']['median']:.0f}/{r['sync']['p90']:.0f}"
        if rep["paired"] and rep["paired"][g]["sync"]:
            cell += f" ({rep['paired'][g]['sync']['median_diff']:+.0f} vs baseline)"
        parts.append(cell)
    bad = [f"{x['line']} {x['scenario']} {x['metric']} p90 {x['value_ms']:.0f}>{x['limit_ms']}"
           for x in rep["lines"] if not x["ok"]]
    load = rep["load"]
    verdict = "OK" if rep["ok"] else "OVER " + ", ".join(bad)
    rss = rep["results"]["subject"].get("rss")
    return (f"lsp-sync-bench: {verdict}; sync median/p90 ms: " + ", ".join(parts)
            + (f"; rss steady/peak MiB {rss['steady_median_mb']:.0f}/{rss['peak_mb'] or 0:.0f}"
               if rss else "")
            + (f"; load {load['min']:.1f}-{load['max']:.1f}" if load else ""))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(root: Path) -> str | None:
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


# ---------------------------------------------------------------- self-test

def self_test() -> None:
    assert quantile([float(x) for x in range(1, 43)], 0.9) == 38.0
    assert quantile([5.0], 0.9) == 5.0
    assert quantile([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 0.9) == 9.0
    src = "pub fn f(a: Int) -> Int = a\nfn g[T](\n  x: T,\n) -> T = {\n  x\n}\npub fn h() -> Int = 1\n"
    assert "pub fn f(a: Int, l1_probe: Int = 0)" in with_param(src, "f")
    assert "  x: T, l1_probe: Int = 0,\n)" in with_param(src, "g")
    assert "pub fn h(l1_probe: Int = 0)" in with_param(src, "h")
    assert ") -> T = {\n  let l1_probe_edit = 7\n  x" in with_let(src, "g", 7)
    assert edit_text(src, "sig", "f", 2) == src
    assert edit_text(src, "type", None, 1).endswith(PROBE_TYPE)
    types = src + 'pub fn eff_suffix(e: Eff) -> String = ""\n'
    both = compose(types, TYPES, {"b": 3, "d": 2})
    assert "eff_suffix(e: Eff, l1_probe" in both and not both.endswith(PROBE_TYPE)
    assert compose(types, TYPES, {"b": 3, "d": 1}) == both + PROBE_TYPE
    assert compose(types, TYPES, {"b": 2, "d": 1}) == types + PROBE_TYPE
    for bad in (lambda: with_let(src, "f", 1), lambda: fn_head(src + src, "f")):
        try:
            bad()
        except Harness:
            pass
        else:
            raise AssertionError("expected a refused anchor")
    assert limits(["L-ws-sig=5"])[("L-ws-sig", "sample", "sync")] == 5
    try:
        limits(["L-nope=5"])
    except Harness:
        pass
    else:
        raise AssertionError("expected an unknown line to be refused")
    assert pick(list("abcdefghij"), 3) == ["a", "d", "g"]
    assert pick(list("abc"), 0) == ["a", "b", "c"]
    # The real tree: every anchor this run would use matches exactly once.
    texts = {m: (ROOT / "selfhost/src" / f"{m}.dawn").read_text() for m in OPEN}
    for e, (mod, kind, loc) in SCENARIOS.items():
        assert edit_text(texts[mod], kind, loc, 1) != texts[mod], e
    fns = pub_fns(texts[TYPES])
    assert len(fns) == len(set(fns)) and fns, "pub fn names of check/types"
    for fn in fns:
        assert PROBE_PARAM in with_param(texts[TYPES], fn), fn
    print(f"OK: lsp-sync-bench self-test ({len(fns)} pub fns of check/types locatable)")


# --------------------------------------------------------------------- main

def parse(argv: list[str]):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jar", type=Path, help="jar under test (judged against the lines)")
    ap.add_argument("--std", type=Path, help="DAWN_STD for --jar (default: the jar's embedded std)")
    ap.add_argument("--baseline", type=Path, help="second jar, run interleaved for paired differences")
    ap.add_argument("--baseline-std", type=Path, help="DAWN_STD for --baseline")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="checkout whose selfhost/ is the workspace (default: this one)")
    ap.add_argument("--scenarios", default="abcd", help="subset of abcd (default abcd; '' for none)")
    ap.add_argument("--passes", type=int, default=6, help="fresh server sessions for the scenarios")
    ap.add_argument("--warm", type=int, default=3, help="unrecorded rounds per session")
    ap.add_argument("--rounds", type=int, default=7, help="recorded rounds per session")
    ap.add_argument("--sample", type=int, default=0,
                    help="pub fns of check/types to edit: 0 all (default), N evenly spread, -1 none")
    ap.add_argument("--sample-reps", type=int, default=1, help="add/remove pairs per function")
    ap.add_argument("--line", action="append", default=[], metavar="NAME=MS",
                    help="override a line (L-edit, L-ws-body, L-ws-sig, L-ws-type)")
    ap.add_argument("--load-max", type=float, default=4.0, help="pause while 1-min loadavg exceeds this")
    ap.add_argument("--load-poll", type=float, default=20.0)
    ap.add_argument("--load-timeout", type=float, default=3600.0,
                    help="give up (status 3) after this many seconds of pausing in total")
    # One string split on blanks, written --jvm='-Xss512m ...': argparse takes a
    # list item that starts with '-' for the next option, so a list of JVM flags
    # could never be passed at all.
    ap.add_argument("--jvm", type=str.split, default=JVM_OPTS, metavar="'OPTS'",
                    help="JVM options for the server under test, one blank-separated string")
    ap.add_argument("--baseline-jvm", type=str.split, metavar="'OPTS'",
                    help="JVM options for --baseline (default: --jvm); the same jar on both sides "
                         "with two option sets compares collectors")
    ap.add_argument("--out", type=Path, help="JSON report (default: stdout)")
    ap.add_argument("--log", type=Path, help="also append progress lines here")
    ap.add_argument("--self-test", action="store_true", help="check the edit logic and anchors, no JVM")
    ap.add_argument("--rejudge", type=Path, metavar="JSON",
                    help="judge a saved report against the lines (with any --line) instead of measuring")
    args = ap.parse_args(argv)
    if args.self_test or args.rejudge:
        return args
    if args.jar is None:
        ap.error("--jar is required")
    for p in [args.jar] + ([args.baseline] if args.baseline else []):
        if not p.is_file():
            ap.error(f"no such jar: {p}")
    if not set(args.scenarios) <= set(SCENARIOS) or len(set(args.scenarios)) != len(args.scenarios):
        ap.error(f"--scenarios {args.scenarios!r}: letters of abcd, each once")
    args.scenarios = list(args.scenarios)
    args.root = args.root.resolve()
    if not args.scenarios and args.sample < 0:
        ap.error("nothing to measure")
    return args


def main(argv: list[str]) -> int:
    args = parse(argv)
    if args.self_test:
        self_test()
        return 0
    try:
        if args.rejudge:
            rep = json.loads(args.rejudge.read_text())
            rep["lines"] = judge(rep["results"]["subject"], limits(args.line))
            rep["ok"] = all(x["ok"] for x in rep["lines"])
            print(one_line(rep))
            return 0 if rep["ok"] else 1
        bench = Bench(args)
        rep = bench.run()
    except Harness as e:
        print(f"lsp-sync-bench: error: {e}", file=sys.stderr)
        return 2
    except LoadTimeout as e:
        print(f"lsp-sync-bench: load guard: {e}", file=sys.stderr)
        return 3
    text = json.dumps(rep, indent=1)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)
    print(one_line(rep), file=sys.stderr if not args.out else sys.stdout)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

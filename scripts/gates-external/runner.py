#!/usr/bin/env python3
"""Orchestrate an external gate run: plan, schedule, run, bundle.

run.sh is the entry point; this is its body. The split of responsibilities is
the point of the design, so it is spelled out:

  gatesplan.py   WHAT runs: every job and step of gates.yml at the tree,
                 with each `uses:` resolved to a replacement id, or a refusal
  backend_*.py   WHERE and HOW: one job at a time, given the tree and the
                 artifact store, returns an exit code and output digests per
                 run step (the contract is in backend_local.py's docstring)
  bundle.py      WHAT IT MEANS: the schema, the leak filter and `complete`
  this file      WHEN: jobs start in gates.yml order (which is descending
                 expected duration), up to --jobs at once; a job with `needs:`
                 waits for them and then runs whatever they returned, as
                 `if: always()` asks

Resuming (--resume OUT). A controller can die mid-run (an SSH drop that
takes the terminal with it, a killed shell) while a backend's jobs keep
running elsewhere. The first run writes OUT/invocation.json; --resume OUT
reads it back, so the resumed run plans the same commit with the same
options and only --jobs may differ, and asks the backend to reuse its run.
Only a backend that says RESUMABLE can: the local one runs jobs as children
of this process, so nothing outlives it. The backend's finished() hands back
the jobs that ended while no controller was watching; they are marked done
without taking a worker slot, and the rest are scheduled as usual (the
backend waits for one still running rather than starting it again).

Things that are useful locally but must not reach the bundle (timings, the
memory peak, per-job exit codes, the paths of the logs) go to summary.json
and the terminal. The bundle is written only by bundle.build, which refuses
rather than trims.
"""

import argparse
import concurrent.futures
import importlib
import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bundle as bundle_mod  # noqa: E402
import gatesplan  # noqa: E402


class MemoryWatch:
    """Peak of MemTotal - MemAvailable, sampled every two seconds."""

    def __init__(self):
        self.baseline = self._used()
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    @staticmethod
    def _used():
        try:
            fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
            total = int(fields["MemTotal"].split()[0])
            available = int(fields["MemAvailable"].split()[0])
            return (total - available) * 1024
        except (OSError, KeyError, ValueError):
            return 0

    def _loop(self):
        while not self._stop.wait(2):
            self.peak = max(self.peak, self._used())

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--out", help="default with --prefix: <prefix>/out/<full sha>")
    parser.add_argument("--prefix", help="run inside this prefix (prefix.py); passed to the "
                        "backend as --backend-opt prefix=DIR")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--repo", default=str(HERE.parents[1]))
    parser.add_argument("--only", default="",
                        help="comma-separated job ids; the rest are recorded as not executed")
    parser.add_argument("--backend-opt", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan (jobs, needs, run steps, substitutions) and stop")
    parser.add_argument("--resume", metavar="OUT",
                        help="continue the run whose --out was OUT, with its recorded options")
    argv = sys.argv[1:]
    if "--resume" in argv:
        # The recorded invocation supplies every required option; --jobs may
        # be given again, anything else is refused below.
        index = argv.index("--resume")
        if index + 1 >= len(argv):
            parser.error("--resume needs a value")
        record = Path(argv[index + 1]) / "invocation.json"
        try:
            saved = json.loads(record.read_text())
        except (OSError, ValueError) as error:
            print(f"gates-external: cannot resume: {record}: {error}", file=sys.stderr)
            return 2
        extra = [a for a in argv[:index] + argv[index + 2:]]
        if any(a != "--jobs" and a.startswith("--") for a in extra):
            print("gates-external: --resume takes only --jobs besides it; the rest comes from "
                  f"{record}", file=sys.stderr)
            return 2
        argv = saved["argv"] + extra + ["--resume", argv[index + 1]]
    args = parser.parse_args(argv)

    started = time.monotonic()
    if not args.out and not args.prefix:
        print("gates-external: --out is required without --prefix", file=sys.stderr)
        return 2
    log_lock = threading.Lock()

    def log(message):
        with log_lock:
            print(f"[{time.monotonic() - started:7.0f}s] {message}", flush=True)

    try:
        plan = gatesplan.plan_at(args.repo, args.sha)
    except gatesplan.PlanError as error:
        print(f"gates-external: refusing to run: {error}", file=sys.stderr)
        return 2
    jobs = plan["jobs"]
    out = Path(args.out or Path(args.prefix) / "out" / plan["tree"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    artifacts = out / "artifacts"
    artifacts.mkdir(exist_ok=True)
    if args.dry_run:
        print(f"tree {plan['tree']}  gates.yml blob {plan['gates_blob']}")
        rows = gatesplan.substitution_rows(jobs)
        for row in rows:
            print(f"substitution  {row['subject']:36} -> {row['replacement']}")
        for job in jobs:
            runs = [a for a in job["actions"] if a["kind"] == "run"]
            needs = ",".join(job["needs"]) or "-"
            print(f"job  {job['id']:38} needs {needs:14} run steps {len(runs)}")
        print(f"{len(jobs)} gate jobs, {len(gatesplan.run_commands(jobs))} run steps; "
              f"plan job {'substituted by external-all' if any(j.get('plan_substituted') for j in jobs) else 'absent'}")
        return 0
    only = {j for j in args.only.split(",") if j}
    unknown = only - {j["id"] for j in jobs}
    if unknown:
        print(f"gates-external: --only names unknown jobs: {sorted(unknown)}", file=sys.stderr)
        return 2
    options = {}
    for item in args.backend_opt:
        key, sep, value = item.partition("=")
        if not sep:
            print(f"gates-external: --backend-opt wants KEY=VALUE, got {item!r}", file=sys.stderr)
            return 2
        options[key] = value
    if args.prefix:
        options.setdefault("prefix", str(Path(args.prefix).resolve()))
    try:
        module = importlib.import_module(f"backend_{args.backend}")
    except ImportError as error:
        print(f"gates-external: no backend {args.backend!r} ({error})", file=sys.stderr)
        return 2
    if args.resume:
        if Path(args.resume).resolve() != out:
            print(f"gates-external: --resume {args.resume} is not this run's out ({out})",
                  file=sys.stderr)
            return 2
        if not getattr(module, "RESUMABLE", False):
            print(f"gates-external: the {args.backend} backend cannot resume a run",
                  file=sys.stderr)
            return 2
        options["resume"] = "1"
    else:
        # Everything but --jobs, which a resumed run may change. Paths are
        # made absolute so the record does not depend on the shell's cwd.
        recorded = ["--sha", plan["tree"], "--backend", args.backend, "--out", str(out),
                    "--repo", str(Path(args.repo).resolve())]
        if args.prefix:
            recorded += ["--prefix", str(Path(args.prefix).resolve())]
        if args.only:
            recorded += ["--only", args.only]
        for item in args.backend_opt:
            recorded += ["--backend-opt", item]
        (out / "invocation.json").write_text(json.dumps({"argv": recorded}, indent=2) + "\n")
    backend = module.create({"repo": Path(args.repo).resolve(), "tree": plan["tree"],
                             "out": out, "options": options, "log": log})
    log(f"tree {plan['tree']}, gates.yml blob {plan['gates_blob']}, {len(jobs)} jobs, "
        f"{len(gatesplan.run_commands(jobs))} run steps, backend {args.backend}, "
        f"--jobs {args.jobs}")

    memory = MemoryWatch()
    memory.start()
    results = {}
    timings = {}
    done = {j["id"]: threading.Event() for j in jobs}
    selected = [j for j in jobs if not only or j["id"] in only]

    def run(job):
        # `needs:` with `if: always()`: wait for the needed jobs to end, not
        # to succeed. gatesplan refuses any other job condition.
        for need in job["needs"]:
            done[need].wait()
        # The needed jobs' outcomes, for `${{ needs.<id>.result }}`. A job
        # that was never run here (--only) is "skipped", as on GitHub.
        job = dict(job, needs_results={
            need: ("skipped" if need not in results
                   else "success" if results[need]["ok"] else "failure")
            for need in job["needs"]})
        t0 = time.monotonic()
        log(f"start {job['id']}")
        try:
            results[job["id"]] = backend.run_job(job, artifacts)
        except Exception as error:  # a crashed job is a failed job, never a skipped one
            log(f"{job['id']} crashed in the backend: {type(error).__name__}: {error}")
            results[job["id"]] = {"steps": None, "ok": False}
        timings[job["id"]] = time.monotonic() - t0
        log(f"end {job['id']}: {'ok' if results[job['id']]['ok'] else 'FAILED'} "
            f"in {timings[job['id']]:.0f}s")
        done[job["id"]].set()

    try:
        backend.prepare()
        for job in jobs:
            if job not in selected:
                done[job["id"]].set()
        # Jobs an earlier controller of this run left finished: done, with
        # the result the backend read back, before any worker starts.
        earlier = backend.finished() if args.resume else {}
        for job_id, result in sorted(earlier.items()):
            if job_id in done and any(j["id"] == job_id for j in selected):
                results[job_id] = result
                timings[job_id] = 0
                done[job_id].set()
                log(f"collected {job_id} from the earlier controller: "
                    f"{'ok' if result['ok'] else 'FAILED'}")
        selected = [j for j in selected if j["id"] not in results]
        # Jobs with needs are submitted last so a waiting job never holds a
        # worker slot while the jobs it waits for are still queued.
        ordered = [j for j in selected if not j["needs"]] + [j for j in selected if j["needs"]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            for future in [pool.submit(run, job) for job in ordered]:
                future.result()
    finally:
        backend.cleanup()
        memory.stop()

    steps = []
    for job in jobs:
        run_actions = [a for a in job["actions"] if a["kind"] == "run"]
        got = (results.get(job["id"]) or {}).get("steps")
        if got is None or len(got) != len(run_actions):
            got = [{"executed": False, "exit_code": None, "stdout_sha256": None,
                    "stderr_sha256": None}] * len(run_actions)
        for action, result in zip(run_actions, got):
            steps.append({"job": job["id"], "name": action["name"],
                          "command": action["command"], **result})

    toolchain = backend.toolchain()
    try:
        bundle = bundle_mod.build(plan, steps, toolchain)
    except bundle_mod.BundleError as error:
        print(f"gates-external: the bundle was refused, nothing written:\n{error}",
              file=sys.stderr)
        return 3
    bundle_mod.write(bundle, out / "bundle.json")
    complete, reasons = bundle_mod.completeness(jobs, steps)

    wall = time.monotonic() - started
    summary = {
        "wall_seconds": round(wall),
        "memory_baseline_gib": round(memory.baseline / 2**30, 2),
        "memory_peak_gib": round(memory.peak / 2**30, 2),
        "jobs": {},
    }
    for job in jobs:
        mine = [s for s in steps if s["job"] == job["id"]]
        codes = [s["exit_code"] for s in mine]
        summary["jobs"][job["id"]] = {
            "ran": job["id"] in results,
            "ok": bool((results.get(job["id"]) or {}).get("ok")),
            "seconds": round(timings.get(job["id"], 0)),
            "step_exit_codes": codes,
        }
    summary["incomplete_reasons"] = reasons
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print()
    print(f"{'job':40} {'result':8} {'secs':>6}  step exit codes")
    for job_id, row in summary["jobs"].items():
        result = "skipped" if not row["ran"] else ("ok" if row["ok"] else "FAILED")
        codes = " ".join("-" if c is None else str(c) for c in row["step_exit_codes"])
        print(f"{job_id:40} {result:8} {row['seconds']:6}  {codes}")
    print()
    for reason in reasons:
        print(f"INCOMPLETE {reason}")
    print(f"wall clock {wall:.0f}s; memory in use: baseline "
          f"{summary['memory_baseline_gib']} GiB, peak {summary['memory_peak_gib']} GiB")
    print(f"bundle: {out / 'bundle.json'} (complete={str(complete).lower()})")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())

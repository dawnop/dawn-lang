#!/usr/bin/env python3
"""Report what a push to main costs in job-seconds, week against week.

gates.yml's `# push-total:` holds the sum of the budget CLAIMS, offline, on
every push (scripts/check-gate-budgets.py). Two things it cannot see, and
both have already drifted here unseen:

* what the pushes really cost. The claims bound it from above (the nightly
  audit holds each claim at or over its job's worst run), but a cap that
  holds while the real total climbs toward it is a trend nobody is shown.
  The pole's own arithmetic asked to be redone "when the job set changes";
  by 2026-09-25 the job set had grown past it by 4,300 job-seconds a push
  and nothing had said so.
* how often the path-triggered gates run. tile.yml left the push path on
  2026-09-11 because its paths had been touched on none of the thirty pushes
  before; from 09-12 to 09-24 it ran on 19 of 80, and on 6 of the 12 pushes
  of 09-24. A path total caps what one trigger costs, not how often it fires.

So the nightly budget job adds this: it reads the per-run records
scripts/gate-observations.py writes (the same API answers, through the same
reader, as the budget audit) for ci.yml and tile.yml over fourteen days, and
prints one Markdown table: pushes, full runs, the median job-seconds of a
successful push, its median span, the share of each job family, and the rate
at which tile.yml fires. The workflow puts the table in the step summary.

It exits 1, and the workflow opens an issue, when

* this week's median job-seconds per successful push is more than 10% over
  last week's, or
* tile.yml fired on more than one push in five this week.

Why these two and not a hard cap: a report is what this is, and the hard cap
is the push total, which a push cannot get past without saying so. These are
the two drifts the cap does not see. The thresholds are the ones the ruling
of 2026-09-25 set; they are constants below, not flags, so changing one is a
diff someone reads.

The families are job id prefixes, the grouping the 2026-09-25 research used:
`incremental-*`; the mutant matrices (syntax-mutants, builtin-type,
classfile-never-mutants and the shard-union check); the native differential
(native-diff-*, prev-diff-native, native-selfhost-tests); `contracts-*`; and
everything else, `plan` and ci.yml's `secrets` included.

    gate-totals.py --ci ci.json --tile tile.json    the table, exit 1 on drift
    gate-totals.py --selftest                       fixture weeks, each drift
                                                    required to go red

No network here and no token: the fetching is gate-observations.py's.
"""

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GROWTH_LIMIT = 0.10     # this week's median over last week's, as a fraction
TILE_RATE_LIMIT = 0.20  # tile.yml push triggers per ci.yml push to main
WEEK = timedelta(days=7)

FAMILIES = ("incremental", "mutants", "native", "contracts", "other")


def family(job):
    if job.startswith("incremental-"):
        return "incremental"
    if (job.startswith("syntax-mutants") or job.startswith("builtin-type")
            or job in ("classfile-never-mutants", "mutant-shards-complete")):
        return "mutants"
    if (job.startswith("native-diff") or job in ("prev-diff-native",
                                                  "native-selfhost-tests")):
        return "native"
    if job == "contracts" or job.startswith("contracts-"):
        return "contracts"
    return "other"


def when(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def pushes(report):
    return [run for run in report.get("per_run", []) if run.get("event") == "push"]


def week_of(runs, start, end):
    return [run for run in runs if start < when(run["created"]) <= end]


def summarise(ci_runs, tile_runs):
    full = [run for run in ci_runs if run.get("conclusion") == "success"]
    totals = [sum(run["jobs"].values()) for run in full]
    spans = [run["span"] for run in full if run.get("span") is not None]
    shares = dict.fromkeys(FAMILIES, 0)
    for run in full:
        for job, seconds in run["jobs"].items():
            shares[family(job)] += seconds
    tile_full = [sum(run["jobs"].values()) for run in tile_runs
                 if run.get("conclusion") == "success"]
    return {
        "pushes": len(ci_runs),
        "full": len(full),
        "median_total": statistics.median(totals) if totals else None,
        "median_span": statistics.median(spans) if spans else None,
        "family_seconds": shares,
        "tile": len(tile_runs),
        "tile_rate": len(tile_runs) / len(ci_runs) if ci_runs else None,
        "tile_median": statistics.median(tile_full) if tile_full else None,
    }


def judge(this, last):
    """-> the reasons this report should open an issue (empty when none)."""
    reasons = []
    if this["median_total"] is not None and last["median_total"]:
        growth = this["median_total"] / last["median_total"] - 1
        if growth > GROWTH_LIMIT:
            reasons.append(
                f"the median successful push cost {this['median_total']:,.0f}"
                f" job-seconds this week against {last['median_total']:,.0f}"
                f" last week, {growth:+.1%}, over the {GROWTH_LIMIT:.0%} limit")
    if this["tile_rate"] is not None and this["tile_rate"] > TILE_RATE_LIMIT:
        reasons.append(
            f"tile.yml ran on {this['tile']} of {this['pushes']} pushes to main"
            f" this week ({this['tile_rate']:.0%}), over the"
            f" {TILE_RATE_LIMIT:.0%} it left the push path on the premise of")
    return reasons


def number(value, unit=""):
    return "n/a" if value is None else f"{value:,.0f}{unit}"


def table(this, last, start, now):
    rows = [
        "| main, ci.yml | this week | last week |",
        "|---|---|---|",
        f"| pushes | {this['pushes']} | {last['pushes']} |",
        f"| successful (full-set) runs | {this['full']} | {last['full']} |",
        f"| median job-seconds per successful push |"
        f" {number(this['median_total'])} | {number(last['median_total'])} |",
        f"| median span, s | {number(this['median_span'])} |"
        f" {number(last['median_span'])} |",
        f"| tile.yml push triggers | {this['tile']}"
        f" ({'n/a' if this['tile_rate'] is None else format(this['tile_rate'], '.0%')})"
        f" | {last['tile']}"
        f" ({'n/a' if last['tile_rate'] is None else format(last['tile_rate'], '.0%')}) |",
        f"| median tile.yml job-seconds per successful trigger |"
        f" {number(this['tile_median'])} | {number(last['tile_median'])} |",
        "",
        "| family (job-seconds share of successful pushes) | this week | last week |",
        "|---|---|---|",
    ]
    for name in FAMILIES:
        cells = []
        for week in (this, last):
            whole = sum(week["family_seconds"].values())
            cells.append("n/a" if not whole
                         else f"{week['family_seconds'][name] / whole:.1%}")
        rows.append(f"| {name} | {cells[0]} | {cells[1]} |")
    rows.append("")
    rows.append(f"This week is {(now - WEEK).strftime('%Y-%m-%dT%H:%MZ')} .. "
                f"{now.strftime('%Y-%m-%dT%H:%MZ')}; last week the seven days before,"
                f" from {start.strftime('%Y-%m-%dT%H:%MZ')}. Job-seconds are"
                " `completed_at - started_at` of each successful job; span is run"
                " creation to its last job's finish.")
    return "\n".join(rows)


def report(ci, tile, now=None):
    """-> (markdown, reasons) from two gate-observations.py reports."""
    now = now or when(ci["generated"])
    start = now - 2 * WEEK
    ci_runs, tile_runs = pushes(ci), pushes(tile)
    this = summarise(week_of(ci_runs, now - WEEK, now), week_of(tile_runs, now - WEEK, now))
    last = summarise(week_of(ci_runs, start, now - WEEK),
                     week_of(tile_runs, start, now - WEEK))
    reasons = judge(this, last)
    text = "## Gate job-seconds per push to main\n\n" + table(this, last, start, now)
    if reasons:
        text += "\n\n**Over a limit:**\n\n" + "\n".join(f"- {r}" for r in reasons)
    return text + "\n", reasons


# --- self-test -------------------------------------------------------------

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _run(days_ago, total, event="push", conclusion="success", jobs=None):
    stamp = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs = jobs or {"incremental-1": total // 4, "syntax-mutants-1": total // 4,
                    "native-diff-1": total // 4, "test": total - 3 * (total // 4)}
    return {"id": int(days_ago * 1000), "created": stamp, "event": event,
            "conclusion": conclusion, "span": 1600, "jobs": jobs}


def _weeks(this_total, last_total, tile_this=1, pushes=10):
    ci = [_run(0.5 + i * 0.6, this_total) for i in range(pushes)]
    ci += [_run(7.5 + i * 0.6, last_total) for i in range(pushes)]
    ci.append(_run(1.0, 99999, conclusion="cancelled"))   # a cancelled run:
    ci.append(_run(1.0, 99999, event="pull_request"))     # counted, not added
    tile = [_run(0.5 + i, 4800, jobs={"golden-1": 4800}) for i in range(tile_this)]
    tile.append(_run(2.0, 4800, event="schedule", jobs={"golden-1": 4800}))
    return ({"generated": NOW.isoformat(), "per_run": ci},
            {"generated": NOW.isoformat(), "per_run": tile})


def selftest():
    cases = [
        ("a steady week", _weeks(21600, 21600), False),
        ("growth of 9%", _weeks(23544, 21600), False),
        ("growth of 15%", _weeks(24840, 21600), True),
        ("tile.yml on 3 of 11 pushes (27%)", _weeks(21600, 21600, tile_this=3), True),
        ("tile.yml on 2 of 11 pushes (18%)", _weeks(21600, 21600, tile_this=2), False),
        ("no last week to compare with", ({"generated": NOW.isoformat(),
          "per_run": [_run(1, 30000)]}, {"per_run": []}), False),
    ]
    failures = []
    for label, (ci, tile), want_red in cases:
        text, reasons = report(ci, tile, NOW)
        if bool(reasons) != want_red:
            failures.append(f"{label}: expected {'red' if want_red else 'green'},"
                            f" got {reasons or 'green'}")
        else:
            print(f"  {'refused' if want_red else 'accepted'}: {label}")
    # The cancelled run counts as a push and adds nothing; the pull request
    # run and the scheduled tile run count as neither.
    text, _ = report(*_weeks(21600, 21600), NOW)
    if "| pushes | 11 | 10 |" not in text or "| successful (full-set) runs | 10 | 10 |" not in text:
        failures.append("pushes and full runs are not counted as documented:\n" + text)
    if "| median job-seconds per successful push | 21,600 | 21,600 |" not in text:
        failures.append("the median total is not the successful runs' median:\n" + text)
    wanted = {"incremental-7-2": "incremental", "builtin-type-1": "mutants",
              "classfile-never-mutants": "mutants", "prev-diff-native": "native",
              "prev-diff": "other", "contracts-2": "contracts",
              "native-selfhost-tests": "native", "secrets": "other"}
    for job, name in wanted.items():
        if family(job) != name:
            failures.append(f"{job} is in family {family(job)}, not {name}")
    for failure in failures:
        print(f"SELFTEST FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"selftest: {len(cases)} fixture weeks and the family table as documented")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ci", type=Path, help="gate-observations.py report of ci.yml")
    ap.add_argument("--tile", type=Path, help="gate-observations.py report of tile.yml")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.ci or not args.tile:
        ap.error("--ci and --tile are both required")
    ci = json.loads(args.ci.read_text(encoding="utf-8"))
    tile = json.loads(args.tile.read_text(encoding="utf-8"))
    for name, doc in (("--ci", ci), ("--tile", tile)):
        if "per_run" not in doc:
            print(f"{name}: no per_run records; written by an older"
                  " gate-observations.py?", file=sys.stderr)
            return 2
    text, reasons = report(ci, tile)
    print(text)
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())

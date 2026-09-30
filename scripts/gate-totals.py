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
successful push, that median against the declared push total, the median of
the current job shape, its median span, the share of each job family, and
the rate at which tile.yml really runs its shards. The workflow puts the
table in the step summary.

It exits 1, and the workflow opens an issue, when

* the measured cost reaches for the claim: the median over this week's
  successful pushes of job-seconds / gates.yml's push-total at that push's
  own commit is over 0.85, or rose more than 10 points on last week's; or
* the same job shape got dearer: among the successful pushes whose job set
  equals the newest one's, this week's median is more than 10% over last
  week's; or
* tile.yml ran its shards on more than one push in five this week.

WHY NOT THE PLAIN WEEK-ON-WEEK MEDIAN (the rule until 2026-09-30, issue
#231). It jumped with every change of job shape in either direction. The
09-29 report was +20.7%, and the research behind the fix found the jump was
about 35 contract steps parked in existing jobs on 09-22 and deleted again
on 09-27 (#259, #261); the reshards of the same week (36 -> 41 -> 45 -> 43 ->
35 jobs) moved the median by tens of seconds. By 10-04 the same rule would
have read about -44% and then held a 12,000 baseline against the next added
job. Both new rules follow the shape: a structural change must move the
push total with a Gate-Budget or Gate-Retire line anyway, so the ratio to
it moves with the shape, and the same-shape median compares like with like.
A shape change is printed as `shape changed at <sha>: N->M jobs, declared
X->Y` and judged by neither rule.

WHY A MINIMUM SAMPLE. The week before 09-29 had 6 successful pushes, and a
median of 6 is a thin baseline; a window whose pushes age out faster than
its tile runs also pushes the tile rate up while nothing got worse (the
research predicted 47% on 10-01 for exactly that reason). So each week
needs at least 10 successful pushes, and each shape at least 10 on both
sides, or the report is printed with "insufficient sample" and not judged.

WHAT A TILE TRIGGER IS. Since 2026-09-30 tile.yml skips its six shards on
a push whose git tree already passed it (its header has why), and such a
run is one ~20s job that concludes success. So a trigger is a push run in
which all six tile-golden shards concluded success; a deduplicated run is
counted in its own row and not in the rate. The 20% limit is kept and now
reads "the share of pushes that still run the shards".

A cut to the declared push total that the measured cost does not follow
turns the ratio-rise check red, by design: a claim lowered below what the
pushes still cost is the drift this report exists to show.

Why these and not a hard cap: a report is what this is, and the hard cap is
the push total, which a push cannot get past without saying so. The
thresholds are constants below, not flags, so changing one is a diff
someone reads.

The families are job id prefixes, the grouping the 2026-09-25 research used:
`incremental-*`; the mutant matrices (syntax-mutants, builtin-type,
classfile-never-mutants and the shard-union check); the native differential
(native-diff-*, prev-diff-native, native-selfhost-tests); `contracts-*`; and
everything else, `plan` and ci.yml's `secrets` included.

    gate-totals.py --ci ci.json --tile tile.json    the table, exit 1 on drift
    gate-totals.py --self-test                      fixture weeks, each drift
                                                    required to go red
                                                    (--selftest is the same)

No network here and no token: the fetching is gate-observations.py's. The
push total at each run's commit is read with git (the nightly checkout has
the history); a commit git does not have counts as unknown, not as today's.
"""

import argparse
import importlib.util
import json
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GROWTH_LIMIT = 0.10       # same-shape median, this week over last, a fraction
RATIO_LIMIT = 0.85        # median measured / declared push-total
RATIO_RISE_LIMIT = 0.10   # that ratio, this week minus last week
TILE_RATE_LIMIT = 0.20    # tile.yml runs that ran the shards, per ci.yml push
MIN_SAMPLE = 10           # successful pushes a side must have to be judged
WEEK = timedelta(days=7)

TILE_SHARDS = tuple(f"tile-golden-{i}" for i in range(1, 7))
GATES = ".github/workflows/gates.yml"
HERE = Path(__file__).resolve().parent

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


def shape(run):
    """A run's job shape: the set of job ids that ran (a success runs all)."""
    return frozenset(run["jobs"])


def ran_shards(run):
    """A tile.yml run that really ran: all six shards concluded success."""
    return all(job in run.get("jobs", {}) for job in TILE_SHARDS)


def median(values):
    return statistics.median(values) if values else None


class DeclaredAt:
    """gates.yml's `# push-total:` at a commit, read with git once per sha.

    The line is read by check-gate-budgets.py's read_total, the reader the
    tree gate and the trailer check share, so the three cannot disagree
    about what it says.
    """

    def __init__(self, git_dir=HERE.parent):
        spec = importlib.util.spec_from_file_location(
            "check_gate_budgets", HERE / "check-gate-budgets.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.read_total = module.read_total
        self.git_dir = git_dir
        self.cache = {}

    def __call__(self, sha):
        if not sha:
            return None
        if sha not in self.cache:
            proc = subprocess.run(
                ["git", "-C", str(self.git_dir), "show", f"{sha}:{GATES}"],
                capture_output=True, text=True, check=False)
            value = None
            if proc.returncode == 0:
                _problems, value = self.read_total(proc.stdout, "gates.yml",
                                                   "push-total")
            self.cache[sha] = value
        return self.cache[sha]


def summarise(ci_runs, tile_runs, declared):
    full = [run for run in ci_runs if run.get("conclusion") == "success"]
    totals = [sum(run["jobs"].values()) for run in full]
    spans = [run["span"] for run in full if run.get("span") is not None]
    shares = dict.fromkeys(FAMILIES, 0)
    for run in full:
        for job, seconds in run["jobs"].items():
            shares[family(job)] += seconds
    ratios = []
    for run in full:
        claim = declared(run.get("head_sha"))
        if claim:
            ratios.append(sum(run["jobs"].values()) / claim)
    executed = [run for run in tile_runs
                if run.get("conclusion") == "success" and ran_shards(run)]
    deduped = [run for run in tile_runs
               if run.get("conclusion") == "success" and not ran_shards(run)
               and not any(job.startswith("tile-golden-") for job in run["jobs"])]
    return {
        "pushes": len(ci_runs),
        "full": full,
        "median_total": median(totals),
        "median_span": median(spans),
        "family_seconds": shares,
        "ratio": median(ratios),
        "ratio_n": len(ratios),
        "tile_runs": len(tile_runs),
        "tile": len(executed),
        "tile_deduped": len(deduped),
        "tile_rate": len(executed) / len(ci_runs) if ci_runs else None,
        "tile_median": median([sum(run["jobs"].values()) for run in executed]),
    }


def same_shape(this, last):
    """-> (the newest shape, its runs this week, its runs last week)."""
    if not this["full"]:
        return None, [], []
    newest = max(this["full"], key=lambda run: when(run["created"]))
    current = shape(newest)
    return (current,
            [run for run in this["full"] if shape(run) == current],
            [run for run in last["full"] if shape(run) == current])


def shape_changes(ci_runs, declared):
    """`shape changed at <sha>: N->M jobs, declared X->Y`, oldest first."""
    lines = []
    previous = None
    full = sorted((run for run in ci_runs if run.get("conclusion") == "success"),
                  key=lambda run: when(run["created"]))
    for run in full:
        if previous is not None and shape(run) != shape(previous):
            before = declared(previous.get("head_sha"))
            after = declared(run.get("head_sha"))
            lines.append(
                f"shape changed at {(run.get('head_sha') or '?')[:8]}:"
                f" {len(shape(previous))}->{len(shape(run))} jobs,"
                f" declared {number(before)}->{number(after)}")
        previous = run
    return lines


def judge(this, last):
    """-> (reasons to open an issue, notes that are only reported, and the
    reasons' stable keys for the verdict line the nightly issue step
    compares)."""
    reasons, notes, keys = [], [], []
    if len(this["full"]) < MIN_SAMPLE or len(last["full"]) < MIN_SAMPLE:
        notes.append(
            f"insufficient sample: {len(this['full'])} successful pushes this"
            f" week and {len(last['full'])} last week, at least {MIN_SAMPLE}"
            " each; reported, not judged")
        return reasons, notes, keys
    if this["ratio_n"] < MIN_SAMPLE:
        notes.append(f"insufficient sample for the declared ratio:"
                     f" {this['ratio_n']} pushes with a push total this week")
    else:
        if this["ratio"] > RATIO_LIMIT:
            keys.append("ratio")
            reasons.append(
                f"the median successful push cost {this['ratio']:.2f} of the"
                f" declared push total this week, over {RATIO_LIMIT:.2f}")
        if last["ratio_n"] >= MIN_SAMPLE and (
                this["ratio"] - last["ratio"] > RATIO_RISE_LIMIT):
            keys.append("ratio-rise")
            reasons.append(
                f"the median measured / declared ratio rose from"
                f" {last['ratio']:.2f} to {this['ratio']:.2f}, more than"
                f" {RATIO_RISE_LIMIT * 100:.0f} points")
    current, now, before = same_shape(this, last)
    if len(now) < MIN_SAMPLE or len(before) < MIN_SAMPLE:
        notes.append(
            f"insufficient sample for the same-shape median: {len(now)} pushes"
            f" this week and {len(before)} last week of the current"
            f" {len(current or ())}-job shape, at least {MIN_SAMPLE} each")
    else:
        this_median = median([sum(run["jobs"].values()) for run in now])
        last_median = median([sum(run["jobs"].values()) for run in before])
        growth = this_median / last_median - 1
        if growth > GROWTH_LIMIT:
            keys.append("shape-growth")
            reasons.append(
                f"the {len(current)}-job shape cost {this_median:,.0f}"
                f" job-seconds a successful push this week against"
                f" {last_median:,.0f} last week, {growth:+.1%}, over the"
                f" {GROWTH_LIMIT:.0%} limit")
    if this["tile_rate"] is not None and this["tile_rate"] > TILE_RATE_LIMIT:
        keys.append("tile")
        reasons.append(
            f"tile.yml ran its shards on {this['tile']} of {this['pushes']}"
            f" pushes to main this week ({this['tile_rate']:.0%}), over the"
            f" {TILE_RATE_LIMIT:.0%} it left the push path on the premise of")
    return reasons, notes, keys


def number(value, unit=""):
    return "n/a" if value is None else f"{value:,.0f}{unit}"


def fraction(value):
    return "n/a" if value is None else f"{value:.2f}"


def table(this, last, start, now):
    current, same_now, same_before = same_shape(this, last)
    same = [median([sum(run["jobs"].values()) for run in runs])
            for runs in (same_now, same_before)]
    rows = [
        "| main, ci.yml | this week | last week |",
        "|---|---|---|",
        f"| pushes | {this['pushes']} | {last['pushes']} |",
        f"| successful (full-set) runs | {len(this['full'])} | {len(last['full'])} |",
        f"| median job-seconds per successful push |"
        f" {number(this['median_total'])} | {number(last['median_total'])} |",
        f"| median of job-seconds / declared push-total |"
        f" {fraction(this['ratio'])} | {fraction(last['ratio'])} |",
        f"| median job-seconds, current {len(current or ())}-job shape |"
        f" {number(same[0])} ({len(same_now)}) | {number(same[1])} ({len(same_before)}) |",
        f"| median span, s | {number(this['median_span'])} |"
        f" {number(last['median_span'])} |",
        f"| tile.yml push runs that ran the shards | {this['tile']}"
        f" ({'n/a' if this['tile_rate'] is None else format(this['tile_rate'], '.0%')})"
        f" | {last['tile']}"
        f" ({'n/a' if last['tile_rate'] is None else format(last['tile_rate'], '.0%')}) |",
        f"| tile.yml push runs skipped as an already verified tree |"
        f" {this['tile_deduped']} | {last['tile_deduped']} |",
        f"| median tile.yml job-seconds per run of the shards |"
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
                " creation to its last job's finish. The declared push total is"
                " gates.yml's `# push-total:` at each run's own commit; a shape is"
                " a run's set of job ids.")
    return "\n".join(rows)


def report(ci, tile, now=None, declared=None):
    """-> (markdown, reasons) from two gate-observations.py reports."""
    now = now or when(ci["generated"])
    declared = declared or DeclaredAt()
    start = now - 2 * WEEK
    ci_runs, tile_runs = pushes(ci), pushes(tile)
    this = summarise(week_of(ci_runs, now - WEEK, now),
                     week_of(tile_runs, now - WEEK, now), declared)
    last = summarise(week_of(ci_runs, start, now - WEEK),
                     week_of(tile_runs, start, now - WEEK), declared)
    reasons, notes, keys = judge(this, last)
    text = "## Gate job-seconds per push to main\n\n" + table(this, last, start, now)
    changes = shape_changes(week_of(ci_runs, start, now), declared)
    if changes:
        text += "\n\n**Job shape changes in the fourteen days** (judged by neither rule):\n\n"
        text += "\n".join(f"- {line}" for line in changes)
    if notes:
        text += "\n\n**Not judged:**\n\n" + "\n".join(f"- {n}" for n in notes)
    if reasons:
        text += "\n\n**Over a limit:**\n\n" + "\n".join(f"- {r}" for r in reasons)
        # Which limits, not by how much: the nightly issue step comments
        # again only when this line differs from the last comment's.
        text += f"\n\n<!-- verdict: {','.join(keys)} -->"
    return text + "\n", reasons


# --- self-test -------------------------------------------------------------

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
JOBS4 = ("incremental-1", "syntax-mutants-1", "native-diff-1", "test")


def _jobs(total, names=JOBS4):
    share = total // len(names)
    jobs = {name: share for name in names}
    jobs[names[-1]] = total - share * (len(names) - 1)
    return jobs


def _run(days_ago, total, event="push", conclusion="success", jobs=None,
         sha=None, now=NOW):
    stamp = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": int(days_ago * 1000), "created": stamp, "event": event,
            "conclusion": conclusion, "span": 1600,
            "head_sha": sha or f"{int(days_ago * 1000):040d}",
            "jobs": jobs or _jobs(total)}


def _declared(value):
    return lambda sha: value


def _tile(days_ago, deduped=False, now=NOW):
    jobs = ({"dedupe": 20} if deduped else
            {"dedupe": 20, **{name: 800 for name in TILE_SHARDS},
             "tile-shards-complete": 30})
    return _run(days_ago, 0, jobs=jobs, now=now)


def _weeks(this_total, last_total, tile_this=1, pushes=10, deduped=0):
    ci = [_run(0.5 + i * 0.6, this_total) for i in range(pushes)]
    ci += [_run(7.5 + i * 0.6, last_total) for i in range(pushes)]
    ci.append(_run(1.0, 99999, conclusion="cancelled"))   # a cancelled run:
    ci.append(_run(1.0, 99999, event="pull_request"))     # counted, not added
    tile = [_tile(0.5 + i * 0.5) for i in range(tile_this)]
    tile += [_tile(0.7 + i * 0.5, deduped=True) for i in range(deduped)]
    tile.append(_run(2.0, 4800, event="schedule", jobs=_jobs(4800, TILE_SHARDS)))
    return ({"generated": NOW.isoformat(), "per_run": ci},
            {"generated": NOW.isoformat(), "per_run": tile})


# The 09-29 report, rebuilt from research-nightly-231 section one: the
# successful pushes of each shape with their medians, the push total each
# shape ran under (none before 09-25, when the line was added), and 19 tile
# runs that all ran the shards. `now` is that report's 2026-09-29T11:00:53Z.
REPORT_0929 = datetime(2026, 9, 29, 11, 0, 53, tzinfo=timezone.utc)
SHAPES_0929 = [
    # (successful pushes, jobs, median job-seconds, push total, days ago)
    (6, 36, 17714, None, (13.5, 7.2)),    # last week, before the slice
    (8, 36, 20177, None, (6.9, 5.9)),     # the slice steps parked, 09-22
    (26, 41, 21640, 26149, (5.8, 2.7)),   # the first reshard
    (7, 45, 21628, 26617, (2.6, 2.1)),    # the second reshard
    (2, 43, 16082, 22000, (2.0, 1.95)),   # K1
    (3, 35, 12011, 20516, (1.9, 1.5)),    # K2
]


def _shape_names(count):
    return tuple(f"job-{i:02d}" for i in range(count))


def _week_0929(last_pushes=6):
    ci, claims = [], {}
    for n, count, total, claim, (old, new) in SHAPES_0929:
        if count == 36 and old > 7:
            n = last_pushes
        for i in range(n):
            days = old - (old - new) * i / max(n - 1, 1)
            sha = f"{count:02d}{i:02d}{int(days * 1000):036d}"
            claims[sha] = claim
            ci.append(_run(days, total, jobs=_jobs(total, _shape_names(count)),
                           sha=sha, now=REPORT_0929))
    ci += [_run(3.0 + i * 0.3, 0, conclusion="failure", now=REPORT_0929)
           for i in range(11)]
    tile = [_tile(0.2 + i * 0.3, now=REPORT_0929) for i in range(19)]
    return ({"generated": REPORT_0929.isoformat(), "per_run": ci},
            {"generated": REPORT_0929.isoformat(), "per_run": tile},
            lambda sha: claims.get(sha))


def _cross_shape():
    """Last week 12 pushes of 35 jobs at 12,011 under 20,516; this week 12 of
    a new 40-job shape at 14,000 under a push total raised to 24,000. The
    median went up 16.6% and nothing is wrong: the push total moved too."""
    claims = {}
    ci = []
    for i in range(12):
        sha = f"a{i:039d}"
        claims[sha] = 20516
        ci.append(_run(8 + i * 0.4, 12011, jobs=_jobs(12011, _shape_names(35)), sha=sha))
    for i in range(12):
        sha = f"b{i:039d}"
        claims[sha] = 24000
        ci.append(_run(0.5 + i * 0.4, 14000, jobs=_jobs(14000, _shape_names(40)), sha=sha))
    return ({"generated": NOW.isoformat(), "per_run": ci},
            {"generated": NOW.isoformat(), "per_run": []},
            lambda sha: claims.get(sha))


def selftest():
    cases = [
        ("a steady week", _weeks(21600, 21600), _declared(40000), False),
        ("same-shape growth of 9%", _weeks(23544, 21600), _declared(40000), False),
        ("same-shape growth of 15%", _weeks(24840, 21600), _declared(40000), True),
        ("measured at 0.90 of the declared total", _weeks(21600, 21600),
         _declared(24000), True),
        ("the push total cut, same cost: the ratio rose 11 points (0.54 -> 0.65)",
         _weeks(21600, 21600),
         lambda sha: 33000 if int(sha) < 7000 else 40000, True),
        ("the push total cut a little: the ratio rose 9 points (0.54 -> 0.63)",
         _weeks(21600, 21600),
         lambda sha: 34300 if int(sha) < 7000 else 40000, False),
        ("tile.yml ran the shards on 3 of 11 pushes (27%)",
         _weeks(21600, 21600, tile_this=3), _declared(40000), True),
        ("tile.yml ran the shards on 2 of 11 pushes (18%)",
         _weeks(21600, 21600, tile_this=2), _declared(40000), False),
        ("2 shard runs and 17 deduplicated of 11 pushes",
         _weeks(21600, 21600, tile_this=2, deduped=17), _declared(40000), False),
        ("growth of 50% on 9 pushes a week", _weeks(32400, 21600, pushes=9),
         _declared(40000), False),
        ("no last week to compare with", ({"generated": NOW.isoformat(),
          "per_run": [_run(1, 30000)]}, {"per_run": []}), _declared(40000), False),
    ]
    ci, tile, claims = _cross_shape()
    cases.append(("a new shape, +16.6%, with its push total raised",
                  (ci, tile), claims, False))
    ci, tile, claims = _week_0929()
    cases.append(("the 09-29 report: 6 successful pushes last week",
                  (ci, tile), claims, False))
    failures = []
    texts = {}
    for label, (ci, tile), declared, want_red in cases:
        now = REPORT_0929 if label.startswith("the 09-29") else NOW
        text, reasons = report(ci, tile, now, declared)
        texts[label] = text
        if bool(reasons) != want_red:
            failures.append(f"{label}: expected {'red' if want_red else 'green'},"
                            f" got {reasons or 'green'}")
        else:
            print(f"  {'refused' if want_red else 'accepted'}: {label}")
    # What the 09-29 report says instead of an issue, and that the same week
    # with a thick last week is still not judged on the shape or the ratio.
    text = texts["the 09-29 report: 6 successful pushes last week"]
    for wanted in ("insufficient sample: 46 successful pushes this week and 6 last week",
                   "shape changed at 4100", "36->41 jobs, declared n/a->26,149",
                   "45->43 jobs, declared 26,617->22,000",
                   "| tile.yml push runs that ran the shards | 19 (33%)"):
        if wanted not in text:
            failures.append(f"the 09-29 report lacks {wanted!r}:\n{text}")
    ci, tile, claims = _week_0929(last_pushes=12)
    text, reasons = report(ci, tile, REPORT_0929, claims)
    if ("insufficient sample for the same-shape median: 3 pushes this week"
            " and 0 last week of the current 35-job shape" not in text
            or any("job shape cost" in r or "ratio" in r for r in reasons)):
        failures.append("the 09-29 week with 12 pushes last week judged the"
                        f" shape or the ratio: {reasons}\n{text}")
    else:
        print("  accepted: the 09-29 week with 12 last week: shape and ratio"
              f" not judged, tile still red ({len(reasons)} reason)")
    if "<!-- verdict: shape-growth -->" not in texts["same-shape growth of 15%"]:
        failures.append("the verdict line does not name the one limit crossed:\n"
                        + texts["same-shape growth of 15%"])
    if "<!-- verdict:" in texts["a steady week"]:
        failures.append("a green report carries a verdict line")
    text = texts["a new shape, +16.6%, with its push total raised"]
    if "35->40 jobs, declared 20,516->24,000" not in text:
        failures.append(f"the shape change is not printed:\n{text}")
    # The cancelled run counts as a push and adds nothing; the pull request
    # run and the scheduled tile run count as neither; a deduplicated tile
    # run is its own row.
    text, _ = report(*_weeks(21600, 21600, deduped=3), NOW, _declared(40000))
    if "| pushes | 11 | 10 |" not in text or "| successful (full-set) runs | 10 | 10 |" not in text:
        failures.append("pushes and full runs are not counted as documented:\n" + text)
    if "| median job-seconds per successful push | 21,600 | 21,600 |" not in text:
        failures.append("the median total is not the successful runs' median:\n" + text)
    if ("| tile.yml push runs skipped as an already verified tree | 3 | 0 |" not in text
            or "| tile.yml push runs that ran the shards | 1 (9%)" not in text):
        failures.append("deduplicated tile runs are counted as triggers:\n" + text)
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
    print(f"selftest: {len(cases)} fixture weeks, the 09-29 replay and the"
          " family table as documented")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ci", type=Path, help="gate-observations.py report of ci.yml")
    ap.add_argument("--tile", type=Path, help="gate-observations.py report of tile.yml")
    ap.add_argument("--self-test", "--selftest", dest="selftest",
                    action="store_true")
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

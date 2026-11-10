"""Validate retained Actions responses and derive attempt observations offline.

Durations are never repaired. Step bounds allow two seconds of rounding.
Terminal metadata can lag steps; a lag over five minutes needs investigation.
Unknown image and checkout identities stay explicit and cannot prove a match.
"""

from collections import Counter, defaultdict
from datetime import datetime
import io
import math
import re
import statistics
import zipfile

SCHEMA = 2
CLOCK_TOLERANCE = 2
TERMINAL_LAG_LIMIT = 300


def instant(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return result.timestamp()


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    return {"n": len(values), "p50": statistics.median(values),
            "p95": values[math.ceil(.95 * len(values)) - 1],
            "max": values[-1]}


def pages_check(pages, field):
    """Keep page counts and reject missing, repeated or changing responses."""
    if not pages:
        raise ValueError(f"no {field} pages")
    items = [item for page in pages for item in page[field]]
    totals = {page["total_count"] for page in pages}
    ids = [item["id"] for item in items]
    if len(totals) != 1 or totals != {len(items)} or len(set(ids)) != len(ids):
        raise ValueError(f"{field} pagination mismatch: totals={sorted(totals)}, "
                         f"records={len(items)}, distinct={len(set(ids))}")
    return items, {"pages": len(pages), "total_count": len(items),
                   "records": len(items), "distinct": len(set(ids))}


def read_pages(repo, endpoint, field, fetch):
    """Retain every API response, then reconcile total_count and IDs."""
    pages = []
    page = 1
    while True:
        payload = fetch(["gh", "api", f"repos/{repo}/{endpoint}&per_page=100&page={page}"])
        pages.append(payload)
        if len(payload[field]) < 100:
            break
        page += 1
    pages_check(pages, field)
    return pages


def image_from_log(text):
    """Read the runner image, not the runner label or provisioner version."""
    image = re.search(r"\bImage:\s*(\S+)", text)
    version = re.search(r"\bImage:\s*\S+\s*\n[^\n]*?Version:\s*(\S+)", text)
    return {"image": image.group(1) if image else "unknown",
            "version": version.group(1) if version else "unknown"}


def headers_from_archive(payload):
    """Read bounded headers without extracting paths or guessing job names."""
    headers = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            with archive.open(member) as stream:
                text = stream.read(16384).decode("utf-8-sig", "replace")
            name = re.search(r"Complete job name:\s*([^\r\n]+)", text)
            if name is None or "unknown" in image_from_log(text).values():
                continue
            name = name.group(1).strip()
            if name in headers and image_from_log(headers[name]) != image_from_log(text):
                raise ValueError(f"conflicting image headers for {name}")
            headers.setdefault(name, text)
    return headers


def job_name(job):
    return job["name"].rsplit(" / ", 1)[-1].strip()


def classify(job, run, cutoff, seen):
    """Return classification, errors, D, Q; semantic keys ignore new job IDs."""
    errors = []
    start, end, created = (instant(job.get(key)) for key in
                           ("started_at", "completed_at", "created_at"))
    begin = instant(run["run_started_at"])
    duration = end - start if start is not None and end is not None else None
    queue = start - created if start is not None and created is not None else None
    conclusion = job.get("conclusion")
    executed = any(step["name"] == "Set up job" and
                   step.get("conclusion") == "success"
                   for step in job.get("steps", []))
    if conclusion == "skipped":
        return "skipped", errors, None, None
    if duration is not None and duration < 0:
        errors.append("negative_duration")
    if not errors and (end is None or end > cutoff):
        return "right_censored", errors, None, queue
    if not errors:
        # A rerun response may include earlier executions with fresh IDs.
        key = (run["id"], job["name"], job.get("started_at"),
               job.get("completed_at"), conclusion,
               tuple((s["name"], s.get("started_at"), s.get("completed_at"),
                      s.get("conclusion")) for s in job.get("steps", [])))
        if (key in seen or
                (run["run_attempt"] > 1 and start is not None and
                 start < begin - CLOCK_TOLERANCE) or
                job.get("run_attempt", run["run_attempt"]) != run["run_attempt"]):
            return "inherited", errors, None, None
        seen.add(key)
    if conclusion == "cancelled" and not executed and not errors:
        return "cancelled_unexecuted", errors, None, None
    if start is not None and start < begin - CLOCK_TOLERANCE:
        errors.append("job_before_attempt")
    if start is None or end is None:
        errors.append("missing_job_time")
    if queue is not None and queue < 0:
        errors.append("negative_queue")
    step_ends = []
    for step in job.get("steps", []):
        if step.get("conclusion") == "skipped":
            continue
        a, b = instant(step.get("started_at")), instant(step.get("completed_at"))
        if a is not None and b is not None:
            step_ends.append(b)
            if b < a:
                errors.append("negative_step_duration")
            if start is not None and a < start - CLOCK_TOLERANCE:
                errors.append("step_before_job")
            if end is not None and b > end + CLOCK_TOLERANCE:
                errors.append("step_after_job")
    if conclusion == "success":
        if not executed or not step_ends:
            errors.append("success_without_execution")
        elif end is not None and end - max(step_ends) > TERMINAL_LAG_LIMIT:
            errors.append("terminal_clock_conflict")
    if errors:
        return "data_quality_error", sorted(set(errors)), None, None
    return {"success": "success", "failure": "failure",
            "cancelled": "cancelled_executed"}.get(conclusion, "other"), [], duration, queue


def rebuild(report):
    """Recompute derived fields from raw records; never trust cached maxima."""
    if report.get("schema") != SCHEMA:
        raise ValueError("observation report lacks verifiable run/attempt/job "
                         "records; regenerate with gate-observations.py")
    cutoff = instant(report["until"])
    counts = {}
    listed, counts["runs"] = pages_check(report["raw_run_pages"], "workflow_runs")
    originals = {r["id"]: r for r in listed}
    since = instant(report.get("since"))
    if since is not None and since > cutoff:
        raise ValueError("observation window ends before it starts")
    window_ids = {r["id"] for r in listed if
                  (since is None or instant(r["created_at"]) >= since) and
                  instant(r["created_at"]) <= cutoff}
    selected = report.get("selected_run_ids", sorted(window_ids))
    if len(selected) != len(set(selected)) or not set(selected) <= {r["id"] for r in listed}:
        raise ValueError("selected original run IDs do not match enumeration")
    if since is not None and set(selected) != window_ids:
        raise ValueError("fixed window enumeration was truncated")
    expected = {run["id"]: run.get("run_attempt", 1) for run in listed if run["id"] in selected}
    raw = report["raw_attempts"]
    actual = [(x["run"]["id"], x["run"]["run_attempt"]) for x in raw]
    wanted = {(rid, attempt) for rid, last in expected.items()
              for attempt in range(1, last + 1)}
    if len(actual) != len(set(actual)) or set(actual) != wanted:
        raise ValueError("run/attempt coverage mismatch")
    records, attempts, errors, seen = [], [], [], set()
    for entry in sorted(raw, key=lambda x: (x["run"]["id"], x["run"]["run_attempt"])):
        run = entry["run"]
        rid, attempt = run["id"], run["run_attempt"]
        original_created = originals[rid]["created_at"]
        jobs, count = pages_check(entry["jobs_pages"], "jobs")
        counts[f"{rid}/{attempt}"] = count
        local = []
        steps = entry["steps"]
        if entry["input"] != run["head_sha"]:
            raise ValueError(f"run {rid}/{attempt} source input does not match head SHA")
        for job in jobs:
            if job.get("run_id", rid) != rid:
                raise ValueError(f"job {job['id']} belongs to a different run")
            state, issues, duration, queue = classify(job, run, cutoff, seen)
            name = job_name(job)
            image = image_from_log(entry.get("image_logs", {}).get(str(job["id"]), ""))
            if state == "success" and "unknown" in image.values():
                errors.append({"run": rid, "attempt": attempt, "job_id": job["id"],
                               "errors": ["unknown_image"]})
            row = {"run": rid, "attempt": attempt, "job_id": job["id"],
                   "name": name, "event": run["event"], "branch": run["head_branch"],
                   "head_sha": run["head_sha"], "input": entry["input"],
                   "created": original_created, "steps": (steps or {}).get(name),
                   "image": image, "classification": state, "errors": issues,
                   "conclusion": job.get("conclusion"), "D": duration, "Q": queue,
                   "started_at": job.get("started_at"),
                   "completed_at": job.get("completed_at")}
            terminal = [instant(s["completed_at"]) for s in job.get("steps", [])
                        if s.get("completed_at") and s.get("conclusion") != "skipped"]
            row["terminal_lag"] = (instant(job["completed_at"]) - max(terminal)
                                   if terminal and job.get("completed_at") else None)
            records.append(row)
            local.append(row)
            if issues:
                errors.append({"run": rid, "attempt": attempt,
                               "job_id": job["id"], "errors": issues})
        success = [r for r in local if r["classification"] == "success"]
        bill = [r for r in local if r["classification"] in
                ("success", "failure", "cancelled_executed", "other") and r["D"] is not None]
        names = [r["name"] for r in success]
        if steps is None and success:
            errors.append({"run": rid, "attempt": attempt, "errors": ["unknown_steps"]})
        if len(names) != len(set(names)):
            errors.append({"run": rid, "attempt": attempt, "errors": ["duplicate_job_name"]})
        expected_names = set(entry["expected_jobs"])
        complete = (steps is not None and bool(expected_names) and
                    expected_names <= set(names) and len(names) == len(set(names)))
        deduplicated = (report["workflow"] == "tile.yml" and
                        run.get("conclusion") == "success" and
                        set(names) == {"dedupe"} and
                        {r["name"] for r in local} == expected_names and
                        all(r["classification"] in ("success", "skipped") for r in local))
        ended = [instant(r["completed_at"]) for r in bill]
        last = max(ended) if ended else None
        full_jobs = [r for r in success if r["name"] in expected_names]
        attempts.append({"id": rid, "attempt": attempt, "event": run["event"],
                         "head_sha": run["head_sha"], "input": entry["input"],
                         "created": original_created, "full": complete,
                         "deduplicated": deduplicated,
                         "conclusion": run.get("conclusion") if complete or deduplicated else "incomplete",
                         "jobs": {r["name"]: r["D"] for r in success}, "steps": steps,
                         "S": last - instant(run["run_started_at"]) if last else None,
                         "span": last - instant(original_created) if last else None,
                         "W": sum(r["D"] for r in full_jobs) if complete else None,
                         "executed_W": sum(r["D"] for r in bill),
                         "classifications": dict(Counter(r["classification"] for r in local))})
    first = [r for r in attempts if r["attempt"] == 1]
    worst, where = {}, {}
    for r in first:
        for name, duration in r["jobs"].items():
            if duration > worst.get(name, -1):
                worst[name], where[name] = duration, r["id"]
    result = {**report, "records": records, "attempts": attempts,
              "per_run": first, "jobs": worst, "worst_run": where,
              "pagination": counts, "data_quality_errors": errors,
              "classifications": dict(Counter(r["classification"] for r in records))}
    result["groups"] = grouped(records, attempts)
    result["attempt_groups"] = attempt_groups(records, attempts)
    return result


def grouped(records, attempts):
    """Keep event, image/version, steps and input identity in every group."""
    groups = defaultdict(list)
    for r in records:
        if r["classification"] != "success":
            continue
        key = ("first" if r["attempt"] == 1 else "rerun", r["event"],
               r["name"], r["image"]["image"], r["image"]["version"],
               r["steps"], r["input"])
        groups[key].append(r)
    output = []
    for key, rows in sorted(groups.items(), key=lambda kv: repr(kv[0])):
        phase, event, name, image, version, steps, source = key
        output.append({"phase": phase, "event": event, "name": name,
                       "image": image, "image_version": version, "steps": steps,
                       "input": source, "D": stats([r["D"] for r in rows]),
                       "Q": stats([r["Q"] for r in rows if r["Q"] is not None]),
                       "runs": sorted({r["run"] for r in rows})})
    return output


def attempt_groups(records, attempts):
    groups = defaultdict(list)
    by_attempt = defaultdict(list)
    for row in records:
        by_attempt[row["run"], row["attempt"]].append(row)
    for attempt in attempts:
        identity = tuple(sorted((r["name"], r["steps"], r["image"]["image"],
                                 r["image"]["version"]) for r in
                                by_attempt[attempt["id"], attempt["attempt"]]))
        key = ("first" if attempt["attempt"] == 1 else "rerun",
               attempt["event"], attempt["input"], identity, attempt["full"])
        groups[key].append(attempt)
    return [{"phase": phase, "event": event, "input": source,
             "job_identities": identity, "full": full,
             "W": stats([r["W"] for r in rows if r["W"] is not None]),
             "S": stats([r["S"] for r in rows if r["S"] is not None]),
             "span": stats([r["span"] for r in rows if r["span"] is not None]),
             "executed_W": stats([r["executed_W"] for r in rows]),
             "attempts": [[r["id"], r["attempt"]] for r in rows]}
            for (phase, event, source, identity, full), rows in
            sorted(groups.items(), key=lambda kv: repr(kv[0]))]


def summary_lines(report):
    yield "classifications: " + ", ".join(f"{k}={v}" for k, v in sorted(report["classifications"].items()))
    for phase, predicate in (("first", lambda a: a == 1), ("rerun", lambda a: a > 1)):
        for event in sorted({r["event"] for r in report["records"]}):
            jobs = [r for r in report["records"] if predicate(r["attempt"]) and r["event"] == event]
            success = [r for r in jobs if r["classification"] == "success"]
            full = [r for r in report["attempts"] if predicate(r["attempt"]) and
                    r["event"] == event and r["full"]]
            yield (f"{phase} {event} descriptive totals (see identity groups): "
                   f"D={stats([r['D'] for r in success])} "
                   f"W={stats([r['W'] for r in full])} "
                   f"Q={stats([r['Q'] for r in success if r['Q'] is not None])} "
                   f"S={stats([r['S'] for r in full if r['S'] is not None])} "
                   f"span={stats([r['span'] for r in full if r['span'] is not None])}")
            for state in ("failure", "cancelled_executed", "cancelled_unexecuted", "right_censored"):
                rows = [r for r in jobs if r["classification"] == state]
                yield f"{phase} {event} {state}: records={len(rows)}, executed_W={sum(r['D'] or 0 for r in rows)}"

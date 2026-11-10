"""Offline controls for the Actions observation reader; no token or network."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
from pathlib import Path
import sys
import zipfile

from gate_observation_data import grouped, headers_from_archive, image_from_log, read_pages, rebuild, stats


def stamp(seconds):
    return (datetime(2026, 11, 1, tzinfo=timezone.utc) +
            timedelta(seconds=seconds)).isoformat()


def job(number=1, start=10, end=110, conclusion="success", name=None):
    return {"id": number, "run_id": 1, "run_attempt": 1,
            "name": name or f"gate-{number}", "created_at": stamp(0),
            "started_at": stamp(start), "completed_at": stamp(end),
            "status": "completed", "conclusion": conclusion,
            "steps": [{"name": "Set up job", "started_at": stamp(start),
                       "completed_at": stamp(start + 1), "conclusion": "success"},
                      {"name": "Complete job", "started_at": stamp(end - 3),
                       "completed_at": stamp(end - 2), "conclusion": conclusion}]}


def fixture(jobs=None):
    jobs = jobs if jobs is not None else [job()]
    run = {"id": 1, "run_attempt": 1, "created_at": stamp(0),
           "run_started_at": stamp(0), "event": "push", "head_branch": "main",
           "head_sha": "source-a", "conclusion": "success"}
    steps = {j["name"]: "steps-" + j["name"] for j in jobs}
    logs = {str(j["id"]): "Image: ubuntu-24.04\nVersion: 20261101.360.1\n" for j in jobs}
    entry = {"run": run, "jobs_pages": [{"total_count": len(jobs), "jobs": jobs}],
             "steps": steps, "expected_jobs": sorted(steps), "input": "source-a",
             "image_logs": logs}
    return {"schema": 2, "workflow": "ci.yml", "until": stamp(100000),
            "raw_run_pages": [{"total_count": 1, "workflow_runs": [deepcopy(run)]}],
            "raw_attempts": [entry]}


def rerun(report, begin):
    entry = deepcopy(report["raw_attempts"][0])
    entry["run"].update(run_attempt=2, run_started_at=stamp(begin),
                        created_at=stamp(begin - 1))
    for page in entry["jobs_pages"]:
        for row in page["jobs"]:
            old = str(row["id"])
            row["id"] += 1000
            row["run_attempt"] = 2
            entry["image_logs"][str(row["id"])] = entry["image_logs"][old]
    report["raw_run_pages"][0]["workflow_runs"][0]["run_attempt"] = 2
    report["raw_attempts"].append(entry)
    return entry


def selftest():
    checks = 0

    def require(condition, label):
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1
        print("  verified: " + label)

    clean = rebuild(fixture())
    require(clean["records"][0]["D"] == 100 and clean["attempts"][0]["W"] == 100,
            "valid execution D/W, separate from Q/S")
    require(clean["records"][0]["Q"] == 10 and clean["attempts"][0]["S"] == 110,
            "queue is not charged to job execution")
    before_attempt = fixture()
    before_attempt["raw_attempts"][0]["run"]["run_started_at"] = stamp(1000)
    got = rebuild(before_attempt)
    require(got["records"][0]["errors"] == ["job_before_attempt"] and
            got["attempts"][0]["S"] is None,
            "first attempt cannot bill a job before its own start or produce negative S")
    delayed = fixture()
    delayed["raw_attempts"][0]["run"]["run_started_at"] = stamp(5)
    got = rebuild(delayed)["attempts"][0]
    require(got["S"] == 105 and got["span"] == 110,
            "negative control: original creation and actual attempt dispatch stay separate")

    inherited = fixture([job(i) for i in range(1, 43)])
    rerun(inherited, 1000)
    got = rebuild(inherited)
    require(got["classifications"].get("inherited") == 42 and
            not got["attempts"][1]["jobs"], "42 inherited executions with new IDs are excluded")
    fresh = deepcopy(inherited)
    for row in fresh["raw_attempts"][1]["jobs_pages"][0]["jobs"]:
        row.update(started_at=stamp(1010), completed_at=stamp(1110), created_at=stamp(1000))
        for step in row["steps"]:
            for field in ("started_at", "completed_at"):
                step[field] = (datetime.fromisoformat(step[field]) + timedelta(seconds=1000)).isoformat()
    require(rebuild(fresh)["classifications"].get("success") == 84,
            "negative control: genuinely fresh rerun executions are retained")
    semantic = deepcopy(inherited)
    semantic["raw_attempts"][1]["run"]["run_started_at"] = stamp(0)
    require(rebuild(semantic)["classifications"].get("inherited") == 42,
            "semantic deduplication also catches overlap without earlier starts")

    negative = fixture([job(i) for i in range(1, 21)])
    for row in negative["raw_attempts"][0]["jobs_pages"][0]["jobs"]:
        row["completed_at"] = stamp(1)
    got = rebuild(negative)
    require(got["classifications"].get("data_quality_error") == 20 and not got["jobs"],
            "20 negative successful durations are errors, never zero or absolute values")
    require(rebuild(fixture([job(i) for i in range(1, 21)]))["classifications"]["success"] == 20,
            "negative control: positive successful durations remain observations")

    conflicts = fixture([job(i) for i in range(1, 69)])
    for row in conflicts["raw_attempts"][0]["jobs_pages"][0]["jobs"]:
        row["completed_at"] = stamp(3710)
    got = rebuild(conflicts)
    require(sum("terminal_clock_conflict" in e["errors"] for e in got["data_quality_errors"]) == 68,
            "68 positive durations with stage clock conflicts are isolated")
    require(rebuild(fixture([job(i) for i in range(1, 69)]))["classifications"]["success"] == 68,
            "negative control: aligned job and step clocks remain valid")
    outside = fixture()
    outside["raw_attempts"][0]["jobs_pages"][0]["jobs"][0]["steps"][-1]["completed_at"] = stamp(120)
    require("step_after_job" in rebuild(outside)["data_quality_errors"][0]["errors"],
            "steps outside the job clock bounds are errors")

    overnight = fixture()
    last = rerun(overnight, 84339)
    row = job(1001, start=85000, end=86590)
    row.update(run_attempt=2, created_at=stamp(84339), name="gate-1")
    last["jobs_pages"][0]["jobs"] = [row]
    got = rebuild(overnight)["attempts"][1]
    require(got["S"] == 2251 and got["span"] == 86590,
            "overnight cumulative span 86590 is separate from attempt S 2251")
    require(clean["attempts"][0]["S"] == clean["attempts"][0]["span"],
            "negative control: first attempt without dispatch delay has equal S and span")

    cancelled = job(conclusion="cancelled")
    cancelled["steps"] = []
    got = rebuild(fixture([cancelled]))
    require(got["records"][0]["classification"] == "cancelled_unexecuted" and
            got["records"][0]["D"] is None and not got["attempts"][0]["full"],
            "cancellation without execution is not successful zero seconds")
    require(rebuild(fixture([job(conclusion="cancelled")]))["records"][0]["D"] == 100,
            "negative control: executed cancellation keeps its resource cost")
    failed = rebuild(fixture([job(conclusion="failure")]))
    require(not failed["jobs"] and failed["attempts"][0]["executed_W"] == 100,
            "failure cost is retained outside successful duration distributions")
    clipped = fixture()
    clipped["until"] = stamp(100)
    require(rebuild(clipped)["classifications"] == {"right_censored": 1},
            "completion after cutoff is right censored even if API now says success")
    require(clean["classifications"] == {"success": 1},
            "negative control: completion before cutoff is observed")
    deduped = fixture([job(1, name="dedupe"),
                       job(2, name="tile-golden-1", conclusion="skipped"),
                       job(3, name="tile-shards-complete", conclusion="skipped")])
    deduped["workflow"] = "tile.yml"
    got = rebuild(deduped)["per_run"][0]
    require(got["deduplicated"] and got["conclusion"] == "success" and
            not got["full"] and got["W"] is None and got["executed_W"] == 100,
            "intentional deduplication remains countable without becoming full zero work")
    deduped["raw_attempts"][0]["jobs_pages"][0]["jobs"][1] = job(
        2, name="tile-golden-1", conclusion="cancelled")
    got = rebuild(deduped)["per_run"][0]
    require(not got["deduplicated"] and got["conclusion"] == "incomplete",
            "negative control: cancelled shards cannot masquerade as deduplication")

    broken_pages = fixture()
    broken_pages["raw_attempts"][0]["jobs_pages"][0]["total_count"] = 2
    try:
        rebuild(broken_pages)
    except ValueError:
        require(True, "missing jobs page is refused")
    else:
        require(False, "missing jobs page is refused")
    many = fixture([job(i) for i in range(1, 102)])
    page = many["raw_attempts"][0]["jobs_pages"][0]
    many["raw_attempts"][0]["jobs_pages"] = [
        {"total_count": 101, "jobs": page["jobs"][:100]},
        {"total_count": 101, "jobs": page["jobs"][100:]}]
    require(rebuild(many)["pagination"]["1/1"]["pages"] == 2,
            "negative control: all 101 jobs across two retained pages reconcile")
    missing_attempt = deepcopy(inherited)
    missing_attempt["raw_attempts"].pop()
    try:
        rebuild(missing_attempt)
    except ValueError:
        require(True, "missing attempt is refused even when job counts reconcile")
    else:
        require(False, "missing attempt is refused even when job counts reconcile")
    unknown = fixture()
    unknown["raw_attempts"][0]["image_logs"] = {}
    require(rebuild(unknown)["data_quality_errors"][0]["errors"] == ["unknown_image"],
            "missing image identity is explicit data quality failure")

    require(stats([1, 2, 100, 1000]) == {"n": 4, "p50": 51, "p95": 1000, "max": 1000},
            "P50 is median; P95 is nearest rank")
    require(image_from_log("Version: provisioner\nImage: ubuntu-24.04\nVersion: actual\n")["version"] == "actual",
            "image version is not the provisioner version")
    first = clean["records"][0]
    duplicate = {**first, "run": 2}
    require(len(grouped([first, duplicate], [])) == 1,
            "matching identities share one statistical group")
    for field, value in (("event", "pull_request"), ("steps", "older-shape"),
                         ("input", "source-b"), ("attempt", 2),
                         ("image", {"image": "ubuntu-26.04", "version": "new"}),
                         ("image", {"image": "ubuntu-24.04", "version": "other"})):
        require(len(grouped([first, {**duplicate, field: value}], [])) == 2,
                f"negative control: changing {field} separates statistical groups")
    for field, value in (("event", "pull_request"), ("head_sha", "source-b")):
        split = fixture()
        last = rerun(split, 1000)
        last["run"][field] = value
        # Reuse genuinely fresh job timestamps from the earlier control.
        last["jobs_pages"][0]["jobs"] = [deepcopy(fresh["raw_attempts"][1]["jobs_pages"][0]["jobs"][0])]
        last["input"] = last["run"]["head_sha"]
        require(len(rebuild(split)["groups"]) == 2, f"identity control: separate {field} groups")
    spec = importlib.util.spec_from_file_location("budget_reader", Path(__file__).with_name("check-gate-budgets.py"))
    budget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(budget)
    try:
        budget.load_reports([{"per_run": [], "jobs": {}}], {})
    except SystemExit:
        require(True, "legacy reports without verifiable raw records are refused")
    else:
        require(False, "legacy reports without verifiable raw records are refused")
    forged = fixture()
    forged.update(jobs={"gate-1": 0}, per_run=[])
    seen = budget.load_reports([forged], {"ci.yml": {"gate-1": "steps-gate-1"}})["ci.yml"]
    require(seen.for_file("gates.yml").get("gate-1") == 100,
            "observed audit recomputes from raw records rather than cached totals")
    spec = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("gate-observations.py"))
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    run_process, sleep = collector.subprocess.run, collector.time.sleep
    calls, waits = [], []

    def transient_then_success(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return collector.subprocess.CompletedProcess(args, 1, "", "HTTP 502")
        return collector.subprocess.CompletedProcess(args, 0, "response", "")

    try:
        collector.subprocess.run = transient_then_success
        collector.time.sleep = waits.append
        require(collector._gh(["gh", "api", "fixture"]) == "response" and
                len(calls) == 2 and waits == [collector.GH_RETRY_WAIT],
                "transient API failure retries without a real network or sleep")
        calls.clear()

        def forbidden(*args, **kwargs):
            calls.append(args)
            return collector.subprocess.CompletedProcess(args, 1, "", "HTTP 403")

        collector.subprocess.run = forbidden
        try:
            collector._gh(["gh", "api", "fixture"])
        except SystemExit:
            require(len(calls) == 1, "negative control: API refusal is final, not retried")
        else:
            require(False, "API refusal must not become a successful response")
        calls.clear()
        waits.clear()

        def binary_retry(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return collector.subprocess.CompletedProcess(args, 1, b"", b"HTTP 502")
            return collector.subprocess.CompletedProcess(args, 0, b"archive", b"")

        collector.subprocess.run = binary_retry
        require(collector._gh(["gh", "api", "fixture"], binary=True) == b"archive" and
                len(calls) == 2 and waits == [collector.GH_RETRY_WAIT],
                "binary archive retry preserves bytes and decodes error messages")
    finally:
        collector.subprocess.run, collector.time.sleep = run_process, sleep

    def archive_bytes(entries):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            for name, text in entries.items():
                archive.writestr(name, text)
        return payload.getvalue()

    a = "Image: ubuntu-24.04\nVersion: actual\nComplete job name: caller / gate\n"
    b = "Image: ubuntu-26.04\nVersion: other\nComplete job name: other / gate\n"
    archived = headers_from_archive(archive_bytes({"0_a.txt": a, "b.txt": b,
                                                 "system.txt": "not an image header"}))
    require(set(archived) == {"caller / gate", "other / gate"} and
            image_from_log(archived["caller / gate"])["image"] == "ubuntu-24.04",
            "attempt archive keeps each complete job name and actual image")
    unnamed = "Image: ubuntu-24.04\nVersion: actual\n"
    require(not headers_from_archive(archive_bytes({"caller _ gate.txt": unnamed})),
            "negative control: archive filenames cannot substitute for job identity")
    try:
        headers_from_archive(archive_bytes({"a.txt": a,
                                           "b.txt": a.replace("24.04", "26.04")}))
    except ValueError:
        require(True, "conflicting image headers for the same complete name are refused")
    else:
        require(False, "conflicting archive identities must not be blended")

    base = fixture([job(1), job(2)])
    entry = base["raw_attempts"][0]
    by_id = {str(j["id"]): "Image: ubuntu-24.04\nVersion: actual\nComplete job name: " +
             j["name"] + "\n" for j in entry["jobs_pages"][0]["jobs"]}
    payload = archive_bytes({key + ".txt": text for key, text in by_id.items()})
    original_io = collector.gh_json, collector.gh_bytes, collector.gh_text, collector.steps_reader

    def json_fetch(args):
        if "/workflows/" in args[-1]:
            return base["raw_run_pages"][0]
        if "/jobs?" in args[-1]:
            return entry["jobs_pages"][0]
        return entry["run"]

    class FixtureSteps:
        reads = {}

        def at(self, source):
            return entry["steps"], None

    try:
        collector.gh_json = json_fetch
        collector.gh_bytes = lambda args: payload
        collector.gh_text = lambda args: by_id[args[-1].split("/")[-2]]
        collector.steps_reader = lambda *args: FixtureSteps()

        def collect_fixture():
            return collector.collect("fixture", "main", "fixture.yml", 1,
                                     collector.parse_since(stamp(0)),
                                     until=collector.parse_since(stamp(100000)))

        batched = collect_fixture()
        require(batched["image_reads"] == {"attempt_archives": 1, "job_fallbacks": 0} and
                not batched["data_quality_errors"] and batched["attempts"][0]["W"] == 200,
                "collector reads one archive for multiple jobs without per-job requests")

        def unavailable(args):
            raise SystemExit("archive not ready")

        collector.gh_bytes = unavailable
        fallback = collect_fixture()
        require(fallback["image_reads"] == {"attempt_archives": 1, "job_fallbacks": 2} and
                fallback["raw_attempts"][0]["image_archive_error"] == "archive not ready" and
                not fallback["data_quality_errors"] and fallback["jobs"] == batched["jobs"],
                "negative control: an unavailable archive falls back without changing measurements")
    finally:
        collector.gh_json, collector.gh_bytes, collector.gh_text, collector.steps_reader = original_io
    pages = many["raw_attempts"][0]["jobs_pages"]
    calls = []

    def fetch(args):
        calls.append(args[-1])
        return pages[len(calls) - 1]

    require(len(read_pages("fixture", "jobs?", "jobs", fetch)) == 2 and
            calls[-1].endswith("page=2"), "collector fetches and retains the second API page")
    calls.clear()
    try:
        read_pages("fixture", "jobs?", "jobs", lambda args: pages[1])
    except ValueError:
        require(True, "collector refuses a truncated API response")
    else:
        require(False, "collector refuses a truncated API response")
    print(f"OK: {checks} offline observation controls")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())

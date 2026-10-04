#!/usr/bin/env python3
"""Three-way differential over generated programs: JVM, native (ASan+UBSan), comptime.

    scripts/fuzz3/run.py --minutes 25 --out DIR               # nightly shape
    scripts/fuzz3/run.py --seeds 1-40 --out DIR               # a fixed batch list
    scripts/fuzz3/run.py --seeds 1-40 --jar OLD.jar --rt OLD/runtime/c --out DIR
                                                              # another compiler

Why three executors. The tree already has two backends and a third executor
nobody differentiates: the comptime interpreter folds `const` with its own
evaluator over the same Core IR. Each is the others' oracle, so no program
needs a written expectation, which is what makes generated programs usable at
all. The 2026-10-04 bug survey put the densest defects exactly there: the C
backend with its runtime (16 in about 11k lines) and the interpreter (5 in
about 3k). A defect the three share is invisible here; the spike-native
corpus with its written `.expect` files remains the answer to that.

What is compared, per case (gen.py says what a case is):

  jvm      `build` of the batch, run with `java -jar`
  native   `__emitc`, cc -O2 with spike-native's flags (-Werror included), run
  san      the same C at -O0 under -fsanitize=address,undefined, run with
           leak detection on: its stdout must equal native's and stderr must
           carry no sanitizer report
  comptime every case the two backends completed and agreed on, folded into a
           const in a second program, built and run on the JVM

Stdout of every case, the exit status of a case that died, and the first line
of its stderr must agree between jvm and native. A batch that dies part way is
restarted after the dying case (main starts at the position given by its
argument count), so one
panic costs one more process start rather than the rest of the batch.

Why nightly and not push. Ruling on bug-rate (2026-10-04): push-total has no
room, and this finds old defects rather than guarding a change, so a day's
delay costs little. The run is bounded by wall clock, not by a count: each
night starts at a seed derived from the date and works until --minutes is up,
so a slow runner explores fewer programs rather than timing out. A finding is
reproduced from the seed and case index printed for it (gen.py --seed S
--case I), and that single-case program is saved beside it. A finding the
batch shows and the case alone does not is an interaction between cases (a
LeakSanitizer report at exit is the usual one, which is why such a report is
charged to the case its backtrace names rather than to the last case run).

Exit status: 0 when nothing diverged, 1 when anything did (compiler findings
and generator rejections alike: a generator the checker refuses is testing
nothing, and that needs to be seen as much as a miscompile does).
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen  # noqa: E402

JVM_OPTS = ["-Xss512m", "-Xmx2g", "-XX:+UseSerialGC"]
CC = os.environ.get("CC", "cc")
# spike-native's flags, for the reasons its header gives: -fwrapv because Int
# wraps, -fexceptions because a raise unwinds, -Werror because a Core type
# that reaches C wrong shows up first as a warning.
CFLAGS = ["-std=c11", "-O2", "-fwrapv", "-fexceptions", "-fno-strict-aliasing", "-pthread"]
WFLAGS = ["-Wall", "-Wextra", "-Werror", "-Wno-unused-variable", "-Wno-unused-but-set-variable",
          "-Wno-unused-parameter", "-Wno-unused-label",
          # a Dawn program may compare a value with itself or a Bool with a
          # literal; cc's opinion of that is about the source, not the backend
          "-Wno-tautological-compare", "-Wno-bool-compare",
          # `9223372036854775807 + 5` folded by cc: defined under -fwrapv,
          # and what the backend owes is the wrapped value, which is compared
          "-Wno-overflow"]
SANFLAGS = ["-std=c11", "-g", "-O0", "-fno-omit-frame-pointer", "-fwrapv", "-fexceptions",
            "-fno-strict-aliasing", "-pthread", "-fsanitize=address,undefined",
            "-fno-sanitize-recover=undefined"]
SAN_ENV = {"ASAN_OPTIONS": "detect_leaks=1", "UBSAN_OPTIONS": "print_stacktrace=1"}
SAN_REPORT = re.compile(r"ERROR: (Address|Leak)Sanitizer|runtime error:")
RUN_TIMEOUT = 30
COMPILE_TIMEOUT = 300


def sh(cmd, cwd=None, env=None, timeout=COMPILE_TIMEOUT, stdin=subprocess.DEVNULL):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as t:
        out = (t.stdout or b"").decode("utf-8", "replace")
        err = (t.stderr or b"").decode("utf-8", "replace")
        return "timeout", out, err


class Toolchain:
    def __init__(self, jar, std, rt, work):
        self.jar, self.std, self.rt = jar, std, rt
        self.rt_o = work / "dawn_rt.o"
        self.rt_san = work / "dawn_rt.san.o"
        # one runtime object per flavour for the whole run: the runtime is the
        # same for every batch, and the batch's own C is what cc has to see
        for out, flags in ((self.rt_o, CFLAGS), (self.rt_san, SANFLAGS)):
            rc, o, e = sh([CC, *flags, "-I", str(rt), "-c", str(rt / "dawn_rt.c"), "-o", str(out)])
            if rc != 0:
                raise SystemExit(f"FAIL: cannot build the C runtime ({' '.join(flags)}):\n{e}")

    def dawn(self, *args, timeout=COMPILE_TIMEOUT):
        std = ["--std", str(self.std)] if self.std else []
        env = dict(os.environ)
        env.pop("DAWN_STD", None)
        cmd = ["java", *JVM_OPTS, "-jar", str(self.jar), args[0], *std, *args[1:]]
        return sh(cmd, env=env, timeout=timeout)


def classify_compile(out, err):
    """A refusal with diagnostics is the generator's; anything else is the compiler's."""
    text = out + err
    if re.search(r"^error(\[\w+\])?:", text, re.M) and "panic" not in text and "Exception" not in text:
        return "rejected"
    return "crash"


def san_case(report, default):
    """The case a sanitizer report belongs to, read from its backtrace.

    LeakSanitizer reports when the process exits, which is after the last case
    it ran, not after the case that leaked; the allocating frame names the
    case's own function (`dawn_<module>__c<i>_...`), so that is the answer when
    there is one."""
    m = re.search(r"in dawn_\w*?__c(\d+)_", report)
    return int(m.group(1)) if m else default


def first_line(s):
    for line in s.splitlines():
        if line.strip():
            return line.strip()
    return ""


def run_cases(cmd, labels, env=None):
    """Run a batch binary from the start, restarting after each case that dies.

    Returns {label: {"out": [...], "status": "ok"|"died"|"timeout", "exit": n,
    "err": first stderr line, "errfull": stderr}}.
    """
    res = {}
    start = 0
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    while start < len(labels):
        rc, out, err = sh(cmd + ["x"] * start, env=full_env, timeout=RUN_TIMEOUT)
        cur = None
        seen = []
        for line in out.split("\n"):
            m = re.fullmatch(r"@@ (\d+)", line)
            if m:
                cur = int(m.group(1))
                seen.append(cur)
                res[cur] = {"out": [], "status": "ok", "exit": 0, "err": "", "errfull": ""}
            elif cur is not None:
                res[cur]["out"].append(line)
        if rc == 0:
            if res and seen:
                last = res[seen[-1]]
                if last["out"] and last["out"][-1] == "":
                    last["out"].pop()
            res["__err"] = res.get("__err", "") + err
            break
        if not seen:
            # died before printing a marker: charge the case it was asked to start at
            cur = labels[start]
            seen.append(cur)
            res[cur] = {"out": [], "status": "ok", "exit": 0, "err": "", "errfull": ""}
        last = res[seen[-1]]
        if last["out"] and last["out"][-1] == "":
            last["out"].pop()
        last["status"] = "timeout" if rc == "timeout" else "died"
        last["exit"] = rc
        last["err"] = first_line(err)
        last["errfull"] = err
        start = labels.index(seen[-1]) + 1
    for cur in res:
        if cur != "__err" and res[cur]["out"] and res[cur]["out"][-1] == "":
            res[cur]["out"].pop()
    return res


class Batch:
    def __init__(self, tc, seed, indices, work, no_never=False):
        self.tc, self.seed, self.indices, self.work = tc, seed, indices, work
        self.no_never = no_never
        work.mkdir(parents=True, exist_ok=True)
        self.findings = []
        self.stats = {"cases": len(indices), "died": 0, "comptime": 0}

    def find(self, kind, case, detail):
        if len(detail) > 4000:   # a sanitizer's header and a backtrace's tail both matter
            detail = detail[:3000] + "\n[...]\n" + detail[-1000:]
        self.findings.append({"seed": self.seed, "case": case, "kind": kind, "detail": detail})

    def compile_jvm(self, src, out):
        return self.tc.dawn("build", str(src), "-o", str(out))

    def run(self):
        src = self.work / "b.dawn"
        src.write_text(gen.program(self.seed, self.indices, no_never=self.no_never))
        labels = list(self.indices)
        jar = self.work / "b.jar"
        c = self.work / "b.c"
        rc, o, e = self.compile_jvm(src, jar)
        if rc != 0:
            return self.attribute("jvm-compile", classify_compile(o, e), o + e)
        rc, o, e = self.load_jvm(jar)
        if rc != 0:
            return self.attribute("jvm-load", "crash", o + e)
        rc, o, e = self.tc.dawn("__emitc", str(src), "-o", str(c))
        if rc != 0:
            return self.attribute("emitc", classify_compile(o, e), o + e)
        self.three_way(labels, jar, c)

    def load_jvm(self, jar):
        """Load the main class and run no case: as many arguments as there are
        cases start main past the last one. A class the verifier rejects fails
        here, and would otherwise fail every case of the batch at once."""
        return sh(["java", "-Xss512m", "-jar", str(jar)] + ["x"] * len(self.indices), timeout=RUN_TIMEOUT)

    def stage(self, stage, src, work):
        if stage == "jvm-compile":
            return self.compile_jvm(src, work / "one.jar")
        if stage == "jvm-load":
            rc, o, e = self.compile_jvm(src, work / "one.jar")
            if rc != 0:
                return rc, o, e
            return sh(["java", "-Xss512m", "-jar", str(work / "one.jar")] + ["x"] * len(self.indices),
                      timeout=RUN_TIMEOUT)
        return self.tc.dawn("__emitc", str(src), "-o", str(work / "one.c"))

    def attribute(self, stage, cls, text):
        """A batch failed to compile: find the case(s) by compiling each alone."""
        if len(self.indices) == 1:
            kind = "rejected" if cls == "rejected" else f"{stage}-crash"
            self.find(kind, self.indices[0], text)
            return
        one = self.work / "one"
        one.mkdir(exist_ok=True)

        def fails(idx):
            src = one / "one.dawn"
            src.write_text(gen.program(self.seed, idx, no_never=self.no_never))
            rc, o, e = self.stage(stage, src, one)
            return None if rc == 0 else (o + e)

        # bisect rather than compile every case alone: a batch usually holds
        # one or two bad cases, and a compile is the expensive step here
        bad = []

        def split(idx, known):
            if not known:
                return
            if len(idx) == 1:
                c = classify_compile(known, "")
                self.find("rejected" if c == "rejected" else f"{stage}-crash", idx[0], known)
                bad.append(idx[0])
                return
            half = len(idx) // 2
            for part in (idx[:half], idx[half:]):
                split(part, fails(part))

        split(self.indices, text)
        good = [i for i in self.indices if i not in bad]
        if len(good) == len(self.indices):
            # only the batch fails: an interaction between cases, reported on the batch
            self.find(f"{stage}-crash" if cls != "rejected" else "rejected", -1, text)
            return
        if good:   # the rest of the batch still gets its three-way run
            rest = Batch(self.tc, self.seed, good, self.work / "rest", self.no_never)
            rest.run()
            self.findings += rest.findings
            for k in ("died", "comptime"):
                self.stats[k] += rest.stats[k]

    def three_way(self, labels, jar, c):
        tc = self.tc
        nbin, sbin = self.work / "b.bin", self.work / "b.san"
        rc, o, e = sh([CC, *CFLAGS, *WFLAGS, "-I", str(tc.rt), str(c), str(tc.rt_o), "-lm", "-o", str(nbin)])
        native_ok = rc == 0
        if not native_ok:
            self.find("cc", -1, e)
        rc, o, e2 = sh([CC, *SANFLAGS, "-I", str(tc.rt), str(c), str(tc.rt_san), "-lm", "-o", str(sbin)])
        san_ok = rc == 0
        if not san_ok:
            self.find("cc-san", -1, e2)
        jv = run_cases(["java", "-Xss512m", "-jar", str(jar)], labels)
        nv = run_cases([str(nbin)], labels) if native_ok else None
        sv = run_cases([str(sbin)], labels, SAN_ENV) if san_ok else None
        agreed = []
        for i in labels:
            j = jv.get(i)
            if j is None:
                self.find("jvm-missing", i, "the JVM run never reached this case")
                continue
            if j["status"] != "ok":
                self.stats["died"] += 1
            if nv is not None:
                n = nv.get(i)
                if n is None:
                    self.find("native-missing", i, "the native run never reached this case")
                else:
                    self.compare(i, "jvm", j, "native", n)
                    if j["status"] == "ok" and n["status"] == "ok" and j["out"] == n["out"]:
                        agreed.append(i)
            if sv is not None and nv is not None:
                s, n = sv.get(i), nv.get(i)
                if s is not None and n is not None:
                    if SAN_REPORT.search(s["errfull"]):
                        self.find("sanitizer", san_case(s["errfull"], i), s["errfull"])
                    elif s["out"] != n["out"] or s["status"] != n["status"] or s["exit"] != n["exit"]:
                        self.find("san-diff", i, f"native {n['status']} {n['exit']} {n['out'][:5]}\n"
                                                  f"san {s['status']} {s['exit']} {s['out'][:5]}\n{s['errfull']}")
        if sv is not None and SAN_REPORT.search(sv.get("__err", "")):
            self.find("sanitizer", san_case(sv["__err"], -1), sv["__err"])
        if agreed:
            self.comptime(agreed, jv)

    def compare(self, i, an, a, bn, b):
        if a["status"] != b["status"] or a["exit"] != b["exit"]:
            self.find("exit", i, f"{an}: {a['status']} exit {a['exit']} {a['err']}\n"
                                 f"{bn}: {b['status']} exit {b['exit']} {b['err']}\n"
                                 f"--- {an} stderr\n{a['errfull'][:1500]}\n--- {bn} stderr\n{b['errfull'][:1500]}")
        elif a["out"] != b["out"]:
            self.find("stdout", i, f"{an}: {a['out']}\n{bn}: {b['out']}")
        elif a["err"] != b["err"]:
            self.find("stderr", i, f"{an}: {a['err']}\n{bn}: {b['err']}")

    def comptime(self, agreed, jv):
        src = self.work / "k.dawn"
        src.write_text(gen.program(self.seed, agreed, comptime=True, no_never=self.no_never))
        jar = self.work / "k.jar"
        rc, o, e = self.compile_jvm(src, jar)
        if rc != 0:
            if len(agreed) == 1:
                self.find("comptime-compile", agreed[0], o + e)
                return
            half = len(agreed) // 2   # bisect to the case(s) the interpreter refused
            self.comptime(agreed[:half], jv)
            self.comptime(agreed[half:], jv)
            return
        self.stats["comptime"] += len(agreed)
        kv = run_cases(["java", "-jar", str(jar)], agreed)
        for i in agreed:
            k = kv.get(i)
            if k is None or k["status"] != "ok":
                self.find("comptime-run", i, json.dumps(k)[:2000])
            elif k["out"] != jv[i]["out"]:
                self.find("comptime", i, f"runtime: {jv[i]['out']}\ncomptime: {k['out']}")


def parse_seeds(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", help="batch seeds, e.g. 1-40 or 3,9")
    ap.add_argument("--minutes", type=float, help="run batches from --seed-base until this is up")
    ap.add_argument("--seed-base", type=int,
                    help="first seed for --minutes (default: today's date, YYYYMMDD000)")
    ap.add_argument("--cases", type=int, default=20, help="cases per batch")
    ap.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 8))
    ap.add_argument("--jar", default=str(ROOT / "build/dawn-selfhost.jar"))
    ap.add_argument("--std", default=str(ROOT / "std"), help="'' for the jar's embedded std")
    ap.add_argument("--rt", default=str(ROOT / "runtime/c"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", action="store_true", help="keep every batch's work directory")
    ap.add_argument("--no-never", action="store_true",
                    help="generate no jumps or panics in operand positions (a control)")
    a = ap.parse_args()
    if not a.seeds and a.minutes is None:
        ap.error("give --seeds or --minutes")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + a.minutes * 60 if a.minutes is not None else None
    if a.seeds:
        seeds = iter(parse_seeds(a.seeds))
    else:
        base = a.seed_base if a.seed_base is not None else int(datetime.date.today().strftime("%Y%m%d")) * 1000
        seeds = iter(range(base, base + 10**6))
    work_root = Path(tempfile.mkdtemp(prefix="fuzz3-"))
    tc = Toolchain(Path(a.jar), Path(a.std) if a.std else None, Path(a.rt), work_root)
    lock = threading.Lock()
    findings, totals = [], {"batches": 0, "cases": 0, "died": 0, "comptime": 0}
    seeds_run = []

    def one(seed):
        b = Batch(tc, seed, list(range(a.cases)), work_root / f"s{seed}", a.no_never)
        try:
            b.run()
        except Exception as ex:  # a harness bug must not pass for a quiet night
            b.find("harness", -1, repr(ex))
        with lock:
            seeds_run.append(seed)
            totals["batches"] += 1
            for k in ("cases", "died", "comptime"):
                totals[k] += b.stats[k]
            for f in b.findings:
                findings.append(f)
                save(out, f, a.no_never)
                print(f"FINDING seed={f['seed']} case={f['case']} kind={f['kind']}", flush=True)
        if not a.keep and not b.findings:
            shutil.rmtree(b.work, ignore_errors=True)

    with cf.ThreadPoolExecutor(a.jobs) as pool:
        pending = set()
        exhausted = False
        while True:
            while not exhausted and len(pending) < a.jobs and (deadline is None or time.monotonic() < deadline):
                try:
                    pending.add(pool.submit(one, next(seeds)))
                except StopIteration:
                    exhausted = True
            if not pending:
                break
            done, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for d in done:
                d.result()
            if deadline is not None and time.monotonic() >= deadline and not pending:
                break
    elapsed = time.monotonic() - started
    kinds = {}
    for f in findings:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    summary = {"seeds": sorted(seeds_run), "elapsed_s": round(elapsed), **totals,
               "findings": len(findings), "by_kind": kinds,
               "jar": a.jar, "cases_per_batch": a.cases}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    with open(out / "findings.jsonl", "w") as fh:
        for f in findings:
            fh.write(json.dumps(f) + "\n")
    sigs = report(out, findings, summary)
    for sig in sorted(sigs):
        print(f"  {len(sigs[sig]):4d}  {sig}")
    if not a.keep:
        shutil.rmtree(work_root, ignore_errors=True)
    print(f"fuzz3: {totals['batches']} batches, {totals['cases']} cases "
          f"({totals['died']} died by design or not, {totals['comptime']} folded), "
          f"{len(findings)} findings {kinds}, {elapsed:.0f}s", flush=True)
    sys.exit(1 if findings else 0)


def signature(f):
    """What a finding is, without which program found it: the kind and the
    first line of the message with numbers, names and paths blanked. Two
    nights that hit the same defect agree on it, so the issue is commented on
    only when the set of signatures changes (nightly-issue.sh's verdict)."""
    d = f["detail"]
    line = ""
    pats = [r"panic:[^\n]*", r"java\.lang\.\w+(?:Error|Exception)[^\n]*", r"Exception[^\n]*", r"error: [^\n]*"]
    san = [r"ERROR: \w+Sanitizer: [^\n]*", r"runtime error:[^\n]*"]
    # a sanitizer report may follow a case's own panic line; the report is the finding
    for pat in (san + pats if f["kind"] in ("sanitizer", "san-diff") else pats + san):
        m = re.search(pat, d)
        if m:
            line = m.group(0)
            break
    if not line and f["kind"] in ("stdout", "exit", "stderr", "comptime", "san-diff"):
        line = ""   # a value difference has no message worth keying on
    line = re.sub(r" at src/\S+$", "", line)   # where in the compiler, not what
    line = re.sub(r"/\S+", "<path>", line)
    line = re.sub(r"\bc\d+_\w+", "<fn>", line)
    line = re.sub(r"\b\w+\.<fn>", "<fn>", line)
    line = re.sub(r"unbalanced in \w+:", "unbalanced in <module>:", line)
    line = re.sub(r"\d+", "N", line)
    line = re.sub(r"(;.*)$", "", line)   # rc lists every unbalanced function; the first says which check
    return f"{f['kind']}: {line}".strip()


def report(out, findings, summary):
    """report.md: the issue body, one line per signature with its first example."""
    sigs = {}
    for f in findings:
        sigs.setdefault(signature(f), []).append(f)
    lines = [f"fuzz3: {summary['batches']} batches, {summary['cases']} cases, "
             f"{len(findings)} findings in {len(sigs)} signatures, {summary['elapsed_s']}s.", ""]
    for sig in sorted(sigs):
        fs = sigs[sig]
        ex = ", ".join(f"seed {f['seed']} case {f['case']}" for f in fs[:3])
        lines.append(f"- `{sig}` x{len(fs)} ({ex})")
    lines += ["", "Reproduce: `scripts/fuzz3/gen.py --seed S --case I > case.dawn` regenerates",
              "the case alone (the run's artifact holds every one); run it through",
              "`dawn run` and `dawn __emitc` + cc as run.py's header describes.", ""]
    digest = __import__("hashlib").sha256("\n".join(sorted(sigs)).encode()).hexdigest()[:16]
    lines.append(f"<!-- verdict: fuzz3-{digest} -->")
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return sigs


def save(out, f, no_never):
    """The single-case program and the finding, under <out>/s<seed>-c<case>-<kind>/."""
    d = out / f"s{f['seed']}-c{f['case']}-{f['kind']}"
    d.mkdir(parents=True, exist_ok=True)
    if f["case"] >= 0:
        (d / "case.dawn").write_text(gen.program(f["seed"], [f["case"]], no_never=no_never))
    (d / "finding.json").write_text(json.dumps(f, indent=1) + "\n")


if __name__ == "__main__":
    main()

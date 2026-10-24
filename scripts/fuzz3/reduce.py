#!/usr/bin/env python3
"""Shrink fuzz3 findings to small programs, and draft corpus entries from them.

    scripts/fuzz3/reduce.py --findings fuzz3-out --minutes 6         # nightly shape
    scripts/fuzz3/reduce.py --findings DIR --only s20261008115-c7-emitc-crash
    scripts/fuzz3/reduce.py --findings DIR --jar OLD.jar --std OLD/std --rt OLD/runtime/c
    scripts/fuzz3/reduce.py --findings DIR --per-signature 99 --check-lines 20
                                                  # cut 2's criterion, red when missed
    scripts/fuzz3/reduce.py --self-test                               # no compiler needed

FUZZ3_REDUCE_DEBUG=1 prints what made a round fall back to bisection.

Why a reducer at all. A generated case is 60 to 200 lines, and the defect it
found usually needs five of them. Nobody turns a finding into a regression
test before cutting it down by hand, and the 2026-10-10 triage of #632 spent
most of its time doing exactly that. research-bug-rate-report 7.3 cut 2 asks
for every finding of cut 1 to come out at 20 lines or fewer.

What the units are. The generator writes a case as top-level declarations
separated by blank lines, and every statement as whole lines, with a block
opening at the end of a line and closing at the start of one (gen.py's stmt,
block_expr, match_expr). So the line structure, nested by braces, is the
generator's statement structure, and this file reads it back rather than
asking gen.py to keep a tree: a finding saved by an older generator, or one
written by hand, reduces the same way. The edits are the ones hierarchical
delta debugging uses on such a tree: delete a declaration, a statement or a
match arm; replace an `if`, a loop or a block by one of its bodies; once
bodies hold a single line, join them onto the lines around them (match arms
with commas, spec 1.7); and give a function returning a scalar a literal
body, since every function of a module is compiled, called or not. The loop
counter increment gen.py writes into every `while` is not deleted while the
`while` holds it, because a deleted increment is a loop that only the run
timeout ends.

What has to stay the same. A candidate counts only if it shows the original
finding again: the same kind (the same pair of executors disagreeing in the
same way), and for a message the same signature run.py keys its issue on
(first line with numbers, names and paths blanked), with the exit statuses
of both sides for an `exit` finding. Without that a reduction slides from the
defect it was given to whatever defect the smaller program happens to have,
or to a program the checker refuses, which is the commonest smaller program.

Why candidates are batched. Every evaluation is a JVM build, an emitc and a
cc of a translation unit that carries all of std, and cc is the expensive one
(#239, and 7.3's own note). So one round puts many candidates into one
program as separate cases, renamed apart (c7 becomes c1000, c1001, ...),
which is exactly how run.py batches its own cases: one compile per round, not
one per candidate. (Measured 2026-10-19 on two pinned cores: emitc and build
each take 2.0 to 2.4 s for 1, 6, 12 or 24 copies of a case; the fixed cost is
the JVM and std, not the candidates.) A candidate the checker refuses would refuse the whole
batch, so refusals are charged to candidates by the line numbers in the
diagnostics and the rest is compiled again; a compiler crash, which has no
line, is charged by the function its message names, and only a crash with
neither falls back to run.py's bisection. Each round tries the single edits of
largest gain together with their unions, keeps the best candidate that
reproduces, and stops when a whole pass of single edits reproduces nothing.
The result is checked once more alone, with a four-line main, since batching
is an optimisation and the answer has to hold as a program of its own.

What it writes, under <findings>/reduced/: per finding, reduced.dawn and
reduce.json (lines before and after, rounds, verdict), and drafts for the
spike-native corpus: a program, the JVM's answer as a draft .expect, and the
known-red.txt lines the finding implies. Drafts, never entries: the corpus
rule is that an .expect is written by hand from what the program should
print (spike-native/run.sh's header), so a person reads the draft, decides
which side is right, and files it. summary.md is the overview.

Budget. --minutes is a wall-clock bound for the whole run, checked before
each round starts with the round's measured cost as margin; whatever is
smallest so far is written when it is up, marked as cut short.
"""

import argparse
import concurrent.futures as cf
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run  # noqa: E402

BASE = 1000          # the first label a candidate is renamed to
ROUND = 24           # single edits per round
RUN_TIMEOUT = 8      # a reduced case that runs this long has lost its loop bound
# the counter gen.py's `while` increments; see the header
PROTECTED = re.compile(r"^\s*(w\d+) = \1 \+ 1\s*$")

# the executors each kind of finding needs; everything else is not compiled
# (an emitc crash needs no JVM build per round: emitc checks the program
# too, so a refusal still shows, and the JVM half is checked once at the end)
LEGS = {
    "rejected": {"jvm", "emitc"},
    "jvm-compile-crash": {"jvm"},
    "jvm-load-crash": {"jvm"},
    "emitc-crash": {"emitc"},
    "exit": {"jvm", "native"},
    "stdout": {"jvm", "native"},
    "stderr": {"jvm", "native"},
    "native-missing": {"jvm", "native"},
    "jvm-missing": {"jvm", "native"},
    "sanitizer": {"jvm", "native", "san"},
    "san-diff": {"jvm", "native", "san"},
    "comptime": {"jvm", "comptime"},
    "comptime-run": {"jvm", "comptime"},
    "comptime-compile": {"jvm", "comptime"},
}

# spike-native checks a finding of each kind is expected to turn red, for the
# known-red.txt draft (run.sh's check names). Which side is wrong is for the
# person filing it to say; the draft assumes the JVM is right, as #632 was.
KNOWN_RED = {
    "rejected": ["jvm"],
    "jvm-compile-crash": ["jvm"],
    "jvm-load-crash": ["jvm"],
    "emitc-crash": ["emitc"],
    "exit": ["exit"],
    "stdout": ["native", "diff"],
    "stderr": ["stderr"],
    "native-missing": ["native", "diff"],
    "jvm-missing": ["jvm", "diff"],
    "sanitizer": ["asan"],
    "san-diff": ["asan"],
    "comptime": ["jvm", "native"],
    "comptime-run": ["jvm", "native"],
    "comptime-compile": ["jvm", "native"],
}


# ------------------------------------------------------------------ the tree
class Block:
    """Lines nested by braces: parts alternate between a line (str) and a
    list of items (a Seq). A declaration is a Block of one Seq and no lines."""

    def __init__(self, parts):
        self.parts = parts

    def seqs(self):
        return [k for k, p in enumerate(self.parts) if isinstance(p, list)]


def depth_walk(line, d):
    """(lowest depth reached, depth after) for a line read from depth d. The
    braces of string literals need no care: gen.py's literals hold none and
    an interpolation's are balanced."""
    lo = d
    for ch in line:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
            lo = min(lo, d)
    return lo, d


def parse_seq(lines):
    out, i = [], 0
    while i < len(lines):
        _, d = depth_walk(lines[i], 0)
        if d <= 0:
            out.append(lines[i])
            i += 1
            continue
        # t is the depth the last structural line left: a line that dips
        # below it closes what that line opened, so it is the next separator
        # (`} else {`, `} - 3), b: f({`) or, back at 0, the closer
        parts, cur, j, t = [lines[i]], [], i + 1, d
        while j < len(lines):
            lo, nd = depth_walk(lines[j], d)
            if lo < t:
                parts += [parse_seq(cur), lines[j]]
                cur = []
                d = t = nd
                j += 1
                if nd <= 0:
                    break
            else:
                cur.append(lines[j])
                d = nd
                j += 1
        else:
            if cur:
                parts.append(parse_seq(cur))
        out.append(Block(parts))
        i = j
    return out


def render(seq):
    out = []
    for it in seq:
        if isinstance(it, str):
            out.append(it)
        else:
            for p in it.parts:
                out += [p] if isinstance(p, str) else render(p)
    return out


def parse_case(text):
    """Declarations separated by blank lines, each a Block of one Seq."""
    decls = [d for d in re.split(r"\n\s*\n", text.strip("\n")) if d.strip()]
    return [Block([parse_seq(d.split("\n"))]) for d in decls]


def render_case(tree):
    return "\n".join("\n".join(render(d.parts[0])) for d in tree if render(d.parts[0]))


def size(tree):
    return sum(len(render(d.parts[0])) for d in tree)


# ------------------------------------------------------------------ the edits
# A function whose result is a scalar can lose its body: the defect is often
# in a helper the case function no longer needs to call, and every function of
# the module is compiled whether called or not.
STUB = re.compile(r"(fn \w+\([^\n]*\) -> (String|Int|Bool) = )\{\n")
STUB_VALUE = {"String": '""', "Int": "0", "Bool": "false"}


def joined(b):
    """A block of single lines written on one line, or None. Between match
    arms a comma does what the newline did (spec 1.7); anywhere else only a
    body of one line can be joined, since a statement needs its newline."""
    segs = [b.parts[k] for k in b.seqs()]
    if not segs or any(not all(isinstance(x, str) for x in sg) for sg in segs):
        return None
    if all(len(sg) == 1 for sg in segs):
        return " ".join(x.strip() if isinstance(x, str) else x[0].strip() for x in b.parts)
    if len(segs) == 1 and re.search(r"\bmatch \(", b.parts[0]) and isinstance(b.parts[-1], str):
        return f"{b.parts[0].rstrip()} {', '.join(x.strip() for x in segs[0])} {b.parts[-1].strip()}"
    return None

def at(tree, path):
    """The Seq holding the item at path, and the item's index in it."""
    seq = tree
    for k in range(0, len(path) - 1, 2):
        seq = seq[path[k]].parts[path[k + 1]]
    return seq, path[-1]


def edits(tree):
    """Every single edit on the tree: (gain, key, op, path, arg)."""
    out = []

    def walk(seq, path, top, opener=""):
        for i, it in enumerate(seq):
            p = path + (i,)
            n = len(render([it]))
            text = "\n".join(render([it]))
            if isinstance(it, str):
                # the counter is kept only while a `while` still holds it
                guard = opener.lstrip().startswith("while ") and PROTECTED.match(it)
                if not top and not guard:
                    out.append((1, ("del", text), "del", p, None))
                continue
            if top or n > 0:
                out.append((n, ("del", text), "del", p, None))
            if top and n > 1 and "{" not in text and "}" not in text:
                out.append((n - 1, ("joindecl", text), "joindecl", p, None))
            m = STUB.match(text)
            if top and n > 1 and m:
                stub = f"{m.group(1)}{STUB_VALUE[m.group(2)]}"
                out.append((n - 1, ("stub", text), "stub", p, stub))
            if not top:
                ks = it.seqs()
                for k in ks:
                    body = len(render(it.parts[k]))
                    if body < n:
                        out.append((n - body, ("unwrap", text, k), "unwrap", p, k))
                flat = joined(it)
                if flat is not None:
                    out.append((n - 1, ("join", text), "join", p, flat))
                elif len(ks) > 1:
                    # one inner body of a single line onto the lines around it,
                    # when the whole cannot go onto one line
                    for k in ks:
                        sg = it.parts[k]
                        if len(sg) == 1 and isinstance(sg[0], str) and k + 1 < len(it.parts):
                            out.append((2, ("joinseg", text, k), "joinseg", p, k))
            for k in it.seqs():
                walk(it.parts[k], p + (k,), False, it.parts[k - 1] if k > 0 else "")

    walk(tree, (), True)
    out.sort(key=lambda e: -e[0])
    seen = set()   # a declaration's only item is the declaration again
    return [e for e in out if not (e[1] in seen or seen.add(e[1]))]


def apply(tree, chosen):
    """A copy of tree with the edits applied; None when two of them overlap."""
    paths = [e[3] for e in chosen]
    for x, a in enumerate(paths):
        for y, b in enumerate(paths):
            if x != y and b[:len(a)] == a:
                return None
    t = copy.deepcopy(tree)
    for _, _, op, path, arg in sorted(chosen, key=lambda e: e[3], reverse=True):
        seq, i = at(t, path)
        if op == "del":
            del seq[i]
        elif op == "unwrap":
            seq[i:i + 1] = seq[i].parts[arg]
        elif op == "joinseg":
            b, k = seq[i], arg
            line = f"{b.parts[k - 1].rstrip()} {b.parts[k][0].strip()} {b.parts[k + 1].strip()}"
            parts = b.parts[:k - 1] + [line] + b.parts[k + 2:]
            # two lines in a row now: the merged one swallows its neighbour seq boundary
            seq[i] = Block(parts) if any(isinstance(x, list) for x in parts) else line
        elif op in ("join", "stub"):
            seq[i] = Block([[arg]]) if op == "stub" else arg
        elif op == "joindecl":
            seq[i] = Block([[" ".join(l.strip() for l in render(seq[i].parts[0]))]])
    return [d for d in t if render(d.parts[0])]


# ------------------------------------------------------------- the predicate
def key(f):
    """What has to stay the same: run.py's signature, made blind to addresses,
    and for an exit difference the statuses and exit codes of both sides."""
    detail = re.sub(r"0x[0-9a-fA-F]+", "0xH", f["detail"])
    # rc's "a return left a binding behind: 3,7,9" lists the bindings, and
    # how many there are is a property of the program, not of the defect
    sig = re.sub(r"N(,N)+", "N", run.signature({**f, "detail": detail}))
    if f["kind"] == "exit":
        sides = []
        for line in detail.split("\n")[:2]:
            m = re.match(r"(\w+): (\w+) exit (\S+)", line)
            if m:
                sides.append(" ".join(m.groups()))
        sig += " [" + "; ".join(sides) + "]"
    return sig


def rename(text, old, new):
    text = re.sub(rf"\bc{old}_", f"c{new}_", text)
    return re.sub(rf"\bC{old}(?=[A-Z])", f"C{new}", text)


def main_src(labels, comptime=False):
    if comptime:
        consts = "\n".join(f"const K{i}: String = c{i}_case()" for i in labels)
        body = "\n".join(f'  io.println("@@ {i}")\n  io.println(K{i})' for i in labels)
        return f"{consts}\npub fn main() -> Unit !io = {{\n{body}\n}}"
    if len(labels) == 1:
        # four lines, and still the batch's contract: an argument means "start
        # past the case", which is how run.py's load check runs no case
        i = labels[0]
        return (f'pub fn main() -> Unit !io = {{\n  io.println("@@ {i}")\n'
                f'  if (len(args()) == 0) {{ io.println(c{i}_case()) }}\n}}')
    names = ", ".join(f"c{i}_case" for i in labels)
    return ("pub fn main() -> Unit !io = {\n"
            f"  let cases: List[fn() -> String] = [{names}]\n"
            f"  let labels: List[Int] = [{', '.join(map(str, labels))}]\n"
            "  let from = len(args())\n"
            "  for i in from..len(cases) {\n"
            '    io.println("@@ ${labels[i]}")\n'
            "    io.println(cases[i]())\n"
            "  }\n"
            "}")


class Cands(run.Batch):
    """run.py's batch over candidate texts instead of generated cases."""

    def __init__(self, tc, header, texts, work, legs, want=None):
        super().__init__(tc, 0, sorted(texts), work, legs=legs)
        self.header, self.texts, self.want = header, texts, want
        self.ranges = {}
        self.hit = None     # the candidates a matching crash named, in order

    def source(self, indices, comptime=False):
        lines = self.header.split("\n")
        rng = {}
        for i in indices:
            body = self.texts[i].split("\n")
            rng[i] = (len(lines) + 1, len(lines) + len(body))
            lines += body
        self.ranges[tuple(indices)] = rng
        m = main_src(indices, comptime)
        return "\n".join(lines + m.split("\n")) + "\n"

    def sub(self, indices, work):
        return Cands(self.tc, self.header, {i: self.texts[i] for i in indices}, work, self.legs, self.want)

    def rest(self, drop):
        good = [i for i in self.indices if i not in drop]
        if good:
            r = self.sub(good, self.work / "rest")
            r.run()
            self.findings += r.findings
            self.hit = self.hit if self.hit is not None else r.hit

    def attribute(self, stage, cls, text):
        """Charge refusals to candidates by the lines their diagnostics name."""
        rng = self.ranges.get(tuple(self.indices))
        if cls == "rejected" and len(self.indices) > 1 and rng:
            blocks = re.split(r"\n(?=error)", text)
            mine = {}
            for b in blocks:
                if not b.startswith("error"):
                    continue
                m = re.search(r"--> \S+?:(\d+):\d+", b)
                owner = None
                if m:
                    line = int(m.group(1))
                    owner = next((i for i, (a, z) in rng.items() if a <= line <= z), None)
                if owner is None:
                    # outside every candidate, i.e. in main: a candidate that
                    # lost its case function is named by the message
                    n = re.match(r"error[^\n]*\b[cC](\d+)_?\w*", b)
                    owner = int(n.group(1)) if n and int(n.group(1)) in rng else None
                if owner is None:
                    mine = None
                    break
                mine.setdefault(owner, []).append(b)
            if mine:
                for i, bs in mine.items():
                    self.find("rejected", i, "\n".join(bs))
                return self.rest(mine)
        if cls == "crash" and len(self.indices) > 1:
            # A compiler crash names the function it failed on, so the
            # candidate is in the name, and rc's balance check names the
            # first three unbalanced functions of the module in source order
            # (rc.dawn's `list.take(bad, 3)`; measured on five copies of
            # #632's case: the first three in file order, whatever their
            # numbers). So the named candidates
            # that match are the answer, the ones before the last name that
            # are not named did not crash, and what follows it is unknown
            # and not compiled. A crash that does not match is dropped and
            # the rest compiled again. No name, and run.py bisects.
            line = next((l for l in text.split("\n") if "panic" in l or "Exception" in l), text)
            named = [n for n in dict.fromkeys(int(x) for x in re.findall(r"\bc(\d+)_", line))
                     if n in self.indices]
            if named:
                for n in named:
                    self.find(f"{stage}-crash", n, text)
                if self.want is not None and key(self.findings[-1]) == self.want:
                    self.hit = named
                    return
                return self.rest(set(named))
        if os.environ.get("FUZZ3_REDUCE_DEBUG") and len(self.indices) > 1:
            print(f"bisecting {len(self.indices)} after {stage} {cls}: {text[:600]!r}", flush=True)
        super().attribute(stage, cls, text)


class Counted:
    """The toolchain, counting compiler runs for the round log."""

    def __init__(self, tc):
        self.tc, self.runs, self.lock = tc, 0, threading.Lock()

    def __getattr__(self, name):
        return getattr(self.tc, name)

    def dawn(self, *args, **kw):
        with self.lock:
            self.runs += 1
        return self.tc.dawn(*args, **kw)


class Reducer:
    def __init__(self, tc, fdir, finding, out, deadline, log, par=1):
        self.tc, self.fdir, self.f, self.out = Counted(tc), fdir, finding, out
        self.par = par        # batches compiled side by side per round
        self.deadline, self.log = deadline, log
        self.idx = finding["case"]
        self.want = key(finding)
        self.legs = LEGS.get(finding["kind"], set(run.LEGS))
        self.rounds = 0
        self.cost = 60.0      # seconds a round is assumed to take until one has
        self.work = Path(tempfile.mkdtemp(prefix="fuzz3-reduce-"))

    def split(self, text):
        """(header, case declarations, main) of a saved single-case program."""
        lines = text.rstrip("\n").split("\n")
        first = next(i for i, l in enumerate(lines)
                     if re.match(rf"(type C{self.idx}[A-Z]|fn c{self.idx}_)", l))
        mainl = next(i for i, l in enumerate(lines) if l.startswith("pub fn main"))
        return "\n".join(lines[:first]).rstrip("\n"), "\n".join(lines[first:mainl]), "\n".join(lines[mainl:])

    def evaluate(self, trees, header=None, legs=None):
        """For each tree: True (shows the finding), False (does not), or None
        (not compiled: an earlier candidate's crash answered first). The trees
        are dealt into self.par batches compiled side by side."""
        self.rounds += 1
        n = max(1, min(self.par, len(trees)))
        groups = [list(range(len(trees)))[g::n] for g in range(n)]
        t0 = time.monotonic()
        res = [None] * len(trees)

        def one(g, ks):
            texts = {BASE + k: rename(render_case(trees[k]), self.idx, BASE + k) for k in ks}
            w = self.work / f"r{self.rounds}-{g}"
            b = Cands(self.tc, header if header is not None else self.header, texts, w,
                      legs or self.legs, self.want)
            try:
                b.run()
            except Exception as ex:   # noqa: BLE001  a harness fault is not a reproduction
                self.log(f"  round {self.rounds}: harness {ex!r}")
                for k in ks:
                    res[k] = False
                return
            finally:
                shutil.rmtree(w, ignore_errors=True)
            got = {}
            for f in b.findings:
                got.setdefault(f["case"], set()).add(key({**f, "case": self.idx}))
            last = max(b.hit) if b.hit else None
            for k in ks:
                if b.hit is not None and BASE + k > last:
                    continue          # after an early answer nothing is known
                res[k] = (BASE + k in b.hit) if b.hit is not None else (self.want in got.get(BASE + k, set()))

        if n == 1:
            one(0, groups[0])
        else:
            with cf.ThreadPoolExecutor(n) as pool:
                list(pool.map(lambda a: one(*a), enumerate(groups)))
        self.cost = max(self.cost * 0.5, time.monotonic() - t0)
        return res

    def alone(self, tree, header):
        """The reduced program on its own, through every leg up to its finding's
        and the JVM's. Its own reading of the findings, not evaluate's: the
        answer the rounds were steered by is what this checks."""
        w = self.work / "alone"
        b = Cands(self.tc, header, {self.idx: render_case(tree)}, w, self.legs | {"jvm"}, None)
        try:
            b.run()
        except Exception as ex:   # noqa: BLE001
            self.log(f"  {self.name()}: alone: harness {ex!r}")
            return False
        finally:
            shutil.rmtree(w, ignore_errors=True)
        return any(f["case"] == self.idx and key(f) == self.want for f in b.findings)

    def time_left(self):
        return self.deadline - time.monotonic() > self.cost * 1.2

    def run(self):
        t0 = time.monotonic()
        text = (self.fdir / "case.dawn").read_text()
        self.header, case_text, _ = self.split(text)
        tree = parse_case(case_text)
        assert render_case(tree) == "\n".join(l for l in case_text.strip("\n").split("\n") if l.strip()), \
            "the tree does not render back to the case"
        orig_lines = len(text.rstrip("\n").split("\n"))
        verdict = "budget"
        ok = self.evaluate([tree])[0] if self.time_left() else False
        if not ok:
            verdict = "not reproduced" if self.time_left() else "budget"
            return self.finish(t0, orig_lines, None, verdict)
        tree, verdict = self.shrink(tree)
        return self.finish(t0, orig_lines, tree, verdict)

    def shrink(self, tree):
        """Rounds of edits until a whole pass reproduces nothing, or time is up."""
        failed = set()
        progressed = False
        while True:
            if not self.time_left():
                return tree, "budget"
            es = [e for e in edits(tree) if e[1] not in failed]
            if not es:
                if progressed:     # something changed since the last clean pass: one more
                    failed.clear()
                    progressed = False
                    continue
                return tree, "minimal"
            chunk = es[:ROUND * self.par]
            singles = [apply(tree, [e]) for e in chunk]
            combos = []
            for part in (chunk, chunk[:len(chunk) // 2], chunk[len(chunk) // 2:]):
                if len(part) > 1:
                    c = apply(tree, part)
                    if c is not None:
                        combos.append(c)
            cands = combos + singles
            hits = self.evaluate(cands)
            good = [c for c, h in zip(cands, hits) if h]
            for e, h in zip(chunk, hits[len(combos):]):
                if h is False:
                    failed.add(e[1])
            if good:
                tree = min(good, key=size)
                progressed = True
            self.log(f"  {self.name()}: round {self.rounds}, {len(cands)} candidates, "
                     f"{hits.count(True)} reproduce, now {size(tree)} lines, "
                     f"{getattr(getattr(self, 'tc', None), 'runs', 0)} compiler runs so far")

    def name(self):
        return self.fdir.name

    def final(self, tree):
        """The reduced program alone, with only the imports it uses."""
        case = render_case(tree)
        keep = []
        for l in self.header.split("\n"):
            m = re.match(r"use std/(\w+)$", l)
            if m:
                if m.group(1) == "io" or re.search(rf"\b{m.group(1)}\.", case):
                    keep.append(l)
        return "\n".join(keep), case

    def finish(self, t0, orig_lines, tree, verdict):
        d = self.out / self.name()
        d.mkdir(parents=True, exist_ok=True)
        info = {"finding": self.name(), "seed": self.f["seed"], "case": self.idx, "kind": self.f["kind"],
                "key": self.want, "original_lines": orig_lines, "rounds": self.rounds}
        if tree is not None:
            header, case = self.final(tree)
            alone = None
            if self.deadline - time.monotonic() > self.cost * 0.6:
                alone = self.alone(tree, header)
                if not alone:          # an import mattered after all: keep them all
                    header = self.header
                    alone = self.alone(tree, header)
            prog = (header + "\n" if header else "") + case + "\n" + main_src([self.idx]) + "\n"
            (d / "reduced.dawn").write_text(prog)
            info.update(reduced_lines=len(prog.rstrip("\n").split("\n")), verified_alone=alone)
            self.drafts(d, header, case, alone)
        info.update(verdict=verdict, seconds=round(time.monotonic() - t0))
        (d / "reduce.json").write_text(json.dumps(info, indent=1) + "\n")
        shutil.rmtree(self.work, ignore_errors=True)
        return info

    def drafts(self, d, header, case, alone):
        name = f"fuzz3_s{self.f['seed']}_c{self.idx}"
        sd = d / "spike-native"
        sd.mkdir(exist_ok=True)
        note = (f"# Drafted by scripts/fuzz3/reduce.py from fuzz3 seed {self.f['seed']} case {self.idx}:\n"
                f"# {self.want}\n"
                "# Not a corpus entry yet: say in this comment what the program checks, write\n"
                f"# {name}.expect by hand, add the name to matrix.txt, and run run.sh on it.\n")
        body = (header + "\n\n" if header else "") + case + \
            f"\n\npub fn main() -> Unit !io = io.println(c{self.idx}_case())\n"
        (sd / f"{name}.dawn").write_text(note + "\n" + body)
        exp = self.jvm_answer(d / "reduced.dawn") if alone else None
        (sd / f"{name}.expect.draft").write_text(exp if exp is not None else
                                                 "(no JVM answer: the JVM side is the finding, or it was not run)\n")
        (sd / "known-red.draft").write_text("".join(f"{name}:{c}\n" for c in KNOWN_RED.get(self.f["kind"], [])))

    def jvm_answer(self, src):
        jar = self.work / "answer.jar"
        rc, o, e = self.tc.dawn("build", str(src), "-o", str(jar))
        if rc != 0:
            return None
        rc, o, e = run.sh(["java", "-XX:-UsePerfData", "-Xss512m", "-jar", str(jar)], timeout=RUN_TIMEOUT)
        if rc != 0:
            return None
        return "\n".join(l for l in o.split("\n") if not l.startswith("@@ ")).rstrip("\n") + "\n"


def pick(findings, per_sig):
    """Findings worth reducing, first example of each key first."""
    by = {}
    for fdir, f in findings:
        if f["case"] < 0 or not (fdir / "case.dawn").exists():
            continue
        by.setdefault(key(f), []).append((fdir, f))
    order = []
    for n in range(per_sig):
        for k in sorted(by):
            if n < len(by[k]):
                order.append(by[k][n])
    return order


def summary(out, infos, skipped, elapsed):
    lines = [f"fuzz3 reduce: {len(infos)} findings, {elapsed:.0f}s.", "",
             "| finding | key | lines | after | verified | verdict |", "|---|---|---:|---:|---|---|"]
    for i in infos:
        lines.append(f"| {i['finding']} | `{i['key']}` | {i['original_lines']} | {i.get('reduced_lines', '-')} "
                     f"| {i.get('verified_alone', '-')} | {i['verdict']} |")
    if skipped:
        lines += ["", f"Not reduced: {skipped} (a batch-level finding, a repeat of a key already "
                      "reduced, or out of time)."]
    lines += ["", "Drafts are under each finding's spike-native/: a program, the JVM's answer as a",
              "draft .expect, and known-red.txt lines. None of them is filed; see reduce.py's header.", ""]
    (out / "summary.md").write_text("\n".join(lines))
    drafts = [out / i["finding"] / "spike-native" / "known-red.draft" for i in infos]
    reds = sorted({l for d in drafts if d.exists() for l in d.read_text().splitlines()})
    (out / "known-red.draft").write_text("".join(l + "\n" for l in reds))


# ------------------------------------------------------------------ self-test
def self_test():
    """The tree and the edits, without a compiler; and the loop against a
    stand-in predicate, including the two that must make it fail."""
    case = "\n".join([
        "type C7R = { a: Int } derive Show", "",
        "fn c7_h0(p0: Int) -> Int = {", "let v1: Int = (p0 + 1)", "v1", "}", "",
        "fn c7_case() -> String = {", "var trace: List[String] = []",
        "var w2 = 0", "while (w2 < 3) {", "w2 = w2 + 1", "if (true) {", "let _ = 1", "} else {",
        "let _ = 2", "}", "}", "let v3: Int = match (1) {", "1 -> {", "BUG", "0", "}", "w4 -> 2", "}",
        'join(trace, "|") ++ " #" ++ to_string(v3)', "}"])
    tree = parse_case(case)
    flat = "\n".join(l for l in case.split("\n") if l.strip())
    assert render_case(tree) == flat, "render(parse(x)) != x"
    es = edits(tree)
    assert not any(e[2] == "del" and PROTECTED.match(e[1][1]) for e in es), "the loop counter is deletable"
    assert any(e[2] == "unwrap" for e in es)
    m = parse_case("fn c7_h0(p0: Int) -> Int = {\nlet v = match (p0) {\n1 -> 2\nw -> {\n3\n}\n}\nv\n}")
    got = {e[2]: e[4] for e in edits(m) if e[2] in ("stub", "join")}
    assert got == {"stub": "fn c7_h0(p0: Int) -> Int = 0", "join": "w -> { 3 }"}, got
    m = apply(m, [e for e in edits(m) if e[2] == "join"])
    assert [e[4] for e in edits(m) if e[2] == "join"] == ["let v = match (p0) { 1 -> 2, w -> { 3 } }"]

    class Stand(Reducer):
        """The real rounds, with a predicate on the text instead of a compiler."""

        def __init__(self, pred):
            self.pred, self.par, self.rounds, self.cost = pred, 1, 0, 0.0
            self.deadline, self.log = time.monotonic() + 60, lambda m: None
            self.fdir = Path("stand-in")

        def evaluate(self, trees, header=None, legs=None):
            return [bool(self.pred(render_case(t))) for t in trees]

    def shrink(pred):
        t, verdict = Stand(pred).shrink(tree)
        assert verdict == "minimal", verdict
        return t

    small = render_case(shrink(lambda s: "BUG" in s and "fn c7_case" in s))
    assert "BUG" in small and "c7_h0" not in small and "C7R" not in small, small
    assert size(parse_case(small)) <= 6, small
    # the negative controls: a predicate that always holds reduces past the
    # finding, one that never holds reduces nothing
    assert "BUG" not in render_case(shrink(lambda s: True))
    assert render_case(shrink(lambda s: False)) == flat
    # the key keeps an exit difference's two sides apart
    f = {"kind": "exit", "case": 1, "seed": 1,
         "detail": "jvm: died exit 1 panic: x\nnative: died exit 134 panic: x\n"}
    g = dict(f, detail=f["detail"].replace("134", "1"))
    assert key(f) != key(g)
    assert key(dict(f, kind="sanitizer", detail="ERROR: AddressSanitizer: x on 0x7fff10")) == \
        key(dict(f, kind="sanitizer", detail="ERROR: AddressSanitizer: x on 0x6020ab"))
    assert key(dict(f, kind="emitc-crash", detail="panic: rc: x: a return left a binding behind: 3,7")) == \
        key(dict(f, kind="emitc-crash", detail="panic: rc: x: a return left a binding behind: 4"))
    assert rename("C7S C7A c7_h0(c17_x) C7", 7, 1003) == "C1003S C1003A c1003_h0(c17_x) C7"
    print("reduce.py self-test: ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--findings", help="a run.py --out directory")
    ap.add_argument("--out", help="default: <findings>/reduced")
    ap.add_argument("--only", action="append", help="a finding directory name (repeatable)")
    ap.add_argument("--minutes", type=float, default=6)
    ap.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 4))
    ap.add_argument("--per-signature", type=int, default=2)
    ap.add_argument("--jar", default=str(run.ROOT / "build/dawn-selfhost.jar"))
    ap.add_argument("--std", default=str(run.ROOT / "std"))
    ap.add_argument("--rt", default=str(run.ROOT / "runtime/c"))
    ap.add_argument("--check-lines", type=int, metavar="N",
                    help="exit 1 unless every finding reduced to N lines or fewer and held alone "
                         "(cut 2's criterion is 20; the nightly does not pass it)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.findings:
        ap.error("give --findings or --self-test")
    started = time.monotonic()
    deadline = started + a.minutes * 60
    root = Path(a.findings).resolve()
    out = Path(a.out).resolve() if a.out else root / "reduced"
    out.mkdir(parents=True, exist_ok=True)
    found = []
    for fj in sorted(root.glob("*/finding.json")):
        if fj.parent.parent == out or (a.only and fj.parent.name not in a.only):
            continue
        found.append((fj.parent, json.loads(fj.read_text())))
    todo = pick(found, a.per_signature)
    run.RUN_TIMEOUT = RUN_TIMEOUT
    work = Path(tempfile.mkdtemp(prefix="fuzz3-rt-"))
    tc = run.Toolchain(Path(a.jar), Path(a.std) if a.std else None, Path(a.rt), work)
    lock = threading.Lock()

    def log(msg):
        with lock:
            print(msg, flush=True)

    infos = []
    # jobs split between findings first, then inside each: one finding with
    # four cores compiles four batches a round instead of idling three
    par = max(1, a.jobs // max(1, len(todo)))
    with cf.ThreadPoolExecutor(max(1, min(a.jobs, len(todo) or 1))) as pool:
        futs = []
        for fdir, f in todo:
            futs.append(pool.submit(lambda fd=fdir, ff=f: Reducer(tc, fd, ff, out, deadline, log, par).run()))
        for fu in futs:
            info = fu.result()
            infos.append(info)
            log(f"REDUCED {info['finding']}: {info['original_lines']} -> {info.get('reduced_lines', '-')} lines, "
                f"{info['verdict']}, verified alone {info.get('verified_alone')}, {info['seconds']}s")
    shutil.rmtree(work, ignore_errors=True)
    elapsed = time.monotonic() - started
    summary(out, infos, len(found) - len(infos), elapsed)
    print(f"fuzz3 reduce: {len(infos)} reduced of {len(found)} findings, {elapsed:.0f}s", flush=True)
    if a.check_lines is not None:
        bad = [i["finding"] for i in infos
               if not i.get("verified_alone") or i.get("reduced_lines", a.check_lines + 1) > a.check_lines]
        bad += [fd.name for fd, f in todo if fd.name not in {i["finding"] for i in infos}]
        if bad:
            print(f"FAIL: not reduced to {a.check_lines} lines and held alone: {', '.join(bad)}", flush=True)
            sys.exit(1)
        print(f"OK: every finding reduced to {a.check_lines} lines or fewer and held alone", flush=True)


if __name__ == "__main__":
    main()

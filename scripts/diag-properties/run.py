#!/usr/bin/env python3
"""Recovery properties of the diagnostics, under one-token mutations.

    scripts/diag-properties/run.py                     # every tracked .dawn file
    scripts/diag-properties/run.py --dawn <launcher>   # another toolchain (a mutant)
    scripts/diag-properties/run.py --self-test         # the judges on tiny inputs

Why this exists. Every corpus of diagnostics in the tree (grammar-corpus
reject cases, checker-corpus goldens, the parser's inline tests) was written
by someone who already knew what the mistake was, and records what the
compiler says about exactly that input. Three shipped recovery defects sat
one token away from inputs like those. #190: a missing comma in a record
literal made the statement resync stop at the literal's own `}`, so the rest
of the body fell out to module level as false "only declarations are
allowed" errors. #191: deleting the `}` of an interpolation reported
"unterminated string" at the closing quote and dropped the rest of the line,
while the diagnostic written for that case was unreachable. 24ab1b6e: the
declaration resync skipped over `use` and `test`, so one bad line lost every
import and test block up to the next `fn`. Nobody wrote a case for any of
them because nobody had made that typo yet. So this makes the typos, one
token at a time and in every file, and asks what any good recovery owes:

  (a) no crash: `__parse` of every mutant, and `__check` of every mutant
      that still parses, exit 0 within the time limit and print a section
      for every file. (--check-paths narrows the second half; the default
      is every file: 282s on four pinned cores, against 139s for
      checker-corpus and examples alone.)
  (b) near: the first diagnostic (the first one `dawn check` prints) has a
      span, its own or a note's, within 2 lines of the mutated token.
  (c) no top-level cascade: a mutation strictly inside a braced fn or test
      body, of a token that is no bracket, raises no "only declarations
      ... are allowed at module top level" error. The body's braces are
      intact, so nothing in it can have reached module level but through a
      resync that crossed a `}` it should have stopped at (#190).
  (d) later declarations survive: for the same bracket-neutral mutations,
      every top-level declaration that begins after the declaration holding
      the mutation is still in the tree, at its shifted offset, unchanged.
      A resync that skips past a declaration keyword loses them (24ab1b6e).

A mutation is one of: delete a token (its characters become blanks, so no
line moves and the neighbours cannot fuse), insert a copy of a token from the
same file before another token, or delete the `}` that closes an
interpolation (`"${x}"` to `"${x"`, #191; the lexer keeps a string with its
interpolations as one token, so the token-level mutations never reach it).
A token is a bracket when it is one of ( ) [ ] { }: adding or removing one
legitimately moves where a body ends, so (c) and (d) judge only the others.
An interpolation's `}` is no bracket of the code around the string, and a
lexer that recovers from it well leaves the code around the string intact.

Determinism. File f's mutations draw from random.Random("<seed>:<f>"), so a
finding is reproduced from the seed and the file; nothing reads the clock.
--out keeps every mutant next to its original as `<stem>__m<k>.dawn`.

Why a script outside the compiler. Same reason as scripts/fmt-properties:
the checks read only what the CLI prints (`__lex`, `__parse`, `__check`), so
they are the same for any toolchain passed with --dawn, which is how a
restored defect is shown red (the report on this cut, prop-k2, has the
toolchains for #190, #191 and 24ab1b6e).

What is not judged, and why. (b) is judged on syntax diagnostics only. A
mutant that still parses is a different well-formed program, and where its
first type error falls is a fact about that program (deleting `pub` is
reported at the importer), not about recovery; such mutants get (a) from
`__check`. A mutant with no diagnostic at all is a valid program and passes.

Why nightly. The push total has no room (ruling on bug-rate, 2026-10-04),
and the run finds recovery defects in old code rather than guarding a change.

Output: one line per finding, `<property> <rule> <file> [<kind>]: <detail>`,
a summary, and the verdict line `verdict: <keys>`, the sorted set of
`<property>:<rule>:<kind>`, so a nightly issue is commented on when a kind of
finding appears or goes, not every night the same files are listed. Exit 1
when anything is found.
"""

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANY_SPAN = re.compile(r"@\d+\.\.\d+")
SPAN = re.compile(r"@(\d+)\.\.(\d+)$")
BRACKETS = {"LPAREN", "RPAREN", "LBRACKET", "RBRACKET", "LBRACE", "RBRACE"}
TOP_LEVEL = "are allowed at module top level"
NEAR = 2  # lines either side of the mutated token

# ---------------------------------------------------------------- toolchain


class Crash(Exception):
    pass


def run_batch(dawn, mode, files, limit):
    """`dawn <mode> files...` -> {path: section lines}, or Crash with a reason."""
    try:
        p = subprocess.run([dawn, mode] + files, cwd=ROOT, capture_output=True,
                           text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        raise Crash(f"no answer within {limit}s")
    out, cur, buf = {}, None, []
    for line in p.stdout.split("\n"):
        if line.startswith("== ") and line.endswith(" =="):
            if cur is not None:
                out[cur] = buf
            cur, buf = line[3:-3], []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = buf
    if p.returncode != 0 or any(f not in out for f in files):
        lines = [ln for ln in p.stderr.split("\n") if ln.strip()]
        # the first line that names what went wrong, not a launcher banner
        why = next((ln for ln in lines if re.search(r"panic|Exception|Error|error", ln)),
                   lines[0] if lines else "no output")
        raise Crash(f"exit {p.returncode}: {why.strip()[:200]}")
    return out


def run_all(dawn, mode, files, jobs, chunk=200):
    """Sections for every file that did not crash, and {file: reason} for those
    that did. A crashing batch is halved until the file is found."""
    sections, crashes = {}, {}

    def one(group):
        res, bad = {}, {}
        stack = [group]
        while stack:
            g = stack.pop()
            try:
                res.update(run_batch(dawn, mode, g, 120 + len(g)))
            except Crash as c:
                if len(g) == 1:
                    bad[g[0]] = str(c)
                else:
                    stack += [g[:len(g) // 2], g[len(g) // 2:]]
        return res, bad

    groups = [files[i:i + chunk] for i in range(0, len(files), chunk)]
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for res, bad in ex.map(one, groups):
            sections.update(res)
            crashes.update(bad)
    return sections, crashes


# ---------------------------------------------------------------- dumps


class Tok:
    __slots__ = ("kind", "lo", "hi", "parts")

    def __init__(self, kind, lo, hi, parts):
        self.kind, self.lo, self.hi, self.parts = kind, lo, hi, parts


def parse_lex(lines):
    toks, diags = [], 0
    for ln in lines:
        if not ln:
            continue
        f = ln.split("\t")
        if f[0] == "!":
            diags += 1
        elif len(f) >= 3:
            toks.append(Tok(f[0], int(f[1]), int(f[2]), f[4:]))
    return toks, diags


class Diag:
    __slots__ = ("lo", "hi", "msg", "spans")

    def __init__(self, lo, hi, msg, spans):
        self.lo, self.hi, self.msg, self.spans = lo, hi, msg, spans


def parse_diag(line):
    """`!  lo  hi  msg  hint  [note  lo  hi  msg]...`"""
    f = line.split("\t")
    lo, hi = int(f[1]), int(f[2])
    spans = [(lo, hi)]
    i = 5
    while i + 2 < len(f):
        if f[i] == "note":
            spans.append((int(f[i + 1]), int(f[i + 2])))
            i += 4
        else:
            i += 1
    return Diag(lo, hi, f[3] if len(f) > 3 else "", spans)


class Node:
    __slots__ = ("kind", "head", "lo", "hi", "kids")

    def __init__(self, kind, head, lo, hi):
        self.kind, self.head, self.lo, self.hi = kind, head, lo, hi
        self.kids = []


def parse_ast(lines):
    """(module node, diagnostics) of one `__parse` section."""
    root, stack, diags = None, [], []
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("!"):
            diags.append(parse_diag(ln))
            continue
        depth = (len(ln) - len(ln.lstrip(" "))) // 2
        body = ln[2 * depth:]
        m = SPAN.search(body)
        lo, hi = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        if body.startswith("SText"):
            lo, hi = None, None
        n = Node(body.split(" ")[0], ANY_SPAN.sub("@", body), lo, hi)
        while len(stack) > depth:
            stack.pop()
        if stack:
            stack[-1].kids.append(n)
        else:
            root = n
        stack.append(n)
    return root, diags


def walk(n):
    yield n
    for k in n.kids:
        yield from walk(k)


def braced_bodies(root, text):
    """(lo, hi) of every fn and test body that is a braced block."""
    out = []
    for n in walk(root):
        if n.kind not in ("Fn", "Test") or not n.kids:
            continue
        b = n.kids[-1]
        if b.kind == "Block" and b.lo is not None and text[b.lo:b.lo + 1] == "{":
            out.append((b.lo, b.hi))
    return out


def top_decls(root):
    return [k for k in root.kids if k.lo is not None] if root else []


# ---------------------------------------------------------------- mutations


def line_starts(text):
    starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            starts.append(i + 1)
    return starts


def line_of(starts, off):
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= off:
            lo = mid
        else:
            hi = mid - 1
    return lo


def interp_closers(text, toks):
    """Offsets of the `}` that closes each interpolation in a string token. The
    lex dump gives each interpolation's code offset (`C:<off>:<code>`); the
    closer is found by scanning the source from there, skipping nested braces
    and nested string literals, and is kept only where the scan lands on `}`."""
    out = []
    for t in toks:
        if t.kind != "STRING":
            continue
        for part in t.parts:
            if not part.startswith("C:"):
                continue
            c = int(part.split(":")[1])
            if text[c - 2:c] != "${":
                continue
            depth, i, ok = 0, c, False
            while i < t.hi:
                ch = text[i]
                if ch == '"':
                    i += 1
                    while i < t.hi and text[i] != '"':
                        i += 2 if text[i] == "\\" else 1
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    if depth == 0:
                        ok = True
                        break
                    depth -= 1
                i += 1
            if ok:
                out.append(i)
    return out


class Mutant:
    __slots__ = ("path", "kind", "at", "shift", "neutral", "what", "partner")

    def __init__(self, path, kind, at, shift, neutral, what, partner=None):
        # at: offset of the mutated token in the mutant (and in the original:
        # nothing before it moves); shift: characters added at `at`; partner:
        # for a deleted bracket, the offset of the one it paired with
        self.path, self.kind, self.at, self.shift, self.neutral, self.what, self.partner = \
            path, kind, at, shift, neutral, what, partner


def partners(code):
    """{offset: offset} between each bracket and the one it pairs with."""
    pair, stack = {}, []
    for t in code:
        if t.kind in ("LPAREN", "LBRACKET", "LBRACE"):
            stack.append(t)
        elif t.kind in ("RPAREN", "RBRACKET", "RBRACE") and stack:
            o = stack.pop()
            pair[o.lo], pair[t.lo] = t.lo, o.lo
    return pair


def mutate(text, toks, rng, n):
    """n (mutant text, kind, at, shift, neutral, what, partner) for one file."""
    code = [t for t in toks if t.kind not in ("NEWLINE", "EOF", "COMMENT")
            and "\n" not in text[t.lo:t.hi]]
    if not code:
        return []
    closers = interp_closers(text, toks)
    pair = partners(code)
    out, made = [], set()
    for _ in range(n):
        r = rng.random()
        if closers and r < 0.1:
            at = rng.choice(closers)
            out.append((text[:at] + " " + text[at + 1:], "delete-interp", at, 0, True,
                        "deleted an interpolation's `}`", None))
        elif r < 0.55:
            t = rng.choice(code)
            word = text[t.lo:t.hi]
            neutral = t.kind not in BRACKETS
            out.append((text[:t.lo] + " " * (t.hi - t.lo) + text[t.hi:],
                        "delete-" + ("other" if neutral else "bracket"), t.lo, 0, neutral,
                        f"deleted `{word[:30]}`", pair.get(t.lo)))
        else:
            t = rng.choice(code)
            src = rng.choice(code)
            word = text[src.lo:src.hi]
            ins = word + " "
            if t.lo > 0 and not text[t.lo - 1].isspace():
                ins = " " + ins
            neutral = src.kind not in BRACKETS
            out.append((text[:t.lo] + ins + text[t.lo:],
                        "insert-" + ("other" if neutral else "bracket"), t.lo, len(ins), neutral,
                        f"inserted `{word[:30]}` before `{text[t.lo:t.hi][:30]}`", None))
    # the same token drawn twice is one mutant
    return [m for m in out if not (m[0] in made or made.add(m[0]))]


# ---------------------------------------------------------------- judges


def judge_parse(mut, text, starts, root0, bodies, diags, root):
    """Rules (b), (c), (d) for one mutant. Yields (property, rule, detail).
    `text`, `starts`, `root0` and `bodies` are the original's."""
    mline = line_of(starts, mut.at)
    # a deleted bracket is reported well at the one it paired with, too: a
    # missing `}` is the `{` left open, however long the block between
    anchors = [mline] + ([line_of(starts, mut.partner)] if mut.partner is not None else [])
    if diags:
        d = diags[0]
        def back(o):
            # spans are the mutant's; nothing before `at` moved
            return min(len(text), o if o <= mut.at else max(mut.at, o - mut.shift))

        # a span counts by the lines it covers: a diagnostic on a construct
        # that starts above the mutation and runs through it is about it
        dist = []
        for lo, hi in d.spans:
            a, b = line_of(starts, back(lo)), line_of(starts, back(max(lo, hi - 1)))
            for m in anchors:
                dist.append(0 if a <= m <= b else min(abs(a - m), abs(b - m)))
        if min(dist) > NEAR:
            yield ("b", "near", f"line {mline + 1}: {mut.what}; the first diagnostic is at line "
                   f"{line_of(starts, back(d.lo)) + 1}: {d.msg[:100]}")
    if not mut.neutral:
        return
    in_body = any(lo < mut.at < hi - 1 for lo, hi in bodies)
    if in_body:
        for d in diags:
            if TOP_LEVEL in d.msg:
                off = d.lo if d.lo <= mut.at else max(mut.at, d.lo - mut.shift)
                yield ("c", "top-level", f"line {mline + 1}: {mut.what} inside a body; a "
                       f"top-level error follows at line {line_of(starts, off) + 1}")
                break
    decls0 = top_decls(root0)
    anchor = next((i for i, k in enumerate(decls0) if k.hi > mut.at), None)
    if anchor is None:
        return
    have = {(k.lo, k.head) for k in top_decls(root)}
    for k in decls0[anchor + 1:]:
        if (k.lo + mut.shift, k.head) not in have:
            yield ("d", "decl-lost", f"line {mline + 1}: {mut.what}; the {k.kind} at line "
                   f"{line_of(starts, k.lo) + 1} is gone from the tree")
            break


# ---------------------------------------------------------------- driver


def tracked(pattern):
    p = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--", *pattern],
                       capture_output=True, text=True, check=True)
    return sorted(f for f in p.stdout.split("\0") if f)


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dawn", default=os.path.join(ROOT, "bin", "dawn"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mutants", type=int, default=12, help="mutants per file")
    ap.add_argument("--check-paths", default=".",
                    help="a regex: mutants of these files that still parse also go through "
                         "__check (default: every file)")
    ap.add_argument("--only", help="a regex the input paths must match")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", help="keep the work tree here (default: a temporary one)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test(a.dawn)

    work = os.path.abspath(a.out) if a.out else tempfile.mkdtemp(prefix="diag-properties-")
    if a.out:
        shutil.rmtree(work, ignore_errors=True)
    src = os.path.join(work, "src")
    # the mirror: every tracked .dawn and the manifests that resolve their path
    # dependencies, so a mutant's imports find what the original's found
    for f in tracked(["*.dawn", "*dawn.toml", "*dawn.lock"]):
        write(os.path.join(src, f), read(os.path.join(ROOT, f)))
    inputs = tracked(["*.dawn"])
    if a.only:
        inputs = [f for f in inputs if re.search(a.only, f)]

    def at(f):
        return os.path.join(src, f)

    lex0, lcrash = run_all(a.dawn, "__lex", [at(f) for f in inputs], a.jobs)
    ast0, pcrash = run_all(a.dawn, "__parse", [at(f) for f in inputs], a.jobs)
    findings = []
    for f in inputs:
        for layer, crashes in (("lex", lcrash), ("parse", pcrash)):
            if at(f) in crashes:
                findings.append(("a", "crash-" + layer, f, "unmutated", crashes[at(f)]))
    clean, info = [], {}
    for f in inputs:
        if at(f) not in lex0 or at(f) not in ast0:
            continue
        toks, ld = parse_lex(lex0[at(f)])
        root, pd = parse_ast(ast0[at(f)])
        if ld or pd or root is None:
            continue
        text = read(at(f))
        clean.append(f)
        info[f] = (text, line_starts(text), root, braced_bodies(root, text), toks)

    # the mutants, next to their originals
    muts = []
    for f in clean:
        text, _, _, _, toks = info[f]
        rng = random.Random(f"{a.seed}:{f}")
        stem = f[:-len(".dawn")]
        for k, (mt, kind, off, shift, neutral, what, partner) in enumerate(
                mutate(text, toks, rng, a.mutants)):
            mp = f"{stem}__m{k}.dawn"
            write(at(mp), mt)
            muts.append((f, Mutant(mp, kind, off, shift, neutral, what, partner)))

    astm, mcrash = run_all(a.dawn, "__parse", [at(m.path) for _, m in muts], a.jobs)
    to_check, verdicts = [], {"parse": 0, "check": 0}
    for f, m in muts:
        if at(m.path) in mcrash:
            findings.append(("a", "crash-parse", f, m.kind,
                             f"{m.what} (line {line_of(info[f][1], m.at) + 1}, {m.path}): "
                             f"{mcrash[at(m.path)]}"))
            continue
        root, diags = parse_ast(astm[at(m.path)])
        verdicts["parse"] += 1
        text, starts, root0, bodies, _ = info[f]
        for prop, rule, detail in judge_parse(m, text, starts, root0, bodies, diags, root):
            findings.append((prop, rule, f, m.kind, detail))
        if not diags and re.search(a.check_paths, f):
            to_check.append((f, m))

    # the checker on what still parses, after its originals: an original that
    # the checker cannot take on its own (a module that is not an entry point
    # of anything that parses alone) leaves its mutants out
    base = sorted({f for f, _ in to_check})
    _, bcrash = run_all(a.dawn, "__check", [at(f) for f in base], a.jobs, chunk=50)
    for f in base:
        if at(f) in bcrash:
            findings.append(("a", "crash-check", f, "unmutated", bcrash[at(f)]))
    to_check = [(f, m) for f, m in to_check if at(f) not in bcrash]
    _, ccrash = run_all(a.dawn, "__check", [at(m.path) for _, m in to_check], a.jobs, chunk=50)
    for f, m in to_check:
        verdicts["check"] += 1
        if at(m.path) in ccrash:
            findings.append(("a", "crash-check", f, m.kind,
                             f"{m.what} (line {line_of(info[f][1], m.at) + 1}, {m.path}): "
                             f"{ccrash[at(m.path)]}"))

    # one line per finding, the first few per (property, rule, file)
    seen = {}
    for prop, rule, f, kind, detail in sorted(findings):
        key = (prop, rule, f)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= 3:
            print(f"{prop} {rule} {f} [{kind}]: {detail}")
    for key, n in sorted(seen.items()):
        if n > 3:
            print(f"{key[0]} {key[1]} {key[2]}: {n - 3} more")
    kinds = {}
    for _, m in muts:
        kinds[m.kind] = kinds.get(m.kind, 0) + 1
    print(f"inputs: {len(inputs)} files, {len(clean)} lex and parse cleanly")
    print(f"mutants: {len(muts)} ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}); "
          f"{verdicts['parse']} judged on __parse, {verdicts['check']} still parse and went "
          f"through __check")
    if not a.out:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"work tree kept in {work}")
    if findings:
        sigs = sorted({f"{p}:{r}:{k}" for p, r, _, k, _ in findings})
        print(f"{len(findings)} findings in {len(seen)} (property, rule, file) keys")
        print("verdict: " + ",".join(sigs))
        return 1
    print("verdict: green")
    return 0


# ---------------------------------------------------------------- self-test


def self_test(dawn):
    """Each judge on an input it must flag and one it must pass. The diagnostics
    are written here, not asked of a toolchain, so a judge is tested apart from
    the parser it judges; one real round trip checks the dump readers."""
    text = ("use std/str\n"            # line 1
            "fn f() -> Int = {\n"      # 2
            "  let a = 1\n"            # 3
            "  a\n"                    # 4
            "}\n"                      # 5
            "\n"                       # 6
            "\n"                       # 7
            "\n"                       # 8
            "test \"t\" {\n"           # 9
            "  assert f() == 1\n"      # 10
            "}\n")                     # 11
    tmp = tempfile.mkdtemp(prefix="diag-properties-self-")
    p = os.path.join(tmp, "c.dawn")
    write(p, text)
    lex = run_batch(dawn, "__lex", [p], 120)
    ast = run_batch(dawn, "__parse", [p], 120)
    shutil.rmtree(tmp, ignore_errors=True)
    toks, ld = parse_lex(lex[p])
    root, pd = parse_ast(ast[p])
    starts = line_starts(text)
    bodies = braced_bodies(root, text)
    bad = 0

    def expect(name, ok):
        nonlocal bad
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        bad += 0 if ok else 1

    expect("the sample parses cleanly", not ld and not pd and root is not None)
    expect("both braced bodies are found", len(bodies) == 2)
    expect("three top-level declarations", len(top_decls(root)) == 3)
    let_at = text.index("let")
    a_at = text.index("a\n}")
    mut = Mutant("x", "delete-other", let_at, 0, True, "deleted `let`")
    mut_line4 = Mutant("x", "delete-other", a_at, 0, True, "deleted `a`")

    def rules(m, diags, r=root):
        return {rule for _, rule, _ in judge_parse(m, text, starts, root, bodies, diags, r)}

    far = Diag(text.index("assert"), text.index("assert") + 6, "far away", [])
    far.spans = [(far.lo, far.hi)]
    near = Diag(let_at + 4, let_at + 5, "near", [(let_at + 4, let_at + 5)])
    noted = Diag(far.lo, far.hi, "far, with a note near", [(far.lo, far.hi), (let_at, let_at + 3)])
    top = Diag(a_at, a_at + 1, "only declarations (use, fn) " + TOP_LEVEL, [(a_at, a_at + 1)])
    expect("(b) flags a first diagnostic 7 lines away", "near" in rules(mut, [far]))
    expect("(b) passes one on the next line", "near" not in rules(mut, [near]))
    expect("(b) passes a far one whose note is near", "near" not in rules(mut, [noted]))
    expect("(b) judges the first diagnostic only", "near" not in rules(mut, [near, far]))
    expect("(c) flags a top-level error after a body mutation", "top-level" in rules(mut_line4, [near, top]))
    brk = Mutant("x", "delete-bracket", a_at, 0, False, "deleted `}`")
    closer = text.index("}\n\n")
    lone = Mutant("x", "delete-bracket", closer, 0, False, "deleted `}`")
    paired = Mutant("x", "delete-bracket", closer, 0, False, "deleted `}`", text.index("{"))
    opener = Diag(text.index("{"), text.index("{") + 1, "unclosed", [(text.index("{"), text.index("{") + 1)])
    at_eof = Diag(len(text) - 1, len(text), "eof", [(len(text) - 1, len(text))])
    expect("(b) takes the opener of a deleted closer as near", "near" not in rules(paired, [opener]))
    expect("(b) wants the opener's line, not any line", "near" in rules(paired, [at_eof]))
    expect("(b) has no opener to take without the pairing", "near" in rules(lone, [far]))
    expect("(c) leaves a bracket mutation alone", "top-level" not in rules(brk, [near, top]))
    outside = Mutant("x", "delete-other", text.index("std"), 0, True, "deleted `std`")
    expect("(c) leaves a mutation outside a body alone", "top-level" not in rules(outside, [near, top]))
    lost = Node("Module", "Module", None, None)
    lost.kids = top_decls(root)[:2]
    expect("(d) flags a later declaration gone", "decl-lost" in rules(mut, [near], lost))
    expect("(d) passes the full tree", "decl-lost" not in rules(mut, [near], root))
    moved = Mutant("x", "insert-other", let_at, 4, True, "inserted `let`")
    expect("(d) wants a later declaration at its shifted offset",
           "decl-lost" in rules(moved, [near], root))
    at_assert = Mutant("x", "delete-other", text.index("assert"), 0, True, "deleted `assert`")
    whole = Diag(text.index("fn f"), len(text) - 1, "from line 2 to the end",
                 [(text.index("fn f"), len(text) - 1)])
    expect("(b) passes a span that runs through the mutated line", "near" not in rules(at_assert, [whole]))
    closers = interp_closers('f("a${x}b${g("}")}")', [Tok("STRING", 2, 19, ["T:a", "C:6:x", "T:b", "C:11:g(\"}\")"])])
    expect("an interpolation's closer is found past a nested string", closers == [7, 17])
    # a launcher that dies on one file: the batch is halved down to it
    tmp = tempfile.mkdtemp(prefix="diag-properties-self-")
    fake = os.path.join(tmp, "dawn")
    write(fake, "#!/usr/bin/env python3\nimport sys\n"
          "if any('boom' in f for f in sys.argv[2:]): sys.exit('panic: boom')\n"
          "for f in sys.argv[2:]: print('== ' + f + ' ==')\n")
    os.chmod(fake, 0o755)
    names = [f"f{i}.dawn" for i in range(9)] + ["boom.dawn"] + [f"g{i}.dawn" for i in range(5)]
    secs, crashes = run_all(fake, "__parse", names, 2, chunk=8)
    shutil.rmtree(tmp, ignore_errors=True)
    expect("a crash is found by halving, and only that file",
           list(crashes) == ["boom.dawn"] and "panic: boom" in crashes["boom.dawn"]
           and len(secs) == len(names) - 1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

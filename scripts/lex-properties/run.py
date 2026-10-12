#!/usr/bin/env python3
"""The lexer's dump as a round trip, and the two highlighters held against it.

    scripts/lex-properties/run.py                     # every tracked .dawn file
    scripts/lex-properties/run.py --dawn <launcher>   # another toolchain (a mutant)
    scripts/lex-properties/run.py --self-test         # the judges on tiny inputs

Why this exists. Dawn's string, comment and interpolation rules are written
four times: the compiler's lexer (front/lexer.dawn), the site's build-time
highlighter (site/src/hl/dawn.dawn), the Playground's stream tokenizer and,
in the same file, the Playground's `lexContext`, which decides how completion
behaves at the cursor (site/play-ui/src/dawn-lang.ts). The 2026-10-04 bug
survey put "two copies of one rule drift apart" among the families nothing
watched: #83 (the editor lost a string's state after an interpolation), #188
(fmt's and the lexer's continuation sets), #320 and #350. Each copy has hand
picked examples; none has ever been held against the lexer on real code. So
this is cut 3 of the property-test line (the bug-rate plan, 7.2). The other
round trips that cut weighed already have a gate (parse then fmt then parse,
and fmt's idempotence, in scripts/fmt-properties; the three-way backend
differential in scripts/fuzz3) or have no reader to round-trip through (the Core IR dump).

  (a) The lexer's dump is a round trip of the source. Tokens come in order and
      do not overlap; each token's text is the source between its offsets; what
      lies between tokens is whitespace or a `#` comment and nothing else; and
      each interpolation's code is the source at its offset, between a `${` and
      a `}`, inside its string. Lexed again on its own (as the parser does), an
      interpolation's code holds to the same, recursively. Every other check
      here derives the lexer's reading from this dump, so a dump whose offsets
      drift would make them judge against the wrong answer; and the offsets are
      what diagnostics, hover and semantic tokens point with.
  (b) The highlighters read regions as the lexer does. Every code point is
      comment, string, interpolation delimiter (`${` and its `}`) or code by
      the lexer; the site's and the editor's classes must agree on each one
      (keyword, type, number and plain text are all "code" here; inside a char
      literal nothing is judged). A hard keyword of the lexer (a word with a
      token kind of its own) must be coloured as a keyword by both. And `lexContext`, asked
      at positions the editor bundle samples, must say comment inside a
      comment, string inside a string, code (or its `interp`) inside an
      interpolation's code and code elsewhere.

Oracle. The lexer is the language's definition, so it is the answer; neither
highlighter is judged against the other. The checks read only CLI output
(`dawn __lex`), the site's `highlight_dawn` through a project that depends on
the site (sitehl/), and the editor's own module bundled with its own esbuild
(site/play-ui/test/lex-classes.ts): no copy of any of the four rules lives here.

Determinism. Inputs are the tracked files; the only draw is `lexContext`'s
positions, seeded by the path in lex-classes.ts. Nothing reads the clock.

Known findings. The first run's findings are filed as issues and pinned in
KNOWN_KEYS, one `<property> <rule> <subject> <where>` per line with its issue,
`<where>` being the file, or the word for a keyword finding (a word missing
from a highlighter's list is one defect however many files use it). A pin the
run no longer finds is stale and fails the run, so the list only shrinks; a
finding in a file not pinned is new and fails it, which is how a restored
defect shows red under pins that already cover its kind.

Why nightly. The push total has no room (ruling on bug-rate, 2026-10-04), and
this finds drift in three copies nobody edits often, rather than guarding a
change. Measured 2026-10-12 on four cores: see the nightly job's comment.
"""

import argparse
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
PLAY_UI = os.path.join(ROOT, "site", "play-ui")

# A hard keyword is a word the lexer gives a kind of its own, named after it
# (`fn` is FN): read from the dump, so no copy of front/token's `keyword` table
# lives here. TRUE and FALSE are left out: the highlighters colour them as
# literals.
NOT_KEYWORDS = {"IDENT", "TRUE", "FALSE"}


def hard_keyword(t):
    return t.text.isalpha() and t.text.islower() and t.kind == t.text.upper() \
        and t.kind not in NOT_KEYWORDS

# Findings of the first run, filed and pinned: `<property> <rule> <subject> <where>`.
KNOWN_KEYS = """
# #709: lexContext does not track strings or braces inside `${...}`, and takes
# `\\$name` for an interpolation.
b context lexContext packages/xmap/src/javap.dawn
b context lexContext scripts/dict-owner-contract/eq_string.dawn
b context lexContext scripts/example-main-contract/fixtures/literals.dawn
b context lexContext scripts/grammar-corpus/accept/dollar_literals.dawn
b context lexContext scripts/grammar-corpus/accept/string_interp.dawn
b context lexContext scripts/pipe-contract/cases/order.dawn
b context lexContext scripts/pipe-contract/cases/qualified.dawn
b context lexContext scripts/spike-native/apply_postfix.dawn
b context lexContext scripts/spike-native/bounded_value_effvar.dawn
b context lexContext scripts/spike-native/bounded_value_trait.dawn
b context lexContext scripts/spike-native/const_fold.dawn
b context lexContext scripts/spike-native/erased/src/main.dawn
b context lexContext scripts/spike-native/fn_value_bounds.dawn
b context lexContext scripts/spike-native/list_elems.dawn
b context lexContext scripts/spike-native/pipe_general.dawn
b context lexContext scripts/spike-native/rc_reuse_early_exit.dawn
b context lexContext scripts/tile-gpu-diff/scalar_diff.dawn
b context lexContext site/play-ui/samples/records.dawn
b context lexContext site/src/gen/gpu.dawn
"""

# ---------------------------------------------------------------- toolchain


def run_chunks(cmd, files, jobs, chunk=300, cwd=ROOT):
    groups = [files[i:i + chunk] for i in range(0, len(files), chunk)]

    def one(g):
        p = subprocess.run(cmd + g, cwd=cwd, capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit(f"{' '.join(cmd[:3])} failed (exit {p.returncode}):\n{p.stderr[-2000:]}")
        return p.stdout

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(one, groups))


def unesc(s):
    """Undo lexdump's `esc`: backslash, newline, tab, CR."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


class Tok:
    __slots__ = ("kind", "lo", "hi", "text", "segs")

    def __init__(self, kind, lo, hi, text, segs):
        self.kind, self.lo, self.hi, self.text, self.segs = kind, lo, hi, text, segs


def parse_lex(lines):
    """(tokens, diagnostic count) of one file's `__lex` section. A STRING's
    segs are its interpolations as (offset, code)."""
    toks, diags = [], 0
    for ln in lines:
        if not ln:
            continue
        f = ln.split("\t")
        if f[0] == "!":
            diags += 1
            continue
        segs = []
        if f[0] == "STRING":
            for x in f[4:]:
                if x.startswith("C:"):
                    off, _, code = x[2:].partition(":")
                    segs.append((int(off), unesc(code)))
        toks.append(Tok(f[0], int(f[1]), int(f[2]), unesc(f[3]), segs))
    return toks, diags


def lex_files(dawn, files, jobs):
    out = {}
    for so in run_chunks([dawn, "__lex"], files, jobs):
        cur, buf = None, []
        for line in so.split("\n"):
            if line.startswith("== ") and line.endswith(" =="):
                if cur is not None:
                    out[cur] = buf
                cur, buf = line[3:-3], []
            elif cur is not None:
                buf.append(line)
        if cur is not None:
            out[cur] = buf
    return {k: parse_lex(v) for k, v in out.items()}


# ---------------------------------------------------------------- (a) round trip


class Reading:
    """The lexer's reading of one file: per code point a region (`c` comment,
    `s` string, `i` interpolation delimiter, `o` code, `x` not judged), the
    hard keywords' spans, and the expected cursor context per position."""

    def __init__(self, n):
        self.region = ["o"] * n
        self.ctx = ["code"] * (n + 1)
        self.keywords = []  # (lo, hi, word)


def check_lex(src, toks, base, seg_lex, rd, out, depth=0, end=None):
    """Rule (a) over one token list whose offsets are relative to `base`;
    fills `rd` with the lexer's reading as it goes. `seg_lex(code)` is the
    lexer's tokens for an interpolation's code lexed on its own."""
    end = len(src) if end is None else end
    prev = base
    for t in toks:
        lo, hi = t.lo + base, t.hi + base
        if t.kind == "EOF" or lo >= end:
            # the end of the input; lexed on its own, an interpolation's code
            # also ends in a NEWLINE the source does not have
            gap(src, prev, end, rd, out)
            break
        if lo < prev or hi < lo:
            out.append(("lex-order", lo, f"{t.kind} at {lo}..{hi} starts before the previous token ends ({prev})"))
            return
        gap(src, prev, lo, rd, out)
        text = "\n" if t.kind == "NEWLINE" else t.text  # the dump prints it as `\\n`
        if src[lo:hi] != text:
            out.append(("lex-text", lo, f"{t.kind} at {lo}..{hi} prints {t.text!r}, the source there is {src[lo:hi]!r}"))
            return
        prev = hi
        if t.kind == "STRING":
            opener = 3 if t.text.startswith('"""') else 1
            for p in range(lo, hi):
                rd.region[p] = "s"
            for p in range(lo + 1, hi):
                rd.ctx[p] = "string"
            for p in list(range(lo + 1, lo + opener)) + list(range(hi - opener + 1, hi)):
                rd.ctx[p] = "*"
            for off, code in t.segs:
                o = off + base
                e = o + len(code)
                if not (lo < o - 2 and e < hi) or src[o - 2:o] != "${" or src[e:e + 1] != "}" \
                        or src[o:e] != code:
                    out.append(("lex-seg", o, f"interpolation code {code!r} at {o} is not the source "
                                f"between a `${{` and a `}}` in its string ({src[o - 2:e + 1]!r})"))
                    return
                rd.region[o - 2] = rd.region[o - 1] = rd.region[e] = "i"
                for p in range(o, e):
                    rd.region[p] = "o"
                for p in range(o, e + 1):
                    rd.ctx[p] = "icode"
                inner = seg_lex(code)
                if inner is None:
                    out.append(("lex-seg", o, f"interpolation code {code!r} does not lex on its own"))
                    return
                check_lex(src, inner, o, seg_lex, rd, out, depth + 1, e)
        elif t.kind == "CHAR":
            for p in range(lo, hi):
                rd.region[p] = "x"
        elif hard_keyword(t):
            rd.keywords.append((lo, hi, t.text))
    else:
        gap(src, prev, end, rd, out)


def gap(src, lo, hi, rd, out):
    """Between tokens: whitespace, or a `#` comment to the end of its line."""
    p = lo
    while p < hi:
        c = src[p]
        if c == "#":
            e = src.find("\n", p, hi)
            e = hi if e < 0 else e
            for q in range(p, e):
                rd.region[q] = "c"
            for q in range(p + 1, e + 1):
                rd.ctx[q] = "comment"
            p = e
        elif c in " \t\r\n\f":
            p += 1
        else:
            out.append(("lex-gap", p, f"{src[p:p + 12]!r} lies between tokens and is no comment"))
            return


def read_dawn(src, toks, seg_lex):
    rd = Reading(len(src))
    out = []
    check_lex(src, toks, 0, seg_lex, rd, out)
    return rd, out


# ---------------------------------------------------------------- (b) highlighters


SPAN = re.compile(r'<span class="([a-z]+)">(.*?)</span>', re.S)
SITE_REGION = {"c": "c", "s": "s", "i": "i"}


def site_classes(markup):
    """Per code point: c, s, i, k (keyword) or o, from highlight_dawn's HTML."""
    cls = []
    pos = 0
    for m in SPAN.finditer(markup):
        cls += ["o"] * len(html.unescape(markup[pos:m.start()]))
        c = m.group(1)
        cls += [c if c in ("c", "s", "i", "k") else "o"] * len(html.unescape(m.group(2)))
        pos = m.end()
    cls += ["o"] * len(html.unescape(markup[pos:]))
    return cls


def runs(text):
    cls = []
    for c, n in re.findall(r"([a-z-])(\d+)", text):
        cls += [c] * int(n)
    return cls


def judge_regions(src, rd, cls):
    """First disagreement (position, lexer's region, highlighter's) and count."""
    if len(cls) != len(src):
        return (0, "length", f"{len(cls)} classes for {len(src)} code points"), 1
    first, n = None, 0
    for p, want in enumerate(rd.region):
        if want == "x" or cls[p] == "-":
            continue
        got = cls[p] if cls[p] in ("c", "s", "i") else "o"
        if got != want:
            n += 1
            if first is None:
                first = (p, want, got)
    return first, n


def judge_keywords(rd, cls):
    missed = {}
    for lo, hi, w in rd.keywords:
        if any(cls[p] not in ("k", "-") for p in range(lo, hi)):
            missed.setdefault(w, lo)
    return missed


NAMES = {"c": "comment", "s": "string", "i": "interpolation delimiter", "o": "code"}


def line_col(src, p):
    ln = src.count("\n", 0, p)
    return ln + 1, p - (src.rfind("\n", 0, p) + 1) + 1


# ---------------------------------------------------------------- driver


def tracked():
    p = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--", "*.dawn"],
                       capture_output=True, text=True, check=True)
    return sorted(f for f in p.stdout.split("\0") if f)


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read_known(text):
    keys = {}
    for n, line in enumerate(io.StringIO(text), 1):
        line = line.split("#", 1)[0].strip()
        if line:
            parts = line.split()
            if len(parts) != 4:
                raise SystemExit(f"KNOWN_KEYS line {n}: want `<property> <rule> <subject> <where>`")
            keys[tuple(parts)] = n
    return set(keys)


def lex_with_segments(dawn, paths, work, jobs):
    """`__lex` of every path, then of every interpolation's code on its own,
    level by level, so a nested interpolation is lexed as the parser lexes it.
    Returns (lexed files, code -> tokens or None)."""
    files = lex_files(dawn, paths, jobs)
    seg = {}
    todo = sorted({code for toks, _ in files.values() for t in toks for _, code in t.segs})
    level = 0
    while todo:
        level += 1
        names = []
        for k, code in enumerate(todo):
            p = os.path.join(work, "seg", str(level), f"{k}.dawn")
            write(p, code)
            names.append(p)
        lexed = lex_files(dawn, names, jobs)
        nxt = set()
        for code, p in zip(todo, names):
            toks, diags = lexed[p]
            seg[code] = None if diags else toks
            for t in toks:
                for _, c in t.segs:
                    if c not in seg:
                        nxt.add(c)
        todo = sorted(nxt - set(todo))
    return files, seg


def site_run(dawn, paths):
    p = subprocess.run([dawn, "run", os.path.join(HERE, "sitehl"), "--"] + paths,
                       cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"the site highlighter failed (exit {p.returncode}):\n{p.stderr[-2000:]}")
    out = {}
    for line in p.stdout.split("\n"):
        if "\t" in line:
            path, _, markup = line.partition("\t")
            out[path] = site_classes(unesc(markup))
    return out


def editor_bundle(work):
    esbuild = os.path.join(PLAY_UI, "node_modules", ".bin", "esbuild")
    if not os.path.exists(esbuild):
        sys.exit("site/play-ui/node_modules is missing: run `npm ci --prefix site/play-ui` first")
    out = os.path.join(work, "lex-classes.mjs")
    subprocess.run([esbuild, "test/lex-classes.ts", "--bundle", "--platform=node", "--format=esm",
                    "--external:./builtins.generated", f"--outfile={out}", "--log-level=error"],
                   cwd=PLAY_UI, check=True)
    return out


def editor_run(bundle, paths, jobs):
    out = {}
    for so in run_chunks(["node", bundle], paths, jobs, chunk=200):
        for line in so.split("\n"):
            if line.count("\t") == 2:
                path, rs, ctx = line.split("\t")
                samples = []
                for x in ctx.split(",") if ctx else []:
                    pos, _, c = x.partition(":")
                    samples.append((int(pos), c))
                out[path] = (runs(rs), samples)
    return out


def judge(f, src, rd, site, editor, findings):
    def add(prop, rule, subject, p, detail, where=f):
        ln, col = line_col(src, p)
        findings.append((prop, rule, subject, where, f, ln, col, detail))

    for subject, cls in (("site", site), ("editor", editor[0] if editor else None)):
        if cls is None:
            continue
        first, n = judge_regions(src, rd, cls)
        if first:
            p, want, got = first
            if want == "length":
                add("b", "region", subject, 0, got)
            else:
                add("b", "region", subject, p,
                    f"{NAMES[want]} by the lexer, {NAMES[got]} here ({n} code points disagree; "
                    f"source {src[max(0, p - 12):p + 12]!r})")
        if len(cls) == len(src):
            for w, p in sorted(judge_keywords(rd, cls).items()):
                add("b", "keyword", subject, p, f"`{w}` is a keyword of the lexer, not coloured as one", w)
    if editor:
        for pos, got in editor[1]:
            want = rd.ctx[pos] if pos < len(rd.ctx) else "code"
            ok = want == "*" or got == want or (want == "icode" and got in ("code", "interp"))
            if not ok:
                add("b", "context", "lexContext", pos,
                    f"cursor here is {'interpolation code' if want == 'icode' else want} by the lexer, "
                    f"lexContext says {got} (source {src[max(0, pos - 12):pos + 12]!r})")
                break


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dawn", default=os.path.join(ROOT, "bin", "dawn"))
    ap.add_argument("--only", help="a regex the input paths must match")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-site", action="store_true", help="skip the site highlighter")
    ap.add_argument("--no-editor", action="store_true", help="skip the Playground editor")
    ap.add_argument("--out", help="keep the work tree here (default: a temporary one)")
    ap.add_argument("--show", type=int, default=12,
                    help="findings printed per (property, rule, subject)")
    ap.add_argument("--all", action="store_true", help="print pinned findings too")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test(a.dawn)

    work = a.out or tempfile.mkdtemp(prefix="lex-properties-")
    if a.out:
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
    inputs = tracked()
    if a.only:
        inputs = [f for f in inputs if re.search(a.only, f)]
    paths = [os.path.join(ROOT, f) for f in inputs]

    files, seg = lex_with_segments(a.dawn, paths, work, a.jobs)
    findings, clean, judged = [], [], {}
    for f, p in zip(inputs, paths):
        toks, diags = files[p]
        if diags:
            continue
        clean.append(f)
        src = read(p)
        rd, out = read_dawn(src, toks, lambda code: seg.get(code))
        for rule, pos, detail in out:
            ln, col = line_col(src, pos)
            findings.append(("a", rule, "lexer", f, f, ln, col, detail))
        if not out:
            judged[f] = (src, rd)

    names = [os.path.join(ROOT, f) for f in judged]
    site = {} if a.no_site else site_run(a.dawn, names)
    editor = {} if a.no_editor else editor_run(editor_bundle(work), names, a.jobs)
    samples = 0
    for f, (src, rd) in judged.items():
        p = os.path.join(ROOT, f)
        ed = editor.get(p)
        samples += len(ed[1]) if ed else 0
        judge(f, src, rd, None if a.no_site else site.get(p, []), ed, findings)

    known = read_known(KNOWN_KEYS)
    keys = {}
    shown = {}
    for prop, rule, subject, where, f, ln, col, detail in sorted(findings):
        k = (prop, rule, subject, where)
        keys[k] = keys.get(k, 0) + 1
        if k in known and not a.all:
            continue
        g = (prop, rule, subject)
        shown[g] = shown.get(g, 0) + 1
        if shown[g] <= a.show:
            print(f"{prop} {rule} {subject} {f}:{ln}:{col}: {detail}")
    for g, n in sorted(shown.items()):
        if n > a.show:
            print(f"{' '.join(g)}: {n - a.show} more")
    full = not (a.only or a.no_site or a.no_editor)
    new = sorted(set(keys) - known)
    stale = sorted(known - set(keys)) if full else []
    print(f"inputs: {len(inputs)} files, {len(clean)} lex clean, {len(judged)} judged by (b); "
          f"{len(seg)} interpolations lexed on their own; {samples} lexContext samples")
    print(f"findings: {len(findings)} in {len(keys)} keys; {len(known)} pinned, "
          f"{len(new)} new, {len(stale)} stale")
    for k in new:
        print(f"new: {' '.join(k)}")
    for k in stale:
        print(f"stale pin: {' '.join(k)} (the run no longer finds it: take it out of KNOWN_KEYS)")
    if a.out:
        print(f"work tree kept in {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    if new or stale:
        # coarse, so the nightly issue is one per kind of finding, not per file
        sigs = sorted({":".join(k[:3]) for k in new})
        print("verdict: " + ",".join(sigs + (["stale-pins"] if stale else [])))
        return 1
    print("verdict: green")
    return 0


# ---------------------------------------------------------------- self-test


def self_test(dawn):
    """The judges on inputs built by hand: a reading must flag what it must."""
    bad = 0

    def expect(name, ok):
        nonlocal bad
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        bad += 0 if ok else 1

    src = 'fn f() = "a ${g("}")} b" # c\n'
    tmp = tempfile.mkdtemp(prefix="lex-properties-self-")
    p = os.path.join(tmp, "a.dawn")
    write(p, src)
    files, seg = lex_with_segments(dawn, [p], tmp, 1)
    toks, diags = files[p]
    rd, out = read_dawn(src, toks, lambda code: seg.get(code))
    expect("a clean file reads clean", not diags and not out)
    want = "".join(rd.region)
    q = src.index('"a')
    expect("regions: string, delimiters, code, nested string, comment",
           want[q:q + 3] == "sss" and want[q + 3:q + 5] == "ii" and want[q + 5:q + 7] == "oo"
           and want[src.index('"}"'):src.index('"}"') + 3] == "sss" and want[src.index("#"):-1] == "c" * 3)
    expect("the keyword is seen", [w for _, _, w in rd.keywords] == ["fn"])
    expect("cursor contexts", rd.ctx[q + 1] == "string" and rd.ctx[q + 5] == "icode"
           and rd.ctx[len(src) - 1] == "comment" and rd.ctx[1] == "code")

    # a dump whose interpolation offset is one off is refused
    shifted = [Tok(t.kind, t.lo, t.hi, t.text, [(o + 1, c) for o, c in t.segs]) for t in toks]
    _, out = read_dawn(src, shifted, lambda code: seg.get(code))
    expect("(a) an interpolation offset one off is lex-seg", [r for r, _, _ in out] == ["lex-seg"])
    widened = [Tok(t.kind, t.lo, t.hi + (1 if t.kind == "RPAREN" else 0), t.text, t.segs) for t in toks]
    _, out = read_dawn(src, widened, lambda code: seg.get(code))
    expect("(a) a token wider than its text is lex-text", [r for r, _, _ in out] == ["lex-text"])
    dropped = [t for t in toks if t.kind != "EQ"]
    _, out = read_dawn(src, dropped, lambda code: seg.get(code))
    expect("(a) a lost token is lex-gap", [r for r, _, _ in out] == ["lex-gap"])

    # (b): a highlighter that ends the string at the nested quote (#83's shape)
    good = ["o" if c in "ok" else c for c in want]
    expect("(b) the lexer's own regions agree", judge_regions(src, rd, good)[0] is None)
    lost = list(good)
    for k in range(src.index('"}"') + 1, src.index("b\"") + 1):
        lost[k] = "s"
    first, n = judge_regions(src, rd, lost)
    expect("(b) a string read through the interpolation is a region finding", first is not None and n > 0)
    expect("(b) an uncoloured keyword is a keyword finding", judge_keywords(rd, good) == {"fn": 0})
    kw = list(good)
    kw[0] = kw[1] = "k"
    expect("(b) a coloured keyword passes", judge_keywords(rd, kw) == {})
    expect("(site) markup reads back to classes",
           site_classes('<span class="k">fn</span> a &lt; <span class="s">"x"</span>')
           == ["k", "k", "o", "o", "o", "o", "o", "s", "s", "s"])
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

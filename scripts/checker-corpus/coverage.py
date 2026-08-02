#!/usr/bin/env python3
"""Which `cerr` call sites does the corpus actually reach?

The goldens next door pin the diagnostics some program produces. They cannot
say anything about a diagnostic no case produces -- and a message nothing
reaches is exactly the one a refactor can reword, misplace or delete unseen.
This walks the other way: from every `cerr` / `cerr_h` / `cerr_o` call site in
the checker's modules (SOURCES below) to the recorded goldens, and reports the
ones with no case.

## How a site is matched

By message text, not by execution. Each site's message expression is expanded
one level through local `let`/`var` bindings and through same-file helper
functions, and every string-literal chunk in it (interpolations cut out)
becomes a candidate; the site counts as reached when a recorded diagnostic
contains one of them.

Two consequences, both deliberate:

  * Sites that emit the *same* sentence -- `duplicate type parameter names` is
    written at three declaration sites -- are one group here. The corpus has a
    case for each anyway; this script just cannot tell them apart.
  * Reaching a site by a *different* branch than a case intended still counts.
    The goldens, not this script, are what pin the wording.

## The ratchet

`uncovered.txt` lists the sites no case reaches, with the reason. It fails in
both directions: a newly unreached site fails the build, and so does a site
that became reachable without being struck off. Sites are keyed by their
message signature rather than by line, so moving code between files -- which is
the refactor this corpus exists for -- does not churn the list, as long as the
destination file is in SOURCES.
"""
import glob
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
# The checker's own modules, in the order docs/arch-split-design.md §2.1 puts
# them: `cerr` and the resolvers it reports from now live in the base module,
# and a site that leaves this glob leaves the ratchet with it.
SOURCES = ("selfhost/src/cx.dawn", "selfhost/src/checker*.dawn")
CASES = "scripts/checker-corpus/cases"
UNCOVERED = "scripts/checker-corpus/uncovered.txt"

CALL = re.compile(r"\bcerr(_h|_o)?\(")
STR = re.compile(r'"((?:[^"\\]|\\.)*)"')
LET = re.compile(
    r"^\s*(?:let|var)\s+(\(?[A-Za-z_][A-Za-z0-9_, ]*\)?)\s*(?::[^=]*)?=", re.M
)
FN = re.compile(r"^(?:pub )?fn ([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
IDENT = re.compile(r"\b([a-z_][A-Za-z0-9_]*)\b")

MIN_CHUNK = 8  # shorter chunks match by accident ("` is ", " and ")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def scan_args(s, i):
    """`i` points just past `(`. Returns the top-level argument expressions."""
    depth, args, cur = 0, [], []
    while i < len(s):
        c = s[i]
        if c == '"':
            j = i + 1
            cur.append(c)
            while j < len(s):
                if s[j] == "\\":
                    cur.append(s[j : j + 2])
                    j += 2
                    continue
                cur.append(s[j])
                if s[j] == '"':
                    j += 1
                    break
                j += 1
            i = j
            continue
        if c == "#":
            i = s.find("\n", i)
            if i < 0:
                break
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if c == ")" and depth == 0:
                args.append("".join(cur))
                return args
            depth -= 1
        elif c == "," and depth == 0:
            args.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    raise ValueError("unterminated call at offset %d" % i)


def block_after(text, pos):
    """The expression starting at `pos`, to the end of its brace/paren nesting
    or to a line that starts a new top-level-ish statement. Good enough to pick
    up the literals of an `if`/`match` right-hand side."""
    depth, i, n = 0, pos, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return text[pos:i]
            depth -= 1
        elif c == "\n" and depth == 0:
            nxt = text[i + 1 : i + 400]
            if re.match(r"\s*(let |var |return |cx|pub fn |fn |\}|#)", nxt):
                return text[pos:i]
        i += 1
    return text[pos:n]


def literals(expr):
    """Literal chunks of a message expression, interpolations cut out."""
    out = []
    for m in STR.finditer(expr):
        body = m.group(1)
        body = (
            body.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )
        for piece in re.split(r"\$\{[^}]*\}", body):
            if piece:
                out.append(piece)
    return out


# A message expression is often an `if`/`match` over several wordings. Splitting
# on the branch boundaries gives one candidate per wording; the flattened whole
# is kept as a candidate too, for the messages that interpolate a branch into
# the middle of one sentence.
BRANCH = re.compile(r"\}\s*else\s*\{|->|\bif\b|\bmatch\b|[{}]")


def patterns(lits, expr):
    """Regexes a recorded diagnostic may match for this site. Chunks in order,
    joined by `.*` -- so a site is reached only by a message that has its
    literal pieces in its literal order, not merely one piece of it."""
    cands = []

    def add(chunks):
        # One long chunk is discriminating on its own; so is a run of short
        # ones in a fixed order ("field `" ... "` of `" ... "` is " ... ", got ").
        if not chunks:
            return
        if max(len(c) for c in chunks) < MIN_CHUNK and len(chunks) < 3:
            return
        cands.append(".*".join(re.escape(c) for c in chunks))

    add(lits)
    # Prefixes too: a message built with `join(...)` or an inner lambda drags
    # that helper's own literals in after the sentence, and only the sentence
    # is in the diagnostic.
    for k in range(1, len(lits)):
        add(lits[:k])
    for seg in BRANCH.split(expr):
        add(literals(seg))
    return cands


def collect_sites():
    sites = []
    paths = []
    for pat in SOURCES:
        paths += glob.glob(os.path.join(ROOT, pat))
    for path in sorted(paths):
        text = read(path)
        rel = os.path.relpath(path, ROOT)
        # local `let x = ...` / `var x = ...` and same-file `fn f(...) = ...`
        # bodies, so an indirect message expression can be expanded once.
        fns = {}
        for m in FN.finditer(text):
            eq = text.find("=", m.end())
            if eq > 0:
                fns[m.group(1)] = block_after(text, eq + 1)
        lets = []  # (offset, name, body), in file order
        for m in LET.finditer(text):
            body = block_after(text, m.end())
            # `let (msg, hint) = helper(...)` binds both from one expression
            for nm in m.group(1).strip("()").split(","):
                lets.append((m.start(), nm.strip(), body))
        fn_starts = [m.start() for m in FN.finditer(text)]
        for m in CALL.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            try:
                args = scan_args(text, m.end())
            except ValueError:
                continue
            if len(args) < 2:
                continue
            expr = args[1]
            # `cerr` inside `cerr`, `cerr_h` or `cerr_o` is the definition or
            # the forward `cerr_o` makes, not a report.
            head = text.rfind("\n", 0, m.start()) + 1
            owner = ""
            for fm in FN.finditer(text, 0, head):
                owner = fm.group(1)
            if re.match(r"(pub )?fn cerr", text[head:]):
                owner = "cerr"
            if owner in ("cerr", "cerr_h", "cerr_o"):
                continue
            full = expr
            lits = literals(expr)
            if not patterns(lits, expr):
                # An indirect message: either `helper(...)` or a local `msg`.
                # Expanding any identifier anywhere would drag in every `let cx
                # = ...` in the file, so resolve a call by its callee's body and
                # a bare name by the nearest binding inside the same function.
                call = re.match(r"\s*([a-z_][A-Za-z0-9_]*)\s*\(", expr)
                bodies = []
                if call and call.group(1) in fns:
                    bodies.append(fns[call.group(1)])
                else:
                    scope = 0
                    for st in fn_starts:
                        if st < m.start():
                            scope = st
                    for name in set(IDENT.findall(expr)):
                        best = None
                        for off, nm, body in lets:
                            if nm == name and scope <= off < m.start():
                                best = body
                        if best is not None:
                            bodies.append(best)
                # Two rounds: `let (msg, hint) = helper(...)` needs the
                # binding resolved first and the helper's body after it.
                for _round in range(2):
                    for body in bodies:
                        full += " " + body
                        lits += literals(body)
                    if lits:
                        break
                    nxt = []
                    for body in bodies:
                        c2 = re.match(r"\s*([a-z_][A-Za-z0-9_]*)\s*\(", body)
                        if c2 and c2.group(1) in fns:
                            nxt.append(fns[c2.group(1)])
                    bodies = nxt
            sites.append(
                {
                    "file": rel,
                    "line": line,
                    "expr": " ".join(expr.split()),
                    "pats": patterns(lits, full),
                }
            )
    return sites


def key_of(site, seen):
    sig = site["expr"]
    n = seen.get(sig, 0)
    seen[sig] = n + 1
    return sig if n == 0 else "%s  ##%d" % (sig, n + 1)


def recorded_messages():
    msgs = []
    for path in glob.glob(os.path.join(ROOT, CASES, "*.expected")):
        for line in read(path).split("\n"):
            cols = line.split("\t")
            if len(cols) >= 5 and cols[0] == "D":
                msgs.append(cols[4] + "\t" + (cols[5] if len(cols) > 5 else ""))
    return msgs


def main():
    record = "--record" in sys.argv
    sites = collect_sites()
    msgs = recorded_messages()

    seen = {}
    uncovered = []
    n_cov = 0
    for s in sites:
        k = key_of(s, seen)
        hit = any(re.search(p, m) for p in s["pats"] for m in msgs)
        if hit:
            n_cov += 1
        else:
            uncovered.append((k, s))

    path = os.path.join(ROOT, UNCOVERED)
    if record:
        old = {}
        if os.path.exists(path):
            for line in read(path).split("\n"):
                if line.startswith("  "):
                    body = line[2:]
                    if "\t" in body:
                        k, why = body.split("\t", 1)
                        old[k] = why
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER % (len(sites), n_cov, len(uncovered)))
            for k, s in uncovered:
                f.write("  %s\t%s\n" % (k, old.get(k, "TODO: reason")))
        print(
            "recorded coverage: %d/%d cerr sites reached, %d listed as unreached"
            % (n_cov, len(sites), len(uncovered))
        )
        return 0

    if not os.path.exists(path):
        print("FAIL: no %s; run --record" % UNCOVERED, file=sys.stderr)
        return 1
    listed = []
    for line in read(path).split("\n"):
        if line.startswith("  ") and "\t" in line:
            listed.append(line[2:].split("\t", 1)[0])
    now = [k for k, _ in uncovered]
    added = [k for k in now if k not in listed]
    gone = [k for k in listed if k not in now]
    bad = False
    if added:
        print("FAIL: %d cerr site(s) no case reaches, and not listed in %s:" % (len(added), UNCOVERED), file=sys.stderr)
        for k in added[:20]:
            print("  + %s" % k, file=sys.stderr)
        bad = True
    if gone:
        print("FAIL: %d site(s) in %s are now reached -- strike them off:" % (len(gone), UNCOVERED), file=sys.stderr)
        for k in gone[:20]:
            print("  - %s" % k, file=sys.stderr)
        bad = True
    if bad:
        return 1
    print("     cerr coverage: %d/%d sites reached (%d listed as unreached)" % (n_cov, len(sites), len(uncovered)))
    return 0


HEADER = """# `cerr` call sites in the checker's modules that no corpus case reaches.
# Regenerate with `./scripts/checker-corpus/run.sh --record`; the reason column
# is kept across regenerations, so write it once.
#
# A ratchet in both directions (see coverage.py): a new unreached site fails
# the build, and so does a listed site that became reachable.
#
# %d sites, %d reached, %d here.
#
#   <message expression>\t<why no case reaches it>
"""

if __name__ == "__main__":
    sys.exit(main())

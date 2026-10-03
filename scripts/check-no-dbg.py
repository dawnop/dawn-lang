#!/usr/bin/env python3
"""Guard: no `dbg` call is checked in under this tree's own sources.

    python3 scripts/check-no-dbg.py             # the tree
    python3 scripts/check-no-dbg.py --selftest  # the scanner on fixtures

`dbg` (docs/source-location-design.md section 6) is pure by type and writes to
stderr, which the language allows only because the line is declared to be a
debugging side channel of the program being debugged. So the compiler refuses
it in std and in any module loaded through `[deps]`: a package somebody depends
on must not make that promise on their behalf. The five source roots here are
the same kind of thing -- the compiler, std, the packages, the site and the
playground are what every user of the language runs or depends on -- but the
compiler does not see them as dependencies (selfhost and site build as
projects of their own), so the rule is held here instead, before main.

Why a scanner and not `git grep -w dbg`: the word is legitimately in these
trees as text. The compiler names the builtin in strings (`name == "dbg"`),
its messages show how to call it, comments explain it, and packages/tileir
uses the string "dbg" for something else entirely. Only an identifier in code
position is a call, so this reads the source the way the lexer does: `#`
comments, `"..."` and `\"\"\"...\"\"\"` strings with `${...}` code inside them,
backtick raw strings and character literals. An interpolation is code, so
`"${dbg(x)}"` is caught.

selfhost/builtins.dawn is exempt by name: it is the builtin table written out
as declarations (a gated document, never compiled), and `pub fn dbg` is a line
of it.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTS = ("selfhost", "std", "packages", "site", "playground")
EXEMPT = {
    "selfhost/builtins.dawn": "the builtin mirror declares `dbg`; it is a document, not a module",
}


def is_ident_start(c):
    return c.isalpha() or c == "_"


def is_ident(c):
    return c.isalnum() or c == "_"


class Scan:
    """One file's code identifiers, with their 1-based line and column."""

    def __init__(self, text):
        self.s = text
        self.n = len(text)
        self.found = []

    def pos(self, i):
        line = self.s.count("\n", 0, i) + 1
        col = i - (self.s.rfind("\n", 0, i) + 1) + 1
        return line, col

    def code(self, i, in_interp):
        """Code from i; in an interpolation, up to and past its closing `}`."""
        depth = 0
        while i < self.n:
            c = self.s[i]
            if c == "#" and not in_interp:
                # interpolation is single-line and the lexer keeps `#` an
                # ordinary character inside it; elsewhere it runs to the line end
                while i < self.n and self.s[i] != "\n":
                    i += 1
            elif self.s.startswith('"""', i):
                i = self.string(i + 3, '"""')
            elif c == '"':
                i = self.string(i + 1, '"')
            elif c == "`":
                j = self.s.find("`", i + 1)
                i = self.n if j < 0 else j + 1
            elif c == "'":
                i = self.char(i)
            elif is_ident_start(c):
                j = i
                while j < self.n and is_ident(self.s[j]):
                    j += 1
                if self.s[i:j] == "dbg":
                    self.found.append(self.pos(i))
                i = j
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if in_interp and depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        return i

    def string(self, i, close):
        while i < self.n:
            if self.s.startswith(close, i):
                return i + len(close)
            c = self.s[i]
            if c == "\\":
                i += 2
            elif self.s.startswith("${", i):
                i = self.code(i + 2, True)
            elif c == "\n" and close == '"':
                # unterminated: the lexer stops at the line end, and so does this
                return i
            else:
                i += 1
        return i

    def char(self, i):
        # 'x', '\n', '\u{1F388}', '\''; a quote that opens none of these is
        # read as one character, which only a file that does not lex has
        j = i + 1
        if j < self.n and self.s[j] == "\\":
            j += 2
            while j < self.n and self.s[j] not in "'\n":
                j += 1
        else:
            j += 1
        if j < self.n and self.s[j] == "'":
            return j + 1
        return i + 1


def dbg_sites(text):
    sc = Scan(text)
    sc.code(0, False)
    return sc.found


def tracked_sources():
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--"] + [f"{r}/*.dawn" for r in ROOTS] +
        [f"{r}/**/*.dawn" for r in ROOTS],
        check=True, capture_output=True,
    ).stdout.decode()
    return sorted({p for p in out.split("\0") if p})


def check_tree():
    files = tracked_sources()
    if not files:
        print("FAIL  no .dawn sources found under " + ", ".join(ROOTS), file=sys.stderr)
        return 1
    bad = []
    for rel in files:
        if rel in EXEMPT:
            continue
        for line, col in dbg_sites((ROOT / rel).read_text(encoding="utf-8")):
            bad.append(f"{rel}:{line}:{col}")
    for rel in EXEMPT:
        if rel not in files:
            print(f"FAIL  {rel} is exempt but is not a tracked source; drop the exemption",
                  file=sys.stderr)
            return 1
    if bad:
        for b in bad:
            print(f"{b}: `dbg` is for debugging locally and is not checked in here", file=sys.stderr)
        print(f"FAIL  {len(bad)} `dbg` call(s) under {', '.join(ROOTS)}", file=sys.stderr)
        return 1
    print(f"PASS  no `dbg` in the {len(files)} .dawn sources under {', '.join(ROOTS)}")
    return 0


# (source, the sites expected). The controls are the ones a text search gets
# wrong in each direction.
FIXTURES = [
    ("fn f(n: Int) -> Int = dbg(n)\n", [(1, 23)]),
    ("let x = xs\n  |> dbg\n", [(2, 6)]),
    ('let s = "${dbg(x)} and ${ {a: 1}.a }"\n', [(1, 12)]),
    ('let s = """\n  ${dbg(x)}\n"""\n', [(2, 5)]),
    ("let f = dbg\n", [(1, 9)]),
    ('if name == "dbg" { 1 } else { 2 }\n', []),
    ("# call dbg(x) to see x\nfn f() = 1\n", []),
    ("let r = `dbg(x)`\n", []),
    ("let c = '\"'\nlet d = dbg(c)\n", [(2, 9)]),
    ("let c = '\\''\nlet e = '}'\n", []),
    ('let s = "a \\" dbg(x)"\n', []),
    ("fn dbgx(n: Int) -> Int = my_dbg(n)\n", []),
    ('let s = "${ "dbg" }"\n', []),
]


def selftest():
    failed = 0
    for src, want in FIXTURES:
        got = dbg_sites(src)
        if got != want:
            print(f"FAIL  {src!r}: wanted {want}, scanned {got}", file=sys.stderr)
            failed += 1
    # the exemption is by exact path, and the exempt file really does declare it
    mirror = (ROOT / "selfhost/builtins.dawn").read_text(encoding="utf-8")
    if not dbg_sites(mirror):
        print("FAIL  selfhost/builtins.dawn no longer declares `dbg`; drop its exemption",
              file=sys.stderr)
        failed += 1
    if failed:
        return 1
    print(f"PASS  the scanner reads {len(FIXTURES)} fixtures as the lexer would")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    if sys.argv[1:]:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(check_tree())

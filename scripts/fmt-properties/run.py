#!/usr/bin/env python3
"""Structural properties of `dawn fmt`, checked against the parser.

    scripts/fmt-properties/run.py                     # every tracked .dawn file
    scripts/fmt-properties/run.py --gen <gen.py>      # plus generated programs
    scripts/fmt-properties/run.py --dawn <launcher>   # another toolchain (a mutant)
    scripts/fmt-properties/run.py --self-test         # the checks on tiny inputs

Why this exists. `dawn fmt --check` over the tree, the fmt differential and the
inline tests all ask one question: is the output a fixed point. Two shipped
defects were fixed points. #187 printed the empty row `-> Int !()` as
`Int!()`, which reads as the postfix unwrap and a call; #188 printed the line
after a trailing `|` or `:` at statement indentation, as if it began a new
statement, while the parser joined it to the line above. In both the formatter
decided from tokens something the parser decides from the grammar, the two
answers differed, and nothing compared them. So these checks compare them, on
inputs the formatter has not already settled:

  (a)  idempotent: fmt(fmt(x)) == fmt(x).
  (a2) blind to indentation: re-indenting x at random leaves fmt(x) unchanged.
       The formatter claims to own the indentation; an input whose old
       indentation leaks into the output was not reformatted, only kept.
  (b)  fmt keeps the tree: `dawn __parse` of fmt(x) equals that of x with the
       spans taken out.
  (c)  fmt's statement boundaries are the parser's. Every line that starts an
       item (a declaration, a block statement, a match or handler arm, a
       trait or impl member) sits one level inside the construct that owns
       it: column 0 at the top, else one level in from the line its owner
       starts on. A body brace or `match` left on a wrapped header line
       (`if a &&` / `b {`) belongs to the construct, not to the wrapped line.
       Every other line sits deeper than the line its nearest base starts
       on, a base being an item, an element of a bracketed list (a call's
       argument, a list or record entry) or a construct with a header (`if`,
       `match`, `while`, `for`). So a line the parser continues never sits
       where a statement, an element or a body would. Two layouts are taken
       as fmt's style rather than judged: the lines of one wrapped operator
       chain share a column (no base is a binary node), and a `derive`
       clause sits at its type's column. Closers, a leading `else` and an
       or-pattern's leading `|` are exempt, each where it is skipped below.
  (d)  fmt's token roles are the parser's: a `!` is spaced as the postfix
       unwrap exactly where the parser built an unwrap, and a `-` as an infix
       operator exactly where it built a binary node.

  (e)  chains fold: no output line is wider than 100 columns while it holds a
       chain link at its own bracket depth (a `.f(` straight after `)`, `]`
       or a postfix `?` / `!`), unless it is a line the formatter leaves to
       its author (brackets open across the line, begins with a closer, a
       comment or `use`, holds a multi-line string). A trailing comment is not
       counted. The tracked files hold almost no such line, so a synthetic
       chain corpus (`chain_inputs`: widths straddling 100, each link kind,
       a non-ASCII string, a trailing comment, a chain nested in an argument)
       is judged by (a)-(e) as well; a folding that is not a fixed point, or
       that stops folding, shows there. The report on this cut has the
       mutants.

Inputs. Every tracked .dawn file that lexes (a) and parses cleanly (b-d), in
three variants: as written; re-indented at random; and re-broken, a newline
inserted after a random part of the tokens the lexer joins to the next line.
The re-broken variant is what reaches #188 from ordinary code: `let a: Int`
becomes `let a:` then `Int`. Which breaks are harmless is asked of the lexer,
not of a list here (a list here would be a third copy of the rule #188 was
about): every eligible break is inserted at once, the result is lexed, and a
break the lexer kept as a NEWLINE token is dropped. A variant whose parse
still differs from the original's is set aside and counted, not judged.
`--gen` adds programs from the fuzz3 generator (scripts/fuzz3/gen.py), which
writes unindented code nobody formatted.

Determinism. Variant choices draw from random.Random("<seed>:<path>"), so a
finding is reproduced from the seed and the file; generated programs come
from fixed generator seeds. Nothing reads the clock.

Why a script outside the compiler. The oracle must not be the formatter's own
code: an inline test in front/fmt.dawn would share its token classifiers. The
checks read only what the CLI prints (`__lex`, `__parse`, `fmt`), so they are
the same for any toolchain passed with --dawn, which is how a restored defect
is shown red (the report on this cut, prop-k1, has the mutants).

Why nightly. The push total has no room (ruling on bug-rate, 2026-10-04), and
the checks find layout defects in old code rather than guard a change.

Output: one line per finding, `<property> <rule> <file>: <detail>`, a
summary, and with --out the variants and formatted files for a look. Exit 1
when anything is found. The verdict line, `verdict: <keys>`, is the sorted set
of `<property>:<rule>:<variant>`, so a nightly issue is commented on when a
kind of finding appears or goes, not every night the same files are listed.
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
SPAN = re.compile(r"@(\d+)\.\.(\d+)$")
ANY_SPAN = re.compile(r"@\d+\.\.\d+")
CLOSERS = {"RPAREN", "RBRACKET", "RBRACE"}
# contextual words that stand before a declaration, outside its span
MODIFIERS = {"ctl", "opaque"}

# Containers whose children are items, and which children those are. A Block
# owns every child (statements and the tail); the others own only the kinds
# named. A kind absent here is no container: its lines take rule (c)'s
# continuation half only.
ITEM_KINDS = {
    "Module": None,
    "Block": None,
    "Match": {"Arm"},
    "Handle": {"Arm", "Cell"},
    "Impl": {"Fn", "AssocBind", "EffBind"},
    "Trait": {"TraitMethod", "Assoc", "EffAssoc", "Fn"},
    "Effect": {"Op"},
}


# ---------------------------------------------------------------- toolchain


def run_dawn(dawn, args, files, jobs, chunk=300):
    """`dawn <args> <files...>` in chunks, outputs joined in file order."""
    groups = [files[i:i + chunk] for i in range(0, len(files), chunk)]

    def one(g):
        p = subprocess.run([dawn] + args + g, cwd=ROOT, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(one, groups))
    return results


def dump_by_file(results):
    """Split `== path ==` sections of __lex/__parse output."""
    out = {}
    for rc, so, se in results:
        if rc != 0:
            sys.exit(f"dawn failed (exit {rc}):\n{se[-2000:]}")
        cur = None
        buf = []
        for line in so.split("\n"):
            if line.startswith("== ") and line.endswith(" =="):
                if cur is not None:
                    out[cur] = buf
                cur, buf = line[3:-3], []
            elif cur is not None:
                buf.append(line)
        if cur is not None:
            out[cur] = buf
    return out


def fmt_tree(dawn, root, jobs):
    """Format every .dawn under `root` in place; files that do not lex stay."""
    files = []
    for d, _, fs in os.walk(root):
        files += [os.path.join(d, f) for f in fs if f.endswith(".dawn")]
    files.sort()
    for rc, so, se in run_dawn(dawn, ["fmt"], files, jobs):
        # 1 with a refusal list is a file that does not lex; anything else is
        # the formatter itself failing
        if rc not in (0, 1) or (rc == 1 and "do not lex" not in se):
            sys.exit(f"dawn fmt failed (exit {rc}):\n{se[-2000:]}")


# ---------------------------------------------------------------- dumps


class Tok:
    __slots__ = ("kind", "lo", "hi")

    def __init__(self, kind, lo, hi):
        self.kind, self.lo, self.hi = kind, lo, hi


def parse_lex(lines):
    toks, diags = [], 0
    for ln in lines:
        if not ln:
            continue
        f = ln.split("\t")
        if f[0] == "!":
            diags += 1
        elif len(f) >= 3:
            toks.append(Tok(f[0], int(f[1]), int(f[2])))
    return toks, diags


class Node:
    __slots__ = ("kind", "line", "lo", "hi", "parent", "kids")

    def __init__(self, kind, line, lo, hi, parent):
        self.kind, self.line, self.lo, self.hi, self.parent = kind, line, lo, hi, parent
        self.kids = []


def parse_ast(lines):
    """(root node, span-free dump, diagnostic count) of one `__parse` section."""
    root, stack, shape, diags = None, [], [], 0
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("!") or ln.startswith("\tnote"):
            diags += 1
            continue
        depth = (len(ln) - len(ln.lstrip(" "))) // 2
        body = ln[2 * depth:]
        if body.startswith("SText"):
            # a string's text, verbatim: what looks like a span in it is text
            shape.append(ln)
            lo, hi = None, None
        elif body.startswith("Assert src="):
            # the asserted expression's source text, kept for the failure
            # message: its layout is the formatter's to change, its tokens not
            m = SPAN.search(body)
            lo, hi = (int(m.group(1)), int(m.group(2))) if m else (None, None)
            shape.append("  " * depth + re.sub(r"(\\n|\s)+", "", ANY_SPAN.sub("@", body)))
        else:
            shape.append("  " * depth + ANY_SPAN.sub("@", body))
            m = SPAN.search(body)
            lo, hi = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        while len(stack) > depth:
            stack.pop()
        parent = stack[-1] if stack else None
        n = Node(body.split(" ")[0], body, lo, hi, parent)
        if parent is not None:
            parent.kids.append(n)
        else:
            root = n
        stack.append(n)
    return root, shape, diags


def walk(n):
    yield n
    for k in n.kids:
        yield from walk(k)


# ---------------------------------------------------------------- variants


def line_starts(text):
    starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            starts.append(i + 1)
    return starts


def covered_starts(text, toks):
    """Line starts that fall inside a token (a multi-line string)."""
    inside = set()
    starts = line_starts(text)
    for t in toks:
        if "\n" in text[t.lo:t.hi]:
            for s in starts:
                if t.lo < s < t.hi:
                    inside.add(s)
    return inside


def reindent(text, toks, rng):
    """Every line's leading blanks replaced by a random amount."""
    inside = covered_starts(text, toks)
    out = []
    pos = 0
    for line in text.split("\n"):
        if pos in inside:
            out.append(line)
        else:
            out.append(" " * rng.choice([0, 0, 1, 2, 3, 4, 6, 8, 13]) + line.lstrip(" \t"))
        pos += len(line) + 1
    return "\n".join(out)


def break_points(text, toks):
    """Token ends followed by another token on the same line, as offsets."""
    pts = []
    code = [t for t in toks if t.kind not in ("NEWLINE", "EOF")]
    for a, b in zip(code, code[1:]):
        gap = text[a.hi:b.lo]
        if "\n" not in gap and "#" not in gap:
            pts.append(a.hi)
    return pts


def insert_breaks(text, pts):
    out, last = [], 0
    for p in sorted(pts):
        out.append(text[last:p])
        out.append("\n")
        last = p
    out.append(text[last:])
    return "".join(out)


def shifted(pts):
    """Where each inserted newline lands in the text with all of `pts` inserted."""
    return [p + i for i, p in enumerate(sorted(pts))]


# ---------------------------------------------------------------- checks


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


class Layout:
    """The formatted text with its tokens and tree, indexed by line."""

    def __init__(self, text, toks, root):
        self.text, self.root = text, root
        self.starts = line_starts(text)
        self.lines = text.split("\n")
        self.code = [t for t in toks if t.kind not in ("NEWLINE", "EOF")]
        inside = covered_starts(text, self.code)
        self.first = {}  # line index -> first token starting on it
        for t in self.code:
            ln = self.line_of(t.lo)
            if ln not in self.first and self.starts[ln] not in inside:
                self.first[ln] = t
        self.first_lo = {t.lo for t in self.first.values()}
        self.brace_lo = {t.lo for t in self.code if t.kind == "LBRACE"}
        self.node_lo = {n.lo for n in walk(root) if n.lo is not None}
        # a node's leftmost offset over its subtree: before #538 a `with`
        # statement's call spanned from the callee while its lambda child
        # started at `with`, and --dawn may name a toolchain from then
        self.lo_min = {}
        for n in reversed(list(walk(root))):
            los = [self.lo_min[id(k)] for k in n.kids if self.lo_min.get(id(k)) is not None]
            if n.lo is not None:
                los.append(n.lo)
            self.lo_min[id(n)] = min(los) if los else None
        # a node's span leaves out the parentheses around it and around its
        # left operand (`(a + 1) % 2` starts at `a`), but the line it starts
        # on is the parenthesis's
        index = {t.lo: i for i, t in enumerate(self.code)}
        match, stack = {}, []
        for i, t in enumerate(self.code):
            if t.kind in ("LPAREN", "LBRACKET", "LBRACE"):
                stack.append(i)
            elif t.kind in CLOSERS and stack:
                match[stack.pop()] = i
        self.lo_bare = dict(self.lo_min)  # before the walk out through parentheses
        for n in walk(root):
            lo = self.lo_min.get(id(n))
            if lo is None or lo not in index or n.hi is None:
                continue
            i = index[lo]
            while i > 0 and self.code[i - 1].kind == "LPAREN" and \
                    i - 1 in match and self.closes_node(match[i - 1], n.hi) and \
                    not self.call_paren(i - 1, text):
                i -= 1
            self.lo_min[id(n)] = self.code[i].lo
        self.index = index
        self.modifier_of = {}  # a modifier token's lo -> its declaration's start
        # a declaration's modifiers (`pub`, `pub(pkg)`, `ctl`) stand before
        # its span; the declaration starts at the first of them
        for c in walk(root):
            if c.kind not in ("Module", "Impl", "Trait"):
                continue
            prev_hi = c.lo if c.lo is not None else 0
            for k in c.kids:
                lo = self.lo_min.get(id(k))
                if lo is None or k.hi is None:
                    continue
                if lo in index:
                    i = index[lo]
                    def word(j):
                        return text[self.code[j].lo:self.code[j].hi]
                    while i > 0 and self.code[i - 1].lo >= prev_hi:
                        if self.code[i - 1].kind == "PUB" or word(i - 1) in MODIFIERS:
                            i -= 1
                        elif i >= 4 and [word(j) for j in range(i - 4, i)] == ["pub", "(", "pkg", ")"]:
                            i -= 4
                        else:
                            break
                    for j in range(i, index[lo]):
                        self.modifier_of[self.code[j].lo] = self.code[i].lo
                    self.lo_min[id(k)] = self.code[i].lo
                prev_hi = k.hi
        self.by_line = {}
        for t in self.code:
            self.by_line.setdefault(self.line_of(t.lo), []).append(t)

    def closes_node(self, m, hi):
        """Whether the `)` at code index `m` closes right after a node that ends
        at `hi`. A node's span leaves out the parentheses around its last
        operand too (`(a & (b & c))` ends at `c`), so any closers between the
        end and this one count as part of the node."""
        j = m
        while j > 0 and self.code[j - 1].lo >= hi:
            if self.code[j - 1].kind != "RPAREN":
                return False
            j -= 1
        return True

    def call_paren(self, i, text):
        """Whether the `(` at code index `i` opens a call's arguments, not a
        grouping. A call's parenthesis closes right after its last argument, so
        a sole argument that ends where the `)` begins looks exactly like a
        parenthesised node (`w(` / `() => {` ... `})`), and the node's start
        would be read as the call's line. A `(` straight after a value (a name,
        a type name, a closer) on its own line is a call; `in` and `assert` are the contextual
        words that read as names and precede a grouping."""
        if i == 0:
            return False
        p = self.code[i - 1]
        if self.line_of(p.hi - 1) != self.line_of(self.code[i].lo):
            return False  # a newline before `(` ends the statement: it groups
        if p.kind in ("RPAREN", "RBRACKET", "TYPEIDENT"):
            return True
        return p.kind == "IDENT" and text[p.lo:p.hi] not in ("in", "assert")

    def code_on(self, ln):
        return self.by_line.get(ln, [])

    def line_of(self, off):
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def indent_at(self, off):
        return indent_of(self.lines[self.line_of(off)])


def spanned_parent(n):
    p = n.parent
    while p is not None and p.lo is None:
        p = p.parent
    return p


def path_to(root, off):
    """The spanned nodes with lo < off < hi on the way down to `off`, outer first."""
    path = []
    frontier = [root]
    while frontier:
        nxt = []
        for n in frontier:
            for k in n.kids:
                if k.lo is None:
                    nxt.append(k)
                elif k.lo < off < k.hi:
                    path.append(k)
                    nxt = [k]
                    break
            else:
                continue
            break
        frontier = nxt
    return path


def innermost(root, off):
    path = path_to(root, off)
    return path[-1] if path else None


# Bracketed lists whose elements are bases for a continuation, like items: a
# line inside a call's argument continues that argument, so it sits deeper
# than the argument's own line (`reason:` then its string, #188's colon). The
# callee of a call is no element, and neither is a pipe's left operand, which
# the parser makes the first argument although it stands before the callee.
ELEMENT_OF = {"Apply", "MethodCall", "ListLit", "TupleLit", "Record",
              "PCtor", "PRecord", "PQual", "PQualRecord", "PTuple", "PList"}
CALLEE_FIRST = {"Apply", "MethodCall"}
# Constructs with a header: a line inside `if a ==` / `b {` continues the `if`
# whether or not the `if` is a statement (an arm's body, a lambda's).
HEADED = {"If", "Match", "While", "For"}


def line_lead(lay, k):
    """The first token of `k`'s line when `k` starts that line: `k` itself, or a
    run of modifiers no node contains (`pub`, `pub(pkg)`, `ctl` sit outside the
    declaration's span). None when something else comes first."""
    lo = lay.lo_min[id(k)]
    ln = lay.line_of(lo)
    t = lay.first.get(ln)
    if t is None:
        return None
    if t.lo == lo:
        i = lay.index.get(lo)
        if i and lay.code[i - 1].kind == "PIPE" and lay.line_of(lay.code[i - 1].lo) < ln:
            # an arm's leading bar alone on the line above: the arm began there,
            # and this line continues it (fmt indents the pattern one level)
            return None
        return t
    for u in lay.code_on(ln):
        if u.lo >= lo:
            return t
        if u.lo in lay.node_lo or innermost(lay.root, u.lo) is not None:
            return None
    return None


def item_children(c):
    kinds = ITEM_KINDS[c.kind]
    return [k for k in c.kids if k.lo is not None and (kinds is None or k.kind in kinds)]


def element_children(lay, c):
    kids = [k for k in c.kids if k.lo is not None]
    if c.kind in CALLEE_FIRST and kids:
        callee = lay.lo_min[id(kids[0])]
        kids = [k for k in kids[1:] if lay.lo_min[id(k)] > callee]
    return kids


def body_anchor(lay, c, bases):
    """The offset whose line a body is indented from, for a block's `{` or a
    `match` that is not first on its line. The body follows the construct it belongs to, not
    the line the construct's header was wrapped to (`if a &&` / `b {`), so
    that is the innermost ancestor that starts before the brace. When the
    statement or element holding the brace starts on the brace's own line
    (`({` opening a tail expression), that line is the construct's."""
    anc = None
    hold = None
    p = c
    while p is not None:
        # a header's body follows the header's keyword, not the parenthesis
        # that groups the whole `if` from the line above
        lo = (lay.lo_bare if p.kind in HEADED or p.kind == "Lambda" else lay.lo_min).get(id(p))
        if p is not c and anc is None and lo is not None and lo < c.lo:
            anc = lo
        if hold is None and id(p) in bases:
            hold = lo
        p = p.parent
    cands = [x for x in (anc, hold) if x is not None]
    if not cands:
        return c.lo
    return max(cands, key=lay.line_of)


def check_layout(lay):
    """Rule (c). Yields (rule, line number, detail)."""
    bases = set()  # ids of the nodes a continuation line is measured from
    for c in walk(lay.root):
        if c.kind in ITEM_KINDS:
            bases.update(id(k) for k in item_children(c))
        if c.kind in ELEMENT_OF:
            bases.update(id(k) for k in element_children(lay, c))
        if c.kind in HEADED:
            bases.add(id(c))
    items = {}  # lo of a line's first token -> expected indent of that line
    for c in walk(lay.root):
        if c.kind not in ITEM_KINDS:
            continue
        if c.kind == "Module":
            want = 0
        elif c.kind == "Block" and c.lo not in lay.brace_lo:
            # no brace: the rest of a block after a `with` statement, which the
            # parser wraps in a lambda; its statements stay where the `with` is
            p = spanned_parent(c)
            want = lay.indent_at(p.lo if p is not None else c.lo)
        elif c.kind in ("Block", "Match", "Handle") and c.lo not in lay.first_lo:
            want = lay.indent_at(body_anchor(lay, c, bases)) + 2
        elif c.kind in ("Impl", "Trait", "Effect"):
            # the declaration starts at its first modifier (`pub(` / `pkg)`
            # wrapped), which sits outside the node's span
            want = lay.indent_at(lay.lo_min[id(c)]) + 2
        else:
            want = lay.indent_at(c.lo) + 2
        for k in item_children(c):
            lead = line_lead(lay, k)
            if lead is not None:
                items[lead.lo] = want
    for ln, t in sorted(lay.first.items()):
        got = indent_of(lay.lines[ln])
        if t.lo in items:
            if got != items[t.lo]:
                yield ("item-indent", ln + 1,
                       f"an item starts at column {got}, its container puts it at {items[t.lo]}")
            continue
        if t.kind in CLOSERS:
            # a closer lines up with its opener's anchor, which rule (c)'s item
            # half already pins through the lines inside
            continue
        if t.kind == "ELSE":
            # fmt lines a leading `else` up with its `if` on purpose
            continue
        if t.kind == "IDENT" and lay.text[t.lo:t.hi] == "derive":
            # a type's `derive` clause on its own line sits at the type's
            # column, by the convention every tracked file follows
            continue
        if t.lo in lay.modifier_of:
            # a modifier wrapped onto a line of its own (`pub(` then `pkg)`)
            # continues the declaration it stands before
            col = lay.indent_at(lay.modifier_of[t.lo])
            if got <= col:
                yield ("continuation-indent", ln + 1,
                       f"a modifier continues the declaration at column {col} but sits at column {got}")
            continue
        path = path_to(lay.root, t.lo)
        if not path:
            yield ("orphan-line", ln + 1, f"no node contains the {t.kind} that starts the line")
            continue
        base = None
        for n in reversed(path):
            if id(n) in bases and lay.lo_min[id(n)] < t.lo and line_lead(lay, n) is not None:
                base = n
                break
        if base is None:
            continue
        col = lay.indent_at(lay.lo_min[id(base)])
        if t.kind == "PIPE" and base.kind in ("Arm", "LetPat", "For"):
            # an or-pattern's alternatives line up with the arm or statement
            # whose pattern they are (fmt's arm_bar). A line-leading bar
            # belongs to a pattern alone, so it cannot be read as a statement.
            if got < col:
                yield ("arm-bar", ln + 1, f"an arm's alternative at {got}, under its arm at {col}")
            continue
        if got <= col:
            yield ("continuation-indent", ln + 1,
                   f"{t.kind} continues the {base.kind} begun at line "
                   f"{lay.line_of(lay.lo_min[id(base)]) + 1} (column {col}) but sits at column {got}")


def default_values(lay):
    """Offsets of parameter default values. The dump prints a parameter's name
    and type but not its default, so nothing there can be judged."""
    hidden = set()
    by_lo = {t.lo: i for i, t in enumerate(lay.code)}
    for n in walk(lay.root):
        if n.kind not in ("Param", "LParam") or n.hi is None:
            continue
        end = max([d.hi for d in walk(n) if d.hi is not None])
        i = next((j for j, t in enumerate(lay.code) if t.lo >= end), None)
        if i is None or lay.code[i].kind != "EQ":
            continue
        depth = 0
        for t in lay.code[i + 1:]:
            if t.kind in ("LPAREN", "LBRACKET", "LBRACE"):
                depth += 1
            elif t.kind in CLOSERS:
                if depth == 0:
                    break
                depth -= 1
            elif t.kind == "COMMA" and depth == 0:
                break
            hidden.add(t.lo)
    return hidden


def check_roles(lay):
    """Rule (d). Yields (rule, line number, detail)."""
    unwrap_ends, binary_ops, starts = set(), set(), set()
    for n in walk(lay.root):
        if n.lo is not None:
            starts.add(n.lo)
        if n.kind == "Unwrap" and n.hi is not None:
            unwrap_ends.add(n.hi)
        elif n.kind == "Binary":
            m = re.search(r" op@(\d+)\.\.(\d+)", n.line)
            if m:
                binary_ops.add(int(m.group(1)))
    hidden = None
    text = lay.text
    for t in lay.code:
        if t.kind not in ("BANG", "MINUS"):
            continue
        if hidden is None:
            hidden = default_values(lay)
        if t.lo in hidden:
            continue
        before = text[t.lo - 1] if t.lo > 0 else "\n"
        after = text[t.hi] if t.hi < len(text) else "\n"
        ln = lay.line_of(t.lo) + 1
        if t.kind == "BANG":
            # the parser's unwrap ends at its `!`; any other `!` the parser
            # accepted is an effect marker (a row or a binding)
            if t.hi in unwrap_ends:
                if before in " \n":
                    yield ("bang-role", ln, "the parser's postfix unwrap is spaced as an effect marker")
            elif before not in " \n([":
                yield ("bang-role", ln, "the parser's effect marker hugs its left, as an unwrap would")
        elif t.lo in binary_ops:
            if before not in " \n" or after not in " \n":
                yield ("minus-role", ln, "the parser's subtraction is printed as a prefix minus")
        elif t.lo in starts:
            # a prefix minus starts the node it negates (a Unary or a literal)
            if after == " ":
                yield ("minus-role", ln, "the parser's prefix minus is printed as a subtraction")


# ---------------------------------------------------------------- driver


def tracked_inputs():
    p = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "*.dawn"],
                       capture_output=True, text=True, check=True)
    return sorted(f for f in p.stdout.split("\0") if f)


def generated_inputs(gen, seeds, cases, into):
    out = []
    for s in seeds:
        p = subprocess.run([sys.executable, gen, "--seed", str(s), "--cases", str(cases)],
                           capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit(f"generator failed on seed {s}:\n{p.stderr[-2000:]}")
        rel = f"generated/seed-{s}.dawn"
        os.makedirs(os.path.join(into, "generated"), exist_ok=True)
        with open(os.path.join(into, rel), "w", encoding="utf-8") as fh:
            fh.write(p.stdout)
        out.append(rel)
    return out


def chain_inputs(into):
    """The synthetic chain corpus: `chains/c<N>.dawn`, each one function whose
    body holds one long dot-call chain. Widths run from well under the limit
    to well past it, so the threshold (a line of exactly 100 stays, 101
    folds) is crossed from both sides; the link kinds are `)`, `]`, `?` and
    `!`; the rest are shapes a lexical folder could get wrong (a comment after
    the line, a non-ASCII string, a chain nested in an argument, a chain the
    author already folded). Deterministic: no random draw."""
    pad = lambda n: "a" * max(n, 1)
    cases = []
    for w in range(88, 116, 3):
        # three links; the middle argument is sized so the line prints w wide
        head = "  let r = xs.map(f)"
        tail = ".filter(g).fold(0, h)"
        cases.append(f"{head}.keep({pad(w - len(head) - len(tail) - 7)}){tail}")
    cases += [
        "  let r = " + "xs.map(f)" + ".step(" + pad(30) + ")?" + ".step(" + pad(30) + ")?" + ".done(" + pad(20) + ")",
        "  let r = " + "xs.map(f)" + ".get(" + pad(30) + ")!" + ".get(" + pad(30) + ")!" + ".done(" + pad(20) + ")",
        "  let r = " + "xs.map(f)" + "[0]" + ".name(" + pad(40) + ")" + "[1]" + ".name(" + pad(40) + ")",
        "  let r = xs.map(f).keep(" + pad(60) + ").take(" + pad(30) + ") # " + "c" * 80,
        "  let r = xs.map(f).keep(\"" + "\u00e9" * 60 + "\").take(" + pad(30) + ").done(1)",
        "  let r = xs.map(f).keep(" + pad(120) + ")",
        "  let r = xs.map(f).keep(" + pad(60) + ").take(ys.map(g).keep(" + pad(30) + ").take(" + pad(30) + "))",
        "  let r = xs.map(f)\n    .keep(" + pad(60) + ")\n    .take(" + pad(60) + ")",
    ]
    out = []
    for i, body in enumerate(cases):
        rel = f"chains/c{i}.dawn"
        write(os.path.join(into, rel), f"fn f() -> Int = {{\n{body}\n  r\n}}\n")
        out.append(rel)
    return out


def check_chains(lay):
    """Rule (e). Yields (rule, line number, detail)."""
    openers = {"LPAREN", "LBRACKET", "LBRACE"}
    for k, line in enumerate(lay.lines):
        toks = lay.code_on(k)
        if not toks:
            continue
        first = toks[0]
        if first.kind in CLOSERS or first.kind in ("COMMENT", "USE"):
            continue
        # the code part of the line: up to a trailing comment
        cut = next((t.lo for t in toks if t.kind == "COMMENT"), None)
        code = [t for t in toks if cut is None or t.lo < cut]
        if any(t.kind == "STRING" and "\n" in lay.text[t.lo:t.hi] for t in code):
            continue
        width = len(lay.lines[k] if cut is None else lay.text[lay.starts[k]:cut].rstrip())
        if width <= 100:
            continue
        depth, bad, links = 0, False, 0
        for j, t in enumerate(code):
            if depth == 0 and j >= 1 and t.kind == "DOT" and j + 2 < len(code) \
                    and code[j + 1].kind == "IDENT" and code[j + 2].kind == "LPAREN":
                p = code[j - 1]
                postfix = p.kind == "BANG" and p.hi == t.lo
                if p.kind in ("RPAREN", "RBRACKET", "QUESTION") or postfix:
                    links += 1
            if t.kind in openers:
                depth += 1
            elif t.kind in CLOSERS:
                depth -= 1
                if depth < 0:
                    bad = True
        if links and depth == 0 and not bad:
            yield ("chain-unfolded", k + 1, f"{width} columns with {links} chain link(s) left on the line")


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
    ap.add_argument("--break-share", type=float, default=0.25,
                    help="share of the eligible breaks the re-broken variant takes")
    ap.add_argument("--gen", help="the fuzz3 generator; default scripts/fuzz3/gen.py when present")
    ap.add_argument("--gen-seeds", default="1-20")
    ap.add_argument("--gen-cases", type=int, default=10)
    ap.add_argument("--only", help="a regex the input paths must match")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", help="keep the work tree here (default: a temporary one)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test(a.dawn)

    work = a.out or tempfile.mkdtemp(prefix="fmt-properties-")
    if a.out:
        shutil.rmtree(work, ignore_errors=True)
    src = os.path.join(work, "src")
    os.makedirs(src)
    inputs = tracked_inputs()
    if a.only:
        inputs = [f for f in inputs if re.search(a.only, f)]
    for f in inputs:
        write(os.path.join(src, f), read(os.path.join(ROOT, f)))
    inputs += chain_inputs(src)
    gen = a.gen or os.path.join(ROOT, "scripts", "fuzz3", "gen.py")
    if os.path.exists(gen):
        lo, _, hi = a.gen_seeds.partition("-")
        seeds = range(int(lo), int(hi or lo) + 1)
        inputs += generated_inputs(gen, seeds, a.gen_cases, src)
        gen_note = f"{len(seeds)} generated files ({a.gen_cases} cases each, seeds {a.gen_seeds})"
    else:
        gen_note = "no generator (scripts/fuzz3/gen.py absent; --gen to name one)"

    def paths(base, fs):
        return [os.path.join(work, base, f) for f in fs]

    # the original: what lexes, what parses
    lex0 = dump_by_file(run_dawn(a.dawn, ["__lex"], paths("src", inputs), a.jobs))
    ast0 = dump_by_file(run_dawn(a.dawn, ["__parse"], paths("src", inputs), a.jobs))
    lexes, parses, toks0, shape0 = [], [], {}, {}
    for f in inputs:
        toks, ld = parse_lex(lex0[os.path.join(work, "src", f)])
        if ld:
            continue
        lexes.append(f)
        toks0[f] = toks
        _, shape, pd = parse_ast(ast0[os.path.join(work, "src", f)])
        if not pd:
            parses.append(f)
            shape0[f] = shape

    # variants: as written, re-indented, and (parsing inputs only) re-broken
    texts = {f: read(os.path.join(src, f)) for f in lexes}
    for f in lexes:
        rng = random.Random(f"{a.seed}:{f}")
        write(os.path.join(work, "v", "orig", f), texts[f])
        write(os.path.join(work, "v", "reindent", f), reindent(texts[f], toks0[f], rng))
    allbreaks = {f: break_points(texts[f], toks0[f]) for f in parses}
    for f in parses:
        write(os.path.join(work, "allbreaks", f), insert_breaks(texts[f], allbreaks[f]))
    lexb = dump_by_file(run_dawn(a.dawn, ["__lex"], paths("allbreaks", parses), a.jobs))
    rebroken = []
    for f in parses:
        toks, ld = parse_lex(lexb[os.path.join(work, "allbreaks", f)])
        if ld:
            continue
        kept = {t.lo for t in toks if t.kind == "NEWLINE"}
        ok = [p for p, q in zip(sorted(allbreaks[f]), shifted(allbreaks[f])) if q not in kept]
        rng = random.Random(f"{a.seed}:{f}:breaks")
        pick = [p for p in ok if rng.random() < a.break_share]
        if pick:
            write(os.path.join(work, "v", "rebreak", f), insert_breaks(texts[f], pick))
            rebroken.append(f)
    variants = {"orig": lexes, "reindent": lexes, "rebreak": rebroken}

    # a re-broken variant must parse as the original did, or it is no input
    astb = dump_by_file(run_dawn(a.dawn, ["__parse"], paths("v/rebreak", rebroken), a.jobs))
    set_aside = []
    for f in rebroken:
        _, shape, pd = parse_ast(astb[os.path.join(work, "v", "rebreak", f)])
        if pd or shape != shape0[f]:
            set_aside.append(f)
    variants["rebreak"] = [f for f in rebroken if f not in set(set_aside)]

    # format once, then again
    shutil.copytree(os.path.join(work, "v"), os.path.join(work, "f1"))
    fmt_tree(a.dawn, os.path.join(work, "f1"), a.jobs)
    shutil.copytree(os.path.join(work, "f1"), os.path.join(work, "f2"))
    fmt_tree(a.dawn, os.path.join(work, "f2"), a.jobs)

    judged = [(v, f) for v, fs in variants.items() for f in fs if f in shape0]
    f1paths = [os.path.join(work, "f1", v, f) for v, f in judged]
    lex1 = dump_by_file(run_dawn(a.dawn, ["__lex"], f1paths, a.jobs))
    ast1 = dump_by_file(run_dawn(a.dawn, ["__parse"], f1paths, a.jobs))

    findings = []

    def add(prop, rule, v, f, detail):
        findings.append((prop, rule, f, v, detail))

    for v, fs in variants.items():
        for f in fs:
            one = read(os.path.join(work, "f1", v, f))
            two = read(os.path.join(work, "f2", v, f))
            if one != two:
                ln = next(i for i, (x, y) in enumerate(zip(one.split("\n") + [None], two.split("\n") + [None])) if x != y)
                add("a", "idempotent", v, f, f"a second fmt moves line {ln + 1}")
            if v == "reindent" and one != read(os.path.join(work, "f1", "orig", f)):
                o = read(os.path.join(work, "f1", "orig", f)).split("\n")
                r = one.split("\n")
                ln = next((i for i, (x, y) in enumerate(zip(o, r)) if x != y), min(len(o), len(r)))
                add("a2", "indent-blind", v, f, f"re-indenting the input moves output line {ln + 1}")
    for v, f in judged:
        p1 = os.path.join(work, "f1", v, f)
        root, shape, pd = parse_ast(ast1[p1])
        if pd or shape != shape0[f]:
            diff = next((i for i, (x, y) in enumerate(zip(shape, shape0[f])) if x != y),
                        min(len(shape), len(shape0[f])))
            add("b", "same-tree", v, f, f"the tree differs from the original's at dump line {diff + 1}"
                + (f" ({pd} diagnostics)" if pd else ""))
            continue
        toks, _ = parse_lex(lex1[p1])
        lay = Layout(read(p1), toks, root)
        for rule, ln, detail in check_layout(lay):
            add("c", rule, v, f, f"line {ln}: {detail}")
        for rule, ln, detail in check_roles(lay):
            add("d", rule, v, f, f"line {ln}: {detail}")
        for rule, ln, detail in check_chains(lay):
            add("e", rule, v, f, f"line {ln}: {detail}")

    # one line per finding, the first few per (property, rule, file)
    seen = {}
    for prop, rule, f, v, detail in sorted(findings):
        key = (prop, rule, f)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= 3:
            print(f"{prop} {rule} {f} [{v}]: {detail}")
    for key, n in sorted(seen.items()):
        if n > 3:
            print(f"{key[0]} {key[1]} {key[2]}: {n - 3} more")
    nb = sum(len(fs) for fs in variants.values())
    print(f"inputs: {len(inputs)} files ({gen_note}); {len(lexes)} lex, {len(parses)} parse")
    print(f"variants judged: orig {len(variants['orig'])}, reindent {len(variants['reindent'])}, "
          f"rebreak {len(variants['rebreak'])} ({len(set_aside)} set aside: their parse moved); "
          f"{nb} formatted")
    for f in set_aside[:5]:
        print(f"  set aside: {f}")
    if not a.out:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"work tree kept in {work}")
    if findings:
        sigs = sorted({f"{p}:{r}:{v}" for p, r, _, v, _ in findings})
        print(f"{len(findings)} findings in {len(seen)} (property, rule, file) keys")
        print("verdict: " + ",".join(sigs))
        return 1
    print("verdict: green")
    return 0


# ---------------------------------------------------------------- self-test


def self_test(dawn):
    """Each check on a two-line input it must flag, and the fix it must pass."""
    cases = [
        # (name, formatted text, must flag a rule)
        ("statement-level continuation (#188's shape)",
         "fn f() -> Int = {\n  let a:\n  Int = 6\n  a\n}\n", "continuation-indent"),
        ("continuation one level in",
         "fn f() -> Int = {\n  let a:\n    Int = 6\n  a\n}\n", None),
        ("a glued empty row (#187's shape)", "fn f() -> Int!() = 1\n", "bang-role"),
        ("a spaced empty row", "fn f() -> Int !() = 1\n", None),
        ("an over-indented statement", "fn f() -> Int = {\n    1\n}\n", "item-indent"),
        ("a spaced subtraction", "fn f(a: Int) -> Int = a - 1\n", None),
        ("a glued subtraction", "fn f(a: Int) -> Int = a -1\n", "minus-role"),
        ("a sole lambda argument on a line of its own",
         "fn f() -> Int = {\n  let a = g(\n    () => {\n      1\n    })\n  a\n}\n", None),
        ("the same body at the call's own level",
         "fn f() -> Int = {\n  let a = g(\n    () => {\n    1\n    })\n  a\n}\n", "item-indent"),
        ("an `if` on the line after the parenthesis that groups it",
         "fn f() -> Int = {\n  let a = (\n    if c {\n      1\n    } else {\n      2\n    })\n  a\n}\n", None),
        ("the same body one level shallower",
         "fn f() -> Int = {\n  let a = (\n    if c {\n    1\n    } else {\n      2\n    })\n  a\n}\n", "item-indent"),
        ("a grouping parenthesis closing after its last operand's own parenthesis",
         "fn f(a: Int, b: Int) -> Int = {\n  let r = a\n  (\n    g(r,\n      28) &\n      (a & b))\n}\n", None),
        ("members of a trait whose modifier wrapped",
         "pub(\n  pkg) trait W[T] {\n  fn w(\n    x: T) -> Int\n}\n", None),
        ("an arm whose leading bar stands alone on the line above",
         "fn f(o: Int) -> Int = match o {\n  1 -> 1\n  |\n    2 -> 0\n}\n", None),
        ("a grouping parenthesis on a line of its own",
         "fn f() -> Int = {\n  let r = b\n  (\n    h(r) << 2) + h(\n      r)\n}\n", None),
        ("a chain line past 100 columns left whole",
         "fn f() -> Int = {\n  let r = xs.map(f).keep(" + "a" * 70 + ").take(" + "a" * 20 + ")\n  r\n}\n",
         "chain-unfolded"),
        ("the same chain folded at its links",
         "fn f() -> Int = {\n  let r = xs.map(f)\n    .keep(" + "a" * 70 + ")\n    .take(" + "a" * 20 + ")\n  r\n}\n",
         None),
        ("a wide line with no chain link is the author's",
         "fn f() -> Int = {\n  let r = g(" + "a" * 70 + ", " + "b" * 40 + ")\n  r\n}\n", None),
    ]
    tmp = tempfile.mkdtemp(prefix="fmt-properties-self-")
    files = []
    for i, (_, text, _) in enumerate(cases):
        p = os.path.join(tmp, f"c{i}.dawn")
        write(p, text)
        files.append(p)
    lex = dump_by_file(run_dawn(dawn, ["__lex"], files, 1))
    ast = dump_by_file(run_dawn(dawn, ["__parse"], files, 1))
    bad = 0
    for (name, text, want), p in zip(cases, files):
        root, _, pd = parse_ast(ast[p])
        toks, _ = parse_lex(lex[p])
        lay = Layout(text, toks, root)
        rules = {r for r, _, _ in check_layout(lay)} | {r for r, _, _ in check_roles(lay)} \
            | {r for r, _, _ in check_chains(lay)}
        ok = (want in rules) if want else not rules
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {sorted(rules) or 'clean'}")
        bad += 0 if ok and not pd else 1
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

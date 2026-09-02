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
functions. A possible wording becomes a sequence of string-literal chunks
(interpolations cut out); the site counts as reached only when one recorded
diagnostic contains every chunk of one possible wording, in source order.

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
SOURCES = (
    "selfhost/src/check/cx.dawn",
    "selfhost/src/check/passes.dawn",
    "selfhost/src/check/checker*.dawn",
)
CASES = "scripts/checker-corpus/cases"
UNCOVERED = "scripts/checker-corpus/uncovered.txt"

CALL = re.compile(r"\bcerr(_h|_o)?\(")
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


def literals(expr, at_depth=None):
    """Literal chunks emitted by an expression, interpolations cut out.

    Formatting helpers carry their own literal arguments -- the separator in
    `join(names, ", ")`, for example. Those are data for the helper rather than
    fixed chunks of the diagnostic, and requiring them would make a one-item
    join look unreached. Keep only literals at the expression's shallowest
    nesting level. Splitting an `if`/`match` branch below gives each branch its
    own level, while nested helper arguments remain deeper. Tuple expansion
    can request an exact depth after it has removed the tuple's parentheses.
    """
    found = []
    depth = 0
    i = 0
    while i < len(expr):
        c = expr[i]
        if c == "#":
            end = expr.find("\n", i)
            i = len(expr) if end < 0 else end + 1
            continue
        if c == '"':
            j = i + 1
            raw = []
            while j < len(expr):
                if expr[j] == "\\" and j + 1 < len(expr):
                    raw.append(expr[j : j + 2])
                    j += 2
                    continue
                if expr[j] == '"':
                    break
                raw.append(expr[j])
                j += 1
            body = "".join(raw)
            body = (
                body.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
            found.append((depth, body))
            i = j + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}" and depth > 0:
            depth -= 1
        i += 1

    if not found:
        return []
    wanted = min(depth for depth, _ in found) if at_depth is None else at_depth
    out = []
    for depth, body in found:
        if depth == wanted:
            for piece in re.split(r"\$\{[^}]*\}", body):
                if piece:
                    out.append(piece)
    return out


# A message expression is often an `if`/`match` over several wordings. Only an
# `if` body or a `match` arm's right-hand side is a possible wording: literals
# in the condition or pattern decide which wording runs, but are not emitted.
def code_mask(expr):
    """Hide quoted contents and comments while preserving offsets and quotes."""
    mask = list(expr)
    i = 0
    while i < len(expr):
        if expr[i] == "#":
            end = expr.find("\n", i)
            end = len(expr) if end < 0 else end
            for j in range(i, end):
                mask[j] = " "
            i = end
            continue
        if expr[i] in "\"'":
            quote = expr[i]
            j = i + 1
            closed = False
            while j < len(expr):
                if expr[j] == "\\" and j + 1 < len(expr):
                    j += 2
                    continue
                if expr[j] == quote:
                    j += 1
                    closed = True
                    break
                j += 1
            # Keep the delimiters so skip_space can still find a quoted RHS.
            # Its contents must be invisible to brace and arrow scans; char
            # literals in particular may themselves contain `{` or `}`.
            content_end = j - 1 if closed else j
            for k in range(i + 1, content_end):
                mask[k] = " "
            i = j
            continue
        i += 1
    return "".join(mask)


def skip_space(code, pos, end=None):
    limit = len(code) if end is None else end
    while pos < limit and code[pos].isspace():
        pos += 1
    return pos


def word_at(code, pos, word):
    end = pos + len(word)
    return (
        code[pos:end] == word
        and (pos == 0 or not (code[pos - 1].isalnum() or code[pos - 1] == "_"))
        and (end == len(code) or not (code[end].isalnum() or code[end] == "_"))
    )


def matching_delimiter(code, pos):
    pairs = {"(": ")", "[": "]", "{": "}"}
    opener = code[pos]
    closer = pairs[opener]
    depth = 1
    i = pos + 1
    while i < len(code):
        if code[i] == opener:
            depth += 1
        elif code[i] == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(code)


def body_brace(code, pos):
    """First brace belonging to this header, past nested branch expressions."""
    # Dawn's no-tail-block header mode still permits a primary `if` or `match`,
    # without grouping, so its complete body must be skipped structurally.
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    while pos < len(code):
        c = code[pos]
        nested = branch_keyword(code, pos)
        if nested is not None:
            after = branch_expression_end(code, pos, nested)
            if after > pos:
                pos = after
                continue
        if c == "{" and not stack:
            return pos
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                return -1
            stack.pop()
        pos += 1
    return -1


def branch_keyword(code, pos):
    """A branch keyword here, excluding a keyword used as a member name."""
    keyword = None
    if word_at(code, pos, "if"):
        keyword = "if"
    elif word_at(code, pos, "match"):
        keyword = "match"
    if keyword is None:
        return None
    before = pos - 1
    while before >= 0 and code[before].isspace():
        before -= 1
    return None if before >= 0 and code[before] == "." else keyword


def branch_expression_end(code, start, keyword):
    """End of an `if`/`match` expression that starts inside a header."""
    brace = body_brace(code, start + len(keyword))
    if brace < 0:
        return start
    close = matching_delimiter(code, brace)
    if close >= len(code):
        return start
    end = close + 1
    if keyword != "if":
        return end
    pos = skip_space(code, end)
    if not word_at(code, pos, "else"):
        return end
    pos = skip_space(code, pos + len("else"))
    if word_at(code, pos, "if"):
        return branch_expression_end(code, pos, "if")
    if pos >= len(code) or code[pos] != "{":
        return start
    close = matching_delimiter(code, pos)
    return start if close >= len(code) else close + 1


def if_arm_bodies(expr, code, start):
    """Return the bodies of one `if` / `else if` / `else` expression."""
    out = []
    pos = start
    while word_at(code, pos, "if"):
        brace = body_brace(code, pos + len("if"))
        if brace < 0:
            return []
        close = matching_delimiter(code, brace)
        if close >= len(code):
            return []
        out.append(expr[brace + 1 : close])
        pos = skip_space(code, close + 1)
        if not word_at(code, pos, "else"):
            return out
        pos = skip_space(code, pos + len("else"))
        if word_at(code, pos, "if"):
            continue
        if pos >= len(code) or code[pos] != "{":
            return []
        close = matching_delimiter(code, pos)
        if close >= len(code):
            return []
        out.append(expr[pos + 1 : close])
        return out
    return []


def match_arrows(code, start, end):
    """Top-level arm arrows inside a match body."""
    stack = []
    out = []
    pairs = {")": "(", "]": "[", "}": "{"}
    i = start
    while i < end:
        c = code[i]
        if c in "([{":
            stack.append(c)
        elif c in ")]}" and stack and stack[-1] == pairs[c]:
            stack.pop()
        elif c == "-" and i + 1 < end and code[i + 1] == ">" and not stack:
            out.append(i)
            i += 1
        i += 1
    return out


def match_arm_bodies(expr, code, start):
    """Return each top-level match arm RHS, excluding its pattern."""
    brace = body_brace(code, start + len("match"))
    if brace < 0:
        return []
    close = matching_delimiter(code, brace)
    if close >= len(code):
        return []
    arrows = match_arrows(code, brace + 1, close)
    out = []
    for i, arrow in enumerate(arrows):
        rhs = skip_space(code, arrow + 2, close)
        end = close
        if rhs < close and code[rhs] in "([{":
            paired = matching_delimiter(code, rhs)
            after = skip_space(code, paired + 1, close)
            if paired < close and code[after : after + 2] != "++":
                end = paired + 1
        if end == close and i + 1 < len(arrows):
            next_arrow = arrows[i + 1]
            line = expr.rfind("\n", rhs, next_arrow)
            if line >= rhs:
                end = line
            else:
                comma = code.rfind(",", rhs, next_arrow)
                semicolon = code.rfind(";", rhs, next_arrow)
                separator = max(comma, semicolon)
                if separator >= rhs:
                    end = separator
        body = expr[rhs:end].rstrip()
        if body.endswith(","):
            body = body[:-1].rstrip()
        out.append(body)
    return out


def outer_parens(expr):
    """Contents when one pair of parentheses encloses the whole expression."""
    code = code_mask(expr)
    start = skip_space(code, 0)
    end = len(code)
    while end > start and code[end - 1].isspace():
        end -= 1
    if start >= end or code[start] != "(":
        return None
    close = matching_delimiter(code, start)
    return expr[start + 1 : close] if close == end - 1 else None


def top_level_parts(expr):
    """Comma-separated expression parts at this delimiter depth."""
    code = code_mask(expr)
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    out = []
    start = 0
    for pos, c in enumerate(code):
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if stack and stack[-1] == pairs[c]:
                stack.pop()
        elif c == "," and not stack:
            out.append(expr[start:pos])
            start = pos + 1
    out.append(expr[start:])
    return out


def branch_bodies(expr):
    """Possible complete RHS/body expressions, or [] for a non-branch."""
    while True:
        inner = outer_parens(expr)
        if inner is None or len(top_level_parts(inner)) != 1:
            break
        expr = inner
    code = code_mask(expr)
    start = skip_space(code, 0)
    if word_at(code, start, "if"):
        return if_arm_bodies(expr, code, start)
    if word_at(code, start, "match"):
        return match_arm_bodies(expr, code, start)
    return []


def patterns(lits, expr):
    """Literal sequences a recorded diagnostic may match for this site."""
    cands = []

    def add(chunks):
        # One long chunk is discriminating on its own; so is a run of short
        # ones in a fixed order ("field `" ... "` of `" ... "` is " ... ", got ").
        if not chunks:
            return
        if max(len(c) for c in chunks) < MIN_CHUNK and len(chunks) < 3:
            return
        candidate = tuple(chunks)
        if candidate not in cands:
            cands.append(candidate)

    # An indirect message helper may choose a complete (message, hint) pair by
    # `if`/`match`. Each arm is a possible complete wording. Do not split an
    # arbitrary concatenation merely because it contains a conditional: that
    # would turn a prefix outside the conditional back into a one-chunk match.
    def wordings(body, chunks=None, direct=False):
        inner = outer_parens(body)
        if inner is not None:
            parts = top_level_parts(inner)
            if len(parts) > 1:
                combinations = [()]
                for part in parts:
                    choices = wordings(part, direct=True)
                    combinations = [
                        prefix + choice
                        for prefix in combinations
                        for choice in choices
                    ]
                return combinations
            return wordings(inner, direct=direct)
        branches = branch_bodies(body)
        if branches:
            out = []
            for branch in branches:
                out += wordings(branch, direct=direct)
            return out
        found = literals(body, 0) if direct else literals(body)
        return [tuple(found if chunks is None else chunks)]

    for chunks in wordings(expr, lits):
        add(chunks)
    return cands


def contains_chunks(message, chunks):
    """Whether every chunk occurs in `message`, in order and without reuse."""
    at = 0
    for chunk in chunks:
        at = message.find(chunk, at)
        if at < 0:
            return False
        at += len(chunk)
    return True


def site_reached(site, messages):
    return any(
        contains_chunks(message, chunks)
        for chunks in site["pats"]
        for message in messages
    )


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
            lits = literals(expr)
            pats = patterns(lits, expr)
            if not pats:
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
                    resolved = []
                    for body in bodies:
                        resolved += patterns(literals(body), body)
                    if resolved:
                        pats = resolved
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
                    "pats": pats,
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


def self_test():
    shared = (
        '"`" ++ fname ++ "` uses the effect `" ++ name ++ '
        '"`, but a local function cannot carry an effect label"'
    )
    echoed = (
        "`unanswered` uses the effect `Ask`, but its signature does not declare !Ask"
    )
    pats = patterns(literals(shared), shared)
    legacy_hit = any(
        chunk in echoed
        for chunk in literals(shared)
        if len(chunk) >= MIN_CHUNK
    )
    if not legacy_hit:
        print("FAIL: shared-chunk control no longer exercises the old matcher", file=sys.stderr)
        return 1
    if site_reached({"pats": pats}, [echoed]):
        print(
            "FAIL: a diagnostic that echoes only one literal chunk reached the site",
            file=sys.stderr,
        )
        return 1
    actual = (
        "`inner` uses the effect `Ask`, but a local function cannot carry an "
        "effect label"
    )
    if not site_reached({"pats": pats}, [actual]):
        print("FAIL: the complete site wording did not reach the site", file=sys.stderr)
        return 1
    ordered = patterns(["first literal", "second literal"], "")
    if site_reached({"pats": ordered}, ["second literal, then first literal"]):
        print("FAIL: reversed literal chunks reached the site", file=sys.stderr)
        return 1
    joined = '"cannot infer " ++ join(names, ", ") ++ " for `" ++ name ++ "`"'
    if patterns(literals(joined), joined) != [
        ("cannot infer ", " for `", "`")
    ]:
        print("FAIL: a nested formatting literal became a message chunk", file=sys.stderr)
        return 1
    branched = (
        'if flag { ("left message", "left hint") } '
        'else { ("right message", "right hint") }'
    )
    branch_pats = patterns(literals(branched), branched)
    if not site_reached({"pats": branch_pats}, ["left message\tleft hint"]):
        print("FAIL: a complete branch wording did not reach the site", file=sys.stderr)
        return 1
    if site_reached({"pats": branch_pats}, ["left message\tright hint"]):
        print("FAIL: chunks from different branches reached the site", file=sys.stderr)
        return 1
    condition_strings = (
        'if d.name == "Option" || d.name == "Result" || d.name == "ForeignError" { '
        '"`" ++ d.name ++ "` is a prelude type and cannot be redefined" '
        '} else { "type `" ++ d.name ++ "` is defined twice" }'
    )
    if patterns(literals(condition_strings), condition_strings) != [
        ("`", "` is a prelude type and cannot be redefined"),
        ("type `", "` is defined twice"),
    ]:
        print("FAIL: literals from an if condition became a message candidate", file=sys.stderr)
        return 1
    pattern_strings = (
        'match kind { "alpha" -> ("alpha message", "alpha hint") '
        '"beta" -> ("beta message", "beta hint") }'
    )
    if patterns(literals(pattern_strings), pattern_strings) != [
        ("alpha message", "alpha hint"),
        ("beta message", "beta hint"),
    ]:
        print("FAIL: match patterns displaced or became message candidates", file=sys.stderr)
        return 1
    bare_match = (
        'match kind {\n  "alpha" -> "alpha message"\n'
        '  "beta" -> "beta message"\n}'
    )
    if patterns(literals(bare_match), bare_match) != [
        ("alpha message",),
        ("beta message",),
    ]:
        print("FAIL: a bare-string match arm was lost", file=sys.stderr)
        return 1
    nested_if = (
        'if outer { if inner { "nested yes message" } '
        'else { "nested no message" } }'
    )
    if patterns(literals(nested_if), nested_if) != [
        ("nested yes message",),
        ("nested no message",),
    ]:
        print("FAIL: nested if wordings were combined", file=sys.stderr)
        return 1
    match_if = (
        'match kind {\n  "nested" -> if inner { "match yes message" } '
        'else { "match no message" }\n  _ -> "other match message"\n}'
    )
    if patterns(literals(match_if), match_if) != [
        ("match yes message",),
        ("match no message",),
        ("other match message",),
    ]:
        print("FAIL: a match arm's nested if wordings were combined", file=sys.stderr)
        return 1
    char_condition = (
        "if marker == '{' { \"opening brace message\" } "
        "else { \"other brace message\" }"
    )
    if patterns(literals(char_condition), char_condition) != [
        ("opening brace message",),
        ("other brace message",),
    ]:
        print("FAIL: a char literal brace changed if structure", file=sys.stderr)
        return 1
    char_pattern = (
        "match marker {\n  '}' -> \"closing brace message\"\n"
        "  _ -> \"other char message\"\n}"
    )
    if patterns(literals(char_pattern), char_pattern) != [
        ("closing brace message",),
        ("other char message",),
    ]:
        print("FAIL: a char literal brace changed match structure", file=sys.stderr)
        return 1
    branch_condition = (
        "if (match flag { True -> true\nFalse -> false }) { "
        '"condition yes message" } else { "condition no message" }'
    )
    if patterns(literals(branch_condition), branch_condition) != [
        ("condition yes message",),
        ("condition no message",),
    ]:
        print("FAIL: a nested branch stole its enclosing if body", file=sys.stderr)
        return 1
    branch_scrutinee = (
        'match (if flag { "left-key" } else { "right-key" }) {\n'
        '  "left-key" -> "left message"\n'
        '  "right-key" -> "right message"\n}'
    )
    if patterns(literals(branch_scrutinee), branch_scrutinee) != [
        ("left message",),
        ("right message",),
    ]:
        print("FAIL: a nested branch stole its enclosing match body", file=sys.stderr)
        return 1
    grouped_branch = (
        'if outer { (if inner { "group yes message" } '
        'else { "group no message" }) }'
    )
    if patterns(literals(grouped_branch), grouped_branch) != [
        ("group yes message",),
        ("group no message",),
    ]:
        print("FAIL: grouping hid a nested branch", file=sys.stderr)
        return 1
    conditional_message = (
        '(if flag { "left message" } else { "right message" }, "shared hint")'
    )
    if patterns(literals(conditional_message), conditional_message) != [
        ("left message", "shared hint"),
        ("right message", "shared hint"),
    ]:
        print("FAIL: a conditional tuple message lost its hint", file=sys.stderr)
        return 1
    conditional_hint = (
        '("shared message", if flag { "left hint" } else { "right hint" })'
    )
    if patterns(literals(conditional_hint), conditional_hint) != [
        ("shared message", "left hint"),
        ("shared message", "right hint"),
    ]:
        print("FAIL: a conditional tuple hint lost its branch", file=sys.stderr)
        return 1
    conditional_pair = (
        '(if left { "first message" } else { "second message" }, '
        'if right { "first hint" } else { "second hint" })'
    )
    if patterns(literals(conditional_pair), conditional_pair) != [
        ("first message", "first hint"),
        ("first message", "second hint"),
        ("second message", "first hint"),
        ("second message", "second hint"),
    ]:
        print("FAIL: conditional tuple elements were not combined", file=sys.stderr)
        return 1
    tuple_formatter = '("shared message", join(names, ", "))'
    if patterns(literals(tuple_formatter), tuple_formatter) != [("shared message",)]:
        print("FAIL: tuple expansion promoted a formatting literal", file=sys.stderr)
        return 1
    ungrouped_condition = (
        "if match flag { true -> true\nfalse -> false } { "
        '"ungrouped yes message" } else { "ungrouped no message" }'
    )
    if patterns(literals(ungrouped_condition), ungrouped_condition) != [
        ("ungrouped yes message",),
        ("ungrouped no message",),
    ]:
        print("FAIL: an ungrouped branch stole its enclosing if body", file=sys.stderr)
        return 1
    ungrouped_scrutinee = (
        'match if flag { "left-key" } else { "right-key" } {\n'
        '  "left-key" -> "ungrouped left message"\n'
        '  "right-key" -> "ungrouped right message"\n}'
    )
    if patterns(literals(ungrouped_scrutinee), ungrouped_scrutinee) != [
        ("ungrouped left message",),
        ("ungrouped right message",),
    ]:
        print("FAIL: an ungrouped branch stole its enclosing match body", file=sys.stderr)
        return 1
    print("coverage selftest: ordered chunks and branch structure verified")
    return 0


def main():
    if "--selftest" in sys.argv:
        return self_test()
    record = "--record" in sys.argv
    sites = collect_sites()
    msgs = recorded_messages()

    seen = {}
    uncovered = []
    n_cov = 0
    for s in sites:
        k = key_of(s, seen)
        hit = site_reached(s, msgs)
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

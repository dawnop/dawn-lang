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
through immutable local `let` bindings and through bounded, safely substitutable
same-file helper calls. A possible wording becomes a sequence of literal chunks
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
    r"^\s*let\s+(\(?[A-Za-z_][A-Za-z0-9_, ]*\)?)\s*(?::[^=]*)?=", re.M
)
FN = re.compile(r"^(?:pub )?fn ([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
IDENT = re.compile(r"\b([a-z_][A-Za-z0-9_]*)\b")

MIN_CHUNK = 8  # shorter chunks match by accident ("` is ", " and ")
MAX_CANDIDATES = 64
MAX_PROJECTION_DEPTH = 32
MAX_HELPER_DEPTH = 8
DELIMITERS = {"(": ")", "[": "]", "{": "}"}


def interpolation_end(text, brace, projection_depth=0):
    """Position past a `${...}` interpolation, including nested literals."""
    if projection_depth >= MAX_PROJECTION_DEPTH:
        return len(text)
    brace_depth = 1
    i = brace + 1
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            i, _, _ = quoted_span(text, i, projection_depth + 1)
            continue
        if c == "{":
            brace_depth += 1
        elif c == "}":
            brace_depth -= 1
            if brace_depth == 0:
                return i + 1
        i += 1
    return len(text)


def quoted_span(text, start, projection_depth=0):
    """Return (end, kind, closed) for every literal form the lexer accepts."""
    if projection_depth >= MAX_PROJECTION_DEPTH:
        return len(text), "string", False
    quote = text[start]
    if quote == "`":
        close = text.find("`", start + 1)
        return (
            (len(text), "raw", False)
            if close < 0
            else (close + 1, "raw", True)
        )
    triple = quote == '"' and text.startswith('"""', start)
    kind = "triple" if triple else "char" if quote == "'" else "string"
    width = 3 if triple else 1
    i = start + width
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if kind != "char" and text[i] == "$":
            if i + 1 < len(text) and text[i + 1] == "{":
                i = interpolation_end(text, i + 1, projection_depth + 1)
                continue
            if i + 1 < len(text) and (text[i + 1].isalpha() or text[i + 1] == "_"):
                i += 2
                while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                continue
        if triple and text.startswith('"""', i):
            return i + 3, kind, True
        if not triple and text[i] == quote:
            return i + 1, kind, True
        i += 1
    return len(text), kind, False


def lexical_spans(text):
    """Yield (kind, start, end, closed) for code, comments and literals."""
    code_start = 0
    pos = 0
    while pos < len(text):
        if text[pos] == "#":
            if code_start < pos:
                yield ("code", code_start, pos, True)
            end = text.find("\n", pos)
            end = len(text) if end < 0 else end
            yield ("comment", pos, end, True)
            pos = end
            code_start = pos
            continue
        if text[pos] in "\"'`":
            if code_start < pos:
                yield ("code", code_start, pos, True)
            end, kind, closed = quoted_span(text, pos)
            yield (kind, pos, end, closed)
            pos = end
            code_start = pos
            continue
        pos += 1
    if code_start < len(text):
        yield ("code", code_start, len(text), True)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def scan_args(s, i, code=None):
    """`i` points just past `(`. Returns the top-level argument expressions."""
    code = code_mask(s) if code is None else code
    close = matching_delimiter(code, i - 1)
    if close >= len(s):
        raise ValueError("unterminated call at offset %d" % i)
    return [
        part for part in split_top_level(s, ",", i, close, code) if part.strip()
    ]


def block_after(text, pos, code=None):
    """The expression at `pos`, through its parser-valid continuation lines."""
    code = code_mask(text) if code is None else code
    for offset in top_level_offsets(code, pos):
        if code[offset] in ")]}":
            return text[pos:offset]
        if code[offset] == "\n":
            if newline_continues(code, offset, pos, len(code)):
                continue
            return text[pos:offset]
    return text[pos:]


def decode_string(text):
    """Decode the fixed-text escapes accepted by the Dawn lexer."""
    out = []
    escapes = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "\\": "\\",
        '"': '"',
        "'": "'",
        "$": "$",
        "{": "{",
    }
    i = 0
    while i < len(text):
        if text[i] != "\\" or i + 1 >= len(text):
            out.append(text[i])
            i += 1
            continue
        if text[i + 1] == "u" and i + 2 < len(text) and text[i + 2] == "{":
            close = text.find("}", i + 3)
            if close >= 0:
                try:
                    out.append(chr(int(text[i + 3 : close], 16)))
                    i = close + 1
                    continue
                except (ValueError, OverflowError):
                    pass
        out.append(escapes.get(text[i + 1], text[i : i + 2]))
        i += 2
    return "".join(out)


def strip_triple_segments(parts):
    """Apply the lexer's triple-string indentation rules to text/code parts."""
    if not parts:
        return parts
    parts = list(parts)
    if isinstance(parts[0], str) and parts[0].startswith("\n"):
        parts[0] = parts[0][1:]
    if isinstance(parts[-1], str):
        last_nl = parts[-1].rfind("\n")
        if last_nl >= 0 and parts[-1][last_nl + 1 :].strip(" \t\r") == "":
            parts[-1] = parts[-1][:last_nl]

    min_indent = None
    at_start = True
    run_ws = 0
    for part in parts:
        if part is None:
            if at_start:
                min_indent = run_ws if min_indent is None else min(min_indent, run_ws)
                at_start = False
                run_ws = 0
            continue
        for char in part:
            if at_start:
                if char in " \t":
                    run_ws += 1
                    continue
                if char == "\n":
                    run_ws = 0
                    continue
                min_indent = run_ws if min_indent is None else min(min_indent, run_ws)
                at_start = False
                run_ws = 0
            elif char == "\n":
                at_start = True
                run_ws = 0
    if not min_indent:
        return parts

    out = []
    at_start = True
    drop = min_indent
    for part in parts:
        if part is None:
            out.append(None)
            at_start = False
            drop = 0
            continue
        buf = []
        for char in part:
            if at_start and drop > 0 and char in " \t":
                drop -= 1
            else:
                buf.append(char)
                if char == "\n":
                    at_start = True
                    drop = min_indent
                else:
                    at_start = False
                    drop = 0
        out.append("".join(buf))
    return out


def string_segments(expr, start, end, kind):
    """Fixed text segments of one string, with interpolations omitted."""
    width = 3 if kind == "triple" else 1
    stop = end - width
    if kind == "raw":
        return [expr[start + 1 : stop]]
    parts = []
    buf = []
    i = start + width
    while i < stop:
        if expr[i] == "\\" and i + 1 < stop:
            buf.append(expr[i : i + 2])
            i += 2
            continue
        if expr[i] == "$":
            next_i = i + 1
            if next_i < stop and expr[next_i] == "{":
                parts.append(decode_string("".join(buf)))
                parts.append(None)
                buf = []
                i = interpolation_end(expr, next_i)
                continue
            if next_i < stop and (expr[next_i].isalpha() or expr[next_i] == "_"):
                parts.append(decode_string("".join(buf)))
                parts.append(None)
                buf = []
                i = next_i + 1
                while i < stop and (expr[i].isalnum() or expr[i] == "_"):
                    i += 1
                continue
        buf.append(expr[i])
        i += 1
    parts.append(decode_string("".join(buf)))
    if kind == "triple":
        parts = strip_triple_segments(parts)
    return [part for part in parts if isinstance(part, str) and part]


def interpolation_expressions(expr):
    """Source expressions inside `${...}` segments of ordinary strings."""
    for kind, start, end, closed in lexical_spans(expr):
        if kind not in ("string", "triple") or not closed:
            continue
        width = 3 if kind == "triple" else 1
        pos, stop = start + width, end - width
        while pos < stop:
            if expr[pos] == "\\" and pos + 1 < stop:
                pos += 2
                continue
            if expr[pos : pos + 2] == "${":
                after = interpolation_end(expr, pos + 1)
                if after > stop:
                    break
                yield expr[pos + 2 : after - 1]
                pos = after
                continue
            pos += 1


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
    for kind, start, end, closed in lexical_spans(expr):
        if kind == "code":
            for char in expr[start:end]:
                if char in "([{":
                    depth += 1
                elif char in ")]}" and depth > 0:
                    depth -= 1
        elif kind != "comment" and closed and kind != "char":
            for body in string_segments(expr, start, end, kind):
                found.append((depth, body))

    if not found:
        return []
    wanted = min(depth for depth, _ in found) if at_depth is None else at_depth
    out = []
    for depth, body in found:
        if depth == wanted:
            out.append(body)
    return out


# A message expression is often an `if`/`match` over several wordings. Only an
# `if` body or a `match` arm's right-hand side is a possible wording: literals
# in the condition or pattern decide which wording runs, but are not emitted.
def code_mask(expr):
    """Hide quoted contents and comments while preserving offsets and quotes."""
    mask = list(expr)
    for kind, start, end, closed in lexical_spans(expr):
        if kind == "comment":
            content_start, content_end = start, end
        elif kind != "code":
            # Keep the delimiters so skip_space can still find a quoted RHS.
            # Its contents must be invisible to brace and arrow scans; char
            # literals in particular may themselves contain `{` or `}`.
            content_start = start + 1
            content_end = end - 1 if closed else end
        else:
            continue
        for pos in range(content_start, content_end):
            mask[pos] = " "
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


def delimiter_events(code, start=0, end=None, initial=()):
    """Yield (offset, char, stack-before, stack-after) from one delimiter scan."""
    end = len(code) if end is None else end
    stack = list(initial)
    for offset in range(start, end):
        char = code[offset]
        before = tuple(stack)
        if char in DELIMITERS:
            stack.append((DELIMITERS[char], offset))
        elif stack and char == stack[-1][0]:
            stack.pop()
        yield offset, char, before, tuple(stack)


def matching_delimiter(code, pos):
    initial = ((DELIMITERS[code[pos]], pos),)
    for offset, _, before, after in delimiter_events(code, pos + 1, initial=initial):
        if before and before[-1][1] == pos and not after:
            return offset
    return len(code)


def top_level_offsets(code, start=0, end=None):
    """Offsets outside every balanced delimiter in already-masked code."""
    for offset, _, before, after in delimiter_events(code, start, end):
        if not before and not after:
            yield offset


def enclosing_block_ends(code, offsets):
    """Innermost braced scope end for requested source offsets."""
    wanted = set(offsets)
    owners = {}
    closes = {}
    for offset, char, before, after in delimiter_events(code):
        if offset in wanted:
            braces = [open_pos for close, open_pos in before if close == "}"]
            owners[offset] = braces[-1] if braces else None
        if before and len(after) < len(before) and char == before[-1][0]:
            closes[before[-1][1]] = offset
    return {
        offset: closes.get(owner, len(code)) if owner is not None else len(code)
        for offset, owner in owners.items()
    }


def top_level_tokens(code, tokens, start=0, end=None):
    """(offset, token) matches outside delimiters, longest token first."""
    tokens = tuple(sorted(tokens, key=len, reverse=True))
    covered = -1
    for offset in top_level_offsets(code, start, end):
        if offset < covered:
            continue
        token = next((token for token in tokens if code.startswith(token, offset)), None)
        if token is not None:
            covered = offset + len(token)
            yield offset, token


def split_top_level(expr, token, start=0, end=None, code=None):
    """Split a source interval on one token outside balanced delimiters."""
    end = len(expr) if end is None else end
    code = code_mask(expr) if code is None else code
    out = []
    part = start
    for offset, _ in top_level_tokens(code, (token,), start, end):
        out.append(expr[part:offset])
        part = offset + len(token)
    out.append(expr[part:end])
    return out


def newline_continues(code, offset, start, end, leading_ops=None):
    """Whether a top-level newline belongs to the surrounding expression."""
    leading_ops = (
        tuple(op for op in HEADER_BINARY_OPS if op not in ("+", "-"))
        if leading_ops is None
        else leading_ops
    )
    nxt = skip_space(code, offset + 1, end)
    if nxt >= end or word_at(code, nxt, "else"):
        return True
    prev = offset - 1
    while prev >= start and code[prev].isspace():
        prev -= 1
    trailing = HEADER_BINARY_OPS + ("=>", "->", "=", ",", ".")
    return any(code[: prev + 1].endswith(token) for token in trailing) or any(
        code.startswith(token, nxt) for token in leading_ops + (".",)
    )


HEADER_BINARY_OPS = (
    ">>>",
    "|>",
    "||",
    "&&",
    "==",
    "!=",
    "<=",
    ">=",
    "<<",
    ">>",
    "++",
    "+",
    "-",
    "*",
    "/",
    "%",
    "|",
    "^",
    "&",
    "<",
    ">",
)


def body_brace(code, pos, depth=0):
    """First brace belonging to this header, past its complete expression."""
    # primary_expr's braced forms are block, if, match, comptime and
    # unsafe_pure. Parentheses and lists contain any braces they own; record
    # and tail-block suffixes are disabled by the header's `nb` mode. A braced
    # primary may also follow a unary/binary operator, `return` or `=>`.
    if depth >= MAX_PROJECTION_DEPTH:
        return -1
    want_primary = True
    bare_return = False
    while pos < len(code):
        space = pos
        while pos < len(code) and code[pos].isspace():
            pos += 1
        if bare_return and "\n" in code[space:pos]:
            want_primary = False
            bare_return = False
        if pos >= len(code):
            return -1
        c = code[pos]
        if c in "\"'`":
            close = code.find(c, pos + 1)
            if close < 0:
                return -1
            pos = close + 1
            want_primary = False
            bare_return = False
            continue
        if c.isalpha() or c == "_":
            end = pos + 1
            while end < len(code) and (code[end].isalnum() or code[end] == "_"):
                end += 1
            word = code[pos:end]
            if want_primary and word in ("if", "match"):
                after = branch_expression_end(code, pos, word, depth + 1)
                if after > pos:
                    pos = after
                    want_primary = False
                    bare_return = False
                    continue
            if want_primary and word in ("comptime", "unsafe_pure"):
                brace = skip_space(code, end)
                if brace >= len(code) or code[brace] != "{":
                    return -1
                close = matching_delimiter(code, brace)
                if close >= len(code):
                    return -1
                pos = close + 1
                want_primary = False
                bare_return = False
                continue
            if want_primary and word == "return":
                pos = end
                bare_return = True
                continue
            if want_primary and word == "not":
                pos = end
                bare_return = False
                continue
            pos = end
            want_primary = False
            bare_return = False
            continue
        bare_return = False
        if c in "([":
            close = matching_delimiter(code, pos)
            if close >= len(code):
                return -1
            pos = close + 1
            want_primary = False
            continue
        if c == "{":
            if not want_primary:
                return pos
            close = matching_delimiter(code, pos)
            if close >= len(code):
                return -1
            pos = close + 1
            want_primary = False
            continue
        if code[pos : pos + 2] == "=>":
            pos += 2
            want_primary = True
            continue
        if not want_primary:
            operator = next((op for op in HEADER_BINARY_OPS if code.startswith(op, pos)), None)
            if operator is not None:
                pos += len(operator)
                want_primary = True
                continue
            if c in "?!.":
                pos += 1
                continue
        elif c in "-~":
            pos += 1
            continue
        # A scalar literal or another token accepted as a primary. Invalid
        # input is irrelevant here: every expression scanned came from a
        # successfully parsed checker source or a syntax-valid self-test.
        pos += 1
        want_primary = False
    return -1


def branch_expression_end(code, start, keyword, depth=0):
    """End of an `if`/`match` expression that starts inside a header."""
    if depth >= MAX_PROJECTION_DEPTH:
        return start
    pos = start
    while True:
        brace = body_brace(code, pos + len(keyword), depth)
        if brace < 0:
            return start
        close = matching_delimiter(code, brace)
        if close >= len(code) or keyword != "if":
            return start if close >= len(code) else close + 1
        end = close + 1
        after = skip_space(code, end)
        if not word_at(code, after, "else"):
            return end
        after = skip_space(code, after + len("else"))
        if word_at(code, after, "if"):
            pos = after
            continue
        if after >= len(code) or code[after] != "{":
            return start
        close = matching_delimiter(code, after)
        return start if close >= len(code) else close + 1


def if_arms(expr, code, start):
    """Return (condition-or-None, body) for an if/else-if/else chain."""
    out = []
    pos = start
    while word_at(code, pos, "if"):
        brace = body_brace(code, pos + len("if"))
        if brace < 0:
            return []
        close = matching_delimiter(code, brace)
        if close >= len(code):
            return []
        out.append((expr[pos + len("if") : brace], expr[brace + 1 : close]))
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
        out.append((None, expr[pos + 1 : close]))
        return out
    return []


def match_arrows(code, start, end):
    """Top-level arm arrows inside a match body."""
    return [offset for offset, _ in top_level_tokens(code, ("->",), start, end)]


def match_arm_separator(code, start, end):
    """First top-level comma or expression-ending newline before another arm."""
    for offset in top_level_offsets(code, start, end):
        if code[offset] == ",":
            return offset
        if code[offset] == "\n" and not newline_continues(code, offset, start, end):
            return offset
    return -1


def match_guard(expr, code, start, end):
    """The top-level guard expression of a match pattern, if it has one."""
    for offset in top_level_offsets(code, start, end):
        if word_at(code, offset, "if"):
            before = offset - 1
            while before >= start and code[before].isspace():
                before -= 1
            if before < start or code[before] != ".":
                return expr[offset + len("if") : end].strip()
    return None


def match_arms(expr, code, start):
    """Return (guard-or-None, RHS) for each top-level match arm."""
    brace = body_brace(code, start + len("match"))
    if brace < 0:
        return []
    close = matching_delimiter(code, brace)
    if close >= len(code):
        return []
    arrows = match_arrows(code, brace + 1, close)
    out = []
    pattern_start = brace + 1
    for i, arrow in enumerate(arrows):
        rhs = skip_space(code, arrow + 2, close)
        end = close
        if end == close and i + 1 < len(arrows):
            next_arrow = arrows[i + 1]
            separator = match_arm_separator(code, rhs, next_arrow)
            if separator < 0:
                return []
            end = separator
        body = expr[rhs:end].rstrip()
        if body.endswith(","):
            body = body[:-1].rstrip()
        out.append((match_guard(expr, code, pattern_start, arrow), body))
        pattern_start = end + 1
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
    return split_top_level(expr, ",")


def branch_parts(expr, code=None):
    """(kind, header, guarded arms) when expr is one complete if/match."""
    code = code_mask(expr) if code is None else code
    start = skip_space(code, 0)
    end = len(code)
    while end > start and code[end - 1].isspace():
        end -= 1
    if word_at(code, start, "if"):
        branch_end = branch_expression_end(code, start, "if")
        return ("if", None, if_arms(expr, code, start)) if branch_end == end else None
    if word_at(code, start, "match"):
        branch_end = branch_expression_end(code, start, "match")
        if branch_end != end:
            return None
        brace = body_brace(code, start + len("match"))
        return (
            "match",
            expr[start + len("match") : brace],
            match_arms(expr, code, start),
        )
    return None


def branch_bodies(expr):
    """Possible complete RHS/body expressions, or [] for a non-branch."""
    while True:
        inner = outer_parens(expr)
        if inner is None or len(top_level_parts(inner)) != 1:
            break
        expr = inner
    branch = branch_parts(expr)
    if branch is None:
        return []
    kind, header, arms = branch
    controls = [condition for condition, _ in arms if condition is not None]
    if kind == "match":
        controls.append(header)
    return [] if any(has_unprojected_control(part) for part in controls) else [
        body for _, body in arms
    ]


def top_level_concats(expr):
    """Operands of a top-level `++`, or the unchanged expression."""
    return split_top_level(expr, "++")


def patterns(_lits, expr):
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

    def combine(parts, opaque_empty=False, depth=0):
        combinations = [()]
        for part in parts:
            choices = wordings(part, opaque_empty=opaque_empty, depth=depth + 1)
            if not choices:
                return []
            if len(combinations) * len(choices) > MAX_CANDIDATES:
                return []
            combinations = [
                prefix + choice
                for prefix in combinations
                for choice in choices
            ]
        return combinations

    def wordings(body, opaque_empty=False, depth=0):
        # These are the only expression forms whose contribution to a String
        # is mechanically provable without type or call semantics: grouping,
        # tuples, concatenation and branch selection.
        if depth >= MAX_PROJECTION_DEPTH:
            return []
        inner = outer_parens(body)
        if inner is not None:
            parts = top_level_parts(inner)
            if len(parts) > 1:
                return combine(parts, opaque_empty=True, depth=depth)
            return wordings(inner, opaque_empty=opaque_empty, depth=depth + 1)
        branches = branch_bodies(body)
        if branches:
            out = []
            for branch in branches:
                out += wordings(
                    branch, opaque_empty=opaque_empty, depth=depth + 1
                )
                if len(out) > MAX_CANDIDATES:
                    return []
            return out
        parts = top_level_concats(body)
        if len(parts) > 1:
            return combine(parts, opaque_empty=True, depth=depth)

        if has_unprojected_control(body):
            return []

        found = literals(body)
        if not found:
            return [()]
        code = code_mask(body)
        start = skip_space(code, 0)
        if start < len(body) and body[start] in '"`':
            end, kind, closed = quoted_span(body, start)
            if closed and kind != "char" and not code[end:].strip():
                return [tuple(found)]
        return [()] if opaque_empty else []

    projected = wordings(expr)
    if len(projected) > MAX_CANDIDATES:
        return []
    for chunks in projected:
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


def root_call(expr):
    """A complete bare-name call, or None for a larger/other expression."""
    code = code_mask(expr)
    start = skip_space(code, 0)
    name = re.match(r"[a-z_][A-Za-z0-9_]*", code[start:])
    if name is None:
        return None
    callee = name.group(0)
    open_pos = skip_space(code, start + len(callee))
    if open_pos >= len(code) or code[open_pos] != "(":
        return None
    close = matching_delimiter(code, open_pos)
    if close >= len(code) or code[close + 1 :].strip():
        return None
    try:
        args = scan_args(expr, open_pos + 1)
    except ValueError:
        return None
    return callee, args


# ---- bounded same-file helper projection ---------------------------------
# This is deliberately smaller than Dawn's evaluator. It proves sequential
# straight-line blocks plus if/match fallthrough and reachable `return` values.
# Loops, `with`, transferring match guards, opaque nested control and unsafe
# substitution fail closed. The caps above bound every recursive/product walk.

def block_segments(body):
    """Top-level statements/expressions in one complete braced block."""
    code = code_mask(body)
    start = skip_space(code, 0)
    if start >= len(code) or code[start] != "{":
        return None
    close = matching_delimiter(code, start)
    if close >= len(code) or code[close + 1 :].strip():
        return None
    out = []
    segment = skip_space(code, start + 1, close)
    for offset in top_level_offsets(code, start + 1, close):
        if code[offset] == "\n" and not newline_continues(
            code, offset, start + 1, close
        ):
            part = body[segment:offset].strip()
            if part:
                out.append(part)
            segment = skip_space(code, offset + 1, close)
    part = body[segment:close].strip()
    if part:
        out.append(part)
    return out


def helper_param_is_bound(code, param):
    """Whether a helper parameter name occurs in any binder-capable region."""
    name = re.compile(r"\b%s\b" % re.escape(param))
    if re.search(r"\bfn\s+%s\s*\(" % re.escape(param), code):
        return True
    for binder in re.finditer(r"\b(?:let|var)\b(.*?)(?<![=!<>])=(?!=|>)", code, re.S):
        if name.search(binder.group(1)):
            return True
    for binder in re.finditer(r"\bfor\b(.*?)\bin\b", code, re.S):
        if name.search(binder.group(1)):
            return True
    for binder in re.finditer(r"\bwith\b(.*?)<-", code, re.S):
        if name.search(binder.group(1)):
            return True
    for binder in re.finditer(
        r"\bfn\s+[a-z_][A-Za-z0-9_]*\s*\((.*?)\)", code, re.S
    ):
        if name.search(binder.group(1)):
            return True
    for arrow in re.finditer(r"=>|->", code):
        start = arrow.start() - 1
        depth = 0
        while start >= 0:
            c = code[start]
            if c in ")]}":
                depth += 1
            elif c in "([{":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and c in "\n,":
                break
            start -= 1
        if name.search(code[start + 1 : arrow.start()]):
            return True
    return False


def top_level_assignment(expr):
    """Right side of a top-level assignment token, or None."""
    code = code_mask(expr)
    for pos in top_level_offsets(code):
        if code[pos] == "=":
            prev = code[pos - 1] if pos else ""
            nxt = code[pos + 1] if pos + 1 < len(code) else ""
            if prev not in "=!<>" and nxt not in "=>":
                return expr[pos + 1 :].strip()
    return None


def has_unprojected_control(expr, depth=0):
    """Control transfer nested in a form whose evaluation we do not model."""
    if depth >= MAX_PROJECTION_DEPTH:
        return True
    spans = list(lexical_spans(expr))
    if any(kind not in ("code", "comment") and not closed for kind, _, _, closed in spans):
        return True
    code = code_mask(expr)
    direct = any(
        before < 0 or code[before] != "."
        for match in re.finditer(r"\b(?:return|break|continue)\b", code)
        for before in [match.start() - 1]
    )
    return direct or any(
        has_unprojected_control(inner, depth + 1)
        for inner in interpolation_expressions(expr)
    )


def helper_expr_flow(expr, depth=0):
    """Project (normal values, returned values, may-fallthrough) for an expression.

    Only blocks and complete if/match expressions receive control-flow
    interpretation. Everything else is retained as an opaque value unless it
    contains control transfer that this small projector cannot place safely.
    """
    if depth >= MAX_PROJECTION_DEPTH:
        return None
    expr = expr.strip()
    if not expr:
        return (["()"], [], True)
    inner = outer_parens(expr)
    if inner is not None and len(top_level_parts(inner)) == 1:
        return helper_expr_flow(inner, depth + 1)

    code = code_mask(expr)
    start = skip_space(code, 0)
    end = len(code)
    while end > start and code[end - 1].isspace():
        end -= 1

    if start < end and code[start] == "{":
        close = matching_delimiter(code, start)
        if close == end - 1:
            return helper_block_flow(expr, depth + 1)
    if word_at(code, start, "return"):
        value = expr[skip_space(code, start + len("return"), end) : end].strip()
        if not value:
            return ([], ["()"], False)
        value_flow = helper_expr_flow(value, depth + 1)
        if value_flow is None:
            return None
        values, returns, _ = value_flow
        return ([], returns + values, False)
    if word_at(code, start, "break") or word_at(code, start, "continue"):
        return None
    branch = branch_parts(expr, code)
    if branch is not None:
        kind, header, arms = branch
        if not arms:
            return None
        normal, returned = [], []
        may_fallthrough = False
        if kind == "match":
            header_flow = helper_expr_flow(header, depth + 1)
            if header_flow is None:
                return None
            _, returned, header_may = header_flow
            if not header_may:
                return ([], returned, False)
        has_else = False
        headers_may = True
        for control, body in arms:
            if control is None:
                has_else = True
            else:
                control_flow = helper_expr_flow(control, depth + 1)
                if control_flow is None:
                    return None
                _, control_returns, control_may = control_flow
                # A transferring guard needs pattern-irrefutability proof to
                # decide whether later arms run; this projector has no such
                # proof and keeps the whole match fail-closed.
                if kind == "match" and control_returns:
                    return None
                returned += control_returns
                if not control_may:
                    if kind == "if":
                        headers_may = False
                        break
                    continue
            value = "{" + body + "}" if kind == "if" else body
            flow = helper_expr_flow(value, depth + 1)
            if flow is None:
                return None
            values, returns, may = flow
            normal += values
            returned += returns
            if len(normal) + len(returned) > MAX_CANDIDATES:
                return None
            may_fallthrough = may_fallthrough or may
        if kind == "if" and headers_may and not has_else:
            normal.append("()")
            may_fallthrough = True
        return (normal, returned, may_fallthrough)
    if has_unprojected_control(expr):
        return None
    return ([expr], [], True)


def helper_statement(segment):
    """Classify a top-level block segment and return any evaluated expression."""
    code = code_mask(segment)
    start = skip_space(code, 0)
    if any(word_at(code, start, word) for word in ("with", "while", "for")):
        return ("unsupported", None)
    if word_at(code, start, "fn"):
        return ("declaration", None)
    if word_at(code, start, "let") or word_at(code, start, "var"):
        return ("statement", top_level_assignment(segment))
    if word_at(code, start, "assert"):
        pos = skip_space(code, start + len("assert"))
        return ("statement", segment[pos:].strip())
    assignment = top_level_assignment(segment)
    name = re.match(r"[a-z_][A-Za-z0-9_]*", code[start:])
    if assignment is not None and name is not None:
        lhs_end = skip_space(code, start + len(name.group(0)))
        if lhs_end < len(code) and code[lhs_end] == "=":
            return ("statement", assignment)
    return ("expression", segment)


def helper_block_flow(body, depth=0):
    """Project reachable return values and the normally completed block value."""
    if depth >= MAX_PROJECTION_DEPTH:
        return None
    segments = block_segments(body)
    if segments is None:
        return None
    if not segments:
        return (["()"], [], True)

    returned = []
    for index, segment in enumerate(segments):
        kind, evaluated = helper_statement(segment)
        if kind == "unsupported" or (kind == "statement" and evaluated is None):
            return None
        if kind == "declaration":
            if index == len(segments) - 1:
                return (["()"], returned, True)
            continue
        flow = helper_expr_flow(evaluated, depth + 1)
        if flow is None:
            return None
        normal, returns, may_fallthrough = flow
        returned += returns
        if len(returned) > MAX_CANDIDATES:
            return None
        if not may_fallthrough:
            return ([], returned, False)
        if index == len(segments) - 1:
            if kind == "expression":
                return (normal, returned, True)
            return (["()"], returned, True)
    return (["()"], returned, True)


def helper_param_is_interpolated(body, param):
    """Whether a parameter occurs in interpolation we cannot safely rewrite."""
    wanted = re.compile(r"\b%s\b" % re.escape(param))
    return any(
        kind in ("string", "triple")
        and "$" in body[start:end]
        and wanted.search(body[start:end]) is not None
        for kind, start, end, _ in lexical_spans(body)
    )


def substitute_helper(info, args):
    """Safely substitute positional call arguments into a same-file helper."""
    params = info["params"]
    if len(args) != len(params):
        return None
    if any(re.match(r"\s*[a-z_][A-Za-z0-9_]*\s*:", arg) for arg in args):
        return None
    body = info["body"]
    full_code = code_mask(body)
    for param in params:
        if helper_param_is_bound(full_code, param) or helper_param_is_interpolated(
            body, param
        ):
            return None
    code = code_mask(body)

    replacements = dict(zip(params, args))
    out = []
    last = 0
    for match in IDENT.finditer(code):
        name = match.group(1)
        if name not in replacements:
            continue
        before = match.start() - 1
        while before >= 0 and code[before].isspace():
            before -= 1
        after = match.end()
        while after < len(code) and code[after].isspace():
            after += 1
        if (before >= 0 and code[before] == ".") or (
            after < len(code) and code[after] == ":"
        ):
            continue
        out.append(body[last : match.start()])
        out.append("(" + replacements[name] + ")")
        last = match.end()
    out.append(body[last:])
    return "".join(out)


def expand_helper(expr, fns, seen=()):
    """(known helper, reachable result expressions) for a same-file call."""
    call = root_call(expr)
    if call is None or call[0] not in fns:
        return False, None
    callee, args = call
    if any(has_unprojected_control(arg) for arg in args):
        return True, None
    if callee in seen or len(seen) >= MAX_HELPER_DEPTH:
        return True, None
    body = substitute_helper(fns[callee], args)
    if body is None:
        return True, None
    flow = helper_expr_flow(body)
    if flow is None:
        return True, None
    normal, returned, _ = flow
    results = []
    body_code = code_mask(body)
    for result in returned + normal:
        nested_call = root_call(result)
        if nested_call is not None and nested_call[0] in fns:
            if helper_param_is_bound(body_code, nested_call[0]):
                return True, None
            _, expanded = expand_helper(result, fns, seen + (callee,))
            if expanded is not None:
                results += expanded
            continue
        masked = code_mask(result)
        if any(re.search(r"\b%s\s*\(" % re.escape(name), masked) for name in fns):
            # A helper call nested under an operator/wrapper needs substitution
            # into that outer expression to be sound. This bounded projector
            # only expands a complete root call, so fail closed for this path.
            continue
        results.append(result)
        if len(results) > MAX_CANDIDATES:
            return True, None
    return True, results


def expanded_patterns(expr, fns):
    """(known helper, complete candidate chunks) for a message expression."""
    known, results = expand_helper(expr, fns)
    if not known:
        return False, []
    out = []
    for result in results or []:
        for candidate in patterns(literals(result), result):
            if candidate not in out:
                out.append(candidate)
    return True, out


def scoped_patterns(expr, fns, scope_prefix):
    """Candidate chunks without mistaking a shadowed callee for a module helper."""
    call = root_call(expr)
    if call is not None and call[0] in fns and helper_param_is_bound(
        scope_prefix, call[0]
    ):
        return False, patterns(literals(expr), expr)
    known, helper_pats = expanded_patterns(expr, fns)
    return (known, helper_pats) if known else (False, patterns(literals(expr), expr))


def collect_sites(sources=None):
    sites = []
    if sources is None:
        paths = []
        for pat in SOURCES:
            paths += glob.glob(os.path.join(ROOT, pat))
        sources = [(os.path.relpath(path, ROOT), read(path)) for path in sorted(paths)]
    for rel, text in sources:
        # Immutable local `let x = ...` and same-file `fn f(...) = ...`
        # bodies, so an indirect message expression can be expanded safely.
        fns = {}
        source_code = code_mask(text)
        fn_matches = list(FN.finditer(text))
        let_matches = list(LET.finditer(text))
        call_matches = list(CALL.finditer(text))
        scope_ends = enclosing_block_ends(
            source_code,
            [m.start() for m in let_matches] + [m.start() for m in call_matches],
        )
        for m in fn_matches:
            close = matching_delimiter(source_code, m.end() - 1)
            if close >= len(text):
                continue
            try:
                decls = scan_args(text, m.end(), source_code)
            except ValueError:
                continue
            params = []
            for decl in decls:
                param = re.match(r"\s*([a-z_][A-Za-z0-9_]*)\b", decl)
                if param is not None:
                    params.append(param.group(1))
            eq = text.find("=", close + 1)
            if eq > 0:
                fns[m.group(1)] = {
                    "params": params,
                    "body": block_after(text, eq + 1, source_code),
                }
        lets = []  # (offset, scope-end, name, body), in file order
        for m in let_matches:
            body = block_after(text, m.end(), source_code)
            # `let (msg, hint) = helper(...)` binds both from one expression
            for nm in m.group(1).strip("()").split(","):
                lets.append((m.start(), scope_ends[m.start()], nm.strip(), body))
        fn_starts = [m.start() for m in fn_matches]
        for m in call_matches:
            line = text.count("\n", 0, m.start()) + 1
            try:
                args = scan_args(text, m.end(), source_code)
            except ValueError:
                continue
            if len(args) < 2:
                continue
            expr = args[1]
            # `cerr` inside `cerr`, `cerr_h` or `cerr_o` is the definition or
            # the forward `cerr_o` makes, not a report.
            head = text.rfind("\n", 0, m.start()) + 1
            owner = ""
            for fm in fn_matches:
                if fm.start() >= head:
                    break
                owner = fm.group(1)
            if re.match(r"(pub )?fn cerr", text[head:]):
                owner = "cerr"
            if owner in ("cerr", "cerr_h", "cerr_o"):
                continue
            scope = 0
            for st in fn_starts:
                if st < m.start():
                    scope = st
            known_helper, pats = scoped_patterns(
                expr, fns, source_code[scope : m.start()]
            )
            if not pats and not known_helper:
                # An indirect local message is safe to resolve only when the
                # complete expression is that bare name. A name under an
                # opaque call/member/operator says nothing about its output.
                bodies = []
                bare = re.fullmatch(r"\s*([a-z_][A-Za-z0-9_]*)\s*", code_mask(expr))
                for name in [bare.group(1)] if bare is not None else []:
                    best = None
                    for off, scope_end, nm, body in lets:
                        if nm == name and scope <= off < m.start() < scope_end:
                            best = (off, body)
                    if best is not None:
                        bodies.append(best)
                resolved = []
                for off, body in bodies:
                    _, body_pats = scoped_patterns(
                        body, fns, source_code[scope:off]
                    )
                    resolved += body_pats
                if resolved:
                    pats = resolved
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
    ordered_expr = '"first literal" ++ "second literal"'
    ordered = patterns(literals(ordered_expr), ordered_expr)
    if not site_reached({"pats": ordered}, ["first literal then second literal"]):
        print("FAIL: ordered literal chunks missed their wording", file=sys.stderr)
        return 1
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
        'match kind { "alpha" -> ("alpha message", "alpha hint")\n'
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
    braced_headers = [
        (
            "block condition",
            'if { marker == "block-key" } { "block yes message" } '
            'else { "block no message" }',
            [("block yes message",), ("block no message",)],
        ),
        (
            "block scrutinee",
            'match { "left-key" } {\n  "left-key" -> "block left message"\n'
            '  _ -> "block right message"\n}',
            [("block left message",), ("block right message",)],
        ),
        (
            "comptime condition",
            'if comptime { marker == "comptime-key" } { "comptime yes message" } '
            'else { "comptime no message" }',
            [("comptime yes message",), ("comptime no message",)],
        ),
        (
            "unsafe_pure condition",
            'if unsafe_pure { marker == "unsafe-key" } { "unsafe yes message" } '
            'else { "unsafe no message" }',
            [("unsafe yes message",), ("unsafe no message",)],
        ),
        (
            "binary block operand",
            'if false || { true } { "binary yes message" } '
            'else { "binary no message" }',
            [("binary yes message",), ("binary no message",)],
        ),
        (
            "unary comptime operand",
            'if not comptime { false } { "unary yes message" } '
            'else { "unary no message" }',
            [("unary yes message",), ("unary no message",)],
        ),
        (
            "lambda block body",
            'match x => { "lambda-key" } {\n'
            '  "lambda-key" -> "lambda body message"\n'
            '  _ -> "other lambda message"\n}',
            [("lambda body message",), ("other lambda message",)],
        ),
        (
            "return block operand",
            'if return { true } { "return yes message" } '
            'else { "return no message" }',
            [],
        ),
    ]
    for name, expr, expected in braced_headers:
        if patterns(literals(expr), expr) != expected:
            print("FAIL: " + name + " stole its enclosing body", file=sys.stderr)
            return 1
    for operator in HEADER_BINARY_OPS:
        right = (
            'if left %s { true } { "right operand message" } '
            'else { "right operand fallback" }' % operator
        )
        left = (
            'if { true } %s right { "left operand message" } '
            'else { "left operand fallback" }' % operator
        )
        expected_right = [("right operand message",), ("right operand fallback",)]
        expected_left = [("left operand message",), ("left operand fallback",)]
        if patterns(literals(right), right) != expected_right:
            print("FAIL: binary `%s` lost its braced right operand" % operator, file=sys.stderr)
            return 1
        if patterns(literals(left), left) != expected_left:
            print("FAIL: binary `%s` lost its braced left operand" % operator, file=sys.stderr)
            return 1
    postfix_headers = [
        'if { value }? { "propagate message" } else { "propagate fallback" }',
        'if { value }! { "unwrap message" } else { "unwrap fallback" }',
        'if { value }[0] { "index message" } else { "index fallback" }',
        'if { value }.member { "member message" } else { "member fallback" }',
        'if { value }(arg) { "call message" } else { "call fallback" }',
        'if { value }\n  .member { "vertical member message" } '
        'else { "vertical member fallback" }',
    ]
    for expr in postfix_headers:
        pats = patterns(literals(expr), expr)
        if len(pats) != 2 or any(len(pat) != 1 for pat in pats):
            print("FAIL: a postfix suffix stole its enclosing body", file=sys.stderr)
            return 1
    reset_delimiters = (
        'if helper(Point { x: "record-key" }, values { "tail-key" }, '
        '[{ "list-key" }]) { "delimiter yes message" } '
        'else { "delimiter no message" }'
    )
    if patterns(literals(reset_delimiters), reset_delimiters) != [
        ("delimiter yes message",),
        ("delimiter no message",),
    ]:
        print("FAIL: a reset delimiter exposed its inner braces", file=sys.stderr)
        return 1
    nested_braced_headers = (
        'if if { true } { true } else { false } { "nested header yes" } '
        'else { "nested header no" }'
    )
    if patterns(literals(nested_braced_headers), nested_braced_headers) != [
        ("nested header yes",),
        ("nested header no",),
    ]:
        print("FAIL: a braced primary inside a nested header escaped", file=sys.stderr)
        return 1
    lexical_headers = [
        (
            "raw condition",
            'if marker == `{` { "raw yes message" } else { "raw no message" }',
            [("raw yes message",), ("raw no message",)],
        ),
        (
            "raw match",
            'match kind { `left{key` -> `raw left message`\n'
            '  _ -> `raw other message`\n}',
            [("raw left message",), ("raw other message",)],
        ),
        (
            "triple-string condition",
            'if marker == """triple " quote { }""" { "triple yes message" } '
            'else { "triple no message" }',
            [("triple yes message",), ("triple no message",)],
        ),
        (
            "triple-string match",
            'match kind { """alpha " {""" -> """triple alpha message"""\n'
            '  _ -> """triple other message"""\n}',
            [("triple alpha message",), ("triple other message",)],
        ),
        (
            "interpolated-string condition",
            'if marker == "before ${if flag { `}` } else { `{` }} after" { '
            '"interpolation yes message" } else { "interpolation no message" }',
            [("interpolation yes message",), ("interpolation no message",)],
        ),
        (
            "hash in interpolation",
            'if marker == "before ${x # } after" { "hash yes message" } '
            'else { "hash no message" }',
            [("hash yes message",), ("hash no message",)],
        ),
    ]
    for name, expr, expected in lexical_headers:
        if patterns(literals(expr), expr) != expected:
            print("FAIL: " + name + " changed branch structure", file=sys.stderr)
            return 1
    triple_chunks = '"""\n  before ${value}\n  after\n  """'
    if literals(triple_chunks) != ["before ", "\nafter"]:
        print("FAIL: triple-string fixed chunks did not match the lexer", file=sys.stderr)
        return 1
    if literals('`raw ${value} { braces }`') != ["raw ${value} { braces }"]:
        print("FAIL: a raw string was treated as interpolated", file=sys.stderr)
        return 1
    if literals('"before $name after ${call(`}`)} done"') != [
        "before ",
        " after ",
        " done",
    ]:
        print("FAIL: interpolated fixed chunks were not separated", file=sys.stderr)
        return 1
    if literals('"before fixed ${x # } after fixed"') != [
        "before fixed ",
        " after fixed",
    ]:
        print("FAIL: `#` inside interpolation hid its closing brace", file=sys.stderr)
        return 1
    compositional = [
        (
            "conditional suffix",
            'if flag { "left prefix" } else { "right prefix" } ++ " shared suffix"',
            [
                ("left prefix", " shared suffix"),
                ("right prefix", " shared suffix"),
            ],
        ),
        (
            "conditional prefix",
            '"shared prefix " ++ if flag { "left tail" } else { "right tail" }',
            [("shared prefix ", "left tail"), ("shared prefix ", "right tail")],
        ),
        (
            "match suffix",
            'match kind { A -> "match left"\n_ -> "match right" } '
            '++ " match suffix"',
            [("match left", " match suffix"), ("match right", " match suffix")],
        ),
        (
            "tuple element branch",
            '("message", "hint prefix " ++ if flag { "hint left" } '
            'else { "hint right" })',
            [
                ("message", "hint prefix ", "hint left"),
                ("message", "hint prefix ", "hint right"),
            ],
        ),
    ]
    for name, expr, expected in compositional:
        actual = patterns(literals(expr), expr)
        if actual != expected:
            print("FAIL: " + name + " lost a feasible wording", file=sys.stderr)
            return 1
        partial = "".join(expected[0][:-1])
        if partial and site_reached({"pats": actual}, [partial]):
            print("FAIL: " + name + " accepted a partial wording", file=sys.stderr)
            return 1
    conditional_suffix = patterns(
        literals(compositional[0][1]), compositional[0][1]
    )
    if site_reached({"pats": conditional_suffix}, ["left prefix"]):
        print("FAIL: a branch-only diagnostic ignored its shared suffix", file=sys.stderr)
        return 1
    direct_transfers = [
        (
            "if condition",
            'if return "caller returned" { "unreachable yes diagnostic" } '
            'else { "unreachable no diagnostic" }',
        ),
        (
            "match scrutinee",
            'match return "caller returned" {\n_ -> "unreachable arm diagnostic"\n}',
        ),
        (
            "match guard",
            'match value {\n_ if return "caller returned" -> "unreachable guarded"\n'
            '_ -> "unprovable later diagnostic"\n}',
        ),
        ("concat", '"unreachable concat prefix " ++ return "caller returned"'),
        ("tuple", '("unreachable tuple message", return "caller returned")'),
        (
            "opaque wrapper",
            '"unreachable opaque prefix " ++ wrap(return "caller returned")',
        ),
        (
            "interpolation",
            '"unreachable interpolation ${return `caller returned`}"',
        ),
    ]
    for name, expr in direct_transfers:
        if patterns(literals(expr), expr):
            print("FAIL: a direct " + name + " transfer reached cerr", file=sys.stderr)
            return 1
    arm_transfer = (
        'if flag { "unreachable branch prefix " ++ return value } '
        'else { "real branch diagnostic" }'
    )
    if patterns(literals(arm_transfer), arm_transfer) != [
        ("real branch diagnostic",)
    ]:
        print("FAIL: a transferring branch hid its feasible sibling", file=sys.stderr)
        return 1
    opaque_branches = [
        (
            "comptime branch",
            'comptime { "comptime prefix " ++ if flag { "comptime left" } '
            'else { "comptime right" } }',
        ),
        (
            "unsafe_pure branch",
            'unsafe_pure { if flag { "unsafe left" } else { "unsafe right" } '
            '++ " unsafe suffix" }',
        ),
        (
            "block branch",
            '{ "block prefix " ++ if flag { "block left" } '
            'else { "block right" } }',
        ),
        (
            "call argument branch",
            'identity("call prefix ", if flag { "call left" } else { "call right" })',
        ),
        (
            "postfix member branch",
            '(if flag { "member left" } else { "member right" })'
            '.append(" member suffix")',
        ),
    ]
    for name, expr in opaque_branches:
        actual = patterns(literals(expr), expr)
        if actual:
            print("FAIL: " + name + " produced an unprovable partial", file=sys.stderr)
            return 1
    opaque_literals = [
        '"not necessarily output literal".replace("not", "yes")',
        '"input literal long" |> transform',
        'ignore("not emitted stable literal")',
    ]
    for expr in opaque_literals:
        if patterns(literals(expr), expr):
            print("FAIL: an opaque expression exposed an argument literal", file=sys.stderr)
            return 1
    binding_pipeline = (
        "fn local_messages(cx: Cx, lo: Int, hi: Int) -> Cx = {\n"
        '  let msg = "inner fixed diagnostic"\n'
        "  let cx1 = cerr(cx, opaque(msg), lo, hi)\n"
        "  cerr(cx1, msg, lo, hi)\n"
        "}\n"
    )
    binding_sites = collect_sites([("selftest/local_messages.dawn", binding_pipeline)])
    if len(binding_sites) != 2 or [site["pats"] for site in binding_sites] != [
        [],
        [("inner fixed diagnostic",)],
    ]:
        print("FAIL: local binding fallback crossed an opaque wrapper", file=sys.stderr)
        return 1
    resolution_pipeline = (
        'fn helper(msg: String) -> String = "module helper " ++ msg\n'
        "fn scoped(cx: Cx, lo: Int, hi: Int) -> Cx = {\n"
        '  let msg = "actual outer diagnostic"\n'
        "  if flag {\n"
        '    let msg = "unrelated nested diagnostic"\n'
        "    use(msg)\n"
        "  }\n"
        "  cerr(cx, msg, lo, hi)\n"
        "}\n"
        "fn parameter_shadow(cx: Cx, helper: fn(String) -> String, "
        "lo: Int, hi: Int) -> Cx =\n"
        '  cerr(cx, helper("caller argument"), lo, hi)\n'
        "fn indirect_shadow(cx: Cx, helper: fn(String) -> String, "
        "lo: Int, hi: Int) -> Cx = {\n"
        '  let msg = helper("caller argument")\n'
        "  cerr(cx, msg, lo, hi)\n"
        "}\n"
        "fn local_shadow(cx: Cx, lo: Int, hi: Int) -> Cx = {\n"
        "  let helper = formatter\n"
        '  let msg = helper("caller argument")\n'
        "  cerr(cx, msg, lo, hi)\n"
        "}\n"
        "fn mutable_message(cx: Cx, lo: Int, hi: Int) -> Cx = {\n"
        '  var msg = "stale mutable diagnostic"\n'
        '  msg = "actual mutable diagnostic"\n'
        "  cerr(cx, msg, lo, hi)\n"
        "}\n"
    )
    resolution_sites = collect_sites(
        [("selftest/local_resolution.dawn", resolution_pipeline)]
    )
    if len(resolution_sites) != 5 or [site["pats"] for site in resolution_sites] != [
        [("actual outer diagnostic",)],
        [],
        [],
        [],
        [],
    ]:
        print("FAIL: local/helper binding resolution escaped its scope", file=sys.stderr)
        return 1
    postfix_rhs = [
        '(if flag { "left nested" } else { "right nested" })'
        '.append("actual member suffix")',
        '(if flag { "left nested" } else { "right nested" })("call data")',
        '(if flag { "left nested" } else { "right nested" })?',
        '(if flag { "left nested" } else { "right nested" })!',
        '(if flag { "left nested" } else { "right nested" })[0]',
        '(if flag { "left nested" } else { "right nested" }) + "add data"',
    ]
    for rhs in postfix_rhs:
        expr = 'match kind { A -> ' + rhs + '\n_ -> "other postfix message"\n}'
        if patterns(literals(expr), expr) != [("other postfix message",)]:
            print("FAIL: a grouped match RHS lost its opaque suffix", file=sys.stderr)
            return 1
    many_branches = "(" + ", ".join(
        'if f%d { "left candidate %d" } else { "right candidate %d" }'
        % (index, index, index)
        for index in range(7)
    ) + ")"
    if patterns(literals(many_branches), many_branches):
        print("FAIL: Cartesian projection exceeded its fail-closed cap", file=sys.stderr)
        return 1
    deep = "(" * (MAX_PROJECTION_DEPTH + 1) + '"deep diagnostic message"' + ")" * (
        MAX_PROJECTION_DEPTH + 1
    )
    if patterns(literals(deep), deep):
        print("FAIL: wording projection exceeded its recursion cap", file=sys.stderr)
        return 1
    nested_string = '"leaf diagnostic message"'
    for _ in range(MAX_PROJECTION_DEPTH + 1):
        nested_string = '"prefix ${' + nested_string + '}"'
    if patterns(literals(nested_string), nested_string):
        print("FAIL: lexical projection exceeded its recursion cap", file=sys.stderr)
        return 1
    very_deep_string = '"leaf diagnostic message"'
    for _ in range(600):
        very_deep_string = '"prefix ${' + very_deep_string + '}"'
    try:
        code_mask(very_deep_string)
    except RecursionError:
        print("FAIL: lexical recursion cap raised RecursionError", file=sys.stderr)
        return 1
    concat_rhs = (
        'match kind { A -> (if flag { "left nested" } '
        'else { "right nested" }) ++ "actual concat suffix"\n'
        '_ -> "other concat message"\n}'
    )
    if patterns(literals(concat_rhs), concat_rhs) != [
        ("left nested", "actual concat suffix"),
        ("right nested", "actual concat suffix"),
        ("other concat message",),
    ]:
        print("FAIL: a grouped match RHS lost its concat suffix", file=sys.stderr)
        return 1
    following_patterns = [
        '(B, C)',
        'Some(B)',
        'Point { x: B, y: C }',
        '"control-a"\n  | "control-b"',
        '(\n  B,\n  C\n)',
    ]
    for following in following_patterns:
        separator = ", " if "\n" not in following else "\n"
        expr = (
            'match kind { A -> "first preserved message"'
            + separator + following + ' -> dynamic\n}'
        )
        if patterns(literals(expr), expr) != [("first preserved message",)]:
            print("FAIL: a following match pattern consumed the prior RHS", file=sys.stderr)
            return 1
    continued_arms = [
        (
            'if flag { "continued yes" }\nelse { "continued no" }',
            [("continued yes",), ("continued no",), ("following arm message",)],
        ),
        (
            '"continued prefix " ++\n  "continued suffix"',
            [("continued prefix ", "continued suffix"), ("following arm message",)],
        ),
        (
            '"leading prefix "\n  ++ "leading suffix"',
            [("leading prefix ", "leading suffix"), ("following arm message",)],
        ),
        (
            'value\n  .append("opaque member data")',
            [("following arm message",)],
        ),
    ]
    for rhs, expected in continued_arms:
        expr = (
            'match kind { A -> ' + rhs + '\nB -> "following arm message"\n}'
        )
        if patterns(literals(expr), expr) != expected:
            print("FAIL: a continued match RHS ended at its newline", file=sys.stderr)
            return 1
    helper_info = {
        "propagate_msg": {
            "params": ["cx", "on", "want", "got"],
            "body": (
                'if in_control_arm(cx) { "`?` on " ++ on ++ '
                '" requires the block this arm answers to be " ++ want ++ '
                '", but it is " ++ got } else { "`?` on " ++ on ++ '
                '" requires the function to return " ++ want ++ '
                '", but it returns " ++ got }'
            ),
        }
    }
    helper_call = (
        'propagate_msg(cx, "an Option", "Option[...]", '
        'ty_show(cx.adts, sig_ret))'
    )
    known, helper_pats = expanded_patterns(helper_call, helper_info)
    expected_helper = [
        (
            "`?` on ",
            "an Option",
            " requires the block this arm answers to be ",
            "Option[...]",
            ", but it is ",
        ),
        (
            "`?` on ",
            "an Option",
            " requires the function to return ",
            "Option[...]",
            ", but it returns ",
        ),
    ]
    if not known or helper_pats != expected_helper:
        print("FAIL: a same-file helper lost its substituted arguments", file=sys.stderr)
        return 1
    helper_site = {"pats": helper_pats}
    if site_reached(helper_site, ["an Option Option[...]"]):
        print("FAIL: helper arguments alone reached the helper site", file=sys.stderr)
        return 1
    if site_reached(helper_site, ["`?` on an Option"]):
        print("FAIL: a helper prefix alone reached the helper site", file=sys.stderr)
        return 1
    if not site_reached(
        helper_site,
        ["`?` on an Option requires the function to return Option[...], but it returns Int"],
    ):
        print("FAIL: a complete substituted helper wording missed", file=sys.stderr)
        return 1
    transfer_args = [
        'choose(flag, return "caller returned")',
        'choose(return "caller returned", "normal diagnostic")',
        'choose(flag, "unreachable prefix " ++ return "caller returned")',
        'choose(flag, (return "caller returned", "tuple data"))',
        (
            'choose(flag, if inner { return "caller returned" } '
            'else { "normal diagnostic" })'
        ),
        'choose(flag, wrap(return "caller returned"))',
        'choose(flag, "prefix ${return `caller returned`}")',
    ]
    choose_info = {
        "choose": {
            "params": ["flag", "message"],
            "body": 'if flag { message } else { "fallback diagnostic" }',
        }
    }
    for call in transfer_args:
        known, transfer_pats = expanded_patterns(call, choose_info)
        if not known or transfer_pats:
            print("FAIL: helper expansion ignored caller-side transfer", file=sys.stderr)
            return 1
    propagate_sites = [
        site for site in collect_sites() if site["expr"].startswith("propagate_msg(")
    ]
    result_args = {"an Option": "a Result", "Option[...]": "Result[...]"}
    result_helper = [
        tuple(result_args.get(chunk, chunk) for chunk in candidate)
        for candidate in expected_helper
    ]
    if len(propagate_sites) != 3 or [site["pats"] for site in propagate_sites] != [
        expected_helper,
        result_helper,
        result_helper,
    ]:
        print("FAIL: propagate_msg call sites bypassed helper expansion", file=sys.stderr)
        return 1
    named_arg_sites = [
        site for site in collect_sites() if site["expr"] == "named_arg_msg(cx, target)"
    ]
    if len(named_arg_sites) != 1 or named_arg_sites[0]["pats"] != [
        ("`", ".", "` is a Java member; Java methods carry no parameter names"),
        (
            "this callee is a function value, and a function type carries no "
            "parameter names",
        ),
    ]:
        print("FAIL: named_arg_msg lost a reachable return or tail", file=sys.stderr)
        return 1
    shadow_info = {
        "shadowed": {
            "params": ["target", "name"],
            "body": (
                'match target {\n  name -> "bound value is " ++ name\n'
                '  _ -> "other bound value"\n}'
            ),
        }
    }
    known, shadowed = expand_helper(
        'shadowed(actual, "call argument")', shadow_info
    )
    if not known or shadowed is not None:
        print("FAIL: a match binder was substituted as a helper parameter", file=sys.stderr)
        return 1
    for binder in ("let", "var"):
        known, shadowed = expand_helper(
            binder + '_shadow("call argument")',
            {
                binder + "_shadow": {
                    "params": ["name"],
                    "body": (
                        "{ " + binder + " name = compute()\n"
                        '  "bound value is " ++ name\n}'
                    ),
                }
            },
        )
        if not known or shadowed is not None:
            print("FAIL: a prior " + binder + " shadow escaped helper checks", file=sys.stderr)
            return 1
    binder_regions = [
        "let (name, rest) = pair",
        "let Point { x: name } = point",
        "for [name, ..rest] in rows { name }",
        "with name <- acquire()\nname",
        "name => name",
        "(name, rest) => name",
    ]
    if any(not helper_param_is_bound(code, "name") for code in binder_regions):
        print("FAIL: a destructuring helper binder escaped shadow detection", file=sys.stderr)
        return 1
    known, interpolated = expand_helper(
        'interpolated("call argument")',
        {"interpolated": {"params": ["name"], "body": '"value: $name"'}},
    )
    if not known or interpolated is not None:
        print("FAIL: an interpolated helper parameter was unsafely substituted", file=sys.stderr)
        return 1
    known, with_body = expand_helper(
        'with_helper("call argument")',
        {
            "with_helper": {
                "params": ["name"],
                "body": (
                    "{ with resource <- handler()\n"
                    '  "handler-body prefix " ++ name\n}'
                ),
            }
        },
    )
    if not known or with_body is not None:
        print("FAIL: a helper tail captured by `with` was treated as its result", file=sys.stderr)
        return 1
    for name, body in (
        ("while", '{ while flag { work() }\n  "loop tail message"\n}'),
        ("for", '{ for item in items { work(item) }\n  "loop tail message"\n}'),
    ):
        known, results = expand_helper(
            name + "_helper()",
            {name + "_helper": {"params": [], "body": body}},
        )
        if not known or results is not None:
            print("FAIL: a " + name + " helper was not fail-closed", file=sys.stderr)
            return 1
    return_info = {
        "return_helper": {
            "params": ["name"],
            "body": (
                '{ return "actual returned message"\n'
                '  "unreachable prefix " ++ name\n}'
            ),
        }
    }
    known, return_pats = expanded_patterns(
        'return_helper("CALL-ARG-FIXED")', return_info
    )
    if not known or return_pats != [("actual returned message",)]:
        print("FAIL: an unconditional return did not stop the helper CFG", file=sys.stderr)
        return 1
    if site_reached(
        {"pats": return_pats}, ["unreachable prefix CALL-ARG-FIXED"]
    ):
        print("FAIL: an unreachable lexical tail reached a helper site", file=sys.stderr)
        return 1
    for name, body in (
        (
            "condition_return",
            'if return "condition returned message" { "unreachable yes message" } '
            'else { "unreachable no message" }',
        ),
        (
            "scrutinee_return",
            'match return "scrutinee returned message" {\n'
            '  _ -> "unreachable match arm"\n}',
        ),
    ):
        known, control_pats = expanded_patterns(
            name + "()", {name: {"params": [], "body": body}}
        )
        expected = [
            (
                "condition returned message"
                if name == "condition_return"
                else "scrutinee returned message",
            )
        ]
        if not known or control_pats != expected:
            print("FAIL: a branch header return did not suppress its bodies", file=sys.stderr)
            return 1
    guarded_info = {
        "guarded_return": {
            "params": [],
            "body": (
                'match value {\n'
                '  _ if return "guard returned message" -> "unreachable guarded arm"\n'
                '  _ -> "unprovable later arm"\n'
                '}'
            ),
        }
    }
    known, guarded_pats = expanded_patterns("guarded_return()", guarded_info)
    if not known or guarded_pats:
        print("FAIL: a transferring match guard was not fail-closed", file=sys.stderr)
        return 1
    nested_return_info = {
        "nested_return": {
            "params": [],
            "body": (
                'return "unreachable outer prefix " ++ '
                'wrap(return "nested returned message")'
            ),
        }
    }
    known, nested_return_pats = expanded_patterns(
        "nested_return()", nested_return_info
    )
    if not known or nested_return_pats:
        print("FAIL: nested control leaked a partial outer return", file=sys.stderr)
        return 1
    terminal_branch_info = {
        "terminal_branches": {
            "params": [],
            "body": (
                '{ if flag { return "first returned message" }\n'
                '  else { return "second returned message" }\n'
                '  "unreachable branch tail"\n}'
            ),
        }
    }
    known, terminal_pats = expanded_patterns(
        "terminal_branches()", terminal_branch_info
    )
    if not known or terminal_pats != [
        ("first returned message",),
        ("second returned message",),
    ]:
        print("FAIL: terminal branch returns did not suppress the tail", file=sys.stderr)
        return 1
    conditional_info = {
        "conditional_helper": {
            "params": ["name"],
            "body": (
                '{ if flag { return "early message for " ++ name }\n'
                '  "fallthrough message for " ++ name\n}'
            ),
        }
    }
    known, conditional_pats = expanded_patterns(
        'conditional_helper("the call")', conditional_info
    )
    if not known or conditional_pats != [
        ("early message for ", "the call"),
        ("fallthrough message for ", "the call"),
    ]:
        print("FAIL: conditional returns and the reachable tail were not unioned", file=sys.stderr)
        return 1
    nested_info = {
        "outer_helper": {
            "params": ["name"],
            "body": (
                '{ match mode {\n'
                '    Java -> return inner_helper(name)\n'
                '    _ -> ()\n'
                '  }\n'
                '  "ordinary outer message for " ++ name\n}'
            ),
        },
        "inner_helper": {
            "params": ["name"],
            "body": '"nested helper message for " ++ name',
        },
    }
    known, nested_pats = expanded_patterns(
        'outer_helper("the target")', nested_info
    )
    if not known or nested_pats != [
        ("nested helper message for ", "the target"),
        ("ordinary outer message for ", "the target"),
    ]:
        print("FAIL: a reachable returned helper was not expanded", file=sys.stderr)
        return 1
    shadowed_nested_info = {
        "inner": {"params": [], "body": '"module inner diagnostic"'},
        "outer_fn": {
            "params": [],
            "body": (
                '{ fn inner() -> String = "local inner diagnostic"\n'
                "  inner()\n}"
            ),
        },
        "outer_let": {
            "params": [],
            "body": '{ let inner = formatter\n  inner()\n}',
        },
    }
    for outer in ("outer_fn", "outer_let"):
        known, shadowed_pats = expanded_patterns(
            "%s()" % outer, shadowed_nested_info
        )
        if not known or shadowed_pats:
            print(
                "FAIL: a nested local callee was resolved as a module helper",
                file=sys.stderr,
            )
            return 1
    helper_chain = {
        "depth_%d" % index: {
            "params": [],
            "body": "depth_%d()" % (index + 1),
        }
        for index in range(MAX_HELPER_DEPTH + 1)
    }
    helper_chain["depth_%d" % (MAX_HELPER_DEPTH + 1)] = {
        "params": [],
        "body": '"too-deep helper message"',
    }
    known, deep_helper_pats = expanded_patterns("depth_0()", helper_chain)
    if not known or deep_helper_pats:
        print("FAIL: helper expansion exceeded its recursion cap", file=sys.stderr)
        return 1
    newline_else = (
        '{ let value = compute()\n  if flag { "newline yes message" }\n'
        '  else { "newline no message" }\n}'
    )
    newline_segments = block_segments(newline_else)
    newline_tail = newline_segments[-1] if newline_segments else None
    if newline_tail is None or patterns(literals(newline_tail), newline_tail) != [
        ("newline yes message",),
        ("newline no message",),
    ]:
        print("FAIL: newline `else` was split from a helper tail", file=sys.stderr)
        return 1
    binding_source = (
        'let msg = if flag { "binding left message" } '
        'else { "binding right message" }\n'
        'cerr_h(cx, msg, lo, hi, "binding hint")\n'
    )
    binding_body = block_after(binding_source, binding_source.index("=") + 1)
    if "cerr_h" in binding_body or patterns(literals(binding_body), binding_body) != [
        ("binding left message",),
        ("binding right message",),
    ]:
        print("FAIL: a diagnostic call was absorbed into its message binding", file=sys.stderr)
        return 1
    for name, middle in (
        ("named continuation", "  cx.name ++\n"),
        ("commented continuation", "  # keep joining\n  cx.name ++\n"),
    ):
        binding_source = (
            'let msg = "prefix diagnostic " ++\n'
            + middle
            + '  "suffix diagnostic"\n'
            'cerr_h(cx, msg, lo, hi, "binding hint")\n'
        )
        binding_body = block_after(binding_source, binding_source.index("=") + 1)
        if "cerr_h" in binding_body or patterns(literals(binding_body), binding_body) != [
            ("prefix diagnostic ", "suffix diagnostic"),
        ]:
            print("FAIL: " + name + " was truncated from a binding", file=sys.stderr)
            return 1
    following_statement = (
        'let msg = "complete prefix " ++ "complete suffix"\n'
        'ignore("not emitted statement data")\n'
        'cerr(cx, msg, lo, hi)\n'
    )
    following_body = block_after(
        following_statement, following_statement.index("=") + 1
    )
    if "ignore" in following_body or patterns(literals(following_body), following_body) != [
        ("complete prefix ", "complete suffix"),
    ]:
        print("FAIL: a following expression statement entered a binding", file=sys.stderr)
        return 1
    negative_statement = (
        'let msg = "negative prefix " ++ "negative suffix"\n'
        '-work()\n'
        'cerr(cx, msg, lo, hi)\n'
    )
    negative_body = block_after(
        negative_statement, negative_statement.index("=") + 1
    )
    if "work" in negative_body or patterns(literals(negative_body), negative_body) != [
        ("negative prefix ", "negative suffix"),
    ]:
        print("FAIL: a leading unary minus continued a binding", file=sys.stderr)
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

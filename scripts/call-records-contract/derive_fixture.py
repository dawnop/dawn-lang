#!/usr/bin/env python3
"""Derive the compiler-written variant of packages/tileir/src/dev.dawn.

The hand-written variant brackets every recorded function with `called(..)`,
`called_bare(..)` and every closure it runs with `user_body(..)`. The derived
variant removes those wrappers and declares `calls(..)` on `Dev` instead, so
the compiler writes the same brackets. Both are compiled against one kernel
corpus and their recorded call tables compared (run.py).

The derivation is textual and exact: each wrapper is found by balanced
parentheses (strings and comments skipped), never by a line pattern, and the
script refuses anything it does not recognize.

    derive_fixture.py --count dev.dawn            # the wrapper census
    derive_fixture.py dev.dawn out/dev.dawn       # write the derived file
"""
import re
import sys

WRAPPERS = ("called_bare", "called_at", "called", "user_body")
CALLS_CLAUSE = ("pub effect Dev calls(enter = t_call_enter, exit = t_call_exit, "
                "body_enter = t_body_enter, body_exit = t_body_exit) {")


def code_mask(src):
    """True for characters outside comments and string literals."""
    mask = [True] * len(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "#":
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                mask[k] = False
            i = j
        elif c == '"':
            j = i + 1
            depth = 0
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "$" and src[j + 1:j + 2] == "{":
                    depth += 1
                    j += 2
                    continue
                if depth and src[j] == "}":
                    depth -= 1
                elif depth == 0 and src[j] == '"':
                    break
                j += 1
            for k in range(i, min(j + 1, n)):
                mask[k] = False
            i = j + 1
        else:
            i += 1
    return mask


def match_paren(src, mask, open_at):
    depth = 0
    for k in range(open_at, len(src)):
        if not mask[k]:
            continue
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                return k
    raise SystemExit("unbalanced parenthesis at offset %d" % open_at)


def split_args(text, mask_off, src_mask):
    """Top-level comma split of text (a slice of src starting at mask_off)."""
    out, depth, cur = [], 0, 0
    for k, c in enumerate(text):
        if not src_mask[mask_off + k]:
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(text[cur:k])
            cur = k + 1
    out.append(text[cur:])
    return out


SITE = re.compile(r"(?<![A-Za-z0-9_])(called_bare|called|user_body)\(")


def sites(src):
    mask = code_mask(src)
    found = []
    for m in SITE.finditer(src):
        if not mask[m.start()]:
            continue
        # a definition is `fn called[...](`, never `called(`; guard anyway
        before = src[max(0, m.start() - 3):m.start()]
        if before.endswith("fn "):
            continue
        found.append((m.group(1), m.start(), m.end() - 1))
    return found, mask


def census(src):
    found, _ = sites(src)
    out = {"called": 0, "called_bare": 0, "user_body": 0}
    for name, _, _ in found:
        out[name] += 1
    return out


def unwrap_one(src):
    found, mask = sites(src)
    if not found:
        return None
    name, start, open_at = found[0]
    close = match_paren(src, mask, open_at)
    inner = src[open_at + 1:close]
    args = split_args(inner, open_at + 1, mask)
    if name == "called":
        if len(args) != 3:
            raise SystemExit("called( with %d args at %d" % (len(args), start))
        fn = args[2].strip()
    elif name == "called_bare":
        if len(args) != 2:
            raise SystemExit("called_bare( with %d args at %d" % (len(args), start))
        fn = args[1].strip()
    else:
        if len(args) != 1:
            raise SystemExit("user_body( with %d args at %d" % (len(args), start))
        fn = args[0].strip()
    if fn.startswith("() =>"):
        body = fn[len("() =>"):].strip()
        repl = body if body.startswith("{") else "(" + body + ")"
    elif re.fullmatch(r"[a-z_][A-Za-z0-9_]*", fn):
        repl = fn + "()"
    else:
        raise SystemExit("unrecognized wrapper argument %r at %d" % (fn, start))
    return src[:start] + repl + src[close + 1:]


DEFS = re.compile(
    r"# `body` bracketed by the two call marks.*?\n(?=## Whether `name` is one of the dialect's floating point formats)",
    re.S)


def derive(src):
    if src.count("pub effect Dev {") != 1:
        raise SystemExit("dev.dawn: expected exactly one `pub effect Dev {`")
    src = src.replace("pub effect Dev {", CALLS_CLAUSE, 1)
    m = DEFS.search(src)
    if not m:
        raise SystemExit("dev.dawn: the wrapper definitions were not found")
    src = src[:m.start()] + src[m.end():]
    n = 0
    while True:
        nxt = unwrap_one(src)
        if nxt is None:
            break
        src = nxt
        n += 1
    return src, n


def main(argv):
    if len(argv) == 3 and argv[1] == "--count":
        c = census(open(argv[2], encoding="utf-8").read())
        print("called %d called_bare %d user_body %d total %d" % (c["called"], c["called_bare"], c["user_body"], sum(c.values())))
        return 0
    if len(argv) != 3:
        print(__doc__)
        return 2
    src = open(argv[1], encoding="utf-8").read()
    out, n = derive(src)
    open(argv[2], "w", encoding="utf-8").write(out)
    print("unwrapped %d sites" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

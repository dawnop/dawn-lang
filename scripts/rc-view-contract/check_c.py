#!/usr/bin/env python3
"""The structural half of the view contract: what the emitted C says.

    check_c.py <emitted.c> <function> <rule>

`<function>` is the emitted symbol of one function; the rule is read off its
body, the text from the signature line to the closing brace in column 0.

  bare      no dup, no drop and no own-slot: the function only reads
  leaf_for  no drop and no own-slot, and no more than two dups -- the two
            references handed back to the caller (the tail and the leaf)
  counted   at least one dup: a projection of an owned parameter is still copied

Exit 0 when the rule holds, 1 when it does not (the reason on stdout), 2 when
the function is not in the file, which is a broken contract, not a red.
"""

import re
import sys


def body_of(text: str, symbol: str):
    sig = re.search(r"^[^\n;{}]*\b" + re.escape(symbol) + r"\([^\n]*\) \{$", text, re.M)
    if not sig:
        return None
    end = text.find("\n}\n", sig.end())
    return text[sig.start(): end + 3 if end >= 0 else len(text)]


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    path, symbol, rule = sys.argv[1:]
    body = body_of(open(path).read(), symbol)
    if body is None:
        print(f"{symbol} is not in {path}")
        return 2
    dups = body.count("dawn_dup(")
    drops = body.count("dawn_drop(")
    own = body.count("dawn_own")
    if rule == "bare":
        ok = dups == 0 and drops == 0 and own == 0
    elif rule == "leaf_for":
        ok = drops == 0 and own == 0 and dups <= 2
    elif rule == "counted":
        ok = dups > 0
    else:
        print(f"unknown rule {rule}")
        return 2
    if not ok:
        print(f"{symbol}: {dups} dup(s), {drops} drop(s), {own} own-slot use(s) fails rule '{rule}'")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

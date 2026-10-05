#!/usr/bin/env python3
"""Read a `.dawnmap`, the C side table `dawn __emitc --map` writes.

    from dawnmap import load
    m = load(path)      # {"lines", "units", "srcs", "fns", "calls"}

The format is docs/source-span-map-design.md section 12.2. This reader is the
one the checker beside it uses and the one the three-backend page (M7) is
meant to import, so that there is one parser of the format and not two. It
refuses a version it does not know and skips a row kind it does not know,
which is the format's compatibility rule: a new row kind does not bump the
version, a changed meaning of an existing field does.

C positions are in the whole text `-o` wrote: lines from 1, columns from 0,
half-open. `unit_line` moves one into the file `--split` wrote. Source
positions are code point offsets into the module's file; a `?` (no
declaration base on record) reads as None and is the checker's to refuse.
"""

VERSION = "1"


def _num(s):
    return None if s in ("-", "?") else int(s)


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = [line.rstrip("\n").split("\t") for line in f]
    if not rows or rows[0][:2] != ["dawnmap", VERSION] or len(rows[0]) != 3:
        raise ValueError(f"{path}: not a version {VERSION} dawnmap: {rows[0] if rows else 'empty'}")
    out = {"backend": rows[0][2], "lines": None, "units": [], "srcs": {}, "fns": [], "calls": []}
    for r in rows[1:]:
        kind = r[0]
        if kind == "text":
            out["lines"] = int(r[1])
        elif kind == "unit":
            out["units"].append({"k": int(r[1]), "file": r[2], "first": int(r[3]), "last": int(r[4])})
        elif kind == "src":
            out["srcs"][r[1]] = r[2]
        elif kind == "fn":
            out["fns"].append({"first": int(r[1]), "last": int(r[2]), "module": r[3],
                               "origin": r[4], "symbol": r[5]})
        elif kind == "call":
            out["calls"].append({
                "first": _num(r[1]), "line": _num(r[2]), "clo": _num(r[3]), "chi": _num(r[4]),
                "module": r[5], "lo": _num(r[6]), "hi": _num(r[7]), "nlo": _num(r[8]), "what": r[9],
            })
    return out


def unit_line(m, line):
    """(file, line) of whole-text line `line` in the files `--split` wrote."""
    for u in m["units"]:
        if u["first"] <= line <= u["last"]:
            if u["file"] == "main.c":
                # a text with no unit markers is its own one file
                return u["file"], line
            # a unit file opens with its `#include` line
            return u["file"], line - u["first"] + 2
    return None

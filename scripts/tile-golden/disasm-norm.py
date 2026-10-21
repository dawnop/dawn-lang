#!/usr/bin/env python3
"""Compare a golden .mlir with `tileirdisasm` of its .tilebc, after normalizing
both sides with a CLOSED table of named rules (docs/tile-backend-design.md 6.37).

  disasm-norm.py compare <k>.mlir <disasm.txt>   exit 0 when equal after normalization
  disasm-norm.py selftest <golden-dir> <tileirdisasm>
                                                 every rule is live and every
                                                 counterexample stays red

Why this file exists, and why it is shaped like this. Two printers are being
compared. The .mlir is packages/tileir's renderer, which spells things the way
cuda-tile-translate does; the disassembly is NVIDIA's closed printer, which
names values by meaning (%tview, %cst_128_i32), elides defaulted attributes,
prints globals as blobs and spaces some things differently. Both go through
this one normalizer and are compared line by line, so the verdict is "the same
program", not "the same spelling". Making the renderer copy the disassembler
would turn its quirks into our format; storing a second golden per kernel
would only say the bytes did not change, which the .tilebc byte gate already
says.

The discipline that keeps this from becoming a gate that cannot go red:

  * The table below is closed. One rule per category of difference, each with
    the side it applies to, a pattern that matches only that category, and a
    counterexample: a semantic edit hidden inside the category's spelling,
    which must still differ after normalization (selftest does it for real
    kernels, against the real disassembler). Selftest also removes each rule in
    turn and requires its example kernel to go red, so no rule is dead.
  * Nothing is fuzzy. No rule skips a line, ignores an operand or matches by
    prefix. A line that survives normalization differently on the two sides is
    an unknown difference and fails with a diff; adding a rule is a decision.
  * SSA names are alpha-renamed by definition order on both sides (the
    disassembler's names carry no information and its numbering restarts in
    sibling regions), but every operand is kept: a use that names another
    value is a different program.
  * Floats are compared by bit pattern at their own width, never by spelling
    and never through a wider type: 0.32759110000000002 and 0.3275911 are one
    f64 and two different f32s.
"""
import difflib
import re
import struct
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- helpers

STR = re.compile(r'"(?:[^"\\]|\\.)*"')
NAME = r"%[A-Za-z0-9_.$\-]+"


class Unknown(Exception):
    """A difference no rule accounts for."""


def outside_strings(line, fn):
    """Apply fn to the parts of a line that are not string literals."""
    out, pos = [], 0
    for m in STR.finditer(line):
        out.append(fn(line[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fn(line[pos:]))
    return "".join(out)


def split_top(s):
    """Split on commas outside <>, [], (), {} and strings."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(s):
        c = s[i]
        if c == '"':
            m = STR.match(s, i)
            cur.append(m.group(0))
            i = m.end()
            continue
        if c in "<[({":
            depth += 1
        elif c in ">])}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def op_of(line):
    """The operation name of an instruction line, or ''."""
    m = re.match(r"(?:%[^=]*= )?([a-z_][a-z0-9_]*)\b", line)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- floats

FLOAT_FMT = {"f64": ("<d", 8), "f32": ("<f", 4), "f16": ("<e", 2)}


def float_bits(ty, lit):
    fmt, width = FLOAT_FMT[ty]
    lit = lit.strip()
    if lit.lower().startswith("0x"):
        v = int(lit, 16)
        if v >= 1 << (8 * width):
            raise Unknown(f"hex float {lit} does not fit {ty}")
        return v
    low = lit.lower()
    if low in ("infinity", "+infinity"):
        val = float("inf")
    elif low == "-infinity":
        val = float("-inf")
    elif low in ("nan", "+nan", "-nan"):
        val = float("nan")
    else:
        val = float(lit)
    try:
        raw = struct.pack(fmt, val)
    except OverflowError as e:
        raise Unknown(f"{lit} overflows {ty}") from e
    return int.from_bytes(raw, "little")


def canon_scalar(ty, lit):
    if ty in FLOAT_FMT:
        return "0x%0*X" % (FLOAT_FMT[ty][1] * 2, float_bits(ty, lit))
    return lit.strip()


def elem_types(types):
    out = []
    for t in split_top(types):
        m = re.fullmatch(r"tile<(?:[0-9?]+x)*([A-Za-z0-9_]+)>", t)
        out.append(m.group(1) if m else None)
    return out


# ---------------------------------------------------------------- rules

RULES = []  # (name, side, counterexample, fn), in application order


def RULE(name, side, counter, live=None):
    """side: 'M' (the renderer's text), 'D' (the disassembly) or 'both'.
    counter: (kernel, side to edit, regex, replacement): an edit that changes
    the program yet stays inside the category the rule normalizes. live: a
    kernel that is red without the rule, when the counterexample's is not."""

    def deco(fn):
        RULES.append((name, side, counter, live or counter[0], fn))
        return fn

    return deco


@RULE("module-wrapper", "M", ("vadd", "M", r"entry @vadd", "entry @vadd2"))
def r_module(lines):
    if not lines or lines[0] != "cuda_tile.module @m {" or lines[-1] != "}":
        raise Unknown("the text is not one `cuda_tile.module @m { ... }`")
    return lines[1:-1]


@RULE("indent", "both", ("vadd", "M", r"\n    return\n  \}", "\n  }\n    return"))
def r_indent(lines):
    return [l.lstrip() for l in lines]


@RULE("producer-comment", "D", ("vadd_producer", "D", r"^// Producer: .*\n", "// Producer: a\n// Producer: b\n"))
def r_producer(lines):
    if lines and lines[0].startswith("// Producer: "):
        return lines[1:]
    return lines


@RULE("region-params-own-line", "D", ("argmax", "D", r"\(%reduce_lhs0: tile<f64>", "(%reduce_lhs0: tile<f32>"))
def r_region_params(lines):
    out = []
    for l in lines:
        if (
            out
            and re.match(r"\(%[^)]*\) \{$", l)
            and re.search(r"= (reduce|scan) ", out[-1])
            and out[-1].endswith(" ")
        ):
            out[-1] += l
        else:
            out.append(l)
    return out


@RULE("space-runs", "both", ("print_tile", "M", r"sum=%d max", "sum=%d  max"), live="vadd")
def r_spaces(lines):
    return [outside_strings(l, lambda s: re.sub(r" {2,}", " ", s)).rstrip() for l in lines]


@RULE("tensor-view-strides-comma", "M", ("attn_bwd_mmt", "M", r"strides=\[(\d+), (\d+)\]", r"strides=[\2,\1]"))
def r_strides(lines):
    return [re.sub(r"strides=\[([0-9, ?]*)\]", lambda m: "strides=[" + m.group(1).replace(", ", ",") + "]", l) for l in lines]


@RULE("view-token-equals-space", "M", ("vadd", "M", r"token=%0", "token=%12"))
def r_view_token(lines):
    return [re.sub(r" token=%", " token = %", l) if op_of(l) in ("load_view_tko", "store_view_tko", "atomic_red_view_tko") else l for l in lines]


@RULE("hints-equals-space", "M", ("hint_memory", "M", r"latency = 4", "latency = 5"))
def r_hints(lines):
    return [l.replace("optimization_hints=<", "optimization_hints = <") if op_of(l) != "entry" else l for l in lines]


@RULE("inbounds-equals-space", "M", ("view_inbounds_dim", "M", r"inbounds=\[false, true\]", "inbounds=[true, false]"))
def r_inbounds(lines):
    return [l.replace(" inbounds=[", " inbounds = [") for l in lines]


ROUND_DEFAULT = {
    "addf": "nearest_even", "subf": "nearest_even", "mulf": "nearest_even",
    "divf": "nearest_even", "sqrt": "nearest_even", "fma": "nearest_even",
    "itof": "nearest_even", "ftof": "nearest_even", "ftoi": "nearest_int_to_zero",
}


@RULE("default-rounding", "M", ("vadd", "M", r"rounding<nearest_even>", "rounding<zero>"))
def r_rounding(lines):
    out = []
    for l in lines:
        d = ROUND_DEFAULT.get(op_of(l))
        if d:
            l = l.replace(f" rounding<{d}>", "")
        out.append(l)
    return out


@RULE("identity-dim-map", "M", ("attn_bwd_mmt", "M", r"dim_map=\[0, 1\]", "dim_map=[1, 0]"))
def r_dim_map(lines):
    def f(l):
        m = re.search(r", dim_map=\[([0-9, ]*)\]>", l)
        if m:
            dims = [int(x) for x in m.group(1).split(",")]
            if dims == list(range(len(dims))):
                l = l[: m.start()] + ">" + l[m.end():]
        return l

    return [f(l) for l in lines]


@RULE("fp8-e5m3-spelling", "D", ("dtype_e5m3", "D", r"fnv8E5M3FNU", "fnv8E4M3FN"))
def r_fp8(lines):
    return [l.replace("fnv8E5M3FNU", "f8E5M3FNU") for l in lines]


@RULE("loop-result-parens", "M", ("loop_count", "M", r"-> \(tile<128xi32>, tile<128xi32>\) \{", "-> (tile<128xi32>, tile<128xi64>) {"))
def r_loop_parens(lines):
    def f(l):
        if op_of(l) == "loop":
            m = re.search(r" -> \((.*)\) \{$", l)
            if m:
                l = l[: m.start()] + " -> " + m.group(1) + " {"
        return l

    return [f(l) for l in lines]


@RULE("for-unsigned-position", "D", ("attr_ucmp", "D", r"for unsigned ", "for "))
def r_for_unsigned(lines):
    def f(l):
        m = re.search(r"\bfor unsigned (%\S+) in (\(.*?\)) : ", l)
        if m:
            l = l[: m.start()] + f"for {m.group(1)} in {m.group(2)} unsigned : " + l[m.end():]
        return l

    return [f(l) for l in lines]


@RULE("empty-else-yield", "M", ("loop_count", "M", r"\} else \{\n( *)yield\n", "} else {\n\\1yield\n\\1yield\n"))
def r_empty_yield(lines):
    out = []
    for i, l in enumerate(lines):
        if l == "yield" and out and out[-1].endswith("else {") and i + 1 < len(lines) and lines[i + 1] == "}":
            continue
        out.append(l)
    return out


def esc_decode(s):
    """A string literal's bytes: \\n, \\t, \\\\, \\\" and \\XX (two hex digits)."""
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            n = s[i + 1]
            if n == "n":
                out.append(10)
                i += 2
            elif n == "t":
                out.append(9)
                i += 2
            elif n in '\\"':
                out.append(ord(n))
                i += 2
            elif re.match(r"[0-9A-Fa-f]{2}", s[i + 1:i + 3]):
                out.append(int(s[i + 1:i + 3], 16))
                i += 3
            else:
                raise Unknown(f"unknown escape in a string literal: {s[i:i+3]!r}")
        else:
            out.extend(c.encode())
            i += 1
    return bytes(out)


def esc_canon(b):
    return "".join(chr(x) if 32 <= x < 127 and chr(x) not in '\\"' else "\\%02X" % x for x in b)


@RULE("string-escape", "both", ("print_tile", "M", r"sum=%d max", "sum=%d mix"))
def r_string(lines):
    return [STR.sub(lambda m: '"' + esc_canon(esc_decode(m.group(0)[1:-1])) + '"', l) for l in lines]


@RULE("i1-literal", "M", ("subarray_sum2d", "M", r"<i1: 0>", "<i1: 1>"))
def r_i1(lines):
    return [re.sub(r"<i1: ([01])>", lambda m: "<i1: " + ("true" if m.group(1) == "1" else "false") + ">", l) for l in lines]


@RULE("float-literal", "both", ("erf_sweep", "D", r"0\.32759110000000002", "0.32759120000000002"))
def r_floats(lines):
    def const(l):
        def f(m):
            ty, v = m.group(1), m.group(2)
            return f"constant <{ty}: {canon_scalar(ty, v)}>" if ty in FLOAT_FMT else m.group(0)

        return re.sub(r"constant <([A-Za-z0-9]+): ([^>\[\]\"]+)>", f, l)

    def idents(l):
        m = re.search(r"identities=\[(.*?)\] : ((?:tile<[^>]*>(?:, )?)+) ->", l)
        if not m:
            return l
        tys = elem_types(m.group(2))
        items = split_top(m.group(1))
        if len(items) != len(tys):
            raise Unknown("identities and operands differ in count")
        out = []
        for it, ety in zip(items, tys):
            mm = re.fullmatch(r"(.*?)(?: : ([A-Za-z0-9]+))?", it)
            lit, ty = mm.group(1), mm.group(2) or ety
            if ty != ety:
                raise Unknown(f"identity {it} is not of its operand's type {ety}")
            out.append(f"{canon_scalar(ty, lit)} : {ty}")
        return l[: m.start(1)] + ", ".join(out) + l[m.end(1):]

    return [idents(const(l)) for l in lines]


@RULE("global-initializer", "both", ("global_syms", "D", r'<f64: "0x000000000000F03F', '<f64: "0x000000000000F13F'))
def r_global(lines):
    def f(l):
        m = re.match(r"(global\b.*?) <([A-Za-z0-9]+): (\[.*\]|\"0x[0-9A-Fa-f]*\"|[^>]+)> : tile<((?:[0-9]+x)*)([A-Za-z0-9]+)>$", l)
        if not m:
            return l
        head, ty, val, dims, ety = m.groups()
        if ty != ety:
            raise Unknown(f"global initializer type {ty} is not its tile's {ety}")
        n = 1
        for d in dims.split("x"):
            if d:
                n *= int(d)
        if val.startswith('"'):
            if ty not in FLOAT_FMT:
                raise Unknown("blob initializer of a non-float global")
            width = FLOAT_FMT[ty][1]
            raw = bytes.fromhex(val[3:-1])
            if len(raw) != n * width:
                raise Unknown("blob length differs from the tile")
            elems = ["0x%0*X" % (2 * width, int.from_bytes(raw[i:i + width], "little")) for i in range(0, len(raw), width)]
        elif val.startswith("["):
            elems = [canon_scalar(ty, x) for x in split_top(val[1:-1])]
        else:
            elems = [canon_scalar(ty, val)] * n
        if len(elems) != n:
            raise Unknown("initializer length differs from the tile")
        return f"{head} <{ty}: [{', '.join(elems)}]> : tile<{dims}{ety}>"

    return [f(l) for l in lines]


@RULE("ssa-alpha", "both", ("vadd", "M", r"addf %12, %17", "addf %12, %12"))
def r_alpha(lines):
    """Rename every value by definition order. Definitions are the line-leading
    results (`%a, %b =` or `%r:N =`), the `for` induction variable, iter_values
    binders and region parameters `(%a: t, ...)`. A use is resolved at the
    time it is read, so a sibling region that reuses a name (the disassembler
    does) gets a fresh value; `%r#i` selects a result of a multi-result."""
    env, count, out = {}, 0, []
    for line in lines:
        # string literals hold %d and friends: mask them out of the scan
        lits = []

        def mask(m):
            lits.append(m.group(0))
            return "\x00%d\x00" % (len(lits) - 1)

        text = STR.sub(mask, line)
        binders = {}  # start offset -> (name, count)
        m = re.match(rf"((?:{NAME})(?:, {NAME})*|{NAME}:\d+) = ", text)
        if m:
            lhs = m.group(1)
            if ":" in lhs:
                nm, n = lhs.split(":")
                binders[0] = (nm, int(n))
            else:
                for mm in re.finditer(NAME, lhs):
                    binders[mm.start()] = (mm.group(0), 1)
        for mm in re.finditer(rf"\bfor (?:unsigned )?({NAME}) in ", text):
            binders[mm.start(1)] = (mm.group(1), 1)
        mm = re.search(r"iter_values\(([^)]*)\)", text)
        if mm:
            for b in re.finditer(rf"({NAME}) = ", mm.group(1)):
                binders[mm.start(1) + b.start(1)] = (b.group(1), 1)
        for b in re.finditer(rf"[(,] ?({NAME}): ", text):
            binders[b.start(1)] = (b.group(1), 1)
        res, pos, pending = [], 0, []
        for mm in re.finditer(rf"({NAME})(#\d+)?", text):
            res.append(text[pos:mm.start()])
            pos = mm.end()
            if mm.start() in binders:
                nm, n = binders[mm.start()]
                ids = ["%%v%d" % (count + i) for i in range(n)]
                count += n
                pending.append((nm, ids))
                res.append(", ".join(ids))
                if n > 1:  # `%r:N` expands to N results; swallow the `:N`
                    pos = mm.end() + len(re.match(r":\d+", text[mm.end():]).group(0))
            else:
                nm, idx = mm.group(1), mm.group(2)
                if nm not in env:
                    raise Unknown(f"{nm} is used before any definition: {line}")
                i = int(idx[1:]) if idx else 0
                if i >= len(env[nm]):
                    raise Unknown(f"{nm}{idx or ''} names a result its definition does not have: {line}")
                res.append(env[nm][i])
        res.append(text[pos:])
        s = "".join(res)
        for i, t in enumerate(lits):
            s = s.replace("\x00%d\x00" % i, t)
        for nm, ids in pending:
            env[nm] = ids
        out.append(s)
    return out


# ---------------------------------------------------------------- driver

def normalize(text, side, disabled=()):
    lines = text.rstrip("\n").split("\n")
    for name, rside, _, _, fn in RULES:
        if name not in disabled and rside in ("both", side):
            lines = fn(lines)
    return lines


def unified(a, b):
    return "\n".join(difflib.unified_diff(a, b, "mlir (normalized)", "tileirdisasm (normalized)", lineterm="", n=2))


def compare(mlir, disasm, disabled=()):
    return normalize(mlir, "M", disabled), normalize(disasm, "D", disabled)


def cmd_compare(mlir_path, dis_path):
    try:
        a, b = compare(Path(mlir_path).read_text(), Path(dis_path).read_text())
    except Unknown as e:
        print(f"unknown difference: {e}", file=sys.stderr)
        return 1
    if a != b:
        print(unified(a, b), file=sys.stderr)
        print("unknown difference: the normalized texts differ", file=sys.stderr)
        return 1
    return 0


def disasm_of(tileirdisasm, tilebc):
    p = subprocess.run([tileirdisasm, str(tilebc)], capture_output=True, text=True)
    if p.returncode != 0 or p.stderr:
        raise Unknown(f"tileirdisasm refused {tilebc}: {p.stderr}")
    return p.stdout


def equal(m, d, disabled=()):
    try:
        a, b = compare(m, d, disabled)
    except Unknown:
        return False
    return a == b


# More counterexamples for rules whose category has more than one way to hide
# a change: (rule, (kernel, side, regex, replacement)).
EXTRA_COUNTERS = [
    ("float-literal", ("flash_attn_bf16", "M", r"<f32: -Infinity>", "<f32: Infinity>")),
    ("float-literal", ("flash_attn_bf16", "M", r"<f32: -Infinity>", "<f32: -3.4028234663852886E38>")),
    ("default-rounding", ("int_ops", "M", r"(ftoi .*?) rounding<nearest_int_to_zero>", r"\1 rounding<nearest_even>")),
    ("global-initializer", ("global_syms", "M", r"<f64: \[1\.0,", "<f64: [1.5,")),
]


def cmd_selftest(gold, tileirdisasm):
    gold = Path(gold)
    fails = 0
    cache = {}
    for name, _, (k, edit_side, pat, repl), live, _fn in RULES:
        if k not in cache:
            cache[k] = ((gold / f"{k}.mlir").read_text(), disasm_of(tileirdisasm, gold / f"{k}.tilebc"))
        m, d = cache[k]
        if not equal(m, d):
            print(f"FAIL  rule {name}: example kernel {k} is not equal after normalization", file=sys.stderr)
            fails += 1
            continue
        if live not in cache:
            cache[live] = ((gold / f"{live}.mlir").read_text(), disasm_of(tileirdisasm, gold / f"{live}.tilebc"))
        if equal(*cache[live], disabled=(name,)):
            print(f"FAIL  rule {name}: {live} is equal without it, so the rule is dead", file=sys.stderr)
            fails += 1
            continue
        src = m if edit_side == "M" else d
        new, n = re.subn(pat, repl, src, count=1, flags=re.M)
        if n != 1 or new == src:
            print(f"FAIL  rule {name}: its counterexample no longer matches {k}", file=sys.stderr)
            fails += 1
            continue
        mm, dd = (new, d) if edit_side == "M" else (m, new)
        if equal(mm, dd):
            print(f"FAIL  rule {name}: the counterexample stayed GREEN after normalization", file=sys.stderr)
            fails += 1
            continue
        print(f"PASS  rule {name}: live on {live}, its counterexample stays red")
    for name, (k, edit_side, pat, repl) in EXTRA_COUNTERS:
        if k not in cache:
            cache[k] = ((gold / f"{k}.mlir").read_text(), disasm_of(tileirdisasm, gold / f"{k}.tilebc"))
        m, d = cache[k]
        src = m if edit_side == "M" else d
        new, n = re.subn(pat, repl, src, count=1, flags=re.M)
        if n != 1 or new == src:
            print(f"FAIL  rule {name}: an extra counterexample no longer matches {k}", file=sys.stderr)
            fails += 1
        elif equal(*((new, d) if edit_side == "M" else (m, new))):
            print(f"FAIL  rule {name}: an extra counterexample on {k} stayed GREEN", file=sys.stderr)
            fails += 1
        else:
            print(f"PASS  rule {name}: extra counterexample on {k} stays red")
    return 1 if fails else 0


def main(argv):
    if len(argv) == 4 and argv[1] == "compare":
        return cmd_compare(argv[2], argv[3])
    if len(argv) == 4 and argv[1] == "selftest":
        return cmd_selftest(argv[2], argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

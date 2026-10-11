#!/usr/bin/env python3
"""Two readers for the Debug section goldens (knife T14b), kept out of run.sh
because the verdicts need real parsing and not a diff.

  debug-check.py locs <kernel>.mlir <tileirdisasm -g output>
      The table `tileirdisasm -g` prints, held against the golden's own text
      instead of against a stored copy of itself: the n-th location after the
      function's own must be the line and column where the n-th instruction
      starts in <kernel>.mlir, and the function's own the `entry` line. The
      expectation is computed here from the .mlir, so it does not move when
      the writer does.

  debug-check.py lines <cubin> [<kernel>.mlir]
      The line numbers the cubin's .debug_line holds, sorted and unique, one
      per line. With the .mlir, every one of them must be the line of an
      instruction (or the entry) in it. The DWARF line program is decoded
      here rather than with readelf, whose layout differs between binutils
      releases; tileiras writes version 2, and only the opcodes it uses are
      handled (anything else is an error and not a silent skip).
"""
import re
import struct
import sys


def mlir_positions(path):
    lines = open(path).read().split("\n")
    entry = next(i for i, l in enumerate(lines) if l.startswith("  entry @"))
    end = next(i for i in range(len(lines) - 1, -1, -1) if lines[i] == "  }")
    ops = []
    for i in range(entry + 1, end):
        text = lines[i].strip()
        if text in ("}", "} else {"):
            continue
        ops.append((i + 1, len(lines[i]) - len(lines[i].lstrip()) + 1))
    return (entry + 1, 3), ops


def cmd_locs(mlir, disasm):
    fn, ops = mlir_positions(mlir)
    text = open(disasm).read()
    base = {}
    for m in re.finditer(r'^(#loc\d*) = loc\("([^"]*)":(\d+):(\d+)\)$', text, re.M):
        base[m.group(1)] = (m.group(2), int(m.group(3)), int(m.group(4)))
    di = []
    for m in re.finditer(r"^#loc\d+ = #cuda_tile\.di_loc<(#loc\d*) in #di_subprogram>$", text, re.M):
        di.append(base[m.group(1)])
    want = [fn] + ops
    got = [(l, c) for (_f, l, c) in di]
    if got != want:
        for n, (g, w) in enumerate(zip(got + [None] * len(want), want + [None] * len(got))):
            if g != w:
                sys.exit(f"debug-check: location {n} is {g} in the disassembly and {w} in {mlir.rsplit(chr(47), 1)[-1]}; "
                         f"{len(got)} locations against {len(want)}")
    files = {f for (f, _l, _c) in di}
    stem = mlir.rsplit("/", 1)[-1]
    if files != {stem}:
        sys.exit(f"debug-check: the locations name {sorted(files)}, expected only {stem}")
    print(f"{len(got)} locations match {stem}")


def section(elf, name):
    shoff, = struct.unpack_from("<Q", elf, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 0x3A)

    def hdr(i):
        return struct.unpack_from("<IIQQQQIIQQ", elf, shoff + i * shentsize)

    stroff = hdr(shstrndx)[4]
    for i in range(shnum):
        h = hdr(i)
        n = elf[stroff + h[0]:elf.index(b"\0", stroff + h[0])].decode()
        if n == name:
            return elf[h[4]:h[4] + h[5]]
    return None


def uleb(b, p):
    r = s = 0
    while True:
        x = b[p]
        p += 1
        r |= (x & 0x7F) << s
        s += 7
        if not x & 0x80:
            return r, p


def sleb(b, p):
    r = s = 0
    while True:
        x = b[p]
        p += 1
        r |= (x & 0x7F) << s
        s += 7
        if not x & 0x80:
            if x & 0x40:
                r -= 1 << s
            return r, p


def line_rows(sec):
    rows = []
    p = 0
    while p < len(sec):
        unit_len, = struct.unpack_from("<I", sec, p)
        end = p + 4 + unit_len
        version, hdr_len = struct.unpack_from("<HI", sec, p + 4)
        if version > 4:
            sys.exit(f"debug-check: DWARF line version {version} is not handled")
        q = p + 10
        min_inst, = struct.unpack_from("<B", sec, q)
        q += 1
        if version >= 4:
            q += 1  # maximum_operations_per_instruction
        default_stmt, line_base, line_range, opcode_base = struct.unpack_from("<BbBB", sec, q)
        q += 4
        std_len = list(sec[q:q + opcode_base - 1])
        prog = p + 10 + hdr_len
        q = prog
        line = 1
        while q < end:
            op = sec[q]
            q += 1
            if op >= opcode_base:
                line += line_base + (op - opcode_base) % line_range
                rows.append(line)
            elif op == 0:
                n, q = uleb(sec, q)
                sub = sec[q]
                if sub == 1:
                    line = 1
                elif sub not in (2, 3):
                    sys.exit(f"debug-check: extended opcode {sub} is not handled")
                q += n
            elif op == 1:
                rows.append(line)
            elif op == 2:
                _, q = uleb(sec, q)
            elif op == 3:
                d, q = sleb(sec, q)
                line += d
            elif op in (4, 5, 9):
                _, q = uleb(sec, q) if op != 9 else (None, q + 2)
            elif op in (6, 7, 8):
                pass
            else:
                sys.exit(f"debug-check: standard opcode {op} is not handled")
        p = end
    return rows


def cmd_lines(cubin, mlir=None):
    sec = section(open(cubin, "rb").read(), ".debug_line")
    got = sorted(set(line_rows(sec))) if sec else []
    if mlir:
        fn, ops = mlir_positions(mlir)
        ok = {fn[0]} | {l for (l, _c) in ops}
        bad = [l for l in got if l not in ok]
        if bad:
            sys.exit(f"debug-check: .debug_line holds lines {bad} that are no instruction of {mlir}")
    for l in got:
        print(l)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "locs":
        cmd_locs(a[1], a[2])
    elif a[:1] == ["lines"] and len(a) in (2, 3):
        cmd_lines(*a[1:])
    else:
        sys.exit(__doc__)

#!/usr/bin/env python3
"""Generate stress families and independent byte oracles, never recordings.

The template stays readable. Large cardinalities belong here so that changing
one boundary cannot leave a hand-copied list or expected transcript behind.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def quoted(text):
    return json.dumps(text, ensure_ascii=False)


def generate(out):
    (out / "src").mkdir(parents=True)
    manifest = (HERE / "dawn.toml").read_text()
    for alias in ("sha2", "inflate"):
        relative = quoted(f"../../packages/{alias}")
        if manifest.count(relative) != 1:
            raise RuntimeError(f"template must name exactly one {alias} dependency")
        manifest = manifest.replace(relative, quoted(str(ROOT / "packages" / alias)), 1)
    (out / "dawn.toml").write_text(manifest)
    (out / "src/data.dawn").write_text((HERE / "src/data.dawn").read_text())
    source = (HERE / "src/main.dawn").read_text()
    decls, checks = [], []
    for i in range(130):
        raw = bytes([i, 255 - i]).hex()
        decls.append(f'const B{i}: Bytes = bytes.from_hex("{raw}").expect("valid")')
    decls.append('fn small(i: Int) -> Bytes = match i {\n' +
                 '\n'.join(f' {i} -> B{i}' for i in range(130)) + '\n _ -> B0\n}')
    decls.append('''const MANY: List[Bytes] = comptime {
  var xs: List[Bytes] = []
  for i in 0..5000 { xs = xs ++ [bytes.pack_ints([i & 255, i >>> 8], 1)] }
  xs
}''')
    checks += [
        'for i in 0..130 { require(bytes.at(small(i), 0) == i && bytes.at(small(i), 1) == 255 - i) }',
        'require(len(MANY) == 5000)',
        'for i in 0..5000 { require(bytes.at(MANY[i], 0) == (i & 255) && bytes.at(MANY[i], 1) == (i >>> 8)) }',
    ]
    ints = [-1, 300, 0x12345678, -(1 << 63)]
    for width in (1, 2, 4, 8):
        mask = (1 << (8 * width)) - 1
        for order in ("Little", "Big"):
            key = f"I{width}{order.upper()}"
            raw = b"".join((x & mask).to_bytes(width, order.lower()) for x in ints)
            decls.append(f'const {key}: Bytes = bytes.pack_ints({ints}, {width}, bytes.{order})')
            checks.append(f'require(bytes.to_hex({key}) == "{raw.hex()}")')
            for signed in (False, True):
                vals = [int.from_bytes(raw[i:i + width], order.lower(), signed=signed or width == 8)
                        for i in range(0, len(raw), width)]
                sign = str(signed).lower()
                decls.append(f'const U{key}{sign.upper()}: List[Int] = bytes.unpack_ints({key}, {width}, {sign}, bytes.{order})')
                checks.append(f'require(U{key}{sign.upper()} == {vals})')
    bits = [0, 1 << 63, 1, 0x0010000000000000, 0x3ff0000000000000,
            0x7ff0000000000000, 0xfff0000000000000, 0x7ff8000000001234, 0xfff8000000005678]
    raw = b"".join(x.to_bytes(8, "little") for x in bits).hex()
    decls.append(f'const FLOATS: List[Float] = bytes.unpack_floats(bytes.from_hex("{raw}").expect("valid"), 8)')
    for order in ("Little", "Big"):
        expected = b"".join(x.to_bytes(8, order.lower()) for x in bits).hex()
        decls.append(f'const F8{order.upper()}: Bytes = bytes.pack_floats(FLOATS, 8, bytes.{order})')
        checks.append(f'require(bytes.to_hex(F8{order.upper()}) == "{expected}")')
        checks.append(f'require(bytes.to_hex(bytes.pack_floats(FLOATS, 8, bytes.{order})) == "{expected}")')
    values = [0.0, -0.0, 1.0, 16777217.0, 1e300, 4.9e-324]
    for order, prefix in (("Little", "<"), ("Big", ">")):
        expected = b"".join(struct.pack(prefix + "f", ctypes.c_float(v).value) for v in values).hex()
        decls.append(f'const F4{order.upper()}: Bytes = bytes.pack_floats({values}, 4, bytes.{order})')
        checks.append(f'require(bytes.to_hex(F4{order.upper()}) == "{expected}")')
    decls.append('const F4NAN: List[Float] = bytes.unpack_floats(bytes.pack_floats([FLOATS[7]], 4), 4)')
    checks.append('require(F4NAN[0] != F4NAN[0])')
    for n in (55, 56, 63, 64, 65):
        expected = hashlib.sha256(b"x" * n).hexdigest()
        decls.append(f'const SHA{n}: String = sha256.hex(filled({n}))')
        checks.append(f'require(SHA{n} == "{expected}" && SHA{n} == sha256.hex(filled({n})))')
    decls.append('''fn buffered(n: Int) -> Bytes = {
  var b = bytes.buf()
  for i in 0..n { b = bytes.put(b, i) }
  bytes.freeze(b)
}
const BUFS: List[Bytes] = [buffered(4095), buffered(4096), buffered(4097)]
const FORKS: (Bytes, Bytes, Bytes) = comptime {
  let b = bytes.put_bytes(bytes.buf(), bytes.utf8("abc"))
  let left = bytes.put(b, 128)
  let right = bytes.put(b, 255)
  (bytes.freeze(b), bytes.freeze(left), bytes.freeze(right))
}''')
    checks.append('for k in 0..3 {\n require(len(BUFS[k]) == 4095 + k)\n for i in 0..len(BUFS[k]) { require(bytes.at(BUFS[k], i) == (i & 255)) }\n}')
    checks.append('match FORKS { (a, b, c) -> {\n require(bytes.to_hex(a) == "616263")\n require(bytes.to_hex(b) == "61626380")\n require(bytes.to_hex(c) == "616263ff")\n} }')
    checks += ['require(bytes.to_hex(bytes.utf8("a中😀")) == "61e4b8adf09f9880")',
               'require(bytes.decode_utf8_lossy(bytes.from_hex("80ff").expect("valid")) == "��")',
               'require(bytes.decode_utf8_lossy(bytes.from_hex("f09f92").expect("valid")) == "�")',
               'require(bytes.to_hex(bytes.slice(RAW, -9, 99)) == "007f80ff")',
               'require(len(bytes.slice(RAW, 3, 1)) == 0)']
    for i, (raw, offset) in enumerate((("80", 0), ("ff", 0), ("c0af", 0), ("e080af", 0),
                                       ("eda080", 0), ("f4908080", 0), ("f09f92", 0), ("61c3", 1))):
        decls.append(f'const UTF{i}: Result[String, bytes.Utf8Error] = bytes.decode_utf8_checked(bytes.from_hex("{raw}").expect("valid"))')
        checks.append(f'match UTF{i} {{ Err(e) -> require(e.offset == {offset})\n _ -> require(false) }}')
    # Also fold the lossy and range paths; runtime-only calls would miss CTFE.
    decls += ['const LOSSY: String = bytes.decode_utf8_lossy(bytes.from_hex("80ff").expect("valid"))',
              'const SLICE: Bytes = bytes.slice(RAW, -9, 99)',
              'const SHOW: String = to_string(RAW)']
    checks += ['require(LOSSY == "��" && SLICE == RAW && SHOW == "<4 bytes>")']
    decls.append('fn generated_checks() -> Unit = {\n' + '\n'.join('  ' + x for x in checks) + '\n}')
    source = source.replace('fn generated_checks() -> Unit = ()', '\n'.join(decls), 1)
    (out / "src/main.dawn").write_text(source)
    (out.parent / "oversized.dawn").write_text('''use std/bytes
fn filled() -> Bytes = {
  var b = bytes.utf8("x")
  while len(b) < 1048576 { b = b ++ b }
  b ++ bytes.utf8("y")
}
const BAD: Bytes = filled()
''')
    (out.parent / "allocation.dawn").write_text('''use std/bytes
fn chunk() -> Bytes = {
  var b = bytes.utf8("x")
  while len(b) < 16384 { b = b ++ b }
  b
}
const BAD: Int = {
  var total = 0
  for _i in 0..2200 { total = total + len(chunk()) }
  total
}
''')
    refusals = {
        "io": ('const BAD: Unit = { println("no")\n () }\n', 'must be pure'),
        "function": ('const BAD: fn(Int) -> Int = x => x\n', 'not a constant-serializable type'),
        "cursor": ('use std/cursor\nconst BAD: cursor.Cursor = cursor.start("😀")\n', 'not a constant-serializable type'),
        "hamt": ('use std/map\nconst BAD: Int = len(map.from([(1, 2)]))\n', 'Map and Set operations are not available at comptime'),
    }
    for name, (body, _) in refusals.items():
        (out.parent / (name + ".dawn")).write_text(body)
    (out.parent / "refusals.json").write_text(json.dumps({name: reason for name, (_, reason) in refusals.items()}))


if __name__ == "__main__":
    generate(Path(sys.argv[1]))

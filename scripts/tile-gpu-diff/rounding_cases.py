#!/usr/bin/env python3
"""Pin source-value and explicit two-step rounding with exact rational distances.

Inputs are a fixed finite boundary corpus. The oracle uses format grids and
integer tie parity, independently of Dawn's codecs, lowering and interpreter.
The generated literals are shared by the existing architecture family on all
three execution paths; --check refuses a stale fixture without rewriting it.
"""
import bisect
from fractions import Fraction
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent

def f64(b): return struct.unpack('>d', struct.pack('>Q', b))[0]
def bits(x): return struct.unpack('>Q', struct.pack('>d', x))[0]
def rn32(x):
    try: return struct.unpack('>f', struct.pack('>f', x))[0]
    except OverflowError: return math.copysign(math.inf, x)
def grid(m, bias, last):
    return [Fraction(i, 2**m) * Fraction(2)**(1-bias) if i < 2**m else
            Fraction(2**m + i % (2**m), 2**m) * Fraction(2)**(i // (2**m)-bias)
            for i in range(last + 1)]
def rounded(x, g):
    if math.isnan(x): return 0.0 if len(g) == 8 else math.nan
    if math.isinf(x): return math.copysign(float(g[-1]), x)
    a = Fraction(abs(x)); k = bisect.bisect_left(g, a)
    if k == len(g): k -= 1
    elif k and (a-g[k-1] < g[k]-a or (a-g[k-1] == g[k]-a and (k-1) % 2 == 0)): k -= 1
    return math.copysign(float(g[k]), x)

def literal(b):
    return f"(0x{b & ((1<<63)-1):016x} | (1 << 63))" if b >> 63 else f"0x{b:016x}"

INPUTS = {
    0: [
        0x3f4fffffffffffff,
        0x3f50000000000000,
        0x3f50000000000001,
        0xbf4fffffffffffff,
        0xbf50000000000000,
        0xbf50000000000001,
        0x3f8dffffffffffff,
        0x3f8e000000000000,
        0x3f8e000000000001,
        0xbf8dffffffffffff,
        0xbf8e000000000000,
        0xbf8e000000000001,
        0x3ff0ffffffffffff,
        0x3ff1000000000000,
        0x3ff1000000000001,
        0xbff0ffffffffffff,
        0xbff1000000000000,
        0xbff1000000000001,
        0x3ff2ffffffffffff,
        0x3ff3000000000000,
        0x3ff3000000000001,
        0xbff2ffffffffffff,
        0xbff3000000000000,
        0xbff3000000000001,
        0x3f60000000000000,
        0x407c000000000000,
        0x408c000000000000,
        0xc08c000000000000,
        0x0000000000000000,
        0x8000000000000000,
        0x0000000000000001,
        0x8000000000000001,
        0x36a0000000000000,
        0xb6a0000000000000,
        0x3810000000000000,
        0xb810000000000000,
        0x7e37e43c8800759c,
        0xfe37e43c8800759c,
        0x7ff0000000000000,
        0xfff0000000000000,
        0x7ff8000000000000,
    ],
    1: [
        0x0000000000000000,
        0x8000000000000000,
        0x3ef0000000000000,
        0xbef0000000000000,
        0x3ee0000000000000,
        0xbee0000000000000,
        0x3ef8000000000000,
        0xbef8000000000000,
        0x3f08000000000000,
        0x3f10000000000000,
        0x3f0c000000000000,
        0xbf0c000000000000,
        0x3ff2000000000000,
        0x3ff6000000000000,
        0xbff2000000000000,
        0xbff6000000000000,
        0x3ff4000000000000,
        0x3ff8000000000000,
        0x40ec000000000000,
        0x40edffe000000000,
        0x40ee000000000000,
        0x40ee002000000000,
        0xc0ee000000000000,
        0x46293e5939a08cea,
        0xc6293e5939a08cea,
        0x7ff0000000000000,
        0xfff0000000000000,
        0x7ff8000000000000,
        0x3edfffffffffffff,
        0x3ee0000000000001,
        0x3f0bffffffffffff,
        0x3f0c000000000001,
        0x3ff1ffffffffffff,
        0x3ff2000000000001,
        0x3ff5ffffffffffff,
        0x3ff6000000000001,
        0xbee0000000000001,
        0xbf0bffffffffffff,
        0xbff2000000000001,
        0xbff5ffffffffffff,
        0x0000000000000001,
        0x8000000000000001,
        0x36a0000000000000,
        0xb6a0000000000000,
        0x3810000000000000,
        0xb810000000000000,
        0x7e37e43c8800759c,
        0xfe37e43c8800759c,
    ],
    3: [
        0x3fcfffffffffffff,
        0x3fd0000000000000,
        0x3fd0000000000001,
        0xbfcfffffffffffff,
        0xbfd0000000000000,
        0xbfd0000000000001,
        0x3ff3ffffffffffff,
        0x3ff4000000000000,
        0x3ff4000000000001,
        0xbff3ffffffffffff,
        0xbff4000000000000,
        0xbff4000000000001,
        0x3ffbffffffffffff,
        0x3ffc000000000000,
        0x3ffc000000000001,
        0xbffbffffffffffff,
        0xbffc000000000000,
        0xbffc000000000001,
        0x4013ffffffffffff,
        0x4014000000000000,
        0x4014000000000001,
        0xc013ffffffffffff,
        0xc014000000000000,
        0xc014000000000001,
        0x3fe0000000000000,
        0x4018000000000000,
        0x4028000000000000,
        0xc028000000000000,
        0x0000000000000000,
        0x8000000000000000,
        0x0000000000000001,
        0x8000000000000001,
        0x36a0000000000000,
        0xb6a0000000000000,
        0x3810000000000000,
        0xb810000000000000,
        0x7e37e43c8800759c,
        0xfe37e43c8800759c,
        0x7ff0000000000000,
        0xfff0000000000000,
        0x7ff8000000000000,
    ],
}

SIGN = 1 << 63

def power(e):
    return Fraction(2) ** e

def decode(bits, width):
    p, eb, bias = (52, 11, 1023) if width == 64 else (23, 8, 127)
    exponent = (bits >> p) & ((1 << eb) - 1)
    fraction = bits & ((1 << p) - 1)
    if exponent == (1 << eb) - 1:
        return 'nan' if fraction else 'inf'
    return Fraction(fraction if exponent == 0 else (1 << p) + fraction) * power((1-bias if exponent == 0 else exponent-bias)-p)

def encode64(value):
    return bits(float(value))

def e8(value):
    if value == 'nan':
        return 0x7ff8000000000000
    if value == 'inf':
        return encode64(power(127))
    eligible = [e for e in range(-127, 128) if power(e) <= value]
    return encode64(power(max(eligible) if eligible else -127))

def rne32(value):
    if isinstance(value, str) or value == 0:
        return value
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if value < power(exponent):
        exponent -= 1
    step = power(max(exponent, -126)-23)
    scaled = value / step
    q, r = divmod(scaled.numerator, scaled.denominator)
    if 2*r > scaled.denominator or (2*r == scaled.denominator and q % 2):
        q += 1
    rounded = q * step
    return 'inf' if rounded >= power(128) else rounded


def e8m0_rows():
    sources = [0x3fffffffffffffff, 0xbfffffffffffffff]
    for exponent in [-128, -127, -126, -1, 0, 1, 2, 126, 127, 128]:
        center = encode64(power(exponent))
        for sign in [0, SIGN]:
            sources.extend(sign | (center + delta) for delta in [-1, 0, 1])
    for bits in [0, 1, 0xfffffffffffff, 0x10000000000000, 0x7fefffffffffffff,
                 0x7ff0000000000000, 0x7ff8000000000000, 0x7ff0000000000001]:
        sources.extend([bits, bits | SIGN])
    f32_sources = []
    for center in [0x400000, 0x800000, 0x3f800000, 0x40000000, 0x7f000000]:
        f32_sources.extend(center + delta for delta in [-1, 0, 1])
    f32_sources += [0, 1, 0x7fffff, 0x7f7fffff, 0x7f800000, 0x7fc00000]
    for bits in f32_sources:
        for sign in [0, 1 << 31]:
            value = decode(bits, 32)
            wide = 0x7ff8000000000000 if value == 'nan' else 0x7ff0000000000000 if value == 'inf' else encode64(value)
            sources.append(wide | (SIGN if sign else 0))
    sources = list(dict.fromkeys(sources))
    rows = [(b, e8(decode(b, 64)), e8(rne32(decode(b, 64)))) for b in sources]
    assert rows[0] == (0x3fffffffffffffff, 0x3ff0000000000000, 0x4000000000000000)
    assert rows[1][1:] == rows[0][1:]
    assert all(e8(power(e)) == encode64(power(e)) for e in range(-127, 128))
    return rows

def generate():
    text = """# Exact rational expectations, generated by rounding_cases.py. This table
# never calls the implementation under test. Each row holds source bits,
# one-rounding result bits, and explicitly requested RNE32-then-target bits.
use std/bytes
use std/list

"""
    for i, args in [(0,(3,7,126)), (1,(2,15,123)), (3,(1,1,7))]:
        g=grid(*args)
        text += f"const CASES_{i}: List[(Int, Int, Int)] = [\n"
        for b in INPUTS[i]:
            x=f64(b)
            text += '  ('+', '.join(map(literal,[b,bits(rounded(x,g)),bits(rounded(rn32(x),g))]))+'),\n'
        text=text[:-2]+'\n]\n\n'
    text += TEMPLATE
    text += "\n# Exact-rational E8M0 source oracle: source binary64 bits, single, explicit RNE32.\n"
    text += "# NaNs are checked by class; no payload or sign is promised.\n"
    text += "const E8M0_SOURCE: List[(Int, Int, Int)] = [\n"
    text += ",\n".join("  (" + ", ".join(map(literal, row)) + ")" for row in e8m0_rows())
    return text + "\n]\n"

TEMPLATE = r'''pub fn cases(i: Int) -> List[(Int, Int, Int)] = match i {
  0 -> CASES_0
  1 -> CASES_1
  3 -> CASES_3
  _ -> []
}

pub fn of_bits(b: Int) -> Float = bytes.unpack_floats(bytes.pack_ints([b], 8), 8)[0]

## The E8M0 probe repeats every frozen source, including the distinguishing
## binary64 neighbours and exact binary32 subnormal/zero patterns.
pub fn e8m0_inputs(n: Int) -> List[Float] = list.map(range(0, n), j => {
  let (b, _, _) = E8M0_SOURCE[j % len(E8M0_SOURCE)]
  of_bits(b)
})

## Count the independently pinned sources and distinct rounding answers.
pub fn e8m0_shape() -> String = {
  let different = list.filter(E8M0_SOURCE, row => {
    let (_, single, explicit) = row
    single != explicit
  })
  "source_bits=${len(E8M0_SOURCE)} single_vs_two=${len(different)} segments=4"
}

## Compare every lane and the untouched tail independently of tileref.
pub fn e8m0_check(v: List[Float], n: Int, tail: Int, sentinel: Float) -> String = {
  if len(v) != 4 * n + tail { return "length=${len(v)} expected=${4 * n + tail}" }
  for lane in range(0, len(v)) {
    let want = if lane >= 4 * n { sentinel } else {
      let (_, single, explicit) = E8M0_SOURCE[(lane % n) % len(E8M0_SOURCE)]
      of_bits(if lane / n < 2 { single } else { explicit })
    }
    if not same(v[lane], want) {
      return "seg=${lane / n} lane=${lane % n} bits=${bits(v[lane])} expected=${bits(want)}"
    }
  }
  "pass"
}

pub fn inputs(i: Int, n: Int) -> List[Float] = {
  let rows = cases(i)
  list.map(range(0, n), j => if j < len(rows) {
    let (b, _, _) = rows[j]
    of_bits(b)
  } else if i == 3 { to_float(j % 29) * 0.25 - 3.5 }
  else { to_float(j - 256) * 0.1 + 1.0 / 3.0 })
}

fn bits(v: Float) -> String = bytes.to_hex(bytes.pack_floats([v], 8, bytes.Big))

pub fn same(a: Float, b: Float) -> Bool =
  if a != a { b != b } else { bytes.pack_floats([a], 8) == bytes.pack_floats([b], 8) }

pub fn check(i: Int, v: List[Float], n: Int, tail: Int, sentinel: Float, explicit: Bool) -> String = {
  let rows = cases(i)
  let count = 2 * n + tail
  if len(v) != count { return "length=${len(v)} expected=${count} first_missing=${len(v)}" }
  let bad = list.find(range(0, len(rows) + tail), j => {
    let lane = if j < len(rows) { n + j } else { 2 * n + j - len(rows) }
    let want = if j < len(rows) {
      let (_, direct, two_step) = rows[j]
      of_bits(if explicit { two_step } else { direct })
    } else { sentinel }
    not same(v[lane], want)
  })
  match bad {
    None -> "pass"
    Some(j) -> {
      let lane = if j < len(rows) { n + j } else { 2 * n + j - len(rows) }
      let want = if j < len(rows) {
        let (_, direct, two_step) = rows[j]
        of_bits(if explicit { two_step } else { direct })
      } else { sentinel }
      "seg=${lane / n} lane=${lane % n} bits=${bits(v[lane])} expected=${bits(want)}"
    }
  }
}
'''

if __name__ == '__main__':
    path=HERE/'rounding.dawn'
    text=generate()
    if sys.argv[1:] == ['--check']:
        if path.read_text() != text: raise SystemExit('rounding_cases: stale independent table')
        print('PASS rounding_cases: '+str({i:len(xs) for i,xs in INPUTS.items()})+' E8M0='+str(len(e8m0_rows())))
    elif not sys.argv[1:]: path.write_text(text)
    else: raise SystemExit('usage: rounding_cases.py [--check]')

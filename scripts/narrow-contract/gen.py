#!/usr/bin/env python3
"""The exact oracle for std/narrow, and the corpus it writes.

    python3 scripts/narrow-contract/gen.py            # rewrite the corpus
    python3 scripts/narrow-contract/gen.py --check    # is the corpus current?

std/narrow rounds Float to bfloat16, binary16 and binary32 and does the
arithmetic of those formats by computing in Float and rounding once more.
Both backends compile the same Dawn source, so comparing them to each other
cannot see a wrong rounding rule: it would be a shared wrong answer. The
outside opinion is this file. It rounds with `fractions.Fraction`, which is
exact, from the definition (nearest representable value, ties to the even
significand, overflow to the infinity, gradual underflow), and writes what it
found as a differential corpus:

    scripts/spike-native/narrow_round.dawn      the program
    scripts/spike-native/narrow_round.expect    what it must print

The program carries every input and every expected answer as literals and
prints, per format and per section, how many disagreed. `.expect` says zero
everywhere. That is the hand-written expectation spike-native's harness
insists on: it is not recorded from either backend, it is what the oracle
says the answers are.

The corpus is deterministic (the seed is fixed below), so `--check`
regenerates into memory and compares: a corpus edited by hand, or a
generator edited without rerunning it, is a failure. scripts/narrow-contract/
run.sh runs that check first.

## What is in the corpus

For each format, in the sections the program prints:

    ties        exact midpoints between adjacent format values, built from a
                random significand plus exactly half a unit in the last
                place, on both sides of even; plus the same midpoints nudged
                one Float ulp either way, which must not tie
    subnormal   values below the format's normal range: on the subnormal
                grid, between its points, half the smallest subnormal (a tie
                down to zero, of both signs), and Float's own subnormals,
                which lie far below every grid here
    overflow    the largest finite value, the midpoint above it (a tie whose
                even side is the carry out of the top exponent), values just
                inside and just outside, and the non-finite inputs
    random      random 64-bit patterns, finite ones kept, so the exponent
                loop is exercised across the whole Float range
    add sub mul div
                pairs of format values, hand-picked (cancellation, a tie in
                the sum, overflow, underflow to zero, division by zero, the
                infinities and NaN) and random; the expected answer is the
                exact rational result rounded once
    sqrt        format values, hand-picked and random; the expected answer is
                the correctly rounded root, decided by exact comparison of
                the input with the square of the midpoint between the two
                candidate results

A negative control for each of the three rules lives in run.sh (ties to
even, the subnormal clamp, the overflow threshold); each has an owning
section here.
"""

import math
import pathlib
import random
import struct
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PROGRAM = ROOT / "scripts" / "spike-native" / "narrow_round.dawn"
EXPECT = ROOT / "scripts" / "spike-native" / "narrow_round.expect"

SEED = 20260902
INF = float("inf")
NAN = float("nan")

# (name, p, emin, emax) -- p counts the hidden bit
FORMATS = [
    ("bf16", 8, -126, 127),
    ("fp16", 11, -14, 15),
    ("f32", 24, -126, 127),
]

# ---------------------------------------------------------------- the oracle


def round_frac(v: Fraction, negative: bool, p: int, emin: int, emax: int) -> float:
    """The format value nearest to the non-negative rational v, signed.

    Returns a Python float; every value of every format here is one. A zero
    result carries the sign, which is what -0.0 is for.
    """
    if v == 0:
        return -0.0 if negative else 0.0
    e = 0
    a = v
    while a >= 2:
        a /= 2
        e += 1
    while a < 1:
        a *= 2
        e -= 1
    # v = a * 2^e with a in [1, 2); the quantum is 2^(max(e, emin) - p + 1)
    quantum = Fraction(2) ** (max(e, emin) - p + 1)
    m = v / quantum
    fl = m.numerator // m.denominator
    rem = m - fl
    if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and fl % 2 == 1):
        fl += 1
    out = fl * quantum
    max_finite = (2 - Fraction(2) ** (1 - p)) * Fraction(2) ** emax
    if out > max_finite:
        result = INF
    else:
        result = float(out)
        assert Fraction(result) == out, "a format value must be a Float"
    return -result if negative else result


def round_float(x: float, p: int, emin: int, emax: int) -> float:
    """round_binary's contract on a Float input."""
    if math.isnan(x) or math.isinf(x) or x == 0.0:
        return x
    return round_frac(Fraction(abs(x)), x < 0, p, emin, emax)


def sqrt_frac(v: Fraction, p: int, emin: int, emax: int) -> float:
    """The correctly rounded p-bit square root of the positive rational v."""
    e = 0
    a = v
    while a >= 2:
        a /= 2
        e += 1
    while a < 1:
        a *= 2
        e -= 1
    # sqrt(v) lies in [2^(e // 2), 2^(e // 2 + 1)), so its p-bit quantum is
    half_e = e // 2  # floor, also for negative e
    quantum = Fraction(2) ** (half_e - p + 1)
    scaled = v / quantum**2
    m = math.isqrt(scaled.numerator // scaled.denominator)
    # m = floor(sqrt(v) / quantum); the answer is m or m + 1, decided by
    # which side of the midpoint the exact root falls on
    mid = Fraction(2 * m + 1, 2)
    if scaled > mid * mid:
        m += 1
    elif scaled == mid * mid:
        # unreachable for a p-bit input (its root is never a midpoint);
        # spelled out so the rule is whole
        if m % 2 == 1:
            m += 1
    # the root of a normal or subnormal value is normal and cannot overflow,
    # but a carry to 2^p is a valid value, and round_frac renormalises it
    return round_frac(m * quantum, False, p, emin, emax)


def op_oracle(op: str, a: float, b: float, p: int, emin: int, emax: int) -> float:
    """The format's correctly rounded a op b, from the exact rational result.

    The special values are IEEE's, and Float arithmetic on the two inputs
    answers them: a NaN or infinite input, a division by zero, and a result
    that is exactly zero (where the sign is the whole answer) all come out of
    the Float operation exactly as the format's operation defines them,
    because they involve no rounding. Everything else is finite and non-zero,
    and there the exact rational result is rounded once.
    """
    if op == "add":
        d = a + b
    elif op == "sub":
        d = a - b
    elif op == "mul":
        d = a * b
    elif op == "div":
        if b == 0:
            # x / 0 is the infinity of the product of the signs; 0 / 0 is NaN
            d = NAN if a == 0 or math.isnan(a) else math.copysign(INF, a) * math.copysign(1.0, b)
        else:
            d = a / b
    else:
        raise ValueError(op)
    if math.isnan(d) or math.isinf(d) or d == 0.0:
        return d
    fa, fb = Fraction(a), Fraction(b)
    if op == "add":
        exact = fa + fb
    elif op == "sub":
        exact = fa - fb
    elif op == "mul":
        exact = fa * fb
    else:
        exact = fa / fb
    return round_frac(abs(exact), exact < 0, p, emin, emax)


def sqrt_oracle(a: float, p: int, emin: int, emax: int) -> float:
    if math.isnan(a) or a == 0.0 or a == INF:
        return a
    if a < 0:
        return NAN
    return sqrt_frac(Fraction(a), p, emin, emax)


# ---------------------------------------------------------------- inputs


def next_up(x: float) -> float:
    return math.nextafter(x, INF)


def next_down(x: float) -> float:
    return math.nextafter(x, -INF)


def min_subnormal(p: int, emin: int) -> float:
    return float(Fraction(2) ** (emin - p + 1))


def max_finite(p: int, emax: int) -> float:
    return float((2 - Fraction(2) ** (1 - p)) * Fraction(2) ** emax)


def random_format_value(rng: random.Random, p: int, emin: int, emax: int, lo: int, hi: int) -> float:
    """A random normal value of the format with exponent in lo..hi."""
    e = rng.randint(lo, hi)
    sig = rng.getrandbits(p - 1) | (1 << (p - 1))
    return float(Fraction(sig) * Fraction(2) ** (e - p + 1))


def tie_cases(rng: random.Random, p: int, emin: int, emax: int) -> list:
    out = []
    # hand-picked: 1 + half ulp (even below), 1 + 3 half ulps (even above)
    ulp1 = float(Fraction(2) ** (1 - p))
    out += [1.0 + ulp1 / 2, 1.0 + 3 * ulp1 / 2, -(1.0 + ulp1 / 2), -(1.0 + 3 * ulp1 / 2)]
    # just off the midpoint, one Float ulp either way
    out += [next_up(1.0 + ulp1 / 2), next_down(1.0 + ulp1 / 2)]
    # the midpoint below 1 is finer: ulp below 1 is half of ulp above
    out += [1.0 - ulp1 / 4, 1.0 - 3 * ulp1 / 4]
    for _ in range(40):
        e = rng.randint(emin, emax - 1)
        sig = rng.getrandbits(p - 1) | (1 << (p - 1))
        half = Fraction(1, 2)
        mid = (Fraction(sig) + half) * Fraction(2) ** (e - p + 1)
        x = float(mid)
        assert Fraction(x) == mid
        sign = -1.0 if rng.random() < 0.5 else 1.0
        out.append(sign * x)
        # and a nudge either side, which must not tie
        out.append(sign * (next_up(x) if rng.random() < 0.5 else next_down(x)))
    return out


def subnormal_cases(rng: random.Random, p: int, emin: int, emax: int) -> list:
    tiny = min_subnormal(p, emin)
    normal_min = float(Fraction(2) ** emin)
    out = [
        tiny, -tiny, tiny / 2, -tiny / 2, next_up(tiny / 2), next_down(tiny / 2),
        3 * tiny / 2, 5 * tiny / 2, tiny * 7, tiny * 0.3, -tiny * 0.7,
        normal_min, next_down(normal_min), normal_min - tiny / 2, normal_min / 3,
        # Float's own subnormals and its smallest normal: far below every grid
        5e-324, -5e-324, 2.2250738585072014e-308, 1e-310,
        1e-40, -1e-40, 9.2e-41, 1e-45, 1e-7, 6e-8, 6.1e-8, 5.9e-8, 2.98e-8,
    ]
    for _ in range(40):
        # a random point in the subnormal range, mostly off the grid
        k = rng.uniform(0, float(2 ** (p - 1)))
        out.append(float(Fraction(k) * Fraction(tiny)))
        # and one exactly on it
        out.append(float(rng.randint(1, 2 ** (p - 1) - 1) * Fraction(tiny)))
    return out


def overflow_cases(rng: random.Random, p: int, emin: int, emax: int) -> list:
    top = max_finite(p, emax)
    ulp_top = float(Fraction(2) ** (emax - p + 1))
    mid = top + ulp_top / 2
    out = [
        top, -top, mid, -mid, next_down(mid), next_up(mid), top + ulp_top / 4,
        top * 1.5, top * 2, -top * 2, float(Fraction(2) ** (emax + 1)),
        1.7976931348623157e308, -1.7976931348623157e308, 1e308, 1e200,
        INF, -INF, NAN, 0.0, -0.0,
        3.4e38, 3.39e38, 65504.0, 65520.0, 65519.0, 65535.0, 65536.0, 1e5,
    ]
    for _ in range(30):
        # random values within a few binades of the top, on either side
        out.append(float(Fraction(rng.uniform(0.5, 4.0)) * Fraction(top)) * (1 if rng.random() < 0.7 else -1))
    return out


def random_cases(rng: random.Random, p: int, emin: int, emax: int) -> list:
    out = []
    while len(out) < 80:
        x = struct.unpack("d", struct.pack("Q", rng.getrandbits(64)))[0]
        if math.isfinite(x):
            out.append(x)
    # plus values of ordinary size, which random bit patterns rarely are
    for _ in range(40):
        out.append(rng.uniform(-1000.0, 1000.0))
    for _ in range(20):
        out.append(rng.uniform(-1.0, 1.0) * 10.0 ** rng.randint(-45, 38))
    return out


def binary_cases(rng: random.Random, op: str, p: int, emin: int, emax: int) -> list:
    tiny = min_subnormal(p, emin)
    top = max_finite(p, emax)
    ulp1 = float(Fraction(2) ** (1 - p))
    one_plus = 1.0 + ulp1
    pairs = [
        # the sum 1 + 2^-p is a tie; so is (1 + ulp) + half ulp
        (1.0, ulp1 / 2), (one_plus, ulp1 / 2), (1.0, -ulp1 / 2),
        # cancellation is exact
        (1.0, 1.0), (one_plus, 1.0), (-1.0, 1.0),
        # overflow and the carry out of the top exponent
        (top, top), (top, ulp1 * top / 2), (-top, -top), (top, -top),
        # underflow: half the smallest subnormal ties to zero, of either sign
        (tiny, tiny), (tiny, -tiny), (-tiny, tiny), (tiny, 0.0), (0.0, -0.0),
        (-0.0, -0.0), (0.0, 0.0),
        # the special values
        (INF, 1.0), (INF, -INF), (-INF, -INF), (NAN, 1.0), (1.0, NAN), (INF, 0.0),
        (1.0, 0.0), (-1.0, 0.0), (1.0, -0.0), (0.0, 0.0), (0.0, INF), (top, tiny),
        (tiny, top), (0.1, 3.0), (2.0, 3.0), (1.0, 3.0), (10.0, 3.0), (1.0, 7.0),
        (0.5, 0.25),
    ]
    for _ in range(40):
        a = random_format_value(rng, p, emin, emax, emin, emax) * (1 if rng.random() < 0.5 else -1)
        b = random_format_value(rng, p, emin, emax, emin, emax) * (1 if rng.random() < 0.5 else -1)
        pairs.append((a, b))
    for _ in range(40):
        # nearby exponents, so add/sub actually round rather than absorb
        e = rng.randint(max(emin, -20), min(emax - 4, 20))
        a = random_format_value(rng, p, emin, emax, e, e) * (1 if rng.random() < 0.5 else -1)
        b = random_format_value(rng, p, emin, emax, e - 3, e + 3) * (1 if rng.random() < 0.5 else -1)
        pairs.append((a, b))
    for _ in range(12):
        # products and quotients that land in the subnormal range
        a = random_format_value(rng, p, emin, emax, emin, emin + 6)
        b = random_format_value(rng, p, emin, emax, 1, 6) if op == "div" else random_format_value(rng, p, emin, emax, -6, -1)
        pairs.append((a, b))
    # every input is rounded into the format first, so that each is a value
    # of it: the hand-picked literals are not all, and a random significand
    # below emin has more bits than the subnormal grid there allows. The
    # program constructs its operands the same way.
    pairs = [(round_float(a, p, emin, emax), round_float(b, p, emin, emax)) for a, b in pairs]
    return [(a, b, op_oracle(op, a, b, p, emin, emax)) for a, b in pairs]


def sqrt_cases(rng: random.Random, p: int, emin: int, emax: int) -> list:
    tiny = min_subnormal(p, emin)
    top = max_finite(p, emax)
    xs = [2.0, 3.0, 0.5, 4.0, 9.0, 1.0, 0.0, -0.0, -1.0, INF, -INF, NAN, tiny, 3 * tiny,
          top, next_down(top), float(Fraction(2) ** emin), 1e-7, 0.1, 10.0, 100.0, 1e10,
          2.0 * 2 ** -20, 1.0 + float(Fraction(2) ** (1 - p))]
    for _ in range(40):
        xs.append(random_format_value(rng, p, emin, emax, emin, emax))
    for _ in range(20):
        # subnormal inputs, whose roots are normal
        xs.append(float(rng.randint(1, 2 ** (p - 1) - 1) * Fraction(tiny)))
    for _ in range(20):
        xs.append(random_format_value(rng, p, emin, emax, -6, 6))
    xs = [round_float(x, p, emin, emax) for x in xs]
    return [(x, sqrt_oracle(x, p, emin, emax)) for x in xs]


# ---------------------------------------------------------------- Dawn text


def lit(x: float) -> str:
    """A Dawn Float expression with exactly this value, sign of zero included."""
    if math.isnan(x):
        return "(0.0 / 0.0)"
    if x == INF:
        return "(1.0 / 0.0)"
    if x == -INF:
        return "(-1.0 / 0.0)"
    if x == 0.0:
        return "(-0.0)" if math.copysign(1.0, x) < 0 else "0.0"
    s = repr(x)
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        s = f"{mant}E{exp}"
    elif "." not in s:
        s += ".0"
    return f"(-{s})" if neg else s


def chunked(items: list, n: int = 32) -> list:
    return [items[i : i + n] for i in range(0, len(items), n)]


def table_fns(name: str, ty: str, rows: list, render) -> tuple:
    """Table functions for one section: chunks, plus the one that joins them."""
    parts = chunked(rows)
    text = []
    names = []
    for i, part in enumerate(parts):
        fname = f"{name}_{i}"
        names.append(fname)
        text.append(f"fn {fname}() -> List[{ty}] = [")
        for row in part:
            text.append(f"  {render(row)},")
        text.append("]")
        text.append("")
    text.append(f"fn {name}() -> List[{ty}] = " + " ++ ".join(f"{n}()" for n in names))
    text.append("")
    return "\n".join(text), len(rows)


def generate() -> tuple:
    rng = random.Random(SEED)
    out = [
        "# GENERATED by scripts/narrow-contract/gen.py -- do not edit by hand.",
        "#     python3 scripts/narrow-contract/gen.py            # rewrite",
        "#     python3 scripts/narrow-contract/gen.py --check    # is it current?",
        "#",
        "# std/narrow against an exact rational oracle: every input and every",
        "# expected answer below was computed with fractions.Fraction from the",
        "# definition of round-to-nearest-even, and the two backends must both",
        "# reproduce them bit for bit. The sections and what each holds are",
        "# described at the top of the generator; narrow_round.expect says every",
        "# section disagrees on nothing.",
        "use std/io",
        "use std/narrow",
        "",
        "# Bitwise equality on Float: NaN matches NaN, and a zero must carry the",
        "# expected sign (the two zeros compare equal, their reciprocals do not).",
        "fn same(got: Float, want: Float) -> Bool =",
        "  if want != want {",
        "    got != got",
        "  } else if want == 0.0 {",
        "    got == 0.0 && 1.0 / got == 1.0 / want",
        "  } else {",
        "    got == want",
        "  }",
        "",
        "fn check1(label: String, f: fn(Float) -> Float, cases: List[(Float, Float)]) -> Int !io = {",
        "  var bad = 0",
        "  for (x, want) in cases {",
        "    let got = f(x)",
        "    if not same(got, want) {",
        "      bad = bad + 1",
        '      println("  ${label}(${x}) = ${got}, want ${want}")',
        "    }",
        "  }",
        '  println("${label}: ${len(cases)} cases, ${bad} bad")',
        "  bad",
        "}",
        "",
        "fn check2(label: String, f: fn(Float, Float) -> Float, cases: List[(Float, Float, Float)]) -> Int !io = {",
        "  var bad = 0",
        "  for (a, b, want) in cases {",
        "    let got = f(a, b)",
        "    if not same(got, want) {",
        "      bad = bad + 1",
        '      println("  ${label}(${a}, ${b}) = ${got}, want ${want}")',
        "    }",
        "  }",
        '  println("${label}: ${len(cases)} cases, ${bad} bad")',
        "  bad",
        "}",
        "",
    ]
    main = ["pub fn main() -> Unit !io = {", "  var bad = 0"]
    expect = []
    r1 = lambda row: f"({lit(row[0])}, {lit(row[1])})"
    r2 = lambda row: f"({lit(row[0])}, {lit(row[1])}, {lit(row[2])})"
    for name, p, emin, emax in FORMATS:
        sections = [
            ("ties", tie_cases(rng, p, emin, emax)),
            ("subnormal", subnormal_cases(rng, p, emin, emax)),
            ("overflow", overflow_cases(rng, p, emin, emax)),
            ("random", random_cases(rng, p, emin, emax)),
        ]
        round_total = 0
        for sec, xs in sections:
            rows = [(x, round_float(x, p, emin, emax)) for x in xs]
            text, n = table_fns(f"{name}_{sec}", "(Float, Float)", rows, r1)
            out.append(text)
            round_total += n
            label = f"{name} round {sec}"
            main.append(f'  bad = bad + check1("{label}", x => narrow.round_{name}(x), {name}_{sec}())')
            expect.append(f"{label}: {n} cases, 0 bad")
        assert round_total >= 174, (name, round_total)
        for op in ("add", "sub", "mul", "div"):
            rows = binary_cases(rng, op, p, emin, emax)
            text, n = table_fns(f"{name}_{op}", "(Float, Float, Float)", rows, r2)
            out.append(text)
            label = f"{name} {op}"
            main.append(
                f'  bad = bad + check2("{label}", (a, b) => narrow.to_f64(narrow.{op}(narrow.{name}(a), narrow.{name}(b))), {name}_{op}())'
            )
            expect.append(f"{label}: {n} cases, 0 bad")
        rows = sqrt_cases(rng, p, emin, emax)
        text, n = table_fns(f"{name}_sqrt", "(Float, Float)", rows, r1)
        out.append(text)
        label = f"{name} sqrt"
        main.append(f'  bad = bad + check1("{label}", a => narrow.to_f64(narrow.sqrt(narrow.{name}(a))), {name}_sqrt())')
        expect.append(f"{label}: {n} cases, 0 bad")
    main.append('  println("total: ${bad} bad")')
    main.append("}")
    expect.append("total: 0 bad")
    program = "\n".join(out) + "\n".join(main) + "\n"
    return program, "\n".join(expect) + "\n"


def main(argv: list) -> int:
    program, expect = generate()
    if argv[1:] == ["--check"]:
        stale = []
        if not PROGRAM.exists() or PROGRAM.read_text() != program:
            stale.append(PROGRAM)
        if not EXPECT.exists() or EXPECT.read_text() != expect:
            stale.append(EXPECT)
        if stale:
            for path in stale:
                print(f"STALE {path.relative_to(ROOT)}: not what gen.py generates", file=sys.stderr)
            print("rerun: python3 scripts/narrow-contract/gen.py", file=sys.stderr)
            return 1
        print("OK   narrow corpus matches its generator")
        return 0
    if argv[1:]:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    PROGRAM.write_text(program)
    EXPECT.write_text(expect)
    print(f"wrote {PROGRAM.relative_to(ROOT)} and {EXPECT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

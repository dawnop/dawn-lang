#!/usr/bin/env python3
"""Directed, adaptive MPFR intervals for the binary64 accuracy contract.

The unit is the binade of the real answer, clamped to 2^-1074, not the
integer distance from a rounded reference. Unresolved intervals are errors.
Only this offline auditor needs libmpfr; CI can verify frozen interval
witnesses with rational arithmetic. No host transcendental is an oracle.
"""
import ctypes as C
from fractions import Fraction
import struct

MASK = (1 << 64) - 1
INF = 0x7ff0000000000000
NAN = 0x7ff8000000000000


def bits(x):
    return struct.unpack('>Q', struct.pack('>d', x))[0]


def value(x):
    return struct.unpack('>d', struct.pack('>Q', int(x) & MASK))[0]


def canonical(x):
    return NAN if (x & (INF | ((1 << 52) - 1))) > INF else x & MASK


class Number(C.Structure):
    _fields_ = [('precision', C.c_long), ('sign', C.c_int),
                ('exponent', C.c_long), ('limbs', C.c_void_p)]


class Oracle:
    def __init__(self):
        self.lib = C.CDLL('libmpfr.so.6')
        self.functions = {}
        self.version = self.bind('get_version', [], C.c_char_p)().decode()
        self.init = self.bind('init2', [C.POINTER(Number), C.c_long], None)
        self.clear = self.bind('clear', [C.POINTER(Number)], None)
        self.prec = self.bind('set_prec', [C.POINTER(Number), C.c_long], None)
        self.set = self.bind('set_d', [C.POINTER(Number), C.c_double, C.c_int])
        self.get = self.bind('get_d', [C.POINTER(Number), C.c_int], C.c_double)
        self.nan = self.bind('nan_p', [C.POINTER(Number)])
        self.inf = self.bind('inf_p', [C.POINTER(Number)])
        self.zero = self.bind('zero_p', [C.POINTER(Number)])
        self.getstr = self.bind('get_str', [C.c_void_p, C.POINTER(C.c_long), C.c_int,
                                          C.c_size_t, C.POINTER(Number), C.c_int], C.c_void_p)
        self.freestr = self.bind('free_str', [C.c_void_p], None)
        self.args = [Number() for _ in range(3)]
        self.lo, self.hi = Number(), Number()
        for n in [*self.args, self.lo, self.hi]:
            self.init(C.byref(n), 256)

    def bind(self, name, args, ret=C.c_int):
        fn = getattr(self.lib, 'mpfr_' + name)
        fn.argtypes, fn.restype = args, ret
        return fn

    def fraction(self, n):
        exponent = C.c_long()
        ptr = self.getstr(None, C.byref(exponent), 2, 0, C.byref(n), 0)
        s = C.string_at(ptr).decode()
        self.freestr(ptr)
        sign = -1 if s.startswith('-') else 1
        s = s.lstrip('-')
        q = sign * int(s, 2)
        e = exponent.value - len(s)
        return Fraction(q << e) if e >= 0 else Fraction(q, 1 << -e)

    def interval(self, name, inputs, minimum_precision=256):
        # StrictMath's explicitly specified IEEE core exception to MPFR pow.
        if name == 'pow' and abs(value(inputs[0])) == 1 and (abs(value(inputs[1])) == float('inf') or value(inputs[1]) != value(inputs[1])):
            return {'bits': NAN, 'precision': 256, 'class': 'nan'}
        count = {'pow': 2, 'hypot': 2, 'atan2': 2, 'fma': 3}.get(name, 1)
        if name not in self.functions:
            self.functions[name] = self.bind(name, [C.POINTER(Number)] * (count + 1) + [C.c_int])
        fn = self.functions[name]
        for n, raw in zip(self.args, inputs):
            self.set(C.byref(n), value(raw), 0)
        for precision in [256, 512, 1024, 2048, 4096, 8192, 16384]:
            if precision < minimum_precision: continue
            for n, rounding in [(self.lo, 3), (self.hi, 2)]:
                self.prec(C.byref(n), precision)
                fn(C.byref(n), *[C.byref(a) for a in self.args[:count]], rounding)
            a = canonical(bits(self.get(C.byref(self.lo), 0)))
            b = canonical(bits(self.get(C.byref(self.hi), 0)))
            if a != b:
                continue
            if self.nan(C.byref(self.lo)):
                return {'bits': a, 'precision': precision, 'class': 'nan'}
            if self.inf(C.byref(self.lo)) or a & ((1 << 63) - 1) == INF:
                return {'bits': a, 'precision': precision, 'class': 'infinity'}
            if self.zero(C.byref(self.lo)) and self.zero(C.byref(self.hi)):
                # RN determines the exact zero sign, including exact FMA cancellation.
                fn(C.byref(self.lo), *[C.byref(n) for n in self.args[:count]], 0)
                return {'bits': bits(self.get(C.byref(self.lo), 0)), 'precision': precision, 'class': 'zero'}
            if max(self.lo.exponent, self.hi.exponent) < -1075:
                # MPFR itself can underflow for exp(very negative). Enclose
                # its directed endpoints on a small dyadic grid instead of
                # allocating a denominator with billions of bits.
                lo, hi = (Fraction(-1, 1 << 1076), Fraction(0)) if a >> 63 else (Fraction(0), Fraction(1, 1 << 1076))
            else:
                lo, hi = self.fraction(self.lo), self.fraction(self.hi)
            if self.lo.exponent != self.hi.exponent and max(self.lo.exponent, self.hi.exponent) > -1022 and not (name == 'tanh' or (name == 'expm1' and value(inputs[0]) < 0)):
                continue
            # A finite nonzero tanh is strictly between -1 and 1. If an
            # outward endpoint is exactly 1, the inner binade is the true one.
            exponent = max(min(self.lo.exponent, self.hi.exponent) - 1, -1022) - 52
            unit = Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)
            # Return exact endpoint encodings, so a reader can recheck the bound.
            return {'bits': a, 'precision': precision, 'class': 'finite',
                    'lo': str(lo), 'hi': str(hi), 'unit': str(unit)}
        raise RuntimeError(f'undecided MPFR interval: {name} {inputs}')

    def close(self):
        for n in [*self.args, self.lo, self.hi]:
            self.clear(C.byref(n))


def error(interval, actual):
    """An outward rational error bound; non-NaN classifications are exact."""
    actual = canonical(actual)
    if interval['class'] != 'finite':
        if actual != canonical(interval['bits']):
            raise AssertionError(('classification', interval, actual))
        return Fraction(0)
    f = value(actual)
    if abs(f) == float('inf') or f != f:
        raise AssertionError(('finite', interval, actual))
    if f == 0 and (actual >> 63) != (interval['bits'] >> 63):
        raise AssertionError(('zero sign', interval, actual))
    y = Fraction(f)
    return max(abs(y - Fraction(interval['lo'])), abs(y - Fraction(interval['hi']))) / Fraction(interval['unit'])

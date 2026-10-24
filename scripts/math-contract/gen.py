#!/usr/bin/env python3
"""Rebuild the fixed raw-bit corpus using pinned StrictMath and MPFR witnesses.

--check never blesses changed output. --record-mpfr separately regenerates the
compensated-function witnesses with adaptive directed MPFR intervals; ordinary
CI consumes these frozen witnesses and checks their rational rounding/bounds.
The PRNG, input construction and oracle version are part of manifest.json.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess
from fractions import Fraction
from mpfr import Oracle, bits, value, canonical, error

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'scripts/math-contract'
SEED = 20261024
UNARY = 'exp exp2 expm1 log log2 log10 log1p sin cos tan asin acos atan sinh cosh tanh cbrt sqrt floor ceil trunc round round_even'.split()
BINARY = ['pow', 'hypot', 'atan2']
REGISTRY = json.loads((HERE/'oracle-differences.json').read_text())
CORRECTED = list(REGISTRY['mpfr_oracles'])
MASK = (1 << 64) - 1


def signed(x):
    return x - (1 << 64) if x >> 63 else x


def label(row):
    op, x, *_ = row
    if op in ["sin", "cos", "tan"] and math.isfinite(value(x)) and abs(value(x)) > 2**20: return op + "/large"
    if op == "round": return "round/boundary"
    a = x & ((1<<63)-1)
    if a == 0 or a >= 0x7ff0000000000000: return op + "/special"
    if a < (1<<52): return op + "/subnormal"
    if op in ['exp','expm1','sinh','cosh','exp2'] and abs(value(x)) > 700: return op + "/range"
    if op in ['log','log2','log10','log1p'] and abs(value(x)-1) < 2**-20: return op + "/near-one"
    return op


def line(row, labeled=True):
    op, *xs = row
    return (label(row) if labeled else op) + ' ' + ' '.join(str(signed(x)) for x in xs) + '\n'


def corpus(extra=0):
    rng = random.Random(SEED)
    special = [0, 1 << 63, 1, (1 << 63) | 1, (1 << 52) - 1, 1 << 52,
               (1 << 52) + 1, 0x7fefffffffffffff, 0xffefffffffffffff,
               0x7ff0000000000000, 0xfff0000000000000, 0x7ff8000000000001,
               0xfff8123456789abc]
    rows = []
    def add(op, x, y=0, z=0): rows.append((op, x & MASK, y & MASK, z & MASK))
    def nearby(op, x, y=0):
        b = bits(x)
        for d in [-2, -1, 0, 1, 2]: add(op, b + d, y)
    for op in UNARY:
        for x in special: add(op, x)
        for x in [-22., -2., -1., -0.5, -2**-28, 2**-28, 0.5, 1., 2., 22.]: nearby(op, x)
        for _ in range(64 + extra): add(op, rng.getrandbits(64))
    for op in ['exp', 'expm1', 'sinh', 'cosh']:
        for x in [-745.1332191019411, -708.3964185322641, 709.782712893384, 710.475860073944]: nearby(op, x)
        for _ in range(64 + extra): add(op, bits(rng.uniform(-746, 711)))
    for x in [-1075., -1074., -1022., 1023., 1024.]: nearby('exp2', x)
    for k in range(-1074, 1024): add('exp2', bits(float(k)))
    for k in range(-1074, 1024):
        x = bits(math.ldexp(1., k))
        for op in ['log', 'log2', 'log10']: add(op, x)
    for layer in range(1,2047):
        raw=(layer<<52)|rng.getrandbits(52)
        for op in ['log','log2','log10']:add(op,raw)
    for op in ['log', 'log2', 'log10', 'log1p']:
        for _ in range(64 + extra):
            x = rng.getrandbits(63)
            if x < 0x7ff0000000000000: add(op, x)
    for op in ['sin', 'cos', 'tan']:
        for k in [1, 2, 3, 17, 31, 2**19, 2**20, 2**52, 2**100, 2**500, 2**1000]:
            for sign in [-1, 1]: nearby(op, sign * k * math.pi / 2)
        for x in [1.7765241907548024e269, 1e300, 1e100, 1e20]: nearby(op, x)
    for op in ['asin', 'acos', 'atan', 'tanh', 'cbrt']:
        for _ in range(128 + extra): add(op, bits(rng.uniform(-1, 1)))
    for x in [float.fromhex('-0x1.da5766c3b4b00p-3'), 0.0, 1., 22., 2**-28]: nearby('tanh', x)
    for op in BINARY:
        for x in special + [bits(-1.), bits(1.)]:
            for y in special + [bits(-1.), bits(1.), bits(0.5), bits(3.)]: add(op, x, y)
        for _ in range(128 + extra): add(op, rng.getrandbits(64), rng.getrandbits(64))
    for x in [-1., 0., 1.]:
        for y in [-2., -0.5, 0.5, 3., 2**31+1, 2**52-1, 2**52, 2**53]: nearby('pow', x, bits(y))
    for k in [-1074, -1022, -500, 0, 500, 1023]:
        for j in [-1074, -1022, -500, 0, 500, 1023]: add('hypot', bits(math.ldexp(1., k)), bits(math.ldexp(1., j)))
    for x in [-2.5, -1.5, -0.5, -0., 0., 0.49999999999999994, 0.5, 1.5, 2.5]:
        for op in ['floor', 'ceil', 'trunc', 'round', 'round_even']: nearby(op, x)
    for args in [(1+2**-27, 1-2**-27, -1.), (value(1), 0.5, value(1)),
                 (value(0x7fefffffffffffff), 2., -value(0x7fefffffffffffff)),
                 (0., math.inf, 1.), (math.inf, 1., -math.inf),
                 (1., 2**-1000, 2**1000), (-0., 1., -0.), (1., 1., -1.),
                 (-0., 1., 0.), (0., 1., -0.)]:
        add('fma', *map(bits, args))
    for _ in range(100):add('fma',rng.getrandbits(64),rng.getrandbits(64),rng.getrandbits(64))
    # Inputs on either side of the square of exact root midpoints.
    for root in [0.75,1.,1.5,2.,math.sqrt(2.),math.ldexp(1.,500),math.ldexp(1.,-500)]:
        midpoint=(Fraction(root)+Fraction(math.nextafter(root,math.inf)))/2
        center=bits(float(midpoint*midpoint))
        for d in [-1,0,1]:add('sqrt',center+d)
    # Tiny rounding sqrt inputs and every exponent layer (subnormal included).
    for b in [1, 2, 3, (1<<52)-1, 1<<52, bits(2.), bits(4.)]:
        for d in [-1, 0, 1]:
            if b+d >= 0: add('sqrt', b+d)
    for op,x,y,z in [['sinh', '-4626150516536001627', '0', '0'], ['sinh', '-4573915590664044557', '0', '0'], ['sinh', '-4612406936605628416', '0', '0'], ['cosh', '4649458370416596732', '0', '0'], ['cosh', '4621419887588836800', '0', '0'], ['atan2', '-3088086972424488266', '-3095437049298422897', '0']]:
        for d in [-2,-1,0,1,2]: add(op,int(x)+d,int(y),int(z))
    if extra:
        # Reproduce the K1 tanh stream, including its 117 >1 ulp witnesses.
        state=20261024
        for _ in range(20000):
            state=state*16807%2147483647
            add('tanh',bits((state/2147483647.0)*40.0-20.0))
        # Reduction cells and every exponent layer, on both sides of ties.
        for k in range(-1075,1025):
            for point in [float(k),k+0.5]:nearby('exp2',point)
        for op,x,y,z in [['sinh', '-4626150516536001627', '0', '0'], ['sinh', '-4573915590664044557', '0', '0'], ['sinh', '-4612406936605628416', '0', '0'], ['cosh', '4649458370416596732', '0', '0'], ['cosh', '4621419887588836800', '0', '0'], ['atan2', '-3088086972424488266', '-3095437049298422897', '0']]:
            for d in range(-256,257):add(op,int(x)+d,int(y),int(z))
        for d in range(-32,33):
            for x in [bits(1.)+d,bits(-1.)+d]:
                for k in range(20,65):
                    for y in [2.0**k-1,2.0**k,2.0**k+1,-2.0**k]:add('pow',x,bits(y))
        for _ in range(5000):
            x=math.ldexp(1+rng.random(),rng.randint(-1022,1022))
            for delta in [-60,-54,-53,-26,-1,0]:
                y=math.ldexp(x,delta)
                add('hypot',bits(x),bits(y))
            y=math.nextafter(x,math.inf)
            for sx,sy in [(1,1),(-1,1),(1,-1),(-1,-1)]:add('atan2',bits(sy*y),bits(sx*x))
    # Stable de-duplication does not hide distinct labels or signed zeros.
    return list(dict.fromkeys(rows))


def java_oracle(rows):
    java = os.environ.get('JAVA_HOME', '')
    java = str(Path(java) / 'bin/java') if java else subprocess.check_output(
        [str(ROOT/'bin/dawn'), '--version'], env={**os.environ, 'DAWN_LAUNCHER_PRINT_JAVA': '1'}, text=True).strip()
    data = ''.join(line(r, False) for r in rows)
    p = subprocess.run([java, str(HERE/'Oracle.java')], input=data, text=True, capture_output=True, check=True)
    ans = [int(s) & MASK for s in p.stdout.splitlines()]
    if len(ans) != len(rows): raise RuntimeError('StrictMath oracle dropped rows')
    return ans


def program(rows):
    head = '''# Generated by scripts/math-contract/gen.py. Inputs and expected bits have
# independent StrictMath/MPFR provenance. Read raw bits so decimal parsing
# cannot erase hard cases, NaN class, subnormals or either zero sign.
use std/math
use std/float
use std/narrow
use std/io
use std/str

fn raw(x: Float) -> Int = if float.is_nan(x) { 0x7ff8000000000000 } else { narrow.f64_bits(x) }
fn direct(op: String, x: Float, y: Float, z: Float) -> Float = match op {
'''
    for op in UNARY: head += f'  "{op}" -> math.{op}(x)\n'
    for op in BINARY: head += f'  "{op}" -> math.{op}(x, y)\n'
    head += '  "fma" -> math.fma(x, y, z)\n  _ -> panic("unknown math operation")\n}\n'
    head += '\nfn unary(op: String) -> fn(Float) -> Float = match op {\n'
    for op in UNARY: head += f'  "{op}" -> math.{op}\n'
    head += '  _ -> math.abs\n}\nfn binary(op: String) -> fn(Float, Float) -> Float = match op {\n'
    for op in BINARY: head += f'  "{op}" -> math.{op}\n'
    head += '  _ -> math.hypot\n}\n'
    # Each family includes a nontrivial compile-time input and boundary specials.
    constants = []
    for op in UNARY + BINARY + ['fma']:
        chosen = [r for r in rows if r[0] == op]
        # Include the known tanh failure, huge reduction, subnormal, and normal.
        candidates = [chosen[0], chosen[2], next((r for r in chosen if r[1] == bits(0.5)), chosen[-1]), chosen[-1]]
        if op in ['sin','cos','tan']: candidates.append((op, bits(1e300), 0, 0))
        if op == 'tanh': candidates.append((op, bits(float.fromhex('-0x1.da5766c3b4b00p-3')),0,0))
        if op == 'fma':
            candidates.extend([('fma',bits(1.),bits(1.),bits(-1.)),
                               ('fma',bits(-0.),bits(1.),bits(0.)),
                               ('fma',bits(-0.),bits(1.),bits(-0.))])
        for row in dict.fromkeys(candidates):
            name=f'C{len(constants)}';constants.append(row)
            _, x,y,z=row
            head+=f'const {name}: Int = raw(direct("{op}", narrow.f64_of_bits({signed(x)}), narrow.f64_of_bits({signed(y)}), narrow.f64_of_bits({signed(z)})))\n'
    head+='\npub fn main() -> Unit !io = {\n'
    for i,r in enumerate(constants): head+=f'  println("const/{r[0]} ${{C{i}}} ${{C{i}}}")\n'
    head+='''  var count = 0
  while true {
    match io.read_line() {
      None -> break
      Some(line) -> {
        let p = str.split(line, " ")
        let section = p[0]
        let op = str.split(section, "/")[0]
        let x = narrow.f64_of_bits(parse_int(p[1]).expect("input x"))
        let y = narrow.f64_of_bits(parse_int(p[2]).expect("input y"))
        let z = narrow.f64_of_bits(parse_int(p[3]).expect("input z"))
        let a = raw(direct(op, x, y, z))
        let b = raw(if op == "fma" { let f = math.fma
          f(x, y, z) } else if op == "pow" || op == "hypot" || op == "atan2" { binary(op)(x, y) } else { unary(op)(x) })
        println("${section} ${a} ${b}")
        count = count + 1
      }
    }
  }
  println("complete ${count}")
}
'''
    return head, constants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--record-mpfr', action='store_true')
    parser.add_argument('--inputs-only', type=Path)
    parser.add_argument('--extra', type=int, default=0)
    args = parser.parse_args()
    rows = corpus(args.extra)
    if args.inputs_only:
        args.inputs_only.write_text(''.join(line(r) for r in rows)); return
    src, constants = program(rows)
    allrows = constants + rows
    transcendental = set(UNARY[:17] + BINARY)
    if transcendental != set(CORRECTED) | set(REGISTRY['strictmath_equal']): raise AssertionError('incomplete oracle registry')
    strict_rows = [r for r in allrows if r[0] not in CORRECTED]
    strict = iter(java_oracle(strict_rows))
    frozen_path = HERE/'mpfr-witnesses.json'
    if args.record_mpfr:
        oracle = Oracle()
        frozen = []
        for r in allrows:
            if r[0] in CORRECTED:
                interval = oracle.interval(r[0], r[1:])
                frozen.append({'input': r, 'interval': interval})
        oracle.close()
        frozen_path.write_text(json.dumps({'mpfr':oracle.version, 'rounding':'adaptive RNDD/RNDU, then binary64 RNDN', 'rows':frozen}, separators=(',',':'))+'\n')
    frozen = json.loads(frozen_path.read_text())
    witnesses = iter(frozen['rows'])
    targets=[]
    for row in allrows:
        if row[0] in CORRECTED:
            witness=next(witnesses)
            if tuple(witness['input']) != row: raise AssertionError('stale MPFR inputs')
            interval=witness['interval']; target=interval['bits']
            if error(interval,target) > Fraction(1,2): raise AssertionError('MPFR target is not nearest')
            if interval['class']=='finite':
                for endpoint in ['lo','hi']:
                    q=Fraction(interval[endpoint])
                    rounded=bits(float(q)) if q else target & (1<<63)
                    if rounded!=target:raise AssertionError('frozen MPFR interval does not decide nearest-even rounding')
            targets.append(target)
        else: targets.append(next(strict))
    if next(witnesses,None) is not None or next(strict,None) is not None: raise AssertionError('unused oracle rows')
    output=''
    for i,(r,want) in enumerate(zip(allrows,targets)):
        section=('const/'+r[0]) if i<len(constants) else label(r)
        output+=f'{section} {signed(canonical(want))} {signed(canonical(want))}\n'
    output+=f'complete {len(rows)}\n'
    inputs=''.join(line(r) for r in rows)
    products={'scripts/spike-native/math_contract.dawn':src,
              'scripts/spike-native/math_contract.stdin':inputs,
              'scripts/spike-native/math_contract.expect':output}
    digest=lambda b:hashlib.sha256(b).hexdigest()
    manifest={'generator':1,'seed':SEED,'prng':'Python random.Random MT19937; raw getrandbits(64) and uniform',
              'java':'21.0.2 StrictMath','mpfr':frozen['mpfr'], 'runtime_rows':len(rows),'comptime_rows':len(constants),
              'mpfr_witnesses_sha256':digest(frozen_path.read_bytes()),
              'products':{p:digest(s.encode()) for p,s in products.items()}}
    products['scripts/math-contract/manifest.json']=json.dumps(manifest,indent=2)+'\n'
    for path,text in products.items():
        p=ROOT/path
        if args.check:
            if not p.exists() or p.read_text()!=text: raise AssertionError(f'stale generated corpus: {path}')
        else:p.write_text(text)
    print(f'math-contract: {len(rows)} runtime rows, {len(constants)} comptime rows; independent oracle verified')

if __name__=='__main__': main()

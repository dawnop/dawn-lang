#!/usr/bin/env python3
"""Audit a real corpus execution against adaptive MPFR directed intervals.

Run gen.py --inputs-only INPUT --extra N, execute math_contract with that
input, then audit.py --inputs INPUT --actual OUTPUT --out REPORT. The tool
fails on any undecided interval, wrong special value or >1 ulp result.
This finite search complements the retained fdlibm analyses; it is not an
exhaustive proof over binary64 inputs.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from mpfr import Oracle, error, canonical

FUNCTIONS = set('exp exp2 expm1 log log2 log10 log1p sin cos tan asin acos atan atan2 sinh cosh tanh cbrt pow hypot sqrt fma'.split())


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--actual',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--binary',type=Path)
    p.add_argument('--backend',default='unspecified')
    a=p.parse_args()
    rows=[s.split() for s in a.inputs.read_text().splitlines()]
    actual=[s.split() for s in a.actual.read_text().splitlines() if not s.startswith('const/')]
    if actual[-1] != ['complete',str(len(rows))] or len(actual)!=len(rows)+1: raise AssertionError('incomplete execution')
    oracle=Oracle();summary={};failures=[];counts=Counter()
    for i,(row,got) in enumerate(zip(rows,actual)):
        section,*args=row
        op=section.split("/")[0]
        if got[0]!=section or len(got)!=3 or got[1]!=got[2]: raise AssertionError(('direct/function-value mismatch',i,row,got))
        if op not in FUNCTIONS: continue
        interval=oracle.interval(op,[int(x)&((1<<64)-1) for x in args])
        result=int(got[1])&((1<<64)-1)
        try: bound=error(interval,result)
        except AssertionError as e:
            failures.append({'row':i,'input':row,'output':got,'error':str(e)})
            continue
        if interval['class']=='finite' and bound>1:
            # Distinguish a proven violation from an interval straddling the
            # exact budget. Never accept an undecided boundary.
            for precision in [256,512,1024,2048,4096,8192,16384]:
                interval=oracle.interval(op,[int(x)&((1<<64)-1) for x in args],precision)
                bound=error(interval,result)
                y=Fraction(__import__('mpfr').value(result))
                lo,hi=Fraction(interval['lo']),Fraction(interval['hi'])
                lower=Fraction(0) if lo<=y<=hi else min(abs(y-lo),abs(y-hi))/Fraction(interval['unit'])
                if bound<=1 or lower>1:break
            else:raise RuntimeError(('undecided error budget',row,result))
        counts[op]+=1
        distance=abs(canonical(result)-canonical(interval['bits']))
        item=summary.setdefault(op,{'maximum_true_error':0.,'maximum_bit_distance':0,'count':0})
        item['count']+=1;item['maximum_bit_distance']=max(item['maximum_bit_distance'],distance)
        if float(bound)>=item['maximum_true_error']:
            # Round the displayed bound outward. Exact rationals remain in the witness.
            import math
            item.update(maximum_true_error=math.nextafter(float(bound),math.inf),
                        witness={'input':row,'output':result,'interval':interval,'error_bound':str(bound)})
        if bound>1:failures.append({'row':i,'input':row,'output':result,'interval':interval,'error_bound':str(bound)})
    report={'mpfr':oracle.version,'input_sha256':hashlib.sha256(a.inputs.read_bytes()).hexdigest(),
            'output_sha256':hashlib.sha256(a.actual.read_bytes()).hexdigest(),'all_intervals_decided':True,
            'functions':summary,'failures':failures,'finite_search_only':True,
            'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256((Path(__file__).resolve().parents[2]/'std/math.dawn').read_bytes()).hexdigest(),
            'generator_sha256':hashlib.sha256(Path(__file__).with_name('gen.py').read_bytes()).hexdigest(),
            'execution':{'backend':a.backend,'binary_sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest() if a.binary else None}}
    oracle.close();a.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'counts':dict(counts),'failures':len(failures),'mpfr':oracle.version}))
    if failures:
        for f in failures[:6]:print(f)
        raise SystemExit(1)

if __name__=='__main__':main()

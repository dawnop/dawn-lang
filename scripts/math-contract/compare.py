#!/usr/bin/env python3
"""Compare every raw result, including row identities and the completion marker.

NaNs have already been canonicalized by the corpus. A backend difference of
one ulp is fatal even when both values satisfy the separate accuracy budget.
"""
import argparse
from pathlib import Path
import sys


def compare(expect, actual, owner=None):
    wanted = Path(expect).read_text().splitlines()
    found = Path(actual).read_text().splitlines()
    if len(wanted) != len(found) or not found or found[-1] != wanted[-1]:
        raise AssertionError('corpus did not complete with the required row count')
    bad=[]
    for i,(a,b) in enumerate(zip(wanted,found),1):
        if a != b:
            if a.split()[0] != b.split()[0]: raise AssertionError(f'row identity moved at {i}')
            bad.append((i,a,b))
    if owner:
        owned=[b for b in bad if b[1].split()[0] == owner]
        if not owned: raise AssertionError(f'negative control did not turn {owner} red')
        print(f'PASS mutant: {owner}, {len(owned)} mismatches after successful completion')
        return
    if bad:
        for i,a,b in bad[:8]: print(f'row {i}: expected {a}; got {b}',file=sys.stderr)
        raise AssertionError(f'{len(bad)} raw-bit mismatches')
    print(f'PASS: {len(wanted)-1} raw-bit rows, direct calls and function values')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('expect');p.add_argument('actual');p.add_argument('--red-owner')
    a=p.parse_args();compare(a.expect,a.actual,a.red_owner)

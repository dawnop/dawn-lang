#!/usr/bin/env python3
"""Check pinned source hashes, distinct Sun notices, and embedded distribution.

This reads declarations and license text as data, not mutation locations.
The port stores constants as raw bits; decimal spellings cannot drift with a
host parser. Source snapshots retain the original approximation/error analyses.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'scripts/math-contract'


def main():
    manifest=json.loads((HERE/'fdlibm/manifest.json').read_text())
    source=(ROOT/'std/math.dawn').read_text()
    embedded=(ROOT/'selfhost/src/embed/stdsrc.dawn').read_text()
    notices=set()
    for item in manifest['files']:
        p=HERE/'fdlibm'/item['source']
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise AssertionError(f'source digest moved: {p.name}')
        notice=next(c for c in re.findall(r'/\*.*?\*/',p.read_text(),re.S) if 'Copyright' in c)
        notices.add(notice)
        rendered='\n'.join('# '+line.rstrip() for line in notice.splitlines())
        if rendered not in source:raise AssertionError(f'Sun notice missing from Dawn: {p.name}')
        escaped=rendered.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')
        if escaped not in embedded:raise AssertionError(f'Sun notice missing from embedded std: {p.name}')
    expected={f['source'] for f in manifest['files']}
    actual={p.name for p in (HERE/'fdlibm').glob('*.c')}
    if actual!=expected:raise AssertionError('unmapped source snapshots')
    audit=json.loads((HERE/'accuracy-audit.json').read_text())
    from mpfr import error
    if audit['failures'] or not audit['all_intervals_decided']:raise AssertionError('accuracy audit failed')
    if audit['source_sha256']!=hashlib.sha256((ROOT/'std/math.dawn').read_bytes()).hexdigest():raise AssertionError('stale algorithm audit')
    if audit['auditor_sha256']!=hashlib.sha256((HERE/'audit.py').read_bytes()).hexdigest():raise AssertionError('stale auditor evidence')
    if audit['generator_sha256']!=hashlib.sha256((HERE/'gen.py').read_bytes()).hexdigest():raise AssertionError('stale search generator evidence')
    registry=json.loads((HERE/'oracle-differences.json').read_text())
    required=set(registry['strictmath_equal'])|set(registry['mpfr_oracles'])|{'sqrt','fma'}
    if set(audit['functions'])!=required:raise AssertionError('missing audited function')
    for item in audit['functions'].values():
        witness=item['witness']
        if error(witness['interval'],witness['output'])>1:raise AssertionError('frozen accuracy witness exceeds 1 ulp')
    print(f'provenance: {len(expected)} pinned files, {len(notices)} distinct notices in source and embedded std')

if __name__=='__main__':main()

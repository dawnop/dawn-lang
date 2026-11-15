"""An observed program large enough for the C backend to cut into several units.

Every unit re-reads the shared head, so the names an observed body writes (its
site and definition slots) have to be declared there. A small program is one
unit and cannot show a slot that only unit 0 declares; this one is generated
big enough to be split, built on both backends from the same text, and held to
a value computed here, independently of either compiler.
"""
import os
import subprocess

from run import ROOT

FUNCTIONS = 450


def program(n=FUNCTIONS):
    out = ['use std/io', 'use std/provenance as p', 'fn f0(x: Int) -> Int = x + 1']
    for i in range(1, n):
        out.append(f'fn f{i}(x: Int) -> Int = {{\n'
                   f'  let a = f{i-1}(x) + {i}\n'
                   f'  let b = if a % 2 == 0 {{ a / 2 + {i % 7} }} else {{ a * 3 + 1 }}\n'
                   f'  let c = [a, b, {i}]\n'
                   f'  let s = to_string(b)\n'
                   f'  if len(s) > 100 {{ -1 }} else {{ c[0] % 1000003 + c[1] % 1000033 + len(s) }}\n'
                   f'}}')
    out.append(f'pub fn main() -> Unit !io = {{\n'
               f'  let (v, snap) = p.observe(scope => {{ (f{n-1}(5), p.completed(scope)) }})\n'
               f'  io.println(to_string(v))\n'
               f'  io.println(to_string(p.record_count(p.records(snap))))\n'
               f'}}\n')
    return '\n'.join(out)


def expected(n=FUNCTIONS):
    v = 5 + 1
    for i in range(1, n):
        a = v + i
        b = a // 2 + i % 7 if a % 2 == 0 else a * 3 + 1
        s = str(b)
        v = -1 if len(s) > 100 else a % 1000003 + b % 1000033 + len(s)
    return v


def split_units(run, name, source):
    units = run.out/(name+'-units')
    result = run.command(name+'-emit', run.compiler('__emitc', source, '--split', units))
    assert result.returncode == 0, (name, 'emit', result.stderr[-4000:])
    assert len(list(units.glob('tu*.c'))) >= 2, (name, 'program no longer splits into several units')
    return units


def link(run, label, units):
    env = dict(os.environ, CC=str(run.args.cc))
    exe = run.out/(label+'.bin')
    result = subprocess.run([str(ROOT/'scripts/cc-units.sh'), '-o', str(exe), str(units)],
                            cwd=ROOT, capture_output=True, text=True, env=env, timeout=run.args.timeout)
    (run.out/(label+'-cc.stderr')).write_text(result.stderr)
    return result, exe


def multi_tu_observe(run):
    name = 'multi-tu-observe'
    source = run.out/'multi_tu_observe.dawn'
    source.write_text(program())
    want = str(expected())

    jvm = run.command(name+'-jvm-run', run.build(name, source, 'jvm'))
    assert jvm.returncode == 0, (name, 'jvm run', jvm.stderr)
    units = split_units(run, name, source)
    result, exe = link(run, name+'-native', units)
    assert result.returncode == 0, (name, 'C compile', result.stderr[-6000:])
    native = run.command(name+'-native-run', [exe])
    assert native.returncode == 0, (name, 'native run', native.stderr)
    assert jvm.stdout.splitlines()[0] == want, (name, 'jvm value', jvm.stdout, want)
    assert native.stdout == jvm.stdout, (name, 'backends differ', native.stdout, jvm.stdout)
    assert int(native.stdout.splitlines()[1]) > 0, (name, 'no records observed')
    run.results.append({'case': name, 'backend': 'native', 'passed': True})
    print('PASS native+jvm', name, flush=True)

    # Negative control: the layout this case guards against, slot names
    # declared in unit 0 only. The very same C must then fail to compile.
    head = units/'dawn_prog.h'
    lines = head.read_text().split('\n')
    slots = [l for l in lines if l.startswith('enum { dawn_prov_')]
    assert slots, (name, 'no slot declarations in the shared head')
    head.write_text('\n'.join(l for l in lines if not l.startswith('enum { dawn_prov_')))
    first = units/'tu00.c'
    text = first.read_text()
    marker = '#include "dawn_prog.h"\n'
    assert text.startswith(marker), (name, 'unit 0 layout')
    first.write_text(marker+'\n'.join(slots)+'\n'+text[len(marker):])
    refused, _ = link(run, name+'-control', units)
    assert refused.returncode != 0 and 'dawn_prov_' in refused.stderr and 'undeclared' in refused.stderr, \
        (name, 'control: slot names declared in unit 0 only were accepted', refused.stderr[-2000:])
    run.results.append({'case': name+' control', 'backend': 'native', 'passed': True})
    print('PASS native', name, 'control: slots declared in unit 0 only are refused', flush=True)

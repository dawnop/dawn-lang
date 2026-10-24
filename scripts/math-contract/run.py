#!/usr/bin/env python3
"""Real backend executions, two compiler constant artifacts, and live controls.

The ordinary corpus is also a spike-native entry, including ASan. This harness
runs the same native/ASan recipe and requires clean positives alongside the
controls. The wasm leg is called by wasm-contract with its existing driver and
SDK. No optional tooling or missing backend is silently skipped.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from compare import compare

ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'scripts/math-contract'
PROGRAM=ROOT/'scripts/spike-native/math_contract.dawn'
INPUT=PROGRAM.with_suffix('.stdin')
EXPECT=PROGRAM.with_suffix('.expect')


def command(args, out=None, stdin=None, env=None):
    print('+ '+' '.join(str(a) for a in args[:3]),flush=True)
    with (open(out,'w') if out else tempfile.TemporaryFile(mode='w+')) as stdout:
        with (open(stdin) if stdin else open(os.devnull)) as data:
            p=subprocess.run([str(a) for a in args],cwd=ROOT,stdin=data,stdout=stdout,stderr=subprocess.PIPE,text=True,env=env)
        if p.returncode:
            print(p.stderr)
            if not out:
                stdout.seek(0);print(stdout.read())
            raise RuntimeError(f'command failed ({p.returncode}): {args}')
        if p.stderr and ('Sanitizer' in p.stderr or 'runtime error:' in p.stderr):raise AssertionError(p.stderr)
        return p.stderr


def native_build(c, binary, runtime, sanitize=False):
    flags=['-std=c11','-O1' if sanitize else '-O2','-fwrapv','-fexceptions','-fno-strict-aliasing','-ffp-contract=off','-pthread']
    if sanitize:flags+=['-fsanitize=address,undefined','-fno-omit-frame-pointer']
    command([os.environ.get('CC','cc'),*flags,'-I',ROOT/'runtime/c','-o',binary,c,runtime,'-lm'])


def emit(std, c):
    command([ROOT/'bin/dawn','__emitc','--std',std,PROGRAM,'-o',c])


def native(work):
    c=work/'clean.c';emit(ROOT/'std',c)
    out=work/'clean.jvm'
    command([ROOT/'bin/dawn','run','--std',ROOT/'std',PROGRAM],out,INPUT);compare(EXPECT,out)
    for sanitize in [False,True]:
        tag='asan' if sanitize else 'native';binary=work/tag;out=work/(tag+'.out')
        native_build(c,binary,ROOT/'runtime/c/dawn_rt.c',sanitize)
        command([binary],out,INPUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1'})
        compare(EXPECT,out)
    # Changing one backend by a single representable value must fail the same
    # raw-bit oracle. The function-value and folded values remain unchanged.
    text=c.read_text()
    text,count=re.subn(r'(?m)^(\s+\w+ = )(dawn_std_2math__exp\([^;]+\));$',r'\1nextafter(\2, INFINITY);',text)
    if count!=1:raise AssertionError(f'generated C exp call is not unique: {count}')
    mutant=work/'one-ulp.c';mutant.write_text(text)
    binary=work/'one-ulp';native_build(mutant,binary,ROOT/'runtime/c/dawn_rt.c')
    out=work/'one-ulp.out';command([binary],out,INPUT);compare(EXPECT,out,'exp')
    runtime=work/'runtime.o'
    command([os.environ.get('CC','cc'),'-std=c11','-O2','-fwrapv','-fexceptions','-fno-strict-aliasing','-ffp-contract=off','-pthread','-I',ROOT/'runtime/c','-c',ROOT/'runtime/c/dawn_rt.c','-o',runtime])
    for name,owner in [('exp-term','exp'),('reduction-split','sin/large'),('round-half','round/boundary')]:
        fork=work/name;fork.mkdir();shutil.copytree(ROOT/'std',fork/'std')
        command(['python3',HERE/'mutate.py',name,fork])
        c=fork/'mutant.c';emit(fork/'std',c)
        binary=fork/'mutant';native_build(c,binary,runtime)
        out=fork/'native.out';command([binary],out,INPUT);compare(EXPECT,out,owner)
        out=fork/'jvm.out';command([ROOT/'bin/dawn','run','--std',fork/'std',PROGRAM],out,INPUT);compare(EXPECT,out,owner)


def wasm(work, driver):
    # The bytes are emitted by two actual compilers, so a host-dependent
    # comptime result moves an artifact before any backend is run.
    c=work/'jvm-compiler.c';emit(ROOT/'std',c)
    n=work/'native-compiler.c';command([driver,'emitc','--std',ROOT/'std',PROGRAM,'-o',n])
    if c.read_bytes()!=n.read_bytes():raise AssertionError('JVM/native compiler constant artifacts differ')
    print('PASS: identical emitted constant artifacts from JVM and native compilers',flush=True)
    cc=os.environ.get('DAWN_WASM_CC','clang')
    crt=subprocess.check_output([cc,'--target=wasm32-wasip1','-print-file-name=crt1.o'],text=True).strip()
    target='wasm32-wasip1' if Path(crt).is_file() else 'wasm32-wasi'
    shim=work/'shim.o';tag=work/'tag.o'
    command([cc,'--target='+target,'-x','c++','-std=c++14','-O2','-fno-rtti','-fwasm-exceptions','-c',ROOT/'runtime/c/dawn_rt_wasi_eh.cc','-o',shim])
    command([cc,'--target='+target,'-std=c11','-O2','-ffp-contract=off','-c',ROOT/'runtime/c/dawn_rt_wasi_tag.c','-o',tag])
    for label,src in [('jvm-compiler',c),('native-compiler',n)]:
        binary=work/(label+'.wasm');out=work/(label+'.out')
        command([cc,'--target='+target,'-std=c11','-O2','-fwrapv','-fwasm-exceptions','-fno-strict-aliasing','-ffp-contract=off','-Wno-parentheses-equality','-I',ROOT/'runtime/c','-o',binary,src,ROOT/'runtime/c/dawn_rt.c',shim,tag,'-lm'])
        stderr=command(['node','--no-warnings',ROOT/'scripts/wasm-contract/runwasi.mjs',binary],out,INPUT,env={**os.environ,'DAWN_RC_BALANCE':'1'})
        if 'rc-balance: 0\n' not in stderr:raise AssertionError('wasm did not release every counted object: '+stderr)
        compare(EXPECT,out)
        # Execute each compiler's constant artifact natively as well.
        native_bin=work/(label+'.native');native_build(src,native_bin,ROOT/'runtime/c/dawn_rt.c')
        native_out=work/(label+'.native.out');command([native_bin],native_out,INPUT);compare(EXPECT,native_out)


def main():
    p=argparse.ArgumentParser();p.add_argument('--wasm',action='store_true');p.add_argument('--driver',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args();start=time.monotonic()
    command(['python3',HERE/'gen.py','--check'])
    command(['python3',HERE/'provenance.py'])
    with tempfile.TemporaryDirectory(prefix='math-contract-') as tmp:
        work=a.out or Path(tmp);work.mkdir(parents=True,exist_ok=True)
        if a.wasm:
            if not a.driver:raise ValueError('--wasm requires the existing native driver')
            wasm(work,a.driver.resolve())
        else:native(work)
    print(f'math-contract: PASS, wall-clock {time.monotonic()-start:.2f}s',flush=True)

if __name__=='__main__':main()

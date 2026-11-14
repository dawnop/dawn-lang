#!/usr/bin/env python3
"""Instrument a complete golden project, without editing tileir or call marks.

The source index comes from the compiler parser, before recording. Each trace
is consumed through the public bulk API. Golden verdicts stay in run.sh.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def instrument(project, compiler, java):
    source = project/'src/main.dawn'
    text = source.read_text()
    if 'fn provenance_trace(' in text:
        raise ValueError('project already instrumented')
    text = re.sub(r'\btrace\(', 'provenance_trace(', text)
    text = text.replace('fn provenance_trace(name:', 'fn trace_raw(name:', 1)
    starts=list(re.finditer(r'^(?:pub )?fn ([a-zA-Z_0-9]+)\(',text,re.M))
    chunks=[text[m.start():starts[i+1].start() if i+1<len(starts) else len(text)] for i,m in enumerate(starts)]
    names=[m[1] for m in starts]
    changed={'provenance_trace'}
    changed|={name for name,chunk in zip(names,chunks) if 'fn() -> TileProg' in chunk[:chunk.index('=')]}
    while True:
        more={name for name,chunk in zip(names,chunks) if name!='trace_raw' and any(re.search(r'\b'+callee+r'\(',chunk.split('=',1)[-1]) for callee in changed)}
        if more<=changed: break
        changed|=more
    for i,(name,chunk) in enumerate(zip(names,chunks)):
        if name in changed:
            chunk=chunk.replace('fn() -> TileProg','fn() -> TileProg !io')
            at=chunk.index('=')
            if not re.search(r'!io\s*$',chunk[:at]): chunk=chunk[:at].rstrip()+' !io '+chunk[at:]
            chunks[i]=chunk
    text=text[:starts[0].start()]+''.join(chunks)
    text='use std/provenance as provenance\nuse provenance_preview as preview\nuse provenance_preview.{SourceIndex}\nuse provenance_source as source_index\n'+text
    cached='  let first = provenance_trace(name)\n  let second = provenance_trace(name)'
    if text.count(cached)!=1: raise ValueError('two-trace source anchor changed')
    text=text.replace(cached,'  let preview_source = source_index.make()\n  let first = provenance_trace(name, preview_source)\n  let second = provenance_trace(name, preview_source)')
    text+='\nfn provenance_trace(name: String, source: SourceIndex = source_index.make()) -> TileProg !io = {\n  let (program, snapshot) = provenance.observe(scope => {\n    let program = trace_raw(name)\n    (program, provenance.completed(scope))\n  })\n  let mapping = preview.consume(snapshot, source, source_index.revision())\n  if len(mapping.owners) == 0 || len(mapping.nodes) == 0 { panic("preview: empty source mapping") }\n  program\n}\n'
    text+='\npub fn provenance_check_case(name: String) -> (String, Bytes) !io = {\n  let program = trace_twice(name)\n  (render(program), encode(program))\n}\n'
    source.write_text(text)
    prepare_index(project, compiler, java)


def prepare_index(project, compiler, java):
    source = project/'src/main.dawn'
    shutil.copyfile(HERE/'preview.dawn',project/'src/provenance_preview.dawn')
    revision=hashlib.sha256(source.read_bytes()).hexdigest()
    cache_name=os.environ.get('DAWN_PROVENANCE_INDEX_CACHE')
    consumer_sha=hashlib.sha256((HERE/'preview.dawn').read_bytes()).hexdigest()
    generator_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    cache=Path(cache_name)/(revision+'-'+consumer_sha[:16]+'-'+generator_sha[:16]) if cache_name else None
    if cache and cache.is_dir():
        for name in ['parser-index.txt','provenance-identity.json']:
            shutil.copyfile(cache/name,project/name)
        identity=json.loads((project/'provenance-identity.json').read_text())
        if identity['source_sha256']!=revision or identity['consumer_sha256']!=consumer_sha or identity['generator_sha256']!=generator_sha:
            raise ValueError('frozen source index identity mismatch')
        for name,sha in identity['modules'].items():
            if Path(name).name!=name: raise ValueError('invalid cached source module')
            data=(cache/name).read_bytes()
            if hashlib.sha256(data).hexdigest()!=sha: raise ValueError('source index module changed')
            (project/'src'/name).write_bytes(data)
        return
    if os.environ.get('DAWN_PROVENANCE_REQUIRE_INDEX_CACHE')=='1':
        raise ValueError('frozen source index missing: '+revision)
    index=project/'parser-index.txt' 
    result=subprocess.run([java,'-Xss512m','-Xmx2g','-jar',str(compiler),'run','--std',str(ROOT/'std'),str(HERE/'source-index'),'--',str(source.resolve())],capture_output=True,text=True)
    (project/'parser-index.stderr').write_text(result.stderr)
    if result.returncode: raise RuntimeError(result.stderr)
    index.write_text(result.stdout)
    declarations, ast=result.stdout.split('@@ast\n',1)
    decls=sorted(tuple(line.split('\t')) for line in declarations.splitlines())
    spans=sorted(set((int(a),int(b)) for a,b in re.findall(r'(?<!name)@([0-9]+)\.\.([0-9]+)',ast)))
    revision=hashlib.sha256(source.read_bytes()).hexdigest()
    content='# A revision cache supplies source facts without repeated parser work.\nuse std/map\nuse std/set\nuse provenance_preview.{SourceIndex}\n'
    content+='pub fn revision() -> String = '+json.dumps(revision)+'\n'
    modules={}
    def table(name, ty, values):
        nonlocal content
        pieces=[]
        # Each source-data module also stays inside the JVM constant pool
        # limit. These are ordinary generated source inputs, not JAR edits.
        for block in range(0,len(values),128):
            module='provenance_'+name+'_'+str(block//128)
            # Constant lists are reconstructed once at class/program setup,
            # not on each source lookup. A unit also bounds cold initializer
            # Code and its constant pool under the existing JVM rules.
            unit='# Bounded immutable source data avoids rebuilding each table per request.\nconst ITEMS: List['+ty+'] = ['+',\n'.join(values[block:block+128])+']\n'
            unit+='pub fn values() -> List['+ty+'] = ITEMS\n'
            filename=module+'.dawn';(project/'src'/filename).write_text(unit)
            modules[filename]=hashlib.sha256(unit.encode()).hexdigest()
            content='use '+module+'\n'+content
            pieces.append(module+'.values()')
        level=0
        while len(pieces)>16:
            parents=[]
            for at in range(0,len(pieces),16):
                part=name+'_group_'+str(level)+'_'+str(at//16)
                content+='fn '+part+'() -> List['+ty+'] = '+' ++ '.join(pieces[at:at+16])+'\n'
                parents.append(part+'()')
            pieces=parents;level+=1
        content+='fn '+name+'() -> List['+ty+'] = '+(' ++ '.join(pieces) if pieces else '[]')+'\n'
    table('declarations','(String, (Int, Int))',['('+json.dumps(key)+', ('+lo+', '+hi+'))' for key,lo,hi in decls])
    table('spans','(Int, Int)',['('+str(lo)+', '+str(hi)+')' for lo,hi in spans])
    content+='pub fn make() -> SourceIndex = SourceIndex { revision = revision(), declarations = map.from(declarations()), spans = set.from(spans()) }\n'
    (project/'src/provenance_source.dawn').write_text(content)
    modules['provenance_source.dawn']=hashlib.sha256(content.encode()).hexdigest()
    (project/'provenance-identity.json').write_text(json.dumps({'source_sha256':revision,'consumer_sha256':consumer_sha,'generator_sha256':generator_sha,'modules':modules,'declarations':len(decls),'syntax_spans':len(spans)},indent=2)+'\n')
    if cache:
        cache.parent.mkdir(parents=True,exist_ok=True)
        # Parallel golden shards publish one complete immutable directory.
        # Readers never see a directory with only half its source modules.
        with tempfile.TemporaryDirectory(prefix='.source-index-',dir=cache.parent) as temporary:
            pending=Path(temporary)/'ready';pending.mkdir()
            for name in ['parser-index.txt','provenance-identity.json']:
                shutil.copyfile(project/name,pending/name)
            for name in modules: shutil.copyfile(project/'src'/name,pending/name)
            try: pending.rename(cache)
            except OSError:
                if not cache.is_dir() or (cache/'provenance-identity.json').read_bytes()!=(project/'provenance-identity.json').read_bytes():
                    raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--compiler',type=Path,required=True)
    parser.add_argument('--java',default='java')
    args=parser.parse_args()
    instrument(args.project,args.compiler,args.java)

if __name__=='__main__': main()

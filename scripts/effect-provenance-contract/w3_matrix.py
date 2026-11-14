"""W3 controls use handwritten call counts, parents and refusal strings.

Large loops have no stopwatch: they prove bounded history and physical TCO.
Correct values alone cannot satisfy the separate source-tree predicates.
"""
from pathlib import Path
from run import HERE, ROOT, exact
from scope_matrix import source
from scope_oracle import rows


def bounded(run):
    def judge(output):
        value, recording = output.split('\n', 1)
        assert value == '42 bounded prefix cumulative rollback nested scopes million tail steps'
        first, rest = recording.split('\n@@rollback\n')
        second, mutual = rest.split('\n@@mutual\n')
        head, frames, notes = rows(first)
        assert head == 'S1\t1\t1\t1' and not notes
        assert [(int(f[3]), int(f[4]), int(f[5])) for f in frames] == [(1,0,0),(2,1,0),(3,2,1),(4,3,1),(5,4,1)]
        assert all(f[15:17] == ['bounded_log','Nf4:loop'] for f in frames[2:])
        head, frames, notes = rows(second)
        assert head.split('\t')[2:] == ['2','1'] and not notes
        assert [(int(f[2]),int(f[3]),int(f[4])) for f in frames] == [(1,1,0),(1,2,1),(2,7,2)]
        head, frames, notes = rows(mutual)
        assert head.split('\t')[2:] == ['1','0'] and not notes and len(frames)==23
        for i,f in enumerate(frames[2:]):
            assert int(f[4])==i+2 and f[5]=='1'
            assert f[16]==('Nf4:even' if i%2==0 else 'Nf3:odd')
    run.execute('w3-bounded', HERE/'bounded_log.dawn', judge)
    for capacity in ['0','-1','38347922']:
        expression = 'match catch_panic(() => provenance.observe(scope => 42, capacity = '+capacity+')) { Ok(value) -> "accepted"\n Err(error) -> error.message }'
        path = source(run, 'capacity-'+capacity.replace('-','minus'), '', expression)
        run.execute(path.stem,path,exact('provenance: capacity must be between 1 and 38347921\n'))


def control_matrix(run):
    def frozen_control(output):
        assert output.startswith('42 frozen continuation snapshots resume and abandonment\n')
        assert '@@discarded\nS1\t2\t1\t0' in output
    run.execute('w3-frozen-control', HERE/'snapshot_control.dawn', frozen_control)
    # Reuse the language's independent one-shot/release expectations under
    # observation. These cover bubbling, repeated suspension, one-shot errors,
    # explicit discard, bare drop, panic/fault during release, and Never exits.
    for name in ['ctl_resume', 'ctl_nested', 'ctl_discard', 'ctl_discard_fault', 'ctl_never_tail']:
        original = ROOT/'scripts/spike-native'/(name+'.dawn')
        text = original.read_text()
        assert text.count('pub fn main()') == 1
        text = 'use std/provenance as provenance\nuse std/provenance.{TraceSnapshot}\n'+text.replace('pub fn main()', 'fn work()')
        text += '\npub fn main() -> Unit !io = {\n let snapshot = provenance.observe(scope => { work()\n provenance.completed(scope) })\n std_io_marker(snapshot)\n}\n'
        text += 'fn std_io_marker(snapshot: TraceSnapshot) -> Unit !io = { io.println("@@observed")\n io.println(provenance.render_snapshot(snapshot)) }\n'
        folder = run.out/'w3-control-sources'; folder.mkdir(exist_ok=True)
        path = folder/(name+'.dawn'); path.write_text(text)
        expected = original.with_suffix('.expect').read_text()
        if name == 'ctl_discard':
            expected = expected.replace('ctl_discard.dawn:32:3', 'ctl_discard.dawn:34:3')
        def judge(output, expected=expected):
            actual, recording = output.split('@@observed\n')
            assert actual == expected, ('control value/release order', actual, expected)
            header, frames, notes = rows(recording)
            assert header.split('\t')[2:] == ['1','0'] and not notes
            ids = [int(f[3]) for f in frames]
            assert ids == list(range(1,len(frames)+1)), 'control replay cannot duplicate identities'
            assert len(frames) > 3 and int(frames[0][4]) == 0
            seen = {0}
            for f in frames:
                assert int(f[4]) in seen and int(f[4]) < int(f[3]), 'parent before child'
                assert f[-1] == '0', 'known Dawn segments cannot silently become unknown'
                seen.add(int(f[3]))
            assert [int(f[5]) for f in frames[:2]] == [0,0]
        previous_std=getattr(run,'std',ROOT/'std')
        if name=='ctl_discard_fault':
            import shutil
            copied=run.out/'control_std'
            shutil.copytree(ROOT/'std',copied,dirs_exist_ok=True)
            shutil.copy2(ROOT/'scripts/spike-native/stdext/raw.dawn',copied/'raw.dawn')
            with (copied/'modules.txt').open('a') as stream: stream.write('\nraw\n')
            run.std=copied
        try: run.execute('w3-observed-'+name,path,judge)
        finally: run.std=previous_std


def foreign(run):
    # Java cannot expose its own internal calls, but a synchronous Dawn SAM
    # callback must regain the observed entry and its real Definition.
    path=run.out/'foreign_boundary.dawn'
    path.write_text('# A real Java boundary plus a known Dawn callback segment.\nuse java "java.util.ArrayList"\nuse java "java.lang.Object"\nuse std/io.{println}\nuse std/provenance as p\nfn known(n: Int) -> Bool = n == 7\npub fn main() -> Unit !io = {\n  let callback: fn(Object) -> Bool = _x => known(7)\n  let (value, snapshot) = p.observe(scope => {\n    let list = ArrayList.new()\n    let added = list.add("x")\n    let removed = list.removeIf(callback)\n    (added && removed && list.size() == 0, p.completed(scope))\n  })\n  println("${value}")\n  println(p.render_snapshot(snapshot))\n}\n')
    command=run.build('w3-foreign',path,'jvm')
    result=run.command('w3-foreign-run',command)
    assert result.returncode==0,result.stderr
    value,recording=result.stdout.split('\n',1)
    assert value=='true'
    head,frames,notes=rows(recording)
    assert head=='S1\t1\t1\t0' and not notes
    known=[f for f in frames if len(f)==22 and f[16]=='Nf5:known']
    assert len(known)==1 and known[0][-1]=='0' and known[0][5]=='1'
    parent=frames[int(known[0][4])-1]
    assert parent[-1]=='1' and parent[-3]=='lambda'
    foreign_rows=[f for f in frames if f[-1]=='1']
    assert len(foreign_rows)==5,('four Java calls plus callback entry',foreign_rows)
    run.results.append({'case':'w3-foreign','backend':'jvm','passed':True})


def control_tree(output):
    value, recording=output.split('\n',1)
    assert value=='84'
    header,frames,notes=rows(recording)
    assert header=='S1\t1\t1\t0' and not notes
    parents=[0,1,2,3,4,5,6,2,8,9,8,11]
    assert len(frames)==len(parents),('logical tail/control count',len(frames))
    for i,(f,parent) in enumerate(zip(frames,parents),1):
        assert list(map(int,f[1:6]))==[1,1,i,parent,0 if i<=2 else 1],f
        assert f[-1]=='0'
    assert all(f[16]=='Nf4:loop' for f in frames[2:7])
    assert frames[7][16]=='Nf7:control' and frames[8][19]=='with'
    assert frames[9][13]=='perform' and frames[9][14]=='control_tree:Ne3:AskNo3:ask'
    assert frames[10][19]=='handler'


def native_command(run,label,target):
    exe=run.out/(label+'.bin')
    result=run.command(label+'-cc',[run.args.cc,'-std=c11','-O2','-fwrapv','-fexceptions',
        '-fno-strict-aliasing','-ffp-contract=off','-pthread','-I'+str(ROOT/'runtime/c'),target,ROOT/'runtime/c/dawn_rt.c','-lm','-o',exe])
    assert result.returncode==0,result.stderr
    return [exe]


def external_native(run):
    source=HERE/'external_boundary.dawn'
    target=run.out/'w3-external-native.c'
    result=run.command('w3-external-native-emit',run.compiler('__emitc',source,'-o',target))
    assert result.returncode==0,result.stderr
    with target.open('a') as stream: stream.write('\nint64_t dawn_x_prov_probe_add(int64_t n) { return n+1; }\n')
    command=native_command(run,'w3-external-native',target)
    result=run.command('w3-external-native-run',command)
    assert result.returncode==0,result.stderr
    def judge(output):
        value,recording=output.split('\n',1)
        assert value=='42'
        header,frames,notes=rows(recording)
        assert header=='S1\t1\t1\t0' and not notes and len(frames)==4
        assert [int(f[4]) for f in frames]==[0,1,2,3]
        assert [int(f[-1]) for f in frames]==[0,0,0,1]
        assert frames[2][16]=='Nf10:native_add' and frames[3][-2]==''
    judge(result.stdout)
    run.results.append({'case':'w3-external-native','backend':'native','passed':True})
    return target,judge


def mutants(run):
    import shutil
    java=Path(shutil.which(run.args.java)).resolve()
    built=run.command('w3-mutator-javac',[java.with_name('javac'),'-cp',run.args.compiler,'-d',run.out,HERE/'ControlMutator.java'])
    assert built.returncode==0,built.stderr
    run.execute('w3-control-tree',HERE/'control_tree.dawn',control_tree)
    foreign(run)
    native_external,native_judge=external_native(run)
    for mode in ['tail','control','unknown']:
        for backend in ['jvm','native']:
            label='w3-mutant-'+mode+'-'+backend
            if backend=='jvm':
                baseline=run.out/('w3-foreign-jvm.jar' if mode=='unknown' else 'w3-control-tree-jvm.jar')
                target=run.out/(label+'.jar')
                built=run.command(label+'-mutate',[java,'-cp',str(run.out)+':'+str(run.args.compiler),'ControlMutator',baseline,target,mode])
                assert built.returncode==0,built.stderr
                command=[java,'-Xverify:all','-jar',target]
                if mode=='unknown':
                    def judge(output):
                        value,text=output.split('\n',1); assert value=='true'
                        _h,frames,_n=rows(text); assert sum(f[-1]=='1' for f in frames)==5
                else: judge=control_tree
            else:
                baseline=native_external if mode=='unknown' else run.out/'w3-control-tree-native.c'
                text=baseline.read_text()
                function={'tail':'dawn_prov_tail_ctx','control':'dawn_prov_control_select','unknown':'dawn_prov_unknown_ctx'}[mode]
                start=text.index(('static DAWN_PROV_CODE void *' if mode=='control' else 'DAWN_PROV_CODE void ')+function+'(')
                body=text.index('{',start); end=text.index('\n}',body)+2
                replacement={'tail':'{ (void)ctx; (void)site; (void)metadata; }','control':'{ return canonical; }','unknown':'{ (void)ctx; }'}[mode]
                text=text[:body]+replacement+text[end:]
                target=run.out/(label+'.c');target.write_text(text)
                command=native_command(run,label,target)
                judge=native_judge if mode=='unknown' else control_tree
            result=run.command(label+'-run',command)
            assert result.returncode==0,(label,result.stderr)
            expected='true' if backend=='jvm' and mode=='unknown' else '42' if mode=='unknown' else '84'
            assert result.stdout.splitlines()[0]==expected,(label,'numeric control failed')
            try: judge(result.stdout)
            except AssertionError: pass
            else: raise AssertionError((label,'provenance mutant stayed green'))
            run.results.append({'case':label,'backend':backend,'passed':True,'numeric_control':True,'origin_rejected':True})
            print('PASS',label,'value correct and independent provenance oracle red',flush=True)


def resources(run):
    import os, re, shutil
    java=Path(shutil.which(run.args.java)).resolve()
    command=run.build('w3-resources',HERE/'control_resources.dawn','jvm')
    jar=run.out/'w3-resources-jvm.jar'
    result=run.command('w3-resources-javac',[java.with_name('javac'),'-cp',jar,'-d',run.out,HERE/'ControlResources.java'])
    assert result.returncode==0,result.stderr
    import zipfile
    probe_jar=run.out/'w3-resources-probe.jar'
    with zipfile.ZipFile(jar) as original,zipfile.ZipFile(probe_jar,'w') as output:
        for entry in original.infolist():
            data=original.read(entry.filename)
            if entry.filename=='META-INF/MANIFEST.MF':
                data=re.sub(rb'Main-Class: [^\r\n]+',b'Main-Class: ControlResources',data)
            output.writestr(entry,data)
        output.write(run.out/'ControlResources.class','ControlResources.class')
    result=run.command('w3-resources-jvm-run',[java,'-Xverify:all','-jar',probe_jar])
    assert result.returncode==0,(result.stdout,result.stderr)
    assert result.stdout=='42 control resource normal panic discard\n'
    run.results.append({'case':'w3-resources','backend':'jvm','passed':True})
    target=run.out/'control_resources.c'
    result=run.command('w3-resources-native-emit',run.compiler('__emitc',HERE/'control_resources.dawn','-o',target))
    assert result.returncode==0,result.stderr
    emitted=target.read_text(); probe=(HERE/'control_resources_probe.c').read_text()
    for macro,name in [('MAKE','make'),('FINISH','finish'),('FAIL','fail_1finish'),('STOP','stop'),('VALUE','value')]:
        match=re.search(r'^[^\n;{}]*\bdawn_control_1resources__'+name+r'\(([^;{}\n]*)\);',emitted,re.M)
        assert match,(macro,'public C prototype')
        count=len(match[1].split(','))
        args=['value']+['NULL']*(count-1)
        probe='#define RESOURCE_'+macro+'(value) dawn_control_1resources__'+name+'('+','.join(args)+')\n'+probe
    source=run.out/'resource_probe.c';source.write_text(probe)
    for sanitized in [False,True]:
        label='w3-resources-native'+('-asan' if sanitized else '')
        flags=['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'] if sanitized else ['-O2']
        exe=run.out/(label+'.bin')
        result=run.command(label+'-cc',[run.args.cc,'-std=c11',*flags,'-fwrapv','-fexceptions','-fno-strict-aliasing','-ffp-contract=off','-pthread','-I'+str(ROOT/'runtime/c'),source,'-lm','-o',exe])
        assert result.returncode==0,result.stderr
        previous=os.environ.get('ASAN_OPTIONS');os.environ['ASAN_OPTIONS']='detect_leaks=1:abort_on_error=1'
        try: result=run.command(label+'-run',[exe])
        finally:
            if previous is None: del os.environ['ASAN_OPTIONS']
            else: os.environ['ASAN_OPTIONS']=previous
        assert result.returncode==0,(result.stdout,result.stderr)
        assert result.stdout=='42 control resource normal panic discard natural drop\n' and not result.stderr,result.stderr
        run.results.append({'case':label,'backend':'native','passed':True})
    print('PASS JVM and native completed ticket releases plus ASan UBSan leak controls',flush=True)

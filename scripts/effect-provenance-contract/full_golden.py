"""The actual complete golden source is also an observed capacity/size input."""
from pathlib import Path
import json
import shutil
import sys
from run import ROOT,HERE
from golden_observe import instrument


def check(run):
    project=run.out/'actual-observed-goldens';(project/'src').mkdir(parents=True)
    shutil.copyfile(ROOT/'scripts/tile-golden/kernels.dawn',project/'src/main.dawn')
    (project/'dawn.toml').write_text('schema = 1\nname = "actual_observed_goldens"\n[deps]\n'
        +'tileir = '+json.dumps(str(ROOT/'packages/tileir'))+'\n'
        +'tileref = '+json.dumps(str(ROOT/'packages/tileref'))+'\n')
    instrument(project,run.args.compiler,run.args.java)
    names=sorted(p.stem for p in (ROOT/'scripts/tile-golden').glob('*.tilebc'))
    listing=run.out/'actual-golden-names.txt';listing.write_text(''.join(name+'\n' for name in names))
    run.build('actual-goldens',project,'jvm');jar=run.out/'actual-goldens-jvm.jar'
    result=run.command('actual-goldens-size',[sys.executable,ROOT/'scripts/method-size-gate.py','--jar',run.args.compiler,'--observed-jar',jar,'--top','10'])
    assert result.returncode==0,result.stdout+result.stderr
    java=Path(shutil.which(run.args.java)).resolve()
    result=run.command('actual-goldens-reader-javac',[java.with_name('javac'),'-cp',jar,'-d',run.out,HERE/'FullGoldenCheck.java'])
    assert result.returncode==0,result.stderr
    out=run.out/'actual-golden-jvm-results'
    result=run.command('actual-goldens-reader-jvm',[java,'-Xverify:all','-cp',str(run.out)+':'+str(jar),'FullGoldenCheck',ROOT/'scripts/tile-golden',listing,out])
    assert result.returncode==0,result.stderr
    target=run.out/'full_golden.c'
    result=run.command('actual-goldens-native-emit',run.compiler('__emitc',project,'-o',target));assert result.returncode==0,result.stderr
    source=run.out/'full_golden_probe.c';shutil.copyfile(HERE/'full_golden_probe.c',source)
    exe=run.out/'full-golden-probe.bin'
    result=run.command('actual-goldens-native-cc',[run.args.cc,'-std=c11','-O2','-fwrapv','-fexceptions','-fno-strict-aliasing','-ffp-contract=off','-pthread','-I'+str(ROOT/'runtime/c'),source,ROOT/'runtime/c/dawn_rt.c','-lm','-o',exe]);assert result.returncode==0,result.stderr
    result=run.command('actual-goldens-reader-native',[exe,ROOT/'scripts/tile-golden',listing]);assert result.returncode==0,result.stderr
    expected=''.join(name+' public CLI mapping and both goldens\n' for name in names)
    assert result.stdout==expected and (run.out/'actual-goldens-reader-jvm.stdout').read_text()==expected
    run.results.append({'case':'actual whole golden source two observations and public mapping','cases':len(names),'backend':'both','passed':True})
    print('PASS actual complete golden source compiler capacity, final Code and public consumption on both backends',flush=True)

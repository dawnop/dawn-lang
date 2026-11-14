"""The CLI consumer has its own handwritten projection and refusal controls."""
from pathlib import Path
import shutil
from run import ROOT,HERE
from golden_observe import prepare_index


def check(run):
    project=run.out/'cli-preview';(project/'src').mkdir(parents=True)
    shutil.copyfile(HERE/'preview_control.dawn',project/'src/main.dawn')
    (project/'dawn.toml').write_text('schema = 1\nname = "public_preview_control"\n')
    prepare_index(project,run.args.compiler,run.args.java)
    run.execute('cli-preview',project,lambda text: None if text.startswith('42 CLI bulk tree and source refusals\n') else (_ for _ in ()).throw(AssertionError(text)))
    jar=run.out/'cli-preview-jvm.jar'
    java=Path(shutil.which(run.args.java)).resolve()
    result=run.command('cli-preview-probe-javac',[java.with_name('javac'),'-cp',jar,'-d',run.out,HERE/'PublicPreviewProbe.java',HERE/'ProbeTables.java'])
    assert result.returncode==0,result.stderr
    result=run.command('cli-preview-probe-jvm',[java,'-Xverify:all','-cp',str(run.out)+':'+str(jar),'PublicPreviewProbe'])
    assert result.returncode==0,result.stderr
    expected=''.join('42 CLI '+mode+' rejected\n' for mode in ['truncated','unknown','uncommitted'])
    assert result.stdout==expected
    shutil.copyfile(run.out/'cli-preview-native.c',run.out/'public_preview.c')
    source=run.out/'public_preview_probe.c';shutil.copyfile(HERE/'public_preview_probe.c',source)
    exe=run.out/'cli-preview-probe.bin'
    result=run.command('cli-preview-probe-cc',[run.args.cc,'-std=c11','-O2','-fwrapv','-fexceptions','-fno-strict-aliasing','-ffp-contract=off','-pthread','-I'+str(ROOT/'runtime/c'),'-I'+str(HERE),source,ROOT/'runtime/c/dawn_rt.c','-lm','-o',exe])
    assert result.returncode==0,result.stderr
    result=run.command('cli-preview-probe-native',[exe])
    assert result.returncode==0 and result.stdout==expected,(result.stdout,result.stderr)
    run.results.append({'case':'CLI public consumer six refusals','backend':'both','passed':True})
    print('PASS CLI public bulk handwritten projection and six refusal controls on both backends',flush=True)

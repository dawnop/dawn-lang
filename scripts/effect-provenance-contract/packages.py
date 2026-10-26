"""Exercise the same handwritten call tree through path and URL dependencies."""
from pathlib import Path
import zipfile
import json
from run import HERE
from scope_oracle import rows


def judge(output):
    value, recording = output.split('\n', 1)
    assert value == '7'
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and not notes and len(frames) == 5
    expected = [(0, '', '', 0), (1, 'main', 'Nf4:main', 0),
                (2, 'dawn$pkg$courier/calls', 'Nf8:dispatch', 1),
                (3, 'main', 'Nf4:main', 1), (4, 'main', 'Nf4:user', 1)]
    for instance, (frame, (parent, owner, definition, status)) in enumerate(zip(frames, expected), 1):
        assert frame[:6] == ['F', '1', '1', str(instance), str(parent), str(status)], frame
        if instance > 1:
            assert len(frame) == 21 and frame[15:17] == [owner, definition], frame
    assert frames[3][7:9] == ['dawn$pkg$courier/calls', 'Nf8:dispatch'], 'callback Site belongs to dependency'
    assert frames[3][19] == 'lambda' and frames[4][19] == 'function'


def packages(run):
    package = HERE/'package'
    hashed = run.command('package-hash', [run.args.java, '-jar', run.args.compiler, '__pkghash', package])
    assert hashed.returncode == 0, hashed.stderr
    archive = run.out/'courier.zip'
    with zipfile.ZipFile(archive, 'w') as target:
        for path in sorted(package.rglob('*')):
            if path.is_file():
                target.write(path, str(path.relative_to(package)))
    for kind in ['path', 'url']:
        project = run.out/('package_'+kind)
        (project/'src').mkdir(parents=True, exist_ok=True)
        (project/'src/main.dawn').write_bytes((HERE/'package_main.dawn').read_bytes())
        dependency = ('[deps]\ng = '+json.dumps(str(package))+'\n') if kind == 'path' else (
            '[deps.g]\nurl = "'+archive.as_uri()+'"\nversion = "1.0.0"\nhash = "'+hashed.stdout.strip()+'"\n')
        (project/'dawn.toml').write_text('schema = 1\nname = "package_observer"\n'+dependency)
        run.execute('package-'+kind, project, judge)

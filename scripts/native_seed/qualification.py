"""One-time controls over real cold results and an independently produced JVM oracle."""

from contextlib import contextmanager
import copy
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace

from native_seed import cold, cold_audit, contract as c, recipe, toolchain

REAL_EXPECTED = {
    'same-version-changed-bytes-own-sidecar': ('Q1', 'seed-digest'),
    'different-real-current-compiler': ('Q1', 'seed-digest'),
    'aarch64-unknown-linux-gnu': ('Q3', 'seed-target'),
    'x86_64-unknown-linux-musl': ('Q3', 'seed-target'),
    'actual-elf-machine': ('Q3', 'seed-target'),
    'wrong-cc-triple': ('Q3', 'toolchain-recipe'),
    'actual-sysroot-content': ('Q3', 'toolchain-identity'),
    'real-seed-std-module': ('Q2', 'std-pairing'),
    'missing-real-runtime-header': ('Q6', 'runtime-pairing'),
    'actual-stale-generated-runtime': ('Q6', 'generated-pairing'),
    'missing-real-transitive-manifest': ('Q7', 'source-inventory'),
    'actual-source-symlink': ('Q7', 'source-type'),
    'nonempty-output-marker': ('Q4', 'cold-directory'),
    'outside-decoys-and-injected-environment': ('Q4', None),
    'runner-skips-C-writes-success': ('Q8', 'audit-coverage'),
    'equal-B-copied-C-without-execution': ('Q8', 'audit-trace'),
    'native-marked-jar': ('Q9', 'seed-kind'), 'unknown-schema': ('Q9', 'schema'),
    'seed-builder-swapped': ('Q9', 'seed-kind'),
    **{stage + '-wrong-' + role: (qid, role + '-pairing')
       for stage in ('A', 'B', 'C') for role, qid in (('std', 'Q2'), ('runtime', 'Q6'))},
    **{name: ('Q8', 'cold-output') for name in ('whole', 'info', 'missing-tu', 'extra-tu', 'elf')},
    **{path: ('Q7', 'source-inventory') for path in
       ('selfhost/dawn.lock', 'selfhost/dawn.toml', 'selfhost/src/nmain.dawn')},
}


def refused(name, code, action):
    try:
        action()
    except c.Rejected as exc:
        c.require(str(exc).startswith(code + ':'), 'control-verdict', f'{name}: {exc}')
        return {'name': name, 'expected': code, 'actual': str(exc)}
    raise c.Rejected(f'control-missed: {name} accepted the fault')


@contextmanager
def changed(path, data):
    """Mutate only caller-owned evidence, restoring bytes and mode even on refusal."""
    path = Path(path)
    original = path.read_bytes() if path.exists() else None
    mode = path.stat().st_mode if original is not None else None
    parent_mode = path.parent.stat().st_mode
    path.parent.chmod(parent_mode | 0o700)
    if path.exists():
        path.chmod(mode | 0o600)
    try:
        if data is None:
            path.unlink()
        else:
            path.write_bytes(data)
        yield
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
            path.chmod(mode)
        path.parent.chmod(parent_mode)


def real_controls(repo, directory, destination):
    directory, destination = Path(directory).absolute(), cold.new_directory(destination)
    baseline = cold.verify(repo, directory)
    lock, inputs = c.read_lock(directory / 'seed-lock.json'), c.read_json(directory / 'inputs.json')
    seed, source, tcdir = directory / 'inputs/seed', directory / 'inputs/source', directory / 'toolchain'
    rows = []

    def reject(q, name, code, action):
        row = refused(name, code, action)
        rows.append(dict(row, q=q, evidence_class='real-input-or-result'))

    data = (seed / 'dawnc').read_bytes()
    bad = data[:-1] + bytes([data[-1] ^ 1])
    replacement = destination / 'same-version-dawnc'
    replacement.write_bytes(bad)
    (destination / 'same-version-dawnc.sha256').write_text(c.digest(bad) + '  same-version-dawnc\n')
    reject('Q1', 'same-version-changed-bytes-own-sidecar', 'seed-digest',
           lambda: c.verify_seed(replacement, lock))
    c.require(c.probe_seed(bad) == (lock['seed']['version'], lock['seed']['build_id']),
              'control-verdict', 'same-version mutation changed the identity transcript')
    reject('Q1', 'different-real-current-compiler', 'seed-digest',
           lambda: c.verify_seed(directory / 'root-1/B/dawnc', lock))
    for target in ('aarch64-unknown-linux-gnu', 'x86_64-unknown-linux-musl'):
        altered = copy.deepcopy(lock)
        altered['seed']['target'] = target
        reject('Q3', target, 'seed-target', lambda: c.validate_lock(altered))
    header = bytearray(data)
    header[18:20] = (183).to_bytes(2, 'little')
    (destination / 'wrong-machine.elf').write_bytes(header)
    reject('Q3', 'actual-elf-machine', 'seed-target', lambda: c.verify_elf(header))
    tcfile = tcdir / 'toolchain.json'
    altered = c.read_json(tcfile)
    altered['compiler']['triple'] = 'aarch64-unknown-linux-gnu'
    with changed(tcfile, c.canonical(altered)):
        reject('Q3', 'wrong-cc-triple', 'toolchain-recipe', lambda: toolchain.verify(tcdir))
    header_path = tcdir / 'root/usr/include/stdio.h'
    with changed(header_path, header_path.read_bytes() + b'\n/* altered sysroot */\n'):
        reject('Q3', 'actual-sysroot-content', 'toolchain-identity', lambda: toolchain.verify(tcdir))
    stdfile = next(p for p in sorted((seed / 'std').rglob('*.dawn')) if p.is_file())
    with changed(stdfile, stdfile.read_bytes() + b'\n# controlled content change\n'):
        reject('Q2', 'real-seed-std-module', 'std-pairing', lambda: c.verify_seed_tree(repo, lock, seed))
    for stage in ('A', 'B', 'C'):
        std = source / 'std' if stage == 'A' else seed / 'std'
        runtime = seed / 'runtime/c' if stage == 'A' else source / 'runtime/c'
        reject('Q2', stage + '-wrong-std', 'std-pairing',
               lambda stage=stage, std=std, runtime=runtime: recipe.stage_inputs(
                   repo, lock, inputs, source, seed, stage, std, runtime))
        std = seed / 'std' if stage == 'A' else source / 'std'
        runtime = source / 'runtime/c' if stage == 'A' else seed / 'runtime/c'
        reject('Q6', stage + '-wrong-runtime', 'runtime-pairing',
               lambda stage=stage, std=std, runtime=runtime: recipe.stage_inputs(
                   repo, lock, inputs, source, seed, stage, std, runtime))
    rtfile = seed / 'runtime/c/dawn_rt.h'
    with changed(rtfile, None):
        reject('Q6', 'missing-real-runtime-header', 'runtime-pairing',
               lambda: c.verify_seed_tree(repo, lock, seed))
    generated = c.scan(source)
    path = 'selfhost/src/embed/rtsrc.dawn'
    generated[path] = (generated[path][0], generated[path][1] + b'\n# stale generation\n')
    reject('Q6', 'actual-stale-generated-runtime', 'generated-pairing', lambda: c.verify_generated(generated))
    manifest = source / 'packages/inflate/dawn.toml'
    with changed(manifest, None):
        reject('Q7', 'missing-real-transitive-manifest', 'source-inventory',
               lambda: c.verify_tree(source, inputs['source']['inventory']))
    for relative, mutation in (('selfhost/dawn.lock', b'controlled missing-state change\n'),
                               ('selfhost/dawn.toml', (source / 'selfhost/dawn.toml').read_bytes() + b'\n'),
                               ('selfhost/src/nmain.dawn', (source / 'selfhost/src/nmain.dawn').read_bytes() + b'\n')):
        with changed(source / relative, mutation):
            reject('Q7', relative, 'source-inventory', lambda: c.verify_tree(source, inputs['source']['inventory']))
    with changed(manifest, None):
        manifest.symlink_to(destination / 'outside-manifest')
        try:
            reject('Q7', 'actual-source-symlink', 'source-type', lambda: c.scan(source))
        finally:
            manifest.unlink()
    warm = cold.new_directory(destination / 'warm-output')
    (warm / 'cached.o').write_bytes(b'false object\n')
    reject('Q4', 'nonempty-output-marker', 'cold-directory', lambda: cold.run(SimpleNamespace(
        repo=repo, lock=directory / 'seed-lock.json', receipt=directory / 'inputs.json',
        source=source, seed_tree=seed, seed=seed / 'dawnc', toolchain=tcdir, out=warm)))
    c.require((warm / 'cached.o').read_bytes() == b'false object\n', 'control-verdict', 'marker changed')
    c.require(not (warm / 'receipt.json').exists() and not (warm / 'root-1').exists(),
              'control-verdict', 'rejected cold run started a compiler or wrote a success receipt')
    # External decoys are intentionally outside every mounted input.
    decoys = cold.new_directory(destination / 'outside-cache')
    for name in ('A', 'B', 'stamp', 'cached.o', 'dawnc'):
        (decoys / name).write_bytes(b'false cached artifact\n')
    tc = toolchain.verify(tcdir)
    output = cold.new_directory(destination / 'isolation-output')
    command = ['/usr/bin/bash', '-c',
               'test ! -e "$1" && test -z "${DAWN_STD+x}" && '
               'test -z "${CCACHE_DIR+x}" && test -z "${DAWN_SEED+x}" && '
               '/seed/dawnc --version', 'probe', str(decoys / 'cached.o')]
    inherited = {name: os.environ.get(name) for name in ('DAWN_STD', 'CCACHE_DIR', 'DAWN_SEED')}
    try:
        for name in inherited:
            os.environ[name] = str(decoys)
        result = cold.run_step(destination, 'boundary-probe', tcdir, tc, source, seed, None, output, command)
    finally:
        for name, value in inherited.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    c.require(not any(str(decoys) in p for p in result['audit']['successful_opens']),
              'control-verdict', 'outside decoy was read')
    rows.append({'q': 'Q4', 'name': 'outside-decoys-and-injected-environment',
                 'evidence_class': 'real-execution-positive', 'result_sha256': c.digest(c.canonical(result))})
    for name, file, mutation in (
            ('whole', 'whole.c', lambda b: b + b'\n'),
            ('info', 'info.c', lambda b: b + b'\n'),
            ('missing-tu', 'units/tu00.c', lambda b: None),
            ('extra-tu', 'units/tu-extra.c', lambda b: b'/* extra TU */\n'),
            ('elf', 'dawnc', lambda b: b[:-1] + bytes([b[-1] ^ 1]))):
        path = directory / 'root-1/C' / file
        if name == 'missing-tu':
            path = next((directory / 'root-1/C/units').glob('tu*.c'))
        previous = path.read_bytes() if path.exists() else b''
        with changed(path, mutation(previous)):
            reject('Q8', name, 'cold-output', lambda: cold.verify(repo, directory))
    altered = copy.deepcopy(baseline)
    altered['roots']['root-1']['steps'] = [s for s in altered['roots']['root-1']['steps'] if s['name'] != 'C-emit']
    reject('Q8', 'runner-skips-C-writes-success', 'audit-coverage', lambda: cold.verify(repo, directory, altered))
    traces = list((directory / 'root-1/C-emit').glob('trace.*'))
    saved = cold.new_directory(destination / 'removed-C-execution')
    for trace in traces:
        trace.rename(saved / trace.name)
    try:
        reject('Q8', 'equal-B-copied-C-without-execution', 'audit-trace', lambda: cold.verify(repo, directory))
    finally:
        for trace in saved.iterdir():
            trace.rename(directory / 'root-1/C-emit' / trace.name)
    for name, mutate, code in (
            ('native-marked-jar', lambda x: x['seed'].update(kind='jvm-jar'), 'seed-kind'),
            ('unknown-schema', lambda x: x.update(schema=999), 'schema'),
            ('seed-builder-swapped', lambda x: x['seed'].update(asset='dawn-selfhost.jar'), 'seed-kind')):
        altered = copy.deepcopy(lock)
        mutate(altered)
        reject('Q9', name, code, lambda: c.validate_lock(altered))
    cold.verify(repo, directory)
    c.atomic_json(destination / 'results.json', {'schema': 1, 'kind': 'native-real-controls',
                  'cold_receipt_sha256': c.digest(c.canonical(baseline)), 'controls': rows})
    return rows


def command(directory, name, argv, cwd, env):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (name + '.stdout')).open('wb') as stdout, (directory / (name + '.stderr')).open('wb') as stderr:
        result = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=stdout, stderr=stderr, timeout=1800)
    row = {'argv': list(map(str, argv)), 'exit_code': result.returncode,
           'stdout_sha256': c.digest((directory / (name + '.stdout')).read_bytes()),
           'stderr_sha256': c.digest((directory / (name + '.stderr')).read_bytes())}
    c.atomic_json(directory / (name + '.json'), row)
    return row


def dual(repo, cold_dir, destination, java, jar):
    """Compare an external JVM compiler with the actual native B, never regenerate the oracle with B."""
    destination = cold.new_directory(destination)
    value = cold.verify(repo, cold_dir)
    source = Path(cold_dir) / 'inputs/source'
    native = Path(cold_dir) / 'root-1/B/dawnc'
    env = {'PATH': str(Path(java).parent) + ':/usr/bin:/bin', 'LANG': 'C.UTF-8',
           'LC_ALL': 'C.UTF-8', 'HOME': str(destination), 'TMPDIR': str(destination),
           'CC': '/usr/lib/llvm-18/bin/clang', 'CC_JOBS': '1'}
    oracle = [str(java), '-XX:-UsePerfData', '-Xss512m', '-jar', str(jar)]
    emitted = cold.new_directory(destination / 'jvm-emission')
    run = command(destination, 'jvm-emission', [*oracle, '__emitc', '--std', source / 'std',
                  source / 'selfhost/src/nmain.dawn', '-o', emitted / 'whole.c',
                  '--build-info', emitted / 'info.c', '--split', emitted / 'units'], source, env)
    c.require(run['exit_code'] == 0, 'dual-command', 'JVM compiler emission failed')
    comparisons = {name: c.digest((emitted / name).read_bytes()) == c.digest((Path(cold_dir) / 'root-1/B' / name).read_bytes())
                   for name in ('whole.c', 'info.c')}
    comparisons['units'] = c.inventory(c.scan(emitted / 'units')) == value['roots']['root-1']['stages']['B']['units']
    c.require(all(comparisons.values()), 'dual-emission', 'JVM/current-std and native B emissions differ')
    cases = cold.new_directory(destination / 'cases')
    (cases / 'standalone.dawn').write_text('pub fn main() -> Unit !io = println("STANDALONE")\n')
    (cases / 'stdlib.dawn').write_text(cold.SMOKE)
    (cases / 'invalid.dawn').write_text('pub fn main() -> Unit = missing_qualification_name\n')
    package = cold.new_directory(cases / 'package')
    (package / 'dawn.toml').write_text('schema = 1\nname = "probe"\n[deps]\nhelper = "../helper"\n')
    (package / 'src').mkdir()
    (package / 'src/main.dawn').write_text('use helper/value\npub fn main() -> Unit !io = println(value.answer())\n')
    helper = cold.new_directory(cases / 'helper')
    (helper / 'src').mkdir()
    (helper / 'dawn.toml').write_text('schema = 1\nname = "helper"\n')
    (helper / 'src/value.dawn').write_text('pub fn answer() -> String = "PACKAGE"\n')
    rows = []
    specs = [('standalone', 'standalone.dawn', b'STANDALONE\n'),
             ('stdlib', 'stdlib.dawn', cold.EXPECTED_SMOKE), ('package', 'package', b'PACKAGE\n')]
    for name, target, expected in specs:
        # JVM run uses the JVM backend; native build uses the native backend and its embedded runtime.
        jvm = command(destination, name + '-jvm', [*oracle, 'run', '--std', source / 'std', target], cases, env)
        built = command(destination, name + '-build', [native, 'build', target, '--std', source / 'std',
                                                      '-o', destination / (name + '.elf')], cases, env)
        ran = command(destination, name + '-native', [destination / (name + '.elf')], cases, env) if built['exit_code'] == 0 else None
        c.require(jvm['exit_code'] == 0 and ran and ran['exit_code'] == 0 and
                  (destination / (name + '-jvm.stdout')).read_bytes() == expected and
                  (destination / (name + '-native.stdout')).read_bytes() == expected,
                  'dual-function', f'{name}: output or exit differs')
        rows.append({'name': name, 'stdout_sha256': c.digest(expected), 'jvm': jvm, 'native': ran})
    for name, args in (('diagnostic', ['check', 'invalid.dawn', '--std', source / 'std']),
                       ('format', ['fmt', 'stdlib.dawn', '--check'])):
        jvm = command(destination, name + '-jvm', [*oracle, *args], cases, env)
        nat = command(destination, name + '-native', [native, *args], cases, env)
        c.require(jvm['exit_code'] == nat['exit_code'] and jvm['stdout_sha256'] == nat['stdout_sha256'] and
                  jvm['stderr_sha256'] == nat['stderr_sha256'], 'dual-function', f'{name}: transcript differs')
        if name == 'diagnostic':
            c.require(jvm['exit_code'] != 0 and b'missing_qualification_name' in
                      (destination / (name + '-jvm.stderr')).read_bytes(), 'dual-function', 'missing owned diagnostic')
        rows.append({'name': name, 'jvm': jvm, 'native': nat})
    result = {'schema': 1, 'kind': 'native-jvm-qualification-diff',
              'cold_receipt_sha256': c.digest(c.canonical(value)),
              'java_sha256': c.digest(Path(java).read_bytes()), 'jar_sha256': c.digest(Path(jar).read_bytes()),
              'native_sha256': c.digest(native.read_bytes()), 'emissions': comparisons, 'cases': rows}
    c.atomic_json(destination / 'summary.json', result)
    return result

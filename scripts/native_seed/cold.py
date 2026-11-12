"""Offline native seed qualification in two fresh, read-only input namespaces."""

from pathlib import Path
import shutil
import subprocess

from native_seed import contract as c
from native_seed import cold_audit, toolchain

POLICY = 'native-cold-linux-x86_64-v1'
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
       'TZ': 'UTC', 'HOME': '/home', 'TMPDIR': '/tmp',
       'XDG_CACHE_HOME': '/home/.cache', 'CC_JOBS': '1'}
SMOKE = '''use std/str

pub fn main() -> Unit !io = {
  println(join(map(sort([3, 1, 2]), x => "${x}"), ","))
  println(str.to_upper("fixpoint"))
}
'''
EXPECTED_SMOKE = b'1,2,3\nFIXPOINT\n'


def new_directory(path):
    path = c.safe_destination(path)
    c.require(not path.exists(), 'cold-directory', 'cold execution requires a new directory')
    path.mkdir(parents=True, mode=0o700)
    return path


def sandbox_command(root, source, seed, emitter, output, home, tmp, command, cc):
    args = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
            '--cap-drop', 'ALL', '--clearenv', '--ro-bind', str(root), '/',
            '--proc', '/proc', '--dev', '/dev', '--bind', str(output), '/out',
            '--bind', str(home), '/home', '--bind', str(tmp), '/tmp']
    for path, logical in ((source, '/src'), (seed, '/seed'), (emitter, '/emitter/dawnc')):
        if path is not None:
            args += ['--ro-bind', str(path), logical]
    for key, value in dict(ENV, CC=cc).items():
        args += ['--setenv', key, value]
    return args + ['--chdir', '/out', *command]


def run_step(base, name, tcdir, tc, source, seed, emitter, output, command, extra=None):
    directory = new_directory(base / name)
    home, tmp = new_directory(directory / 'home'), new_directory(directory / 'tmp')
    c.require(not any(home.iterdir()) and not any(tmp.iterdir()),
              'cold-cache', 'home and temporary directory must start empty')
    argv = sandbox_command(tcdir / 'root', source, seed, emitter, output, home, tmp,
                           command, tc['compiler']['executable'])
    allowed = dict(tc['executables'])
    if seed is not None:
        allowed['/seed/dawnc'] = c.digest((seed / 'dawnc').read_bytes())
    if emitter is not None:
        allowed['/emitter/dawnc'] = c.digest(emitter.read_bytes())
    allowed.update(extra or {})
    trace = ['/usr/bin/strace', '-ff', '-q', '-yy', '--decode-pids=pidns', '-s', '65535',
             '-e', 'trace=%file,%process,%network', '-o', str(directory / 'trace'), *argv]
    request = {'command': command, 'sandbox': argv, 'allowed_executables': allowed,
               'environment': dict(ENV, CC=tc['compiler']['executable'])}
    c.atomic_json(directory / 'request.json', request)
    with (directory / 'stdout').open('wb') as stdout, (directory / 'stderr').open('wb') as stderr:
        result = subprocess.run(trace, stdin=subprocess.DEVNULL,
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'},
                                stdout=stdout, stderr=stderr, timeout=1800)
    c.require(result.returncode == 0, 'cold-command', f'{name} exited {result.returncode}; see stderr')
    audit = cold_audit.audit(directory, command, allowed,
                             ('/usr', '/lib', '/lib64', '/etc', '/src', '/seed',
                              '/emitter', '/out', '/tmp', '/home', '/dev', '/proc'), argv)
    result = {'name': name, 'request_sha256': c.digest(c.canonical(request)), 'audit': audit,
              'stdout_sha256': c.digest((directory / 'stdout').read_bytes()),
              'stderr_sha256': c.digest((directory / 'stderr').read_bytes())}
    c.atomic_json(directory / 'result.json', result)
    return result


def emission_command(stage):
    return ['/seed/dawnc' if stage == 'A' else '/emitter/dawnc', 'emitc', '--std',
            '/seed/std' if stage == 'A' else '/src/std', '/src/selfhost/src/nmain.dawn',
            '-o', '/out/whole.c', '--build-info', '/out/info.c', '--split', '/out/units']


def compilation_command(stage):
    return ['/usr/bin/bash', '/src/scripts/cc-units.sh', '--static', '--inline-rc',
            '--runtime', '/seed/runtime/c' if stage == 'A' else '/src/runtime/c',
            '-o', '/out/dawnc', '/out/units', '/out/info.c']


def emission_identity(directory):
    c.verify_elf(c.regular_bytes(directory / 'dawnc'))
    return {'whole_sha256': c.digest(c.regular_bytes(directory / 'whole.c')),
            'info_sha256': c.digest(c.regular_bytes(directory / 'info.c')),
            'units': c.inventory(c.scan(directory / 'units')),
            'elf_sha256': c.digest(c.regular_bytes(directory / 'dawnc'))}


def compare_outputs(b, d):
    for key, code in (('whole_sha256', 'fixpoint-whole'), ('info_sha256', 'fixpoint-info'),
                      ('units', 'fixpoint-units'), ('elf_sha256', 'fixpoint-elf')):
        c.require(b[key] == d[key], code, f'B/C differ: {key}; retain outputs and stop')


def check_link(audit, stage, units, compiler):
    sources = ['/out/units/' + row['path'] for row in units
               if row['path'].startswith('tu') and row['path'].endswith('.c')]
    if not sources:
        sources = ['/out/units/main.c']
    sources += ['/seed/runtime/c/dawn_rt.c' if stage == 'A' else '/src/runtime/c/dawn_rt.c',
                '/out/info.c']
    commands = [event['argv'] for event in audit['execs']
                if event['success'] and event['path'] == compiler]
    objects, links = {}, []
    for command in commands:
        if '-c' in command:
            source = command[command.index('-c') + 1]
            obj = command[command.index('-o') + 1]
            c.require(source in sources and source not in objects and obj.startswith('/tmp/'),
                      'audit-link', 'unexpected, duplicate or reused compilation input')
            objects[source] = obj
        elif '-o' in command and command[command.index('-o') + 1] == '/out/dawnc':
            links.append(command)
    c.require(set(objects) == set(sources) and len(set(objects.values())) == len(sources) and
              len(links) == 1, 'audit-link', 'independent object compilation or link is missing')
    linked = [arg for arg in links[0] if arg.endswith('.o')]
    c.require(linked == [objects[source] for source in sources] and '-static' in links[0],
              'audit-link', 'object link order or static link differs')


def execute_root(directory, tcdir, tc, source, seed):
    directory = new_directory(directory)
    steps, stages, plans = [], {}, []
    for stage, previous in (('A', None), ('B', 'A'), ('C', 'B')):
        output = new_directory(directory / stage)
        emitter = directory / previous / 'dawnc' if previous else None
        for suffix, command in (('emit', emission_command(stage)),
                                ('link', compilation_command(stage))):
            steps.append(run_step(directory, stage + '-' + suffix, tcdir, tc, source,
                                  seed, emitter, output, command))
        stages[stage] = emission_identity(output)
        check_link(steps[-1]['audit'], stage, stages[stage]['units'], tc['compiler']['executable'])
        # The old seed needs no new query. Every current compiler uses the one producer.
        command = ['/emitter/dawnc', '__source-inputs', '--base', '/src', '/src/selfhost']
        steps.append(run_step(directory, stage + '-plan', tcdir, tc, source, seed,
                              output / 'dawnc', output, command))
        plans.append((directory / (stage + '-plan') / 'stdout').read_bytes())
        c.require(plans[-1].startswith(b'dawn-source-inputs-v1\n'),
                  'cold-plan', 'unexpected source-inputs wire header')
        if previous:
            # Re-query the emitter after its emission, rather than trusting the next generation.
            steps.append(run_step(directory, stage + '-plan-post', tcdir, tc, source, seed,
                                  emitter, output, command))
            c.require((directory / (stage + '-plan-post') / 'stdout').read_bytes() == plans[0],
                      'cold-plan', 'emitter source plan changed across emission')
    c.require(plans[0] == plans[1] == plans[2], 'cold-plan', 'A/B/C source plans differ')
    compare_outputs(stages['B'], stages['C'])
    smoke = new_directory(directory / 'smoke')
    (smoke / 'hello.dawn').write_text(SMOKE)
    # No source or seed mount: std and runtime must come from the compiler itself.
    steps.append(run_step(directory, 'smoke-build', tcdir, tc, None, None,
                          directory / 'B/dawnc', smoke,
                          ['/emitter/dawnc', 'build', 'hello.dawn', '-o', '/out/hello']))
    hello = c.digest(c.regular_bytes(smoke / 'hello'))
    steps.append(run_step(directory, 'smoke-run', tcdir, tc, None, None, None, smoke,
                          ['/out/hello'], {'/out/hello': hello}))
    c.require((directory / 'smoke-run/stdout').read_bytes() == EXPECTED_SMOKE,
              'cold-smoke', 'bare-directory smoke output differs')
    return {'stages': stages, 'steps': steps, 'plan_sha256': c.digest(plans[0]),
            'smoke_elf_sha256': hello}


def run(args):
    lock, receipt = c.read_lock(args.lock), c.read_json(args.receipt)
    c.verify_inputs(args.repo, args.source, lock, receipt, args.seed, args.seed_tree)
    tc = toolchain.verify(args.toolchain)
    destination = new_directory(args.out)
    # Private materialized copies decouple execution from caller paths and pre-existing caches.
    source = destination / 'inputs/source'
    c.write_tree(source, c.scan(args.source))
    seed = destination / 'inputs/seed'
    paired = {p: item for p, item in c.scan(args.seed_tree).items()
              if p.startswith(('std/', 'runtime/c/'))}
    paired['dawnc'] = ('100755', c.verify_seed(args.seed, lock))
    c.write_tree(seed, paired)
    tcdir = destination / 'toolchain'
    shutil.copytree(args.toolchain, tcdir)
    toolchain.verify(tcdir)
    result = {'schema': 1, 'kind': 'native-cold-chain', 'policy': POLICY,
              'inputs_sha256': c.digest(c.canonical(receipt)),
              'seed_lock_sha256': c.digest(c.canonical(lock)),
              'toolchain_sha256': c.digest(c.canonical(tc)),
              'source_commit': receipt['source']['commit'], 'source_tree': receipt['source']['tree'],
              'recipe_sha256': c.digest((source / 'scripts/cc-units.sh').read_bytes()),
              'orchestrator_sha256': c.digest(Path(__file__).read_bytes()),
              'auditor_sha256': c.digest(Path(cold_audit.__file__).read_bytes()),
              'isolation_tools': {name: c.digest(Path('/usr/bin', name).read_bytes())
                                  for name in ('bwrap', 'strace')}, 'roots': {}}
    c.atomic_json(destination / 'inputs.json', receipt)
    c.atomic_json(destination / 'seed-lock.json', lock)
    for name in ('root-1', 'root-2'):
        print(f'cold: {name} S -> A -> B -> C', flush=True)
        result['roots'][name] = execute_root(destination / name, tcdir, tc, source, seed)
        c.verify_inputs(args.repo, source, lock, receipt, seed / 'dawnc', seed)
        toolchain.verify(tcdir)
    one, two = result['roots'].values()
    c.require(one['stages']['B'] == two['stages']['B'], 'cold-reproduction', 'independent roots differ')
    verify(args.repo, destination, result)
    c.atomic_json(destination / 'receipt.json', result)
    return result


def verify(repo, directory, value=None):
    directory = Path(directory).absolute()
    if value is None:
        value = c.read_json(directory / 'receipt.json')
    c.fields(value, 'schema kind policy inputs_sha256 seed_lock_sha256 toolchain_sha256 source_commit source_tree recipe_sha256 orchestrator_sha256 auditor_sha256 isolation_tools roots', 'cold receipt')
    c.require(type(value['schema']) is int and value['schema'] == 1 and
              value['kind'] == 'native-cold-chain' and value['policy'] == POLICY,
              'cold-receipt', 'unknown cold receipt')
    lock, receipt = c.read_lock(directory / 'seed-lock.json'), c.read_json(directory / 'inputs.json')
    source, seed, tcdir = directory / 'inputs/source', directory / 'inputs/seed', directory / 'toolchain'
    c.verify_inputs(repo, source, lock, receipt, seed / 'dawnc', seed)
    tc = toolchain.verify(tcdir)
    c.require(value['isolation_tools'] == {name: c.digest(Path('/usr/bin', name).read_bytes())
                                         for name in ('bwrap', 'strace')},
              'cold-identity', 'isolation or tracing tool differs')
    for actual, expected in ((value['inputs_sha256'], c.digest(c.canonical(receipt))),
                             (value['seed_lock_sha256'], c.digest(c.canonical(lock))),
                             (value['toolchain_sha256'], c.digest(c.canonical(tc))),
                             (value['recipe_sha256'], c.digest((source / 'scripts/cc-units.sh').read_bytes())),
                             (value['orchestrator_sha256'], c.digest(Path(__file__).read_bytes())),
                             (value['auditor_sha256'], c.digest(Path(cold_audit.__file__).read_bytes()))):
        c.require(actual == expected, 'cold-identity', 'receipt input or implementation identity differs')
    c.require(value['source_commit'] == receipt['source']['commit'] and
              value['source_tree'] == receipt['source']['tree'] and
              set(value['roots']) == {'root-1', 'root-2'}, 'cold-identity', 'source or roots differ')
    for name, root in value['roots'].items():
        c.fields(root, 'stages steps plan_sha256 smoke_elf_sha256', 'cold root')
        base = directory / name
        outputs = {stage: emission_identity(base / stage) for stage in ('A', 'B', 'C')}
        c.require(outputs == root['stages'], 'cold-output', 'stage bytes differ')
        compare_outputs(outputs['B'], outputs['C'])
        expected_steps = []
        for stage, previous in (('A', None), ('B', 'A'), ('C', 'B')):
            expected_steps += [(stage + '-emit', emission_command(stage)),
                               (stage + '-link', compilation_command(stage)),
                               (stage + '-plan', ['/emitter/dawnc', '__source-inputs', '--base', '/src', '/src/selfhost'])]
            if previous:
                expected_steps.append((stage + '-plan-post', expected_steps[-1][1]))
        expected_steps += [('smoke-build', ['/emitter/dawnc', 'build', 'hello.dawn', '-o', '/out/hello']),
                           ('smoke-run', ['/out/hello'])]
        c.require(len(root['steps']) == len(expected_steps), 'audit-coverage', 'missing or extra step')
        for step, (step_name, command) in zip(root['steps'], expected_steps):
            c.fields(step, 'name request_sha256 audit stdout_sha256 stderr_sha256', 'cold step')
            request = c.read_json(base / step_name / 'request.json')
            c.require(step['name'] == step_name and request['command'] == command and
                      step['request_sha256'] == c.digest(c.canonical(request)),
                      'audit-coverage', 'step command or identity differs')
            selected_source, selected_seed = source, seed
            if step_name.startswith('smoke-'):
                selected_source, selected_seed = None, None
                output = base / 'smoke'
                emitter = base / 'B/dawnc' if step_name == 'smoke-build' else None
            else:
                stage, phase = step_name.split('-', 1)
                output = base / stage
                previous = {'A': None, 'B': 'A', 'C': 'B'}[stage]
                generation = stage if phase == 'plan' else previous
                emitter = base / generation / 'dawnc' if generation else None
            allowed = dict(tc['executables'])
            if selected_seed:
                allowed['/seed/dawnc'] = lock['seed']['sha256']
            if emitter:
                allowed['/emitter/dawnc'] = c.digest(emitter.read_bytes())
            if step_name == 'smoke-run':
                allowed['/out/hello'] = root['smoke_elf_sha256']
            sandbox = sandbox_command(tcdir / 'root', selected_source, selected_seed, emitter,
                                       output, base / step_name / 'home', base / step_name / 'tmp',
                                       command, tc['compiler']['executable'])
            c.require(request == {'command': command, 'sandbox': sandbox,
                                  'allowed_executables': allowed,
                                  'environment': dict(ENV, CC=tc['compiler']['executable'])},
                      'audit-isolation', 'mount, environment or executable policy differs')
            audit = cold_audit.audit(base / step_name, command, request['allowed_executables'],
                                     ('/usr', '/lib', '/lib64', '/etc', '/src', '/seed',
                                      '/emitter', '/out', '/tmp', '/home', '/dev', '/proc'), sandbox)
            c.require(audit == step['audit'], 'audit-identity', 'execution audit differs')
            if step_name.endswith('-link'):
                check_link(audit, step_name[0], outputs[step_name[0]]['units'], tc['compiler']['executable'])
            for stream in ('stdout', 'stderr'):
                c.require(c.digest((base / step_name / stream).read_bytes()) == step[stream + '_sha256'],
                          'audit-identity', 'step transcript differs')
        plans = [(base / (s + '-plan/stdout')).read_bytes() for s in ('A', 'B', 'C')]
        c.require(plans[0] == plans[1] == plans[2] and c.digest(plans[0]) == root['plan_sha256'],
                  'cold-plan', 'source plan differs')
        c.require((base / 'smoke-run/stdout').read_bytes() == EXPECTED_SMOKE and
                  c.digest((base / 'smoke/hello').read_bytes()) == root['smoke_elf_sha256'],
                  'cold-smoke', 'smoke evidence differs')
    c.require(value['roots']['root-1']['stages']['B'] == value['roots']['root-2']['stages']['B'],
              'cold-reproduction', 'independent roots differ')
    return value

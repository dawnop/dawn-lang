"""Explicit stage selection for the shared split-C recipe, not a cold runner."""

import os
from pathlib import Path
import re
import subprocess
import tempfile

import native_seed.contract as c


def stage_inputs(repo, lock, receipt, source, seed_tree, stage, std, runtime):
    c.validate_lock(lock)
    c.validate_receipt(receipt, lock)
    c.require(stage in ('A', 'B', 'C'), 'stage-pairing', 'expected A, B or C')
    c.verify_source(repo, source, receipt)
    c.verify_seed_tree(repo, lock, seed_tree)
    selected = receipt['stages'][('A', 'B', 'C').index(stage)]
    base = Path(seed_tree if stage == 'A' else source).absolute()
    for key, path, suffix in (('std', std, 'std'), ('runtime', runtime, 'runtime/c')):
        expected = base / suffix
        c.require(Path(path).absolute() == expected, f'{key}-pairing',
                  f'{stage} requires its explicit {key} directory')
        actual = c.inventory_sha(c.inventory(c.scan(expected)))
        c.require(actual == selected[key]['sha256'], f'{key}-pairing',
                  f'{stage} {key} bytes differ from the input receipt')
    return selected


def compiler_probe(cc, env):
    cc = Path(cc)
    c.require(cc.is_absolute() and cc.is_file() and os.access(cc, os.X_OK),
              'cc-identity', 'an explicit executable compiler path is required')
    cc = cc.resolve()

    def query(flag):
        result = subprocess.run([str(cc), flag], env=env, capture_output=True, timeout=20)
        c.require(result.returncode == 0 and not result.stderr,
                  'cc-identity', f'compiler probe failed: {flag}')
        return result.stdout.decode('utf-8').strip()

    version = query('--version')
    c.require(re.search(r'\bclang version 18\.1\.3\b', version) and
              query('-dumpversion') == '18.1.3', 'cc-version', 'clang 18.1.3 is required')
    triple = query('-dumpmachine')
    c.require(re.fullmatch(r'x86_64-(?:[a-z0-9_]+-)?linux-gnu', triple),
              'cc-target', 'x86_64 GNU Linux compiler required')
    resource = query('-print-resource-dir')
    c.require(Path(resource).is_absolute() and Path(resource).is_dir(),
              'cc-identity', 'compiler resource directory missing')
    return {'executable': str(cc), 'sha256': c.digest(cc.read_bytes()),
            'version': version, 'triple': triple, 'resource_dir': resource}


def compile_stage(args):
    lock = c.read_lock(args.lock)
    receipt = c.read_json(args.receipt)
    selected = stage_inputs(args.repo, lock, receipt, args.source, args.seed_tree,
                            args.stage, args.std, args.runtime)
    c.require(args.jobs in (1, 2), 'cc-jobs', 'qualification compile concurrency must be 1 or 2')
    out = c.safe_destination(args.out)
    recipe_out = c.safe_destination(args.recipe_out)
    c.require(not out.exists() and not recipe_out.exists() and out != recipe_out,
              'destination', 'new binary and recipe paths required')
    c.require(out.parent.is_dir(), 'destination', 'binary parent must exist')
    units = Path(args.units).absolute()
    c.scan(units)
    info = Path(args.build_info).absolute()
    c.regular_bytes(info)
    script = Path(__file__).resolve().parents[1] / 'cc-units.sh'
    recipe_sha = c.digest(script.read_bytes())
    with tempfile.TemporaryDirectory(prefix='native-stage-cc-', dir=out.parent) as work:
        # No inherited CFLAGS, include paths, Java, cache or std selections.
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
               'TZ': 'UTC', 'HOME': work, 'TMPDIR': work}
        probe = compiler_probe(args.cc, env)
        env['PATH'] = str(Path(probe['executable']).parent) + ':' + env['PATH']
        env['CC'] = probe['executable']
        env['CC_JOBS'] = str(args.jobs)
        command = [str(script), '--static', '--inline-rc', '--runtime',
                   str(Path(args.runtime).absolute()), '-o', str(out), str(units), str(info)]
        run = subprocess.run(command, env=env)
        c.require(run.returncode == 0, 'cc-build', f'shared recipe exited {run.returncode}')
        stage_inputs(args.repo, lock, receipt, args.source, args.seed_tree,
                     args.stage, args.std, args.runtime)
        c.require(c.digest(Path(probe['executable']).read_bytes()) == probe['sha256'],
                  'cc-identity', 'compiler bytes changed during compilation')
        c.require(c.digest(script.read_bytes()) == recipe_sha,
                  'cc-identity', 'shared recipe changed during compilation')
        binary = c.regular_bytes(out)
        c.verify_elf(binary)
        result = {'schema': 1, 'kind': 'native-stage-compile', 'stage': args.stage,
                  'inputs_sha256': c.digest(c.canonical(receipt)), 'selection': selected,
                  'recipe_sha256': recipe_sha, 'command': command,
                  'compiler_probe': probe, 'jobs': args.jobs, 'output_sha256': c.digest(binary)}
        c.atomic_json(recipe_out, result)
    return result

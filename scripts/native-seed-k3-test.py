#!/usr/bin/env python3
"""One-time cold policy fixtures and a real descendant Java-name canary."""

import argparse
import copy
from pathlib import Path
import sys

from native_seed import cold, cold_audit, contract as c, toolchain


def fixtures(destination):
    destination = cold.new_directory(destination)
    results = []

    def rejected(name, code, action):
        try:
            action()
        except c.Rejected as exc:
            c.require(str(exc).startswith(code + ':'), 'fixture', f'{name}: wrong refusal: {exc}')
            results.append({'name': name, 'expected': code, 'actual': str(exc)})
        else:
            raise c.Rejected(f'fixture: {name}: guard accepted the mutation')

    def trace(name, child, parent=None):
        directory = cold.new_directory(destination / name)
        (directory / 'trace.10').write_text(parent or
            'execve("/test/driver", ["/test/driver"], 0x1 /* 0 vars */) = 0\n'
            'clone(child_stack=NULL, flags=SIGCHLD) = 11\n+++ exited with 0 +++\n')
        if child is not None:
            (directory / 'trace.11').write_text(child)
        return directory

    good_child = ('execve("/test/child", ["/test/child"], 0x1 /* 0 vars */) = 0\n'
                  'openat(AT_FDCWD</out>, "/out/new.c", O_RDONLY) = 3</out/new.c>\n'
                  'openat(AT_FDCWD</out>, "/dev/fd/63", O_RDONLY) = 4<pipe:[123]>\n'
                  '+++ exited with 0 +++\n')
    allowed = {'/test/driver': '0' * 64, '/test/child': '1' * 64}

    def audit(path):
        return cold_audit.audit(path, ['/test/driver'], allowed, ('/out',))

    positive = audit(trace('positive', good_child))
    c.require(positive['descendants'] == 2 and positive['java_execs'] == 0,
              'fixture', 'valid descendant coverage missing')
    results.append({'name': 'positive-descendant', 'descendants': 2, 'java_execs': 0})
    translated = trace('translated-pids', good_child,
        'execve("/test/driver", ["/test/driver"], 0x1 /* 0 vars */) = 0\n'
        "clone(child_stack=NULL, flags=SIGCHLD) = 3 /* 11 in strace's PID NS */\n"
        '+++ exited with 0 +++\n')
    c.require(audit(translated)['descendants'] == 2, 'fixture', 'PID namespace translation lost a child')
    results.append({'name': 'translated-pids', 'descendants': 2})
    rejected('java-child', 'audit-java', lambda: audit(trace('java-child',
        good_child.replace('/test/child', '/test/java'))))
    rejected('missing-child', 'audit-coverage', lambda: audit(trace('missing-child', None)))
    rejected('unknown-child', 'audit-executable', lambda: audit(trace('unknown-child',
        good_child.replace('/test/child', '/test/unknown'))))
    rejected('outside-read', 'audit-read', lambda: audit(trace('outside-read',
        good_child.replace('/out/new.c', '/outside/cache.o'))))
    rejected('network', 'audit-network', lambda: audit(trace('network',
        good_child.replace('+++ exited', 'socket(AF_INET, SOCK_STREAM, 0) = 4\n+++ exited'))))
    rejected('skipped-command', 'audit-coverage', lambda: audit(trace('skipped-command', good_child,
        'execve("/test/other", ["/test/other"], 0x1 /* 0 vars */) = 0\n+++ exited with 0 +++\n')))
    rejected('namespace-argv', 'audit-isolation', lambda: cold_audit.audit(
        trace('namespace-argv', good_child), ['/test/driver'], allowed, ('/out',),
        ['/usr/bin/bwrap', '--unshare-all']))
    warm = cold.new_directory(destination / 'warm')
    (warm / 'cached.o').write_text('old object\n')
    rejected('warm-directory', 'cold-directory', lambda: cold.new_directory(warm))
    b = {'whole_sha256': '1', 'info_sha256': '2', 'units': [{'path': 'tu00.c', 'sha256': '3'}],
         'elf_sha256': '4'}
    for key, code in (('whole_sha256', 'fixpoint-whole'), ('info_sha256', 'fixpoint-info'),
                      ('units', 'fixpoint-units'), ('elf_sha256', 'fixpoint-elf')):
        changed = copy.deepcopy(b)
        changed[key] = [] if key == 'units' else 'changed'
        rejected(code, code, lambda changed=changed: cold.compare_outputs(b, changed))
    c.atomic_json(destination / 'results.json', results)
    return results


def real_canary(destination, tcdir, seed_path, lock_path):
    destination = cold.new_directory(destination)
    tc = toolchain.verify(tcdir)
    lock = c.read_lock(lock_path)
    data = c.verify_seed(seed_path, lock)
    seed = destination / 'seed'
    c.write_tree(seed, {'dawnc': ('100755', data), 'java': ('100755', data)})
    output = cold.new_directory(destination / 'output')
    command = ['/usr/bin/bash', '-c', '/seed/java --version; :']
    try:
        cold.run_step(destination, 'canary', tcdir, tc, None, seed, None, output, command,
                      {'/seed/java': c.digest(data)})
    except c.Rejected as exc:
        c.require(str(exc).startswith('audit-java:'), 'fixture', f'wrong real canary refusal: {exc}')
        events = [event for lines in cold_audit.traces(destination / 'canary').values()
                  for line in lines if (event := cold_audit.exec_record(line)) and event['success']]
        java = [e for e in events if e['path'] == '/seed/java']
        c.require(len(java) == 1 and not (destination / 'canary/result.json').exists(),
                  'fixture', 'canary did not execute or left a success result')
        result = {'expected': 'audit-java', 'actual': str(exc), 'successful_java_name_execs': 1,
                  'seed_sha256': c.digest(data), 'qualified_receipt': False}
        c.atomic_json(destination / 'result.json', result)
        return result
    raise c.Rejected('fixture: real Java-name child was accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path)
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--lock', type=Path)
    args = parser.parse_args()
    try:
        fixtures(args.out / 'fixtures')
        if any((args.toolchain, args.seed, args.lock)):
            c.require(all((args.toolchain, args.seed, args.lock)), 'fixture', 'all canary inputs required')
            real_canary(args.out / 'real-canary', args.toolchain, args.seed, args.lock)
        print('OK cold policy fixtures and requested execution canary')
    except (c.Rejected, OSError, ValueError) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

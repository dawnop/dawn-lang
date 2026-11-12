"""Read descendant traces independently of the cold-chain producer."""

import ast
from pathlib import Path
import re

from native_seed import contract as c

QUOTED = r'"(?:[^"\\]|\\.)*"'
JAVA = re.compile(r'^(?:java|javac|javaw|jshell)(?:[.-].*)?$', re.I)


def traces(directory):
    result = {}
    for path in sorted(Path(directory).glob('trace.*')):
        suffix = path.name.split('.')[-1]
        c.require(suffix.isdigit(), 'audit-trace', 'invalid trace filename')
        result[int(suffix)] = path.read_text().splitlines()
    c.require(result, 'audit-trace', 'no descendant traces')
    return result


def exec_record(line):
    if not re.match(r'execve(?:at)?\(', line):
        return None
    # Both path and complete argv must be visible; truncated/unfinished execs cannot qualify.
    m = re.match(r'execve\((' + QUOTED + r'), (\[.*\]), .*\) = (.*)$', line)
    c.require(m is not None, 'audit-exec', 'unrecognized or truncated exec event')
    try:
        path = ast.literal_eval(m[1])
        argv = ast.literal_eval(m[2])
    except (ValueError, SyntaxError) as exc:
        raise c.Rejected('audit-exec: invalid exec strings') from exc
    return {'path': path, 'argv': argv, 'success': m[3] == '0'}


def audit(directory, command, allowed, input_prefixes, sandbox=None):
    logs = traces(directory)
    if sandbox is not None:
        setups = [event for lines in logs.values() for line in lines
                  if (event := exec_record(line)) and event['success'] and
                  event['path'] == '/usr/bin/bwrap']
        c.require(len(setups) == 1 and setups[0]['argv'] == sandbox,
                  'audit-isolation', 'namespace setup command differs')
    roots = []
    for pid, lines in logs.items():
        for index, line in enumerate(lines):
            event = exec_record(line)
            if event and event['success'] and event['argv'] == command:
                roots.append((pid, index))
    c.require(len(roots) == 1, 'audit-coverage', 'expected exactly one payload execution')
    selected = {roots[0][0]: roots[0][1]}
    pending = list(selected)
    while pending:
        pid = pending.pop()
        for line in logs[pid][selected[pid]:]:
            m = re.match(r'(?:clone|clone3|fork|vfork)\(.*\) = (\d+)'
                         r'(?: /\* (\d+) in strace\'s PID NS \*/)?$', line)
            if m:
                child = int(m[2] or m[1])
                c.require(child in logs, 'audit-coverage', 'missing child trace')
                if child not in selected:
                    selected[child] = 0
                    pending.append(child)
            elif re.match(r'(?:clone|clone3|fork|vfork)\(', line):
                c.require(') = -1 ' in line, 'audit-coverage', 'unrecognized process creation event')
    execs, opens, networks, nss_misses = [], [], [], []
    for pid, index in sorted(selected.items()):
        lines = logs[pid][index:]
        c.require(lines and re.fullmatch(r'\+\+\+ exited with 0 \+\+\+', lines[-1]),
                  'audit-exit', f'payload descendant {pid} did not exit successfully')
        for line in lines:
            event = exec_record(line)
            if event:
                event['pid'] = pid
                execs.append(event)
            if re.match(r'(?:socket|connect|sendto|sendmsg|recvfrom|recvmsg)\(', line):
                if line.startswith('socket(AF_UNIX,'):
                    pass
                elif (line.startswith('connect(') and 'sa_family=AF_UNIX' in line and
                      'sun_path="/var/run/nscd/socket"' in line and ') = -1 ENOENT ' in line):
                    nss_misses.append(line)
                else:
                    networks.append(line)
            if re.match(r'open(?:at|at2)?\(', line):
                m = re.search(r'\) = \d+<(/.*)>$', line)
                if m:
                    path = m[1].split('<', 1)[0].removesuffix(' (deleted)')
                    c.require(any(path == p or path.startswith(p + '/') for p in input_prefixes),
                              'audit-read', f'undeclared successful open: {path}')
                    opens.append(path)
                else:
                    pipe = re.search(r'"((?:/dev/fd|/proc/(?:self|[0-9]+)/fd)/[0-9]+)"', line)
                    if pipe and re.search(r'\) = \d+<pipe:\[[0-9]+\]>$', line):
                        opens.append(pipe[1])
                    else:
                        c.require(re.search(r'\) = -1 ', line), 'audit-read', 'unresolved open event')
    java = [e for e in execs if JAVA.fullmatch(Path(e['path']).name)]
    c.require(not java, 'audit-java', f'Java-name exec count: {len(java)}')
    for event in execs:
        c.require(event['path'] in allowed, 'audit-executable',
                  f'undeclared executable: {event["path"]}')
    c.require(not networks, 'audit-network', 'network syscall in execution payload')
    successful = [e for e in execs if e['success']]
    c.require(successful and successful[0]['argv'] == command,
              'audit-coverage', 'payload command differs')
    return {'descendants': len(selected), 'execs': execs, 'java_execs': 0,
            'successful_opens': sorted(set(opens)), 'network_syscalls': 0,
            'absent_local_nss_probes': len(nss_misses),
            'trace_files': {p.name: c.digest(p.read_bytes())
                            for p in sorted(Path(directory).glob('trace.*'))}}

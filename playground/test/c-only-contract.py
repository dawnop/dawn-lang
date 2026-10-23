#!/usr/bin/env python3
"""Exercise native C requests from the HTTP entry with every JVM tool poisoned.

The sentinels cover probes as well as compilation. The answer-store fixtures
use wire bytes, so normalization cannot hide a schema or field-order change.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

runner, dawnc = map(str, map(Path, sys.argv[1:3]))
hello = 'pub fn main() -> Unit !io = println("native-only")\n'
canonical = os.environ['PLAY_TOOLCHAIN_ID']


def normalized(b):
    return re.sub(rb'"ms":\d+', b'"ms":0', b).replace(b'"cached":true', b'"cached":false')


def key(tc, code, target):
    form = 'project' if 'use tileir/' in code else 'file'
    return hashlib.sha256(f'{tc}\n{form}\n{code}'.encode()).hexdigest() + '.' + target


with tempfile.TemporaryDirectory(prefix='play-c-contract.') as work:
    w = Path(work)
    calls = w / 'jvm-calls'
    spy = w / 'spy'
    spy.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >>' + shlex.quote(str(calls)) + '\nexit 99\n')
    spy.chmod(0o755)
    answers = w / 'answers'
    answers.mkdir()
    env = dict(os.environ, DAWN_BIN=str(spy), PLAY_JAVA=str(spy), PLAY_JAVAP=str(spy),
               DAWNC_BIN=dawnc, PLAY_ANSWERS=str(answers), PLAY_COMPILE_TIMEOUT='30')

    def request(code=hello, target='c', changes=None, raw=None):
        body = raw if raw is not None else json.dumps({'code': code, 'target': target}).encode()
        wire = b'POST /compile HTTP/1.1\r\nHost: x\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
        e = env | (changes or {})
        p = subprocess.run([runner, 'serve'], input=wire, capture_output=True, env=e, timeout=45)
        assert p.returncode == 0, p.stderr
        head, response = p.stdout.split(b'\r\n\r\n', 1)
        return int(head.split()[1]), json.loads(response), response

    status, c, live = request()
    assert status == 200 and c['ok'] and c['gaps']['count'] == 0 and not c['cached'], c
    assert not calls.exists(), 'C reached a JVM executable'
    status, d, _ = request(target='jvm', changes={'PLAY_JAVAP': '/nonexistent/javap'})
    assert status == 503 and 'javap' in d['output'], d
    for metadata in ('', 'missing', '0.100.0', '0.100.0 b1:xyz'):
        status, d, _ = request(changes={'PLAY_TOOLCHAIN_ID': metadata})
        assert status == 503 and 'metadata' in d['output'], d
    status, d, _ = request(changes={'DAWNC_BIN': '/nonexistent/dawnc'})
    assert status == 503 and 'dawnc' in d['output'], d
    fault = w / 'dawnc-fault'
    for name in ('wrong', 'empty', 'timeout', 'diagnostic'):
        probe = "echo 'dawnc 0.0.0 (native)'" if name == 'wrong' else 'exec ' + shlex.quote(dawnc) + ' "$@"'
        action = {'wrong': 'exit 91', 'empty': 'exit 1', 'timeout': 'sleep 5; exit 1',
                  'diagnostic': "echo 'error: deliberate native diagnostic'; exit 1"}[name]
        fault.write_text(f'#!/bin/sh\nif [ "$1" = --version ]; then {probe}; fi\n{action}\n')
        fault.chmod(0o755)
        status, d, _ = request(changes={'DAWNC_BIN': str(fault), 'PLAY_COMPILE_TIMEOUT': '1'})
        assert status == {'wrong': 503, 'empty': 500}.get(name, 200), (name, status, d)
        assert not d['ok'], (name, d)
        assert {'wrong': 'dawnc', 'empty': 'without diagnostics', 'timeout': 'timed out',
                'diagnostic': 'deliberate native diagnostic'}[name] in d['output'], (name, d)
    status, d, _ = request(code='use java "java.lang.System"\npub fn main() -> Unit = ()\n')
    assert status == 200 and not d['ok'] and '`use java` is not available in this compiler' in d['output'], d
    for body, wanted in [(b'\xff', 400), (b'{}', 400), (b'{"target":"c","code":3}', 400),
                         (json.dumps({'target': 'c', 'code': '/' * 70000}).encode(), 413)]:
        assert request(raw=body)[0] == wanted
    assert not calls.exists(), 'a C error or refusal reached a JVM executable'
    assert not list(answers.iterdir()), 'serving wrote a runtime answer'
    print('OK: HTTP C success/errors/metadata/native faults/timeouts: zero JVM processes; JVM without javap is 503')

    # Legacy answers, including a deliberately poisoned body, must miss.
    (answers / key(canonical + ' present', hello, 'c')).write_text('200:S:"poison":true}')
    assert request()[1]['cached'] is False
    # New C namespace accepts only its own target. JVM poison cannot satisfy C.
    (answers / key('play-jvm-paired-v1\n' + canonical + ' present', hello, 'jvm')).write_text('200:S:"poison":true}')
    assert request()[1]['cached'] is False
    rest = re.split(rb'"ms":\d+,', live, maxsplit=1)[1]
    ckey = answers / key('play-c-native-v1\n' + canonical, hello, 'c')
    ckey.write_bytes(b'200:S:' + rest)
    before = {p.name: p.read_bytes() for p in answers.iterdir()}
    for javap in (str(spy), '/nonexistent/javap'):
        status, d, hit = request(changes={'PLAY_JAVAP': javap})
        assert status == 200 and d['cached'] is True and normalized(hit) == normalized(live), d
    assert request(changes={'DAWNC_BIN': '/nonexistent/dawnc'})[0] == 503
    assert request(changes={'PLAY_TOOLCHAIN_ID': ''})[0] == 503
    assert request(code=hello + ' ')[1]['cached'] is False
    other = canonical.replace('b1:', 'b1:0')[:-1]
    assert request(changes={'PLAY_TOOLCHAIN_ID': other})[1]['cached'] is False
    assert before == {p.name: p.read_bytes() for p in answers.iterdir()}
    assert not calls.exists(), 'a C cache path reached a JVM executable'
    print('OK: legacy/schema/target/source/toolchain isolation, javap-independent C hit, hit/live byte equality, read-only store')

    # Tool presence and tool execution are different failures on the retained
    # JVM path. Restore only the real compiler, then fail javap itself.
    real_dawn = os.environ.get('DAWN_BIN', str(Path(__file__).resolve().parents[2] / 'bin/dawn'))
    assert request(target='jvm', changes={'PLAY_JAVAP': '/nonexistent/javap'})[0] == 503
    status, d, _ = request(code=hello + ' ', target='jvm', changes={'DAWN_BIN': real_dawn})
    assert status == 500 and 'listing tool failed' in d['output'], d
    assert calls.exists(), 'the JVM probe did not reach the failing listing tool'
    calls.unlink()
    assert request()[1]['cached'] is True and not calls.exists()
    print('OK: JVM javap execution failure is 500; C hit remains usable and independent')

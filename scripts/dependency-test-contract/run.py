#!/usr/bin/env python3
"""Judge package ownership through real products and observable test execution.

Aliases and a transitive package rule out name and directory heuristics. The
native host leg reuses the driver built by native-selfhost-tests. A compilable
mutation must expose dependency test bytecode and reject a test-only type error.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def run(cmd, ok=True):
    p = subprocess.run(list(map(str, cmd)), cwd=ROOT, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert (p.returncode == 0) == ok, (cmd, p.returncode, p.stdout)
    return p.stdout


def refusal(cmd, reason):
    text = run(cmd, ok=False)
    assert reason in text, (cmd, reason, text)
    return text


def fixture(work):
    for name in ('app', 'dep', 'leaf'):
        (work / name / 'src').mkdir(parents=True)
    (work / 'app/dawn.toml').write_text('schema = 1\nname = "r3_app"\n[deps]\nrenamed = "../dep"\n')
    (work / 'dep/dawn.toml').write_text('schema = 1\nname = "r3_dep"\n[deps]\nother = "../leaf"\n')
    (work / 'leaf/dawn.toml').write_text('schema = 1\nname = "r3_leaf"\n')
    (work / 'app/src/main.dawn').write_text('use renamed/lib\npub fn main() -> Unit !io = println(to_string(lib.value()))\ntest "own test" { println("R3_OWN_TEST_BODY")\n  assert true }\n')
    dep = 'use other/lib\nuse std/str\npub fn value() -> Int = lib.value() + 1\ntest "dependency test" { println(str.trim("R3_DEP_TEST_BODY"))\n  assert true }\ntest value { assert value() == 42 }\n'
    leaf = 'pub fn value() -> Int = 41\ntest "transitive test" { println("R3_LEAF_TEST_BODY")\n  assert true }\n'
    (work / 'dep/src/lib.dawn').write_text(dep)
    (work / 'leaf/src/lib.dawn').write_text(leaf)
    return work / 'app', dep, leaf


def jvm_payload(path):
    with zipfile.ZipFile(path) as jar:
        return b''.join(jar.read(n) for n in jar.namelist() if n.endswith('.class'))


def probe(work, cmd, native=False):
    app, dep, leaf = fixture(work)
    assert run(cmd + ['check', app]).strip() == 'ok'
    assert run(cmd + ['run', app]).strip() == '42'
    report = run(cmd + ['test', app])
    for marker in ('R3_OWN_TEST_BODY', 'R3_DEP_TEST_BODY', 'R3_LEAF_TEST_BODY', 'example value'):
        assert marker in report, (marker, report)
    out = work / ('product' if native else 'product.jar')
    run(cmd + ['build', app, '-o', out])
    if native:
        assert run([out]).strip() == '42'
        payload = out.read_bytes()
    else:
        assert run(['java', '-XX:-UsePerfData', '-jar', out]).strip() == '42'
        payload = jvm_payload(out)
        assert b'R3_OWN_TEST_BODY' in payload
    for marker in (b'R3_DEP_TEST_BODY', b'R3_LEAF_TEST_BODY'):
        assert marker not in payload, marker
    if not native:
        classes = work / 'classes'
        run(cmd + ['__emit', app, '-o', classes])
        for p in classes.rglob('*.class'):
            if 'dawn$pkg$' in str(p):
                assert b'dawn$test$' not in p.read_bytes(), p
    cfile = work / 'product.c'
    run(cmd + [('emitc' if native else '__emitc'), app, '-o', cfile])
    for marker in ('R3_DEP_TEST_BODY', 'R3_LEAF_TEST_BODY'):
        assert marker not in cfile.read_text(), marker
    # A failing test in either dependency still executes and fails the suite.
    for package, original, label in (('dep', dep, 'dependency test'), ('leaf', leaf, 'transitive test')):
        file = work / package / 'src/lib.dawn'
        file.write_text(original.replace('assert true', 'assert false'))
        failed = run(cmd + ['test', app], ok=False)
        assert label in failed and 'FAIL' in failed, failed
        file.write_text(original)
    # Only test bodies are excluded. Syntax and ordinary declarations retain diagnostics.
    file = work / 'dep/src/lib.dawn'
    file.write_text(dep + 'test "type error" { let x: Int = "bad"\n  assert x == 0 }\n')
    assert run(cmd + ['check', app]).strip() == 'ok'
    assert run(cmd + ['run', app]).strip() == '42'
    run(cmd + ['build', app, '-o', out])
    run(cmd + [('emitc' if native else '__emitc'), app, '-o', cfile])
    refusal(cmd + ['test', app], 'annotated type is Int but the initializer is String')
    file.write_text(dep + 'test missing { assert true }\n')
    assert run(cmd + ['check', app]).strip() == 'ok'
    assert 'missing' in run(cmd + ['test', app], ok=False)
    file.write_text(dep + 'fn broken() -> Int = "bad"\n')
    refusal(cmd + ['check', app], 'function `broken` declares return type Int but its body is String')
    file.write_text(dep + 'test "syntax error" { let x = }\n')
    run(cmd + ['check', app], ok=False)
    file.write_text(dep)
    # The same package as the target owns its tests and checks their bodies.
    file.write_text(dep + 'test "type error" { let x: Int = "bad"\n  assert x == 0 }\n')
    refusal(cmd + ['check', work / 'dep'], 'annotated type is Int but the initializer is String')
    file.write_text(dep)
    print('PASS dependency products, test discovery, execution and diagnostic boundaries', flush=True)


def mutant(work):
    tree = work / 'mutant'
    tree.mkdir()
    shutil.copytree(ROOT / 'selfhost', tree / 'selfhost')
    shutil.copytree(ROOT / 'compiler-plan', tree / 'compiler-plan')
    (tree / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
    run(['python3', HERE / 'mutate.py', 'retain-dependency-tests', tree])
    jar = tree / 'compiler.jar'
    run([ROOT / 'bin/dawn', 'build', tree / 'selfhost', '-o', jar,
         '--vendor', 'org/objectweb/asm', '--vendor', 'coursierapi'])
    cmd = ['java', '-XX:-UsePerfData', '-Xss512m', '-Xmx2g', '-jar', jar]
    app, dep, _ = fixture(work / 'mutant-fixture')
    out = work / 'mutant.jar'
    run(cmd + ['build', app, '-o', out])
    assert b'R3_DEP_TEST_BODY' in jvm_payload(out), 'mutant did not expose the test body'
    # The native emitter used to omit tests already. Its red oracle is the
    # test-only type error reaching analysis again, before C emission.
    (work / 'mutant-fixture/dep/src/lib.dawn').write_text(dep + 'test "type error" { let x: Int = "bad"\n  assert x == 0 }\n')
    for mode in ('check', '__emitc'):
        refusal(cmd + [mode, app], 'annotated type is Int but the initializer is String')
    print('PASS retain-dependency-tests mutant builds and turns both owning oracles red', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-host')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='dependency-tests-', dir=os.environ.get('TMPDIR')) as d:
        work = Path(d)
        cmd = [args.native_host] if args.native_host else [ROOT / 'bin/dawn']
        probe(work / 'fixture', cmd, bool(args.native_host))
        if not args.native_host:
            mutant(work)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Exercise std source identities through real LSP reading and editing sessions.

The content request and didOpen use the URI returned by definition, never a
constructed substitute. Mutation owners live in lsp-semantic-tokens/mutate.py;
each compiler must build before its owning assertion is required to fail.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tokens', ROOT / 'scripts/lsp-semantic-tokens.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
USER = '''use std/math
use std/math.{exp as host_exp}
use std/narrow.{BF16, F32, f32}
use std/dtype.{Dtype}
use std/cursor.{start}
fn demo(x: BF16) -> F32 = f32(host_exp(math.exp(1.0)))
fn witness() -> Dtype[F32] = F32
fn scan(s: String) -> Unit = { let _ = start(s) }
fn count() -> Int = len([1])
fn helper(x: Int) -> Int = {
  let n = x
  n + n
}
'''


class Session(h.Session):
    def __init__(self, cmd, cwd, env, capable=True, wire=None):
        self.wire = wire
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0
        self.diagnostics = {}
        init = self.request('initialize', {'rootUri': None, 'capabilities': {
            'experimental': {'dawnSource': capable}}})
        self.provider = (init or {}).get('capabilities', {}).get('semanticTokensProvider')
        self.notify('initialized', {})

    def send(self, obj):
        if self.wire:
            self.wire.write(json.dumps({'send': obj}, ensure_ascii=False) + '\n')
            self.wire.flush()
        super().send(obj)

    def request_msg(self, method, params):
        self.next_id += 1
        mine = self.next_id
        self.send({'jsonrpc': '2.0', 'id': mine, 'method': method, 'params': params})
        while True:
            msg = h.read_msg(self.p.stdout)
            if self.wire:
                self.wire.write(json.dumps({'recv': msg}, ensure_ascii=False) + '\n')
                self.wire.flush()
            if msg is None:
                raise RuntimeError('server exited: ' + self.p.stderr.read().decode())
            if msg.get('method') == 'textDocument/publishDiagnostics':
                self.diagnostics[msg['params']['uri']] = msg['params']['diagnostics']
            if msg.get('id') == mine and 'method' not in msg:
                return msg


def position(text, needle, skip=0):
    return h.utf16_position(text, text.index(needle) + skip)


def params(uri, text, needle, skip=0):
    return {'textDocument': {'uri': uri}, 'position': position(text, needle, skip)}


def opened(s, uri, text, version=1):
    s.notify('textDocument/didOpen', {'textDocument': {
        'uri': uri, 'languageId': 'dawn', 'version': version, 'text': text}})


def changed(s, uri, text, version=2):
    s.notify('textDocument/didChange', {'textDocument': {'uri': uri, 'version': version},
                                       'contentChanges': [{'text': text}]})


def full(s, uri, text):
    result = s.request('textDocument/semanticTokens/full', {'textDocument': {'uri': uri}})
    return h.decode(text, (result or {}).get('data', []), s.provider['legend'])


def at_token(tokens, text, needle, skip=0):
    p = position(text, needle, skip)
    return next((kind for kind, (line, col, _) in tokens
                 if (line, col) == (p['line'], p['character'])), None)


def contract(cmd, work, mode, check, wire=None, capable=True):
    env = dict(os.environ)
    env.pop('DAWN_STD', None)
    if mode == 'disk':
        env['DAWN_STD'] = str(work / 'std')
    else:
        # A launcher normally exports its own std. An explicit absent directory
        # selects the embedded library without depending on the launcher's cwd.
        env['DAWN_STD'] = str(work / 'absent-std')
    s = Session(cmd, str(work), env, capable, wire)
    uri = (work / 'user.dawn').as_uri()
    try:
        opened(s, uri, USER)
        ts = full(s, uri, USER)
        check('user-diagnostics', s.diagnostics.get(uri) == [], s.diagnostics.get(uri))
        for needle, skip, kind, mods in [
            ('exp as', 0, 'function', 'defaultLibrary'),
            ('host_exp}', 0, 'function', 'defaultLibrary'),
            ('math.exp', 5, 'function', 'defaultLibrary'),
            ('f32}', 0, 'function', 'defaultLibrary'),
            ('BF16,', 0, 'type', 'defaultLibrary'),
            ('F32,', 0, 'type', 'defaultLibrary'),
            ('Dtype[F32]', 6, 'type', 'defaultLibrary'),
            ('= F32', 2, 'variable', 'readonly+defaultLibrary')]:
            owner = 'value-identity' if needle == '= F32' else 'import-tokens'
            name = {'exp as': 'exp', 'math.exp': 'exp', 'host_exp}': 'host_exp',
                    'f32}': 'f32', 'BF16,': 'BF16'}.get(needle, 'F32')
            check(owner, at_token(ts, USER, needle, skip) == (name, kind, mods),
                  (needle, at_token(ts, USER, needle, skip)))
        rng = {'start': {'line': 0, 'character': 0}, 'end': {'line': 5, 'character': 0}}
        data = s.request('textDocument/semanticTokens/range', {'textDocument': {'uri': uri}, 'range': rng})
        check('full-range', h.decode(USER, data['data'], s.provider['legend']) == [t for t in ts if t[1][0] < 5], data)
        hover = s.request('textDocument/hover', params(uri, USER, 'exp as'))
        check('import-hover', 'Exponential.' in json.dumps(hover), hover)
        dual = s.request('textDocument/hover', params(uri, USER, 'F32,'))
        check('dual-hover', 'opaque type F32' in json.dumps(dual) and 'const F32' in json.dumps(dual), dual)
        builtin = s.request('textDocument/definition', params(uri, USER, 'len([1])'))
        check('builtin-no-source', builtin == [], builtin)
        for needle in ('exp as', 'F32,', '= F32'):
            locs = s.request('textDocument/definition', params(uri, USER, needle, 2 if needle == '= F32' else 0))
            check('value-definition' if needle == '= F32' else 'reading-location', len(locs or []) == 1, locs)
            if locs and needle != 'exp as':
                loc = locs[0]
                source = None if mode == 'disk' else s.request('dawn/source', {'uri': loc['uri']})
                if mode == 'embedded' and source is None:
                    check('source-content', False, loc['uri'])
                    continue
                text = (work / 'std/narrow.dawn').read_text() if mode == 'disk' else source['text']
                expected = 'pub const F32' if needle == '= F32' else 'pub opaque type F32'
                check('value-definition' if needle == '= F32' else 'reading-location', loc['range']['start'] == position(text, expected, len(expected)-3), loc)
        targets = [('exp as', 'math', 'pub fn exp', 7), ('f32}', 'narrow', 'pub fn f32', 7), ('start}', 'cursor', 'pub fn start', 7)]
        docs = {}
        for use, module, declaration, skip in targets:
            locs = s.request('textDocument/definition', params(uri, USER, use))
            if not locs:
                check('reading-chain', False, (module, locs))
                continue
            loc = locs[0]
            target_uri = loc['uri']
            if mode == 'embedded':
                result = s.request_msg('dawn/source', {'uri': target_uri})
                check('source-content', 'result' in result, result)
                if 'result' not in result:
                    continue
                text = result['result']['text']
                check('source-content', result['result']['uri'] == target_uri and text == (ROOT / f'std/{module}.dawn').read_text(), module)
            else:
                text = (work / f'std/{module}.dawn').read_text()
                check('disk-location', target_uri == (work / f'std/{module}.dawn').as_uri(), target_uri)
            check('reading-chain', loc['range']['start'] == position(text, declaration, skip), loc)
            unopened = full(s, target_uri, text)
            check('unopened', unopened == [], module)
            opened(s, target_uri, text)
            ft = full(s, target_uri, text)
            check('disk-entry' if mode == 'disk' else 'reading-chain', len(ft) > 100, (module, len(ft)))
            check('library-diagnostics', s.diagnostics.get(target_uri) == [], (module, s.diagnostics.get(target_uri)))
            hp = s.request('textDocument/hover', params(target_uri, text, declaration, skip))
            ds = s.request('textDocument/definition', params(target_uri, text, declaration, skip))
            check('disk-entry' if mode == 'disk' else 'reading-chain', hp is not None and ds == [loc], (module, hp, ds))
            docs[module] = (target_uri, text)
        if 'math' in docs:
            u, text = docs['math']
            for use, skip, declaration, off in [('var x_work = x', 13, 'pub fn exp(x', 11), ('fd_hi(x_work)', 0, 'fn fd_hi', 3)]:
                loc = s.request('textDocument/definition', params(u, text, use, skip))
                check('reading-chain', bool(loc) and loc[0]['uri'] == u and loc[0]['range']['start'] == position(text, declaration, off), (use, loc))
        if 'math' in docs:
            u, text = docs['math']
            cross = s.request('textDocument/definition', params(u, text, 'float.is_nan(x)', 6))
            check('cross-std', len(cross or []) == 1 and cross[0]['uri'] != u, cross)
            if cross:
                target = cross[0]
                result = s.request('dawn/source', {'uri': target['uri']}) if mode == 'embedded' else None
                if mode == 'disk' or result:
                    source_text = result['text'] if result else (work / 'std/float.dawn').read_text()
                    check('cross-std', target['range']['start'] == position(source_text, 'pub fn is_nan', 7), target)
                    opened(s, target['uri'], source_text)
                    check('cross-std', bool(full(s, target['uri'], source_text)) and s.diagnostics.get(target['uri']) == [], target['uri'])
                    check('cross-std', s.request('textDocument/definition', params(target['uri'], source_text, 'pub fn is_nan', 7)) == cross, target)
        if 'narrow' in docs:
            u, text = docs['narrow']
            loc = s.request('textDocument/definition', params(u, text, 'pub fn f32(x: Float) -> F32 = round_f32', 30))
            check('reading-chain', bool(loc) and loc[0]['range']['start'] == position(text, 'pub fn round_f32', 7), loc)
        # References compare declaration identities across modules; the type and
        # witness share an import span but have different use positions.
        rt = s.request('textDocument/references', {**params(uri, USER, 'F32,'), 'context': {'includeDeclaration': True}})
        rv = s.request('textDocument/references', {**params(uri, USER, '= F32', 2), 'context': {'includeDeclaration': True}})
        check('reference-identities', bool(rt) and bool(rv) and rt != rv, (rt, rv))
        highlights = s.request('textDocument/documentHighlight', params(uri, USER, '= F32', 2))
        check('reference-identities', len(highlights or []) == 2, highlights)
        rename = s.request_msg('textDocument/rename', {**params(uri, USER, 'math.exp', 5), 'newName': 'other_exp'})
        check('external-rename', 'error' in rename, rename)
        alias = s.request_msg('textDocument/rename', {**params(uri, USER, 'host_exp}'), 'newName': 'local_exp'})
        check('alias-rename', set(alias.get('result', {}).get('changes', {})) == {uri} and len(alias.get('result', {}).get('changes', {}).get(uri, [])) == 2, alias)
        local = s.request('textDocument/documentHighlight', params(uri, USER, 'n + n'))
        check('local-names', len(local or []) == 3 and [x['kind'] for x in local] == [3, 2, 2], local)
        if mode == 'disk' and 'cursor' in docs:
            u, text = docs['cursor']
            shifted = '# 中文🎈\n' + text.replace('pub fn start(s: String) -> Cursor = cursor_start(s)',
                'pub fn start(s: String) -> Cursor = {\n  let _ = "中文🎈" ++ s\n  cursor_start(s)\n}')
            changed(s, u, shifted)
            ft = full(s, u, shifted)
            loc = s.request('textDocument/definition', params(u, shifted, 'pub fn start', 7))
            check('utf16-source', at_token(ft, shifted, '"中文🎈" ++ s', len('"中文🎈" ++ ')) == ('s', 'parameter', 'defaultLibrary'), ft[:5])
            check('disk-edit', bool(ft) and bool(loc) and loc[0]['range']['start'] == position(shifted, 'pub fn start', 7), loc)
            # Two spellings of the same canonical file must share the overlay.
            link = work / 'linked_cursor.dawn'
            link.symlink_to(work / 'std/cursor.dawn')
            opened(s, link.as_uri(), shifted)
            check('file-identities', bool(full(s, link.as_uri(), shifted)) and s.diagnostics.get(link.as_uri()) == [], s.diagnostics.get(link.as_uri()))
            s.notify('textDocument/didClose', {'textDocument': {'uri': link.as_uri()}})
            s.notify('textDocument/didClose', {'textDocument': {'uri': u}})
            opened(s, u, text)
            check('disk-reopen', bool(full(s, u, text)), u)
        # A copied source and a source-looking project path have user privileges.
        fake = work / 'impostor/src/std/cursor.dawn'
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text((ROOT / 'std/cursor.dawn').read_text())
        opened(s, fake.as_uri(), fake.read_text())
        full(s, fake.as_uri(), fake.read_text())
        check('source-provenance', any('cursor_start' in x['message'] for x in s.diagnostics.get(fake.as_uri(), [])), s.diagnostics.get(fake.as_uri()))
        forged = 'dawn-stdlib:wrong/std/cursor.dawn'
        opened(s, forged, fake.read_text())
        check('source-provenance', full(s, forged, fake.read_text()) == [], forged)
        check('source-content', 'error' in s.request_msg('dawn/source', {'uri': forged}), forged)
        if mode == 'embedded' and 'cursor' in docs:
            u, text = docs['cursor']
            changed(s, u, '# tampered\n' + text)
            check('immutable-source', full(s, u, '# tampered\n' + text) == [], u)
            opened(s, u, text)
            check('immutable-source', bool(full(s, u, text)), u)
    finally:
        s.close()


def capability_contract(cmd, work, check):
    env = dict(os.environ, DAWN_STD=str(work / 'absent-std'))
    s = Session(cmd, str(work), env, capable=False)
    uri = (work / 'unsupported.dawn').as_uri()
    try:
        opened(s, uri, USER)
        check('capability-independent-tokens', at_token(full(s, uri, USER), USER, 'exp as') == ('exp', 'function', 'defaultLibrary'), None)
        check('capability-no-location', s.request('textDocument/definition', params(uri, USER, 'exp as')) == [], None)
        check('capability-independent-hover', 'Exponential.' in json.dumps(s.request('textDocument/hover', params(uri, USER, 'exp as'))), None)
    finally:
        s.close()


def identity_contract(cmd, work, check):
    project = work / 'project'
    src = project / 'src'
    src.mkdir(parents=True, exist_ok=True)
    (project / 'dawn.toml').write_text('schema = 1\nname = "identity_probe"\n')
    for module in ('a', 'b'):
        (src / (module + '.dawn')).write_text('pub fn echo(x: Int) -> Int = x\n')
    text = 'use a.{echo as left}\nuse b.{echo as right}\nfn combine(x: Int) -> Int = left(x) + right(x)\n'
    path = src / 'main.dawn'
    path.write_text(text)
    uri = path.as_uri()
    env = dict(os.environ, DAWN_STD=str(work / 'std'))
    s = Session(cmd, str(work), env)
    try:
        opened(s, uri, text)
        full(s, uri, text)
        query = params(uri, text, 'left(x)')
        refs = s.request('textDocument/references', {**query, 'context': {'includeDeclaration': True}})
        check('file-reference-identity', len(refs or []) == 4 and sum(r['uri'] == (src / 'a.dawn').as_uri() for r in refs) == 1
              and all(r['uri'] != (src / 'b.dawn').as_uri() for r in refs), refs)
        highlights = s.request('textDocument/documentHighlight', query)
        check('file-reference-identity', len(highlights or []) == 3, highlights)
        renamed = s.request_msg('textDocument/rename', {**query, 'newName': 'local_echo'})
        check('file-rename-identity', len(renamed.get('result', {}).get('changes', {}).get(uri, [])) == 2
              and set(renamed.get('result', {}).get('changes', {})) == {uri}, renamed)
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', nargs=argparse.REMAINDER)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--mutants', action='store_true')
    args = parser.parse_args()
    cmd = args.server or [str(ROOT / 'bin/dawn'), 'lsp']
    failures = []
    assertions = [0]
    def check(owner, condition, detail):
        assertions[0] += 1
        if not condition:
            failures.append(owner)
            print('FAIL', owner, repr(detail)[:1200], flush=True)
    with tempfile.TemporaryDirectory(prefix='lsp-std-documents.') as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / 'std', work / 'std')
        (work / 'user.dawn').write_text(USER)
        for mode in ('embedded', 'disk'):
            wire = None
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
                wire = (args.out / f'{mode}-wire.jsonl').open('w')
            try:
                contract(cmd, work, mode, check, wire)
            finally:
                if wire:
                    wire.close()
            print('CHECK', mode, flush=True)
        capability_contract(cmd, work, check)
        identity_contract(cmd, work, check)
    if failures:
        print('FAILED OWNERS', sorted(set(failures)))
        return 1
    print('PASS std source document matrix:', assertions[0], 'assertions', flush=True)
    if args.mutants:
        return mutants()
    return 0


MUTANTS = [
    ('std-no-bundled-resolutions', 'import-tokens'),
    ('std-values-prefer-types', 'value-identity'),
    ('std-no-content-registration', 'source-content'),
    ('std-planned-entry', 'disk-entry'),
    ('std-forged-source', 'source-provenance'),
    ('std-wrong-snapshot', 'source-content'),
    ('std-builtin-in-buffer', 'builtin-no-source'),
    ('std-reference-without-source', 'file-reference-identity'),
    ('std-library-as-file', 'cross-std'),
]


def mutants():
    with tempfile.TemporaryDirectory(prefix='lsp-std-document-mutants.') as tmp:
        work = Path(tmp)
        for name, owner in MUTANTS:
            tree = work / name
            shutil.copytree(ROOT / 'selfhost', tree / 'selfhost')
            for package in ('packages', 'compiler-plan'):
                (tree / package).symlink_to(ROOT / package, target_is_directory=True)
            subprocess.run([sys.executable, str(ROOT / 'scripts/lsp-semantic-tokens/mutate.py'), name, str(tree)], check=True)
            jar = tree / 'compiler.jar'
            build = subprocess.run([str(ROOT / 'bin/dawn'), 'build', str(tree / 'selfhost'), '-o', str(jar)],
                                   capture_output=True, text=True)
            if build.returncode:
                print(build.stdout + build.stderr)
                raise RuntimeError(name + ': build failure is not a negative control')
            run = subprocess.run([sys.executable, '-B', __file__, '--server', 'java', '-XX:-UsePerfData', '-Xmx2g', '-jar', str(jar), 'lsp'],
                                 capture_output=True, text=True)
            print(run.stdout, end='')
            if run.returncode != 1 or 'FAIL ' + owner + ' ' not in run.stdout:
                print(run.stderr)
                raise RuntimeError(name + ': owning assertion stayed green or session crashed')
            print('PASS compiling mutant', name, 'turns', owner, 'red', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

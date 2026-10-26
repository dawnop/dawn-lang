"""Numerically correct compiled mutants must fail the exact-origin oracle."""
from pathlib import Path
import re
import shutil
from builder_oracle import judge as judge_builder
from tree_oracle import judge as judge_tree
from run import HERE, ROOT
from scope_oracle import judge_staged, judge_unwind


def mutations(run):
    java = Path(shutil.which(str(run.args.java))).resolve()
    # Release compilers vendor ASM; development jars name it in Class-Path.
    # Both javac and java follow the compiler jar's actual dependency recipe.
    asm = run.args.compiler
    result = run.command('mutator-javac', [java.with_name('javac'), '-cp', asm,
        '-d', run.out, HERE/'ArtifactMutator.java'])
    assert result.returncode == 0, result.stderr
    # Each baseline is compiled, run and judged before making any mutant.
    for fixture, names in [('modes', ['route', 'trait', 'default', 'devirtualized']),
                           ('builder', ['pure', 'instance', 'parent', 'handler', 'query']),
                           ('staged', ['syntax']), ('unwind', ['chain'])]:
        source = HERE/(fixture+'.dawn')
        judges = {'builder': judge_builder, 'modes': lambda value, text: judge_tree(value, text, 'modes'),
                  'staged': judge_staged, 'unwind': judge_unwind}
        judge = lambda output: judges[fixture](output, source.read_text())
        run.execute('mutant-control-'+fixture, source, judge)
        expected = {'builder': '(3, 5)', 'modes': '(7, 4, 8, 4, 8)', 'staged': '7', 'unwind': '(7, None, 2, 3)'}[fixture]
        for mode in names:
            for backend in ['native', 'jvm']:
                label = 'mutant-'+fixture+'-'+mode+'-'+backend
                base = run.out/('mutant-control-'+fixture+'-'+backend)
                if backend == 'jvm':
                    target = run.out/(label+'.jar')
                    result = run.command(label+'-mutate', [java, '-cp', str(run.out)+':'+str(asm),
                        'ArtifactMutator', base.with_suffix('.jar'), target, mode, source])
                    assert result.returncode == 0, result.stderr
                    command = [java, '-Xverify:all', '-jar', target]
                else:
                    text = base.with_suffix('.c').read_text()
                    if mode == 'route':
                        match = re.search(r'\n(?:DAWN_PROV_CODE )?\w+ (dawn_modes__lambda_\w+)_observed\([^\n]+\) \{\n[^\n]+dawn_prov_enter_function\("modes\\tNf4:make\\t[^\n]+\\tlambda\\t', text)
                        assert match, 'missing independently selected factory lambda'
                        name = match[1]+'__clo'
                        old = '{(void*)'+name+', (void*)'+name+'_observed}'
                        new = '{(void*)'+name+', (void*)'+name+'}'
                    elif mode in ['trait', 'default', 'devirtualized']:
                        part = {'trait': 'bridge', 'default': 'default', 'devirtualized': 'impl'}[mode]
                        method = 'twice' if mode == 'default' else 'step'
                        match = re.search(r'\{\(void\*\)(dawn_modes__'+part+r'_\w+_3'+method+r'), \(void\*\)\1_observed\}', text)
                        assert match, (mode, 'canonical trait target')
                        name = match[1]
                        if mode == 'devirtualized':
                            old, new = '= '+name+'_observed(', '= '+name+'('
                        else:
                            old = '{(void*)'+name+', (void*)'+name+'_observed}'
                            new = '{(void*)'+name+', (void*)'+name+'}'
                    elif mode == 'syntax':
                        for role in ['literal', 'operator', 'var', 'for', 'if']:
                            assert r'\t'+role+r'\t' in text, role
                            text = text.replace(r'\t'+role+r'\t', r'\tunknown\t')
                        old = new = 'dawn_prov_sites'
                    elif mode == 'chain':
                        content = source.read_text(); main = content.index('fn main()')
                        lo = content.index('Counter { n = 1 }).bump()', main)-main
                        entries = re.findall(r'\{([0-9]+), "(unwind\\tNf4:main\\t'+str(lo)+r'\\t[^"\n]+)"\}', text)
                        entries = [entry for entry in entries if entry[1].endswith(r'\tcall\t')]
                        assert len(entries) == 2, ('chain Site constants', entries)
                        entries.sort(key=lambda entry: int(entry[1].split(r'\t')[3]))
                        (first_id, first_text), (second_id, second_text) = entries
                        text = text.replace(second_id, first_id)
                        old, new = second_text, first_text
                    elif mode == 'query':
                        content = source.read_text(); main = content.index('fn main()')
                        lo = content.index('query(n) origin source', main)-main
                        pattern = r'(\n[^\n]+_observed\([^\n]+\) \{\n[^\n]+dawn_prov_enter_function\("builder\\tNf4:main\\t'+str(lo)+r'\\t[^\n]+\\thandler\\t[^\n]+\n)(.*?)(\n}\n)'
                        match = re.search(pattern, text, re.S)
                        assert match and 'dawn_prov_note(' in match[2], 'query handler selection'
                        changed = match[0].replace('dawn_prov_note(', 'test_skip_note(')
                        text = '#include "dawn_rt.h"\nstatic void test_skip_note(int64_t s, dawn_str *o) { (void)s; (void)o; }\n'+text
                        old, new = match[0], changed
                    elif mode == 'pure':
                        old, new = '= dawn_builder__pure_observed(', '= dawn_builder__pure('
                    elif mode == 'instance':
                        old, new = '(long long)r->id, (long long)r->parent,', '(long long)r->site, (long long)r->parent,'
                    elif mode == 'parent':
                        old, new = '(long long)r->id, (long long)r->parent,', '(long long)r->id, (long long)r->id,'
                    else:
                        pattern = r'"builder\\tNf6:helper\\t[^"\n]*\\tperform\\t[^"\n]*"'
                        strings = re.findall(pattern, text)
                        assert strings, 'missing perform Site constants'
                        old, new = strings[0], strings[0].replace('Nf6:helper', 'Nf4:main')
                    assert old in text, (label, 'mutation anchor missing')
                    text = text.replace(old, new)
                    target = run.out/(label+'.c'); target.write_text(text)
                    exe = run.out/(label+'.bin')
                    result = run.command(label+'-cc', [run.args.cc, '-std=c11', '-O2', '-fwrapv',
                        '-fexceptions', '-fno-strict-aliasing', '-ffp-contract=off', '-pthread',
                        '-I'+str(ROOT/'runtime/c'), target, ROOT/'runtime/c/dawn_rt.c', '-lm', '-o', exe])
                    assert result.returncode == 0, result.stderr
                    command = [exe]
                result = run.command(label+'-run', command)
                assert result.returncode == 0, (label, 'mutant failed to execute', result.stderr)
                assert result.stdout.splitlines()[0] == expected, (label, 'numeric result changed')
                try:
                    judge(result.stdout)
                except AssertionError as rejection:
                    (run.out/(label+'-oracle.txt')).write_text(str(rejection)+'\n')
                else:
                    raise AssertionError((label, 'exact-origin oracle accepted the mutant'))
                run.results.append({'case': label, 'backend': backend, 'passed': True,
                                    'numeric_control': True, 'origin_rejected': True})
                print('PASS', label, 'computes correctly then exact-origin oracle rejects', flush=True)

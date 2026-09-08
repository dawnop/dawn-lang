#!/usr/bin/env python3
"""Require plain Java scoring answers and consumer contexts to survive.

Only compiled mutations reaching owning assertions count, not oracle panics
or bootstrap failures. Each mutation runs against an isolated source copy.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    variants = [
        ('cx', 'assign-super', 'semantic_reads.JavaAssignable(superclass, subclass, answer)', 'semantic_reads.JavaAssignable("wrong", subclass, answer)'),
        ('cx', 'assign-sub', 'semantic_reads.JavaAssignable(superclass, subclass, answer)', 'semantic_reads.JavaAssignable(superclass, "wrong", answer)'),
        ('cx', 'assign-answer', 'semantic_reads.JavaAssignable(superclass, subclass, answer)', 'semantic_reads.JavaAssignable(superclass, subclass, not answer)'),
        ('cx', 'sam-key', 'semantic_reads.JavaSam(name, answer)', 'semantic_reads.JavaSam("wrong", answer)'),
        ('cx', 'sam-answer', 'semantic_reads.JavaSam(name, answer)', 'semantic_reads.JavaSam(name, None)'),
        ('cx', 'component-key', 'semantic_reads.JavaComponent(name, answer)', 'semantic_reads.JavaComponent("wrong", answer)'),
        ('cx', 'component-answer', 'semantic_reads.JavaComponent(name, answer)', 'semantic_reads.JavaComponent(name, None)'),
        ('semantic_reads', 'assign-direction', 'JavaAssignable(superclass, subclass, answer) -> JavaAssignable(superclass, subclass, answer)', 'JavaAssignable(superclass, subclass, answer) -> JavaAssignable(subclass, superclass, answer)'),
        ('semantic_reads', 'assign-answer', 'JavaAssignable(superclass, subclass, answer) -> JavaAssignable(superclass, subclass, answer)', 'JavaAssignable(superclass, subclass, answer) -> JavaAssignable(superclass, subclass, not answer)'),
        ('semantic_reads', 'sam-key', 'JavaSam(name, answer) -> JavaSam(name, answer)', 'JavaSam(name, answer) -> JavaSam("wrong", answer)'),
        ('semantic_reads', 'sam-answer', 'JavaSam(name, answer) -> JavaSam(name, answer)', 'JavaSam(name, answer) -> JavaSam(name, None)'),
        ('semantic_reads', 'component-key', 'JavaComponent(name, answer) -> JavaComponent(name, answer)', 'JavaComponent(name, answer) -> JavaComponent("wrong", answer)'),
        ('semantic_reads', 'component-answer', 'JavaComponent(name, answer) -> JavaComponent(name, answer)', 'JavaComponent(name, answer) -> JavaComponent(name, None)'),
        ('checker', 'packed-success', '(packed_cx, Some((0, sc)))', '(fixed_cx, Some((0, sc)))'),
        ('checker', 'packed-refusal', '(packed_cx, None)', '(fixed_cx, None)'),
        ('body_product', 'capture', 'semantic_reads.capture(before.function_reads, after.function_reads)?', 'before.function_reads'),
    ]
    for candidate, indent in [('c', '      '), ('m2', '    ')]:
        anchor = f'let (score_cx, score) = fit_score(cx1, {candidate}.param_cls, {candidate}.is_varargs, ats, arities)\n{indent}cx1 = score_cx'
        variants.append(('checker', candidate + '-candidate-context', anchor,
                         anchor.replace('cx1 = score_cx', 'cx1 = cx1')))
    for field, value in [('name', '"wrong"'), ('param_cls', '[]'), ('ret_cls', '"wrong"'),
                         ('is_static', 'not method.is_static'), ('is_varargs', 'not method.is_varargs'),
                         ('is_abstract', 'not method.is_abstract'), ('desc', '"wrong"'), ('decl_cls', '"wrong"')]:
        variants.append(('semantic_reads', 'sam-field-' + field,
                         'JavaSam(name, answer) -> JavaSam(name, answer)',
                         'JavaSam(name, answer) -> JavaSam(name, match answer {\n'
                         '            Some(method) -> Some(JMethod { ..method, ' + field + ': ' + value + ' })\n'
                         '            None -> None\n          })'))
    modules = ('cx', 'checker', 'semantic_reads', 'body_product')
    sources = {m: (ROOT / 'selfhost/src/check' / (m + '.dawn')).read_text() for m in modules}
    subjects = [(m, 'positive', s) for m, s in sources.items()]
    subjects += [(m, name, edit(sources[m], old, new)) for m, name, old, new in variants]
    scoped = [
        ('sam_param_ty', '(cx1, answer)', '(Cx { ..cx1, function_reads: cx.function_reads }, answer)'),
        ('sam_fn_ty', '(cx1, Some((ps, rt)))', '(Cx { ..cx1, function_reads: cx.function_reads }, Some((ps, rt)))'),
        ('sam_ret_compatible', '(cx1, answer)', '(Cx { ..cx1, function_reads: cx.function_reads }, answer)'),
        ('param_score', '(cx, answer)', '(Cx { ..cx, function_reads: initial.function_reads }, answer)'),
        ('score_with', '(cx1, Some(total))', '(Cx { ..cx1, function_reads: cx.function_reads }, Some(total))'),
        ('finalize_sams', '(cx1, atx2, convs, evs, bridges)', '(Cx { ..cx1, function_reads: cx.function_reads }, atx2, convs, evs, bridges)'),
    ]
    for function, old, new in scoped:
        source = sources['checker']
        match = re.search(r'(?m)^fn ' + re.escape(function) + r'\(', source)
        if match is None:
            raise RuntimeError('Missing consumer ' + function)
        following = re.search(r'(?m)^(?:pub )?fn |^test ', source[match.end():])
        end = len(source) if following is None else match.end() + following.start()
        body = edit(source[match.start():end], old, new)
        subjects.append(('checker', function + '-read-context', source[:match.start()] + body + source[end:]))
    with tempfile.TemporaryDirectory(prefix='dawn-java-oracle-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for module, name, source in subjects:
            target = root / 'selfhost/src/check' / (module + '.dawn')
            target.write_text(source)
            owner = root / 'selfhost/src/check' / ('checker.dawn' if module == 'cx' else module + '.dawn')
            status, output = run('test', owner)
            target.write_text(sources[module])
            if name == 'positive':
                if status:
                    raise RuntimeError('Positive ' + module + ' failed\n' + output)
            elif not status or not re.search(r'^FAIL\s+(?:check/\w+ :: )?(?:java oracle reads|java reads|semantic reads preserve Java scoring|body product)[^\n]*\n\s+assertion failed:', output, re.M):
                raise RuntimeError(name + ' did not reach its owning assertion\n' + output)
            print('OK: Java oracle ' + module + ' ' + name, flush=True)
    print(f'OK: Java oracle reads and {len(variants) + len(scoped)} compiling mutants, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()

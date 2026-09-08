#!/usr/bin/env python3
"""Reject lost local namespace observations with compiled, owning assertions.

Each subject is isolated; parser/bootstrap failures are never negative evidence.
The positive modules run first so an unrelated broken owner cannot pass a mutant.
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
        ('cx', 'constructor-name', 'semantic_reads.LocalConstructor(name, answer)', 'semantic_reads.LocalConstructor("wrong", answer)'),
        ('cx', 'constructor-answer', 'semantic_reads.LocalConstructor(name, answer)', 'semantic_reads.LocalConstructor(name, None)'),
        ('cx', 'constant-name', 'semantic_reads.LocalConstant(name, answer)', 'semantic_reads.LocalConstant("wrong", answer)'),
        ('cx', 'constant-answer', 'semantic_reads.LocalConstant(name, answer)', 'semantic_reads.LocalConstant(name, None)'),
        ('cx', 'visibility', 'semantic_reads.ConstantVisible(name, visible)', 'semantic_reads.ConstantVisible(name, not visible)'),
        ('cx', 'constructor-count', 'semantic_reads.ConstructorCount(adt, count)', 'semantic_reads.ConstructorCount(adt, count + 1)'),
        ('cx', 'constructor-arity', 'semantic_reads.ConstructorArity(adt, slot, arity)', 'semantic_reads.ConstructorArity(adt, slot, arity + 1)'),
        ('cx', 'field-slot', 'semantic_reads.ConstructorFields(adt, slot, answer)', 'semantic_reads.ConstructorFields(adt, slot + 1, answer)'),
        ('cx', 'header-key', 'semantic_reads.ConstructorHeaderAnswer(adt, answer)', 'semantic_reads.ConstructorHeaderAnswer(adt + 1, answer)'),
        ('cx', 'constructor-names', 'semantic_reads.ConstructorNames(adt, names)', 'semantic_reads.ConstructorNames(adt, [])'),
        ('cx', 'declared-constant', 'semantic_reads.DeclaredConstantName(name, present)', 'semantic_reads.DeclaredConstantName(name, not present)'),
        ('cx', 'candidate-pool', 'semantic_reads.LocalValueCandidates(include_constants, names)', 'semantic_reads.LocalValueCandidates(include_constants, [])'),
        ('semantic_reads', 'nominal-key', 'ConstructorNames(nominal(adt)?, names)', 'ConstructorNames(adt, names)'),
        ('semantic_reads', 'candidate-mode', 'LocalValueCandidates(include_constants, names) -> LocalValueCandidates(include_constants, names)', 'LocalValueCandidates(include_constants, names) -> LocalValueCandidates(not include_constants, names)'),
        ('semantic_reads', 'header-answer-id', 'id: nominal(answer.id)?, tparams: params', 'id: answer.id, tparams: params'),
        ('semantic_reads', 'header-binder', 'for ty in answer.tparams { params = params ++ [type_value(ty)?] }', 'for ty in answer.tparams { params = params ++ [ty] }'),
        ('semantic_reads', 'field-answer-id', 'CtorI { ..answer, adt: nominal(answer.adt)?, fields: fields }', 'CtorI { ..answer, adt: answer.adt, fields: fields }'),
        ('semantic_reads', 'field-type', 'FieldI { ..field, ty: type_value(field.ty)? }', 'FieldI { ..field, ty: field.ty }'),
        ('semantic_reads', 'field-name', 'FieldI { ..field, ty: type_value(field.ty)? }', 'FieldI { ..field, name: "wrong", ty: type_value(field.ty)? }'),
        ('semantic_reads', 'field-slot', 'ConstructorFields(nominal(adt)?, slot, CtorI', 'ConstructorFields(nominal(adt)?, slot + 1, CtorI'),
        ('body_product', 'capture', 'semantic_reads.capture(before.function_reads, after.function_reads)?', 'before.function_reads'),
    ]
    modules = ('cx', 'checker', 'semantic_reads', 'body_product')
    sources = {module: (ROOT / 'selfhost/src/check' / (module + '.dawn')).read_text() for module in modules}
    subjects = [(module, 'positive', source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    owning = re.compile(r'^FAIL\s+(?:check/\w+ :: )?(?:local |constructor |pre-resolved constructors|export reads|java namespace reads|semantic reads|body product)[^\n]*\n\s+assertion failed:', re.M)
    with tempfile.TemporaryDirectory(prefix='dawn-local-values-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for module, name, source in subjects:
            target = root / 'selfhost/src/check' / (module + '.dawn')
            target.write_text(source)
            owner = target.with_name('checker.dawn') if module == 'cx' else target
            status, output = run('test', owner)
            target.write_text(sources[module])
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive ' + module + ' failed\n' + output)
            elif not status or not owning.search(output):
                raise RuntimeError(name + ' did not reach its owning assertion\n' + output)
            print('OK: local values ' + module + ' ' + name, flush=True)
    print(f'OK: local value reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()

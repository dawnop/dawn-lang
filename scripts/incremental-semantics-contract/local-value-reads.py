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
        ('exhaustive', 'constructor-header-log',
         'let fields = semantic_reads.observe(headers, semantic_reads.ConstructorFields(adt, ci, ctor))',
         'let fields = semantic_reads.observe(state.reads, semantic_reads.ConstructorFields(adt, ci, ctor))'),
        ('exhaustive', 'constructor-fields-log',
         '(ReadState { ..state, reads: fields }, (header, ctor))',
         '(ReadState { ..state, reads: headers }, (header, ctor))'),
        ('exhaustive', 'complete-count-answer',
         'semantic_reads.observe(state.reads, semantic_reads.ConstructorCount(adt, count))',
         'semantic_reads.observe(state.reads, semantic_reads.ConstructorCount(adt, count + 1))'),
        ('exhaustive', 'specialization-arity-answer',
         'semantic_reads.ConstructorArity(adt, ci, nfields)',
         'semantic_reads.ConstructorArity(adt, ci, nfields + 1)'),
        ('exhaustive', 'matrix-normalization-context',
         'simplify_row_read(matrix_state, q, types_)',
         'simplify_row_read(state, q, types_)'),
        ('exhaustive', 'query-normalization-context',
         'useful_go(query_state, normalized_matrix, normalized_q, types_, USEFUL_STEP_LIMIT)',
         'useful_go(matrix_state, normalized_matrix, normalized_q, types_, USEFUL_STEP_LIMIT)'),
        ('exhaustive', 'usefulness-result-context',
         'let (next, remaining, result) = useful_go(query_state, normalized_matrix, normalized_q, types_, USEFUL_STEP_LIMIT)\n  (next, result)',
         'let (next, remaining, result) = useful_go(query_state, normalized_matrix, normalized_q, types_, USEFUL_STEP_LIMIT)\n  (state, result)'),
        ('exhaustive', 'alternative-recursion-context',
         '        observed = next_state\n        left = next',
         '        observed = observed\n        left = next'),
        ('exhaustive', 'missing-list-recursion-context',
         '    observed = next\n    match answer {',
         '    observed = observed\n    match answer {'),
        ('checker', 'let-usefulness-context',
         'let (useful_cx, useful_answer) = useful_check_read(cx1, [[to_spat(tp)]], [SWild], [it])\n        cx1 = useful_cx',
         'let (useful_cx, useful_answer) = useful_check_read(cx1, [[to_spat(tp)]], [SWild], [it])\n        cx1 = Cx { ..useful_cx, function_reads: cx1.function_reads }'),
        ('checker', 'for-usefulness-context',
         'let (useful_cx, useful_answer) = useful_check_read(cx1, [[to_spat(tp)]], [SWild], [loop_t])\n        cx1 = useful_cx',
         'let (useful_cx, useful_answer) = useful_check_read(cx1, [[to_spat(tp)]], [SWild], [loop_t])\n        cx1 = Cx { ..useful_cx, function_reads: cx1.function_reads }'),
        ('checker', 'match-usefulness-context',
         'let (useful_cx, useful_answer) = useful_check_read(cx1, rows, [SWild], tys)\n    cx1 = useful_cx',
         'let (useful_cx, useful_answer) = useful_check_read(cx1, rows, [SWild], tys)\n    cx1 = Cx { ..useful_cx, function_reads: cx1.function_reads }'),
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
        ('cx', 'effect-name', 'semantic_reads.LocalEffectName(name, answer)', 'semantic_reads.LocalEffectName("wrong", answer)'),
        ('cx', 'effect-answer', 'semantic_reads.LocalEffectName(name, answer)', 'semantic_reads.LocalEffectName(name, None)'),
        ('cx', 'effect-candidates', 'semantic_reads.EffectCandidates(names)', 'semantic_reads.EffectCandidates([])'),
        ('cx', 'effect-info-key', 'semantic_reads.DeclaredEffectInfo(id, answer)', 'semantic_reads.DeclaredEffectInfo(id + 1, answer)'),
        ('cx', 'effect-control', 'semantic_reads.DeclaredEffectInfo(id, answer)', 'semantic_reads.DeclaredEffectInfo(id, EffectI { ..answer, ctl: not answer.ctl })'),
        ('cx', 'effect-operations', 'semantic_reads.DeclaredEffectInfo(id, answer)', 'semantic_reads.DeclaredEffectInfo(id, EffectI { ..answer, ops: [] })'),
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
    modules = ('cx', 'checker', 'semantic_reads', 'body_product', 'exhaustive')
    sources = {module: (ROOT / 'selfhost/src/check' / (module + '.dawn')).read_text() for module in modules}
    subjects = [(module, 'positive', source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    scoped = [
        ('check_match', 'missing-count-context', 'cx1 = count_cx', 'cx1 = Cx { ..count_cx, function_reads: cx1.function_reads }'),
        ('check_match', 'missing-arity-context', 'cx1 = arity_cx', 'cx1 = Cx { ..arity_cx, function_reads: cx1.function_reads }'),
        ('check_match', 'missing-case-context', 'cx1 = case_cx', 'cx1 = Cx { ..case_cx, function_reads: cx1.function_reads }'),
        ('check_match', 'missing-name-context', 'cx1 = name_cx', 'cx1 = Cx { ..name_cx, function_reads: cx1.function_reads }'),
        ('check_match', 'missing-list-context', 'cx1 = list_cx', 'cx1 = Cx { ..list_cx, function_reads: cx1.function_reads }'),
        ('check_field_access_typed', 'record-fields-context', 'cx = fields_cx', 'cx = Cx { ..fields_cx, function_reads: cx.function_reads }'),
        ('check_handle', 'handler-name-context', 'cx1 = name_cx', 'cx1 = Cx { ..name_cx, function_reads: cx1.function_reads }'),
        ('check_handle', 'handler-pool-context', 'cx1 = pool_cx', 'cx1 = Cx { ..pool_cx, function_reads: cx1.function_reads }'),
        ('check_handle', 'handler-info-context', 'cx1 = info_cx', 'cx1 = Cx { ..info_cx, function_reads: cx1.function_reads }'),
        ('check_handle', 'handler-fields-context', 'cx1 = record_cx', 'cx1 = Cx { ..record_cx, function_reads: cx1.function_reads }'),
    ]
    for function, name, old, new in scoped:
        source = sources['checker']
        match = re.search(r'(?m)^(?:pub )?fn ' + re.escape(function) + r'\(', source)
        if match is None:
            raise RuntimeError('Missing consumer ' + function)
        following = re.search(r'(?m)^(?:pub )?fn |^test ', source[match.end():])
        end = len(source) if following is None else match.end() + following.start()
        body = edit(source[match.start():end], old, new)
        subjects.append(('checker', name, source[:match.start()] + body + source[end:]))
    owning = re.compile(r'^FAIL\s+(?:check/\w+ :: )?(?:local |constructor |exhaustive reads|handler reads|record field reads|pre-resolved constructors|export reads|java namespace reads|semantic reads|body product)[^\n]*\n\s+assertion failed:', re.M)
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
    print(f'OK: local value reads and {len(variants) + len(scoped)} compiling mutants, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()

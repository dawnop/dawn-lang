#!/usr/bin/env python3
"""Require canonical witness dependencies and candidate recomputation.

Each mutation must compile and fail its specific assertion owner. The private
subject preserves the workspace; this gate does not enable body caching.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    source = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    owner = 'witness revalidation recomputes candidate facts and refuses unknown queries'
    structural = 'witness reads preserve nominal recursion guards and substituted first gaps'
    variants = [
        ('accept-changed-answer', 'Some(semantic_reads.observed_equal(m, fact, observed.function_reads))',
         'Some(true)', owner),
        ('accept-missing-trait', 'if not map.has(initial.traits, moved) { return Some(false) }',
         'if not map.has(initial.traits, moved) { return Some(true) }', owner),
        ('ignore-candidate-owner', 'let initial = Cx { ..candidate, function_reads: Some([]) }',
         'let initial = Cx { ..candidate, owner_class: Some("m"), function_reads: Some([]) }',
         'unification revalidation checks candidate opacity and complete answers'),
        ('drop-recursion-guard-context', 'if set.has(seen, a.name) { return (cx, None) }',
         'if set.has(seen, a.name) { return (initial, None) }', structural),
        ('ignore-substituted-field', 'structural_gap_read(cx, tid, subst(f.ty, m, em), seen2)',
         'structural_gap_read(cx, tid, TyInt, seen2)', structural),
        ('drop-constructor-count-context', 'cx = count_cx', 'cx = cx', structural),
        ('invert-concreteness', 'semantic_reads.ConcreteType(t, answer)',
         'semantic_reads.ConcreteType(t, not answer)',
         'concreteness reads revalidate rigid parameter scope changes'),
        ('swap-compatibility-operands', 'semantic_reads.AssignableType(t, target, answer)',
         'semantic_reads.AssignableType(target, t, answer)',
         'assignability reads revalidate opaque visibility in either direction'),
        ('drop-inferred-types', 'after: InferenceBindings { types: map.entries(types), effects: map.entries(effects) }',
         'after: InferenceBindings { types: [], effects: map.entries(effects) }',
         'unification reads retain complete bindings on success and partial failure'),
        ('drop-effect-reduction-bindings', 'semantic_reads.ReducedEffect(e, map.entries(m), answer)',
         'semantic_reads.ReducedEffect(e, [], answer)',
         'effect reduction reads retain bindings and candidate associated rows'),
        ('drop-type-reduction-bindings', 'semantic_reads.ReducedTypeEffects(t, map.entries(m), answer)',
         'semantic_reads.ReducedTypeEffects(t, [], answer)',
         'effect reduction reads retain bindings and candidate associated rows'),
    ]
    subjects = [('positive', 'checker', source, None)] + [
        (name, 'checker', edit(source, old, new), test) for name, old, new, test in variants
    ]
    projection = (ROOT / 'selfhost/src/check/semantic_reads.dawn').read_text()
    projection_variants = []
    # Mutate production arms only. A retained numeric identity must not pass for
    # a projected identity, even when both domains use the same integer type.
    for constructor, old, new, owner_suffix in [
        ('ImplementationPresence', 'trait_value(trait_id)?', 'nominal(trait_id)?',
         'relocate implementation presence in separate domains'),
        ('ImplementationArity', 'parameters)', 'None)',
         'relocate implementation arity without mapping counts'),
        ('ImplementationSubgoals', 'moved)', 'goals)',
         'relocate ordered implementation subgoals'),
        ('TraitName', 'trait_value(id)?', 'nominal(id)?',
         'project trait names without changing their answers'),
        ('DictionarySymbol', 'binder_value(binder)?', 'nominal(binder)?',
         'project dictionary binders traits and locals independently'),
        ('DictionarySymbol', 'trait_value(trait_id)?', 'nominal(trait_id)?',
         'project dictionary binders traits and locals independently'),
        ('ReducedAssociatedType', 'type_value(input)?', 'input',
         'require both reduction input and answer mappings'),
        ('ReducedAssociatedType', 'type_value(answer)?', 'answer',
         'require both reduction input and answer mappings'),
        ('ConcreteType', 'type_value(input)?', 'input',
         'relocate concreteness inputs and retain verdicts'),
        ('AssignableType', 'type_value(target)?', 'target',
         'relocate both assignability operands'),
        ('ReducedEffect', 'effect_value(answer)?', 'answer',
         'relocate effect reduction rows and ordered bindings'),
        ('ReducedEffect', 'moved,', 'bindings,',
         'relocate effect reduction rows and ordered bindings'),
        ('ReducedTypeEffects', 'type_value(answer)?', 'answer',
         'relocate type effect reduction inputs bindings and answers'),
        ('ReducedTypeEffects', 'moved,', 'bindings,',
         'relocate type effect reduction inputs bindings and answers'),
    ]:
        # The constructor's output expression is on one production line, even
        # for arms that first assemble a list. Exclude fixtures by indentation.
        lines = [line for line in projection.splitlines()
                 if line.startswith('          ') and constructor + '(' in line and old in line]
        if len(lines) != 1:
            raise RuntimeError(f'Ambiguous projection anchor: {constructor} / {old}')
        anchor = lines[0]
        projection_variants.append((f'project-{constructor}-{len(projection_variants)}',
                                   anchor, new.join(anchor.rsplit(old, 1)),
                                   'semantic reads ' + owner_suffix))
    inference_owner = 'semantic reads project unification bindings in independent domains'
    projection_variants.extend([
        ('project-dictionary-local', 'Some(local_value(id)?)', 'Some(nominal(id)?)',
         'semantic reads project dictionary binders traits and locals independently'),
        ('project-inference-type-key', '[(binder(id)?, type_value(ty)?)]',
         '[(id, type_value(ty)?)]', inference_owner),
        ('project-inference-effect-key', '[(effect_binder(id)?, effect_value(row)?)]',
         '[(binder(id)?, effect_value(row)?)]', inference_owner),
        ('project-inference-type-answer', '[(binder(id)?, type_value(ty)?)]',
         '[(binder(id)?, ty)]', inference_owner),
        ('project-inference-effect-answer', '[(effect_binder(id)?, effect_value(row)?)]',
         '[(effect_binder(id)?, row)]', inference_owner),
        ('project-unification-after',
         'after: project_inference(q.after, type_value, effect_value, binder_value, effect_binder)?',
         'after: project_inference(q.before, type_value, effect_value, binder_value, effect_binder)?',
         inference_owner),
    ])
    subjects.append(('projection-positive', 'semantic_reads', projection, None))
    subjects.extend((name, 'semantic_reads', edit(projection, old, new), test)
                    for name, old, new, test in projection_variants)
    with tempfile.TemporaryDirectory(prefix='dawn-witness-revalidation-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, module, text, test in subjects:
            # Restore both modules so each negative has exactly one mutation.
            (root / 'selfhost/src/check/checker.dawn').write_text(source)
            (root / 'selfhost/src/check/semantic_reads.dawn').write_text(projection)
            target = root / f'selfhost/src/check/{module}.dawn'
            target.write_text(text)
            status, output = run('test', target)
            if test is None:
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            else:
                failure = re.compile(r'^FAIL\s+check/' + module + r' :: ' + re.escape(test) +
                                     r'\n\s+assertion failed:', re.M)
                if not status or not failure.search(output) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' did not compile and reach its owner\n' + output)
            print('OK: witness revalidation ' + name, flush=True)
    print(f'OK: {len(variants) + len(projection_variants)} compiling witness controls, '
          f'{time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()

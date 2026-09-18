#!/usr/bin/env python3
"""Exercise real scalar executor admission with compiling negative controls.

Unsupported bodies remain cold. These controls must reach the replay assertions;
parser, type-checker and JVM linkage failures do not establish their coverage.

Most controls mutate the replay module itself. Two mutate the scheduler and the
diagnostic sink it shares with the cold path, because the assembly order and the
diagnostic order are the shared scheduler's and cannot be broken from inside the
replay module: a control for either one has to reach where the order is made,
and the assertion it reddens is still a replay assertion.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


SUBJECT = 'selfhost/src/check/scalar_replay.dawn'
SCHEDULER = 'selfhost/src/check/checker.dawn'
CONTEXT = 'selfhost/src/check/cx.dawn'
SHAPE = 'selfhost/src/check/scalar_shape.dawn'


def main():
    started = time.monotonic()
    own = [
        ('disable-replay', '(Pass { ..state, prepared: Some(after) }, verdict)',
         '(Pass { ..state, prepared: Some(after) }, Unadmitted)'),
        # The shared memo. Its key is the recorded fact, its verdicts are
        # answered once for the whole candidate revision, and none of them
        # crosses into another revision. Each of those three is a separate
        # way for the memo to hand back a verdict the per-body loop it
        # replaced would not have produced.
        ('memo-stale-hit', 'query_runtime.Available(value) -> (asked.engine, value)',
         'query_runtime.Available(value) -> (asked.engine, None)'),
        ('memo-family-closed', 'AssignableType(_, _, _) -> true', 'AssignableType(_, _, _) -> false'),
        ('memo-builtin-disabled', 'BuiltinTypeAnswer(_, _) -> true', 'BuiltinTypeAnswer(_, _) -> false'),
        ('memo-builtin-misses-disabled', 'BuiltinTypeAnswer(_, _) -> true',
         'BuiltinTypeAnswer(_, answer) -> answer != None'),
        ('memo-builtin-hits-disabled', 'BuiltinTypeAnswer(_, _) -> true',
         'BuiltinTypeAnswer(_, answer) -> answer == None'),
        ('memo-wrong-key',
         'let opened = match query_runtime.begin(asked.engine, read) {\n'
         '        Some(engine) -> engine\n'
         '        None -> return (asked.engine, value)\n'
         '      }\n'
         '      match query_runtime.finish(opened, read, value) {',
         'let opened = match query_runtime.begin(asked.engine, AssignableType(TyUnit, TyUnit, false)) {\n'
         '        Some(engine) -> engine\n'
         '        None -> return (asked.engine, value)\n'
         '      }\n'
         '      match query_runtime.finish(opened, AssignableType(TyUnit, TyUnit, false), value) {'),
        ('memo-not-published',
         'match query_runtime.finish(opened, read, value) {\n        Some(engine) -> (engine, value)',
         'match query_runtime.finish(opened, read, value) {\n        Some(engine) -> (asked.engine, value)'),
        ('memo-not-carried', 'let carried = Prepared { ..prepared, memo: memo }', 'let carried = prepared'),
        ('memo-not-threaded', '(Pass { ..state, prepared: Some(after) }, verdict)', '(state, verdict)'),
        # The signature binders. A scoped query is the declaration's own, and
        # what the executor hands in is the context the scheduler entered the
        # declaration with, where nothing is bound yet. Asking it there, or
        # rebuilding the binders wrongly, refuses every generic body.
        ('binder-context-unbound', 'return (memo, checker.revalidate_read(scoped, read))',
         'return (memo, checker.revalidate_read(cx, read))'),
        ('binder-context-tparams', 'TyVar(name, _) -> { out = map.insert(out, name, parameter) }',
         'TyVar(_, _) -> ()'),
        ('generic-carried-binder',
         'for parameter in s.tparams { if parameter == t { return true } }',
         'for parameter in s.tparams { if parameter == t { return false } }'),
        ('generic-entry-bound-write',
         'BoundsKey(id) -> {\n        if not set.has(bound_ids, id) { return None }',
         'BoundsKey(id) -> {\n        if true { return None }'),
        ('source-owner', 'not snapshot_matches(old, old_source)', 'false'),
        ('observer-mode', 'Some(_) -> moved.function_reads', 'Some(_) -> None'),
        ('current-isolation', 'isolated: cx.frame.isolated', 'isolated: false'),
        ('current-test-mode', 'in_test: cx.in_test', 'in_test: false'),
        ('current-handler-cell', 'take_cell: cx.take_cell', 'take_cell: None'),
        ('current-constant-cutoff', 'const_cutoff: cx.const_cutoff', 'const_cutoff: None'),
        ('current-loop-jumps', 'loop_jumps: cx.loop_jumps', 'loop_jumps: set.empty()'),
        # The declaration's own bytes. This is the whole pairing of the two
        # bodies now: identical text parses to the same tree, so admission
        # asks for the bytes rather than walking two parsed bodies.
        ('changed-declaration-text',
         'if not source_projection.same_text(prepared.old_tokens, prepared.tokens,\n'
         '    prior.lo, prior.hi, d.lo, d.hi) { return None }',
         'if false { return None }'),
        ('alias-shadowed-binders', 'if map.has(cx.module_aliases, name) { return None }',
         'if false { return None }'),
        # The record-time half of admission. Its verdicts are what the replay
        # path stops recomputing, so each one needs its own control.
        ('recorded-binders', 'let names = scalar_shape.binders(prior.body, prior_sig.param_names)?',
         'let names: List[String] = []'),
        # Admission against the recorded header rather than the candidate
        # one. What this turns off is the refusal: a declaration whose own
        # bytes are unchanged can still have a different signature, because
        # the types it names are declared elsewhere.
        ('header-only-admission',
         'if not allocation.body_relocation(prior_sig, sig, no_evidence) { return None }',
         'if not allocation.body_relocation(prior_sig, prior_sig, no_evidence) { return None }'),
        # The product is retained under a declaration key, so the key the
        # candidate declaration is looked up with has to be the one this
        # revision's own enumeration gives it. Reading the recorded revision's
        # positions, or treating a syntax index as an identity, both reach for
        # a product under a key that is not this declaration's.
        ('candidate-key-revision',
         'for located in identity.located(scope, next.syntax) {',
         'for located in identity.located(scope, source_snapshot.syntax(settled.source)) {'),
        ('candidate-key-index',
         'candidates = map.insert(candidates, located.span.lo, (located.entry.key, located.entry.declaration))',
         'candidates = map.insert(candidates, located.entry.declaration, (located.entry.key, located.entry.declaration))'),
        ('candidate-key-ignored',
         'let (key, declaration) = map.get(prepared.candidates, d.lo)?',
         'let (key, declaration) = map.values(prepared.candidates)[0]'),
        # The cold remainder, one control per declaration category. Five of
        # the executor's six roles go straight to the cold executor and the
        # sixth goes there when admission refuses, so a category that stops
        # being counted is a category that left the remainder silently.
        ('cold-remainder-function',
         'Unadmitted -> cold.function(unadmitted(stepped), cx, d, sig)',
         'Unadmitted -> cold.function(stepped, cx, d, sig)'),
        ('cold-remainder-inferred-body',
         'inferred_body: (n, cx, d, sig) => cold.inferred_body(unadmitted(n), cx, d, sig),',
         'inferred_body: (n, cx, d, sig) => cold.inferred_body(n, cx, d, sig),'),
        ('cold-remainder-constant',
         'constant: (n, cx, d, ty, visible) => cold.constant(unadmitted(n), cx, d, ty, visible),',
         'constant: (n, cx, d, ty, visible) => cold.constant(n, cx, d, ty, visible),'),
        ('cold-remainder-method',
         'method: (n, cx, tr, subject, d, sig) => cold.method(unadmitted(n), cx, tr, subject, d, sig),',
         'method: (n, cx, tr, subject, d, sig) => cold.method(n, cx, tr, subject, d, sig),'),
        ('cold-remainder-default-body',
         'default_body: (n, cx, tr, d, sig, body) => cold.default_body(unadmitted(n), cx, tr, d, sig, body),',
         'default_body: (n, cx, tr, d, sig, body) => cold.default_body(n, cx, tr, d, sig, body),'),
        ('cold-remainder-test-body',
         'test_body: (n, cx, name, body) => cold.test_body(unadmitted(n), cx, name, body)',
         'test_body: (n, cx, name, body) => cold.test_body(n, cx, name, body)'),
        # The three columns. A claim the candidate revision withdrew is not a
        # class this producer never claimed, the reused column is not the
        # absence of the other two, and `checked` is their sum and not one of
        # them.
        ('count-rejected-as-unadmitted',
         'Rejected -> cold.function(rejected(stepped), cx, d, sig)',
         'Rejected -> cold.function(unadmitted(stepped), cx, d, sig)'),
        ('count-reused-column',
         'Some(after) -> (reused(stepped), after, product.tree)',
         'Some(after) -> (stepped, after, product.tree)'),
        ('count-checked-sum',
         'checked: outcome.counts.cold_unadmitted + outcome.counts.cold_rejected,',
         'checked: outcome.counts.cold_unadmitted,'),
        # Every declaration a revision adds or drops renumbers the
        # declarations after it, so the recorded slice has to be taken at the
        # index the recording gave this declaration and not at the index the
        # candidate revision gives it. Reading both slices at the candidate's
        # index pairs a body against whatever the recorded revision had at
        # that position, which is another declaration or nothing at all.
        ('recorded-declaration-index',
         '    saved.declaration, declaration, prior.lo, prior.hi, d.lo, d.hi) { return None }',
         '    declaration, declaration, prior.lo, prior.hi, d.lo, d.hi) { return None }'),
    ]
    # The assembly boundary is not this module's to break: the order the
    # declarations come out in and the order their diagnostics come out in are
    # both the shared scheduler's, which is the whole reason replay reuses it
    # rather than assembling a module of its own. A control for either one has
    # to mutate the scheduler, and the assertion it has to redden is here.
    shared = [
        ('assembly-order', SCHEDULER,
         '      tfuns = tfuns ++ [Some(tast_positions.function(owner.resolver, tf))]',
         '      tfuns = [Some(tast_positions.function(owner.resolver, tf))] ++ tfuns'),
        ('diagnostic-order', CONTEXT,
         '  Cx { ..cx, diags: cx.diags ++ [raised(cx, msg, lo, hi, "")] }',
         '  Cx { ..cx, diags: [raised(cx, msg, lo, hi, "")] ++ cx.diags }'),
        # Class membership is decided in the shape walk, and a binding with a
        # declared type is what puts a scoped query in an admitted body's log
        # at all. Refusing it there leaves the binder context unreachable.
        ('annotated-binder', SHAPE,
         'SLet(name, false, _, init, _, _) -> { out = binders(init, out)? ++ [name] }',
         'SLet(name, false, None, init, _, _) -> { out = binders(init, out)? ++ [name] }'),
    ]
    variants = [(name, SUBJECT, old, new) for name, old, new in own] + shared
    originals = {p: (ROOT / p).read_text() for p in {v[1] for v in variants}}
    with tempfile.TemporaryDirectory(prefix='dawn-scalar-replay-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, target, source in [('positive', SUBJECT, originals[SUBJECT])] + [
                (name, target, edit(originals[target], old, new))
                for name, target, old, new in variants]:
            for other, text in originals.items():
                (root / other).write_text(text)
            (root / target).write_text(source)
            status, output = run('test', root / SUBJECT)
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            elif not status or not re.search(
                    r'^FAIL\s+check/scalar_replay :: scalar replay [^\n]*\n\s+assertion failed:',
                    output, re.M) or re.search(r'^error:', output, re.M):
                raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: scalar replay ' + name, flush=True)
    print(f'OK: {len(variants)} compiling scalar replay controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()

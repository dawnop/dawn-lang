#!/usr/bin/env python3
"""Require diagnostic query facts and their returned contexts at real consumers.

Every negative must compile and reach an owning assertion. A parser, linker,
or unrelated test failure cannot establish that a lost observation was caught.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def check_cli():
    """Exercise actual CLI parsing and current-source partitions without a compiler."""
    cases = [
        (['--shards', '0'], 2, 'require --shards >= 1'),
        (['--shards', '2', '--shard', '-1'], 2, 'require --shards >= 1'),
        (['--shards', '2', '--shard', '2'], 2, 'require --shards >= 1'),
        (['--shards', '9999', '--shard', '9998'], 2, 'selected shard has no negative controls'),
        (['--shards', '9999', '--check-shards'], 2, 'every shard must contain negative controls'),
    ]
    for count in [1, 2, 3]:
        cases.append((['--shards', str(count), '--check-shards'], 0, 'unique controls; disjoint shard sizes'))
    for args, expected, message in cases:
        result = subprocess.run([sys.executable, __file__, *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != expected or message not in result.stdout:
            raise RuntimeError(f'CLI contract failed for {args}: {result.stdout}')
    print(f'OK: diagnostic shard CLI contracts ({len(cases)} cases)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shards', type=int, default=1)
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--check-shards', action='store_true',
                        help='validate mutation anchors and complete disjoint shard coverage without compiling')
    parser.add_argument('--self-test', action='store_true', help='check shard CLI contracts without compiling')
    args = parser.parse_args()
    if args.self_test:
        check_cli()
        return
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error('require --shards >= 1 and 0 <= --shard < --shards')
    started = time.monotonic()
    modules = ('cx', 'checker', 'semantic_reads', 'body_product')
    sources = {module: (ROOT / 'selfhost/src/check' / (module + '.dawn')).read_text() for module in modules}
    variants = [
        ('cx', 'signature-input', 'semantic_reads.RenderedSignature(sig, answer)', 'semantic_reads.RenderedSignature(Sig { ..sig, param_defaults: [] }, answer)'),
        ('cx', 'signature-answer', 'semantic_reads.RenderedSignature(sig, answer)', 'semantic_reads.RenderedSignature(sig, "wrong")'),
        ('semantic_reads', 'signature-projection', 'RenderedSignature(signature(sig)?, answer)', 'RenderedSignature(sig, answer)'),
        ('semantic_reads', 'signature-answer-projection', 'RenderedSignature(signature(sig)?, answer)', 'RenderedSignature(signature(sig)?, "wrong")'),
        ('cx', 'constructor-input', 'semantic_reads.RenderedConstructor(ctor, answer)', 'semantic_reads.RenderedConstructor(CtorI { ..ctor, fields: [] }, answer)'),
        ('cx', 'constructor-answer', 'semantic_reads.RenderedConstructor(ctor, answer)', 'semantic_reads.RenderedConstructor(ctor, "wrong")'),
        ('semantic_reads', 'constructor-owner-projection', 'RenderedConstructor(CtorI { ..ctor, adt: nominal(ctor.adt)?, fields: fields }, answer)', 'RenderedConstructor(CtorI { ..ctor, adt: ctor.adt, fields: fields }, answer)'),
        ('semantic_reads', 'constructor-field-projection', 'RenderedConstructor(CtorI { ..ctor, adt: nominal(ctor.adt)?, fields: fields }, answer)', 'RenderedConstructor(CtorI { ..ctor, adt: nominal(ctor.adt)?, fields: ctor.fields }, answer)'),
        ('semantic_reads', 'constructor-answer-projection', 'RenderedConstructor(CtorI { ..ctor, adt: nominal(ctor.adt)?, fields: fields }, answer)', 'RenderedConstructor(CtorI { ..ctor, adt: nominal(ctor.adt)?, fields: fields }, "wrong")'),
        ('cx', 'return-input', 'semantic_reads.RenderedFunctionReturn(ret, outer_eff, answer)', 'semantic_reads.RenderedFunctionReturn(TyError, outer_eff, answer)'),
        ('cx', 'return-effect', 'semantic_reads.RenderedFunctionReturn(ret, outer_eff, answer)', 'semantic_reads.RenderedFunctionReturn(ret, EPure, answer)'),
        ('cx', 'return-answer', 'semantic_reads.RenderedFunctionReturn(ret, outer_eff, answer)', 'semantic_reads.RenderedFunctionReturn(ret, outer_eff, "wrong")'),
        ('semantic_reads', 'return-type-projection', 'RenderedFunctionReturn(type_value(ret)?, effect_value(outer_eff)?, answer)', 'RenderedFunctionReturn(ret, effect_value(outer_eff)?, answer)'),
        ('semantic_reads', 'return-effect-projection', 'RenderedFunctionReturn(type_value(ret)?, effect_value(outer_eff)?, answer)', 'RenderedFunctionReturn(type_value(ret)?, outer_eff, answer)'),
        ('semantic_reads', 'return-answer-projection', 'RenderedFunctionReturn(type_value(ret)?, effect_value(outer_eff)?, answer)', 'RenderedFunctionReturn(type_value(ret)?, effect_value(outer_eff)?, "wrong")'),
        ('cx', 'query-input', 'semantic_reads.RenderedType(ty, answer)', 'semantic_reads.RenderedType(TyError, answer)'),
        ('cx', 'query-answer', 'semantic_reads.RenderedType(ty, answer)', 'semantic_reads.RenderedType(ty, "wrong")'),
        ('semantic_reads', 'type-projection', 'RenderedType(type_value(ty)?, answer)', 'RenderedType(ty, answer)'),
        ('semantic_reads', 'answer-projection', 'RenderedType(type_value(ty)?, answer)', 'RenderedType(type_value(ty)?, "wrong")'),
    ]
    subjects = [(module, 'positive', source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    consumers = [
        ('check_lambda', 'lambda-arity-context', 'cerr(render_cx, "this lambda', 'cerr(cx1, "this lambda'),
        ('check_lambda', 'with-closure-arity-context', 'cerr_h(render_cx, "the closure', 'cerr_h(cx1, "the closure'),
        ('check_match', 'match-scrutinee-context', 'cerr(render_cx, "match supports', 'cerr(cx1, "match supports'),
        ('check_match', 'match-guard-context', 'cerr(render_cx, "guard must', 'cerr(cx1, "guard must'),
        ('check_match', 'match-missing-render-context', 'cx1 = render_cx', 'cx1 = cx1'),
        ('declare_cells', 'handler-cell-initializer-context', 'cerr(actual_cx,', 'cerr(cx1,'),
        ('check_stmt', 'handler-cell-assignment-context', 'let (declared_cx, declared_text) = type_display_read(cx1, ct)', 'let (declared_cx, declared_text) = (cx1, ty_show(cx1.adts, ct))'),
        ('check_handle_arms', 'handler-arm-arity-context', 'cerr_h(render_cx,', 'cerr_h(cxa,'),
        ('check_handle_arms', 'handler-arm-return-context', 'cerr(declared_cx,', 'cerr(cxa,'),
        ('check_control_arm', 'control-arm-arity-context', 'cerr_h(render_cx,', 'cerr_h(cx1,'),
        ('check_control_arm', 'control-arm-return-context', 'cerr_h(answer_cx,', 'cerr_h(cx1,'),
        ('check_apply', 'apply-nonfunction-context', 'cerr(render_cx, "cannot call', 'cerr(cx1, "cannot call'),
        ('check_apply', 'apply-arity-context', 'cerr_h(render_cx, "this function takes', 'cerr_h(cx1, "this function takes'),
        ('check_apply', 'apply-argument-context', 'cerr_h(callable_cx, "argument type mismatch: expected " ++ expected_text ++\n              ", got " ++ actual_text, e_lo(a)', 'cerr_h(cx1, "argument type mismatch: expected " ++ expected_text ++\n              ", got " ++ actual_text, e_lo(a)'),
        ('check_apply', 'apply-pretyped-context', 'cerr_h(callable_cx, "argument type mismatch: expected " ++ expected_text ++\n              ", got " ++ actual_text, e_lo(args[i])', 'cerr_h(cx1, "argument type mismatch: expected " ++ expected_text ++\n              ", got " ++ actual_text, e_lo(args[i])'),
        ('check_ctor_call', 'record-spread-context', 'cerr(render_cx, "`..base`', 'cerr(cx1, "`..base`'),
        ('check_call', 'local-nonfunction-context', 'cerr(render_cx, "`" ++ callee ++ "` is not', 'cerr(cxa, "`" ++ callee ++ "` is not'),
        ('check_call', 'local-arity-context', 'cerr_h(render_cx, "`" ++ callee ++ "` takes', 'cerr_h(cxa, "`" ++ callee ++ "` takes'),
        ('check_call', 'local-argument-context', 'cerr_h(callable_cx,', 'cerr_h(cx1,'),
        ('check_stmt', 'discarded-value-context', 'cerr_h(render_cx, "this "', 'cerr_h(cx2, "this "'),
        ('check_stmt', 'assert-condition-context', 'cerr(render_cx, "`assert`', 'cerr(cx1, "`assert`'),
        ('check_stmt', 'while-condition-context', 'cerr(render_cx, "while condition', 'cerr(cx1, "while condition'),
        ('check_stmt', 'while-body-context', 'cerr_h(render_cx, "the loop body', 'cerr_h(cx1, "the loop body'),
        ('check_stmt', 'for-body-context', 'cerr(render_cx, "the loop body', 'cerr(cx1, "the loop body'),
        ('check_stmt', 'range-bound-context', 'cerr(to_cx, "range bounds', 'cerr(cx1, "range bounds'),
        ('check_stmt', 'annotated-let-context', 'cerr(actual_cx, "annotated type', 'cerr(cx1, "annotated type'),
        ('check_stmt', 'variable-assignment-context', 'type_display_read(cx1, sym.ty)', '(cx1, ty_show(cx1.adts, sym.ty))'),
        ('check_expr_at', 'index-missing-impl-context', 'let cx2 = cerr_h(render_cx,', 'let cx2 = cerr_h(cx1,'),
        ('check_expr_at', 'index-eager-description-context', 'resolve_witness(render_cx, INDEX_ID,', 'resolve_witness(cx1, INDEX_ID,'),
        ('check_expr_at', 'index-type-pair-context', 'cerr(actual_cx, "this index', 'cerr(cx3, "this index'),
        ('check_expr_at', 'return-type-pair-context', 'cerr(actual_cx, "`return` type mismatch', 'cerr(cx3, "`return` type mismatch'),
        ('check_expr_at', 'comptime-result-context', 'cerr_h(render_cx, "a comptime result', 'cerr_h(cx3, "a comptime result'),
        ('check_list_elem', 'list-spread-context', 'cerr_h(render_cx, "`..` spreads', 'cerr_h(cx1, "`..` spreads'),
        ('check_list_elem', 'list-condition-context', 'cerr(render_cx, "if condition', 'cerr(cx1, "if condition'),
        ('check_expr_at', 'if-condition-context', 'cerr(render_cx, "if condition', 'cerr(cx2, "if condition'),
        ('check_expr_at', 'if-unit-branch-context', 'cerr_h(render_cx, "an if without else', 'cerr_h(cx4, "an if without else'),
        ('check_pattern', 'tuple-pattern-context', 'cerr_h(render_cx, msg,', 'cerr_h(cx1, msg,'),
        ('check_pattern', 'list-pattern-context', 'cerr(render_cx, "list pattern', 'cerr(cx1, "list pattern'),
        ('check_or_bindings', 'or-pattern-type-context', 'cerr_h(first_cx,', 'cerr_h(cx1,'),
        ('check_lit_pattern', 'literal-pattern-context', 'cerr(scrutinee_cx,', 'cerr(cx1,'),
        ('check_ctor_pattern_at', 'constructor-scrutinee-context', 'cerr(render_cx,', 'cerr(cx1,'),
        ('check_propagate_typed', 'propagate-option-return-context', 'cerr(render_cx,\n            propagate_msg(render_cx, "an Option"', 'cerr(cx,\n            propagate_msg(render_cx, "an Option"'),
        ('check_propagate_typed', 'propagate-result-nominal-context', 'cerr(render_cx,\n                propagate_msg(render_cx, "a Result"', 'cerr(cx,\n                propagate_msg(render_cx, "a Result"'),
        ('check_propagate_typed', 'propagate-result-return-context', 'cerr(render_cx,\n              propagate_msg(render_cx, "a Result"', 'cerr(cx,\n              propagate_msg(render_cx, "a Result"'),
        ('check_propagate_typed', 'propagate-error-pair-context', 'cerr_h(return_cx, "`?` error types', 'cerr_h(cx, "`?` error types'),
        ('check_propagate_typed', 'propagate-nominal-operand-context', '      }\n      let (render_cx, text) = type_display_read(cx, ot)', '      }\n      let (_, text) = type_display_read(cx, ot)\n      let render_cx = cx'),
        ('check_propagate_typed', 'propagate-primitive-operand-context', '    _ -> {\n      let (render_cx, text) = type_display_read(cx, ot)', '    _ -> {\n      let (_, text) = type_display_read(cx, ot)\n      let render_cx = cx'),
        ('check_unwrap_typed', 'unwrap-nominal-context', 'cerr_h(render_cx, "`!` needs an Option, got " ++ text, lo, hi, hint)', 'cerr_h(cx, "`!` needs an Option, got " ++ text, lo, hi, hint)'),
        ('check_unwrap_typed', 'unwrap-primitive-context', 'cerr_h(render_cx, "`!` needs an Option, got " ++ text, lo, hi,\n', 'cerr_h(cx, "`!` needs an Option, got " ++ text, lo, hi,\n'),
        ('check_field_access_typed', 'non-record-field-context', 'cerr_o(render_cx,', 'cerr_o(cx,'),
        ('check_call', 'cast-target-context', 'cerr_h(render_cx, "`" ++ s.name ++ "` target', 'cerr_h(cx1, "`" ++ s.name ++ "` target'),
        ('finalize_sams', 'sam-shape-render-context', 'cerr_h(render_cx, "this function', 'cerr_h(info_cx, "this function'),
        ('finalize_sams', 'list-bridge-render-context', 'cerr_h(element_cx, "cannot bridge', 'cerr_h(info_cx, "cannot bridge'),
        ('check_java_call', 'java-argument-render-context', 'cx1 = render_cx', 'cx1 = cx1'),
        ('check_method_call', 'field-call-arity-context', 'cerr_h(field_cx, "`"', 'cerr_h(cx1, "`"'),
        ('check_method_call', 'field-call-argument-context', 'cerr_h(field_cx, "argument type mismatch', 'cerr_h(cx1, "argument type mismatch'),
        ('earg_row_subtract', 'row-repair-refusal-context', '(render_cx, em, false, Some(', '(cx, em, false, Some('),
        ('earg_row_subtract', 'row-repair-success-context', '(render_cx, map.insert(', '(cx, map.insert('),
        ('check_call', 'row-repair-consumer-context', 'cx1 = row_cx', 'cx1 = cx1'),
        ('resolve_witness', 'witness-bound-context', 'cerr_h(render_cx, requirer', 'cerr_h(cx, requirer'),
        ('resolve_witness', 'witness-hint-header-context', 'diagnostic_cx = header_cx', 'diagnostic_cx = diagnostic_cx'),
        ('resolve_witness', 'witness-refusal-context', 'cerr_h(diagnostic_cx, "no impl of', 'cerr_h(cx, "no impl of'),
        ('resolve_ord_witness', 'ordering-header-context', 'diagnostic_cx = header_cx', 'diagnostic_cx = diagnostic_cx'),
        ('resolve_ord_witness', 'ordering-template-context', 'diagnostic_cx = next', 'diagnostic_cx = diagnostic_cx'),
        ('check_ctor_value', 'constructor-value-context', 'cerr_h(hint_cx,', 'cerr_h(expected_cx,'),
        ('check_ctor_pattern_at', 'constructor-pattern-fallback-context', 'cx1 = hint_cx', 'cx1 = cx1'),
        ('check_ctor_pattern_at', 'constructor-pattern-arity-context', 'cerr_h(hint_cx,', 'cerr_h(cx1,'),
        ('check_ctor_call', 'constructor-call-fallback-context', 'cx1 = hint_cx', 'cx1 = cx1'),
        ('check_ctor_call', 'constructor-overflow-context', 'cerr_h(hint_cx, "`" ++ ci.name ++ "` takes "', 'cerr_h(cx1, "`" ++ ci.name ++ "` takes "'),
        ('resolve_ord_witness', 'ordering-bound-context', 'cerr_h(hint_cx, "values of type', 'cerr_h(message_cx, "values of type'),
        ('resolve_ord_witness', 'ordering-message-context', 'cerr_o(message_cx, "values of type', 'cerr_o(diagnostic_cx, "values of type'),
        ('check_call', 'named-arity-context', '      let cxb = cerr_h(hint_cx, arity_msg', '      let cxb = cerr_h(cx1, arity_msg'),
        ('check_call', 'named-missing-context', 'cerr_h(hint_cx, "missing argument(s)', 'cerr_h(cx1, "missing argument(s)'),
        ('check_call', 'named-fallback-context', '            cx1 = hint_cx\n            "signature: "', '            "signature: "'),
        ('check_call', 'named-suggestion-spurious-read', '          Some(hh) -> hh\n          None -> {', '          Some(hh) -> {\n            let (next, _) = signature_display_read(cx1, s)\n            cx1 = next\n            hh\n          }\n          None -> {'),
        ('check_call', 'signature-arity-context', 'let (hint_cx, hint_text) = signature_display_read(cxa, s)', 'let (_, hint_text) = signature_display_read(cxa, s)\n    let hint_cx = cxa'),
        ('check_call', 'argument-mismatch-context', 'cerr_h(actual_cx, "argument type mismatch', 'cerr_h(cx1, "argument type mismatch'),
        ('structural_gap_err', 'structural-gap-context', 'cerr_h(diagnostic_cx,', 'cerr_h(cx,'),
        ('assoc_witness_hint', 'associated-hint-context', '(next, "a bound', '(cx, "a bound'),
        ('assoc_witness_err', 'associated-message-context', 'assoc_witness_hint(message_cx, t)', 'assoc_witness_hint(cx, t)'),
        ('assoc_witness_err', 'associated-error-context', 'cerr_h(hint_cx,', 'cerr_h(message_cx,'),
        ('unify_branches', 'branch-context', 'cerr(right_cx,', 'cerr(cx,'),
        ('check_unary', 'not-context', 'cerr(render_cx, "`not`', 'cerr(cx, "`not`'),
        ('check_unary', 'negation-context', 'cerr(render_cx, "negation', 'cerr(cx, "negation'),
        ('check_unary', 'bitwise-not-context', 'cerr(render_cx, "`~`', 'cerr(cx, "`~`'),
        ('check_ctor_call', 'record-spelling-context', 'return (cerr_h(hint_cx,\n      "record `"', 'return (cerr_h(cx1,\n      "record `"'),
        ('check_ctor_call', 'bare-constructor-context', 'return (cerr_h(hint_cx, msg,', 'return (cerr_h(cx1, msg,'),
        ('check_ctor_call', 'constructor-field-context', 'cx1 = cerr_h(hint_cx, "field `"', 'cx1 = cerr_h(cx1, "field `"'),
        ('check_ctor_call', 'constructor-missing-context', 'cx1 = cerr_h(hint_cx, "missing field(s)', 'cx1 = cerr_h(cx1, "missing field(s)'),
        ('check_local_fn', 'local-return-hint-context', 'cerr_h(hint_cx,', 'cerr_h(cx1,'),
        ('check_const_init', 'constant-context', 'cerr(body_cx,', 'cerr(cx1,'),
        ('check_fn_body', 'function-context', 'cerr(body_cx,', 'cerr(cx1,'),
        ('check_trait_default', 'trait-default-context', 'cerr(body_cx,', 'cerr(cx1,'),
        ('check_param_default', 'parameter-default-context', 'cerr(default_cx,', 'cerr(cxd,'),
        ('check_test', 'test-context', 'cerr_h(body_cx,', 'cerr_h(cx1,'),
    ]
    for name, reporter, context, message in [
        ('arithmetic-left', 'cerr', 'render_cx', 'arithmetic expects numbers'),
        ('arithmetic-pair', 'cerr_o', 'right_cx', 'both sides must have the same type'),
        ('bitwise-left', 'cerr', 'render_cx', 'bitwise operators expect Int, left'),
        ('bitwise-right', 'cerr', 'render_cx', 'bitwise operators expect Int, right'),
        ('list-concat', 'cerr', 'right_cx', '`++` needs lists'),
        ('concat-pair', 'cerr_h', 'right_cx', '`++` concatenates Strings'),
        ('equality-pair', 'cerr', 'right_cx', '== requires both sides'),
        ('ordering-pair', 'cerr', 'right_cx', 'comparison requires both sides'),
        ('logical-left', 'cerr', 'render_cx', 'logical operators expect Bool, left'),
        ('logical-right', 'cerr', 'render_cx', 'logical operators expect Bool, right'),
    ]:
        consumers.append(('check_binary_typed', name + '-context',
                          reporter + '(' + context + ', "' + message,
                          reporter + '(cx, "' + message))
    for function, name, old, new in consumers:
        source = sources['checker']
        found = re.search(r'(?m)^(?:pub )?fn ' + re.escape(function) + r'\(', source)
        if found is None:
            raise RuntimeError('Missing consumer ' + function)
        following = re.search(r'(?m)^(?:pub )?fn |^test ', source[found.end():])
        end = len(source) if following is None else found.end() + following.start()
        body = edit(source[found.start():end], old, new)
        subjects.append(('checker', name, source[:found.start()] + body + source[end:]))
    negatives = [subject for subject in subjects if subject[1] != 'positive']
    identities = [(module, name) for module, name, _ in negatives]
    if len(set(identities)) != len(identities):
        raise RuntimeError('Duplicate negative control identity')
    if args.check_shards:
        partitions = [identities[index::args.shards] for index in range(args.shards)]
        if any(not partition for partition in partitions):
            parser.error('every shard must contain negative controls')
        covered = [identity for partition in partitions for identity in partition]
        if len(covered) != len(identities) or set(covered) != set(identities):
            raise RuntimeError('Shard coverage is incomplete or duplicated')
        print(f'OK: {len(identities)} unique controls; disjoint shard sizes ' +
              ', '.join(str(len(partition)) for partition in partitions))
        return
    selected = [subject for index, subject in enumerate(negatives) if index % args.shards == args.shard]
    if not selected:
        parser.error('the selected shard has no negative controls')
    # Every shard independently establishes the same positive baseline.
    subjects = [subject for subject in subjects if subject[1] == 'positive'] + selected
    owning = re.compile(r'^FAIL\s+(?:check/\w+ :: )?(?:diagnostic reads|semantic reads relocate signature|semantic reads relocate rendered|semantic reads relocate constructor|semantic reads relocate function return|a local function io hint|body product)[^\n]*\n\s+assertion failed:', re.M)
    with tempfile.TemporaryDirectory(prefix='dawn-diagnostic-reads-') as temp:
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
            print('OK: diagnostic reads ' + module + ' ' + name, flush=True)
    print(f'OK: diagnostic reads and {len(selected)} of {len(negatives)} compiling mutants, shard {args.shard}/{args.shards}, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()

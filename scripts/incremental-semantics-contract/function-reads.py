#!/usr/bin/env python3
"""Observe and revalidate real function queries without claiming full coverage.

Mutants alter the recording sites and captured facts, not the owning tests.
Compilation/link failures are never evidence that an observation was kept.
"""
import argparse
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def select_subjects(subjects, owners, suite):
    if suite == 'all':
        return subjects
    selected = [subject for subject in subjects if subject[1] != 'positive' and
                ((subject[1] in owners) == (suite == 'revalidation'))]
    modules = {subject[0] for subject in selected}
    return [subject for subject in subjects if
            (subject[1] == 'positive' and subject[0] in modules) or subject in selected]


def selection_selftest():
    subjects = [('checker', 'positive', 'base'), ('semantic_reads', 'positive', 'base'),
                ('checker', 'observe', 'one'), ('semantic_reads', 'record', 'two'),
                ('checker', 'query', 'three')]
    owners = {'query': 'owner'}
    observation = select_subjects(subjects, owners, 'observation')
    revalidation = select_subjects(subjects, owners, 'revalidation')
    assert select_subjects(subjects, owners, 'all') == subjects
    assert observation == subjects[:4]
    assert revalidation == [subjects[0], subjects[4]]
    names = [s[1] for s in observation + revalidation if s[1] != 'positive']
    assert sorted(names) == ['observe', 'query', 'record']
    assert len(names) == len(set(names))
    print('OK: function query suite partition and independent positive baselines')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('all', 'observation', 'revalidation'), default='all')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        selection_selftest()
        return
    started = time.monotonic()
    variants = [
        ("checker", "qualified-recording", "Some(_) -> Cx { ..cx, function_reads: semantic_reads.qualified(cx.function_reads, qualifier, name, answer) }", "Some(_) -> cx"),
        ("checker", "alias-recording", "Some(_) -> Cx { ..cx, function_reads: semantic_reads.module_alias(cx.function_reads, name, path) }", "Some(_) -> cx"),
        ("checker", "qualified-value", "let (start_cx, answer) = qual_fn_read(cx, target, fname)", "let (_, answer) = qual_fn_read(cx, target, fname)\n      let start_cx = cx"),
        ("checker", "qualified-expectation", "let (next, answer) = qual_fn_read(cx, target, name)\n      match answer", "let (_, answer) = qual_fn_read(cx, target, name)\n      let next = cx\n      match answer"),
        ("checker", "qualified-call-decision", "let (next, answer) = module_fn_read(cx, rname, name)", "let (_, answer) = module_fn_read(cx, rname, name)\n          let next = cx"),
        ("checker", "qualified-partial", "(next, answer != None)\n    }", "(cx, answer != None)\n    }"),
        ("checker", "qualified-argument", "let (next, answer) = accepts_partial_expected_read(cx1, a)\n          cx1 = next", "let (next, answer) = accepts_partial_expected_read(cx1, a)\n          cx1 = cx1"),
        ("checker", "qualified-call", "let (next, answer) = module_fn_read(cx1, al, name)\n  cx1 = next", "let (next, answer) = module_fn_read(cx1, al, name)\n  cx1 = cx1"),
        ("checker", "qualified-apply", "let (next, is_alias) = module_alias_receiver_read(cx, recv)\n          cx = next", "let (next, is_alias) = module_alias_receiver_read(cx, recv)\n          cx = cx"),
        ("checker", "alias-shadow", "if lookup(cx, alias_name) != None { return (cx, false) }", "if false { return (cx, false) }"),
        # `qualified-reference`, `qualified-identity`, `alias-path`,
        # `candidate-projection` and `read-reference` stood here and are gone
        # with the read-log projection they mutated (K7b). A function fact is
        # carried whole now; the recording controls above still decide it.
        ("checker", "qualifier-alternative", "let (next, answer) = lookup_fn_sig_read(cx, q)", "let next = cx\n  let answer = lookup_fn_sig(cx, q)"),
        ("checker", "expectation-value", "let (next, answer) = lookup_fn_sig_read(cx, name)", "let next = cx\n      let answer = lookup_fn_sig(cx, name)"),
        ("checker", "expectation-call", "let (next, answer) = lookup_fn_sig_read(cx, callee)", "let next = cx\n          let answer = lookup_fn_sig(cx, callee)"),
        ("checker", "expectation-entry", "Some(t) -> check_expr_at(next, e, Some(t))\n    None -> check_expr_at(next, e, expected)", "Some(t) -> check_expr_at(cx, e, Some(t))\n    None -> check_expr_at(cx, e, expected)"),
        ("checker", "argument-decision", "let (next, answer) = needs_expected_read(cx1, a)\n        cx1 = next", "let (next, answer) = needs_expected_read(cx1, a)\n        cx1 = cx1"),
        ("checker", "recording", "Some(_) -> Cx { ..cx, function_reads: semantic_reads.record(cx.function_reads, name, answer) }", "Some(_) -> cx"),
        ("checker", "function-value", "let (cx2, answer) = lookup_fn_sig_read(cx1, name)", "let cx2 = cx1\n      let answer = lookup_fn_sig(cx1, name)"),
        ("checker", "direct-call", "let (next, answer) = lookup_fn_sig_read(cx1, callee)", "let next = cx1\n      let answer = lookup_fn_sig(cx1, callee)"),
        ("checker", "field-ambiguity", "let (next, answer) = lookup_fn_sig_read(cx1, name)", "let next = cx1\n                let answer = lookup_fn_sig(cx1, name)"),
        ("semantic_reads", "negative-answer", "Some(entries) -> Some(entries ++ [FunctionAnswer(NamedFunctionRead { name: name, answer: answer })])", "Some(entries) -> if answer == None { Some(entries) } else { Some(entries ++ [FunctionAnswer(NamedFunctionRead { name: name, answer: answer })]) }"),
        ("checker", "candidate-qualifier", "let (next, pool) = fn_pool_read(cx)", "let next = cx\n  let pool = fn_pool(cx)"),
        ("checker", "candidate-value", "let (cx3, pool) = fn_pool_read(cx2)", "let cx3 = cx2\n          let pool = fn_pool(cx2)"),
        ("checker", "candidate-assignment", "let (next, pool) = fn_pool_read(cx1)", "let next = cx1\n          let pool = fn_pool(cx1)"),
        ("checker", "candidate-call", "let (cxb, pool) = fn_pool_read(cxa)", "let cxb = cxa\n      let pool = fn_pool(cxa)"),
        ("semantic_reads", "candidate-answer", "Some(entries) -> Some(entries ++ [FunctionCandidates(names)])", "Some(entries) -> Some(entries)"),
        ("semantic_reads", "candidate-order", "Some(entries) -> Some(entries ++ [FunctionCandidates(names)])", "Some(entries) -> Some(entries ++ [FunctionCandidates(list.reverse(names))])"),
        ("semantic_reads", "read-suffix", "Some(Some(list.drop(entries, len(prefix))))", "Some(Some(entries))"),
    ]
    revalidation_owner = 'function query revalidation preserves lookup precedence pools and isolation'
    qualified_owner = 'qualified function query revalidation tracks providers aliases and misses'
    source_owner = 'function query revalidation distinguishes source signature edits from body edits'
    query_controls = [
        ('query-dispatch', 'if function_answer != None { return function_answer }',
         'if false { return function_answer }', source_owner),
        ('query-accept-changed', 'Some(semantic_reads.observed_equal(fact, recomputed.function_reads))',
         'Some(true)', source_owner),
        ('query-log-isolation', 'let isolated = Cx { ..candidate, function_reads: Some([]) }',
         'let isolated = candidate', revalidation_owner),
        ('query-qualified-identity', 'module_fn_read(isolated, qualifier, query.name)',
         'lookup_fn_sig_read(isolated, query.name)', qualified_owner),
        ('query-alias-answer', 'let (answer_cx, _) = module_alias_read(isolated, qualifier)\n      answer_cx',
         'let (answer_cx, _) = module_alias_read(isolated, qualifier)\n      isolated', qualified_owner),
        ('query-pool-answer', 'let (answer_cx, _) = fn_pool_read(isolated)\n      answer_cx',
         'let (answer_cx, _) = fn_pool_read(isolated)\n      isolated', revalidation_owner),
    ]
    owners = {name: owner for name, _, _, owner in query_controls}
    variants.extend(('checker', name, old, new) for name, old, new, _ in query_controls)
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("checker", "semantic_reads")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    subjects = select_subjects(subjects, owners, args.suite)
    with tempfile.TemporaryDirectory(prefix="dawn-function-reads-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        query_seconds = 0.0
        for module, name, source in subjects:
            subject_started = time.monotonic()
            target = root / "selfhost/src/check" / (module + ".dawn")
            target.write_text(source)
            status, output = run("test", target)
            target.write_text(sources[module])
            if name == "positive":
                if status:
                    raise RuntimeError("Positive " + module + " failed\n" + output)
            elif name in owners:
                failure = r'^FAIL\s+check/checker :: ' + re.escape(owners[name]) + r'\n\s+assertion failed:'
                if not status or not re.search(failure, output, re.M) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' did not compile and reach its owning assertion\n' + output)
                query_seconds += time.monotonic() - subject_started
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:function reads|semantic reads) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: function reads " + module + " " + name, flush=True)
    query_count = sum(name in owners for _, name, _ in subjects)
    mutant_count = sum(name != 'positive' for _, name, _ in subjects)
    print(f'OK: {query_count} function revalidation controls, {query_seconds:.2f}s', flush=True)
    print(f"OK: function reads and {mutant_count} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()

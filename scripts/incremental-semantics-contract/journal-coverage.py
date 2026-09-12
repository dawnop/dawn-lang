#!/usr/bin/env python3
"""Audit table-write ownership independently of journal cardinality checks.

Every production Cx constructor is inspected, including modules outside check/.
Inline tests are excluded lexically, not by line-number ranges. This is a closed
owner inventory, not a type-checked call-graph proof: changes to exceptional
header/replay owners require review as well as the dynamic body oracle.
"""
import re
from collections import Counter

from cold import ROOT

FIELDS = {'syms', 'fns', 'alias_resolved', 'current_tparam_bounds'}
EXPECTED = Counter({
    **{('check/cx.dawn', 'cx_new', field): 1 for field in FIELDS},
    **{('check/body_product.dawn', 'assemble', field): 1 for field in FIELDS},
    **{('check/header_product.dawn', 'assemble', field): 1 for field in FIELDS - {'syms'}},
    ('check/cx.dawn', 'write_symbol', 'syms'): 1,
    ('check/cx.dawn', 'write_signature', 'fns'): 1,
    ('check/cx.dawn', 'write_alias', 'alias_resolved'): 1,
    ('check/cx.dawn', 'write_bounds', 'current_tparam_bounds'): 1,
    # Header registration/import owners run before the scheduled body boundary.
    ('check/passes.dawn', 'bind_raw', 'fns'): 1,
    ('check/passes.dawn', 'pass_register_traits', 'current_tparam_bounds'): 1,
    ('check/passes.dawn', 'pass_register_impls', 'current_tparam_bounds'): 1,
    ('check/passes.dawn', 'pass_fn_signatures', 'current_tparam_bounds'): 1,
    ('check/passes.dawn', 'inject_selective', 'alias_resolved'): 1,
})


def tokens(source):
    # Dawn strings and comments may contain braces or fake declarations.
    pattern = r'#[^\n]*|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[^\s]'
    return [m.group() for m in re.finditer(pattern, source)
            if not m.group().startswith(('#', '"'))]


def writes(source):
    ts = tokens(source)
    depth, owner, testing = 0, None, False
    result = Counter()
    for i, token in enumerate(ts):
        if depth == 0:
            if token == 'test':
                owner, testing = None, True
            elif token == 'fn':
                owner, testing = ts[i + 1], False
            elif token in ('type', 'use'):
                owner, testing = None, False
        if token == 'Cx' and ts[i + 1:i + 2] == ['{'] and owner and not testing:
            nested = 0
            for j in range(i + 1, len(ts)):
                if ts[j] == '{':
                    nested += 1
                elif ts[j] == '}':
                    nested -= 1
                    if nested == 0:
                        break
                elif nested == 1 and ts[j] in FIELDS and ts[j + 1:j + 2] == [':']:
                    result[(owner, ts[j])] += 1
            else:
                raise RuntimeError('Unterminated Cx constructor')
        if token == '{':
            depth += 1
        elif token == '}':
            depth -= 1
    return result


def inventory():
    result = Counter()
    for path in sorted((ROOT / 'selfhost/src').rglob('*.dawn')):
        for (owner, field), count in writes(path.read_text()).items():
            result[(str(path.relative_to(ROOT / 'selfhost/src')), owner, field)] += count
    return result


def main():
    actual = inventory()
    if actual != EXPECTED:
        raise RuntimeError(f'Cx table writer ownership changed: added={actual - EXPECTED}; removed={EXPECTED - actual}')
    fixture = '''
test "ignored" { let x = Cx { syms: ignored } }
fn actual(cx: Cx) -> Cx = Cx {
  ..cx, syms: replacement,
  frame: Frame { fns: not_a_cx_field }
}
fn exports() -> ModExports = ModExports { fns: unrelated }
# Cx { fns: comment }
fn text() -> String = "Cx { fns: string }"
'''
    if writes(fixture) != Counter({('actual', 'syms'): 1}):
        raise RuntimeError('Constructor scanner failed its lexical controls')
    for field in sorted(FIELDS):
        mutant = Counter(actual)
        for (owner, found), count in writes(f'fn bypass(cx: Cx) -> Cx = Cx {{ ..cx, {field}: cx.{field} }}').items():
            mutant[('check/checker.dawn', owner, found)] += count
        if mutant == EXPECTED:
            raise RuntimeError('Owner inventory accepted a bypass: ' + field)
    print(f'OK: {sum(actual.values())} owned Cx table writes; lexical controls and four bypass controls')


if __name__ == '__main__':
    main()

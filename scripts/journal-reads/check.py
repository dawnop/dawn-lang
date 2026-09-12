#!/usr/bin/env python3
"""Every Cx table read on the body-checking path is accounted for, by name.

## What this gate is for

A cached function body is readmitted on a later revision by replaying its
recorded product instead of checking it again. That is sound only when every
question the body asked of the module environment was written down while it
ran, so admission can ask the candidate revision the same question and compare
the answers. Two logs carry those answers: `check/semantic_reads` records the
queries (the read log, revalidated by `checker.revalidate_read`), and
`check/write_journal` records the keys a body mutated (the write journal,
consumed by `body_product.capture_journaled`).

A read that reaches a `Cx` table directly, without leaving a log entry, is
invisible to both. It is also invisible to every dynamic gate in the tree,
because a dynamic gate only sees the revisions it was handed: the body replays
correctly on the inputs the test wrote, and silently loses a diagnostic on the
input nobody thought of.

That is not hypothetical. `checker.declare` reports a binder that shadows an
imported module alias, through `cx.alias_shadow`, which reads
`cx.module_aliases` and records nothing. A candidate revision that adds
`use dep as y` in front of a body holding `let y = ...` therefore lost the
diagnostic on replay. It was found by walking the admitted AST class by hand,
which neither scales nor survives the next widening of admission (calls,
generics, methods). This is the mechanical version of that walk.

## What it does

It scans the Dawn sources textually, builds a conservative call graph from the
seven body-checking entry points in `check/checker`, collects every read of a
`Cx` field reachable from them, and holds the whole set to a checked-in ledger
(`ledger.txt`) that gives each read site one of four verdicts:

  logged     the read happens inside a function that records a
             `semantic_reads` fact, so admission has something to revalidate.
  product    the value read is body-local state that `body_product.assemble`
             reinstalls from the product itself, so it is not a question about
             the environment at all.
  write      the read is the old value inside that same field's own `Cx { .. }`
             update. Table writer ownership is a separate inventory, held by
             scripts/incremental-semantics-contract/journal-coverage.py.
  uncovered  neither. Every one of these is a real hole and carries a reason,
             plus either `compensated-by=<site>` naming the admission-side
             guard that re-asks the question, or `backlog` saying the hole is
             open and the class that may admit such a body is not open yet.

A read site that is not in the ledger fails the gate. A ledger row whose site
has disappeared fails it too, so the inventory cannot rot in either direction.
An `uncovered` row whose `compensated-by` target has stopped reading that
field fails: that is what reddens if the `module_aliases` guard in
`check/scalar_replay.candidate` is reverted.

Read scripts/journal-reads/README.md for what a textual scan can and cannot
see. The short version: it follows named calls, it does not follow values
through closures, and a `logged` verdict proves a fact was recorded in the
same function, not that the fact's answer determines the read's answer.
"""
import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LEDGER = HERE / 'ledger.txt'

# The scheduler's real body entry points (check/body_execution.record and
# check/checker.cold_body_executor call exactly these). Everything a cached
# body can read is reachable from one of them.
ROOTS = [
    ('check/checker', 'check_fn'),
    ('check/checker', 'check_fn_body'),
    ('check/checker', 'check_fn_inferred'),
    ('check/checker', 'check_fn_inferred_body'),
    ('check/checker', 'check_trait_default'),
    ('check/checker', 'check_test'),
    ('check/checker', 'check_const_init'),
]

VERDICTS = ('logged', 'product', 'write', 'uncovered')

TOKEN = re.compile(r'#[^\n]*|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[^\s]')
IDENT = re.compile(r'^[A-Za-z_]')


def tokens(source):
    """Dawn tokens with line numbers; comments and string literals dropped.

    Strings and comments are dropped rather than skipped by line range so that
    `# Cx { fns: ... }` and "cx.syms" cannot be mistaken for code, which is the
    same lexical rule journal-coverage.py uses on the writer side.
    """
    out = []
    line, pos = 1, 0
    for m in TOKEN.finditer(source):
        line += source.count('\n', pos, m.start())
        pos = m.start()
        text = m.group()
        if text.startswith('#') or text.startswith('"'):
            continue
        out.append((text, line))
    return out


class Fn:
    def __init__(self, module, name, line):
        self.module = module
        self.name = name
        self.line = line
        self.params = []
        self.ret = ''
        self.toks = []
        # Parallel to self.toks: the Cx constructor field this token sits in
        # the value of, or None. `Cx { ..cx, syms: map.insert(cx.syms, ..) }`
        # marks the inner `cx.syms` with 'syms'.
        self.wkey = []

    @property
    def site(self):
        return f'{self.module}.dawn::{self.name}'


def cx_fields(sources):
    body = re.search(r'pub type Cx = \{(.*?)\n\}', sources['check/cx'], re.S)
    if body is None:
        raise SystemExit('journal-reads: the Cx record declaration moved out of check/cx.dawn')
    found = re.findall(r'^\s{2}([a-z_][A-Za-z_0-9]*):', body.group(1), re.M)
    if len(found) < 10:
        raise SystemExit('journal-reads: the Cx field scan found almost nothing; the record shape moved')
    return set(found)


def read_sources(src):
    out = {}
    for path in sorted(Path(src).rglob('*.dawn')):
        out[str(path.relative_to(src))[:-len('.dawn')]] = path.read_text()
    return out


def signature(ts, i):
    """Parameter tokens and return text of the `fn` whose keyword is at i."""
    j = i + 2
    if j < len(ts) and ts[j][0] == '[':
        depth = 0
        while j < len(ts):
            if ts[j][0] == '[':
                depth += 1
            elif ts[j][0] == ']':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
    params = []
    if j < len(ts) and ts[j][0] == '(':
        depth, start = 0, j
        while j < len(ts):
            if ts[j][0] == '(':
                depth += 1
            elif ts[j][0] == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        params = ts[start + 1:j]
        j += 1
    ret = []
    if j + 1 < len(ts) and ts[j][0] == '-' and ts[j + 1][0] == '>':
        k, depth = j + 2, 0
        while k < len(ts):
            text = ts[k][0]
            if text in '([':
                depth += 1
            elif text in ')]':
                depth -= 1
            elif depth == 0 and text in ('=', '{'):
                break
            ret.append(text)
            k += 1
    return params, ''.join(ret)


def index(sources):
    """Every top-level `fn` in the tree, keyed by (module, name).

    Inline `test` blocks are excluded lexically: a test's reads are not
    production reads, and a test is free to reach into any table it likes.
    """
    fns = {}
    for module, text in sources.items():
        ts = tokens(text)
        depth = pdepth = 0
        cur = None
        cx_stack = []
        for i, (text_i, line) in enumerate(ts):
            if depth == 0 and pdepth == 0:
                if text_i == 'test':
                    cur = None
                elif text_i == 'fn' and i + 1 < len(ts) and IDENT.match(ts[i + 1][0]):
                    cur = Fn(module, ts[i + 1][0], line)
                    cur.params, cur.ret = signature(ts, i)
                    fns[(module, cur.name)] = cur
                    cx_stack = []
                elif text_i in ('type', 'use', 'alias', 'const', 'impl', 'trait'):
                    cur = None
            if cur is not None:
                cur.toks.append((text_i, line))
                cur.wkey.append(cx_stack[-1][1] if cx_stack else None)
            if text_i == '{':
                depth += 1
                if i >= 1 and ts[i - 1][0] == 'Cx':
                    cx_stack.append([depth, None])
            elif text_i == '}':
                if cx_stack and cx_stack[-1][0] == depth:
                    cx_stack.pop()
                depth -= 1
            elif text_i == '(':
                pdepth += 1
            elif text_i == ')':
                pdepth -= 1
            elif cx_stack and depth == cx_stack[-1][0] and IDENT.match(text_i) \
                    and i + 1 < len(ts) and ts[i + 1][0] == ':':
                cx_stack[-1][1] = text_i
    return fns


def call_targets(fns, by_name):
    """A conservative call graph: a call resolves to every definition of that
    name, narrowed to the same module when one exists and to the module the
    qualifier names when the call is qualified."""
    graph = {}
    for key, fn in fns.items():
        ts = [t for t, _ in fn.toks]
        out = set()
        for i, text in enumerate(ts):
            if not IDENT.match(text) or i + 1 >= len(ts) or ts[i + 1] != '(':
                continue
            candidates = by_name.get(text, set())
            if i >= 2 and ts[i - 1] == '.':
                # A qualified call names a module. When no scanned module
                # answers to that qualifier the callee is outside this tree
                # (std, a record field holding a closure), and nothing outside
                # it holds a Cx, so the edge is dropped rather than widened to
                # every function of that name: `map.values(..)` is not a call
                # to check/function_product.values.
                qualifier = ts[i - 2]
                out |= {c for c in candidates if c[0].split('/')[-1] == qualifier}
            elif (fn.module, text) in candidates:
                out.add((fn.module, text))
            else:
                out |= candidates
        graph[key] = out
    return graph


def reachable(fns, graph):
    seen = set()
    stack = [r for r in ROOTS if r in fns]
    if len(stack) != len(ROOTS):
        missing = [f'{m}.{n}' for m, n in ROOTS if (m, n) not in fns]
        raise SystemExit('journal-reads: body entry point(s) renamed or gone: ' + ', '.join(missing))
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        stack.extend(c for c in graph.get(key, ()) if c not in seen)
    return seen


def cx_names(fn, ret_cx, ret_tuple_cx, by_name):
    """Local names holding a Cx, over-approximated on purpose.

    A name enters the set from a `: Cx` parameter, from a `Cx { .. }` literal,
    from another Cx-valued name, or from a call whose declared return is `Cx`
    or `(Cx, ..)`. Over-approximating means a read may be attributed that is
    not a Cx read; under-approximating would mean missing one, which is the
    failure this gate exists to prevent.
    """
    names = set()
    params = [t for t, _ in fn.params]
    for i, text in enumerate(params):
        if text == 'Cx' and i >= 2 and params[i - 1] == ':' and IDENT.match(params[i - 2]):
            names.add(params[i - 2])
    ts = [t for t, _ in fn.toks]

    def target(i):
        if i + 1 < len(ts) and IDENT.match(ts[i]) and ts[i + 1] == '(':
            candidates = by_name.get(ts[i], set())
            if (fn.module, ts[i]) in candidates:
                return (fn.module, ts[i])
            if len(candidates) == 1:
                return next(iter(candidates))
        if i + 3 < len(ts) and ts[i + 1] == '.' and IDENT.match(ts[i + 2]) and ts[i + 3] == '(':
            candidates = [c for c in by_name.get(ts[i + 2], set())
                          if c[0].split('/')[-1] == ts[i]]
            if len(candidates) == 1:
                return candidates[0]
        return None

    for _ in range(4):
        grew = False
        for i, text in enumerate(ts):
            bound = None
            if text in ('let', 'var') and i + 2 < len(ts) and ts[i + 2] == '=':
                bound, rhs = ts[i + 1], i + 3
            elif text in ('let', 'var') and i + 1 < len(ts) and ts[i + 1] == '(':
                j, depth = i + 1, 0
                while j < len(ts):
                    if ts[j] == '(':
                        depth += 1
                    elif ts[j] == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                if j + 1 < len(ts) and ts[j + 1] == '=' and target(j + 2) in ret_tuple_cx:
                    if ts[i + 2] not in names:
                        names.add(ts[i + 2])
                        grew = True
                continue
            elif IDENT.match(text) and i + 1 < len(ts) and ts[i + 1] == '=' \
                    and (i == 0 or ts[i - 1] not in ('.', 'let', 'var', '=', '!', '<', '>')):
                bound, rhs = text, i + 2
            if bound is None or bound in names or rhs >= len(ts):
                continue
            if ts[rhs] == 'Cx' or ts[rhs] in names or target(rhs) in ret_cx:
                names.add(bound)
                grew = True
        if not grew:
            break
    return names


def scan(sources, only_reachable=True):
    """Every Cx field read, as {(site, field, kind): [lines]}."""
    fields = cx_fields(sources)
    fns = index(sources)
    by_name = collections.defaultdict(set)
    for key in fns:
        by_name[key[1]].add(key)
    ret_cx = {k for k, f in fns.items() if f.ret == 'Cx'}
    ret_tuple_cx = {k for k, f in fns.items() if f.ret.startswith('(Cx,')}
    graph = call_targets(fns, by_name)
    live = reachable(fns, graph) if only_reachable else set(fns)
    found = {}
    for key in sorted(live):
        fn = fns[key]
        names = cx_names(fn, ret_cx, ret_tuple_cx, by_name)
        ts = fn.toks
        for i in range(1, len(ts) - 1):
            if ts[i][0] != '.' or ts[i + 1][0] not in fields:
                continue
            base = ts[i - 1][0]
            # `headers.cx.diags`: ModuleHeaders/ModuleBodies/Recorded all hold
            # their Cx in a field spelled `cx`, so a selector reaches one too.
            selector = base == 'cx' and i >= 2 and ts[i - 2][0] == '.'
            if base not in names and not selector:
                continue
            field = ts[i + 1][0]
            write = fn.wkey[i + 1] == field
            found.setdefault((fn.site, field, 'write' if write else 'read'), []).append(ts[i][1])
    return fields, fns, found, graph, live


# ---------------------------------------------------------------- the ledger

class Row:
    __slots__ = ('site', 'field', 'verdict', 'detail', 'reason', 'line')

    def __init__(self, site, field, verdict, detail, reason, line):
        self.site, self.field, self.verdict = site, field, verdict
        self.detail, self.reason, self.line = detail, reason, line

    @property
    def key(self):
        return (self.site, self.field, 'write' if self.verdict == 'write' else 'read')


def parse_ledger(text, name='ledger.txt'):
    rows, problems = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) != 4:
            problems.append(f'{name}:{number}: want `site::field | verdict | detail | reason`, got {len(parts)} field(s)')
            continue
        target, verdict, detail, reason = parts
        if verdict not in VERDICTS:
            problems.append(f'{name}:{number}: unknown verdict {verdict!r}')
            continue
        if '::' not in target:
            problems.append(f'{name}:{number}: {target!r} is not `module.dawn::fn::field`')
            continue
        site, _, field = target.rpartition('::')
        if not reason:
            problems.append(f'{name}:{number}: {target} has no reason; every row says why in its own words')
            continue
        if verdict == 'uncovered' and not (detail == 'backlog' or detail.startswith('compensated-by=')):
            problems.append(f'{name}:{number}: {target} is uncovered, so detail must be `backlog` or `compensated-by=<site>`')
            continue
        if verdict == 'logged' and not detail:
            problems.append(f'{name}:{number}: {target} is logged but names no semantic_reads fact')
            continue
        rows.append(Row(site, field, verdict, detail, reason, number))
    return rows, problems


def fact_names(sources):
    body = re.search(r'pub type FunctionRead =(.*?)\n\npub fn observe', sources['check/semantic_reads'], re.S)
    if body is None:
        raise SystemExit('journal-reads: the FunctionRead declaration moved in check/semantic_reads.dawn')
    return set(re.findall(r'([A-Z][A-Za-z0-9_]*)\s*\(', body.group(1)))


def fact_spellings(sources, facts):
    """How a fact can appear at a call site: its own constructor, or the name
    of a check/semantic_reads helper that builds exactly that one variant
    (`semantic_reads.record` is how FunctionAnswer is written)."""
    spelling = {fact: {fact} for fact in facts}
    for (module, name), fn in index({'check/semantic_reads': sources['check/semantic_reads']}).items():
        built = {t for t, _ in fn.toks} & facts
        if len(built) == 1:
            spelling[next(iter(built))].add(name)
    return spelling


def audit(sources, ledger=None):
    fields, fns, found, graph, live = scan(sources)
    facts = fact_names(sources)
    spelling = fact_spellings(sources, facts)
    carried = product_fields(sources)
    rows, problems = parse_ledger(LEDGER.read_text() if ledger is None else ledger)
    by_key = {}
    for row in rows:
        if row.key in by_key:
            problems.append(f'ledger.txt:{row.line}: {row.site}::{row.field} is listed twice')
        by_key[row.key] = row

    for key in sorted(found):
        if key not in by_key:
            site, field, kind = key
            lines = ', '.join(str(n) for n in sorted(set(found[key])))
            problems.append(
                f'unledgered {kind} of cx.{field} in {site} (line {lines}). Give it a verdict in '
                f'scripts/journal-reads/ledger.txt, and if it is `uncovered`, say what re-asks the '
                f'question on admission.')
    for key, row in sorted(by_key.items()):
        if key not in found:
            problems.append(
                f'ledger.txt:{row.line}: {row.site}::{row.field} is no longer read there; drop the row')

    by_site = {}
    for key in live:
        by_site[fns[key].site] = key
    reaches = closure(graph)
    for row in rows:
        if row.key not in found:
            continue
        here = by_site[row.site]
        if row.verdict == 'logged':
            for claim in row.detail.split('+'):
                fact, _, where = claim.partition('@')
                target = by_site.get(where) if where else here
                if fact not in facts:
                    problems.append(
                        f'ledger.txt:{row.line}: {fact} is not a semantic_reads.FunctionRead variant')
                elif target is None:
                    problems.append(f'ledger.txt:{row.line}: {where} is not reachable checker code')
                elif not spelling[fact] & {t for t, _ in fns[target].toks}:
                    problems.append(
                        f'ledger.txt:{row.line}: {fns[target].site} no longer records {fact}, '
                        f'so cx.{row.field} is read there with nothing written down')
                elif target != here and here not in reaches[target] and target not in reaches[here]:
                    problems.append(
                        f'ledger.txt:{row.line}: {fns[target].site} and {row.site} no longer call '
                        f'one another, so {fact} cannot be the answer to this read')
        elif row.verdict == 'product':
            if row.detail not in carried:
                problems.append(
                    f'ledger.txt:{row.line}: body_product.assemble does not reinstall cx.{row.detail}, '
                    f'so cx.{row.field} is not body-local state')
        elif row.verdict == 'uncovered' and row.detail.startswith('compensated-by='):
            guard = row.detail[len('compensated-by='):]
            target = next((k for k, f in fns.items() if f.site == guard), None)
            if target is None:
                problems.append(f'ledger.txt:{row.line}: no function named {guard}')
            elif not reads_field(fns[target], row.field):
                problems.append(
                    f'ledger.txt:{row.line}: {guard} no longer reads cx.{row.field}, so the unlogged '
                    f'read in {row.site} is nobody\'s job again')
    return found, rows, problems


def closure(graph):
    """Transitive callees of every function. The graph is small (hundreds of
    nodes), so the naive fixed point is cheaper than being clever about it."""
    out = {key: set(callees) for key, callees in graph.items()}
    changed = True
    while changed:
        changed = False
        for key, callees in out.items():
            grown = set(callees)
            for callee in callees:
                grown |= out.get(callee, set())
            if grown != callees:
                out[key] = grown
                changed = True
    return out


def product_fields(sources):
    """The Cx fields body_product.assemble puts back from the product."""
    fns = index({'check/body_product': sources['check/body_product']})
    fn = fns[('check/body_product', 'assemble')]
    return {field for field in set(fn.wkey) if field}


def reads_field(fn, field):
    ts = fn.toks
    return any(ts[i][0] == '.' and ts[i + 1][0] == field for i in range(len(ts) - 1))


# ------------------------------------------------------------------ controls

CONTROL_TREE = {
    'check/cx': '''
use std/map
pub type Cx = {
  diags: List[Diag],
  next_id: Int,
  syms: Map[Int, Sym],
  fns: Map[String, Sig],
  adts: Adts,
  traits: Traits,
  consts: Map[String, Ty],
  frame: Frame,
  module_aliases: Map[String, String],
  effects: Map[String, Int],
  is_std_module: Bool,
  function_reads: Option[List[FunctionRead]]
}
pub fn cerr(cx: Cx, msg: String) -> Cx = Cx { ..cx, diags: cx.diags ++ [msg] }
pub fn alias_shadow(cx: Cx, name: String) -> Cx =
  match map.get(cx.module_aliases, name) { None -> cx, Some(_) -> cerr(cx, name) }
pub fn effect_slot_read(cx: Cx, slot: String) -> (Cx, Option[Int]) = {
  let answer = map.get(cx.effects, slot)
  (Cx { ..cx, function_reads: semantic_reads.observe(cx.function_reads, semantic_reads.EffectSlot(slot, answer)) }, answer)
}
test "ignored" { let x = cx.module_aliases }
# cx.module_aliases in a comment
pub fn quoted() -> String = "cx.module_aliases"
''',
    'check/semantic_reads': '''
pub type FunctionRead = EffectSlot(slot: String, answer: Option[Int]) |
StdModuleMode(is_std: Bool)

pub fn observe(reads: Int, fact: Int) -> Int = reads
''',
    'check/body_product': '''
pub fn assemble(current: Cx, product: Int) -> Option[Cx] =
  Some(Cx { ..current, diags: current.diags, syms: product, next_id: product })
''',
    'check/checker': '''
use check/cx
pub fn check_fn(cx: Cx) -> Cx = declare(cx, "x")
pub fn check_fn_body(cx: Cx) -> Cx = check_fn(cx)
pub fn check_fn_inferred(cx: Cx) -> Cx = check_fn(cx)
pub fn check_fn_inferred_body(cx: Cx) -> Cx = check_fn(cx)
pub fn check_trait_default(cx: Cx) -> Cx = check_fn(cx)
pub fn check_test(cx: Cx) -> Cx = check_fn(cx)
pub fn check_const_init(cx: Cx) -> Cx = check_fn(cx)
pub fn declare(cx: Cx, name: String) -> Cx = {
  let seed = cx.next_id
  let (cx1, answer) = cx.effect_slot_read(name)
  alias_shadow(cx1, name)
}
pub fn unreached(cx: Cx) -> Int = cx.next_id
''',
    'check/scalar_replay': '''
pub fn candidate(cx: Cx, name: String) -> Option[Int] = {
  if map.has(cx.module_aliases, name) { return None }
  Some(1)
}
''',
}

CONTROL_LEDGER = '''
check/cx.dawn::cerr::diags | write | | the old list inside its own append
check/cx.dawn::effect_slot_read::function_reads | write | | the old log inside its own append
check/cx.dawn::alias_shadow::module_aliases | uncovered | compensated-by=check/scalar_replay.dawn::candidate | the shadowing report leaves no fact
check/cx.dawn::effect_slot_read::effects | logged | EffectSlot | the lookup is the fact's answer
check/checker.dawn::declare::next_id | product | next_id | the allocator is body-local
'''


def self_test():
    """Negative controls: each must go red, and the clean tree must not."""
    failures = []

    def run(tree, ledger, label, want):
        _, _, problems = audit(tree, ledger)
        if not any(want in problem for problem in problems):
            failures.append(f'{label}: expected a problem matching {want!r}, got {problems or "nothing"}')
        return problems

    _, _, clean = audit(CONTROL_TREE, CONTROL_LEDGER)
    if clean:
        failures.append(f'positive control: the synthetic clean tree is not clean: {clean}')

    # 1. An unjournaled read that nobody has ledgered.
    injected = dict(CONTROL_TREE)
    injected['check/checker'] = CONTROL_TREE['check/checker'].replace(
        '  alias_shadow(cx1, name)\n',
        '  if map.has(cx1.effects, name) { return cx1 }\n  alias_shadow(cx1, name)\n')
    run(injected, CONTROL_LEDGER, 'injected unjournaled read', 'unledgered read of cx.effects')

    # 2. A ledger row with no reason at all.
    run(CONTROL_TREE, CONTROL_LEDGER.replace(
        '| the shadowing report leaves no fact', '|'),
        'reasonless exemption', 'has no reason')

    # 3. The module_aliases case itself: the admission-side guard is reverted.
    reverted = dict(CONTROL_TREE)
    reverted['check/scalar_replay'] = '''
pub fn candidate(cx: Cx, name: String) -> Option[Int] = Some(1)
'''
    run(reverted, CONTROL_LEDGER, 'reverted compensating guard', 'no longer reads cx.module_aliases')

    # 4. A `logged` row whose function stopped recording the fact.
    silent = dict(CONTROL_TREE)
    silent['check/cx'] = CONTROL_TREE['check/cx'].replace(
        'semantic_reads.observe(cx.function_reads, semantic_reads.EffectSlot(slot, answer))',
        'cx.function_reads')
    run(silent, CONTROL_LEDGER, 'silent read accessor', 'no longer records EffectSlot')

    # 5. A `product` row naming a field assemble does not reinstall.
    run(CONTROL_TREE, CONTROL_LEDGER.replace(
        '| product | next_id |', '| product | module_aliases |'),
        'product claim assemble does not back', 'does not reinstall cx.module_aliases')

    # 6. A ledger row for a read that is no longer there.
    run(CONTROL_TREE, CONTROL_LEDGER + 'check/cx.dawn::cerr::next_id | write | | stale\n',
        'stale ledger row', 'is no longer read there')

    # 7. Lexical controls: the test block, the comment and the string literal
    #    in the control tree all spell cx.module_aliases and none may count.
    _, _, found, _, _ = scan(CONTROL_TREE)
    sites = {site for site, _, _ in found}
    for absent in ('check/cx.dawn::quoted', 'check/checker.dawn::unreached'):
        if absent in sites:
            failures.append(f'lexical control: {absent} should contribute no read, got one')
    if ('check/cx.dawn::alias_shadow', 'module_aliases', 'read') not in found:
        failures.append('lexical control: the real alias_shadow read went missing')

    if failures:
        for line in failures:
            print('FAIL: ' + line, file=sys.stderr)
        return 1
    print(f'OK: {len(CONTROL_TREE)}-module control tree, 1 positive and 6 negative controls, '
          f'3 lexical controls')
    return 0


def record(sources):
    """Draft a ledger from the tree. Reasons are the author's to write."""
    _, fns, found, _, live = scan(sources)
    facts = fact_names(sources)
    by_site = {fns[k].site: fns[k] for k in live}
    carried = product_fields(sources)
    lines = []
    for (site, field, kind) in sorted(found):
        if kind == 'write':
            lines.append(f'{site}::{field} | write | | TODO')
            continue
        emitted = [t for t, _ in by_site[site].toks if t in facts]
        if emitted:
            lines.append(f'{site}::{field} | logged | {emitted[0]} | TODO')
        elif field in carried:
            lines.append(f'{site}::{field} | product | {field} | TODO')
        else:
            lines.append(f'{site}::{field} | uncovered | backlog | TODO')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--src', default=str(ROOT / 'selfhost/src'),
                        help='the Dawn source tree to scan (default: selfhost/src)')
    parser.add_argument('--self-test', action='store_true',
                        help='run the scanner against its own controls instead of the tree')
    parser.add_argument('--record', action='store_true',
                        help='print a draft ledger for the tree; reasons still have to be written')
    parser.add_argument('--uncovered', action='store_true',
                        help='print the uncovered reads and nothing else')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    sources = read_sources(args.src)
    if args.record:
        sys.stdout.write(record(sources))
        return 0

    found, rows, problems = audit(sources)
    if args.uncovered:
        for row in sorted((r for r in rows if r.verdict == 'uncovered'), key=lambda r: (r.field, r.site)):
            print(f'{row.site}::{row.field} | {row.detail} | {row.reason}')
    if problems:
        for line in problems:
            print('FAIL: ' + line, file=sys.stderr)
        return 1
    counts = collections.Counter(row.verdict for row in rows)
    sites = sum(len(v) for v in found.values())
    print(f'OK: {sites} Cx table read(s) at {len(found)} site(s) reachable from {len(ROOTS)} body entry '
          f'points; {counts["logged"]} logged, {counts["product"]} body-local, {counts["write"]} in their '
          f'own write, {counts["uncovered"]} uncovered and named')
    return 0


if __name__ == '__main__':
    sys.exit(main())

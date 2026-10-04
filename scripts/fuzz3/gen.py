#!/usr/bin/env python3
"""Typed random Dawn programs for the three-way differential (fuzz3).

    scripts/fuzz3/gen.py --seed 17 --cases 20            # a batch, on stdout
    scripts/fuzz3/gen.py --seed 17 --case 4              # one case alone
    scripts/fuzz3/gen.py --seed 17 --case 4 --comptime   # the folded variant

Why a generator at all. The bug survey of 2026-10-04 (110 defects) found that
the gates had caught one product bug in 90: every corpus here is written by
hand, so a shape nobody wrote down is a shape nobody checks, and the July
defects kept surfacing a month later the first time new code walked into
them. A generator is the only thing in the tree that produces programs nobody
wrote. It is typed rather than grammar-random because a program the checker
refuses tests the checker's refusal and nothing behind it; every program this
file emits is meant to type-check, so a refusal is a generator bug and the
harness reports it as such, apart from the compiler findings.

Why Python and not Dawn. The generator is test infrastructure that has to be
cheap to change while the language moves under it, it must not depend on the
compiler it is testing (a generator built by a broken compiler generates the
broken compiler's idea of a program), and it has to run against an old
release jar for the positive control, whose language is older than HEAD's. So
the subset below is also the subset the v0.75.0 release accepts.

What it emits. A batch is one file holding N independent cases, so a native
leg compiles one translation unit per batch instead of one per program (cc is
the bottleneck: native-selfhost-tests already spends 75% of its time there,
#239). Each case `cN` owns its types and helpers under the `cN_` prefix and a
pure `cN_case() -> String` whose answer is a trace of the values it saw. main
runs the cases from the index given as its first argument and prints a marker
line before each, so a case that panics is attributed and the harness restarts
the binary after it. Everything a case does is pure, which is what lets the
third executor exist: the comptime variant folds the same function into a
`const` and prints it, and the interpreter's answer has to match the two
backends'.

The subset is the one research-bug-rate-report 7.3 cut 1 lists: Int, Bool,
String; let and var; if and match; while with break and continue; functions,
local recursive functions and closures; List literals and `++`; records and
`{ ..r, f: e }`; ADTs with `derive Show, Ord`; Result and `?` (and Option's);
panic and Never in operand positions; division and modulo by zero. It leans
on purpose toward the shapes the old defects had in common: a Never-typed
operand (`break`, `continue`, `return`, a panicking call) in the middle of an
argument list, a list literal, a concatenation or an initializer; a block
argument that assigns a variable an earlier argument read; `?` inside the
right-hand side of an assignment that reads its own target.

Determinism: case i of batch seed S draws from random.Random("S:i") alone, so
`--case i` regenerates exactly the case the batch contained, and a failure is
reproduced from two integers.
"""

import argparse
import random
import sys

# Type spellings. Per-case nominal types are written R and S and renamed to
# the case's own names on output.
INT, BOOL, STR = "Int", "Bool", "String"
LINT, LSTR = "List[Int]", "List[String]"
REC, ADT = "R", "S"
OPT, RES = "Option[Int]", "Result[Int, String]"
FN = "fn(Int) -> Int"
TUP = "(Int, String)"
ALL = [INT, BOOL, STR, LINT, LSTR, REC, ADT, OPT, RES, FN, TUP]
SHOWABLE = [INT, BOOL, STR, LINT, LSTR, REC, ADT, OPT, RES, TUP]
EQABLE = SHOWABLE
# `<` on these: native scalars or derive Ord. Bool, and so a record with a
# Bool field, became orderable after v0.75.0, the positive control's compiler.
ORDERED = [INT, STR, ADT]

INT_EDGES = ["0", "1", "2", "7", "(-1)", "9223372036854775807",
             "(-9223372036854775807 - 1)", "63", "64", "(-64)", "1000003"]
STR_LITS = ['""', '"a"', '"xy"', '"a\\nb"', '"q\\"t"', '"back\\\\slash"', '"中文"',
            '"\\u{1F600}"', '"tab\\tz"', '"  sp "', '"#"']


class Var:
    def __init__(self, name, ty, mut):
        self.name, self.ty, self.mut = name, ty, mut


class Ctx:
    """What an expression may refer to and which jumps it may take."""

    def __init__(self, vars, ret, try_ty, in_loop, in_lambda, trace):
        self.vars = vars          # list[Var], innermost last
        self.ret = ret            # the enclosing function's return type, or None
        self.try_ty = try_ty      # OPT or RES when `?` is available
        self.in_loop = in_loop
        self.in_lambda = in_lambda
        self.trace = trace        # name of the trace var when reachable

    def child(self, **kw):
        c = Ctx(list(self.vars), self.ret, self.try_ty, self.in_loop, self.in_lambda, self.trace)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def of(self, ty, mut=None):
        return [v for v in self.vars if v.ty == ty and (mut is None or v.mut == mut)]


class CaseGen:
    def __init__(self, seed, index, no_never=False):
        self.rng = random.Random(f"{seed}:{index}")
        self.p = f"c{index}"
        self.n = 0
        self.helpers = []         # (name, [param types], ret type)
        self.no_never = no_never

    # ------------------------------------------------------------ utilities
    def fresh(self, base="v"):
        self.n += 1
        return f"{base}{self.n}"

    def chance(self, p):
        return self.rng.random() < p

    def pick(self, xs):
        return self.rng.choice(xs)

    def T(self, ty):
        return ty.replace("R", f"{self.P}R", 1) if ty == REC else \
            (f"{self.P}S" if ty == ADT else ty)

    @property
    def P(self):
        return self.p.upper()

    def stop(self):
        return f"{self.p}_stop"

    # ------------------------------------------------------------- never
    def never(self, ctx):
        """A Never-typed expression the context allows, or None."""
        if self.no_never:
            return None
        opts = []
        if ctx.in_loop and not ctx.in_lambda:
            opts += ["break", "continue", "continue"]
        if ctx.ret is not None and not ctx.in_lambda:
            opts.append("return")
        # a panic ends the case, so it is the rare one: most of what follows
        # a jump should still run
        if not opts or self.chance(0.12):
            if self.chance(0.5) and opts:
                opts = list(opts)
            else:
                opts = ["stop"]
        k = self.pick(opts)
        if k == "return":
            return f"return {self.expr(ctx.ret, ctx.child(), 1)}"
        if k == "stop":
            return f'{self.stop()}("{self.p} stop {self.fresh("s")}")'
        return k

    def cond(self, ctx, d):
        return self.expr(BOOL, ctx, max(0, d - 1))

    def maybe_never_wrap(self, ty, ctx, d, p=0.05):
        """`if c { <never> } else { e }`: a jump in an operand position."""
        if d > 0 and self.chance(p):
            nv = self.never(ctx)
            if nv:
                c = self.cond(ctx, 1)
                e = self.expr(ty, ctx, d - 1)
                if self.chance(0.5):
                    return f"(if ({c}) {{ {nv} }} else {{ {e} }})"
                return f"(if ({c}) {{ {e} }} else {{ {nv} }})"
        return None

    # -------------------------------------------------------------- leaves
    def leaf(self, ty, ctx):
        vs = ctx.of(ty)
        if vs and self.chance(0.7):
            return self.pick(vs).name
        r = self.rng
        if ty == INT:
            return self.int_lit()
        if ty == BOOL:
            return self.pick(["true", "false"])
        if ty == STR:
            return self.pick(STR_LITS)
        if ty == LINT:
            n = r.randint(0, 3)
            return "[" + ", ".join(self.int_lit() for _ in range(n)) + "]" if n else f"{self.p}_nil()"
        if ty == LSTR:
            n = r.randint(0, 2)
            return "[" + ", ".join(self.pick(STR_LITS) for _ in range(n)) + "]" if n else f"{self.p}_snil()"
        if ty == REC:
            return f"{self.P}R {{ a: {self.int_lit()}, b: {self.pick(STR_LITS)}, c: {self.pick(['true', 'false'])} }}"
        if ty == ADT:
            k = r.randint(0, 2)
            if k == 0:
                return f"{self.P}A"
            if k == 1:
                return f"{self.P}B({self.int_lit()})"
            return f"{self.P}C({self.pick(STR_LITS)}, {self.int_lit()})"
        if ty == OPT:
            return f"Some({self.int_lit()})" if self.chance(0.6) else f"{self.p}_none()"
        if ty == RES:
            return f"{self.p}_ok({self.int_lit()})" if self.chance(0.6) else f'{self.p}_err("e{r.randint(0, 9)}")'
        if ty == FN:
            return f"{self.p}_inc"
        if ty == TUP:
            return f"({self.int_lit()}, {self.pick(STR_LITS)})"
        raise ValueError(ty)

    def int_lit(self):
        if self.chance(0.2):
            return self.pick(INT_EDGES)
        n = self.rng.randint(-5, 30)
        return f"({n})" if n < 0 else str(n)

    # --------------------------------------------------------- expressions
    def expr(self, ty, ctx, d):
        if d <= 0:
            return self.leaf(ty, ctx)
        w = self.maybe_never_wrap(ty, ctx, d)
        if w:
            return w
        r = self.rng.random()
        if r < 0.18:
            return self.leaf(ty, ctx)
        if r < 0.26:
            return f"(if ({self.cond(ctx, d)}) {{ {self.expr(ty, ctx, d - 1)} }} else {{ {self.expr(ty, ctx, d - 1)} }})"
        if r < 0.33:
            return self.match_expr(ty, ctx, d)
        if r < 0.40:
            return self.block_expr(ty, ctx, d)
        if r < 0.47:
            call = self.call_helper(ty, ctx, d)
            if call:
                return call
        if r < 0.51 and ctx.try_ty and ty == INT:
            return self.try_expr(ctx, d)
        return self.typed(ty, ctx, d)

    def try_expr(self, ctx, d):
        if ctx.try_ty == RES:
            return f"{self.p}_chk({self.expr(INT, ctx, d - 1)})?"
        return f"get({self.expr(LINT, ctx, d - 1)}, {self.expr(INT, ctx, d - 1)})?"

    def typed(self, ty, ctx, d):
        e = lambda t, dd=d - 1: self.expr(t, ctx, dd)
        k = self.rng.random()
        if ty == INT:
            if k < 0.45:
                op = self.pick(["+", "-", "*", "+", "-", "*", "&", "|", "^", "<<", ">>", ">>>"])
                mv = [v for v in ctx.of(INT) if v.mut is True] if not ctx.in_lambda else []
                if mv and self.chance(0.1):   # the probe again, on an operator's operands
                    v = self.pick(mv)
                    return f"({v.name} {op} {self.mutating_block(INT, ctx, d, v)})"
                return f"({e(INT)} {op} {e(INT)})"
            if k < 0.6:
                op = self.pick(["/", "%"])
                rhs = e(INT) if self.chance(0.08) else f"(({e(INT)} & 7) + 1)"
                return f"({e(INT)} {op} {rhs})"
            if k < 0.66:
                return f"(-{e(INT)})" if self.chance(0.5) else f"(~{e(INT)})"
            if k < 0.74:
                return f"len({e(LINT)})"
            if k < 0.80:
                return f"str.len({e(STR)})"
            if k < 0.86:
                return f"{self.fn_value(ctx, d)}({e(INT)})"
            if k < 0.92:
                return f"unwrap_or(get({e(LINT)}, {e(INT)}), {e(INT)})"
            if k < 0.96:
                return f"list.fold({e(LINT)}, {e(INT)}, (acc: Int, x: Int) => {self.lam_body(INT, ctx, d, [('acc', INT), ('x', INT)])})"
            return self.local_fn_call(ctx, d)
        if ty == BOOL:
            if k < 0.35:
                t = self.pick(ORDERED)
                op = self.pick(["<", "<=", ">", ">="])
                return f"({e(t)} {op} {e(t)})"
            if k < 0.6:
                t = self.pick(EQABLE)
                return f"({e(t)} {self.pick(['==', '!='])} {e(t)})"
            if k < 0.8:
                return f"({e(BOOL)} {self.pick(['&&', '||'])} {e(BOOL)})"
            if k < 0.9:
                return f"(not {e(BOOL)})"
            return f"list.contains({e(LINT)}, {e(INT)})"
        if ty == STR:
            if k < 0.35:
                return f"({e(STR)} ++ {e(STR)})"
            if k < 0.6:
                t = self.pick(SHOWABLE)
                a, b = e(t), e(INT)
                if "\n" in a or "\n" in b:
                    # an interpolation cannot span lines; the same text by hand
                    return f'("<" ++ to_string({a}) ++ ":" ++ to_string({b}) ++ ">")'
                return f'"<${{{a}}}:${{{b}}}>"'
            if k < 0.8:
                return f"to_string({e(self.pick(SHOWABLE))})"
            return f"join({e(LSTR)}, {e(STR)})"
        if ty == LINT:
            if k < 0.35:
                return "[" + ", ".join(self.list_elem(INT, ctx, d) for _ in range(self.rng.randint(1, 3))) + "]"
            if k < 0.6:
                return f"({e(LINT)} ++ {e(LINT)})"
            if k < 0.75:
                return f"list.map({e(LINT)}, (x: Int) => {self.lam_body(INT, ctx, d, [('x', INT)])})"
            if k < 0.85:
                return f"list.filter({e(LINT)}, (x: Int) => {self.lam_body(BOOL, ctx, d, [('x', INT)])})"
            if k < 0.92:
                return f"range({e(INT, 0)} % 4, {e(INT, 0)} % 6)"
            return f"list.reverse({e(LINT)})"
        if ty == LSTR:
            if k < 0.4:
                return "[" + ", ".join(self.list_elem(STR, ctx, d) for _ in range(self.rng.randint(1, 3))) + "]"
            if k < 0.7:
                return f"({e(LSTR)} ++ {e(LSTR)})"
            return f"list.map({e(LINT)}, (x: Int) => {self.lam_body(STR, ctx, d, [('x', INT)])})"
        if ty == REC:
            vs = ctx.of(REC)
            if vs and k < 0.5:
                f = self.pick(["a", "b", "c"])
                ft = {"a": INT, "b": STR, "c": BOOL}[f]
                return f"{self.P}R {{ ..{self.pick(vs).name}, {f}: {e(ft)} }}"
            return f"{self.P}R {{ a: {e(INT)}, b: {e(STR)}, c: {e(BOOL)} }}"
        if ty == ADT:
            if k < 0.3:
                return f"{self.P}A"
            if k < 0.6:
                return f"{self.P}B({e(INT)})"
            return f"{self.P}C({e(STR)}, {e(INT)})"
        if ty == OPT:
            if k < 0.4:
                return f"Some({e(INT)})"
            if k < 0.7:
                return f"get({e(LINT)}, {e(INT)})"
            return f"{self.p}_none()"
        if ty == RES:
            if k < 0.6:
                return f"{self.p}_chk({e(INT)})"
            if k < 0.8:
                return f"{self.p}_ok({e(INT)})"
            return f'{self.p}_err({e(STR)})'
        if ty == FN:
            return self.fn_value(ctx, d)
        if ty == TUP:
            return f"({e(INT)}, {e(STR)})"
        raise ValueError(ty)

    def list_elem(self, ty, ctx, d):
        # an element that can leave the loop is #80/#94's shape
        if ctx.in_loop and not ctx.in_lambda and not self.no_never and self.chance(0.15):
            return f"if ({self.cond(ctx, 1)}) {{ {self.pick(['break', 'continue'])} }} else {{ {self.expr(ty, ctx, d - 1)} }}"
        return self.expr(ty, ctx, d - 1)

    def fn_value(self, ctx, d):
        vs = ctx.of(FN)
        if vs and self.chance(0.4):
            return self.pick(vs).name
        if self.chance(0.3):
            return f"{self.p}_inc"
        body = self.lam_body(INT, ctx, d, [("y", INT)])
        return f"((y: Int) => {body})"

    def lam_body(self, ty, ctx, d, params):
        """A lambda body: sees immutable bindings only, no outer jumps."""
        lv = [v for v in ctx.vars if not v.mut and v.name not in {p for p, _ in params}]
        lc = Ctx(lv + [Var(p, t, False) for p, t in params], None, None, False, True, None)
        return self.expr(ty, lc, min(d - 1, 2))

    def local_fn_call(self, ctx, d):
        """A local recursive fn, declared in a block and called once."""
        name = self.fresh("lf")
        lv = [v for v in ctx.vars if not v.mut]
        inner = Ctx(lv + [Var("k", INT, False), Var("acc", INT, False)], INT, None, False, True, None)
        step = self.expr(INT, inner, min(d - 1, 2))
        start = self.rng.randint(0, 5)
        init = self.expr(INT, ctx, d - 1)
        return (f"{{\n  fn {name}(k: Int, acc: Int) -> Int = if (k <= 0) {{ acc }} else {{ {name}(k - 1, {step}) }}\n"
                f"  {name}({start}, {init})\n}}")

    def call_helper(self, ty, ctx, d):
        cands = [h for h in self.helpers if h[2] == ty]
        if not cands:
            return None
        name, params, _ = self.pick(cands)
        args = [None] * len(params)
        # the evaluation-order probe (#84): an argument reads a var and a later
        # argument assigns it, so a backend that reads arguments late answers
        # with the new value
        mv = [v for v in ctx.vars if v.mut is True] if not ctx.in_lambda else []
        if len(params) > 1 and self.chance(0.3):
            for k, t in enumerate(params[:-1]):
                same = [v for v in mv if v.ty == t]
                if same:
                    v = self.pick(same)
                    args[k] = v.name
                    later = self.rng.randint(k + 1, len(params) - 1)
                    args[later] = self.mutating_block(params[later], ctx, d, v)
                    break
        for k, t in enumerate(params):
            if args[k] is not None:
                continue
            if self.chance(0.15):
                args[k] = self.mutating_block(t, ctx, d)
            else:
                args[k] = self.expr(t, ctx, d - 1)
        return f"{name}({', '.join(args)})"

    def mutating_block(self, ty, ctx, d, v=None):
        """An argument that assigns a var an earlier argument may have read (#84)."""
        mv = [x for x in ctx.vars if x.mut is True and x.ty in (INT, STR, LINT)]
        if v is None and (not mv or ctx.in_lambda):
            return self.expr(ty, ctx, d - 1)
        v = v or self.pick(mv)
        rhs = self.assign_rhs(v, ctx, 1)
        return f"{{\n  {v.name} = {rhs}\n  {self.expr(ty, ctx, d - 1)}\n}}"

    def block_expr(self, ty, ctx, d):
        inner = ctx.child()
        lines = self.stmts(inner, d - 1, self.rng.randint(1, 3))
        tail = self.expr(ty, inner, d - 1)
        return "{\n" + "\n".join(lines) + "\n" + tail + "\n}"

    def match_expr(self, ty, ctx, d):
        st = self.pick([ADT, OPT, RES, LINT, INT, STR, TUP, BOOL])
        scr = self.expr(st, ctx, d - 1)
        arms = []

        def arm(pat, binds, guard_ok=True):
            c = ctx.child()
            for n, t in binds:
                c.vars.append(Var(n, t, False))
            g = ""
            if guard_ok and self.chance(0.2):
                g = f" if ({self.expr(BOOL, c, 1)})"
            arms.append(f"{pat}{g} -> {self.expr(ty, c, d - 1)}")
            return g == ""

        if st == ADT:
            a, b, s, m = self.fresh("n"), self.fresh("n"), self.fresh("s"), self.fresh("m")
            pats = [(f"{self.P}A", []), (f"{self.P}B({a})", [(a, INT)]), (f"{self.P}C({s}, {m})", [(s, STR), (m, INT)])]
            if self.chance(0.3):
                pats = [(f"{self.P}A | {self.P}B(_)", []), (f"{self.P}C(_, {m})", [(m, INT)])]
            self.rng.shuffle(pats)
            clean = True
            for p, bs in pats:
                clean = arm(p, bs) and clean
            if not clean or self.chance(0.3):
                arms.append(f"_ -> {self.expr(ty, ctx, d - 1)}")
        elif st == OPT:
            x = self.fresh("o")
            arm(f"Some({x})", [(x, INT)], False)
            arms.append(f"None -> {self.expr(ty, ctx, d - 1)}")
        elif st == RES:
            x, m = self.fresh("o"), self.fresh("m")
            arm(f"Ok({x})", [(x, INT)], False)
            arm(f"Err({m})", [(m, STR)], False)
        elif st == LINT:
            h, t = self.fresh("h"), self.fresh("t")
            arms.append(f"[] -> {self.expr(ty, ctx, d - 1)}")
            arm(f"[{h}, ..{t}]", [(h, INT), (t, LINT)], False)
        elif st == TUP:
            a, b = self.fresh("n"), self.fresh("s")
            arm(f"({a}, {b})", [(a, INT), (b, STR)], False)
        elif st == BOOL:
            arms.append(f"true -> {self.expr(ty, ctx, d - 1)}")
            arms.append(f"false -> {self.expr(ty, ctx, d - 1)}")
        else:
            lits = [str(self.rng.randint(0, 9)) for _ in range(2)] if st == INT else [self.pick(STR_LITS) for _ in range(2)]
            seen = []
            for l in lits:
                if l not in seen:
                    seen.append(l)
                    arms.append(f"{l} -> {self.expr(ty, ctx, d - 1)}")
            if self.chance(0.3):
                arms.insert(0, f"{lits[0]} | {lits[1]} -> {self.expr(ty, ctx, d - 1)}") if lits[0] != lits[1] else None
            x = self.fresh("w")
            arm(x, [(x, st)], False)
        return f"match ({scr}) {{\n" + "\n".join(arms) + "\n}"

    # ---------------------------------------------------------- statements
    def assign_rhs(self, v, ctx, d):
        # The target's own value appears once at most, so a loop grows a list
        # or a string linearly rather than doubling it.
        others = ctx.child(vars=[x for x in ctx.vars if x.name != v.name or x.ty == INT])
        if v.ty == LINT:
            k = self.rng.random()
            if k < 0.5:
                return f"{v.name} ++ [{self.list_elem(INT, others, d + 1)}]"
            if k < 0.65 and ctx.try_ty and not ctx.in_lambda:
                return f"{v.name} ++ [{self.try_expr(others, d + 1)}]"   # #68
            return self.expr(LINT, others, d)
        if v.ty == STR:
            if self.chance(0.5):
                return f"{v.name} ++ {self.expr(STR, others, d)}"
            return self.expr(STR, others, d)
        if v.ty == LSTR:
            return f"{v.name} ++ [{self.list_elem(STR, others, d + 1)}]"
        return self.expr(v.ty, others, d)

    def stmts(self, ctx, d, n):
        out = []
        for _ in range(n):
            out += self.stmt(ctx, d)
        return out

    def stmt(self, ctx, d):
        r = self.rng.random()
        ty = self.pick(ALL)
        if r < 0.22:
            name = self.fresh()
            e = self.expr(ty, ctx, d)
            ctx.vars.append(Var(name, ty, False))
            return [f"let {name}: {self.T(ty)} = {e}"]
        if r < 0.36:
            ty = self.pick([INT, INT, STR, LINT, LSTR, BOOL, REC])
            name = self.fresh()
            e = self.expr(ty, ctx, d)
            ctx.vars.append(Var(name, ty, True))
            return [f"var {name}: {self.T(ty)} = {e}"]
        mv = [v for v in ctx.vars if v.mut is True]
        if r < 0.52 and mv:
            v = self.pick(mv)
            return [f"{v.name} = {self.assign_rhs(v, ctx, d)}"]
        if r < 0.62 and ctx.trace and not ctx.in_lambda:
            t = self.pick(SHOWABLE)
            return [f"{ctx.trace} = {ctx.trace} ++ [to_string({self.expr(t, ctx.child(vars=[v for v in ctx.vars if v.name != ctx.trace]), d)})]"]
        if r < 0.7 and d > 0:
            c = self.cond(ctx, d)
            a = self.stmts(ctx.child(), d - 1, self.rng.randint(1, 2))
            if self.chance(0.5):
                b = self.stmts(ctx.child(), d - 1, self.rng.randint(1, 2))
                return [f"if ({c}) {{"] + a + ["} else {"] + b + ["}"]
            return [f"if ({c}) {{"] + a + ["}"]
        if r < 0.78 and d > 0:
            w = self.fresh("w")
            bound = self.rng.randint(1, 4)
            inner = ctx.child(in_loop=True)
            inner.vars.append(Var(w, INT, "ro"))   # a var, but the body only reads it
            body = self.stmts(inner, d - 1, self.rng.randint(1, 3))
            return [f"var {w} = 0", f"while ({w} < {bound}) {{", f"{w} = {w} + 1"] + body + ["}"]
        if r < 0.84 and d > 0:
            x = self.fresh("x")
            inner = ctx.child(in_loop=True)
            if self.chance(0.5):
                src = self.expr(LINT, ctx, d - 1)
                inner.vars.append(Var(x, INT, False))
                head = f"for {x} in {self.wrap_head(src)} {{"
            else:
                head = f"for {x} in {self.rng.randint(-1, 2)}..{self.rng.randint(0, 4)} {{"
                inner.vars.append(Var(x, INT, False))
            body = self.stmts(inner, d - 1, self.rng.randint(1, 3))
            return [head] + body + ["}"]
        if r < 0.88 and ctx.in_loop and not ctx.in_lambda and not self.no_never:
            return [f"if ({self.cond(ctx, 1)}) {{ {self.pick(['break', 'continue'])} }}"]
        if r < 0.91 and not self.no_never:
            nv = self.never(ctx)
            if nv:
                return [f"if ({self.cond(ctx, 1)}) {{ {nv} }}"]
        if r < 0.94:
            # a Never initializer read afterwards (#93's shape), behind a condition
            if not self.no_never and d > 0:
                name = self.fresh()
                t = self.pick([INT, LINT, STR])
                nv = self.never(ctx)
                if nv:
                    c = self.cond(ctx, 1)
                    init = nv if t != LINT else f"[{nv}]"
                    return [f"if ({c}) {{", f"let {name}: {self.T(t)} = {init}",
                            f"let _ = {name}" if not ctx.trace or ctx.in_lambda else
                            f"{ctx.trace} = {ctx.trace} ++ [to_string({name})]", "}"]
        return [f"let _ = {self.expr(ty, ctx, d)}"]

    def wrap_head(self, src):
        return f"({src})"

    # ------------------------------------------------------------ the case
    def helper(self, j, d):
        params = [self.pick([INT, INT, STR, LINT, REC, ADT, BOOL]) for _ in range(self.rng.randint(1, 3))]
        ret = self.pick([INT, INT, STR, LINT, RES, RES, OPT, BOOL, ADT])
        name = f"{self.p}_h{j}"
        pv = [Var(f"p{i}", t, False) for i, t in enumerate(params)]
        try_ty = ret if ret in (RES, OPT) else None
        ctx = Ctx(pv, ret, try_ty, False, False, None)
        lines = self.stmts(ctx, d, self.rng.randint(0, 3))
        if ret == RES:
            tail = f"{self.p}_ok({self.expr(INT, ctx, d)})" if self.chance(0.7) else self.expr(RES, ctx, d)
        elif ret == OPT:
            tail = f"Some({self.expr(INT, ctx, d)})" if self.chance(0.7) else self.expr(OPT, ctx, d)
        else:
            tail = self.expr(ret, ctx, d)
        sig = ", ".join(f"p{i}: {self.T(t)}" for i, t in enumerate(params))
        self.helpers.append((name, params, ret))
        return f"fn {name}({sig}) -> {self.T(ret)} = {{\n" + "\n".join(lines + [tail]) + "\n}"

    def case(self):
        P, p = self.P, self.p
        decls = [
            f"type {P}R = {{ a: Int, b: String, c: Bool }} derive Show",
            f"type {P}S =\n  | {P}A\n  | {P}B(n: Int)\n  | {P}C(s: String, m: Int)\nderive Show, Ord",
            f"fn {p}_stop(msg: String) -> Never = panic(msg)",
            f"fn {p}_none() -> Option[Int] = None",
            f"fn {p}_ok(n: Int) -> Result[Int, String] = Ok(n)",
            f"fn {p}_err(m: String) -> Result[Int, String] = Err(m)",
            f'fn {p}_chk(n: Int) -> Result[Int, String] = if (n % 3 == 0) {{ Err("chk ${{n}}") }} else {{ Ok(n) }}',
            f"fn {p}_inc(n: Int) -> Int = n + 1",
            f"fn {p}_nil() -> List[Int] = []",
            f"fn {p}_snil() -> List[String] = []",
        ]
        for j in range(self.rng.randint(1, 4)):
            decls.append(self.helper(j, 2))
        ctx = Ctx([Var("trace", LSTR, True)], STR, None, False, False, "trace")
        body = self.stmts(ctx, 3, self.rng.randint(3, 8))
        fin = self.expr(self.pick(SHOWABLE), ctx, 2)
        decls.append(f"fn {p}_case() -> String = {{\nvar trace: List[String] = []\n" + "\n".join(body) +
                     f'\njoin(trace, "|") ++ " #" ++ to_string({fin})\n}}')
        return "\n\n".join(decls)


HEADER = """use std/io
use std/list
use std/str

# every import is used at least once, whatever the cases draw
fn fuzz_imports() -> Int = str.len("") + len(list.reverse([1]))
"""


def program(seed, indices, comptime=False, no_never=False):
    """One file holding the given cases.

    The runtime variant's main runs the cases from position len(argv) on and
    prints `@@ <index>` before each answer. The comptime variant folds each
    case into a const and prints the same lines, so its stdout is directly
    comparable with a run that completed every case.
    """
    parts = [HEADER]
    for i in indices:
        parts.append(CaseGen(seed, i, no_never).case())
    if comptime:
        for i in indices:
            parts.append(f"const K{i}: String = c{i}_case()")
        body = "\n".join(f'  io.println("@@ {i}")\n  io.println(K{i})' for i in indices)
        parts.append(f"pub fn main() -> Unit !io = {{\n{body}\n}}")
    else:
        names = ", ".join(f"c{i}_case" for i in indices)
        labels = ", ".join(str(i) for i in indices)
        parts.append(
            "pub fn main() -> Unit !io = {\n"
            f"  let cases: List[fn() -> String] = [{names}]\n"
            f"  let labels: List[Int] = [{labels}]\n"
            # the start index is the argument count, which needs no parser
            # whose name has moved between releases
            "  let from = len(args())\n"
            "  for i in from..len(cases) {\n"
            '    io.println("@@ ${labels[i]}")\n'
            "    io.println(cases[i]())\n"
            "  }\n"
            "}")
    return "\n\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--cases", type=int, default=20)
    ap.add_argument("--case", type=int, action="append",
                    help="emit only this case index (repeatable)")
    ap.add_argument("--comptime", action="store_true")
    ap.add_argument("--no-never", action="store_true")
    a = ap.parse_args()
    idx = a.case if a.case else list(range(a.cases))
    sys.stdout.write(program(a.seed, idx, a.comptime, a.no_never))


if __name__ == "__main__":
    main()

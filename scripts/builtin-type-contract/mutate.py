#!/usr/bin/env python3
"""Apply one builtin-type mutant's edits to a copy of the repository tree.

    scripts/builtin-type-contract/mutate.py <mutant> <tree-root>

The anchors used to be run.sh's: `replace_once` arguments and five Python
heredocs, each refusing a moved anchor only when the builtin-type shard
holding that mutant built its compiler. The files they quote (check/cx,
passes, checker, types, lsp/lspc, lspq, doc.dawn, embed/stdsrc.dawn) change
with most checker work, so a drifted anchor surfaced as a red shard long
after the edit (#277). Declared here, in the registry shape
mutation-anchor-preflight.py discovers, the same anchors have two consumers:
run.sh applies one mutant per private selfhost copy, and the preflight proves
every one before any build.

The keys are the names of run.sh's `mutants` list and matrix.txt, in the
same order; which assertion each has to turn red stays in run.sh. A mutant is
an ordered tuple of edits, each applied to the text the previous one left,
with paths relative to the tree root. An edit is (path, old, new), and
matches exactly once, or (path, old, new, count) when it rewrites every one
of a known number of copies: stale-checker-consumer renames both calls of
public_builtin_type_names() in cx.dawn, and the count is held both ways, so
a third call or a lost one is as red as a respelled anchor.
"""

from pathlib import Path
import sys

CX = "selfhost/src/check/cx.dawn"
PASSES = "selfhost/src/check/passes.dawn"
CHECKER = "selfhost/src/check/checker.dawn"
TYPES = "selfhost/src/check/types.dawn"
LSPC = "selfhost/src/lsp/lspc.dawn"
LSPQ = "selfhost/src/lsp/lspq.dawn"
DOC = "selfhost/src/doc.dawn"
STDSRC = "selfhost/src/embed/stdsrc.dawn"

TYPE_RESOLUTION = "# ---- type resolution ----\n"

MUTATIONS = {
    "stale-checker-consumer": (
        (CX, "public_builtin_type_names()", "stale_public_builtin_type_names()", 2),
        (CX, TYPE_RESOLUTION,
         '''fn stale_public_builtin_type_names() -> List[String] =
  ["Int", "Float", "Bool", "String", "Unit", "List"]

''' + TYPE_RESOLUTION),
        # the import goes with its last use: an unused import is an error, and
        # a mutant that does not compile proves nothing
        (CX, "  public_builtin_type_names,\n", ""),
    ),
    "stale-lsp-consumer": (
        (LSPC, "  for t in public_builtin_type_names() {\n",
         '  for t in ["Int", "Float", "Bool", "String", "Unit", "List", "Map", "Set"] {\n'),
        # the import goes with its only use (an unused import is an error)
        (LSPC, "  public_builtin_type_names, return_only_builtin_type_names,\n",
         "  return_only_builtin_type_names,\n"),
    ),
    "omit-return-lsp": (
        (LSPC, '    for t in return_only_builtin_type_names() {',
         '    for t in public_builtin_type_names() {'),
        # the import goes with its only use (an unused import is an error)
        (LSPC, '  public_builtin_type_names, return_only_builtin_type_names,',
         '  public_builtin_type_names,'),
    ),
    "omit-return-hover": ((
        LSPQ,
        '      if type_use == WtReturn && len(args) == 0 {',
        '      if false && type_use == WtReturn && len(args) == 0 {',
    ),),
    "omit-doc-type": ((
        DOC,
        "  for info in documented_builtin_types() {\n    w = open_obj(w)\n",
        "  for info in documented_builtin_types() {\n    if info.name == \"Char\" { continue }\n    w = open_obj(w)\n",
    ),),
    "flatten-return-doc": ((
        TYPES,
        '''pub fn builtin_type_use(info: BuiltinTypeI) -> String =
  if info.access == BtReturnOnly { "return" } else { "any" }''',
        'pub fn builtin_type_use(_info: BuiltinTypeI) -> String = "any"',
    ),),
    "omit-public-function-doc": ((
        DOC,
        '    ("char_is_letter", "whether a character is a Unicode letter"),\n',
        "",
    ),),
    "omit-prelude-function-doc": ((
        DOC,
        '    ("map", "a new list with a function applied to every element"),\n',
        "",
    ),),
    "reject-top-return": ((
        PASSES,
        '''    let (cx5, ret) = match d.ret {
      Some(r) -> resolve_return_type(cx1, r)
      None -> (cx1, TyError)
    }''',
        '''    let (cx5, ret) = match d.ret {
      Some(r) -> if d.name == "top_return_contract" {
        resolve_type(cx1, r)
      } else {
        resolve_return_type(cx1, r)
      }
      None -> (cx1, TyError)
    }''',
    ),),
    "reject-local-return": ((
        CHECKER,
        '  let (cxb, ret) = resolve_return_type(cx1, ret_ref)',
        '''  let (cxb, ret) = if name == "local_return_contract" {
    resolve_type(cx1, ret_ref)
  } else {
    resolve_return_type(cx1, ret_ref)
  }''',
    ),),
    "reject-trait-return": ((
        PASSES,
        '      let (cx5, ret) = resolve_return_type(cx1, me.ret)',
        '''      let (cx5, ret) = if me.name == "trait_return_contract" {
        resolve_type(cx1, me.ret)
      } else {
        resolve_return_type(cx1, me.ret)
      }''',
    ),),
    "reject-impl-return": ((
        PASSES,
        '''    let (cx4, ret) = match me.ret {
      Some(r) -> resolve_return_type(cx1, r)
      None -> (cx1, TyError)
    }''',
        '''    let (cx4, ret) = match me.ret {
      Some(r) -> if me.name == "impl_return_contract" {
        resolve_type(cx1, r)
      } else {
        resolve_return_type(cx1, r)
      }
      None -> (cx1, TyError)
    }''',
    ),),
    "reject-effect-return": ((
        PASSES,
        '      let (cxb, ret) = resolve_return_type(cx1, op.ret)',
        '''      let (cxb, ret) = if op.name == "effect_return_contract" {
        resolve_type(cx1, op.ret)
      } else {
        resolve_return_type(cx1, op.ret)
      }''',
    ),),
    "reject-function-type-return": ((
        CX,
        '      let (cx4, rt) = resolve_type_for(cx2, ret, TypeReturn)',
        '      let (cx4, rt) = resolve_type(cx2, ret)',
    ),),
    "allow-storage-parameter": ((
        PASSES,
        '''    for p in d.params {
      let (cx4, t) = resolve_type(cx1, p.tref)''',
        '''    for p in d.params {
      let (cx4, t) = if d.name == "storage_parameter_contract" {
        resolve_return_type(cx1, p.tref)
      } else {
        resolve_type(cx1, p.tref)
      }''',
    ),),
    "allow-storage-field": ((
        PASSES,
        '        let (cx2, ft0) = resolve_type(cx1, f.tref)',
        '''        let (cx2, ft0) = if c.name == "StorageFieldContract" {
          resolve_return_type(cx1, f.tref)
        } else {
          resolve_type(cx1, f.tref)
        }''',
    ),),
    "allow-storage-const": ((
        PASSES,
        '    let (cx2, declared0) = resolve_type(cx1, d.ann)',
        '''    let (cx2, declared0) = if d.name == "NEVER_STORAGE_CONST_CONTRACT" {
      resolve_return_type(cx1, d.ann)
    } else {
      resolve_type(cx1, d.ann)
    }''',
    ),),
    "allow-storage-let": ((
        CHECKER,
        '      let (cxa, t) = resolve_type(cx1, ref)',
        '''      let (cxa, t) = if name == "storage_let_contract" {
        resolve_return_type(cx1, ref)
      } else {
        resolve_type(cx1, ref)
      }''',
    ),),
    "allow-storage-generic": ((
        CX,
        '''        for arg in targs {
          let (cx2, ty) = resolve_type(cx1, arg)
          cx1 = cx2
          args = args ++ [ty]
        }
        return (record_span_at(cx1, lo, hi, targs), builtin_type_apply(info, args))''',
        '''        for arg in targs {
          let (cx2, ty) = if name == "List" {
            resolve_return_type(cx1, arg)
          } else {
            resolve_type(cx1, arg)
          }
          cx1 = cx2
          args = args ++ [ty]
        }
        return (record_span_at(cx1, lo, hi, targs), builtin_type_apply(info, args))''',
    ),),
    "allow-storage-tuple": ((
        CX,
        '        let (cx2, t) = resolve_type(cx1, e)',
        '        let (cx2, t) = resolve_return_type(cx1, e)',
    ),),
    "allow-function-parameter": ((
        CX,
        '        let (cx3, t) = resolve_type(cx2, p)',
        '        let (cx3, t) = resolve_return_type(cx2, p)',
    ),),
    "allow-storage-assoc": ((
        PASSES,
        '    let (cxab, bt) = resolve_type(cx1, ab.tref)',
        '    let (cxab, bt) = resolve_return_type(cx1, ab.tref)',
    ),),
    "allow-direct-alias": ((
        CX,
        '  let (cx2, t) = resolve_type(cx1, ref)',
        '  let (cx2, t) = resolve_return_type(cx1, ref)',
    ),),
    "allow-reserved-name": (
        (TYPES,
         '''pub fn builtin_type_name_reserved(info: BuiltinTypeI, is_std: Bool) -> Bool =
  builtin_type_visible(info, is_std) || info.access == BtReturnOnly''',
         '''pub fn builtin_type_name_reserved(info: BuiltinTypeI, is_std: Bool) -> Bool =
  builtin_type_visible(info, is_std)'''),
        (TYPES,
         '''pub fn hard_reserved_builtin_type_name(name: String) -> Bool =
  match builtin_type_at(name) {
    Some(info) -> builtin_type_hard_reserved(info)
    None -> false
  }''',
         'pub fn hard_reserved_builtin_type_name(_name: String) -> Bool = false'),
    ),
    "allow-never-fallthrough": ((
        CHECKER,
        '''  let (cx2, bt, bx) = check_expr(cx1, d.body, Some(s.ret))
  cx1 = cx2
  if not assignable(cx1, bt, s.ret) {''',
        '''  let (cx2, bt, bx) = check_expr(cx1, d.body, Some(s.ret))
  cx1 = cx2
  if d.name != "body_contract" && not assignable(cx1, bt, s.ret) {''',
    ),),
    "make-io-exit-bottom": (
        (TYPES,
         '    eff1(bsig("io_exit", [TyInt], ["code"], TyUnit), EIo),',
         '    eff1(bsig("io_exit", [TyInt], ["code"], TyNever), EIo),'),
        (STDSRC,
         'pub fn exit(code: Int) -> Unit !Exit = exit_now(code)',
         'pub fn exit(code: Int) -> Never !Exit = exit_now(code)'),
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutant> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new, *declared in MUTATIONS[mutation]:
        expected = declared[0] if declared else 1
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != expected:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} matches "
                             f"{count} times, expected {expected}")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()

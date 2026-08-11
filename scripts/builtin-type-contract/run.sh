#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
probe="$root/scripts/builtin-type-contract/probe.py"
work=$(mktemp -d "${TMPDIR:-/tmp}/builtin-type-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

new_mutant() {
  mutant="$work/$1"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  ln -s "$root/packages" "$mutant/packages"
}

build_mutant() {
  if ! "$dawn" build "$mutant/selfhost" -o "$mutant/compiler.jar" \
      > "$mutant/build.out" 2>&1; then
    cat "$mutant/build.out" >&2
    fail "$1 mutant did not compile"
  fi
  if ! java -jar "$mutant/compiler.jar" --version \
      > "$mutant/version.out" 2>&1; then
    cat "$mutant/version.out" >&2
    fail "$1 mutant jar did not answer --version"
  fi
}

replace_once() {
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
text = path.read_text()
if text.count(old) != 1:
    raise SystemExit(f"mutation anchor drifted in {path}: expected one, found {text.count(old)}")
path.write_text(text.replace(old, new))
PY
}

expect_marker() {
  local name=$1
  local marker=$2
  if python3 "$probe" "$mutant/compiler.jar" > "$mutant/probe.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  grep '^ASSERT: ' "$mutant/probe.out" > "$mutant/assertions.out" || true
  printf 'ASSERT: %s\n' "$marker" > "$mutant/assertions.expected"
  if ! cmp -s "$mutant/assertions.expected" "$mutant/assertions.out"; then
    cat "$mutant/probe.out" >&2
    fail "$name mutant missed its unique owning assertion"
  fi
  echo "PASS  $name compiles, then turns only $marker red"
}

"$dawn" --version > /dev/null
python3 "$probe" "$root/build/dawn-selfhost.jar"

new_mutant stale-checker-consumer
python3 - "$mutant/selfhost/src/check/cx.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
anchor = "# ---- type resolution ----\n"
stale = '''fn stale_public_builtin_type_names() -> List[String] =
  ["Int", "Float", "Bool", "String", "Unit", "List"]

'''
if text.count(anchor) != 1 or text.count("public_builtin_type_names()") != 2:
    raise SystemExit("stale-checker-consumer mutation anchor drifted")
path.write_text(text.replace(
    "public_builtin_type_names()", "stale_public_builtin_type_names()"
).replace(anchor, stale + anchor))
PY
build_mutant stale-checker-consumer
expect_marker stale-checker-consumer CHECKER_TYPE_INVENTORY

new_mutant stale-lsp-consumer
python3 - "$mutant/selfhost/src/lsp/lspc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "  for t in public_builtin_type_names() {\n"
new = '  for t in ["Int", "Float", "Bool", "String", "Unit", "List", "Map", "Set"] {\n'
if text.count(old) != 1:
    raise SystemExit("stale-lsp-consumer mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
build_mutant stale-lsp-consumer
expect_marker stale-lsp-consumer LSP_TYPE_INVENTORY

new_mutant omit-return-lsp
replace_once "$mutant/selfhost/src/lsp/lspc.dawn" \
  '    for t in return_only_builtin_type_names() {' \
  '    for t in public_builtin_type_names() {'
build_mutant omit-return-lsp
expect_marker omit-return-lsp LSP_NEVER_RETURN_CONTEXT

new_mutant omit-return-hover
replace_once "$mutant/selfhost/src/lsp/lspq.dawn" \
  '      if type_use == WtReturn && len(args) == 0 {' \
  '      if false && type_use == WtReturn && len(args) == 0 {'
build_mutant omit-return-hover
expect_marker omit-return-hover LSP_NEVER_RETURN_HOVER

new_mutant omit-doc-type
python3 - "$mutant/selfhost/src/doc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "  for info in documented_builtin_types() {\n    w = open_obj(w)\n"
new = "  for info in documented_builtin_types() {\n    if info.name == \"Char\" { continue }\n    w = open_obj(w)\n"
if text.count(old) != 1:
    raise SystemExit("omit-doc-type mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
build_mutant omit-doc-type
expect_marker omit-doc-type DOC_TYPE_INVENTORY

new_mutant flatten-return-doc
replace_once "$mutant/selfhost/src/check/types.dawn" \
  'pub fn builtin_type_use(info: BuiltinTypeI) -> String =
  if info.access == BtReturnOnly { "return" } else { "any" }' \
  'pub fn builtin_type_use(_info: BuiltinTypeI) -> String = "any"'
build_mutant flatten-return-doc
expect_marker flatten-return-doc DOC_TYPE_INVENTORY

new_mutant omit-public-function-doc
python3 - "$mutant/selfhost/src/doc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '    ("parse_int_radix", "parse an integer in base 2 through 36; None on malformed input")\n'
if text.count(old) != 1:
    raise SystemExit("omit-public-function-doc mutation anchor drifted")
path.write_text(text.replace(old, ""))
PY
build_mutant omit-public-function-doc
expect_marker omit-public-function-doc DOC_FUNCTION_INVENTORY

new_mutant omit-prelude-function-doc
python3 - "$mutant/selfhost/src/doc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '    ("map", "a new list with a function applied to every element"),\n'
if text.count(old) != 1:
    raise SystemExit("omit-prelude-function-doc mutation anchor drifted")
path.write_text(text.replace(old, ""))
PY
build_mutant omit-prelude-function-doc
expect_marker omit-prelude-function-doc DOC_FUNCTION_INVENTORY

new_mutant reject-top-return
replace_once "$mutant/selfhost/src/check/passes.dawn" \
'    let (cx5, ret) = match d.ret {
      Some(r) -> resolve_return_type(cx1, r)
      None -> (cx1, TyError)
    }' \
'    let (cx5, ret) = match d.ret {
      Some(r) -> if d.name == "top_return_contract" {
        resolve_type(cx1, r)
      } else {
        resolve_return_type(cx1, r)
      }
      None -> (cx1, TyError)
    }'
build_mutant reject-top-return
expect_marker reject-top-return NEVER_TOP_RETURN

new_mutant reject-local-return
replace_once "$mutant/selfhost/src/check/checker.dawn" \
  '  let (cxb, ret) = resolve_return_type(cx1, ret_ref)' \
  '  let (cxb, ret) = if name == "local_return_contract" {
    resolve_type(cx1, ret_ref)
  } else {
    resolve_return_type(cx1, ret_ref)
  }'
build_mutant reject-local-return
expect_marker reject-local-return NEVER_LOCAL_RETURN

new_mutant reject-trait-return
replace_once "$mutant/selfhost/src/check/passes.dawn" \
  '      let (cx5, ret) = resolve_return_type(cx1, me.ret)' \
  '      let (cx5, ret) = if me.name == "trait_return_contract" {
        resolve_type(cx1, me.ret)
      } else {
        resolve_return_type(cx1, me.ret)
      }'
build_mutant reject-trait-return
expect_marker reject-trait-return NEVER_TRAIT_RETURN

new_mutant reject-impl-return
replace_once "$mutant/selfhost/src/check/passes.dawn" \
'      let (cx4, ret) = match me.ret {
        Some(r) -> resolve_return_type(cx1, r)
        None -> (cx1, TyError)
      }' \
'      let (cx4, ret) = match me.ret {
        Some(r) -> if me.name == "impl_return_contract" {
          resolve_type(cx1, r)
        } else {
          resolve_return_type(cx1, r)
        }
        None -> (cx1, TyError)
      }'
build_mutant reject-impl-return
expect_marker reject-impl-return NEVER_IMPL_RETURN

new_mutant reject-effect-return
replace_once "$mutant/selfhost/src/check/passes.dawn" \
  '      let (cxb, ret) = resolve_return_type(cx1, op.ret)' \
  '      let (cxb, ret) = if op.name == "effect_return_contract" {
        resolve_type(cx1, op.ret)
      } else {
        resolve_return_type(cx1, op.ret)
      }'
build_mutant reject-effect-return
expect_marker reject-effect-return NEVER_EFFECT_RETURN

new_mutant reject-function-type-return
replace_once "$mutant/selfhost/src/check/cx.dawn" \
  '      let (cx4, rt) = resolve_type_for(cx2, ret, TypeReturn)' \
  '      let (cx4, rt) = resolve_type(cx2, ret)'
build_mutant reject-function-type-return
expect_marker reject-function-type-return NEVER_FUNCTION_TYPE_RETURN

new_mutant allow-storage-parameter
replace_once "$mutant/selfhost/src/check/passes.dawn" \
'    for p in d.params {
      let (cx4, t) = resolve_type(cx1, p.tref)' \
'    for p in d.params {
      let (cx4, t) = if d.name == "storage_parameter_contract" {
        resolve_return_type(cx1, p.tref)
      } else {
        resolve_type(cx1, p.tref)
      }'
build_mutant allow-storage-parameter
expect_marker allow-storage-parameter NEVER_STORAGE_PARAMETER

new_mutant allow-storage-field
replace_once "$mutant/selfhost/src/check/passes.dawn" \
  '        let (cx2, ft0) = resolve_type(cx1, f.tref)' \
  '        let (cx2, ft0) = if c.name == "StorageFieldContract" {
          resolve_return_type(cx1, f.tref)
        } else {
          resolve_type(cx1, f.tref)
        }'
build_mutant allow-storage-field
expect_marker allow-storage-field NEVER_STORAGE_FIELD

new_mutant allow-storage-const
replace_once "$mutant/selfhost/src/check/passes.dawn" \
  '    let (cx2, declared0) = resolve_type(cx1, d.ann)' \
  '    let (cx2, declared0) = if d.name == "NEVER_STORAGE_CONST_CONTRACT" {
      resolve_return_type(cx1, d.ann)
    } else {
      resolve_type(cx1, d.ann)
    }'
build_mutant allow-storage-const
expect_marker allow-storage-const NEVER_STORAGE_CONST

new_mutant allow-storage-let
replace_once "$mutant/selfhost/src/check/checker.dawn" \
  '          let (cxa, t) = resolve_type(cx1, ref)' \
  '          let (cxa, t) = if name == "storage_let_contract" {
            resolve_return_type(cx1, ref)
          } else {
            resolve_type(cx1, ref)
          }'
build_mutant allow-storage-let
expect_marker allow-storage-let NEVER_STORAGE_LET

new_mutant allow-storage-generic
replace_once "$mutant/selfhost/src/check/cx.dawn" \
'      for arg in targs {
        let (cx2, ty) = resolve_type(cx1, arg)
        cx1 = cx2
        args = args ++ [ty]
      }
      return (record_span_at(cx1, lo, hi, targs), builtin_type_apply(info, args))' \
'      for arg in targs {
        let (cx2, ty) = if name == "List" {
          resolve_return_type(cx1, arg)
        } else {
          resolve_type(cx1, arg)
        }
        cx1 = cx2
        args = args ++ [ty]
      }
      return (record_span_at(cx1, lo, hi, targs), builtin_type_apply(info, args))'
build_mutant allow-storage-generic
expect_marker allow-storage-generic NEVER_STORAGE_GENERIC

new_mutant allow-storage-tuple
replace_once "$mutant/selfhost/src/check/cx.dawn" \
  '        let (cx2, t) = resolve_type(cx1, e)' \
  '        let (cx2, t) = resolve_return_type(cx1, e)'
build_mutant allow-storage-tuple
expect_marker allow-storage-tuple NEVER_STORAGE_TUPLE

new_mutant allow-function-parameter
replace_once "$mutant/selfhost/src/check/cx.dawn" \
  '        let (cx3, t) = resolve_type(cx2, p)' \
  '        let (cx3, t) = resolve_return_type(cx2, p)'
build_mutant allow-function-parameter
expect_marker allow-function-parameter NEVER_FUNCTION_PARAMETER

new_mutant allow-storage-assoc
replace_once "$mutant/selfhost/src/check/passes.dawn" \
  '      let (cxab, bt) = resolve_type(cx1, ab.tref)' \
  '      let (cxab, bt) = resolve_return_type(cx1, ab.tref)'
build_mutant allow-storage-assoc
expect_marker allow-storage-assoc NEVER_STORAGE_ASSOC

new_mutant allow-direct-alias
replace_once "$mutant/selfhost/src/check/cx.dawn" \
  '  let (cx2, t) = resolve_type(cx1, ref)' \
  '  let (cx2, t) = resolve_return_type(cx1, ref)'
build_mutant allow-direct-alias
expect_marker allow-direct-alias NEVER_ALIAS_DIRECT

new_mutant allow-reserved-name
replace_once "$mutant/selfhost/src/check/types.dawn" \
  'pub fn builtin_type_name_reserved(info: BuiltinTypeI, is_std: Bool) -> Bool =
  builtin_type_visible(info, is_std) || info.access == BtReturnOnly' \
  'pub fn builtin_type_name_reserved(info: BuiltinTypeI, is_std: Bool) -> Bool =
  builtin_type_visible(info, is_std)'
replace_once "$mutant/selfhost/src/check/types.dawn" \
'pub fn hard_reserved_builtin_type_name(name: String) -> Bool =
  match builtin_type_at(name) {
    Some(info) -> builtin_type_hard_reserved(info)
    None -> false
  }' \
'pub fn hard_reserved_builtin_type_name(_name: String) -> Bool = false'
build_mutant allow-reserved-name
expect_marker allow-reserved-name NEVER_RESERVED_NAME

new_mutant allow-never-fallthrough
replace_once "$mutant/selfhost/src/check/checker.dawn" \
'  let (cx2, bt, bx) = check_expr(cx1, d.body, Some(s.ret))
  cx1 = cx2
  if not assignable(cx1, bt, s.ret) {' \
'  let (cx2, bt, bx) = check_expr(cx1, d.body, Some(s.ret))
  cx1 = cx2
  if d.name != "body_contract" && not assignable(cx1, bt, s.ret) {'
build_mutant allow-never-fallthrough
expect_marker allow-never-fallthrough NEVER_BODY_DIVERGES

new_mutant make-io-exit-bottom
replace_once "$mutant/selfhost/src/check/types.dawn" \
  '    eff1(bsig("io_exit", [TyInt], ["code"], TyUnit), EIo),' \
  '    eff1(bsig("io_exit", [TyInt], ["code"], TyNever), EIo),'
replace_once "$mutant/selfhost/src/embed/stdsrc.dawn" \
  'pub fn exit(code: Int) -> Unit !io = io_exit(code)' \
  'pub fn exit(code: Int) -> Never !io = io_exit(code)'
build_mutant make-io-exit-bottom
expect_marker make-io-exit-bottom IO_EXIT_UNIT

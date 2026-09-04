#!/usr/bin/env bash
# The checker, LSP and reference expose different views of one layered
# builtin-type inventory; twenty-six compiling mutants prove each consumer,
# every Never context, and both sides of the reference's reverse
# function-membership check.
#
#   ./scripts/builtin-type-contract/run.sh                 # everything
#   ./scripts/builtin-type-contract/run.sh --shard 2/3     # probe + a third
#   ./scripts/builtin-type-contract/run.sh --only <mutant> # one mutant
#
#   ITEM_TIMES=<file> ./scripts/builtin-type-contract/run.sh
#                                # also append `<mutant> <seconds>` per mutant,
#                                # for balancing the shards (matrix.txt says how)
#
# Sharding exists because a mutant costs one whole compiler build plus a
# probe. Every shard first runs probe.py against the real compiler, so no
# shard is a partial verdict about what the inventory contract asserts; the
# mutants are divided round-robin, and each shard records what it ran for
# scripts/mutant-coverage/check.py to hold the union to matrix.txt.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
probe="$root/scripts/builtin-type-contract/probe.py"
matrix="$root/scripts/builtin-type-contract/matrix.txt"
work=$(mktemp -d "${TMPDIR:-/tmp}/builtin-type-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
only=
if [ "${#shard_rest[@]}" -gt 0 ]; then
  case "${shard_rest[0]}" in
    --only)
      [ "${#shard_rest[@]}" -eq 2 ] || { echo "--only needs a mutant name" >&2; exit 2; }
      only=${shard_rest[1]}
      ;;
    *)
      echo "builtin-type-contract: unknown argument(s): ${shard_rest[*]}" >&2
      exit 2
      ;;
  esac
fi

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The executable mutant list, in run order. matrix.txt is the persistent
# record the coverage checker reads; the two are held equal in both
# directions below.
mutants=(
  stale-checker-consumer
  stale-lsp-consumer
  omit-return-lsp
  omit-return-hover
  omit-doc-type
  flatten-return-doc
  omit-public-function-doc
  omit-prelude-function-doc
  reject-top-return
  reject-local-return
  reject-trait-return
  reject-impl-return
  reject-effect-return
  reject-function-type-return
  allow-storage-parameter
  allow-storage-field
  allow-storage-const
  allow-storage-let
  allow-storage-generic
  allow-storage-tuple
  allow-function-parameter
  allow-storage-assoc
  allow-direct-alias
  allow-reserved-name
  allow-never-fallthrough
  make-io-exit-bottom
)

printf '%s\n' "${mutants[@]}" > "$work/matrix.executable"
grep -v '^#' "$matrix" | grep -v '^$' > "$work/matrix.recorded" || true
cmp -s "$work/matrix.executable" "$work/matrix.recorded" || {
  diff -u "$work/matrix.recorded" "$work/matrix.executable" >&2 || true
  fail "matrix.txt and the runner's executable mutant list disagree"
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

run_builtin_mutant() {
  new_mutant "$1"
  case "$1" in
    stale-checker-consumer)
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
      build_mutant "$1"
      expect_marker "$1" CHECKER_TYPE_INVENTORY
      ;;

    stale-lsp-consumer)
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
      build_mutant "$1"
      expect_marker "$1" LSP_TYPE_INVENTORY
      ;;

    omit-return-lsp)
      replace_once "$mutant/selfhost/src/lsp/lspc.dawn" \
        '    for t in return_only_builtin_type_names() {' \
        '    for t in public_builtin_type_names() {'
      build_mutant "$1"
      expect_marker "$1" LSP_NEVER_RETURN_CONTEXT
      ;;

    omit-return-hover)
      replace_once "$mutant/selfhost/src/lsp/lspq.dawn" \
        '      if type_use == WtReturn && len(args) == 0 {' \
        '      if false && type_use == WtReturn && len(args) == 0 {'
      build_mutant "$1"
      expect_marker "$1" LSP_NEVER_RETURN_HOVER
      ;;

    omit-doc-type)
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
      build_mutant "$1"
      expect_marker "$1" DOC_TYPE_INVENTORY
      ;;

    flatten-return-doc)
      replace_once "$mutant/selfhost/src/check/types.dawn" \
        'pub fn builtin_type_use(info: BuiltinTypeI) -> String =
  if info.access == BtReturnOnly { "return" } else { "any" }' \
        'pub fn builtin_type_use(_info: BuiltinTypeI) -> String = "any"'
      build_mutant "$1"
      expect_marker "$1" DOC_TYPE_INVENTORY
      ;;

    omit-public-function-doc)
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
      build_mutant "$1"
      expect_marker "$1" DOC_FUNCTION_INVENTORY
      ;;

    omit-prelude-function-doc)
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
      build_mutant "$1"
      expect_marker "$1" DOC_FUNCTION_INVENTORY
      ;;

    reject-top-return)
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
      build_mutant "$1"
      expect_marker "$1" NEVER_TOP_RETURN
      ;;

    reject-local-return)
      replace_once "$mutant/selfhost/src/check/checker.dawn" \
        '  let (cxb, ret) = resolve_return_type(cx1, ret_ref)' \
        '  let (cxb, ret) = if name == "local_return_contract" {
    resolve_type(cx1, ret_ref)
  } else {
    resolve_return_type(cx1, ret_ref)
  }'
      build_mutant "$1"
      expect_marker "$1" NEVER_LOCAL_RETURN
      ;;

    reject-trait-return)
      replace_once "$mutant/selfhost/src/check/passes.dawn" \
        '      let (cx5, ret) = resolve_return_type(cx1, me.ret)' \
        '      let (cx5, ret) = if me.name == "trait_return_contract" {
        resolve_type(cx1, me.ret)
      } else {
        resolve_return_type(cx1, me.ret)
      }'
      build_mutant "$1"
      expect_marker "$1" NEVER_TRAIT_RETURN
      ;;

    reject-impl-return)
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
      build_mutant "$1"
      expect_marker "$1" NEVER_IMPL_RETURN
      ;;

    reject-effect-return)
      replace_once "$mutant/selfhost/src/check/passes.dawn" \
        '      let (cxb, ret) = resolve_return_type(cx1, op.ret)' \
        '      let (cxb, ret) = if op.name == "effect_return_contract" {
        resolve_type(cx1, op.ret)
      } else {
        resolve_return_type(cx1, op.ret)
      }'
      build_mutant "$1"
      expect_marker "$1" NEVER_EFFECT_RETURN
      ;;

    reject-function-type-return)
      replace_once "$mutant/selfhost/src/check/cx.dawn" \
        '      let (cx4, rt) = resolve_type_for(cx2, ret, TypeReturn)' \
        '      let (cx4, rt) = resolve_type(cx2, ret)'
      build_mutant "$1"
      expect_marker "$1" NEVER_FUNCTION_TYPE_RETURN
      ;;

    allow-storage-parameter)
      replace_once "$mutant/selfhost/src/check/passes.dawn" \
'    for p in d.params {
      let (cx4, t) = resolve_type(cx1, p.tref)' \
'    for p in d.params {
      let (cx4, t) = if d.name == "storage_parameter_contract" {
        resolve_return_type(cx1, p.tref)
      } else {
        resolve_type(cx1, p.tref)
      }'
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_PARAMETER
      ;;

    allow-storage-field)
      replace_once "$mutant/selfhost/src/check/passes.dawn" \
        '        let (cx2, ft0) = resolve_type(cx1, f.tref)' \
        '        let (cx2, ft0) = if c.name == "StorageFieldContract" {
          resolve_return_type(cx1, f.tref)
        } else {
          resolve_type(cx1, f.tref)
        }'
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_FIELD
      ;;

    allow-storage-const)
      replace_once "$mutant/selfhost/src/check/passes.dawn" \
        '    let (cx2, declared0) = resolve_type(cx1, d.ann)' \
        '    let (cx2, declared0) = if d.name == "NEVER_STORAGE_CONST_CONTRACT" {
      resolve_return_type(cx1, d.ann)
    } else {
      resolve_type(cx1, d.ann)
    }'
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_CONST
      ;;

    allow-storage-let)
      replace_once "$mutant/selfhost/src/check/checker.dawn" \
        '          let (cxa, t) = resolve_type(cx1, ref)' \
        '          let (cxa, t) = if name == "storage_let_contract" {
            resolve_return_type(cx1, ref)
          } else {
            resolve_type(cx1, ref)
          }'
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_LET
      ;;

    allow-storage-generic)
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
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_GENERIC
      ;;

    allow-storage-tuple)
      replace_once "$mutant/selfhost/src/check/cx.dawn" \
        '        let (cx2, t) = resolve_type(cx1, e)' \
        '        let (cx2, t) = resolve_return_type(cx1, e)'
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_TUPLE
      ;;

    allow-function-parameter)
      replace_once "$mutant/selfhost/src/check/cx.dawn" \
        '        let (cx3, t) = resolve_type(cx2, p)' \
        '        let (cx3, t) = resolve_return_type(cx2, p)'
      build_mutant "$1"
      expect_marker "$1" NEVER_FUNCTION_PARAMETER
      ;;

    allow-storage-assoc)
      replace_once "$mutant/selfhost/src/check/passes.dawn" \
        '      let (cxab, bt) = resolve_type(cx1, ab.tref)' \
        '      let (cxab, bt) = resolve_return_type(cx1, ab.tref)'
      build_mutant "$1"
      expect_marker "$1" NEVER_STORAGE_ASSOC
      ;;

    allow-direct-alias)
      replace_once "$mutant/selfhost/src/check/cx.dawn" \
        '  let (cx2, t) = resolve_type(cx1, ref)' \
        '  let (cx2, t) = resolve_return_type(cx1, ref)'
      build_mutant "$1"
      expect_marker "$1" NEVER_ALIAS_DIRECT
      ;;

    allow-reserved-name)
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
      build_mutant "$1"
      expect_marker "$1" NEVER_RESERVED_NAME
      ;;

    allow-never-fallthrough)
      replace_once "$mutant/selfhost/src/check/checker.dawn" \
'  let (cx2, bt, bx) = check_expr(cx1, d.body, Some(s.ret))
  cx1 = cx2
  if not assignable(cx1, bt, s.ret) {' \
'  let (cx2, bt, bx) = check_expr(cx1, d.body, Some(s.ret))
  cx1 = cx2
  if d.name != "body_contract" && not assignable(cx1, bt, s.ret) {'
      build_mutant "$1"
      expect_marker "$1" NEVER_BODY_DIVERGES
      ;;

    make-io-exit-bottom)
      replace_once "$mutant/selfhost/src/check/types.dawn" \
        '    eff1(bsig("io_exit", [TyInt], ["code"], TyUnit), EIo),' \
        '    eff1(bsig("io_exit", [TyInt], ["code"], TyNever), EIo),'
      replace_once "$mutant/selfhost/src/embed/stdsrc.dawn" \
        'pub fn exit(code: Int) -> Unit !Exit = exit_now(code)' \
        'pub fn exit(code: Int) -> Never !Exit = exit_now(code)'
      build_mutant "$1"
      expect_marker "$1" IO_EXIT_UNIT
      ;;

    *) fail "no assertion for mutant $1" ;;
  esac
}

# Per-mutant wall clock, when ITEM_TIMES names a file. The round-robin deal in
# matrix.txt is only as good as the costs it was computed from, and a mutant
# here is one whole compiler build plus a probe, so the costs are neither equal
# nor guessable by eye. Off by default and free when off.
timed_mutant() { # name
  if [ -z "${ITEM_TIMES:-}" ]; then
    run_builtin_mutant "$1"
    return
  fi
  local start end
  start=${EPOCHREALTIME/,/.}
  run_builtin_mutant "$1"
  end=${EPOCHREALTIME/,/.}
  awk -v n="$1" -v a="$start" -v b="$end" 'BEGIN{printf "%s %.2f\n", n, b-a}' >> "$ITEM_TIMES"
}

"$dawn" --version > /dev/null
python3 "$probe" "$root/build/dawn-selfhost.jar"

if [ -n "$only" ]; then
  found=0
  for name in "${mutants[@]}"; do
    if [ "$name" = "$only" ]; then
      timed_mutant "$name"
      found=1
    fi
  done
  [ "$found" -eq 1 ] || fail "no mutant named $only"
else
  shard_begin builtin-type-contract
  position=0
  for name in "${mutants[@]}"; do
    if ! shard_skips "$position"; then
      shard_record "$name"
      timed_mutant "$name"
    fi
    position=$((position + 1))
  done
  shard_report "${#mutants[@]}"
fi

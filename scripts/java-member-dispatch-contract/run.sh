#!/usr/bin/env bash
# What `recv.member(args)` means when the member is a Java one (SYN-09).
#
# The parser cannot tell a member read from a member call: after `.` an
# UPPERCASE word became an `EFieldAcc` and a lowercase one an `EMethod`, which
# made a Java member reachable or not according to its host's naming style.
# `check_apply` now dispatches the call-shaped field access instead, so the call
# suffix decides, and the fixture below is the subject that can ask every
# question -- the JDK has no public uppercase INSTANCE method and no exported
# class with a public field and a public method of the same name, so a JDK-only
# subject can only reach half the rules. It is compiled here with
# `javac --release 21` and handed over with `--cp`, the same way a user's own
# classes arrive.
#
# Ten source mutants then compile private selfhost copies and each turns its own
# assertion red. The one asymmetry is deliberate and named where it happens:
# `java-first` breaks the Dawn qualified rules wholesale, so it reds the module
# assertion too; the constructor assertion is the one only it reds.
#
# shellcheck disable=SC2016  # the assertion sentences quote member names in
# backticks; they are diagnostics text, never command substitution.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
here="$root/scripts/java-member-dispatch-contract"
work=$(mktemp -d "${TMPDIR:-/tmp}/java-member-dispatch-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for command in javac python3; do
  command -v "$command" > /dev/null || fail "missing required command: $command"
done

"$dawn" --version > /dev/null

classes="$work/classes"
mkdir -p "$classes"
javac --release 21 -d "$classes" "$here/fixture/fixture/Syn09.java"

# ---- assertions -------------------------------------------------------------
#
# Every assertion prints exactly one `ASSERT: <sentence>` line when it fails and
# nothing when it holds, so a mutant can be attributed to the sentence it broke
# rather than to "the contract went red".

ASSERT_STATIC='uppercase Java static methods are callable'
ASSERT_INSTANCE='uppercase Java instance methods are callable'
ASSERT_SAME_NAME='a call suffix selects the method over the same-named field'
ASSERT_READ='a bare member reference is still a static field read'
ASSERT_CTOR='a qualified Dawn constructor outranks the Java lookup'
ASSERT_MODULE='a module alias receiver keeps the Dawn qualified rules'
ASSERT_EXACT='Java member names match the JVM declaration exactly'
ASSERT_STATICNESS='staticness is part of the Java member match'
ASSERT_INSTANCE_FIELD='instance fields stay unreadable'
ASSERT_PARSER='an uppercase member after `.` stays a field access in the AST'
ASSERT_LSP='a Java call maps its arguments for the language server'

# `dawn run <subject>` must print exactly `ok`: each accept subject panics with
# the leg's own name when a call resolves to the wrong member, so a wrong answer
# that still type-checks is caught by its value.
assert_runs() {
  local cli=$1 subject=$2 sentence=$3 label=$4
  shift 4
  set +e
  "$cli" run "$@" "$here/$subject" > "$work/$label.out" 2> "$work/$label.err"
  local status=$?
  set -e
  if [ "$status" -ne 0 ] || [ "$(cat "$work/$label.out")" != "ok" ]; then
    printf 'ASSERT: %s\n' "$sentence"
    return 1
  fi
  return 0
}

# The reject subject reports every line in one pass, so one changed sentence
# leaves the others intact and each group can own its own assertion.
reject_diagnostics() {
  local cli=$1 label=$2
  set +e
  "$cli" run --cp "$classes" "$here/reject" > "$work/$label.out" 2> "$work/$label.err"
  set -e
  cat "$work/$label.out" "$work/$label.err"
}

assert_messages() {
  local haystack=$1 sentence=$2
  shift 2
  local needle
  for needle in "$@"; do
    if ! grep -Fq "$needle" "$haystack"; then
      printf 'ASSERT: %s\n' "$sentence"
      return 1
    fi
  done
  return 0
}

assert_parser_shape() {
  local cli=$1 label=$2
  "$cli" __parse "$here/shape.dawn" > "$work/$label.parse"
  if ! grep -Eq '^ *Apply nargs=2 ' "$work/$label.parse" ||
      ! grep -Eq '^ *FieldAccess IEEEremainder ' "$work/$label.parse"; then
    printf 'ASSERT: %s\n' "$ASSERT_PARSER"
    return 1
  fi
  return 0
}

# Hover inside the arguments of `Class.Member(args)`. The walk reaches the
# argument either way; what it cannot do without the XJava child mapping is
# carry the typed node, and a local's hover is rendered from that node alone.
assert_lsp_children() {
  local cli=$1 label=$2
  if ! python3 "$here/hover.py" "$cli" "$root" > "$work/$label.hover" 2>&1 ||
      ! grep -Fq 'let scale: Float' "$work/$label.hover"; then
    printf 'ASSERT: %s\n' "$ASSERT_LSP"
    return 1
  fi
  return 0
}

# The whole public surface, run against one toolchain. Returns the assertion
# sentences that failed, one per line, so both the real gate and every mutant
# are judged by the same code.
run_all_assertions() {
  local cli=$1 label=$2
  assert_runs "$cli" accept/static_call.dawn "$ASSERT_STATIC" "$label-static" \
    --cp "$classes" || true
  assert_runs "$cli" accept/instance_call.dawn "$ASSERT_INSTANCE" "$label-instance" \
    --cp "$classes" || true
  assert_runs "$cli" accept/same_name.dawn "$ASSERT_SAME_NAME" "$label-same" \
    --cp "$classes" || true
  assert_runs "$cli" accept/member_read.dawn "$ASSERT_READ" "$label-read" \
    --cp "$classes" || true
  assert_runs "$cli" qualified "$ASSERT_CTOR" "$label-qualified" || true

  reject_diagnostics "$cli" "$label-reject" > "$work/$label-reject.all"
  assert_messages "$work/$label-reject.all" "$ASSERT_EXACT" \
    '`fixture.Syn09` has no static method `upperstatic`' \
    '`fixture.Syn09` has no static method `LOWERSTATIC`' || true
  assert_messages "$work/$label-reject.all" "$ASSERT_STATICNESS" \
    '`fixture.Syn09` has no static method `UpperInstance`' \
    '`fixture.Syn09` has no method `UpperStatic`' || true
  assert_messages "$work/$label-reject.all" "$ASSERT_INSTANCE_FIELD" \
    '`fixture.Syn09` has no static field `inst`' || true
  assert_messages "$work/$label-reject.all" "$ASSERT_MODULE" \
    'cannot call a value of type Int' \
    'module `lib` has no exported value `NOPE`' || true

  assert_parser_shape "$cli" "$label" || true
  assert_lsp_children "$cli" "$label" || true
}

run_all_assertions "$dawn" subject > "$work/subject.assert"
if [ -s "$work/subject.assert" ]; then
  cat "$work/subject.assert" >&2
  cat "$work"/subject-*.err 2>/dev/null >&2 || true
  fail "the Java member dispatch does not hold"
fi
echo "PASS  Java member dispatch: name, call suffix and receiver decide; case does not"

# ---- mutants ----------------------------------------------------------------

mutate() {
  local name=$1 dir=$2
  python3 - "$name" "$dir/src/check/checker.dawn" "$dir/src/front/parser.dawn" \
      "$dir/src/lsp/lspq.dawn" <<'PY'
from pathlib import Path
import sys

name, checker_name, parser_name, lspq_name = sys.argv[1:]
paths = {
    "checker": Path(checker_name),
    "parser": Path(parser_name),
    "lspq": Path(lspq_name),
}
text = {key: path.read_text() for key, path in paths.items()}


def replace_once(key: str, old: str, new: str) -> None:
    if text[key].count(old) != 1:
        raise SystemExit(f"{name}: mutation anchor drifted in {key}: {old!r}")
    text[key] = text[key].replace(old, new)


DISPATCH_ARM = """        None ->
          if not module_alias_receiver(cx, recv) {
            return check_method_call(cx, recv, fname, args0, expected, flo, fhi, lo, hi)
          }"""

if name == "drop-dispatch":
    replace_once("checker", DISPATCH_ARM, "        None -> ()")
elif name == "static-only":
    replace_once(
        "checker",
        "          if not module_alias_receiver(cx, recv) {",
        "          if not module_alias_receiver(cx, recv) && static_field_target(cx, recv) != None {",
    )
elif name == "java-first":
    replace_once(
        "checker",
        DISPATCH_ARM,
        "        None -> ()",
    )
    replace_once(
        "checker",
        "    EFieldAcc(recv, fname, flo, fhi, _, _) ->\n      match qual_ctor(cx, recv, fname) {",
        "    EFieldAcc(recv, fname, flo, fhi, _, _) -> {\n"
        "      return check_method_call(cx, recv, fname, args0, expected, flo, fhi, lo, hi)\n"
        "      match qual_ctor(cx, recv, fname) {",
    )
    replace_once(
        "checker",
        "        None -> ()\n      }\n    _ -> ()\n  }\n  # a name: `f(x)`.",
        "        None -> ()\n      }\n    }\n    _ -> ()\n  }\n  # a name: `f(x)`.",
    )
elif name == "drop-module-guard":
    replace_once(
        "checker",
        "          if not module_alias_receiver(cx, recv) {",
        "          if true {",
    )
elif name == "field-wins":
    replace_once(
        "checker",
        DISPATCH_ARM,
        """        None -> {
          var field_first = false
          match static_field_target(cx, recv) {
            Some(fq) -> {
              for f in cx.jsig.static_fields_of(fq) {
                if f.name == fname { field_first = true }
              }
            }
            None -> ()
          }
          if not module_alias_receiver(cx, recv) && not field_first {
            return check_method_call(cx, recv, fname, args0, expected, flo, fhi, lo, hi)
          }
        }""",
    )
elif name == "case-fold":
    replace_once(
        "checker",
        "    if m0.name == name && m0.is_static == is_static { matching = matching ++ [m0] }",
        "    if str.to_lower(m0.name) == str.to_lower(name) && m0.is_static == is_static {\n"
        "      matching = matching ++ [m0]\n"
        "    }",
    )
elif name == "drop-staticness":
    replace_once(
        "checker",
        "    if m0.name == name && m0.is_static == is_static { matching = matching ++ [m0] }",
        "    if m0.name == name { matching = matching ++ [m0] }",
    )
elif name == "bare-member-calls":
    replace_once(
        "checker",
        "                Some(fq) -> check_java_static_field(cx, fq, fname, flo, fhi, lo, hi)",
        "                Some(_) -> {\n"
        "                  let no_args: List[Arg] = []\n"
        "                  check_method_call(cx, target, fname, no_args, expected, flo, fhi, lo, hi)\n"
        "                }",
    )
elif name == "parser-uppercase-method":
    replace_once(
        "parser",
        "        let st3 = adv1(p, st2)\n"
        "        e = EFieldAcc(e, nt.text, nt.lo, nt.hi, e_lo(e), nt.hi)\n"
        "        st1 = st3",
        "        let st3 = adv1(p, st2)\n"
        "        if at_kind(p, st3, LPAREN) {\n"
        "          let (st6, args, close) = call_args(p, st3)?\n"
        "          e = EMethod(e, nt.text, args, nt.lo, nt.hi, e_lo(e), close.hi)\n"
        "          st1 = st6\n"
        "        } else {\n"
        "          e = EFieldAcc(e, nt.text, nt.lo, nt.hi, e_lo(e), nt.hi)\n"
        "          st1 = st3\n"
        "        }",
    )
elif name == "drop-lsp-children":
    replace_once(
        "lspq",
        """        EFieldAcc(recv, _, _, _, _, _) ->
          match te {
            Some(XJava(call, _, _, _)) -> {
              match call.target {
                Some(tt) -> { q = walk_e(qc, q, recv, Some(tt)) }
                None -> { q = walk_e(qc, q, recv, None) }
              }
              q = walk_list(qc, q, args, opt_list(call.args))
            }
            _ -> { q = walk_apply_value(qc, q, target, args, te) }
          }
""",
        "",
    )
else:
    raise SystemExit(f"unknown mutation: {name}")

for key, path in paths.items():
    path.write_text(text[key])
PY
}

# Each mutant: build a private compiler, then judge it by the same assertion set
# the subject went through. `owns` is the sentence only this mutant breaks;
# `keeps` is a sentence that must survive, which is what makes the mutant a
# discriminator rather than a way of breaking everything at once.
check_mutant() {
  local name=$1 owns=$2 keeps=$3
  local dir="$work/mutant-$name"
  mkdir -p "$dir"
  cp -R "$root/selfhost" "$dir/selfhost"
  cp -R "$root/compiler-plan" "$dir/compiler-plan"
  ln -s "$root/packages" "$dir/packages"
  mutate "$name" "$dir/selfhost"

  if ! "$dawn" build "$dir/selfhost" -o "$dir/compiler.jar" \
      > "$dir/build.out" 2>&1; then
    cat "$dir/build.out" >&2
    fail "$name mutant did not compile"
  fi

  printf '#!/bin/sh\nexec java -Xss512m -Xmx2g -jar "%s" "$@"\n' "$dir/compiler.jar" \
    > "$dir/cli"
  chmod +x "$dir/cli"

  run_all_assertions "$dir/cli" "$name" > "$dir/assert"
  if ! grep -Fxq "ASSERT: $owns" "$dir/assert"; then
    cat "$dir/assert" >&2
    fail "$name mutant did not turn its owning assertion red: $owns"
  fi
  if grep -Fxq "ASSERT: $keeps" "$dir/assert"; then
    cat "$dir/assert" >&2
    fail "$name mutant also broke the control assertion: $keeps"
  fi
  echo "PASS  $name compiles, then reds: $owns"
}

check_mutant drop-dispatch "$ASSERT_STATIC" "$ASSERT_READ"
check_mutant static-only "$ASSERT_INSTANCE" "$ASSERT_STATIC"
check_mutant java-first "$ASSERT_CTOR" "$ASSERT_STATIC"
check_mutant drop-module-guard "$ASSERT_MODULE" "$ASSERT_CTOR"
check_mutant field-wins "$ASSERT_SAME_NAME" "$ASSERT_STATIC"
check_mutant case-fold "$ASSERT_EXACT" "$ASSERT_STATIC"
check_mutant drop-staticness "$ASSERT_STATICNESS" "$ASSERT_STATIC"
check_mutant bare-member-calls "$ASSERT_READ" "$ASSERT_STATIC"
check_mutant parser-uppercase-method "$ASSERT_PARSER" "$ASSERT_STATIC"
check_mutant drop-lsp-children "$ASSERT_LSP" "$ASSERT_STATIC"

echo "java-member-dispatch-contract: OK"

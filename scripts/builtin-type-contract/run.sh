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

new_mutant omit-doc-type
python3 - "$mutant/selfhost/src/doc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "  for info in public_builtin_types() {\n    w = open_obj(w)\n"
new = "  for info in public_builtin_types() {\n    if info.name == \"Char\" { continue }\n    w = open_obj(w)\n"
if text.count(old) != 1:
    raise SystemExit("omit-doc-type mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
build_mutant omit-doc-type
expect_marker omit-doc-type DOC_TYPE_INVENTORY

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

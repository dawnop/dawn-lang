#!/usr/bin/env bash
# The custom-element boundary at the bridge, and the mutants that say the
# assertions are looking.
#
#   ./scripts/wasm-dom-contract/foreign.sh
#
# run.sh calls this before it builds anything, because nothing here needs a
# wasm toolchain: foreign.mjs drives `DomHost` with the patch lists an
# application mounting a foreign element would produce, against a document
# stub whose custom element registry dispatches `connectedCallback`/
# `disconnectedCallback` in tree order. It is here rather than in a gate of
# its own because it is about the same files the transcripts are about, and
# neither application in those transcripts mounts a foreign element -- so the
# lifecycle reaches the document by no other route.
#
# Each mutant edits a copy of one file and must turn the assertions red. Two
# of the three are production mutants (packages/tea-dom/js/dom.mjs) and one is
# a stub mutant, because the contract leans on the stub's dispatch and a stub
# that stopped dispatching would leave the assertions vacuously green. The
# edit is checked for having applied: a sed that matched nothing would report
# a clean tree as a killed mutant, which is how a mutant harness goes quietly
# blind.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (it is the bridge's runtime)." >&2
  exit 1
fi

fail=0

if node --no-warnings "$here/foreign.mjs" >"$work/base.txt" 2>&1; then
  echo "OK   foreign elements: $(grep -c '^OK' "$work/base.txt") assertions"
else
  echo "FAIL: the foreign element assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

# name @ file @ sed program
mutants=(
  # The stub stops dispatching disconnected. Every cleanup assertion --
  # remove, truncate, replace, and the disconnect half of move -- is then
  # asserting on lines nobody writes, which is the blindness this mutant
  # exists to rule out.
  'stub-drops-disconnect@scripts/wasm-dom-contract/domstub.mjs@s#if (typeof node.disconnectedCallback === .function.) {#if (false) {#'
  # Production: `remove` edits the child list behind the DOM's back instead of
  # calling `removeChild` -- the innerHTML-clearing school of removal. The
  # document ends up the right shape, and the widget is never told it left:
  # no removal recorded, no disconnected fired, the library's cleanup never
  # runs and everything it holds leaks.
  'remove-bypasses-the-dom@packages/tea-dom/js/dom.mjs@s#el.removeChild(el.childNodes\[p.at\]);#el.childNodes.splice(p.at, 1);#'
  # Production: `set-self` rebuilds instead of updating in place. An attribute
  # change then tears the widget down -- the teardown-without-notice failure,
  # landing on the one op that must never cause it. The observed red is a
  # crash before the assertions are even reached: a `set-self` payload ships
  # no `kids` field to rebuild from, so the wire's locality is what convicts
  # the rebuild.
  'set-self-rebuilds@packages/tea-dom/js/dom.mjs@s#.set-self.: (host, p) => host.setSelf(host.at(p.path), p.node),#"set-self": (host, p) => host.replaceAt(p.path, p.node),#'
)

holes=0
killed=0
for m in "${mutants[@]}"; do
  name="${m%%@*}"
  rest="${m#*@}"
  file="${rest%%@*}"
  prog="${rest#*@}"
  rm -rf "$work/tree"
  mkdir -p "$work/tree/scripts"
  cp -r "$root/packages" "$work/tree/"
  cp -r "$here" "$work/tree/scripts/wasm-dom-contract"
  target="$work/tree/$file"
  before="$(md5sum "$target")"
  sed -i "$prog" "$target"
  if [ "$before" = "$(md5sum "$target")" ]; then
    echo "NOT APPLIED: $name (the sed matched nothing; the mutant is vacuous)"
    holes=$((holes + 1))
    continue
  fi
  if node --no-warnings "$work/tree/scripts/wasm-dom-contract/foreign.mjs" >/dev/null 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} foreign-element mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "foreign elements ok ($killed/${#mutants[@]} mutants killed)"

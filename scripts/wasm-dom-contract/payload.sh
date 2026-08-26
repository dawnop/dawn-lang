#!/usr/bin/env bash
# The host half of an event payload, and the mutants that say the assertions
# are looking.
#
#   ./scripts/wasm-dom-contract/payload.sh
#
# run.sh calls this before it builds anything, because nothing here needs a
# wasm toolchain: payload.mjs drives `DomHost` and `Reactor.event` with
# hand-written listeners against the recording document stub. It is here
# rather than in a gate of its own because it is about the same files the
# transcripts are about, and most of what it pins those cannot reach: neither
# demo application declares a `key` listener, has a checkbox, or ever changes
# the kind an attached listener asked for.
#
# Each mutant edits a copy of a production file and must turn the assertions
# red. The edit is checked for having applied: a sed that matched nothing would
# report a clean tree as a killed mutant, which is how a mutant harness goes
# quietly blind.
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

if node --no-warnings "$here/payload.mjs" >"$work/base.txt" 2>&1; then
  echo "OK   payloads: $(grep -c '^OK' "$work/base.txt") assertions"
else
  echo "FAIL: the payload assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

# name @ file @ sed program
mutants=(
  # The keystroke is swallowed on its way to the element. Nothing raises, the
  # message is dispatched, and the character never appears in the field -- the
  # reason the cancel became conditional at all.
  'key-swallows-the-keystroke@packages/tea-dom/js/dom.mjs@s#if (kind !== .key. \&\& ev \&\& typeof ev.preventDefault#if (ev \&\& typeof ev.preventDefault#'
  # A checkbox reports `target.value`, which is `"on"` in a browser and the
  # empty string here: the same answer whether it is ticked or not.
  'checkbox-is-not-folded@packages/tea-dom/js/dom.mjs@s#if (target.type === .checkbox. || target.type === .radio.) {#if (false) {#'
  # `key` reads the element instead of the event, so every keystroke reports
  # whatever is in the box rather than which key was pressed.
  'key-reads-the-value@packages/tea-dom/js/dom.mjs@s#if (kind === .key.) return ev \&\& ev.key#if (false) return ev \&\& ev.key#'
  # A listener whose kind changed is left attached. The handler is closed over
  # the old kind, so the guest goes on being told the old thing forever.
  'kind-change-is-not-reattached@packages/tea-dom/js/dom.mjs@s#if (wanted.get(name) === entry.kind) continue;#if (wanted.has(name)) continue;#'
  # Absent becomes empty: the guest declared no payload for that listener, so
  # a field that is there at all makes the turn a refusal. Assigning
  # `undefined` instead would not be a mutant at all -- `JSON.stringify` drops
  # such a key, so the line on the wire would be the same one.
  'absent-payload-becomes-empty@packages/tea-dom/js/reactor.mjs@s#if (payload !== undefined) request.payload = payload;#request.payload = payload === undefined ? "" : payload;#'
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
  if node --no-warnings "$work/tree/scripts/wasm-dom-contract/payload.mjs" >/dev/null 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} payload mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "payloads ok ($killed/${#mutants[@]} mutants killed)"

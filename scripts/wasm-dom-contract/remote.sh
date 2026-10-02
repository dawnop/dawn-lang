#!/usr/bin/env bash
# The worker host of the DOM bridge, and the mutants that say the assertions
# are looking.
#
#   ./scripts/wasm-dom-contract/remote.sh
#
# run.sh calls this before it builds anything, because nothing here needs a
# wasm toolchain: remote.mjs drives `Remote` against a scripted worker and the
# recording document stub, and `worker.mjs` against a hand-written module with
# nothing in it. Its head says why the transcripts cannot see any of this:
# they drive the synchronous host, where nothing can be out of order.
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

if node --no-warnings "$here/remote.mjs" >"$work/base.txt" 2>&1; then
  echo "OK   remote: $(grep -c '^OK' "$work/base.txt") assertions"
else
  echo "FAIL: the remote assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

# name @ file @ sed program
mutants=(
  # Every turn is sent the moment its event fires. The second click goes out
  # against a model the first has not finished with, and with the address the
  # element had before the first reply moved it.
  'turns-overlap@packages/tea-dom/js/remote.mjs@s#      if (busy) return;#      if (false) return;#'
  # The address recorded when the event fired is the one sent. Right whenever
  # nothing is queued, which is almost always, and the wrong message whenever
  # it is not.
  'address-from-the-past@packages/tea-dom/js/remote.mjs@s#const path = job.el ? host.addressOf(job.el) : job.path;#const path = job.path;#'
  # An element the previous reply removed still gets its turn, with no
  # address at all.
  'dead-element-is-sent@packages/tea-dom/js/remote.mjs@s#          if (path === null) continue;#          if (false) continue;#'
  # The field is left as the reply wrote it: one keystroke behind, with the
  # caret thrown to the end, until the queued turn is answered.
  'reply-rolls-the-field-back@packages/tea-dom/js/remote.mjs@s#      putBack(keep);#      void keep;#'
  # `idle` answers at once, so a page that asks whether the panel is still
  # open asks it of a document one Escape behind the reader.
  'idle-does-not-wait@packages/tea-dom/js/remote.mjs@s#      if (!busy \&\& queue.length === 0) return Promise.resolve();#      return Promise.resolve();#'
  # A dead worker leaves its callers waiting forever: the panel says nothing
  # and never will.
  'dead-worker-hangs@packages/tea-dom/js/remote.mjs@s#    for (const w of this.waiting.values()) w.reject(this.dead);#    void 0;#'
  # The worker handles each message as it arrives instead of after the one
  # before it, so a turn posted right behind `load` runs against no module.
  'worker-out-of-order@packages/tea-dom/js/worker.mjs@s#  queue = queue.then(() => handle(msg)).then(#  queue = handle(msg).then(#'
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
  if node --no-warnings "$work/tree/scripts/wasm-dom-contract/remote.mjs" >/dev/null 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} remote mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "remote ok ($killed/${#mutants[@]} mutants killed)"

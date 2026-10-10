#!/usr/bin/env bash
# The host half of a `Fetch` command, and the mutants that say the assertions
# are looking.
#
#   ./scripts/wasm-dom-contract/fetch.sh
#
# run.sh calls this before it builds anything, because nothing here needs a
# wasm toolchain: fetch.mjs drives the fetch executor, the worker, `Remote`
# and `app.mjs` against scripted reactors and a stubbed `fetch`. Its head says
# why no transcript sees any of this: the guest only describes the request, so
# everything that matters happens on the host's side of the wire.
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

if node --no-warnings "$here/fetch.mjs" >"$work/base.txt" 2>&1; then
  echo "OK   fetch: $(grep -c '^OK' "$work/base.txt") assertions"
else
  echo "FAIL: the fetch assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

# name @ file @ sed program
mutants=(
  # A finished fetch is sent to the guest at the front of the queue, so it is
  # addressed against a document the in-flight event is about to change.
  'supply-jumps-the-queue@packages/tea-dom/js/remote.mjs@s#queue.push({ op: .supply., tag, outcome });#queue.unshift({ op: "supply", tag, outcome });#'
  # A non-2xx status rejects instead of answering, so the guest waits for a
  # reply that never comes.
  'status-rejects@packages/tea-dom/js/reactor.mjs@s#if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };#if (!res.ok) throw new Error("status");#'
  # A network failure escapes the executor.
  'network-failure-escapes@packages/tea-dom/js/reactor.mjs@s#return { ok: false, error: String((e \&\& e.message) || e) };#throw e;#'
  # The worker feeds the outcome to the reactor on its own, bypassing the
  # page's queue (and every address the page has in flight).
  'worker-supplies-itself@packages/tea-dom/js/worker.mjs@s#self.postMessage({ fetched: { tag: f.tag, outcome } })#reactor.supply(f.tag, outcome)#'
  # The worker never starts a fetch.
  'worker-never-fetches@packages/tea-dom/js/worker.mjs@s#for (const f of (reply \&\& reply.fetch) || \[\])#for (const f of [])#'
  # A supply message is not a turn of the reactor.
  'worker-drops-supply@packages/tea-dom/js/worker.mjs@s#  if (msg.op === .supply.) return reactor.supply(msg.tag, msg.outcome);##'
  # The supply line loses the tag the guest chose.
  'supply-drops-the-tag@packages/tea-dom/js/reactor.mjs@s#model: this.model, tag, ok: outcome.ok#model: this.model, ok: outcome.ok#'
  # A failure's sentence travels as if it were a body.
  'error-sent-as-body@packages/tea-dom/js/reactor.mjs@s#else request.error = outcome.error;#else request.body = outcome.error;#'
  # The page ignores what the worker reports.
  'page-ignores-fetched@packages/tea-dom/js/remote.mjs@s#if (this.onfetched) this.onfetched(fetched);#void fetched;#'
  # The synchronous host does not act on a reply's fetches.
  'app-ignores-fetch@packages/tea-dom/js/app.mjs@s#for (const f of reply.fetch || \[\])#for (const f of [])#'
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
  if node --no-warnings "$work/tree/scripts/wasm-dom-contract/fetch.mjs" >/dev/null 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} fetch mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "fetch ok ($killed/${#mutants[@]} mutants killed)"

#!/usr/bin/env bash
# Compile and execute lifecycle regressions against private selfhost copies.
# Every mutant reaches a normal LSP session and must fail only its target case.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="$root/scripts/lsp-lifecycle.py"
work="$(mktemp -d "${TMPDIR:-/tmp}/lsp-lifecycle-contract.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mutate() {
  local name=$1 source=$2
  python3 - "$name" "$source" <<'PY'
from pathlib import Path
import sys

name, source = sys.argv[1:]
path = Path(source)
text = path.read_text()

def replace_once(old, new):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"mutation anchor occurs {count} times: {old!r}")
    text = text.replace(old, new)

if name == "gate-after-update":
    replace_once(
        "          let gate = lifecycle_gate(st.lifecycle, msg)\n",
        """          match update_of(msg) {
            Some(update) -> { pending = Some(update) }
            None -> ()
          }
          let gate = lifecycle_gate(st.lifecycle, msg)
""",
    )
elif name == "early-exit-zero":
    replace_once(
        "const ABNORMAL_EXIT_STATUS: Int = 1",
        "const ABNORMAL_EXIT_STATUS: Int = 0",
    )
elif name == "shutdown-continues":
    replace_once(
        """    Shutdown -> {
      if method == \"exit\" && not request {
        LgExit(0)
      } else if request {
        LgReject(-32600, \"Invalid Request\")
      } else {
        LgIgnore
      }
    }""",
        """    Shutdown -> {
      if method == \"exit\" && not request {
        LgExit(0)
      } else if request {
        LgDispatch
      } else {
        LgIgnore
      }
    }""",
    )
elif name == "shutdown-flushes":
    replace_once(
        """            LgBeginShutdown -> {
              pending = None
              st = LspState { ..st, lifecycle: Shutdown }""",
        """            LgBeginShutdown -> {
              st = flush(st, pending)
              pending = None
              st = LspState { ..st, lifecycle: Shutdown }""",
    )
elif name == "repeat-initialize":
    replace_once(
        """      } else if method == \"initialize\" {
        if request { LgReject(-32600, \"Invalid Request\") } else { LgIgnore }""",
        """      } else if method == \"initialize\" {
        if request { LgDispatch } else { LgIgnore }""",
    )
else:
    raise SystemExit(f"unknown mutation: {name}")

path.write_text(text)
PY
}

expect_mutant_red() {
  local name=$1 case_name=$2 expected=$3
  local mutant="$work/mutant-$name"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  ln -s "$root/packages" "$mutant/packages"
  mutate "$name" "$mutant/selfhost/src/lsp/server.dawn"
  if ! java -Xss512m -Xmx2g -jar "$root/build/dawn-selfhost.jar" build \
      "$mutant/selfhost" -o "$mutant/compiler.jar" --std "$root/std" \
      --vendor org/objectweb/asm --vendor coursierapi \
      > "$mutant/build.out" 2>&1; then
    cat "$mutant/build.out" >&2
    fail "$name mutant did not compile"
  fi
  if "$harness" --case "$case_name" \
      java -Xss512m -Xmx2g -jar "$mutant/compiler.jar" lsp \
      > "$mutant/run.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  if ! grep -Fq "$expected" "$mutant/run.out"; then
    cat "$mutant/run.out" >&2
    fail "$name mutant missed its intended lifecycle boundary"
  fi
  echo "PASS  $name mutant compiles, runs, and turns $case_name red"
}

"$root/bin/dawn" --version > /dev/null
"$harness"

expect_mutant_red gate-after-update preinit-notification \
  'FAIL preinit-notification: unexpected server notification'
expect_mutant_red early-exit-zero early-exit \
  'FAIL early-exit: pre-init exit status: expected 1, got 0'
expect_mutant_red shutdown-continues post-shutdown \
  'FAIL post-shutdown: request after shutdown: expected error -32600'
expect_mutant_red shutdown-flushes pending-discard \
  'FAIL pending-discard: unexpected server notification'
expect_mutant_red repeat-initialize repeat-initialize \
  'FAIL repeat-initialize: repeat initialize: expected error -32600'

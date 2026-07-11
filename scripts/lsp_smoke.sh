#!/bin/sh
# LSP smoke test: initialize → didOpen(file with an effect error) → expect
# a publishDiagnostics notification mentioning the !io violation.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mktemp)"

send() {
  body="$1"
  printf 'Content-Length: %s\r\n\r\n%s' "${#body}" "$body"
}

{
  send '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}'
  send '{"jsonrpc":"2.0","method":"initialized","params":{}}'
  send '{"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{"uri":"file:///tmp/smoke.dawn","languageId":"dawn","version":1,"text":"fn f() -> Unit = println(\"hi\")\npub fn main() -> Unit !io = f()\n"}}}'
  sleep 3
} | "$ROOT/bin/dawn" lsp > "$OUT" 2>/dev/null || true

echo "--- server output ---"
cat "$OUT"
echo "---------------------"

if grep -q 'publishDiagnostics' "$OUT" && grep -q 'not declared !io' "$OUT"; then
  echo "SMOKE TEST PASSED: diagnostics published with the expected message"
  rm -f "$OUT"
  exit 0
else
  echo "SMOKE TEST FAILED"
  rm -f "$OUT"
  exit 1
fi

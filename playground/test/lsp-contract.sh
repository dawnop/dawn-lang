#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
sh -n playground/sandbox/run-lsp-sandboxed.sh
bash -n playground/deploy/redeploy.sh
PYTHONDONTWRITEBYTECODE=1 python3 -B playground/deploy/lsp-measure.py --self-test
# The live check of a deployed Playground talks to the internet, so only its
# offline half runs here: how a sample's recorded output is compared with
# what the runner prints for its prog.dawn buffer.
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/play-live-check.py --self-test
PYTHONDONTWRITEBYTECODE=1 \
  PLAY_LSP_CONTRACT_OMIT_FAKE_VERSION=0 \
  python3 -B playground/test/lsp_contract.py

negative="$(mktemp "${TMPDIR:-/tmp}/dawn-lsp-version-negative.XXXXXX")"
trap 'rm -f "$negative"' EXIT HUP INT TERM
if PYTHONDONTWRITEBYTECODE=1 \
  PLAY_LSP_CONTRACT_OMIT_FAKE_VERSION=1 \
  python3 -B playground/test/lsp_contract.py >"$negative" 2>&1; then
  echo "lsp-contract: diagnostics-version negative control stayed green" >&2
  exit 1
fi
if ! grep -Fq "GATEWAY_DIAGNOSTIC_VERSION_NOT_FORWARDED" "$negative"; then
  cat "$negative" >&2
  echo "lsp-contract: diagnostics-version negative control missed its assertion" >&2
  exit 1
fi
echo "lsp-contract: diagnostics-version negative control turns its assertion red"

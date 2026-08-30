#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
sh -n playground/sandbox/run-lsp-sandboxed.sh
bash -n playground/deploy/redeploy.sh
PYTHONDONTWRITEBYTECODE=1 exec python3 -B playground/test/lsp_contract.py

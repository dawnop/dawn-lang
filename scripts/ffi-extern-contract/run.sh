#!/usr/bin/env bash
# Keep the F1 entry callable like the other contracts. All inputs are explicit;
# the Python harness checks failures before accepting the positive executions.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scripts/ffi-extern-contract/run.py "$@"

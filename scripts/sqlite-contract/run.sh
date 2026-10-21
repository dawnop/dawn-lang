#!/usr/bin/env bash
# Each CI leg selects its backend contract and shares pinned fixture bytes.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scripts/sqlite-contract/run.py "$@"

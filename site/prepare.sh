#!/usr/bin/env bash
# Bootstrap is explicit so consuming a prepared site never starts a JVM.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 site/inputs.py prepare "$@"

#!/usr/bin/env bash
# Keep the human entry point stable while the strict parser, Linux sampler and
# JSON reader live in one testable implementation.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"
exec python3 -B "$root/scripts/selfhost-bench.py" "$@"

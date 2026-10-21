#!/usr/bin/env bash
# Exercise the real package driver rather than linking the fixture by hand.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scripts/ffi-sources-contract/run.py "$@"

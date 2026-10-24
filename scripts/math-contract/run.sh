#!/usr/bin/env bash
# Keep the native-diff entry small: all builds and verdicts live in run.py.
set -euo pipefail
exec python3 "$(dirname "$0")/run.py" "$@"

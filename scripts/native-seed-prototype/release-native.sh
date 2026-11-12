#!/usr/bin/env bash
# Isolated metadata producer; no build, upload or production release mutation.
set -euo pipefail
exec python3 -B "$(dirname "$0")/rehearse.py" produce "$@"

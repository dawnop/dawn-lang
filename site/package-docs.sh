#!/usr/bin/env bash
# All packages use native doc. Reviewed Java targets receive the explicit raw
# manifest; driver selection and JVM fallback are absent from production.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$#" = 1 ] || { echo "usage: site/package-docs.sh <fresh-out-dir>" >&2; exit 2; }
exec python3 site/inputs.py packages --out "$1"

#!/usr/bin/env bash
# Build the site into site/dist (run from anywhere).
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p site/build
./bin/dawn doc --builtins > site/build/builtins.json

# The Playground editor bundle (CodeMirror 6 + Dawn mode). Built locally with
# node; the server never runs node — it only receives site/dist. Skipped with a
# warning if npm is unavailable, so the rest of the site still builds.
if command -v npm >/dev/null 2>&1; then
  echo "=== building play-ui ==="
  (cd site/play-ui && npm install --silent && npm run build)
else
  echo "warning: npm not found — Playground editor bundle NOT rebuilt" >&2
fi

rm -rf site/dist
# gen_assets vendors site/play-ui/dist/playground.{js,css} into dist/assets
./bin/dawn run site

#!/usr/bin/env bash
# Build the site into site/dist (run from anywhere).
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p site/build
./bin/dawn doc --builtins > site/build/builtins.json
rm -rf site/dist
./bin/dawn run site

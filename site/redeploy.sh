#!/usr/bin/env bash
# Build the site and push to production.
# Prerequisites: SSH key loaded, user added to dawnop.com's known_hosts.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== building ==="
./site/build.sh

echo "=== deploying to dawn-lang.dawnop.com ==="
rsync -avz --delete site/dist/ <user>@dawnop.com:/var/www/dawnlang/dist/

echo "=== done ==="
echo "https://dawn-lang.dawnop.com"

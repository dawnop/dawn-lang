#!/usr/bin/env bash
# Build the site and push to production.
# Prerequisites: SSH key loaded, user added to dawnop.com's known_hosts,
# DEPLOY_USER set to the server login name (not committed — public repo).
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DEPLOY_USER:?set DEPLOY_USER to the server login name}@dawnop.com"

echo "=== building ==="
./site/build.sh

echo "=== deploying to dawn-lang.dawnop.com ==="
rsync -avz --delete site/dist/ "$HOST:/var/www/dawnlang/dist/"

echo "=== done ==="
echo "https://dawn-lang.dawnop.com"

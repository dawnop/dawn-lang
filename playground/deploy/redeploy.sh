#!/usr/bin/env bash
# Push the playground runner to production. REPEATABLE step — assumes the
# one-time server setup in DEPLOY.md is already done (dawn-play user, JDK at
# /opt/dawn/jdk, sudoers, systemd unit installed).
#
# Does NOT run itself as part of any build. Run it by hand when you mean to ship.
# Prerequisites: SSH key loaded; JAVA_HOME set or a GraalVM under ~/tools.
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

# Server login name is not committed (public repo); set DEPLOY_USER in your env.
HOST="${DEPLOY_USER:?set DEPLOY_USER to the server login name}@dawnop.com"
REMOTE=/opt/dawn

if [ -z "${JAVA_HOME:-}" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home "$HOME"/tools/graalvm-*; do
    [ -x "$d/bin/java" ] && JAVA_HOME="$d" && break
  done
fi
export JAVA_HOME

echo "=== building the selfhost toolchain ==="
./bin/dawn --version > /dev/null

echo "=== syncing to $HOST:$REMOTE ==="
# the launcher + the standalone jar it runs (bin/dawn's deployed form needs
# only build/dawn-selfhost.jar next to it — no seed fetch on the server)
rsync -avz bin/ "$HOST:$REMOTE/bin/"
rsync -avz --relative build/dawn-selfhost.jar "$HOST:$REMOTE/"
# the runner sources + manifest (recompiled on service start) and the sandbox
# scripts. main.dawn imports the `web`/`json` deps by path (playground/dawn.toml
# -> ../packages), so those packages must ship too and resolve at $REMOTE/packages.
rsync -avz --delete playground/dawn.toml playground/src playground/README.md "$HOST:$REMOTE/playground/"
rsync -avz --delete packages/ "$HOST:$REMOTE/packages/"
rsync -avz playground/sandbox/ "$HOST:$REMOTE/playground/sandbox/"

echo "=== restarting service ==="
# shellcheck disable=SC2029
ssh "$HOST" 'sudo systemctl restart dawn-play && sleep 2 && curl -s --noproxy "*" http://127.0.0.1:8087/health && echo'

echo "=== done ==="
echo "verify: curl https://dawn-lang.dawnop.com/api/health"

#!/usr/bin/env bash
# Push the playground runner to production. REPEATABLE step — assumes the
# one-time server setup in DEPLOY.md is already done (dawn-play user, JDK at
# /opt/dawn/jdk, sudoers, systemd unit installed).
#
# Does NOT run itself as part of any build. Run it by hand when you mean to ship.
# Prerequisites: SSH key loaded; JAVA_HOME set or a GraalVM under ~/tools.
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

HOST=<user>@dawnop.com
REMOTE=/opt/dawn

if [ -z "${JAVA_HOME:-}" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home "$HOME"/tools/graalvm-*; do
    [ -x "$d/bin/java" ] && JAVA_HOME="$d" && break
  done
fi
export JAVA_HOME

echo "=== building compiler fat jar ==="
gradle :compiler:fatJar -q

echo "=== syncing to $HOST:$REMOTE ==="
# the launcher + the compiler jar it points at
rsync -avz bin/ "$HOST:$REMOTE/bin/"
rsync -avz --relative compiler/build/libs/dawn.jar "$HOST:$REMOTE/"
# the runner sources (recompiled on service start) and the sandbox scripts
rsync -avz --delete playground/src playground/README.md "$HOST:$REMOTE/playground/"
rsync -avz playground/sandbox/ "$HOST:$REMOTE/playground/sandbox/"

echo "=== restarting service ==="
# shellcheck disable=SC2029
ssh "$HOST" 'sudo systemctl restart dawn-play && sleep 2 && curl -s --noproxy "*" http://127.0.0.1:8087/health && echo'

echo "=== done ==="
echo "verify: curl https://dawn-lang.dawnop.com/api/health"

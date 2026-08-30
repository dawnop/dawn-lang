#!/usr/bin/env bash
# Push the playground runner to production. REPEATABLE step — assumes the
# one-time server setup in DEPLOY.md is already done (dawn-play user, JRE 21,
# sudoers, and the gateway service/slice installed).
#
# Does NOT run itself as part of any build. Run it by hand when you mean to ship.
# Prerequisites: SSH key loaded; JAVA_HOME set or a GraalVM under ~/tools.
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

# Server login name is not committed (public repo); set DEPLOY_USER in your env.
HOST="${DEPLOY_USER:?set DEPLOY_USER to the server login name}@dawnop.com"
REMOTE=/opt/dawn
NATIVE_BIN="${DAWN_NATIVE_BIN:-dawnc-linux-x86_64}"
case "$NATIVE_BIN" in
  /*) ;;
  *) NATIVE_BIN="$PWD/$NATIVE_BIN" ;;
esac

if [ -z "${JAVA_HOME:-}" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home "$HOME"/tools/graalvm-*; do
    [ -x "$d/bin/java" ] && JAVA_HOME="$d" && break
  done
fi
export JAVA_HOME

echo "=== building the selfhost toolchain ==="
./bin/dawn --version > /dev/null

# Building the native release artifact is an independent, expensive gate and
# is deliberately not hidden inside a production deploy.  Reuse the exact
# artifact already verified by release-native.sh / CI.
if [ ! -x "$NATIVE_BIN" ]; then
  echo "error: $NATIVE_BIN is missing or not executable" >&2
  echo "build it first with: ./scripts/release-native.sh -o dawnc-linux-x86_64" >&2
  exit 1
fi
VERSION=$(sed -n 's/^pub const VERSION: String = "\(.*\)"$/\1/p' selfhost/src/version.dawn)
NATIVE_VERSION=$("$NATIVE_BIN" version)
if [ "$NATIVE_VERSION" != "dawnc $VERSION (native)" ]; then
  echo "error: native artifact says '$NATIVE_VERSION', expected dawnc $VERSION (native)" >&2
  exit 1
fi

echo "=== syncing to $HOST:$REMOTE ==="
# the launcher + the standalone jar it runs (bin/dawn's deployed form needs
# only build/dawn-selfhost.jar next to it — no seed fetch on the server)
rsync -avz bin/ "$HOST:$REMOTE/bin/"
rsync -avz --relative build/dawn-selfhost.jar "$HOST:$REMOTE/"
# Use a same-directory rename so an interrupted transfer cannot replace the
# native service binary with a partial file.
rsync -avz "$NATIVE_BIN" "$HOST:$REMOTE/bin/.dawnc.next"
# shellcheck disable=SC2029
ssh "$HOST" "
  set -e
  chmod 755 '$REMOTE/bin/.dawnc.next'
  mv '$REMOTE/bin/.dawnc.next' '$REMOTE/bin/dawnc'
  mkdir -p '$REMOTE/site/play-ui/samples'
"
# the runner sources + manifest (recompiled on service start) and the sandbox
# scripts. main.dawn imports the `web`/`json` deps by path (playground/dawn.toml
# -> ../packages), so those packages must ship too and resolve at $REMOTE/packages.
rsync -avz --delete playground/dawn.toml playground/src playground/README.md \
  playground/lsp_gateway.py "$HOST:$REMOTE/playground/"
rsync -avz --delete packages/ "$HOST:$REMOTE/packages/"
rsync -avz playground/sandbox/ "$HOST:$REMOTE/playground/sandbox/"
rsync -avz playground/deploy/ "$HOST:$REMOTE/playground/deploy/"
# Keep lsp-measure.py's deployed default repo-shaped: its location under
# /opt/dawn/playground/deploy resolves these samples under /opt/dawn/site.
# --delete: the tree is the only source of these files, so anything left in the
# directory by hand is removed rather than kept beside a measurement run.
rsync -avz --delete site/play-ui/samples/ \
  "$HOST:$REMOTE/site/play-ui/samples/"

# The remote half of the restart. It is a variable rather than an inline
# argument so the contract test can run it here against stubbed systemctl and
# curl: this is the least-executed code in the deploy, and it used to restart
# dawn-play-lsp unconditionally under `set -e`, so a machine that had not
# been through DEPLOY.md step 6 failed its next deploy, after the rsyncs.
# shellcheck disable=SC2016  # $LSP_INSTALLED is the remote shell's, not ours
REMOTE_RESTART='
  set -e
  LSP_INSTALLED=1
  systemctl cat dawn-play-lsp.service >/dev/null 2>&1 || LSP_INSTALLED=0
  if [ "$LSP_INSTALLED" = 0 ]; then
    echo "skip: dawn-play-lsp.service is not installed on this host."
    echo "      Install the systemd units first: DEPLOY.md step 6."
    sudo systemctl restart dawn-play
  else
    sudo systemctl restart dawn-play dawn-play-lsp
  fi
  # Ten one-second request budgets plus nine two-second waits bound this whole
  # check to 28 seconds, even if a process accepts TCP but never answers HTTP.
  HEALTH_ATTEMPTS=10
  HEALTH_ATTEMPT=1
  until curl -fsS --noproxy "*" --connect-timeout 1 --max-time 1 -w "\n" \
      http://127.0.0.1:8087/health; do
    if [ "$HEALTH_ATTEMPT" -ge "$HEALTH_ATTEMPTS" ]; then
      echo "error: dawn-play failed its health check after $HEALTH_ATTEMPTS attempts" >&2
      exit 1
    fi
    HEALTH_ATTEMPT=$((HEALTH_ATTEMPT + 1))
    sleep 2
  done
  if [ "$LSP_INSTALLED" = 1 ]; then
    sudo systemctl is-active --quiet dawn-play-lsp
    /usr/bin/python3 -I -B /opt/dawn/playground/deploy/lsp-smoke.py
  fi
'

echo "=== restarting service ==="
# shellcheck disable=SC2029
ssh "$HOST" "$REMOTE_RESTART"

echo "=== done ==="
echo "verify: curl https://dawn-lang.dawnop.com/api/health"

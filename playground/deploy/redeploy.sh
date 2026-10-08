#!/usr/bin/env bash
# Push the playground runner to production. REPEATABLE step — assumes the
# one-time server setup in DEPLOY.md is already done (dawn-play user, JDK 21,
# sudoers, and the gateway service/slice installed).
#
# Does NOT run itself as part of any build. Run it by hand when you mean to ship.
# Prerequisites: SSH key loaded; JAVA_HOME set or a GraalVM under ~/tools;
# DAWN_DEPLOY_COMMIT=$(git rev-parse HEAD) of the checkout this script is in.
set -euo pipefail
# The repo is resolved from this script's own location, never from $PWD (the
# same rule as site/redeploy.sh, which learned it on 2026-10-08 when a `cd`
# into a deleted worktree ran the script from the wrong checkout and shipped
# the wrong commit). The caller names the commit it means to ship
# (DAWN_DEPLOY_COMMIT, the full sha) and the script refuses unless its own
# checkout is exactly that commit with no tracked changes. This runs before
# anything is built or sent: the deploy now ships a compiler, a native runner
# and two units that must all come from one commit.
repo="$(cd "$(dirname "$0")/../.." && pwd)" || { echo "error: cannot resolve the repo from $0" >&2; exit 1; }
want_commit="${DAWN_DEPLOY_COMMIT:-}"
if ! printf '%s' "$want_commit" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "refusing to deploy: DAWN_DEPLOY_COMMIT must be the full 40-hex commit sha to ship." >&2
  echo "  got: \"$want_commit\"" >&2
  echo "  e.g. DAWN_DEPLOY_COMMIT=\$(git rev-parse HEAD) in the checkout you mean to deploy" >&2
  exit 1
fi
have_commit="$(git -C "$repo" rev-parse HEAD)"
if [ "$have_commit" != "$want_commit" ]; then
  echo "refusing to deploy: this checkout ($repo) is not the requested commit." >&2
  echo "  DAWN_DEPLOY_COMMIT: $want_commit" >&2
  echo "  git rev-parse HEAD: $have_commit" >&2
  exit 1
fi
if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then
  echo "refusing to deploy: the checkout has uncommitted changes to tracked files (HEAD $have_commit)." >&2
  git -C "$repo" status --porcelain --untracked-files=no >&2
  exit 1
fi
cd "$repo"

# Server login name is not committed (public repo); set DEPLOY_USER in your env.
HOST="${DEPLOY_USER:?set DEPLOY_USER to the server login name}@dawnop.com"
REMOTE=/opt/dawn
NATIVE_BIN="${DAWN_NATIVE_BIN:-dawnc-linux-x86_64}"
case "$NATIVE_BIN" in
  /*) ;;
  *) NATIVE_BIN="$PWD/$NATIVE_BIN" ;;
esac
# The native runner (docs/playground-native-runner-design.md, K4): the
# process-per-request binary the canary socket starts. Built like the compiler,
# off the server, because the server has no C compiler and gets none:
#   ./dawnc-linux-x86_64 build playground/native -o dawn-play-linux-x86_64
# DAWN_PLAY_NATIVE=0 ships the JVM runner alone (and leaves an installed canary
# as it is).
PLAY_NATIVE="${DAWN_PLAY_NATIVE:-1}"
PLAY_NATIVE_BIN="${DAWN_PLAY_NATIVE_BIN:-dawn-play-linux-x86_64}"
case "$PLAY_NATIVE_BIN" in
  /*) ;;
  *) PLAY_NATIVE_BIN="$PWD/$PLAY_NATIVE_BIN" ;;
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
# A binary that carries a build manifest appends its digest, ` b1:<12 hex>`;
# one built without it prints the bare line. Either is this tree's version.
# The digest is matched exactly, so a malformed tail still stops the deploy;
# the hex digits are spelled out because a range follows the locale's order.
NATIVE_BUILD=${NATIVE_VERSION#"dawnc $VERSION (native)"}
if [ "$NATIVE_BUILD" = "$NATIVE_VERSION" ] ||
    ! [[ -z "$NATIVE_BUILD" || "$NATIVE_BUILD" =~ ^\ b1:[0123456789abcdef]{12}$ ]]; then
  echo "error: native artifact says '$NATIVE_VERSION', expected dawnc $VERSION (native) [b1:<12 hex>]" >&2
  exit 1
fi

# The native runner is a second program that answers the same requests, so it
# is checked the way the compiler is: before anything is shipped, against what
# this tree says. The toolchain id is what `dawn --version` prints after its
# name ("0.85.0 b1:<12 hex>"); the unit gets it as PLAY_TOOLCHAIN_ID so that
# /health answers without a child, and the binary is asked for /health with
# that id, here, on this machine (no server, no sandbox: /health runs nothing).
# A binary built from another tree, or one that cannot start, stops the deploy
# here and not after the restart.
PLAY_TOOLCHAIN_ID=$(./bin/dawn --version | tail -n 1 | sed -e 's/^dawn //' -e 's/ (selfhost)//')
if [ "$PLAY_NATIVE" != 0 ]; then
  if [ ! -x "$PLAY_NATIVE_BIN" ]; then
    echo "error: $PLAY_NATIVE_BIN is missing or not executable" >&2
    echo "build it first with: ./dawnc-linux-x86_64 build playground/native -o dawn-play-linux-x86_64" >&2
    echo "(or set DAWN_PLAY_NATIVE=0 to ship the JVM runner alone)" >&2
    exit 1
  fi
  PLAY_NATIVE_HEALTH=$(printf 'GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n' |
    PLAY_TOOLCHAIN_ID="$PLAY_TOOLCHAIN_ID" "$PLAY_NATIVE_BIN" serve 2>/dev/null || true)
  case "$PLAY_NATIVE_HEALTH" in
    *'"ok":true,"version":"'"$VERSION"'"'*) ;;
    *)
      echo "error: $PLAY_NATIVE_BIN does not answer /health as release $VERSION:" >&2
      printf '%s\n' "$PLAY_NATIVE_HEALTH" >&2
      exit 1 ;;
  esac
fi

# The native runner runs commands from the unit's default PATH. They are
# coreutils and util-linux on any Ubuntu, but a minimal image can lack one, and
# the failure would be a 500 on /run only, behind a green /health: `timeout`
# bounds a job, `flock` is the gate, `head` bounds a read, `chmod` and `rm`
# prepare and clear a request's directory.
if [ "$PLAY_NATIVE" != 0 ]; then
  echo "=== checking $HOST has the commands the native runner runs ==="
  # shellcheck disable=SC2016  # $c is the remote shell's
  if ! ssh "$HOST" 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    missing=""
    for c in timeout flock head chmod rm sh; do
      command -v "$c" >/dev/null 2>&1 || missing="$missing $c"
    done
    if [ -n "$missing" ]; then echo "missing:$missing" >&2; exit 1; fi'; then
    echo "error: the server lacks a command the native runner needs (timeout, flock, head, chmod, rm, sh)" >&2
    exit 1
  fi
fi

# The runner runs everything on one pinned GraalVM CE 21.0.2 unpacked for it
# alone (DEPLOY.md step 2, playground/deploy/install-jdk.sh): the compiler and
# user programs for /run and /check, and javap for /compile, which only a JDK
# has. It is the toolchain CI tests on, and it is not the system's, so that no
# package changes the JRE other JVM services on the host share. The path is the
# one dawn-play.service gives the runner as PLAY_JDK and run-sandboxed.sh gives
# the units as JAVA_HOME. A runner without javap still starts and answers every
# other endpoint, which is how a deploy would go wrong quietly: the editor's
# output tab would show a 503 and the health check would be green. And a
# missing java would fail every /run. So both are checked here, before anything
# is shipped, the way the native artifact's version is.
PLAY_JDK_REMOTE="$REMOTE/graalvm-21"
echo "=== checking $HOST has GraalVM 21.0.2 at $PLAY_JDK_REMOTE ==="
# shellcheck disable=SC2029
if ! ssh "$HOST" "'$PLAY_JDK_REMOTE/bin/java' -version 2>&1 | grep -q 'version \"21\\.0\\.2\"' &&
    '$PLAY_JDK_REMOTE/bin/javap' -version 2>&1 | grep -qx '21\\.0\\.2'"; then
  echo "error: $PLAY_JDK_REMOTE/bin/java or javap is missing or is not 21.0.2 on the server" >&2
  echo "install the pinned JDK with playground/deploy/install-jdk.sh (DEPLOY.md step 2)" >&2
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
if [ "$PLAY_NATIVE" != 0 ]; then
  # Same-directory rename, as for dawnc: a connection that arrives mid-transfer
  # starts the old binary or the new one, never half of one.
  rsync -avz "$PLAY_NATIVE_BIN" "$HOST:$REMOTE/bin/.dawn-play.next"
  # The unit's EnvironmentFile; written whole and renamed for the same reason.
  # shellcheck disable=SC2029
  ssh "$HOST" "
    set -e
    chmod 755 '$REMOTE/bin/.dawn-play.next'
    mv '$REMOTE/bin/.dawn-play.next' '$REMOTE/bin/dawn-play'
    mkdir -p '$REMOTE/playground'
    printf 'PLAY_TOOLCHAIN_ID=\"%s\"\n' '$PLAY_TOOLCHAIN_ID' >'$REMOTE/playground/toolchain.env.next'
    mv '$REMOTE/playground/toolchain.env.next' '$REMOTE/playground/toolchain.env'
  "
fi
# the runner sources + manifest (recompiled on service start) and the sandbox
# scripts. main.dawn imports the `web`/`json` deps by path (playground/dawn.toml
# -> ../packages), so those packages must ship too and resolve at $REMOTE/packages.
rsync -avz --delete playground/dawn.toml playground/src playground/README.md \
  playground/lsp_gateway.py "$HOST:$REMOTE/playground/"
rsync -avz --delete packages/ "$HOST:$REMOTE/packages/"
# The site origin the gateway accepts and the smoke sends, named once in
# scripts/repo.env: dawn-play-lsp.service reads it as its EnvironmentFile, and
# lsp_gateway.py and lsp-smoke.py read it through repo_env.py by path.
rsync -avz scripts/repo.env scripts/repo_env.py "$HOST:$REMOTE/scripts/"
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

# The canary: the native runner behind its own socket, next to the JVM runner
# that has just been restarted and answered /health (it stays the primary;
# nothing is taken off it here). Last, so a canary that fails cannot leave the
# primary half-deployed, and its own variable for the reason REMOTE_RESTART is
# one. The check runs as dawn-play, who owns the socket; it compares the two
# runners' answers byte for byte and applies the ruling's gate: p95 of the
# native /health at most twice the JVM's (playground/deploy/canary-check.py).
# shellcheck disable=SC2016
REMOTE_CANARY='
  set -e
  D=/opt/dawn/playground/deploy
  sudo install -m 644 "$D/dawn-play-native.socket" /etc/systemd/system/dawn-play-native.socket
  sudo install -m 644 "$D/dawn-play-native@.service" "/etc/systemd/system/dawn-play-native@.service"
  sudo systemctl daemon-reload
  sudo systemctl enable dawn-play-native.socket
  sudo systemctl restart dawn-play-native.socket
  sudo systemctl is-active --quiet dawn-play-native.socket
  sudo -n -u dawn-play /usr/bin/python3 -I -B "$D/canary-check.py"
'
if [ "$PLAY_NATIVE" != 0 ]; then
  echo "=== installing and checking the native canary ==="
  # shellcheck disable=SC2029
  if ! ssh "$HOST" "$REMOTE_CANARY"; then
    echo "error: the native canary failed its check. The JVM runner is deployed and serving." >&2
    echo "Do not point nginx at the native socket (playground/deploy/nginx-switch.sh); read" >&2
    echo "  journalctl -u 'dawn-play-native@*' and systemctl status dawn-play-native.socket" >&2
    exit 1
  fi
fi

echo "=== done ==="
# The public health endpoint is on the service's own origin: the pages sit
# behind a CDN that cannot carry the LSP WebSocket, so the four `/api/*`
# endpoints moved off the site's origin (docs/site-cdn-design.md).
# Overridable for a deployment elsewhere.
if [ "$PLAY_NATIVE" != 0 ]; then
  echo "native canary is up on /run/dawn-play/http.sock and passed; nginx still routes to the JVM runner."
  echo "to route to it: playground/deploy/nginx-switch.sh native (prints the config; apply by hand)."
fi
echo "verify: curl ${PLAY_HEALTH_URL:-https://play.dawnop.com/api/health}"

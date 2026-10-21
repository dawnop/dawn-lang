#!/usr/bin/env bash
# Push the playground runner to production. REPEATABLE step — assumes the
# one-time server setup in DEPLOY.md is already done (dawn-play user, JDK 21,
# sudoers, the tmpfiles rule, and the gateway service/slice installed).
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
# anything is built or sent: the deploy ships a compiler, the runner binary
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
# The runner (docs/playground-native-runner-design.md): the
# process-per-request binary dawn-play-native.socket starts. Built like the
# compiler, off the server, because the server has no C compiler and gets none:
#   ./dawnc-linux-x86_64 build playground -o dawn-play-linux-x86_64
# It is the only runner since K5, so there is no longer a way to deploy
# without it (DAWN_PLAY_NATIVE=0 shipped the JVM runner alone).
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

# Used by the rollback copy below; a function so that the JDK check's own
# "stops the deploy" contract (playground/test/lsp_contract.py) stays about
# the JDK check.
backup_failed() {
  echo "error: could not make a rollback copy; nothing was deployed." >&2
  echo "  Free some space, or set DAWN_DEPLOY_NO_BACKUP=1 to deploy without one." >&2
  exit 1
}

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

# The runner is checked the way the compiler is: before anything is shipped,
# against what this tree says. The toolchain id is what `dawn --version` prints after its
# name ("0.85.0 b1:<12 hex>"); the unit gets it as PLAY_TOOLCHAIN_ID so that
# /health answers without a child, and the binary is asked for /health with
# that id, here, on this machine (no server, no sandbox: /health runs nothing).
# A binary built from another tree, or one that cannot start, stops the deploy
# here and not after the restart.
PLAY_TOOLCHAIN_ID=$(./bin/dawn --version | tail -n 1 | sed -e 's/^dawn //' -e 's/ (selfhost)//')
if [ ! -x "$PLAY_NATIVE_BIN" ]; then
  echo "error: $PLAY_NATIVE_BIN is missing or not executable" >&2
  echo "build it first with: ./dawnc-linux-x86_64 build playground -o dawn-play-linux-x86_64" >&2
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

# The runner runs commands from the unit's default PATH. They are
# coreutils and util-linux on any Ubuntu, but a minimal image can lack one, and
# the failure would be a 500 on /run only, behind a green /health: `timeout`
# bounds a job, `flock` is the gate, `head` bounds a read, `chmod` and `rm`
# prepare and clear a request's directory.
echo "=== checking $HOST has the commands the runner runs ==="
# shellcheck disable=SC2016  # $c is the remote shell's
if ! ssh "$HOST" 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  missing=""
  for c in timeout flock head chmod rm sh; do
    command -v "$c" >/dev/null 2>&1 || missing="$missing $c"
  done
  if [ -n "$missing" ]; then echo "missing:$missing" >&2; exit 1; fi'; then
  echo "error: the server lacks a command the runner needs (timeout, flock, head, chmod, rm, sh)" >&2
  exit 1
fi

# Which runner nginx sends /api/run to is the server's configuration, changed
# by hand, so it is read, never assumed: the deploy used to end with "nginx
# still routes to the JVM runner" after every run, and was wrong once the switch
# had been made (#682). Read-only: the effective config (`nginx -T`, which needs
# root) or else the files under /etc/nginx, reduced to the proxy_pass target of
# the /api/run location. The `: nginx-routing` no-op is a marker for the deploy
# guards' ssh stub.
#
# It is read before anything is shipped because since K5 the answer can stop
# the deploy: the JVM runner is gone, so a host whose nginx still sends
# /api/run to its old port would be left serving whatever that process still
# runs, from sources this deploy no longer ships. That host must be switched
# first (DEPLOY.md, "Retiring the JVM runner"). A config that cannot be read,
# or names an upstream that is neither, is "cannot tell": a warning, not a
# refusal, as before.
# shellcheck disable=SC2016
REMOTE_ROUTING=': nginx-routing
  { sudo -n nginx -T 2>/dev/null || cat $(find /etc/nginx -type f 2>/dev/null) 2>/dev/null; } |
  awk "
    /^[ \t]*#/ { next }
    /location[^{]*\/api\/run[ \t]*\{/ { inloc = 1; next }
    /^[ \t]*location[ \t]/ { inloc = 0 }
    inloc && /proxy_pass/ { t = \$0; sub(/^.*proxy_pass[ \t]+/, \"\", t); sub(/;.*/, \"\", t); print t; inloc = 0 }
  "
'
echo "=== reading which runner nginx on $HOST routes /api/run to ==="
# shellcheck disable=SC2029
ROUTING_TARGETS=$(ssh "$HOST" "$REMOTE_ROUTING" 2>/dev/null | sed '/^$/d' | sort -u || true)
case "$ROUTING_TARGETS" in
  http://unix:*) ROUTING_LINE="nginx routes /api/run to the runner's socket ($ROUTING_TARGETS)." ;;
  http://127.0.0.1:8087/*|http://localhost:8087/*)
    echo "error: nginx routes /api/run to the JVM runner's port ($ROUTING_TARGETS), and this release has no JVM runner." >&2
    echo "  Point nginx at the runner's socket first (playground/deploy/nginx-play.conf; DEPLOY.md, \"Retiring the JVM runner\")." >&2
    exit 1 ;;
  "") ROUTING_LINE="cannot tell which runner nginx routes /api/run to: no proxy_pass found (config unreadable?). Check the server's nginx config." ;;
  *) ROUTING_LINE="cannot tell which runner nginx routes /api/run to: unrecognised upstream(s): $(printf '%s' "$ROUTING_TARGETS" | tr '\n' ' '). Check the server's nginx config." ;;
esac
echo "$ROUTING_LINE"

# The runner runs everything on one pinned GraalVM CE 21.0.2 unpacked for it
# alone (DEPLOY.md step 2, playground/deploy/install-jdk.sh): the compiler and
# user programs for /run and /check, and javap for /compile, which only a JDK
# has. It is the toolchain CI tests on, and it is not the system's, so that no
# package changes the JRE other JVM services on the host share. The path is the
# one dawn-play-native@.service gives the runner as PLAY_JDK and
# run-sandboxed.sh gives the units as JAVA_HOME. A runner without javap still starts and answers every
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

# Rollback point. Before anything on the server is replaced, the live runner
# side (launcher, jar, runner sources, packages, scripts, samples) is copied to
# $REMOTE/.prev-<live version>-<UTC stamp>-runner and the newest 3 are kept
# (scripts/deploy-backup.sh, which has the reasons). It fails closed: if the
# copy cannot be made the deploy stops here, before the first rsync. A rerun
# of this commit after a run that stopped part way keeps that run's copy
# instead of copying the half-deployed tree; the --done call at the end is
# what marks a run as finished.
# DAWN_DEPLOY_NO_BACKUP=1 skips it, for a disk that cannot hold a copy.
# DEPLOY.md, "Rollback", says how to restore one.
if [ "${DAWN_DEPLOY_NO_BACKUP:-}" = 1 ]; then
  echo "warning: DAWN_DEPLOY_NO_BACKUP=1, deploying without a rollback copy" >&2
else
  echo "=== keeping a rollback copy on $HOST ==="
  # shellcheck disable=SC2029
  if ! ssh "$HOST" bash -s -- "$REMOTE" "$REMOTE" runner "cmd:$REMOTE/bin/dawnc" "$want_commit" \
      bin build playground packages scripts site <scripts/deploy-backup.sh; then
    backup_failed
  fi
fi
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
# The runner binary goes beside the live one and is not swapped in until the
# canary below has held it to that one; same directory, so the swap is a
# rename and a connection that arrives then starts the old binary or the new
# one, never half of one.
rsync -avz "$PLAY_NATIVE_BIN" "$HOST:$REMOTE/bin/.dawn-play.next"
# shellcheck disable=SC2029
ssh "$HOST" "chmod 755 '$REMOTE/bin/.dawn-play.next'"
# The runner's README and the LSP gateway. Not the runner's sources: until K5
# the JVM runner compiled them on every start (`dawn run /opt/dawn/playground`);
# the binary needs none of them, and the packages below ship for the Tile IR
# view and the language server, which read them per request.
rsync -avz playground/README.md playground/lsp_gateway.py "$HOST:$REMOTE/playground/"
rsync -avz --delete packages/ "$HOST:$REMOTE/packages/"
# The project the language server opens a tileir program in (lsp_gateway.py):
# its manifest names ../../packages/tileir, tileref and tileinterp, which are
# $REMOTE/packages above, so the three must ship together.
rsync -avz --delete playground/lsp-tile/ "$HOST:$REMOTE/playground/lsp-tile/"
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
# argument so the contract test can run it here against stubbed systemctl:
# this is the least-executed code in the deploy, and it used to restart
# dawn-play-lsp unconditionally under `set -e`, so a machine that had not
# been through DEPLOY.md step 6 failed its next deploy, after the rsyncs.
# The runner is not restarted here: it has no resident process (systemd starts
# one per connection), and the binary swap below is what changes it. Until K5
# this also restarted the JVM runner and polled its /health on 127.0.0.1:8087.
# shellcheck disable=SC2016  # $LSP_INSTALLED is the remote shell's, not ours
REMOTE_RESTART='
  set -e
  LSP_INSTALLED=1
  systemctl cat dawn-play-lsp.service >/dev/null 2>&1 || LSP_INSTALLED=0
  if [ "$LSP_INSTALLED" = 0 ]; then
    echo "skip: dawn-play-lsp.service is not installed on this host."
    echo "      Install the systemd units first: DEPLOY.md step 6."
  else
    sudo systemctl restart dawn-play-lsp
    sudo systemctl is-active --quiet dawn-play-lsp
    /usr/bin/python3 -I -B /opt/dawn/playground/deploy/lsp-smoke.py
  fi
'

echo "=== restarting the LSP gateway ==="
# shellcheck disable=SC2029
ssh "$HOST" "$REMOTE_RESTART"

# The canary, before the swap: the binary this deploy ships against the one
# that is live, as dawn-play (the user the units run as, whom sudoers lets run
# the sandbox wrapper), both started per request the way the socket unit
# starts them, with the unit's environment, on the toolchain synced above
# (playground/deploy/canary-check.py has the cases and the thresholds): the
# candidate's own expected answers and access lines, the same answers as the
# previous runner, and on /run hello and /check hello, 20 spaced requests
# each, a p95 at most 1.15 x the previous one's + 100 ms. A runner change
# that is meant to change an answer says so with
# DAWN_PLAY_CANARY_ACCEPT_DIFF=1; the differences are printed either way. It
# adds roughly 2 to 4 minutes to a deploy. A failure leaves the previous binary
# live.
# shellcheck disable=SC2016  # the remote shell's variables
REMOTE_CANARY='
  set -e
  D=/opt/dawn/playground/deploy
  B=/opt/dawn/bin
  ACCEPT=""
  if [ "$ACCEPT_DIFF" = 1 ]; then ACCEPT=--accept-diff; fi
  # shellcheck disable=SC2086  # ACCEPT is a flag or nothing
  sudo -n -u dawn-play /usr/bin/python3 -I -B "$D/canary-check.py" \
    --candidate "$B/.dawn-play.next" --previous "$B/dawn-play" \
    --unit "$D/dawn-play-native@.service" --toolchain-id "$TOOLCHAIN_ID" $ACCEPT
'
# The sample answers (play/answers, docs/playground-native-runner-design.md
# 4.4), made before the swap and by the binary that is about to go live: its
# `warm` subcommand sends every sample in the tree just synced through its own
# routes, as dawn-play so that the jobs go through the real sandbox, into a
# staging directory under the work root. The staged files are then copied into
# a directory the deploy user owns and swapped in for the live one; the runner
# (user dawn-play) can read it and, being the only other writer and not
# writing in a serving process, never changes it. It runs after the canary, so
# the canary's byte compare sees a runner with no store, and before the swap,
# so that the first request the new binary answers already finds its samples.
# A sample that does not get an answer stops the deploy here with the previous
# binary live: see play/warm.dawn for why that is a failure and not a warning.
# shellcheck disable=SC2016  # the remote shell's variables
REMOTE_WARM='
  set -e
  D=/opt/dawn/playground/deploy
  B=/opt/dawn/bin
  P=/opt/dawn/playground
  STAGE=/var/lib/dawn-play/work/answers-stage
  sudo -n -u dawn-play /usr/bin/python3 -I -B "$D/canary-check.py" --warm \
    --candidate "$B/.dawn-play.next" --unit "$D/dawn-play-native@.service" --toolchain-id "$TOOLCHAIN_ID" \
    --samples /opt/dawn/site/play-ui/samples --stage "$STAGE"
  rm -rf /opt/dawn/playground/answers.next /opt/dawn/playground/answers.old
  mkdir -m 755 /opt/dawn/playground/answers.next
  cp "$STAGE"/* /opt/dawn/playground/answers.next/
  chmod 644 /opt/dawn/playground/answers.next/*
  if [ -d /opt/dawn/playground/answers ]; then mv /opt/dawn/playground/answers /opt/dawn/playground/answers.old; fi
  mv /opt/dawn/playground/answers.next /opt/dawn/playground/answers
  rm -rf /opt/dawn/playground/answers.old
'
# The swap, and the check through the socket after it. The toolchain id the
# units read (their EnvironmentFile) and the binary are each renamed into
# place; the two units are installed only when they differ from what is
# installed, and the socket is restarted only when its own unit changed or it
# is not running, because a restart closes the listening socket that nginx
# sends every request to. Then /health and /run through the socket itself, as
# dawn-play, who may connect: this release and build, a /health p95 at most
# 25 ms over 100 new connections (the real Accept=yes start-up), hello prints
# hello, and the hello sample out of the answer store (a copy with one more
# byte compiled instead).
# shellcheck disable=SC2016  # the remote shell's variables
REMOTE_SWAP='
  set -e
  D=/opt/dawn/playground/deploy
  B=/opt/dawn/bin
  P=/opt/dawn/playground
  printf "PLAY_TOOLCHAIN_ID=\"%s\"\n" "$TOOLCHAIN_ID" >"$P/toolchain.env.next"
  mv "$P/toolchain.env.next" "$P/toolchain.env"
  mv "$B/.dawn-play.next" "$B/dawn-play"
  UNITS_CHANGED=0
  SOCKET_CHANGED=0
  for u in dawn-play-native.socket dawn-play-native@.service; do
    if ! cmp -s "$D/$u" "/etc/systemd/system/$u"; then
      sudo install -m 644 "$D/$u" "/etc/systemd/system/$u"
      UNITS_CHANGED=1
      if [ "$u" = dawn-play-native.socket ]; then SOCKET_CHANGED=1; fi
    fi
  done
  if [ "$UNITS_CHANGED" = 1 ]; then sudo systemctl daemon-reload; fi
  sudo systemctl enable dawn-play-native.socket
  if [ "$SOCKET_CHANGED" = 1 ] || ! sudo systemctl is-active --quiet dawn-play-native.socket; then
    sudo systemctl restart dawn-play-native.socket
  fi
  sudo systemctl is-active --quiet dawn-play-native.socket
  sudo -n -u dawn-play /usr/bin/python3 -I -B "$D/canary-check.py" --live --toolchain-id "$TOOLCHAIN_ID" --samples /opt/dawn/site/play-ui/samples
'
CANARY_ENV="TOOLCHAIN_ID='$PLAY_TOOLCHAIN_ID'; ACCEPT_DIFF='${DAWN_PLAY_CANARY_ACCEPT_DIFF:-}';"
echo "=== checking the new runner against the live one (canary) ==="
# shellcheck disable=SC2029
if ! ssh "$HOST" "$CANARY_ENV $REMOTE_CANARY"; then
  echo "error: the runner canary failed its check; the new binary was not swapped in." >&2
  echo "  The previous runner binary is still live, on the toolchain this deploy synced." >&2
  echo "  Fix and redeploy, or restore the rollback copy (playground/deploy/DEPLOY.md, \"Rollback copies\")." >&2
  exit 1
fi
echo "=== warming the sample answers with the new runner ==="
# shellcheck disable=SC2029
if ! ssh "$HOST" "$CANARY_ENV $REMOTE_WARM"; then
  echo "error: the sample answers could not be warmed; the new binary was not swapped in." >&2
  echo "  The previous runner binary is still live. Read the warm: lines above for the sample that got no answer." >&2
  exit 1
fi
echo "=== swapping the runner in and checking it through the socket ==="
# shellcheck disable=SC2029
if ! ssh "$HOST" "$CANARY_ENV $REMOTE_SWAP"; then
  echo "error: the new runner is live and failed its check through the socket." >&2
  echo "  Read journalctl -u 'dawn-play-native@*' and systemctl status dawn-play-native.socket;" >&2
  echo "  restore the rollback copy if it does not recover (playground/deploy/DEPLOY.md, \"Rollback copies\")." >&2
  exit 1
fi

# Finished: the next deploy copies what is live now. Only a warning when it
# fails, since the runner is already live; a rerun of this same commit would
# then keep the older copy (DEPLOY.md, "Rollback copies").
# shellcheck disable=SC2029
if ! ssh "$HOST" bash -s -- --done "$REMOTE" runner <scripts/deploy-backup.sh; then
  echo "warning: could not clear $REMOTE/.deploy-pending-runner; remove it by hand" >&2
fi

echo "=== done ==="
# The public health endpoint is on the service's own origin: the pages sit
# behind a CDN that cannot carry the LSP WebSocket, so the four `/api/*`
# endpoints moved off the site's origin (docs/site-cdn-design.md).
# Overridable for a deployment elsewhere.
echo "the runner is live on /run/dawn-play/http.sock and passed its checks."
echo "$ROUTING_LINE"
echo "verify: curl ${PLAY_HEALTH_URL:-https://play.dawnop.com/api/health}"

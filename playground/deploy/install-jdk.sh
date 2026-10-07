#!/usr/bin/env bash
# Install the pinned GraalVM CE 21.0.2 that the Playground runner runs on.
# Run by hand on YOUR machine, once per pin change; it is not part of
# redeploy.sh, which only checks that the result is there.
#
# Why this JDK: it is the one the dev box and CI (setup-graalvm, distribution
# graalvm-community, java 21) test the compiler on, so the server runs what was
# tested. Why a private copy and not `apt-get install openjdk-21-jdk-headless`:
# the package puts javap in /usr/bin through alternatives and moves the patch
# level of the JRE that every other JVM service on the host shares. This tree
# is read by nothing but the runner (PLAY_JDK in dawn-play.service) and the
# sandbox units, which see it through their read-only bind of /opt/dawn. It
# lives under /opt/dawn and not $HOME because those units run with
# ProtectHome=yes. It must stay at /opt/dawn/graalvm-21: run-sandboxed.sh names
# that path as the units' JAVA_HOME.
#
# Why the download happens here: the server cannot reach GitHub. The sha256 is
# pinned below (it is the one in the .sha256 file next to the tarball), so a
# changed or truncated file stops the script before anything leaves this
# machine.
#
# Server login is not committed (public repo); set DEPLOY_USER like redeploy.sh.
# To move the pin: take the new tarball and its .sha256 from the graalvm-ce-builds
# release (https://github.com/graalvm/graalvm-ce-builds/releases), change the
# lines below together, and the version checks in redeploy.sh.
set -euo pipefail

TAG='jdk-21.0.2'
FILE='graalvm-community-jdk-21.0.2_linux-x64_bin.tar.gz'
SHA256='b048069aaa3a99b84f5b957b162cc181a32a4330cbc35402766363c5be76ae48'

HOST="${DEPLOY_USER:?set DEPLOY_USER to the server login name}@dawnop.com"
REMOTE=/opt/dawn
TARGET="$REMOTE/graalvm-21"   # the path dawn-play.service names in PLAY_JAVAP
URL="https://github.com/graalvm/graalvm-ce-builds/releases/download/$TAG/$FILE"

CACHE="${DAWN_JDK_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/dawn-play}"
mkdir -p "$CACHE"
TARBALL="$CACHE/$FILE"

if [ ! -f "$TARBALL" ]; then
  echo "=== downloading $FILE ==="
  curl -fL --retry 3 -o "$TARBALL.part" "$URL"
  mv "$TARBALL.part" "$TARBALL"
fi
echo "=== verifying sha256 ==="
if ! echo "$SHA256  $TARBALL" | sha256sum -c - >/dev/null; then
  echo "error: $TARBALL does not match the pinned sha256 $SHA256" >&2
  echo "delete it and run again; if it keeps failing, do not install it" >&2
  exit 1
fi

echo "=== sending to $HOST:$REMOTE ==="
# shellcheck disable=SC2029
ssh "$HOST" "mkdir -p '$REMOTE'"
rsync -v --partial "$TARBALL" "$HOST:$REMOTE/.jdk-incoming.tar.gz"

echo "=== unpacking beside $TARGET and swapping it in ==="
# The tarball is unpacked next to the target and renamed into place, so a
# half-unpacked tree is never at the path the runner reads. The previous tree,
# if any, is moved aside first and removed after the swap.
# shellcheck disable=SC2029
ssh "$HOST" "
  set -euo pipefail
  umask 022
  cd '$REMOTE'
  stage=\$(mktemp -d '$REMOTE/.jdk-stage.XXXXXX')
  trap 'rm -rf \"\${stage:?}\"' EXIT
  tar -xzf .jdk-incoming.tar.gz -C \"\$stage\" --strip-components=1 --no-same-owner
  chmod -R go+rX \"\$stage\"
  \"\$stage/bin/javap\" -version 2>&1 | grep -qx '21\\.0\\.2'
  \"\$stage/bin/java\" -version 2>&1 | grep -q 'version \"21\\.0\\.2\"'
  if [ -e '$TARGET' ]; then
    rm -rf /opt/dawn/graalvm-21.old
    mv '$TARGET' /opt/dawn/graalvm-21.old
  fi
  mv \"\$stage\" '$TARGET'
  trap - EXIT
  rm -rf /opt/dawn/graalvm-21.old
  rm -f .jdk-incoming.tar.gz
  '$TARGET/bin/java' -version 2>&1 | head -1
  '$TARGET/bin/javap' -version
"
echo "done: $TARGET is $TAG. Run redeploy.sh (or restart dawn-play) so the runner"
echo "starts on it; the next sandbox units pick it up on their own."

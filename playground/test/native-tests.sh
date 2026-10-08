#!/bin/sh
# Runs the runner's test blocks with the native compiler (`dawnc test`), over
# the modules the native entry reaches: everything under src/play except the
# JVM server's host (jvmhost) and its cache. The point is the other half of
# `dawn test playground`: the same tests on a toolchain with no JVM, which is
# the one that builds the binary (docs/playground-native-runner-design.md, K3).
#
# `dawnc test` compiles the test blocks of one project's own modules, and the
# runner's modules are a dependency of playground/native, so they are copied
# into a scratch project here. Needs a `dawnc` (DAWNC, default `dawnc` on PATH)
# and `timeout`, `flock`, `head` and `sh`.
set -e
cd "$(dirname "$0")/.."
ROOT=$(cd .. && pwd)
DAWNC=${DAWNC:-dawnc}
TMP=$(mktemp -d "${TMPDIR:-/tmp}/play-native-tests.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/src/play"
for f in src/play/*.dawn; do
  case "$f" in
    */jvmhost.dawn|*/cache.dawn) ;;
    *) cp "$f" "$TMP/src/play/" ;;
  esac
done
cat >"$TMP/src/main.dawn" <<'EOF'
pub fn main() -> Unit = ()
EOF
cat >"$TMP/dawn.toml" <<EOF
schema = 1
name = "play_native_tests"

[deps]
json = "$ROOT/packages/json"
sha2 = "$ROOT/packages/sha2"
xmap = "$ROOT/packages/xmap"
EOF
"$DAWNC" test "$TMP"

#!/usr/bin/env bash
# The paired correctness matrix is a regression gate. Modes 0..4 and all are
# manual old-vs-new performance acceptance tools, not per-push gates or speed
# ratchets. The measured five-group data lives in agent-handoff's
# play-c-only-view-report-20261023.md. Keep their toolchain and limits identical.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
MODE=${1:-matrix}
case "$MODE" in matrix|all|0|1|2|3|4) ;; *) echo 'usage: c-only-acceptance.sh matrix|0|1|2|3|4|all' >&2; exit 2;; esac
W=$(mktemp -d)
trap 'rm -rf "${W:?}"' EXIT
mkdir -p "$W/work" "$W/slots"
export PLAY_UNSAFE_LOCAL=1 PLAY_WORK_ROOT="$W/work" PLAY_SLOT_DIR="$W/slots"
export PLAY_PACKAGES="$ROOT/packages" PLAY_COMPILE_TIMEOUT=60 PLAY_TIMEOUT=10
export DAWN_BIN="$ROOT/bin/dawn"
: "${JAVA_HOME:?a JDK is required}"
export PLAY_JAVAP="$ROOT/playground/test/javap-no-perf.sh" PLAY_JAVA="$ROOT/playground/test/java-no-perf.sh"
PLAY_TOOLCHAIN_ID=$("$DAWN_BIN" --version | tail -n 1 | sed -e 's/^dawn //' -e 's/ (selfhost)//')
export PLAY_TOOLCHAIN_ID
DAWNC=$(DAWNC_BIN="${PLAY_TEST_DAWNC:-${DAWNC_BIN:-}}" bash -euc '. site/dawnc.sh; site_dawnc')
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC";; esac
export DAWNC_BIN="$DAWNC"
"$DAWNC" build playground -o "$W/dawn-play"
python3 -I -B playground/test/c-only-matrix.py "$W/dawn-play" "$DAWNC" "$MODE"

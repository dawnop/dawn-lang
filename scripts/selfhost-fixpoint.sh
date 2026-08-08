#!/usr/bin/env bash
# Keep the historical fixed-point gate as a thin compatibility entry point.
# The release artifact and this gate must use the same non-configurable recipe.
set -euo pipefail
cd "$(dirname "$0")/.."

work="$(mktemp -d "${TMPDIR:-/tmp}/selfhost-fixpoint.XXXXXX")"
trap 'rm -rf "$work"' EXIT
./scripts/build-release-jar.sh -o "$work/dawn-selfhost.jar"

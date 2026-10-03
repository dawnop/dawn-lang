#!/usr/bin/env bash
# `dawn doc` for every package under packages/, one JSON document each, into
# <out>/<dir>.json: what gen/packages.dawn reads for packages.html.
#
# Its own file because two callers run it and they must agree on the layout:
# site/build.sh writes into site/build/packages, and scripts/site-dist-diff.sh
# into its snapshot, for the reason it regenerates stdlib.json there (the
# generator only reads files already on disk). A package without a manifest
# is not a package and is skipped, the way gen/packages.package_dirs skips it.
#
# Four at a time: ten packages one after another took 16.9s here on a built
# toolchain, four at a time 8.4s, and a CI runner has four cores. Every run
# writes its own file, so the order they finish in changes nothing.
#
#   site/package-docs.sh <out-dir>     (run from the repository root)
set -euo pipefail
out="${1:?usage: site/package-docs.sh <out-dir>}"
mkdir -p "$out"
for pkg in packages/*/; do
  pkg="${pkg%/}"
  if [ -f "$pkg/dawn.toml" ]; then printf '%s\0' "${pkg#packages/}"; fi
done | xargs -0 -P 4 -I{} sh -c './bin/dawn doc "packages/$1" > "$2/$1.json"' sh {} "$out"

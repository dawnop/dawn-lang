#!/bin/sh
# Runs the runner's test blocks with the native compiler (`dawnc test`): the
# other half of `dawn test playground`, the same tests on the toolchain with
# no JVM, which is the one that builds the binary
# (docs/playground-native-runner-design.md, K3).
#
# Until K5 the runner's modules were a dependency of a separate native entry
# project, and `dawnc test` only tests a project's own modules, so this script
# copied them into a scratch project and left the JVM server's two modules
# out. With the JVM server gone the project is the native entry, and the
# script is the one call. Needs a `dawnc` (DAWNC, default `dawnc` on PATH) and
# `timeout`, `flock`, `head` and `sh`.
set -e
cd "$(dirname "$0")/.."
exec "${DAWNC:-dawnc}" test .

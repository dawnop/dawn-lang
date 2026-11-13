#!/usr/bin/env bash
# Keep actual compiler/backend artifacts and their independent oracles in one
# gate. Performance remains the separately frozen manual benchmark protocol.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
runtime_args=()
if [[ $# -eq 1 && $1 == --reuse-runtime ]]; then
  runtime_args=(--reuse-runtime)
elif [[ $# -ne 0 ]]; then
  echo 'usage: run.sh [--reuse-runtime]' >&2
  exit 2
fi
./bin/dawn --version > /dev/null
work=$(mktemp -d "${TMPDIR:-/tmp}/effect-provenance-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT
python3 scripts/gen-provenance-rt.py --javac "${JAVA_HOME:+$JAVA_HOME/bin/}javac" --check
python3 scripts/effect-provenance-contract/run.py \
  --compiler build/dawn-selfhost.jar --java "${JAVA_HOME:+$JAVA_HOME/bin/}java" \
  --cc "${CC:-cc}" --out "$work/source" "${runtime_args[@]}"
python3 scripts/effect-provenance-contract/runtime.py \
  --java-home "${JAVA_HOME:?JAVA_HOME must name the gate JDK}" --cc "${CC:-cc}"

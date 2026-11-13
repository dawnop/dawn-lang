#!/usr/bin/env bash
# Keep actual compiler/backend artifacts and their independent oracles in one
# gate. Performance remains the separately frozen manual benchmark protocol.
#
# The contract is scheduled in several jobs so that none passes the design
# limit. The owning invocation takes `--except <cases>` and also runs the
# generator check and the runtime probe; each other invocation takes
# `--cases <cases>` and runs just those cases. scheduling_test.py holds the
# union of all invocations in gates.yml equal to the complete case list.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
usage() {
  echo 'usage: run.sh [--reuse-runtime] [--except CASE... | --cases CASE...]' >&2
  exit 2
}
runtime_args=()
mode=all
selector=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --reuse-runtime) runtime_args=(--reuse-runtime); shift ;;
    --except|--cases)
      [[ $mode == all ]] || usage
      mode=${1#--}; shift
      while [[ $# -gt 0 && $1 != --* ]]; do selector+=("$1"); shift; done
      [[ ${#selector[@]} -gt 0 ]] || usage ;;
    *) usage ;;
  esac
done
./bin/dawn --version > /dev/null
work=$(mktemp -d "${TMPDIR:-/tmp}/effect-provenance-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT
case_args=()
[[ $mode == cases ]] && case_args=(--only "${selector[@]}")
[[ $mode == except ]] && case_args=(--except "${selector[@]}")
if [[ $mode != cases ]]; then
  python3 scripts/gen-provenance-rt.py --javac "${JAVA_HOME:+$JAVA_HOME/bin/}javac" --check
fi
python3 scripts/effect-provenance-contract/run.py \
  --compiler build/dawn-selfhost.jar --java "${JAVA_HOME:+$JAVA_HOME/bin/}java" \
  --cc "${CC:-cc}" --out "$work/source" "${runtime_args[@]}" "${case_args[@]}"
if [[ $mode != cases ]]; then
  python3 scripts/effect-provenance-contract/runtime.py \
    --java-home "${JAVA_HOME:?JAVA_HOME must name the gate JDK}" --cc "${CC:-cc}"
fi

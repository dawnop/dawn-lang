#!/usr/bin/env bash
# Run the test blocks of every source package.
#
# Discovery, not a list (GOV-07). The gate this replaced named five packages by
# hand in .github/workflows/gates.yml; the five it named were the five that
# existed, so it was correct and blind at the same time. A sixth package would
# have joined the tree untested, and nothing would have said so -- forgetting to
# extend a list looks exactly like not having written one. The same lesson had
# already been learned for examples/ (scripts/example-tests.sh); this is it
# applied to packages/.
#
# A package is a directory under packages/ with a dawn.toml. playground/ is a
# consumer rather than a package -- it has its own dawn.toml and [deps] onto
# these -- so it is named separately, and that naming is the whole exemption
# list: there is no way to opt a packages/ entry out.
#
# `dawn test` errors on a target with no test blocks rather than passing
# vacuously, so a package that asserts nothing reds here instead of being
# skipped. That is the intended reading of "every package with a suite of its
# own": every package must have one.
set -euo pipefail

cd "$(dirname "$0")/.."

units=()
for m in packages/*/dawn.toml; do
  [ -e "$m" ] || continue
  units+=("$(dirname "$m")")
done

if [ "${#units[@]}" -lt 5 ]; then
  echo "FAIL: found only ${#units[@]} package(s) under packages/; the tree cannot have shrunk that far" >&2
  exit 1
fi

# The consumers: they exercise the packages through [deps], which is a
# different claim from the packages' own suites and worth keeping in the gate.
units+=(playground)

fail=0
for u in "${units[@]}"; do
  echo "== $u"
  if ! ./bin/dawn test "$u"; then
    fail=1
  fi
done

if [ "$fail" != 0 ]; then
  echo "FAIL: a package's test blocks did not pass" >&2
  exit 1
fi
echo "OK: ${#units[@]} package unit(s), every test block run"

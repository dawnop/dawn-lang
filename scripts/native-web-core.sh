#!/usr/bin/env bash
# The native compiler must be able to check and document packages/web whole,
# and this is what says so.
#
# Why it exists. packages/web had 34 `use java` lines, so the native driver
# refused the whole package: `dawnc check`, `doc` and `test` each stopped at the
# first of them, and the site's package page, the ASan run and the native
# services work all carried an exception for it. 7.0 moved the JDK server into
# its own package, packages/web-jvm, and left packages/web pure Dawn
# (docs/web-core-split-design.md). That is a property of the source, and a
# property of the source rots the way every other one does: one `use java`
# added to router.dawn for a convenient JDK call, in a PR whose JVM tests all
# pass, and the package is JVM-only again with nothing red.
#
# What it holds: `dawnc check packages/web` and `dawnc doc packages/web`, the
# whole package as a directory target, both succeed. The JVM server lives
# apart because a directory target loads every module under src/ (spec §10.5),
# so a package with one `use java` cannot be checked natively at all; a
# separate package needs no loader mechanism for it.
#
# And two negative controls, on a copy of the package: a `use java` line added
# to router.dawn, and the JVM server module itself (packages/web-jvm's) copied
# into web/src. Each has to turn `dawnc check` red on the refusal of `use java`
# and on nothing else. A green here that never ran the controls would say
# nothing about whether the gate can see.
#
#   scripts/native-web-core.sh <path to dawnc>
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

DAWNC=${1:?usage: scripts/native-web-core.sh <dawnc>}
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC" ;; esac

OUT=$(mktemp -d "${TMPDIR:-/tmp}/native-web-core.XXXXXX")
trap 'rm -rf "$OUT"' EXIT

REFUSAL='`use java` is not available in this compiler'

echo "== packages/web: the whole package checks and documents natively =="
if ! "$DAWNC" check packages/web > "$OUT/check.txt" 2>&1; then
  head -20 "$OUT/check.txt"
  echo "FAIL: dawnc check packages/web"
  exit 1
fi
if ! "$DAWNC" doc packages/web > "$OUT/doc.json" 2> "$OUT/doc.err"; then
  head -20 "$OUT/doc.err"
  echo "FAIL: dawnc doc packages/web"
  exit 1
fi
# the package that is allowed to name Java must still exist and still do so,
# or the split has nothing to hold
if ! grep -qE '^[[:space:]]*use java' packages/web-jvm/src/server.dawn; then
  echo "FAIL: packages/web-jvm/src/server.dawn has no use java, so the split holds nothing"
  exit 1
fi
echo "OK   dawnc check and dawnc doc accept packages/web as a whole"

fail=0
red_for_java() { # label, dir holding web/ and json/
  local label=$1 dir=$2
  if "$DAWNC" check "$dir/web" > "$OUT/ctl.txt" 2>&1; then
    echo "FAIL: control '$label' did not turn dawnc check red"
    fail=1
  elif grep -qF "$REFUSAL" "$OUT/ctl.txt"; then
    echo "OK   control: $label is refused (use java)"
  else
    head -10 "$OUT/ctl.txt"
    echo "FAIL: control '$label' went red for a reason other than use java"
    fail=1
  fi
}

# Control 1: a core module gets a `use java` line, after its other imports.
mkdir -p "$OUT/c1"
cp -r packages/web packages/json "$OUT/c1/"
sed -i '0,/^use /s//use java "java.lang.System"\nuse /' "$OUT/c1/web/src/router.dawn"
red_for_java "a use java line in router.dawn" "$OUT/c1"

# Control 2: the JVM server module lands in the pure package.
mkdir -p "$OUT/c2"
cp -r packages/web packages/json "$OUT/c2/"
cp packages/web-jvm/src/server.dawn "$OUT/c2/web/src/jvm_copy.dawn"
red_for_java "the JVM server module copied into web/src" "$OUT/c2"

if [ "$fail" != 0 ]; then exit 1; fi
echo "OK   native-web-core: the gate and its two controls"

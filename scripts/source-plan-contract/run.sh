#!/usr/bin/env bash
# The source graph is the only planner for Java coordinates.
#
# Two aliases require two versions of one remote package. The MVS loser names
# a valid but absent Maven coordinate; the winner names an artifact served by
# a file:// repository built below. A cold-cache build of a .dawn file proves
# source fetch happens before coordinate collection, while the lock proves the
# losing manifest never leaks out of the resolver cache.
#
# Everything is local: source archives and the Maven repository are file://
# URLs, and DAWN_MAVEN_MIRROR replaces the default repository list.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work=$(mktemp -d "${TMPDIR:-/tmp}/source-plan-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

compare_compiler_inputs() {
  local expected=$1 actual=$2 label=$3
  if ! cmp -s "$expected" "$actual"; then
    diff -u "$expected" "$actual" >&2 || true
    fail "$label compiler input manifest drifted"
  fi
}

run_jar_exact() {
  local jar_path=$1 label=$2
  if ! java -jar "$jar_path" > "$work/$label.run.out" 2> "$work/$label.run.err"; then
    cat "$work/$label.run.err" >&2
    fail "$label jar did not run"
  fi
  printf 'winner:42\n' > "$work/$label.run.expected"
  if ! cmp -s "$work/$label.run.expected" "$work/$label.run.out" ||
      [ -s "$work/$label.run.err" ]; then
    diff -u "$work/$label.run.expected" "$work/$label.run.out" >&2 || true
    cat "$work/$label.run.err" >&2
    fail "$label jar output was not exactly winner:42"
  fi
}

zip_of() {
  python3 - "$1" "$2" <<'PY'
import os
import sys
import zipfile

source, target = sys.argv[1:]
with zipfile.ZipFile(target, "w") as archive:
    for current, directories, files in os.walk(source):
        directories.sort()
        for name in sorted(files):
            path = os.path.join(current, name)
            archive.write(path, os.path.relpath(path, source))
PY
}

make_package() {
  local dir=$1 version=$2 coord=$3 marker=$4
  mkdir -p "$dir/src"
  cat > "$dir/dawn.toml" <<EOF
schema = 1
name = "lib"
version = "$version"

[java-deps]
java = "$coord"
EOF
  cat > "$dir/src/value.dawn" <<EOF
pub fn marker() -> String = "$marker"
EOF
}

# Initialize the repository toolchain before replacing Maven's repositories.
# The compiler itself legitimately declares ASM; every fixture below is local
# and the Planner inspector has no dependency on the compiler package.
if ! "$dawn" --version > "$work/version.out" 2> "$work/version.err"; then
  cat "$work/version.out" >&2
  cat "$work/version.err" >&2
  fail "$dawn could not initialize the current toolchain"
fi

if ! "$dawn" __source-inputs --base "$root" selfhost \
    > "$work/source-plan.inputs" 2> "$work/source-plan.inputs.err"; then
  cat "$work/source-plan.inputs.err" >&2
  fail "SourcePlan could not list the selfhost compiler inputs"
fi
if [ -s "$work/source-plan.inputs.err" ]; then
  cat "$work/source-plan.inputs.err" >&2
  fail "SourcePlan wrote diagnostics while listing selfhost compiler inputs"
fi
if ! python3 "$root/scripts/gate-map/gatemap.py" --compiler-inputs \
    > "$work/gate-map.inputs" 2> "$work/gate-map.inputs.err"; then
  cat "$work/gate-map.inputs.err" >&2
  fail "gate-map could not derive the selfhost compiler inputs"
fi
if [ -s "$work/gate-map.inputs.err" ]; then
  cat "$work/gate-map.inputs.err" >&2
  fail "gate-map wrote diagnostics while listing selfhost compiler inputs"
fi
compare_compiler_inputs \
  "$work/source-plan.inputs" "$work/gate-map.inputs" "SourcePlan and gate-map"
echo "PASS  SourcePlan and gate-map agree exactly on selfhost compiler inputs"

python3 - "$work/gate-map.inputs" "$work" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
lines = source.read_text(encoding="utf-8").splitlines()
files = [index for index, line in enumerate(lines) if line.startswith("R\tF\t")]
if len(files) < 2:
    raise SystemExit("compiler input negative controls need two required files")

mutants = {}
schema = list(lines)
schema[0] = "dawn-source-inputs-v2"
mutants["schema"] = schema

paths = list(lines)
del paths[files[0]]
mutants["paths"] = paths

kind = list(lines)
kind[files[0]] = kind[files[0]].replace("R\tF\t", "R\tO\t", 1)
mutants["kind"] = kind

order = list(lines)
order[files[0]], order[files[1]] = order[files[1]], order[files[0]]
mutants["order"] = order

for name, mutant in mutants.items():
    (target / f"gate-map.{name}.mutant").write_text(
        "\n".join(mutant) + "\n", encoding="utf-8"
    )
PY
for mutant in schema paths kind order; do
  if (compare_compiler_inputs \
      "$work/source-plan.inputs" "$work/gate-map.$mutant.mutant" "$mutant mutant") \
      > "$work/$mutant.control.out" 2> "$work/$mutant.control.err"; then
    fail "$mutant compiler input mutant did not turn the byte-exact check red"
  fi
done
echo "PASS  compiler input negative controls reject schema, path, kind and order drift"

mkdir -p "$work/java-src/g" "$work/java-classes" "$work/maven/g/selected/1"

# Every contract fixture sees only these temporary caches and the file://
# repository assembled below. No fixture can fall back to the public network
# or a package/Coursier cache left by another checkout.
export DAWN_PKG_CACHE="$work/cache"
export COURSIER_CACHE="$work/coursier-cache"
export DAWN_MAVEN_MIRROR="file://$work/maven"

cat > "$work/java-src/g/Selected.java" <<'JAVA'
package g;

public final class Selected {
    private Selected() {}

    public static long value() {
        return 42L;
    }
}
JAVA
javac --release 17 -d "$work/java-classes" "$work/java-src/g/Selected.java"
jar --create --file "$work/maven/g/selected/1/selected-1.jar" -C "$work/java-classes" .
cat > "$work/maven/g/selected/1/selected-1.pom" <<'POM'
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>g</groupId>
  <artifactId>selected</artifactId>
  <version>1</version>
</project>
POM

make_package "$work/lib-1.0" 1.0.0 g:poison:1 loser
make_package "$work/lib-1.1" 1.1.0 g:selected:1 winner
zip_of "$work/lib-1.0" "$work/lib-1.0.zip"
zip_of "$work/lib-1.1" "$work/lib-1.1.zip"
hash_10=$("$dawn" __pkghash "$work/lib-1.0" 2>/dev/null)
hash_11=$("$dawn" __pkghash "$work/lib-1.1" 2>/dev/null)
case "$hash_10:$hash_11" in
  d1:*:d1:*) ;;
  *) fail "$dawn did not produce package hashes" ;;
esac

mkdir -p "$work/app/src"
cat > "$work/app/dawn.toml" <<EOF
schema = 1
name = "source_plan_app"

[deps.z_old]
url = "file://$work/lib-1.0.zip"
version = "1.0.0"
hash = "$hash_10"

[deps.a_new]
url = "file://$work/lib-1.1.zip"
version = "1.1.0"
hash = "$hash_11"
EOF
cat > "$work/app/src/main.dawn" <<'DAWN'
use java "g.Selected"
use a_new/value

pub fn main() -> Unit !io = println(value.marker() ++ ":" ++ to_string(Selected.value()))
DAWN

"$dawn" build "$work/app/src/main.dawn" -o "$work/cold.jar" > "$work/cold.out" 2>&1 || {
  cat "$work/cold.out" >&2
  fail "cold-cache file target did not build"
}
run_jar_exact "$work/cold.jar" cold
echo "PASS  cold-cache file target runs the MVS winner"

# Inspect the real public SourcePlan through a temporary Dawn program. This is
# deliberately not inferred from lock text (lock coordinates are sorted): the
# observed list must preserve the mixed TOML declaration order itself, while
# the root manifest's Java coordinate remains first.
mkdir -p "$work/order-path/src" "$work/order-url-first/src" \
  "$work/order-path-first/src" "$work/inspector/src"
cat > "$work/order-path/dawn.toml" <<'EOF'
schema = 1
name = "path_order"

[java-deps]
path = "g:path:1"
EOF
cat > "$work/order-path/src/value.dawn" <<'DAWN'
pub fn marker() -> String = "path"
DAWN
cat > "$work/order-url-first/src/main.dawn" <<'DAWN'
pub fn main() -> Unit = ()
DAWN
cat > "$work/order-path-first/src/main.dawn" <<'DAWN'
pub fn main() -> Unit = ()
DAWN
cat > "$work/order-url-first/dawn.toml" <<EOF
schema = 1
name = "order_url_first"

[java-deps]
root = "g:root:1"

[deps.remote]
url = "file://$work/lib-1.1.zip"
version = "1.1.0"
hash = "$hash_11"

[deps]
local = "../order-path"
EOF
cat > "$work/order-path-first/dawn.toml" <<EOF
schema = 1
name = "order_path_first"

[java-deps]
root = "g:root:1"

[deps]
local = "../order-path"

[deps.remote]
url = "file://$work/lib-1.1.zip"
version = "1.1.0"
hash = "$hash_11"
EOF
python3 - "$root/scripts/source-plan-contract/fixtures/inspector/dawn.toml.in" \
    "$work/inspector/dawn.toml" "$root/compiler-plan" <<'PY'
import pathlib
import sys

source, target, compiler_plan = sys.argv[1:]
text = pathlib.Path(source).read_text()
if text.count("@COMPILER_PLAN@") != 1:
    raise SystemExit("inspector manifest must contain one @COMPILER_PLAN@ placeholder")
pathlib.Path(target).write_text(text.replace("@COMPILER_PLAN@", compiler_plan))
PY
cp "$root/scripts/source-plan-contract/fixtures/inspector/src/main.dawn" \
  "$work/inspector/src/main.dawn"
if ! python3 - "$root/compiler-plan/dawn.toml" "$work/inspector/dawn.toml" \
    "$root/compiler-plan" <<'PY'
import pathlib
import sys
import tomllib

planner_name, inspector_name, planner_path = sys.argv[1:]

with pathlib.Path(planner_name).open("rb") as source:
    planner = tomllib.load(source)
with pathlib.Path(inspector_name).open("rb") as source:
    inspector = tomllib.load(source)

expected_planner_deps = {
    "fspath": "../packages/fspath",
    "sha2": "../packages/sha2",
    "inflate": "../packages/inflate",
}
if planner.get("deps") != expected_planner_deps:
    raise SystemExit(
        "compiler-plan dependencies must remain exactly fspath, sha2, and inflate"
    )
if "java-deps" in planner:
    raise SystemExit("compiler-plan must not declare Java dependencies")
if inspector.get("deps") != {"compiler_plan": planner_path}:
    raise SystemExit("SourcePlan inspector must depend only on compiler-plan")
if "java-deps" in inspector:
    raise SystemExit("SourcePlan inspector must not declare Java dependencies")
PY
then
  fail "Planner package dependency boundary drifted"
fi
if grep -R -n '^use java' "$root/compiler-plan/src"; then
  fail "compiler-plan acquired a Java dependency"
fi
echo "PASS  Planner and its inspector are independent of compiler Java dependencies"
cat > "$work/order.expected" <<'EOF'
url-first
g:root:1
g:selected:1
g:path:1
path-first
g:root:1
g:path:1
g:selected:1
EOF
"$dawn" run "$work/inspector" -- "$work/order-url-first" "$work/order-path-first" \
    > "$work/order.out" 2> "$work/order.err" || {
  cat "$work/order.err" >&2
  fail "SourcePlan order inspector failed"
}
if ! cmp -s "$work/order.expected" "$work/order.out"; then
  diff -u "$work/order.expected" "$work/order.out" >&2 || true
  fail "SourcePlan did not preserve mixed manifest declaration order"
fi
echo "PASS  SourcePlan preserves both mixed dependency orders root-first"

# A content hash may have several legitimate origins. The first mirror is
# unavailable and must be diagnosed only provisionally: the second URL serves
# the declared bytes, so both the cold parent plan and warm re-exec plan must
# succeed without retaining the first transport error.
mkdir -p "$work/mirror-app/src"
cat > "$work/mirror-app/dawn.toml" <<EOF
schema = 1
name = "mirror_app"

[deps.bad]
url = "file://$work/no-such-mirror.zip"
version = "1.1.0"
hash = "$hash_11"

[deps.good]
url = "file://$work/lib-1.1.zip"
version = "1.1.0"
hash = "$hash_11"
EOF
cat > "$work/mirror-app/src/main.dawn" <<'DAWN'
use good/value

pub fn main() -> Unit !io = println(value.marker())
DAWN
if ! DAWN_PKG_CACHE="$work/mirror-cache" \
    "$dawn" run "$work/mirror-app" > "$work/mirror.out" 2> "$work/mirror.err"; then
  cat "$work/mirror.err" >&2
  fail "a bad first mirror suppressed the good second mirror"
fi
printf 'winner\n' > "$work/mirror.expected"
if ! cmp -s "$work/mirror.expected" "$work/mirror.out"; then
  diff -u "$work/mirror.expected" "$work/mirror.out" >&2 || true
  fail "the good second mirror did not supply the selected package"
fi
if grep -q '^error:' "$work/mirror.err"; then
  cat "$work/mirror.err" >&2
  fail "a recovered mirror failure remained diagnostic"
fi
echo "PASS  a good second mirror recovers the same content hash"

rm "$work/lib-1.0.zip" "$work/lib-1.1.zip"
"$dawn" build "$work/app/src/main.dawn" -o "$work/warm.jar" > "$work/warm.out" 2>&1 || {
  cat "$work/warm.out" >&2
  fail "warm-cache file target did not build"
}
run_jar_exact "$work/warm.jar" warm
echo "PASS  warm-cache file target runs the same MVS winner"

"$dawn" lock "$work/app" > "$work/lock.out" 2>&1 || {
  cat "$work/lock.out" >&2
  fail "lock generation failed"
}
grep -qx 'coord g:selected:1' "$work/app/dawn.lock" || fail "winner coordinate missing from lock"
if grep -q 'g:poison:1' "$work/app/dawn.lock"; then
  fail "MVS loser coordinate leaked into lock"
fi
if [ "$(grep -c '^coord ' "$work/app/dawn.lock")" -ne 1 ]; then
  fail "lock contains coordinates outside the selected source graph"
fi
echo "PASS  lock contains only the MVS winner"

# One unavailable archive appears under two aliases/subdirs and is revisited
# during winner resolution. The isolated cache ensures the fixed test hash can
# never collide with a real ~/.dawn entry; one failed fetch must yield one
# diagnostic across all aliases and phases.
mkdir -p "$work/failure-app"
failure_hash=d1:0000000000000000000000000000000000000000000000000000000000000000
cat > "$work/failure-app/dawn.toml" <<EOF
schema = 1
name = "failure_app"

[deps.first]
url = "file://$work/no-such-archive.zip"
version = "1.0.0"
hash = "$failure_hash"
subdir = "one"

[deps.second]
url = "file://$work/no-such-archive.zip"
version = "1.0.0"
hash = "$failure_hash"
subdir = "two"
EOF
if DAWN_PKG_CACHE="$work/failure-cache" \
    "$dawn" lock "$work/failure-app" > "$work/failure.out" 2>&1; then
  fail "missing source archive unexpectedly resolved"
fi
failure_diags=$(grep -c '^error: package `' "$work/failure.out" || true)
if [ "$failure_diags" -ne 1 ]; then
  cat "$work/failure.out" >&2
  fail "one archive failure produced $failure_diags diagnostics"
fi
echo "PASS  archive failure is reported once across aliases and phases"

test ! -e "$root/selfhost/src/pkg/manifest.dawn" || fail "light manifest parser still exists"
if grep -q 'pkg\.manifest\.core' "$root/scripts/core-golden/selfhost.sha" \
    "$root/scripts/core-golden/selfhost.norm.sha"; then
  fail "deleted light manifest module remains in the Core baseline"
fi
for forbidden in \
  'type Coord' \
  'parse_coord' \
  'collect_java_deps' \
  'fn dep_root' \
  'fn walk_pkg' \
  'to_lite' \
  'ver_parts' \
  'ver_lt'; do
  if grep -R -n -F "$forbidden" \
      "$root/selfhost/src/driver/analyze.dawn" "$root/selfhost/src/pkg/maven.dawn"; then
    fail "duplicate planner helper remains: $forbidden"
  fi
done
echo "PASS  duplicate parser and graph helpers are absent"

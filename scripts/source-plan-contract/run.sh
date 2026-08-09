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

make_asm_fixture() {
  python3 - "$1" "$2" <<'PY'
import sys
import zipfile

source, target = sys.argv[1:]
prefix = "org/objectweb/asm/"
sentinel = prefix + "Opcodes.class"

try:
    with zipfile.ZipFile(source) as source_jar:
        entries = sorted(
            {
                name for name in source_jar.namelist()
                if name.startswith(prefix) and name.endswith(".class")
            }
        )
        if sentinel not in entries:
            print(f"current toolchain jar is missing {sentinel}", file=sys.stderr)
            raise SystemExit(1)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as fixture:
            for name in entries:
                fixture.writestr(name, source_jar.read(name))
except (OSError, zipfile.BadZipFile) as error:
    print(f"cannot read current toolchain jar: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
}

relock_asm_fixture() {
  python3 - "$1" "$2" <<'PY'
import hashlib
import pathlib
import re
import sys

fixture_name, lock_name = sys.argv[1:]
fixture = pathlib.Path(fixture_name)
lock = pathlib.Path(lock_name)
digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
text = lock.read_text()
updated, count = re.subn(
    r"(?m)^artifact [0-9a-f]{64}  asm-9\.7\.1\.jar$",
    f"artifact {digest}  asm-9.7.1.jar",
    text,
)
if count != 1:
    print(f"ASM artifact lock entry occurs {count} times in {lock}", file=sys.stderr)
    raise SystemExit(1)
lock.write_text(updated)
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

toolchain_jar="$root/build/dawn-selfhost.jar"
if ! "$dawn" --version > "$work/version.out" 2> "$work/version.err"; then
  cat "$work/version.out" >&2
  cat "$work/version.err" >&2
  fail "$dawn could not initialize the current toolchain"
fi
test -f "$toolchain_jar" || fail "current toolchain jar is missing after $dawn --version"

mkdir -p "$work/java-src/g" "$work/java-classes" "$work/maven/g/selected/1" \
  "$work/maven/org/ow2/asm/asm/9.7.1"
asm_fixture="$work/maven/org/ow2/asm/asm/9.7.1/asm-9.7.1.jar"
if ! make_asm_fixture "$toolchain_jar" "$asm_fixture"; then
  fail "could not build an ASM fixture from $toolchain_jar"
fi
cat > "$work/maven/org/ow2/asm/asm/9.7.1/asm-9.7.1.pom" <<'POM'
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.ow2.asm</groupId>
  <artifactId>asm</artifactId>
  <version>9.7.1</version>
</project>
POM

# Isolate both source and Maven caches only after the current toolchain has
# supplied the local ASM fixture. Every contract invocation below sees only
# this file:// mirror and cannot fall back to the public network or ~/.dawn.
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
cat > "$work/inspector/dawn.toml" <<EOF
schema = 1
name = "source_plan_inspector"

[deps]
compiler = "$root/selfhost"
EOF
cat > "$work/inspector/src/main.dawn" <<EOF
use compiler/driver/analyze.{source_plan}
use compiler/pkg/manifestv.{mcoord_show}

fn show(label: String, target: String) -> Unit !io = {
  println(label)
  let plan = source_plan(target)
  if len(plan.diags) != 0 { panic("unexpected SourcePlan diagnostics") }
  for coord in plan.java_coords { println(mcoord_show(coord)) }
}

pub fn main() -> Unit !io = {
  show("url-first", "$work/order-url-first")
  show("path-first", "$work/order-path-first")
}
EOF
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
"$dawn" run "$work/inspector" > "$work/order.out" 2> "$work/order.err" || {
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

# Bootstrap input-manifest producer.
input_root="$work/input-manifest"
input_base="$input_root/repo"
input_app="$input_base/app"
input_alpha="$input_base/pkg-alpha"
input_charlie="$input_base/pkg-charlie"
input_shared="$input_root/external/shared"
mkdir -p "$input_app/src" "$input_alpha/src" "$input_charlie/src" "$input_shared/src"
cat > "$input_app/dawn.toml" <<'EOF'
schema = 1
name = "input_app"

[deps]
alpha = "../pkg-alpha"
charlie = "../pkg-charlie"
EOF
cat > "$input_app/src/main.dawn" <<'DAWN'
pub fn main() -> Unit = ()
DAWN
cat > "$input_alpha/dawn.toml" <<'EOF'
schema = 1
name = "alpha"

[deps]
shared = "../../external/shared"
EOF
cat > "$input_alpha/src/value.dawn" <<'DAWN'
pub fn alpha() -> Int = 1
DAWN
cat > "$input_charlie/dawn.toml" <<'EOF'
schema = 1
name = "charlie"

[deps]
shared = "../../external/shared"
EOF
cat > "$input_charlie/src/value.dawn" <<'DAWN'
pub fn charlie() -> Int = 3
DAWN
cat > "$input_shared/dawn.toml" <<'EOF'
schema = 1
name = "shared"
EOF
cat > "$input_shared/src/value.dawn" <<'DAWN'
pub fn shared() -> Int = 2
DAWN

cat > "$work/inputs.expected" <<EOF
dawn-source-inputs-v1
A	F	$input_shared/dawn.toml
A	T	$input_shared/src
R	F	app/dawn.toml
R	F	pkg-alpha/dawn.toml
R	F	pkg-charlie/dawn.toml
R	O	app/dawn.lock
R	T	app/src
R	T	pkg-alpha/src
R	T	pkg-charlie/src
EOF

run_input_manifest() {
  local compiler=$1 base=$2 target=$3 output=$4
  if [[ "$compiler" == *.jar ]]; then
    java -Xss512m -Xmx2g -jar "$compiler" __source-inputs --base "$base" "$target" \
      > "$output.out" 2> "$output.err"
  else
    "$compiler" __source-inputs --base "$base" "$target" \
      > "$output.out" 2> "$output.err"
  fi
}

if ! run_input_manifest "$dawn" "$input_base" "$input_app" "$work/inputs"; then
  cat "$work/inputs.err" >&2
  fail "source input manifest command failed"
fi
if ! cmp -s "$work/inputs.expected" "$work/inputs.out" || [ -s "$work/inputs.err" ]; then
  diff -u "$work/inputs.expected" "$work/inputs.out" >&2 || true
  cat "$work/inputs.err" >&2
  fail "source input manifest did not match the selected recursive graph"
fi
if [ "$(grep -Fxc $'A\tF\t'"$input_shared/dawn.toml" "$work/inputs.out")" -ne 1 ] ||
    [ "$(grep -Fxc $'A\tT\t'"$input_shared/src" "$work/inputs.out")" -ne 1 ]; then
  fail "diamond package root was not emitted exactly once"
fi
grep -Fqx $'R\tO\tapp/dawn.lock' "$work/inputs.out" ||
  fail "missing optional dawn.lock record"
echo "PASS  source input manifest is recursive, typed, and diamond-deduplicated"

moved_base="$input_root/moved-repo"
cp -R "$input_base" "$moved_base"
if ! run_input_manifest "$dawn" "$moved_base" "$moved_base/app" "$work/moved-inputs"; then
  cat "$work/moved-inputs.err" >&2
  fail "moved source input manifest command failed"
fi
if ! cmp -s "$work/inputs.expected" "$work/moved-inputs.out" ||
    [ -s "$work/moved-inputs.err" ]; then
  diff -u "$work/inputs.expected" "$work/moved-inputs.out" >&2 || true
  cat "$work/moved-inputs.err" >&2
  fail "repo-local source inputs retained an absolute checkout path"
fi
if grep -Fq "$input_base/" "$work/moved-inputs.out"; then
  fail "moved manifest still names the old checkout"
fi
echo "PASS  repo-local source inputs survive checkout relocation"

direct_base="$input_root/direct-file"
direct_file="$direct_base/project/src/main.dawn"
mkdir -p "$direct_base/project/src"
cat > "$direct_base/project/dawn.toml" <<'EOF'
schema = "invalid if planning is reached"
name = "direct_file"
EOF
cat > "$direct_file" <<'DAWN'
pub fn main() -> Unit = ()
DAWN
set +e
run_input_manifest "$dawn" "$direct_base" "$direct_file" "$work/direct-file"
direct_rc=$?
set -e
if [ "$direct_rc" -ne 2 ]; then
  cat "$work/direct-file.err" >&2
  fail "direct-file source input rejection exited $direct_rc instead of 2"
fi
test ! -s "$work/direct-file.out" || fail "direct-file rejection wrote stdout"
printf 'error: __source-inputs requires a project directory: %s\n' \
  "$direct_file" > "$work/direct-file.expected"
if ! cmp -s "$work/direct-file.expected" "$work/direct-file.err"; then
  diff -u "$work/direct-file.expected" "$work/direct-file.err" >&2 || true
  fail "direct-file source input rejection drifted or reached SourcePlan"
fi
echo "PASS  source input manifest rejects direct files before planning"

expect_input_failure() {
  local label=$1 base=$2 target=$3 expected=$4
  if run_input_manifest "$dawn" "$base" "$target" "$work/failure-$label"; then
    fail "$label input manifest unexpectedly succeeded"
  fi
  if [ -s "$work/failure-$label.out" ]; then
    cat "$work/failure-$label.out" >&2
    fail "$label input failure leaked a partial manifest"
  fi
  printf '%s\n' "$expected" > "$work/failure-$label.expected"
  if ! cmp -s "$work/failure-$label.expected" "$work/failure-$label.err"; then
    diff -u "$work/failure-$label.expected" "$work/failure-$label.err" >&2 || true
    fail "$label input failure diagnostic drifted"
  fi
}

newline_path="$input_app/src/bad
name.dawn"
printf 'not parsed\n' > "$newline_path"
expect_input_failure newline "$input_base" "$input_app" \
  "error: source input path contains LF: $input_app/src/bad\\nname.dawn"
rm "$newline_path"

ln -s main.dawn "$input_app/src/link.dawn"
expect_input_failure symlink "$input_base" "$input_app" \
  "error: source input path crosses a symbolic link: $input_app/src/link.dawn"
rm "$input_app/src/link.dawn"

mkdir -p "$input_root/wrong-type/app"
cat > "$input_root/wrong-type/app/dawn.toml" <<'EOF'
schema = 1
name = "wrong_type"
EOF
printf 'not a directory\n' > "$input_root/wrong-type/app/src"
expect_input_failure wrong-type "$input_root/wrong-type" "$input_root/wrong-type/app" \
  "error: source input must be a directory tree: $input_root/wrong-type/app/src"

mkdir -p "$input_root/unreadable/app/src/blocked"
cat > "$input_root/unreadable/app/dawn.toml" <<'EOF'
schema = 1
name = "unreadable"
EOF
printf 'hidden\n' > "$input_root/unreadable/app/src/blocked/value.dawn"
chmod 000 "$input_root/unreadable/app/src/blocked"
if run_input_manifest "$dawn" "$input_root/unreadable" "$input_root/unreadable/app" \
    "$work/failure-traversal"; then
  chmod 700 "$input_root/unreadable/app/src/blocked"
  fail "unreadable input tree unexpectedly produced a manifest"
fi
chmod 700 "$input_root/unreadable/app/src/blocked"
test ! -s "$work/failure-traversal.out" || fail "traversal failure leaked a partial manifest"
printf 'error: source input tree cannot be traversed: %s\n' \
  "$input_root/unreadable/app/src/blocked" > "$work/failure-traversal.expected"
if ! cmp -s "$work/failure-traversal.expected" "$work/failure-traversal.err"; then
  diff -u "$work/failure-traversal.expected" "$work/failure-traversal.err" >&2 || true
  fail "traversal failure diagnostic drifted"
fi
echo "PASS  source input manifest fails closed before stdout"

if "$dawn" --help | grep -q '__source-inputs'; then
  fail "bootstrap source input command leaked into public help"
fi
echo "PASS  source input manifest command remains hidden"

mutate_source_inputs() {
  python3 - "$1" "$2" <<'PY'
import pathlib
import sys

mutation, name = sys.argv[1:]
path = pathlib.Path(name)
text = path.read_text()

if mutation == "drop-deps-recursion":
    old = '''  for key in map.keys(pkg.deps) {
    let child = map.get(pkg.deps, key).expect("resolved package")
    let (next, visited) = collect_source_pkg_inputs(child, inputs, seen)
    inputs = next
    seen = visited
  }
  (inputs, seen)
'''
    new = '''  (inputs, seen)
'''
elif mutation == "drop-package-manifest":
    old = '''    SourceInput { kind: InputFile, path: parent ++ "/dawn.toml" },
    SourceInput { kind: InputTree, path: root }
'''
    new = '''    SourceInput { kind: InputTree, path: root }
'''
elif mutation == "persist-internal-absolute":
    old = '''      if str.starts_with(input.path, prefix) {
        ("R", str.drop(input.path, str.len(prefix)))
      } else {
        ("A", input.path)
      }
'''
    new = '''      if str.starts_with(input.path, prefix) {
        ("A", input.path)
      } else {
        ("A", input.path)
      }
'''
else:
    raise SystemExit(f"unknown mutation: {mutation}")

count = text.count(old)
if count != 1:
    raise SystemExit(f"{mutation} anchor occurs {count} times")
path.write_text(text.replace(old, new))
PY
}

expect_input_mutant_red() {
  local mutation=$1 mutant="$work/mutant-$1" output="$work/mutant-$1.manifest"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/packages" "$mutant/packages"
  if ! relock_asm_fixture "$asm_fixture" "$mutant/selfhost/dawn.lock"; then
    fail "$mutation mutant lock could not adopt the local ASM fixture"
  fi
  mutate_source_inputs "$mutation" "$mutant/selfhost/src/driver/analyze.dawn"
  if ! "$dawn" build "$mutant/selfhost" -o "$mutant/compiler.jar" --std "$root/std" \
      > "$mutant/build.out" 2>&1; then
    cat "$mutant/build.out" >&2
    fail "$mutation mutant did not compile"
  fi
  if ! run_input_manifest "$mutant/compiler.jar" "$input_base" "$input_app" "$output"; then
    cat "$output.err" >&2
    fail "$mutation mutant did not execute the source input command"
  fi
  if cmp -s "$work/inputs.expected" "$output.out"; then
    fail "$mutation mutant stayed green"
  fi
  if [ -s "$output.err" ]; then
    cat "$output.err" >&2
    fail "$mutation mutant failed outside its owning contract"
  fi
  case "$mutation" in
    drop-deps-recursion)
      if grep -Fqx $'A\tF\t'"$input_shared/dawn.toml" "$output.out"; then
        fail "$mutation mutant still emitted the transitive package manifest"
      fi
      ;;
    drop-package-manifest)
      if grep -Fqx $'R\tF\tpkg-alpha/dawn.toml' "$output.out"; then
        fail "$mutation mutant still emitted the package manifest"
      fi
      ;;
    persist-internal-absolute)
      if grep -Fqx $'R\tF\tapp/dawn.toml' "$output.out" ||
          ! grep -Fqx $'A\tF\t'"$input_app/dawn.toml" "$output.out"; then
        fail "$mutation mutant missed the repo-relative scope boundary"
      fi
      ;;
  esac
  echo "PASS  $mutation mutant compiles and turns its input-manifest contract red"
}

expect_input_mutant_red drop-deps-recursion
expect_input_mutant_red drop-package-manifest
expect_input_mutant_red persist-internal-absolute

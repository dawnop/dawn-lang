#!/usr/bin/env bash
# Target-scoped Java classpath and lock contracts for JVM check/doc. Fixture
# jars and the file:// Maven repository are rebuilt from tracked Java sources;
# after the compiler bootstrap, every subject uses private package and Coursier
# caches and cannot reach a public repository. The native driver is compiled
# from tracked C/runtime sources and must not touch Coursier at all.
#
# `__check` is intentionally outside this slice: it remains the internal
# previous-release golden path and continues to use the compiler system loader.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/java-target-classpath-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work="$(mktemp -d "${TMPDIR:-/tmp}/java-target-classpath-contract.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "java-target-classpath-contract: $*" >&2
  exit 1
}

for command in javac jar java cc python3; do
  command -v "$command" > /dev/null || fail "missing required command: $command"
done

sha256_file() {
  if command -v sha256sum > /dev/null; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum > /dev/null; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    fail "no SHA-256 command available"
  fi
}

# Bootstrap is the test runner, not a fixture dependency. Once it is current,
# all Maven lookups below are forced through the repository built in $work.
if ! "$dawn" --version > "$work/version.out" 2> "$work/version.err"; then
  cat "$work/version.out" >&2
  cat "$work/version.err" >&2
  fail "current compiler did not initialize"
fi

if ! "$dawn" __emitc "$root/selfhost/src/nmain.dawn" -o "$work/nmain.c" \
    > "$work/native-build.out" 2> "$work/native-build.err"; then
  cat "$work/native-build.out" >&2
  cat "$work/native-build.err" >&2
  fail "native driver C emission failed"
fi
if ! cc -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" -o "$work/dawnc" "$work/nmain.c" \
    "$root/runtime/c/dawn_rt.c" -lm > "$work/native-cc.out" 2>&1; then
  cat "$work/native-cc.out" >&2
  fail "native driver C compilation failed"
fi

repo="$work/maven"
build_fixture() {
  local name=$1
  local artifact="api-$name"
  local classes="$work/classes-$name"
  local target="$repo/fixture/$artifact/1"
  mkdir -p "$classes" "$target"
  javac --release 17 -d "$classes" "$here/fixtures/$name/src/fixture/Shared.java"
  jar --create --file "$target/$artifact-1.jar" -C "$classes" .
  cat > "$target/$artifact-1.pom" <<EOF
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>fixture</groupId>
  <artifactId>$artifact</artifactId>
  <version>1</version>
</project>
EOF
}

build_asm_fixture() {
  local classes="$work/classes-asm"
  local target="$repo/fixture/asm-stub/1"
  mkdir -p "$classes" "$target"
  javac --release 17 -d "$classes" \
    "$here/fixtures/asm/src/org/objectweb/asm/ClassWriter.java" \
    "$here/fixtures/asm/src/org/objectweb/asm/FieldVisitor.java" \
    "$here/fixtures/asm/src/org/objectweb/asm/MethodVisitor.java"
  jar --create --file "$target/asm-stub-1.jar" -C "$classes" .
  cat > "$target/asm-stub-1.pom" <<'EOF'
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>fixture</groupId>
  <artifactId>asm-stub</artifactId>
  <version>1</version>
</project>
EOF
}

build_fixture a
build_fixture b
build_asm_fixture

export DAWN_PKG_CACHE="$work/package-cache"
export COURSIER_CACHE="$work/coursier-cache"
export DAWN_MAVEN_MIRROR="file://$repo"
# Private compiler builds vendor the compiler APIs out of the already-running
# toolchain. This marker prevents build/run/test's retained re-exec path from
# resolving the private selfhost manifest against the fixture-only repository.
export DAWN_SELFHOST_CP=""

write_lock() {
  local project=$1 coordinate=$2 jar_path=$3
  cat > "$project/dawn.lock" <<EOF
schema 1
coord $coordinate
artifact $(sha256_file "$jar_path")  $(basename "$jar_path")
EOF
}

make_java_project() {
  local name=$1 method=$2
  local project="$work/app-$name"
  local artifact="api-$name"
  local cap
  cap=$(printf '%s' "$name" | tr 'ab' 'AB')
  mkdir -p "$project/src"
  cat > "$project/dawn.toml" <<EOF
schema = 1
name = "app_$name"

[java-deps]
api = "fixture:$artifact:1"
EOF
  cat > "$project/src/main.dawn" <<EOF
use java "fixture.Shared"

pub fn $method() -> Int !io = Shared.only$cap()

pub fn main() -> Unit !io = ()
EOF
  write_lock "$project" "fixture:$artifact:1" "$repo/fixture/$artifact/1/$artifact-1.jar"
}

make_java_project a call_a
make_java_project b call_b

mkdir -p "$work/bridge/src"
cat > "$work/bridge/dawn.toml" <<'EOF'
schema = 1
name = "bridge_app"

[java-deps]
asm = "fixture:asm-stub:1"
EOF
cat > "$work/bridge/src/main.dawn" <<'EOF'
use java "dawn.rt.Asm"
use java "dawn.rt.AsmWriter"

pub fn exercise_bridges() -> Unit !io = {
  let flags = AsmWriter.COMPUTE_FRAMES
  let writer = Asm.plain(flags).expect("plain writer")
  Asm.beginOn(writer, 52, 1, "fixture/Generated", "java/lang/Object")
  let _ = Asm.methodOn(writer, 1, "run", "()V").expect("method visitor")
  let supers: List[String] = []
  let _ = AsmWriter.of(flags, supers).expect("frame writer")
  ()
}

pub fn main() -> Unit !io = exercise_bridges()
EOF
write_lock "$work/bridge" "fixture:asm-stub:1" \
  "$repo/fixture/asm-stub/1/asm-stub-1.jar"

mkdir -p "$work/jdk/src" "$work/asm/src" "$work/coursier/src" "$work/bridge-no-asm/src"
for name in jdk asm coursier; do
  cat > "$work/$name/dawn.toml" <<EOF
schema = 1
name = "$name"
EOF
done
cat > "$work/jdk/src/main.dawn" <<'EOF'
use java "java.lang.String"

pub fn main() -> Unit !io = {
  let _ = String.valueOf(1)
  ()
}
EOF
cat > "$work/asm/src/main.dawn" <<'EOF'
use java "org.objectweb.asm.ClassWriter"

pub fn main() -> Unit !io = ()
EOF
cat > "$work/coursier/src/main.dawn" <<'EOF'
use java "coursierapi.Fetch"

pub fn main() -> Unit !io = ()
EOF
cat > "$work/bridge-no-asm/dawn.toml" <<'EOF'
schema = 1
name = "bridge_no_asm"
EOF
cat > "$work/bridge-no-asm/src/main.dawn" <<'EOF'
use java "dawn.rt.Asm"
use java "dawn.rt.AsmWriter"

pub fn main() -> Unit !io = ()
EOF

CAPTURE_STATUS=0
capture() {
  local label=$1
  shift
  set +e
  "$@" > "$work/$label.out" 2> "$work/$label.err"
  CAPTURE_STATUS=$?
  set -e
}

expect_no_resolving() {
  local label=$1
  if grep -Fq 'resolving ' "$work/$label.out" "$work/$label.err"; then
    cat "$work/$label.out" >&2
    cat "$work/$label.err" >&2
    fail "$label printed dependency-resolution progress"
  fi
}

capture multi-check "$dawn" check "$work/app-a" "$work/app-b"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ "$(cat "$work/multi-check.out")" != "ok" ] ||
    [ -s "$work/multi-check.err" ]; then
  cat "$work/multi-check.out" >&2
  cat "$work/multi-check.err" >&2
  fail "target-local multi-target check failed"
fi
expect_no_resolving multi-check
echo "PASS  one check invocation isolates same-FQCN target dependencies"

capture target-doc "$dawn" doc "$work/app-a"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ -s "$work/target-doc.err" ]; then
  cat "$work/target-doc.out" >&2
  cat "$work/target-doc.err" >&2
  fail "doc did not resolve the target dependency cleanly"
fi
python3 - "$work/target-doc.out" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    data = json.load(stream)
names = [fn["name"] for module in data["modules"] for fn in module["fns"]]
if "call_a" not in names:
    raise SystemExit("target-doc JSON omitted call_a")
PY
expect_no_resolving target-doc
echo "PASS  doc resolves target dependencies without progress output"

capture bridge-check "$dawn" check "$work/bridge"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ "$(cat "$work/bridge-check.out")" != "ok" ] ||
    [ -s "$work/bridge-check.err" ]; then
  cat "$work/bridge-check.out" >&2
  cat "$work/bridge-check.err" >&2
  fail "target ASM did not expose the two generated bridge signatures"
fi
expect_no_resolving bridge-check

capture bridge-build env -u DAWN_SELFHOST_CP "$dawn" build "$work/bridge" -o "$work/bridge.jar"
if [ "$CAPTURE_STATUS" -ne 0 ]; then
  cat "$work/bridge-build.out" >&2
  cat "$work/bridge-build.err" >&2
  fail "bridge-importing target did not build"
fi
jar tf "$work/bridge.jar" > "$work/bridge.entries"
for entry in dawn/rt/Asm.class dawn/rt/AsmWriter.class; do
  if [ "$(grep -Fxc "$entry" "$work/bridge.entries")" -ne 1 ]; then
    cat "$work/bridge.entries" >&2
    fail "bridge-importing target jar did not contain exactly one $entry"
  fi
done
capture bridge-run java -jar "$work/bridge.jar"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ -s "$work/bridge-run.err" ]; then
  cat "$work/bridge-run.out" >&2
  cat "$work/bridge-run.err" >&2
  fail "bridge-importing target jar did not link and run"
fi
echo "PASS  target ASM exposes bridge calls and emits a linked standalone jar"

capture jdk-only env COURSIER_CACHE="$work/empty-jdk-cache" "$dawn" check "$work/jdk"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ "$(cat "$work/jdk-only.out")" != "ok" ] ||
    [ -s "$work/jdk-only.err" ] || [ -e "$work/empty-jdk-cache" ]; then
  cat "$work/jdk-only.out" >&2
  cat "$work/jdk-only.err" >&2
  fail "zero-jar platform parent did not expose exactly the JDK"
fi

capture compiler-leak env COURSIER_CACHE="$work/empty-leak-cache" \
  "$dawn" check "$work/asm" "$work/coursier"
if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/compiler-leak.out" ] ||
    [ "$(grep -Fc 'Java class not found:' "$work/compiler-leak.err")" -ne 2 ] ||
    ! grep -Fq 'Java class not found: org.objectweb.asm.ClassWriter' "$work/compiler-leak.err" ||
    ! grep -Fq 'Java class not found: coursierapi.Fetch' "$work/compiler-leak.err" ||
    [ -e "$work/empty-leak-cache" ]; then
  cat "$work/compiler-leak.out" >&2
  cat "$work/compiler-leak.err" >&2
  fail "zero-jar target leaked the compiler application classpath"
fi
echo "PASS  empty targets see JDK classes but not compiler ASM/Coursier"

capture bridge-hidden env COURSIER_CACHE="$work/empty-bridge-cache" \
  "$dawn" check "$work/bridge-no-asm"
if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/bridge-hidden.out" ] ||
    [ "$(grep -Fc 'Java class not found:' "$work/bridge-hidden.err")" -ne 2 ] ||
    ! grep -Fq 'Java class not found: dawn.rt.Asm' "$work/bridge-hidden.err" ||
    ! grep -Fq 'Java class not found: dawn.rt.AsmWriter' "$work/bridge-hidden.err" ||
    grep -Fq 'Java class not found: org.objectweb.asm.ClassWriter' "$work/bridge-hidden.err" ||
    [ -e "$work/empty-bridge-cache" ]; then
  cat "$work/bridge-hidden.out" >&2
  cat "$work/bridge-hidden.err" >&2
  fail "generated bridges were visible without target ASM"
fi
echo "PASS  generated bridges stay invisible when target ASM is absent"

cp -R "$work/app-a" "$work/malformed-lock"
printf 'not a lock\n' > "$work/malformed-lock/dawn.lock"
cp -R "$work/app-a" "$work/hash-drift"
python3 - "$work/hash-drift/dawn.lock" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
path.write_text(re.sub(r"(?m)^artifact [0-9a-f]+", "artifact " + "0" * 64, text))
PY
cp -R "$work/jdk" "$work/stale-lock"
cat > "$work/stale-lock/dawn.lock" <<'EOF'
schema 1
coord fixture:api-a:1
artifact 0000000000000000000000000000000000000000000000000000000000000000  api-a-1.jar
EOF
cp -R "$work/app-a" "$work/unreadable-lock"
chmod 000 "$work/unreadable-lock/dawn.lock"

expect_setup_error() {
  local label=$1 target=$2 needle=$3
  capture "$label" "$dawn" check "$target"
  if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/$label.out" ] ||
      ! grep -Fq "$needle" "$work/$label.err" ||
      ! head -n 1 "$work/$label.err" | grep -Fq 'error:'; then
    cat "$work/$label.out" >&2
    cat "$work/$label.err" >&2
    fail "$label did not fail closed on stderr with exit 1"
  fi
  expect_no_resolving "$label"
}

expect_setup_error malformed-lock "$work/malformed-lock" \
  'unrecognized line in dawn.lock: not a lock'
expect_setup_error hash-drift "$work/hash-drift" \
  'dawn.lock disagrees about api-a-1.jar'
expect_setup_error stale-lock "$work/stale-lock" \
  "dawn.lock's direct coordinates do not match dawn.toml"
expect_setup_error unreadable-lock "$work/unreadable-lock" \
  "cannot read $work/unreadable-lock/dawn.lock:"
chmod 600 "$work/unreadable-lock/dawn.lock"
echo "PASS  malformed, drifted, stale, and unreadable locks fail closed"

mkdir -p "$work/planner-error/src"
cat > "$work/planner-error/dawn.toml" <<'EOF'
schema = 1
name = "Bad-Name"
EOF
cat > "$work/planner-error/src/main.dawn" <<'EOF'
use java "java.lang.String"

pub fn main() -> Unit !io = {
  let _ = String.valueOf(1)
  ()
}
EOF
printf 'schema 1\ncoord fixture:api-a:1\n' > "$work/planner-error/dawn.lock"
chmod 000 "$work/planner-error/dawn.lock"
capture planner-first env COURSIER_CACHE="$work/planner-cache" "$dawn" check "$work/planner-error"
chmod 600 "$work/planner-error/dawn.lock"
if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/planner-first.out" ] ||
    ! grep -Fq 'invalid package name `Bad-Name`' "$work/planner-first.err" ||
    grep -Fq 'dawn.lock' "$work/planner-first.err" || [ -e "$work/planner-cache" ]; then
  cat "$work/planner-first.out" >&2
  cat "$work/planner-first.err" >&2
  fail "planner diagnostics did not retain precedence over Maven/lock setup"
fi
echo "PASS  planner diagnostics skip Maven and retain diagnostic precedence"

mkdir -p "$work/no-src"
cat > "$work/no-src/dawn.toml" <<'EOF'
schema = 1
name = "no_src"

[java-deps]
missing = "fixture:no-such:1"
EOF
capture missing-src env COURSIER_CACHE="$work/missing-src-cache" "$dawn" check "$work/no-src"
if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/missing-src.out" ] ||
    ! grep -Fq 'project directory has no `src/` folder' "$work/missing-src.err" ||
    grep -Fq 'could not resolve' "$work/missing-src.err" || [ -e "$work/missing-src-cache" ]; then
  cat "$work/missing-src.out" >&2
  cat "$work/missing-src.err" >&2
  fail "missing src/ was not rejected before planning and Maven fetch"
fi
echo "PASS  missing src/ is rejected before manifest planning and Maven fetch"

capture native-refusal env COURSIER_CACHE="$work/native-cache" \
  DAWN_MAVEN_MIRROR="file://$repo" "$work/dawnc" check "$work/app-a"
if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/native-refusal.out" ] ||
    ! grep -Fq '`use java` is not available in this compiler' "$work/native-refusal.err" ||
    [ -e "$work/native-cache" ]; then
  cat "$work/native-refusal.out" >&2
  cat "$work/native-refusal.err" >&2
  fail "native check crossed the Java/Maven boundary"
fi
echo "PASS  native keeps its use-java refusal without creating a Coursier cache"

prepare_mutant() {
  local name=$1
  MUTANT_DIR="$work/mutant-$name"
  MUTANT_JAR="$MUTANT_DIR/compiler.jar"
  mkdir -p "$MUTANT_DIR"
  cp -R "$root/selfhost" "$MUTANT_DIR/selfhost"
  cp -R "$root/compiler-plan" "$MUTANT_DIR/compiler-plan"
  ln -s "$root/packages" "$MUTANT_DIR/packages"
}

mutate_private() {
  local name=$1 dir=$2
  python3 - "$name" "$dir/selfhost/src/main.dawn" \
      "$dir/selfhost/src/driver/analyze.dawn" \
      "$dir/selfhost/src/jvm/jreflect.dawn" <<'PY'
from pathlib import Path
import sys

name, main_name, analyze_name, jreflect_name = sys.argv[1:]
main_path = Path(main_name)
analyze_path = Path(analyze_name)
jreflect_path = Path(jreflect_name)
main = main_path.read_text()
analyze = analyze_path.read_text()
jreflect = jreflect_path.read_text()

def replace_once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"mutation anchor occurs {count} times: {old!r}")
    return text.replace(old, new)

release_block = '''  let lease = jsig_for(jars)
  Ok(bracket(
    lease,
    held => held.close(),
    held => analyze_program(loaded, std, ct_default(), held.jsig)
  ))'''

if name == "always-system":
    main = replace_once(
        main,
        release_block,
        '''  let _ = jars
  Ok(analyze_program(loaded, std, ct_default(), jsig_real()))''',
    )
elif name == "merge-classpaths":
    main = replace_once(
        main,
        "  let lease = jsig_for(jars)",
        '''  let merged = match io.getenv("DAWN_MUTANT_MERGED_CP") {
    Some(cp) -> str.split(cp, path_sep())
    None -> jars
  }
  let lease = jsig_for(merged)''',
    )
elif name == "skip-lock":
    main = replace_once(
        main,
        "maven.fetch_checked(plan.source.project, plan.source.java_coords)",
        "maven.fetch(plan.source.java_coords)",
    )
elif name == "empty-system":
    main = replace_once(
        main,
        "  let lease = jsig_for(jars)",
        '''  if len(jars) == 0 {
    return Ok(analyze_program(loaded, std, ct_default(), jsig_real()))
  }
  let lease = jsig_for(jars)''',
    )
elif name == "fetch-with-planner-diags":
    main = replace_once(
        main,
        "  let jars = if len(plan.source.diags) > 0 {",
        "  let jars = if false {",
    )
elif name == "plan-before-preflight":
    old = '''pub fn project_plan_for_load(
  target: source.SourceTarget
) -> Result[ProjectPlan, LoadResult] !io =
  match target {
    source.ProjectDirectory(dir) ->
      if io.is_dir(dir ++ "/src") {
        Ok(project_plan(target))
      } else {
        Err(missing_source_root(dir))
      }
    source.SourceFile(_) -> Ok(project_plan(target))
  }'''
    new = '''pub fn project_plan_for_load(
  target: source.SourceTarget
) -> Result[ProjectPlan, LoadResult] !io = Ok(project_plan(target))'''
    analyze = replace_once(analyze, old, new)
elif name == "drop-asm-bridge":
    jreflect = replace_once(
        jreflect,
        "  lease_with(loader, target_has_asm(loader.base))",
        "  lease_with(loader, false)",
    )
elif name == "instrument-close":
    main = replace_once(
        main,
        "    held => held.close(),",
        '''    held => {
      held.close()
      match io.getenv("DAWN_TARGET_CLOSE_SENTINEL") {
        Some(path) ->
          match io.write_file(path, "closed\\n") {
            Ok(_) -> ()
            Err(e) -> panic("cannot write close sentinel: " ++ e.message)
          }
        None -> ()
      }
    },''',
    )
elif name == "bypass-bracket":
    instrumented = release_block.replace(
        "    held => held.close(),",
        '''    held => {
      held.close()
      match io.getenv("DAWN_TARGET_CLOSE_SENTINEL") {
        Some(path) ->
          match io.write_file(path, "closed\\n") {
            Ok(_) -> ()
            Err(e) -> panic("cannot write close sentinel: " ++ e.message)
          }
        None -> ()
      }
    },''',
    )
    main = replace_once(
        main,
        instrumented,
        '''  let lease = jsig_for(jars)
  let _ = lease.jsig.find_class("java.lang.String")
  Ok(analyze_program(loaded, std, ct_default(), lease.jsig))''',
    )
else:
    raise SystemExit(f"unknown mutation: {name}")

main_path.write_text(main)
analyze_path.write_text(analyze)
jreflect_path.write_text(jreflect)
PY
}

build_private_jar() {
  local label=$1 dir=$2 jar_path=$3
  if ! DAWN_SELFHOST_CP="" "$dawn" build "$dir/selfhost" -o "$jar_path" \
      --std "$root/std" --vendor org/objectweb/asm --vendor coursierapi \
      > "$dir/$label-build.out" 2> "$dir/$label-build.err"; then
    cat "$dir/$label-build.out" >&2
    cat "$dir/$label-build.err" >&2
    fail "$label private selfhost did not compile"
  fi
}

build_mutant() {
  local name=$1
  prepare_mutant "$name"
  mutate_private "$name" "$MUTANT_DIR"
  build_private_jar "$name" "$MUTANT_DIR" "$MUTANT_JAR"
}

run_mutant() {
  local label=$1 jar_path=$2
  shift 2
  capture "$label" java -Xss512m -Xmx2g -jar "$jar_path" "$@"
}

build_mutant always-system
run_mutant always-system-check "$MUTANT_JAR" check "$work/app-a"
if [ "$CAPTURE_STATUS" -ne 1 ] ||
    ! grep -Fq 'Java class not found: fixture.Shared' "$work/always-system-check.err"; then
  cat "$work/always-system-check.out" >&2
  cat "$work/always-system-check.err" >&2
  fail "always-system mutant missed TARGET_CHECK_DEPENDENCY_MISMATCH"
fi
run_mutant always-system-doc "$MUTANT_JAR" doc "$work/app-a"
if [ "$CAPTURE_STATUS" -ne 1 ] ||
    ! grep -Fq 'Java class not found: fixture.Shared' "$work/always-system-doc.err"; then
  cat "$work/always-system-doc.out" >&2
  cat "$work/always-system-doc.err" >&2
  fail "always-system mutant missed TARGET_DOC_DEPENDENCY_MISMATCH"
fi
echo "PASS  system-loader check/doc mutant compiles, then loses target dependencies"

build_mutant merge-classpaths
merged_cp="$repo/fixture/api-a/1/api-a-1.jar$(python3 -c 'import os; print(os.pathsep, end="")')$repo/fixture/api-b/1/api-b-1.jar"
capture merge-classpaths env DAWN_MUTANT_MERGED_CP="$merged_cp" \
  java -Xss512m -Xmx2g -jar "$MUTANT_JAR" check "$work/app-a" "$work/app-b"
if [ "$CAPTURE_STATUS" -ne 1 ] || ! grep -Fq 'onlyB' "$work/merge-classpaths.err"; then
  cat "$work/merge-classpaths.out" >&2
  cat "$work/merge-classpaths.err" >&2
  fail "merged-classpath mutant missed TARGET_CLASSPATH_ISOLATION_MISMATCH"
fi
echo "PASS  merged-classpath mutant compiles, then crosses same-FQCN targets"

build_mutant skip-lock
run_mutant skip-lock "$MUTANT_JAR" check "$work/hash-drift"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ "$(cat "$work/skip-lock.out")" != "ok" ]; then
  cat "$work/skip-lock.out" >&2
  cat "$work/skip-lock.err" >&2
  fail "skip-lock mutant missed LOCK_DRIFT_ACCEPTED"
fi
echo "PASS  skip-lock mutant compiles, then wrongly accepts hash drift"

build_mutant empty-system
run_mutant empty-system "$MUTANT_JAR" check "$work/asm" "$work/coursier"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ "$(cat "$work/empty-system.out")" != "ok" ]; then
  cat "$work/empty-system.out" >&2
  cat "$work/empty-system.err" >&2
  fail "empty-system mutant missed COMPILER_CLASSPATH_LEAK"
fi
echo "PASS  empty-system mutant compiles, then leaks compiler ASM/Coursier"

build_mutant fetch-with-planner-diags
chmod 000 "$work/planner-error/dawn.lock"
run_mutant planner-fetch "$MUTANT_JAR" check "$work/planner-error"
chmod 600 "$work/planner-error/dawn.lock"
if [ "$CAPTURE_STATUS" -ne 1 ] ||
    ! grep -Fq "cannot read $work/planner-error/dawn.lock:" "$work/planner-fetch.err"; then
  cat "$work/planner-fetch.out" >&2
  cat "$work/planner-fetch.err" >&2
  fail "planner-fetch mutant missed PLANNER_DIAGNOSTIC_PRECEDENCE_MISMATCH"
fi
echo "PASS  planner-fetch mutant compiles, then lets lock I/O hide planner diagnostics"

build_mutant plan-before-preflight
capture preflight-mutant env COURSIER_CACHE="$work/preflight-mutant-cache" \
  java -Xss512m -Xmx2g -jar "$MUTANT_JAR" check "$work/no-src"
if [ "$CAPTURE_STATUS" -ne 1 ] ||
    ! grep -Fq 'could not resolve dependency fixture:no-such:1' "$work/preflight-mutant.err"; then
  cat "$work/preflight-mutant.out" >&2
  cat "$work/preflight-mutant.err" >&2
  fail "plan-before-preflight mutant missed MISSING_SRC_FETCHED"
fi
echo "PASS  plan-before-preflight mutant compiles, then fetches for a rejected directory"

prepare_mutant close-path
mutate_private instrument-close "$MUTANT_DIR"
control_jar="$MUTANT_DIR/control.jar"
build_private_jar close-control "$MUTANT_DIR" "$control_jar"
control_sentinel="$work/close-control.sentinel"
capture close-control env DAWN_TARGET_CLOSE_SENTINEL="$control_sentinel" \
  java -Xss512m -Xmx2g -jar "$control_jar" check "$work/jdk"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ "$(cat "$control_sentinel" 2>/dev/null || true)" != "closed" ]; then
  cat "$work/close-control.out" >&2
  cat "$work/close-control.err" >&2
  fail "instrumented bracket control did not close its target lease"
fi
mutate_private bypass-bracket "$MUTANT_DIR"
bypass_jar="$MUTANT_DIR/bypass.jar"
build_private_jar bypass-bracket "$MUTANT_DIR" "$bypass_jar"
bypass_sentinel="$work/bypass.sentinel"
capture bypass-bracket env DAWN_TARGET_CLOSE_SENTINEL="$bypass_sentinel" \
  java -Xss512m -Xmx2g -jar "$bypass_jar" check "$work/jdk"
if [ "$CAPTURE_STATUS" -ne 0 ] || [ -e "$bypass_sentinel" ]; then
  cat "$work/bypass-bracket.out" >&2
  cat "$work/bypass-bracket.err" >&2
  fail "bypass-bracket mutant missed TARGET_LEASE_CLOSE_MISSING"
fi
echo "PASS  bracket-bypass mutant compiles, then skips the proven close path"

build_mutant drop-asm-bridge
run_mutant drop-asm-bridge "$MUTANT_JAR" check "$work/bridge"
if [ "$CAPTURE_STATUS" -ne 1 ] || [ -s "$work/drop-asm-bridge.out" ] ||
    [ "$(grep -Fc 'Java class not found:' "$work/drop-asm-bridge.err")" -ne 2 ] ||
    ! grep -Fq 'Java class not found: dawn.rt.Asm' "$work/drop-asm-bridge.err" ||
    ! grep -Fq 'Java class not found: dawn.rt.AsmWriter' "$work/drop-asm-bridge.err" ||
    grep -Fq 'Java class not found: org.objectweb.asm.ClassWriter' \
      "$work/drop-asm-bridge.err"; then
  cat "$work/drop-asm-bridge.out" >&2
  cat "$work/drop-asm-bridge.err" >&2
  fail "drop-asm-bridge mutant missed TARGET_ASM_BRIDGE_MISSING"
fi
echo "PASS  bridge-overlay mutant compiles, then loses exactly the two generated bridges"

echo "java-target-classpath-contract: OK"

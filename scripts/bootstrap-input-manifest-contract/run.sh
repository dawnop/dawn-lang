#!/usr/bin/env bash
# The bootstrap source-input manifest is a protocol between the Planner and the
# repository launcher, not part of SourcePlan's Maven/MVS contract. This script
# drives the real hidden CLI for the public process boundary, then compiles a
# Planner-only producer probe for fail-closed boundary cases and mutations.
#
# All package and Maven caches are temporary. The repository toolchain is
# initialized before the local-only mirror is installed; no fixture depends on
# compiler internals, the selfhost package, ASM, or a host cache.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work=$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-input-manifest-contract.XXXXXX")
trap 'chmod -R u+rwx "$work" 2>/dev/null || true; rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if ! "$dawn" --version > "$work/version.out" 2> "$work/version.err"; then
  cat "$work/version.out" >&2
  cat "$work/version.err" >&2
  fail "$dawn could not initialize the current toolchain"
fi

mkdir -p "$work/maven"
export DAWN_PKG_CACHE="$work/cache"
export COURSIER_CACHE="$work/coursier-cache"
export DAWN_MAVEN_MIRROR="file://$work/maven"

run_input_manifest() {
  local base=$1 target=$2 output=$3
  "$dawn" __source-inputs --base "$base" "$target" \
    > "$output.out" 2> "$output.err"
}

run_producer() {
  local jar_path=$1 output=$2
  shift 2
  java -Xss512m -Xmx2g -jar "$jar_path" "$@" > "$output.out" 2> "$output.err"
}

render_probe_manifest() {
  python3 - "$root/scripts/bootstrap-input-manifest-contract/fixtures/producer/dawn.toml.in" \
      "$1" "$2" <<'PY'
import pathlib
import sys

source, target, compiler_plan = sys.argv[1:]
text = pathlib.Path(source).read_text()
if text.count("@COMPILER_PLAN@") != 1:
    raise SystemExit("producer manifest must contain one @COMPILER_PLAN@ placeholder")
pathlib.Path(target).write_text(text.replace("@COMPILER_PLAN@", compiler_plan))
PY
}

build_producer() {
  local compiler_plan=$1 project=$2 jar_path=$3 label=$4
  mkdir -p "$project/src"
  render_probe_manifest "$project/dawn.toml" "$compiler_plan"
  cp "$root/scripts/bootstrap-input-manifest-contract/fixtures/producer/src/main.dawn" \
    "$project/src/main.dawn"
  if ! "$dawn" build "$project" -o "$jar_path" --std "$root/std" \
      > "$project/build.out" 2>&1; then
    cat "$project/build.out" >&2
    fail "$label producer probe did not compile"
  fi
}

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

if ! run_input_manifest "$input_base" "$input_app" "$work/inputs"; then
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
if ! run_input_manifest "$moved_base" "$moved_base/app" "$work/moved-inputs"; then
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

set +e
"$dawn" __source-inputs > "$work/arity.out" 2> "$work/arity.err"
arity_rc=$?
set -e
if [ "$arity_rc" -ne 2 ]; then
  cat "$work/arity.err" >&2
  fail "source input argument rejection exited $arity_rc instead of 2"
fi
test ! -s "$work/arity.out" || fail "source input argument rejection wrote stdout"
printf '%s\n' 'error: usage: dawn __source-inputs --base <repo> <project-dir>' \
  > "$work/arity.expected"
if ! cmp -s "$work/arity.expected" "$work/arity.err"; then
  diff -u "$work/arity.expected" "$work/arity.err" >&2 || true
  fail "source input argument rejection drifted"
fi
echo "PASS  source input manifest rejects an invalid argument shape"

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
run_input_manifest "$direct_base" "$direct_file" "$work/direct-file"
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

invalid_project="$input_root/invalid-plan/app"
mkdir -p "$invalid_project/src"
cat > "$invalid_project/dawn.toml" <<'EOF'
schema = "invalid"
name = "invalid_plan"
EOF
cat > "$invalid_project/src/main.dawn" <<'DAWN'
pub fn main() -> Unit = ()
DAWN
if run_input_manifest "$input_root/invalid-plan" "$invalid_project" "$work/invalid-plan"; then
  fail "a SourcePlan diagnostic unexpectedly produced an input manifest"
fi
test ! -s "$work/invalid-plan.out" || fail "SourcePlan diagnostics leaked a partial manifest"
if ! grep -q 'schema' "$work/invalid-plan.err"; then
  cat "$work/invalid-plan.err" >&2
  fail "SourcePlan diagnostic did not identify the invalid manifest"
fi
echo "PASS  SourcePlan diagnostics leave source-input stdout empty"

expect_input_failure() {
  local label=$1 base=$2 target=$3 expected=$4
  if run_input_manifest "$base" "$target" "$work/failure-$label"; then
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
echo "PASS  source input manifest rejects LF, symlinks, and wrong tree types"

mkdir -p "$input_root/unreadable/app/src/blocked"
cat > "$input_root/unreadable/app/dawn.toml" <<'EOF'
schema = 1
name = "unreadable"
EOF
printf 'hidden\n' > "$input_root/unreadable/app/src/blocked/value.dawn"
chmod 000 "$input_root/unreadable/app/src/blocked"
if (cd "$input_root/unreadable/app/src/blocked" && cat value.dawn > /dev/null) \
    2> /dev/null; then
  chmod 700 "$input_root/unreadable/app/src/blocked"
  echo "SKIP  unreadable-tree rejection (current uid bypasses mode-000 permissions)"
else
  if run_input_manifest "$input_root/unreadable" "$input_root/unreadable/app" \
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
  echo "PASS  source input manifest rejects unreadable trees"
fi

build_producer "$root/compiler-plan" "$work/producer" "$work/producer.jar" "baseline"

expect_producer_failure() {
  local label=$1 expected=$2
  shift 2
  if run_producer "$work/producer.jar" "$work/producer-$label" "$@"; then
    fail "$label Planner producer unexpectedly succeeded"
  fi
  test ! -s "$work/producer-$label.out" || fail "$label Planner producer wrote stdout"
  printf '%s\n' "$expected" > "$work/producer-$label.expected"
  if ! cmp -s "$work/producer-$label.expected" "$work/producer-$label.err"; then
    diff -u "$work/producer-$label.expected" "$work/producer-$label.err" >&2 || true
    fail "$label Planner producer diagnostic drifted"
  fi
}

missing_case="$input_root/post-plan-missing"
cp -R "$input_base" "$missing_case"
expect_producer_failure required-missing \
  "error: required source input is missing: $missing_case/app/dawn.toml" \
  --remove-manifest "$missing_case" "$missing_case/app"

file_directory_case="$input_root/post-plan-file-directory"
cp -R "$input_base" "$file_directory_case"
expect_producer_failure file-directory \
  "error: source input must be a file: $file_directory_case/app/dawn.toml" \
  --manifest-directory "$file_directory_case" "$file_directory_case/app"

optional_case="$input_root/post-plan-optional-directory"
cp -R "$input_base" "$optional_case"
expect_producer_failure optional-directory \
  "error: source input must be a file: $optional_case/app/dawn.lock" \
  --lock-directory "$optional_case" "$optional_case/app"
echo "PASS  required files and present optional files fail closed on type changes"

if "$dawn" --help | grep -q '__source-inputs'; then
  fail "bootstrap source input command leaked into public help"
fi
echo "PASS  source input manifest command remains hidden"

expect_input_mutant_red() {
  local mutation=$1 mutant="$work/mutant-$1" output="$work/mutant-$1.manifest"
  mkdir -p "$mutant/packages"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  for package in fspath sha2 inflate; do
    cp -R "$root/packages/$package" "$mutant/packages/$package"
  done
  python3 "$root/scripts/bootstrap-input-manifest-contract/mutate.py" \
    "$mutation" "$mutant/compiler-plan/src/source.dawn"
  build_producer "$mutant/compiler-plan" "$mutant/producer" "$mutant/producer.jar" "$mutation"
  if ! run_producer "$mutant/producer.jar" "$output" "$input_base" "$input_app"; then
    cat "$output.err" >&2
    fail "$mutation mutant did not execute the Planner producer"
  fi
  if [ -s "$output.err" ]; then
    cat "$output.err" >&2
    fail "$mutation mutant failed outside its owning contract"
  fi
  case "$mutation" in
    drop-deps-recursion)
      cat > "$output.expected" <<EOF
dawn-source-inputs-v1
R	F	app/dawn.toml
R	F	pkg-alpha/dawn.toml
R	F	pkg-charlie/dawn.toml
R	O	app/dawn.lock
R	T	app/src
R	T	pkg-alpha/src
R	T	pkg-charlie/src
EOF
      ;;
    drop-package-manifest)
      cat > "$output.expected" <<EOF
dawn-source-inputs-v1
A	T	$input_shared/src
R	F	app/dawn.toml
R	O	app/dawn.lock
R	T	app/src
R	T	pkg-alpha/src
R	T	pkg-charlie/src
EOF
      ;;
    persist-internal-absolute)
      cat > "$output.expected" <<EOF
dawn-source-inputs-v1
A	F	$input_shared/dawn.toml
A	F	$input_app/dawn.toml
A	F	$input_alpha/dawn.toml
A	F	$input_charlie/dawn.toml
A	O	$input_app/dawn.lock
A	T	$input_shared/src
A	T	$input_app/src
A	T	$input_alpha/src
A	T	$input_charlie/src
EOF
      ;;
    *) fail "unknown input-manifest mutation: $mutation" ;;
  esac
  if ! cmp -s "$output.expected" "$output.out"; then
    diff -u "$output.expected" "$output.out" >&2 || true
    fail "$mutation mutant did not produce its exact expected broken manifest"
  fi
  echo "PASS  $mutation mutant compiles and turns its input-manifest contract red"
}

expect_input_mutant_red drop-deps-recursion
expect_input_mutant_red drop-package-manifest
expect_input_mutant_red persist-internal-absolute

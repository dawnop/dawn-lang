#!/usr/bin/env bash
# ProjectPlan capture contracts. Both negative controls compile private
# selfhost trees first, then fail only after their owning behavior is exercised.

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
dawn="$root/bin/dawn"
work=$(mktemp -d "${TMPDIR:-/tmp}/dawn-project-plan-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "project-plan-contract: $*" >&2
  exit 1
}

# The anchors live in mutate.py, one registered mutation per mutant name, so
# mutation-anchor-preflight.py proves each one matches exactly once before any
# build, not only when this script reaches that mutant.
mutate() { # <mutation> <tree-root>
  python3 "$here/mutate.py" "$1" "$2"
}

setup_captured_fixture() {
  local fixture=$1
  mkdir -p "$fixture/app/src" "$fixture/a/src" "$fixture/b/src"
  cat > "$fixture/app/dawn.toml" <<'EOF'
schema = 1
name = "app"

[deps]
dep = "../a"
EOF
  cat > "$fixture/app/src/main.dawn" <<'EOF'
use dep/api
pub fn main() -> Unit !io = println(api.alpha())
EOF
  cat > "$fixture/app/src/bad-name.dawn" <<'EOF'
pub fn bad() -> Int = 0
EOF
  cat > "$fixture/a/dawn.toml" <<'EOF'
schema = 1
name = "pkg_a"
EOF
  cat > "$fixture/a/src/api.dawn" <<'EOF'
pub fn alpha() -> Int = 1
EOF
  cat > "$fixture/b/dawn.toml" <<'EOF'
schema = 1
name = "pkg_b"
EOF
  cat > "$fixture/b/src/api.dawn" <<'EOF'
pub fn beta() -> Int = 2
EOF
}

run_probe() {
  local project=$1 fixture=$2 jar=$3
  "$dawn" build "$project" -o "$jar" --std "$root/std"
  DAWN_PROJECT_PLAN_FIXTURE="$fixture" \
    java -Xss512m -Xmx2g -jar "$jar"
}

setup_captured_fixture "$work/captured-baseline"
run_probe "$here/captured-probe" "$work/captured-baseline" "$work/captured.jar"
python3 "$here/completion.py" "$dawn" lsp

loader_mutant="$work/loader-mutant"
mkdir -p "$loader_mutant"
cp -R "$root/selfhost" "$loader_mutant/selfhost"
cp -R "$root/compiler-plan" "$loader_mutant/compiler-plan"
ln -s "$root/packages" "$loader_mutant/packages"
# The probe keeps the path it has in the checkout, so its manifest's
# `../../../selfhost` resolves to this mutant's compiler as written.
loader_probe="$loader_mutant/scripts/project-plan-contract/captured-probe"
mkdir -p "$(dirname "$loader_probe")"
cp -R "$here/captured-probe" "$loader_probe"
mutate fresh-replan-loader "$loader_mutant"

setup_captured_fixture "$work/captured-loader-mutant"
if ! "$dawn" build "$loader_probe" -o "$work/loader-mutant.jar" \
    --std "$root/std" > "$work/loader-mutant-build.out" 2>&1; then
  cat "$work/loader-mutant-build.out" >&2
  fail "fresh-replan loader mutant did not compile"
fi
if DAWN_PROJECT_PLAN_FIXTURE="$work/captured-loader-mutant" \
    java -Xss512m -Xmx2g -jar "$work/loader-mutant.jar" \
    > "$work/loader-mutant.out" 2>&1; then
  fail "fresh-replan loader mutant stayed green"
fi
if ! grep -Fq "captured plan did not retain dependency A" "$work/loader-mutant.out"; then
  cat "$work/loader-mutant.out" >&2
  fail "fresh-replan loader mutant missed its captured-plan boundary"
fi
echo "PASS  fresh-replan loader mutant compiles and turns captured-plan red"

completion_mutant="$work/completion-mutant"
mkdir -p "$completion_mutant"
cp -R "$root/selfhost" "$completion_mutant/selfhost"
cp -R "$root/compiler-plan" "$completion_mutant/compiler-plan"
ln -s "$root/packages" "$completion_mutant/packages"
mutate fresh-completion "$completion_mutant"
if ! "$dawn" build "$completion_mutant/selfhost" -o "$work/completion-mutant.jar" \
    --std "$root/std" > "$work/completion-mutant-build.out" 2>&1; then
  cat "$work/completion-mutant-build.out" >&2
  fail "fresh-completion mutant did not compile"
fi
if python3 "$here/completion.py" \
    java -Xss512m -Xmx2g -jar "$work/completion-mutant.jar" lsp \
    > "$work/completion-mutant.out" 2>&1; then
  fail "fresh-completion mutant stayed green"
fi
if ! grep -Fq "CAPTURED_SESSION_MISMATCH" "$work/completion-mutant.out"; then
  cat "$work/completion-mutant.out" >&2
  fail "fresh-completion mutant missed its session-consistency boundary"
fi
echo "PASS  fresh-completion mutant compiles and turns completion consistency red"

echo "project-plan-contract: OK"

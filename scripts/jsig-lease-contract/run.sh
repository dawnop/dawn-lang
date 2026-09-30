#!/usr/bin/env bash
# Build all fixture artifacts from tracked sources, then compile the production
# JsigLease seam and every behavioral mutant as a minimal dependency package.
# After the ordinary compiler bootstrap, the subject has no external Java
# dependency and never reaches for ASM, a host artifact cache, or the network.
#
#   ./scripts/jsig-lease-contract/run.sh
#
# `expected.txt` is the positive fixture's five PASS lines. No `--record`: the
# mutant legs are read as substrings of their own runs, and only this file says
# what the unmutated seam must report. Edit it by hand when a leg is added.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/jsig-lease-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work="$(mktemp -d "${TMPDIR:-/tmp}/jsig-lease-contract.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for command in javac jar java python3; do
  command -v "$command" > /dev/null || fail "missing required JDK command: $command"
done

build_fixture() {
  local name=$1
  local source="$here/fixtures/$name"
  local out="$work/fixture-$name"
  mkdir -p "$out/classes"
  javac -d "$out/classes" "$source/src/fixture/"*.java
  if [ -d "$source/resources" ]; then
    cp -R "$source/resources/." "$out/classes/"
  fi
  (cd "$out/classes" && jar cf "$work/$name.jar" .)
}

build_fixture a
build_fixture b
mkdir -p "$work/host/classes"
javac -d "$work/host/classes" "$here/fixtures/host/src/host/Leak.java"

# A case's subject and app are assembled from <tree>, which holds the two
# files a mutant may edit at the paths they have in the checkout: the
# checkout itself for the positive case, a mutated copy for a mutant.
prepare_case() { # <case-dir> <tree>
  local case_dir=$1
  local tree=$2
  mkdir -p "$case_dir/subject/src/check" "$case_dir/subject/src/jvm" "$case_dir/app/src"
  cp "$root/selfhost/src/check/jsig.dawn" "$case_dir/subject/src/check/jsig.dawn"
  cp "$tree/selfhost/src/jvm/jreflect.dawn" "$case_dir/subject/src/jvm/jreflect.dawn"
  printf '\n' >> "$case_dir/subject/src/jvm/jreflect.dawn"
  cat "$here/resource-probe.dawn" >> "$case_dir/subject/src/jvm/jreflect.dawn"
  cat > "$case_dir/subject/dawn.toml" <<'EOF'
schema = 1
name = "jsig_subject"
EOF
  cat > "$case_dir/app/dawn.toml" <<EOF
schema = 1
name = "jsig_lease_probe"

[deps]
compiler = "$case_dir/subject"
EOF
  cp "$tree/scripts/jsig-lease-contract/probe.dawn" "$case_dir/app/src/main.dawn"
}

# The anchors live in mutate.py, one registered mutation per mutant name, so
# mutation-anchor-preflight.py proves each one matches exactly once before any
# build, not only when this script reaches that mutant.
mutate_tree() { # <name> <tree>
  local name=$1
  local tree=$2
  mkdir -p "$tree/selfhost/src/jvm" "$tree/scripts/jsig-lease-contract"
  cp "$root/selfhost/src/jvm/jreflect.dawn" "$tree/selfhost/src/jvm/jreflect.dawn"
  cp "$here/probe.dawn" "$tree/scripts/jsig-lease-contract/probe.dawn"
  python3 "$here/mutate.py" "$name" "$tree" "$work/a.jar" "$work/b.jar"
}

build_case() {
  local label=$1
  local case_dir=$2
  if ! "$dawn" build "$case_dir/app" -o "$case_dir/app.jar" \
      > "$case_dir/build.out" 2>&1; then
    cat "$case_dir/build.out" >&2
    fail "$label did not compile"
  fi
  jar uf "$case_dir/app.jar" -C "$work/host/classes" .
}

run_case() {
  local case_dir=$1
  java -Xss512m -Xmx1g -jar "$case_dir/app.jar" "$work/a.jar" "$work/b.jar"
}

positive="$work/positive"
prepare_case "$positive" "$root"
build_case positive "$positive"
if ! run_case "$positive" > "$positive/run.out" 2>&1; then
  cat "$positive/run.out" >&2
  fail "positive JsigLease contract did not run"
fi
diff -u "$here/expected.txt" "$positive/run.out" || fail "positive transcript changed"
cat "$positive/run.out"

expect_mutant_red() {
  local name=$1
  local expected=$2
  local mutant="$work/mutant-$name"
  mutate_tree "$name" "$mutant/tree"
  prepare_case "$mutant" "$mutant/tree"
  build_case "$name mutant" "$mutant"
  if run_case "$mutant" > "$mutant/run.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  if ! grep -Fq "$expected" "$mutant/run.out"; then
    cat "$mutant/run.out" >&2
    fail "$name mutant missed its owning assertion"
  fi
  echo "PASS  $name mutant compiles, then turns its owning assertion red"
}

expect_mutant_red queries-use-system \
  "FAIL isolation: first lease did not resolve fixture.Api"
expect_mutant_red parent-is-system \
  "FAIL platform-parent: target lease leaked host.Leak"
expect_mutant_red merge-loaders \
  "FAIL isolation: second lease API mismatch"
expect_mutant_red drop-close \
  "FAIL close: unique resource remained visible after normal close"
expect_mutant_red bypass-bracket \
  "FAIL bracket-close: unique resource remained visible after panic"

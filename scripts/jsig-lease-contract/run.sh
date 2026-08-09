#!/usr/bin/env bash
# Build all fixture artifacts from tracked sources, then compile the production
# JsigLease seam and every behavioral mutant as a minimal dependency package.
# After the ordinary compiler bootstrap, the subject has no external Java
# dependency and never reaches for ASM, a host artifact cache, or the network.
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

prepare_case() {
  local case_dir=$1
  mkdir -p "$case_dir/subject/src/check" "$case_dir/subject/src/jvm" "$case_dir/app/src"
  cp "$root/selfhost/src/check/jsig.dawn" "$case_dir/subject/src/check/jsig.dawn"
  cp "$root/selfhost/src/jvm/jreflect.dawn" "$case_dir/subject/src/jvm/jreflect.dawn"
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
  cp "$here/probe.dawn" "$case_dir/app/src/main.dawn"
}

mutate_case() {
  local name=$1
  local case_dir=$2
  python3 - "$name" "$case_dir/subject/src/jvm/jreflect.dawn" \
      "$case_dir/app/src/main.dawn" "$work/a.jar" "$work/b.jar" <<'PY'
from pathlib import Path
import json
import sys

name, reflect_name, probe_name, first_jar, second_jar = sys.argv[1:]
reflect_path = Path(reflect_name)
probe_path = Path(probe_name)
reflect = reflect_path.read_text()
probe = probe_path.read_text()

def replace_once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"mutation anchor occurs {count} times: {old!r}")
    return text.replace(old, new)

if name == "queries-use-system":
    reflect = replace_once(
        reflect,
        """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  lease_with(loader, target_has_asm(loader.base))
}""",
        """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  JsigLease { jsig: jsig_real(), close: () => loader.closeable.close() }
}""",
    )
elif name == "parent-is-system":
    reflect = replace_once(
        reflect,
        'let parent = ClassLoader.getPlatformClassLoader().expect("platform loader")',
        'let parent = ClassLoader.getSystemClassLoader().expect("system loader")',
    )
elif name == "merge-loaders":
    reflect = replace_once(
        reflect,
        """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  lease_with(loader, target_has_asm(loader.base))
}""",
        f"""pub fn jsig_for(jars: List[String]) -> JsigLease !io = {{
  let loader = loader_for([{json.dumps(first_jar)}, {json.dumps(second_jar)}])
  lease_with(loader, target_has_asm(loader.base))
}}""",
    )
elif name == "drop-close":
    reflect = replace_once(
        reflect,
        "JsigLease { jsig: jsig_with(loader.base, asm_bridge), close: () => loader.closeable.close() }",
        "JsigLease { jsig: jsig_with(loader.base, asm_bridge), close: () => () }",
    )
elif name == "bypass-bracket":
    probe = replace_once(
        probe,
        "bracket(guarded, probe => probe.lease.close(), fail_after_load)",
        "fail_after_load(guarded)",
    )
else:
    raise SystemExit(f"unknown mutation: {name}")

reflect_path.write_text(reflect)
probe_path.write_text(probe)
PY
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
prepare_case "$positive"
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
  prepare_case "$mutant"
  mutate_case "$name" "$mutant"
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

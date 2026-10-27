#!/usr/bin/env bash
# The same std builders run in CTFE and at runtime. Embedded independent
# oracles judge the values; cross-backend agreement alone is insufficient.
# The native-host leg reuses the compiler native-selfhost-tests already built.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
here="$root/scripts/comptime-bytes-contract"
mode=${1:-all}
case "$mode" in all|--native-host) ;; *) exit 2 ;; esac
work=$(mktemp -d "${TMPDIR:-/tmp}/comptime-bytes.XXXXXX")
trap 'rm -rf "$work"' EXIT
python3 "$here/generate.py" "$work/project"
printf 'byte literals ok\n' > "$work/expected"

fail() { echo "FAIL: $*" >&2; exit 1; }
if [ "$mode" = --native-host ]; then
  compiler=${DAWNC_BIN:?DAWNC_BIN must name the current-source native compiler}
  "$compiler" run "$work/project" > "$work/native-host.out"
  diff -u "$work/expected" "$work/native-host.out"
else
  compiler="$root/bin/dawn"
  "$compiler" run "$work/project" > "$work/jvm.out"
  diff -u "$work/expected" "$work/jvm.out"
  "$compiler" __emit "$work/project" -o "$work/classes" > /dev/null
  javac -d "$work/verify" "$root/scripts/classfile-verify/Verify.java" "$root/scripts/classfile-verify/AccessCheck.java"
  java -XX:-UsePerfData --add-exports java.base/jdk.internal.vm=ALL-UNNAMED \
    -cp "$work/verify:$root/build/dawn-selfhost.jar" Verify "$work/classes" | tee "$work/verify.out"
  grep -Fq '0 not initializable, 0 illegal' "$work/verify.out" || fail 'a literal holder did not initialize'
  "$compiler" __emitc "$work/project" -o "$work/probe.c"
  "${CC:-cc}" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread \
    -fsanitize=address -I "$root/runtime/c" -o "$work/probe" "$work/probe.c" "$root/runtime/c/dawn_rt.c" -lm
  ASAN_OPTIONS=detect_leaks=1 "$work/probe" > "$work/c.out"
  diff -u "$work/expected" "$work/c.out"
fi

# Quotas and semantic refusals have to fail in their own words. A syntax or
# import error is a broken fixture rather than evidence of a preserved gate.
expect_refusal() {
  local file=$1 reason=$2
  if "$compiler" check "$file" > "$work/refusal.out" 2>&1; then fail "accepted $file"; fi
  grep -Fq "$reason" "$work/refusal.out" || { cat "$work/refusal.out" >&2; fail "wrong refusal: $reason"; }
}
expect_refusal "$work/oversized.dawn" 'Bytes size limit: requested 1048577 bytes (limit 1048576)'
expect_refusal "$work/allocation.dawn" 'logical allocation limit'
for name in io function cursor hamt; do
  reason=$(python3 - "$work/refusals.json" "$name" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))[sys.argv[2]])
PY
)
  expect_refusal "$work/$name.dawn" "$reason"
done

if [ "$mode" = all ]; then
  cp -R "$root/compiler-plan" "$work/compiler-plan"
  ln -s "$root/packages" "$work/packages"
  for mutation in allocation-guard byte-emitter; do
    rm -rf "$work/selfhost"
    cp -R "$root/selfhost" "$work/selfhost"
    python3 "$here/mutate.py" "$mutation" "$work"
    if ! "$compiler" build "$work/selfhost" -o "$work/compiler.jar" > "$work/build.out" 2>&1; then
      cat "$work/build.out" >&2; fail "$mutation compiler did not build"
    fi
    if [ "$mutation" = allocation-guard ]; then
      # With only the allocation guard removed, bounded individual blobs
      # can accumulate more than the fold's logical budget and still finish.
      if ! java -XX:-UsePerfData -Xss512m -jar "$work/compiler.jar" check --std "$root/std" \
          "$work/allocation.dawn" > "$work/mutant.out" 2>&1; then
        cat "$work/mutant.out" >&2; fail 'allocation mutant missed its owning refusal'
      fi
    else
      if java -XX:-UsePerfData -Xss512m -jar "$work/compiler.jar" run --std "$root/std" \
          "$work/project" > "$work/mutant.out" 2>&1; then fail 'empty literal payload stayed green'; fi
      grep -Fq 'literal mismatch' "$work/mutant.out" || { cat "$work/mutant.out" >&2; fail 'literal mutant failed elsewhere'; }
    fi
    echo "PASS  comptime Bytes $mutation control"
  done
fi
echo "PASS  comptime Bytes values, quotas and refusals ($mode)"

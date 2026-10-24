#!/usr/bin/env bash
# The interpreter against tileref (docs/tileinterp-design.md 3): every
# layer-2 family of scripts/tile-gpu-diff, with packages/tileinterp in the
# device's chair, judged by the corpus, reference and tier the GPU is judged
# by. No GPU, no tileiras, no cubin: this is the half of layer 2 that CI can
# run.
#
#   scripts/tileinterp-diff/run.sh             # run and judge (the CI gate)
#   scripts/tileinterp-diff/run.sh --write     # run and rewrite covered.txt
#   scripts/tileinterp-diff/run.sh --selftest  # compiled negative controls
#
# The run: build.py copies the family programs into one project with the
# device swapped (its header says how and why), `dawn build` compiles it once,
# and one JVM a family runs it. verdicts.py reads the transcripts: every case
# agrees or is blocked by a refusal the interpreter made before running
# (`interp.unsupported_op`), and the kernels that ran in agreeing cases are
# exactly covered.txt. expected-ub.txt names the two kernels whose corpus
# reaches undefined behaviour on purpose.
#
# Why the families run on the JVM and not natively like scripts/tile-gpu-diff:
# the device programs are native because the device runtime is; with the
# interpreter there is no device, and one JVM build of 40,000 lines costs
# seconds where a native build costs a C compile of all of them.
#
# scan.py recounts the golden kernels the interpreter can reach at all and is
# run here so that a covered kernel outside that ceiling is red.
#
# --selftest applies each mutant of mutate.py to a copy of packages/tileinterp
# and requires the check that names it to go red: `mulf-adds` the comparison,
# `bounds-unchecked` the package's out-of-bounds test, `unsupported-skipped`
# the package's refusal test and the comparison, `mma-drops-term` and
# `narrow-unrounded` the package's product and rounding tests and the
# comparison, `fma-two-roundings` the package's fused tests.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
cd "$root"

mode=run
case "${1:-}" in
  "") ;;
  --write) mode=write ;;
  --selftest) mode=selftest ;;
  *) echo "usage: run.sh [--write | --selftest]" >&2; exit 2 ;;
esac

work="$(mktemp -d "${TMPDIR:-/tmp}/tileinterp-diff.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# bin/dawn's own choice of JVM, so the jar runs on the JDK that built it.
java_bin=java
if [ -z "${JAVA_HOME:-}" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home "$HOME"/tools/graalvm-*; do
    if [ -x "$d/bin/java" ]; then JAVA_HOME="$d"; break; fi
  done
fi
if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then java_bin="$JAVA_HOME/bin/java"; fi

fail() { echo "FAIL: $*" >&2; exit 1; }

# build_jar <dir> <interp package>: the project and its jar under <dir>.
build_jar() {
  python3 "$here/build.py" --out "$1/proj" --interp "$2" > "$1/families.txt"
  ./bin/dawn build "$1/proj" -o "$1/diff.jar" > "$1/build.log" 2>&1 ||
    { cat "$1/build.log" >&2; fail "the interpreter-against-tileref program does not build"; }
}

# run_families <dir> [seconds]: one JVM a family, transcripts in <dir>/out. A
# family program exits 1 on a `fail` verdict; verdicts.py is the judge either
# way. The bound is for a kernel whose `loop` never exits, which is what a
# wrong comparison inside one does (the mulf-adds mutant turns loop_until into
# exactly that): the interpreter's own step limit is 2^24 iterations, which
# is minutes of interpretation, so a family is cut off well before and its
# transcript gets a verdict line no judge accepts.
run_families() {
  mkdir -p "$1/out"
  local fam rc
  while read -r fam _mod _n; do
    rc=0
    timeout -k 5 "${2:-120}" "$java_bin" -XX:-UsePerfData -Xss512m -Xmx2g -jar "$1/diff.jar" "$fam" \
      > "$1/out/$fam.out" 2> "$1/out/$fam.err" || rc=$?
    if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
      echo "  verdict timeout:${2:-120}s" | tee -a "$1/out/$fam.out" >> "$1/out/$fam.err"
    fi
  done < "$1/families.txt"
}

families_of() { cut -d' ' -f1 "$1/families.txt" | tr '\n' ' '; }

# judge <dir> [extra verdicts.py args]
judge() {
  local d="$1"
  shift
  # shellcheck disable=SC2046
  python3 "$here/verdicts.py" "$d/out" $(families_of "$d") --covered "$here/covered.txt" \
    --expected-ub "$here/expected-ub.txt" "$@"
}

# A copy of packages/tileinterp under <dir>/tree with one mutant applied, its
# tileir dependency pointed back at this tree.
mutant_package() { # dir mutant
  mkdir -p "$1/tree/packages"
  cp -r "$root/packages/tileinterp" "$1/tree/packages/tileinterp"
  sed -i "s|^tileir = .*|tileir = \"$root/packages/tileir\"|" "$1/tree/packages/tileinterp/dawn.toml"
  python3 "$here/mutate.py" "$2" "$1/tree"
}

if [ "$mode" != selftest ]; then
  start=$(date +%s)
  build_jar "$work" "$root/packages/tileinterp"
  built=$(date +%s)
  run_families "$work"
  ran=$(date +%s)
  echo "tileinterp-diff: build $((built - start))s, families $((ran - built))s"
  if [ "$mode" = write ]; then judge "$work" --write; else judge "$work"; fi
  # the ceiling the covered set is measured against (scan.py's header): a
  # covered kernel the scan says is out of reach by construction is a bug in
  # one of the two
  python3 "$here/scan.py" --check
  exit 0
fi

# ---- --selftest
# The reference dependency control is legal Dawn, compiled and executed before
# the independence oracle sees it. A compiler refusal is not a killed mutant.
d="$work/reference-borrows-exp"
mkdir -p "$d/tree/packages" "$d/probe/src"
cp -r "$root/packages/tileref" "$d/tree/packages/tileref"
python3 "$here/mutate.py" reference-borrows-exp "$d/tree"
cat > "$d/probe/dawn.toml" <<EOF
schema = 1
name = "referenceprobe"
version = "0.0.0"
[deps]
tileref = "$d/tree/packages/tileref"
EOF
cat > "$d/probe/src/main.dawn" <<'EOF'
# Prove that aliasing and forwarding a host algorithm is legal but dependent.
use tileref/ref
pub fn main() -> Unit ! io = {
  if ref.ref_exp(0.0) != 1.0 { panic("forwarder did not run") } else { () }
  println("reference-forwarder complete")
}
EOF
./bin/dawn build "$d/probe" -o "$d/probe.jar" > "$d/build.log" 2>&1 ||
  { cat "$d/build.log" >&2; fail "reference-borrows-exp did not compile"; }
"$java_bin" -jar "$d/probe.jar" > "$d/run.out" 2>&1 || fail "reference-borrows-exp did not execute"
grep -qx 'reference-forwarder complete' "$d/run.out" || fail "reference-borrows-exp did not finish"
if python3 - "$root" "$d/tree" > "$d/judge.out" <<'PYCONTROL'
import runpy
import sys
from pathlib import Path
root, mutant = map(Path, sys.argv[1:])
gate = runpy.run_path(str(root / "scripts/leetgpu-diff/check.py"))
files = gate["gather"]()
path = "packages/tileref/src/ref.dawn"
files[path] = (mutant / path).read_text()
_listed, problems = gate["check"](gate["TABLE"].read_text(), files, gate["LEDGER"].read_text())
for problem in problems:
    print("FAIL: " + problem)
sys.exit(bool(problems))
PYCONTROL
then fail "reference-borrows-exp: the independence oracle stayed green"; fi
grep -q 'reaches std/math.exp: a reference must keep' "$d/judge.out" ||
  { cat "$d/judge.out" >&2; fail "reference-borrows-exp: the wrong oracle failed"; }
echo "PASS  reference-borrows-exp: compiled, executed, then the independence oracle went red"

for m in exp-misrouted mulf-adds bounds-unchecked unsupported-skipped mma-drops-term narrow-unrounded fma-two-roundings shift-ub-restored; do
  d="$work/$m"
  mkdir -p "$d"
  mutant_package "$d" "$m"
  pkg="$d/tree/packages/tileinterp"
  case "$m" in
    exp-misrouted)
      if ./bin/dawn test "$pkg" > "$d/test.out" 2>&1; then fail "$m: the dispatch test stayed green"; fi
      grep -q '^FAIL  interp :: host math dispatch retains the K1 exp witness and IEEE boundaries' "$d/test.out" ||
        { cat "$d/test.out" >&2; fail "$m: the K1 witness oracle did not fail"; }
      echo "PASS  $m: compiled and the K1 exp witness test went red"
      ;;
    mulf-adds)
      build_jar "$d" "$pkg"
      run_families "$d" 30
      if judge "$d" > "$d/judge.out" 2>&1; then cat "$d/judge.out" >&2; fail "$m: the comparison stayed green"; fi
      grep -q '^FAIL ' "$d/judge.out" || fail "$m: the comparison failed without naming a case"
      echo "PASS  $m: the comparison went red ($(grep -c '^FAIL ' "$d/judge.out") finding(s), first: $(grep -m1 '^FAIL ' "$d/judge.out" | cut -c1-160))"
      ;;
    bounds-unchecked)
      if ./bin/dawn test "$pkg" > "$d/test.out" 2>&1; then fail "$m: the package tests stayed green"; fi
      grep -q '^FAIL  selftest :: a store past the end of its buffer is undefined behaviour, refused' "$d/test.out" ||
        { cat "$d/test.out" >&2; fail "$m: the out-of-bounds test is not the one that failed"; }
      echo "PASS  $m: the out-of-bounds test went red"
      ;;
    unsupported-skipped)
      if ./bin/dawn test "$pkg" > "$d/test.out" 2>&1; then fail "$m: the package tests stayed green"; fi
      grep -q '^FAIL  selftest :: an instruction the interpreter does not model is refused by name before anything runs' "$d/test.out" ||
        { cat "$d/test.out" >&2; fail "$m: the refusal test is not the one that failed"; }
      build_jar "$d" "$pkg"
      run_families "$d" 30
      if judge "$d" > "$d/judge.out" 2>&1; then cat "$d/judge.out" >&2; fail "$m: the comparison stayed green"; fi
      # Skipping a fence newly covers token_fences. Require that precise
      # oracle, so a timeout in an unrelated family cannot kill this control.
      grep -q '^FAIL  covered but not in covered.txt: token_fences$' "$d/judge.out" ||
        { cat "$d/judge.out" >&2; fail "$m: the newly accepted fence was not named"; }
      echo "PASS  $m: the refusal test went red and the comparison named the incorrectly accepted token_fences"
      ;;
    mma-drops-term | narrow-unrounded)
      if ./bin/dawn test "$pkg" > "$d/test.out" 2>&1; then fail "$m: the package tests stayed green"; fi
      want='a matrix product adds every term of k to the accumulator'
      [ "$m" = narrow-unrounded ] && want='a narrow sum is rounded into its format after every operation'
      grep -q "^FAIL  selftest :: $want" "$d/test.out" ||
        { cat "$d/test.out" >&2; fail "$m: the test that names it is not one that failed"; }
      build_jar "$d" "$pkg"
      run_families "$d" 30
      if judge "$d" > "$d/judge.out" 2>&1; then cat "$d/judge.out" >&2; fail "$m: the comparison stayed green"; fi
      echo "PASS  $m: the package test and the comparison went red (first finding: $(grep -m1 '^FAIL ' "$d/judge.out" | cut -c1-160))"
      ;;
    shift-ub-restored)
      if ./bin/dawn test "$pkg" > "$d/test.out" 2>&1; then fail "$m: the package tests stayed green"; fi
      grep -q '^FAIL  interp :: integer shifts mask all counts even when UB checks are enabled' "$d/test.out" ||
        { cat "$d/test.out" >&2; fail "$m: the count-mask test did not fail"; }
      echo "PASS  $m: raw out-of-width and negative counts made the integer shift test red"
      ;;
    fma-two-roundings)
      if ./bin/dawn test "$pkg" > "$d/test.out" 2>&1; then fail "$m: the package tests stayed green"; fi
      grep -q '^FAIL  selftest :: fma rounds once, in f64 and in f32' "$d/test.out" ||
        { cat "$d/test.out" >&2; fail "$m: the fused test is not the one that failed"; }
      echo "PASS  $m: the fused package tests went red ($(grep -c '^FAIL ' "$d/test.out") of them)"
      ;;
  esac
done
echo "tileinterp-diff: selftest ok"

#!/usr/bin/env bash
# Bootstrap cost, as a ratio. docs/native-backend-plan.md 4 Phase 2 exits on
# "bootstrap time regresses by <= +15%", and until this script there was
# neither a way to measure that nor a number to measure it against.
#
#   ./scripts/selfhost-bench.sh                 # measure and print
#   ./scripts/selfhost-bench.sh --check         # compare against the baseline
#   ./scripts/selfhost-bench.sh --record        # overwrite the baseline
#   ./scripts/selfhost-bench.sh -n 5 --check    # more samples
#
# ## What is measured, and why it is a ratio
#
# `selfhost-fixpoint.sh` runs three builds, and they are not the same build:
#
#   pass A   the *seed* (a published release) compiles HEAD
#   pass B   A compiles HEAD
#   pass C   B compiles HEAD
#
# Only B and C run HEAD's own code generator over HEAD's own sources. Pass A
# runs a fixed, already-published artifact -- so it is structurally immune to
# anything HEAD changes, including the pure-Dawn collections of D2/D3, which
# is exactly what makes it a control group.
#
# The number this reports is therefore `passC_user / passA_user` from a single
# run. Both passes compile the same sources on the same machine in the same
# minute, so CPU model, core count, JVM, disk and source-tree growth divide
# out, and a baseline checked into the repository means something on a machine
# that has never seen this one. It is also the same shape as the +11% that
# docs/collections-dejava-research.md 9.2 measured (one compile command, with
# and without a perturbation).
#
# ## What is not measured
#
# * **wall** -- 4.2% spread here against 2.1% for user, worse with a cold
#   page cache. It is recorded for context and never compared.
# * **RSS** -- the same tree under the same heap limit reports 3.64GB on one
#   JVM and 2.53GB on another. It is a property of the collector, not of the
#   compiler. Recorded, never compared.
#
# Pinning `-Xmx` would make RSS comparable and change what is being measured;
# the bootstrap runs on the default heap, so this does too.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
. scripts/seedjar.sh

baseline="$ROOT/scripts/selfhost-bench.baseline"
samples=3
mode=print

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) mode=check; shift ;;
    --record) mode=record; shift ;;
    -n) samples="$2"; shift 2 ;;
    *) echo "usage: $0 [--check|--record] [-n samples]" >&2; exit 2 ;;
  esac
done

OUT=${TMPDIR:-/tmp}/selfhost-bench.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

VENDOR=(--std std --embed-std std
  --vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi)

SEED="$(seed_jar)"
seed_tag=$(tr -d ' \n' < "$ROOT/scripts/seed-release.txt")

# user milliseconds of one build. bash's `time` keyword with an explicit
# TIMEFORMAT, so there is no locale-dependent parsing and no dependency on an
# external time(1). `times` cannot be used: `$(times)` accounts inside its own
# subshell, which has no children, and reports zero.
run_user_ms() {
  local jar="$1" out="$2" secs
  secs=$( { TIMEFORMAT='%3U'; time java -Xss512m -jar "$jar" build selfhost \
    -o "$out" "${VENDOR[@]}" > /dev/null 2>/dev/null; } 2>&1 )
  python3 -c "print(int(round(float('$secs') * 1000)))"
}

wall_ms() {
  local start end
  start=$(date +%s%3N)
  "$@" > /dev/null
  end=$(date +%s%3N)
  echo $((end - start))
}

echo "seed $seed_tag, $samples sample(s) after a warm-up" >&2

# warm-up: never counted. The first JIT profile and the first page-cache pass
# are worth ~20% on wall and are not what this is measuring.
java -Xss512m -jar "$SEED" build selfhost -o "$OUT/warm.jar" "${VENDOR[@]}" > /dev/null

> "$OUT/samples"
for i in $(seq 1 "$samples"); do
  a_ms=$(run_user_ms "$SEED" "$OUT/a.jar")
  b_ms=$(run_user_ms "$OUT/a.jar" "$OUT/b.jar")
  c_ms=$(run_user_ms "$OUT/b.jar" "$OUT/c.jar")
  r=$(python3 -c "print(f'{$c_ms/$a_ms:.4f}')")
  printf '  sample %d  A %sms  B %sms  C %sms  ratio %s\n' "$i" "$a_ms" "$b_ms" "$c_ms" "$r" >&2
  echo "$r $a_ms $c_ms" >> "$OUT/samples"
done

# The ratio is formed *within* a sample -- taking the best A and the best C
# from different samples would divide two different machines.
#
# Across samples the estimator is the median, not the minimum. Noise on each
# individual pass is one-sided (something else ran, so it can only be slower),
# which is why a best-of is right for a single duration. But the ratio's noise
# is two-sided: a slow A pushes it down exactly as a slow C pushes it up, so a
# minimum systematically picks the sample where the *denominator* was worst.
read -r ratio best_a best_c spread <<EOF
$(python3 - "$OUT/samples" <<'PY'
import sys
rows = [l.split() for l in open(sys.argv[1]) if l.strip()]
rows.sort(key=lambda r: float(r[0]))
med = rows[len(rows) // 2]
lo, hi = float(rows[0][0]), float(rows[-1][0])
print(med[0], med[1], med[2], f"{(hi - lo) / float(med[0]) * 100:.1f}")
PY
)
EOF
c_wall=$(wall_ms java -Xss512m -jar "$OUT/b.jar" build selfhost -o "$OUT/w.jar" "${VENDOR[@]}")
java_id=$(java -version 2>&1 | head -1 | tr -d '"')

printf 'ratio   %s   (passC %sms / passA %sms, user, median of %s; spread %s%%)\n' \
  "$ratio" "$best_c" "$best_a" "$samples" "$spread"

# A budget the measurement cannot resolve is not a gate. Say so rather than
# reporting a pass or a fail that the noise decided.
noisy=$(python3 -c "print(1 if $spread > 15 else 0)")
if [ "$noisy" = 1 ]; then
  echo "warning: sample spread ${spread}% is at or above the +15% budget --" >&2
  echo "         this machine is too busy to resolve it. Re-run quiet, or -n higher." >&2
fi

write_baseline() {
  cat > "$baseline" <<EOF
# Bootstrap cost baseline. See scripts/selfhost-bench.sh for what the ratio is
# and why it, rather than a number of seconds, is the thing compared.
#
# ratio = passC_user / passA_user in a single run: HEAD compiling HEAD over a
# published seed compiling HEAD. Both halves see the same machine, so this
# transfers between machines; the context block below does not, and is
# recorded only so a surprising ratio has something to be read against.
ratio $ratio
seed $seed_tag
tolerance 0.15

# context (recorded, never compared)
context samples $samples
context spread_pct $spread
context passA_user_ms $best_a
context passC_user_ms $best_c
context passC_wall_ms $c_wall
context java $java_id
context recorded_by scripts/selfhost-bench.sh
EOF
  echo "wrote $baseline" >&2
}

case "$mode" in
  record) write_baseline ;;
  check)
    if [ ! -f "$baseline" ]; then
      echo "FAIL: no baseline; run --record first" >&2
      exit 1
    fi
    base_ratio=$(awk '$1=="ratio"{print $2}' "$baseline")
    base_seed=$(awk '$1=="seed"{print $2}' "$baseline")
    tol=$(awk '$1=="tolerance"{print $2}' "$baseline")
    # the seed is the denominator. A different one is a different measurement,
    # so refuse rather than compare: re-record deliberately after a bump.
    if [ "$base_seed" != "$seed_tag" ]; then
      echo "FAIL: baseline was taken against seed $base_seed, this run used $seed_tag." >&2
      echo "      The seed is the denominator -- re-record after a seed bump." >&2
      exit 2
    fi
    python3 - "$ratio" "$base_ratio" "$tol" <<'PY'
import sys
cur, base, tol = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
limit = base * (1 + tol)
delta = (cur / base - 1) * 100
if cur > limit:
    print(f"FAIL: ratio {cur:.4f} is {delta:+.1f}% against baseline {base:.4f} "
          f"(budget +{tol*100:.0f}%)")
    sys.exit(1)
print(f"ok: ratio {cur:.4f} is {delta:+.1f}% against baseline {base:.4f} "
      f"(budget +{tol*100:.0f}%)")
PY
    ;;
  print) : ;;
esac

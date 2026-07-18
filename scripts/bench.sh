#!/usr/bin/env bash
# Performance guardrail for the JSON example (docs/seq6-research.md §五, step 0).
#
# Reports the *median peak RSS* of parsing a generated corpus. Memory rather
# than wall clock because the signal-to-noise ratio is not close: across runs
# wall varies by tens of percent while peak RSS is stable to a few megabytes,
# and the thing seq6 is about — materializing a whole file as List[Int] — shows
# up as hundreds of megabytes.
#
# Measures a built jar, not `dawn run`: running in-process would fold the
# compiler's own footprint into the number being watched.
#
#   scripts/bench.sh            # default corpus, 5 runs
#   scripts/bench.sh 2000 9     # ~2000 KB corpus, 9 runs
#
# The baseline lives in docs/seq6-research.md. Re-record it there when a change
# is meant to move the number, so a regression stays distinguishable from a win.
set -euo pipefail

cd "$(dirname "$0")/.."

KB="${1:-1000}"
RUNS="${2:-5}"
OUT="build/bench"
CORPUS="$OUT/corpus.json"
JAR="$OUT/json.jar"

mkdir -p "$OUT"

# Deterministic corpus: no seeding from the clock, so two runs on one machine
# are comparable and so is one run on two machines. Mixed scalar types and
# nesting keep every branch of the lexer on the path; the non-ASCII strings are
# deliberate, since code-point handling is exactly what is under measurement.
python3 - "$CORPUS" "$KB" <<'PY'
import json, sys

path, kb = sys.argv[1], int(sys.argv[2])
target = kb * 1024
words = ["alpha", "beta", "gamma", "déjà", "中文", "\U0001f388"]
rows, i = [], 0
while True:
    rows.append({
        "id": i,
        "name": words[i % len(words)] + "-" + str(i),
        "score": i * 1.5,
        "ok": i % 2 == 0,
        "tags": [words[(i + k) % len(words)] for k in range(3)],
        "meta": {"n": i, "prev": None if i == 0 else i - 1},
    })
    i += 1
    if i % 64 == 0 and len(json.dumps(rows)) >= target:
        break
with open(path, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False)
print(f"corpus: {path} ({len(rows)} rows, {round(len(open(path, 'rb').read()) / 1024)} KB)")
PY

echo "building examples/m4/json ..."
./bin/dawn build examples/m4/json -o "$JAR" >/dev/null

# /usr/bin/time reports "Maximum resident set size" in KB on Linux. Guard the
# result: a crashed run prints no such line, and silently treating that as 0
# would read as a spectacular improvement.
rss=()
for _ in $(seq "$RUNS"); do
  log="$OUT/time.txt"
  /usr/bin/time -v java -jar "$JAR" "$CORPUS" >/dev/null 2>"$log" || {
    echo "run failed:" >&2
    tail -20 "$log" >&2
    exit 1
  }
  kb_used=$(awk '/Maximum resident set size/ {print $NF}' "$log")
  [ -n "$kb_used" ] || { echo "no RSS line in $log" >&2; exit 1; }
  rss+=("$kb_used")
done

printf '%s\n' "${rss[@]}" | sort -n | awk -v n="$RUNS" '
  { v[NR] = $1 }
  END {
    med = (n % 2) ? v[(n + 1) / 2] : (v[n / 2] + v[n / 2 + 1]) / 2
    printf "peak RSS: median %.0f MB  (min %.0f, max %.0f, n=%d)\n",
      med / 1024, v[1] / 1024, v[n] / 1024, n
  }'

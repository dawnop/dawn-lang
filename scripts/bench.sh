#!/usr/bin/env bash
# Performance guardrail for the JSON example (docs/seq6-research.md §五, step 0).
#
# Reports the *smallest heap the program completes in*, found by bisection.
#
# Not peak RSS, which is what this script measured until 2026-07-18 and which is
# the wrong number: given a large -Xmx (the default is a quarter of RAM) a JVM
# fills the heap and collects lazily, so peak RSS says how much room the GC was
# given, not how much the program needs. On the 2719 KB corpus that read as
# 259 MB while the program in fact runs in 39 MB — a 6.6x overstatement that made
# an ordinary object graph look like a crisis. See §五之补 for what it cost.
#
# Minimum heap is not a perfect live-set measure either: a program that allocates
# hard but keeps little will sit somewhat above its live set, because the
# collector needs headroom to work in. It is, however, monotone in the thing we
# care about and it cannot be inflated by an idle collector.
#
#   scripts/bench.sh            # default corpus
#   scripts/bench.sh 2000       # ~2000 KB corpus
#
# The baseline lives in docs/seq6-research.md. Re-record it there when a change
# is meant to move the number, so a regression stays distinguishable from a win.
set -euo pipefail

cd "$(dirname "$0")/.."

KB="${1:-1000}"
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

# Bisect -Xmx. `ok` demands the expected output, not just a zero exit: a JVM that
# dies of OutOfMemoryError inside a caught region could otherwise "succeed" while
# printing nothing, and the search would converge on a heap that does not work.
ok() {
  [ "$(java "-Xmx${1}m" -jar "$JAR" "$CORPUS" 2>/dev/null)" = "valid" ]
}

lo=4
hi=2048
ok "$hi" || { echo "does not run even in ${hi}m" >&2; exit 1; }
while [ $((hi - lo)) -gt 2 ]; do
  mid=$(((lo + hi) / 2))
  if ok "$mid"; then hi=$mid; else lo=$mid; fi
done

corpus_kb=$(($(stat -c%s "$CORPUS") / 1024))
echo "minimum heap: ${hi} MB   (corpus ${corpus_kb} KB, ratio $((hi * 1024 / corpus_kb))x)"

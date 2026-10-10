#!/usr/bin/env bash
# Negative controls for site/search-budget.sh (docs/site-search-design.md 13.7,
# 13.11). A gate that has only ever been green has not been shown to be able to
# go red, and this one is made of four comparisons, each of which could be
# wrong (a budget read from the wrong column, a sum that skips the manifest, a
# run that measures nothing). So each number is broken in turn on a copy of the
# real dist, and the gate has to fail on that number and on no other:
#
#   control    the real dist, the real budgets: exit 0
#   fragment   one fragment made incompressibly large: only the fragment
#              budget is over
#   chunk      one postings chunk, one no recorded query fetches, made
#              incompressibly large: only the chunk budget is over
#   manifest   the manifest made larger the same way: the manifest budget is
#              over, and the first-query one with it, the manifest being part
#              of what a first query costs; the chunk and fragment budgets are not
#   first      every English fragment made large, each under the fragment
#              budget: only the first-query budget is over, which is the
#              property that a query costs the sum and not the largest
#   budget     the first-query budget lowered under the measured worst: red,
#              so a budget the file lists is a budget the gate reads
#
# It needs a built dist and the run the build left (site/build/search-budget.run),
# so it runs after site/build.sh, and it spends no JVM start of its own.
set -euo pipefail
cd "$(dirname "$0")/.."
real=site/dist
run=site/build/search-budget.run
[ -d "$real/assets/search-text" ] && [ -d "$real/assets/search-index" ] && [ -s "$run" ] || { echo "error: run site/build.sh first" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fresh() { # a copy of just what the gate reads
  rm -rf "$work/dist"
  mkdir -p "$work/dist/assets"
  cp -r "$real/assets/search-text" "$real/assets/search-index" "$work/dist/assets/"
  cp "$real"/assets/search-body-en.json "$real"/assets/search-body-zh.json "$work/dist/assets/"
}
gate() { # <label> <expected exit> [budgets-file]; stderr to $work/err
  local label="$1" want="$2"
  set +e
  DAWN_SEARCH_BUDGETS="${3:-site/search-budget.txt}" SEARCH_BUDGET_RUN="$run" \
    site/search-budget.sh "$work/dist" > "$work/out" 2> "$work/err"
  local got=$?
  set -e
  if [ "$got" != "$want" ]; then
    echo "FAIL $label: exit $got, wanted $want" >&2
    cat "$work/out" "$work/err" >&2
    exit 1
  fi
}
expect_only() { # <label> <must> [also]: stderr has \`must\`, and no kind of failure but that and \`also\`
  local label="$1" must="$2" also="${3:-}"
  grep -q -- "$must" "$work/err" || { echo "FAIL $label: stderr lacks \`$must\`" >&2; cat "$work/err" >&2; exit 1; }
  for kind in "manifest budget" "chunk budget" "fragment budget" "on first query"; do
    if [ "$kind" != "$must" ] && [ "$kind" != "$also" ] && grep -q -- "$kind" "$work/err"; then
      echo "FAIL $label: also failed on \`$kind\`" >&2; cat "$work/err" >&2; exit 1
    fi
  done
}

# random hex of about $1 characters: incompressible beyond 4 bits a character
junk() { python3 -c 'import secrets,sys; print(secrets.token_hex(int(sys.argv[1]) // 2))' "$1"; }

fresh
gate control 0
echo "ok control: the real assets pass"

fresh
python3 - "$work/dist/assets/search-text/en" <<'PY'
import sys, glob, json, secrets
# the largest fragment, written back as valid JSON holding 32000 random characters
f = sorted(glob.glob(sys.argv[1] + '/*.json'))[0]
sec = json.load(open(f))[0]
open(f, 'w').write(json.dumps([sec, [secrets.token_hex(16000)]]) + "\n")
PY
gate fragment 1
expect_only fragment "fragment budget"
echo "ok fragment: one oversized fragment turns the gate red, on the fragment budget alone"

fresh
python3 - "$work/dist/assets/search-index/en" "$run" <<'PY'
import sys, glob, json, secrets, os
# a chunk no recorded query fetches, written back as a valid chunk holding one
# extra 32000-character word-less filler: the gate reads sizes, not words
asked = set()
for line in open(sys.argv[2]):
    asked.update(line.split('\t')[0].split()[2:])
for f in sorted(glob.glob(sys.argv[1] + '/*.json')):
    if 'search-index/en/' + os.path.basename(f) not in asked:
        c = json.load(open(f))
        c[1].append(secrets.token_hex(16000))
        c[2].append([1])
        open(f, 'w').write(json.dumps(c, ensure_ascii=False, separators=(',', ':')) + "\n")
        break
else:
    sys.exit("every chunk is fetched by some recorded query")
PY
gate chunk 1
expect_only chunk "chunk budget"
echo "ok chunk: one oversized chunk turns the gate red, on the chunk budget alone"

fresh
python3 - "$work/dist/assets/search-body-en.json" <<'PY'
import sys, json, secrets
p = sys.argv[1]
ix = json.load(open(p))
ix[2][0][2] = ix[2][0][2] + " " + secrets.token_hex(20000)
open(p, 'w').write(json.dumps(ix, ensure_ascii=False, separators=(',', ':')) + "\n")
PY
gate manifest 1
# a larger manifest is also a dearer first query, by exactly its size
expect_only manifest "manifest budget" "on first query"
echo "ok manifest: an oversized manifest turns the gate red, on the manifest budget (and so on the first query it is part of)"

fresh
python3 - "$work/dist/assets/search-text/en" <<'PY'
import sys, glob, json, secrets, gzip
# every fragment padded with random text until it is about 11 KB gzip, inside
# the 12 KB fragment budget
def size(sec, texts, pad):
    out = json.dumps([sec, texts + [pad]], ensure_ascii=False, separators=(',', ':')) + "\n"
    return out, len(gzip.compress(out.encode(), 9))
for f in glob.glob(sys.argv[1] + '/*.json'):
    sec, texts = json.load(open(f))
    lo, hi = 0, 40000
    while hi - lo > 40:
        mid = (lo + hi) // 2
        if size(sec, texts, secrets.token_hex(mid // 2))[1] < 11000:
            lo = mid
        else:
            hi = mid
    out, n = size(sec, texts, secrets.token_hex(lo // 2))
    assert 10000 < n < 11900, n
    open(f, 'w').write(out)
PY
gate first 1
expect_only first "on first query"
echo "ok first: large fragments, each within its budget, turn the gate red on the first-query budget alone"

fresh
sed 's/^en first .*/en first 1000/' site/search-budget.txt > "$work/budgets.txt"
gate budget 1 "$work/budgets.txt"
grep -q "on first query" "$work/err" || { echo "FAIL budget: the lowered first-query budget was not read" >&2; exit 1; }
echo "ok budget: a lowered budget in the file is the budget the gate holds"

echo "search budget gate: every negative control went red as and where it should"

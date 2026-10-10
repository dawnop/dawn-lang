#!/usr/bin/env bash
# The search assets' size gate (docs/site-search-design.md 13.7): three numbers
# per language, each held against site/search-budget.txt, any over -> exit 1.
#
#   index      the gzip size of search-body-<lang>.json: what every reader who
#              types pays before the first result, and the part of the cost
#              that grows with the vocabulary, not with the prose
#   fragment   the largest single text fragment's gzip size: what one row can
#              cost, and the one number that says a section grew past what a
#              row should have to fetch
#   first      the worst first-query bytes over site/search-queries.txt: the
#              index plus every fragment the panel fetches for the query, run
#              by the panel's own code on these assets (site/search-budget/)
#
# Total bytes are not a number here: a reader never downloads the total (13.1),
# so a gate on it would turn every added paragraph into an argument about a
# figure nobody pays. Sizes are `gzip -9`, the same measure as before 13 and as
# the server's precompressed files.
#
# Usage: site/search-budget.sh [dist-dir]       (default site/dist)
#   DAWN_SEARCH_BUDGETS=<file>   the budgets (default site/search-budget.txt)
#   SEARCH_BUDGET_SKIP_QUERIES=1 measure the first two numbers only
#   SEARCH_BUDGET_RUN=<file>     use that recorded run of the panel instead of
#                                making one (site/build/search-budget.run is
#                                what a run leaves); the self-test's use
set -euo pipefail
cd "$(dirname "$0")/.."
dist="${1:-site/dist}"
budgets="${DAWN_SEARCH_BUDGETS:-site/search-budget.txt}"

gz() { gzip -9c "$1" | wc -c; }

# budget <lang> <what>: the number in the budgets file, or fail loudly
budget() {
  local v
  v="$(awk -v l="$1" -v w="$2" '$1 == l && $2 == w { print $3 }' "$budgets")"
  if [ -z "$v" ]; then
    echo "error: $budgets has no \`$1 $2\` budget" >&2
    exit 2
  fi
  echo "$v"
}

over=0
for lang in en zh; do
  index="$dist/assets/search-body-$lang.json"
  [ -f "$index" ] || { echo "error: $index is missing" >&2; exit 2; }

  # 1. the index
  index_gz=$(gz "$index")
  index_budget=$(budget "$lang" index)
  echo "  search $lang index: $(wc -c < "$index") bytes raw, $index_gz bytes gzip (budget $index_budget)"
  if [ "$index_gz" -gt "$index_budget" ]; then
    echo "error: $index is over its $index_budget byte gzip budget (docs/site-search-design.md 13.7)" >&2
    over=1
  fi

  # 2. the largest fragment
  frag_max=0
  frag_name=""
  frag_n=0
  frag_total=0
  for f in "$dist/assets/search-text/$lang"/*.json; do
    [ -f "$f" ] || { echo "error: no fragments under $dist/assets/search-text/$lang" >&2; exit 2; }
    n=$(gz "$f")
    frag_n=$((frag_n + 1))
    frag_total=$((frag_total + n))
    if [ "$n" -gt "$frag_max" ]; then
      frag_max=$n
      frag_name=$(basename "$f")
    fi
  done
  frag_budget=$(budget "$lang" fragment)
  echo "  search $lang fragments: $frag_n files, $frag_total bytes gzip together, largest $frag_name $frag_max bytes (budget $frag_budget)"
  if [ "$frag_max" -gt "$frag_budget" ]; then
    echo "error: $frag_name ($lang) is over its $frag_budget byte gzip fragment budget (docs/site-search-design.md 13.7)" >&2
    over=1
  fi
done

# 3. the first query, on the panel's own code
if [ "${SEARCH_BUDGET_SKIP_QUERIES:-0}" != 1 ]; then
  # The run is kept where the self-test can find it: what the panel asks for
  # depends on the dist and the sample, not on the sizes, so a dist whose files
  # were made larger (the self-test's) is measured against the same run.
  out="${SEARCH_BUDGET_RUN:-site/build/search-budget.run}"
  if [ -z "${SEARCH_BUDGET_RUN:-}" ]; then
    mkdir -p "$(dirname "$out")"
    DAWN_SEARCH_DIST="$dist" ./bin/dawn run site/search-budget > "$out"
  elif [ ! -s "$out" ]; then
    echo "error: SEARCH_BUDGET_RUN=$out is empty or missing; run site/build.sh first" >&2
    exit 2
  fi
  for lang in en zh; do
    index_gz=$(gz "$dist/assets/search-body-$lang.json")
    first_budget=$(budget "$lang" first)
    worst=0
    worst_q=""
    while IFS=$'\t' read -r head q; do
      read -r _ l frags <<< "$head"
      [ "$l" = "$lang" ] || continue
      bytes=$index_gz
      n=0
      for p in $frags; do
        bytes=$((bytes + $(gz "$dist/assets/$p")))
        n=$((n + 1))
      done
      printf '    %-2s %-34s %2d fragment(s), %6d bytes\n' "$lang" "$q" "$n" "$bytes"
      if [ "$bytes" -gt "$worst" ]; then
        worst=$bytes
        worst_q=$q
      fi
    done < <(grep '^query ' "$out")
    echo "  search $lang first query: worst \`$worst_q\` $worst bytes gzip (budget $first_budget)"
    if [ "$worst" -eq 0 ]; then
      echo "error: no $lang query was measured; the sample file or the run is broken" >&2
      over=1
    fi
    if [ "$worst" -gt "$first_budget" ]; then
      echo "error: \`$worst_q\` ($lang) costs $worst bytes gzip on first query, over its $first_budget budget (docs/site-search-design.md 13.7)" >&2
      over=1
    fi
  done
fi

exit "$over"

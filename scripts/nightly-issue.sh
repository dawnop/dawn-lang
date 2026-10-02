#!/usr/bin/env bash
# Turn a red scheduled check into an issue, once per title, and comment on it
# again only when the verdict changes.
#
#   scripts/nightly-issue.sh "<fixed title>" <body file>
#   scripts/nightly-issue.sh --self-test
#
# Why: a scheduled run blocks nothing, so a red one that only paints the
# Actions page is a red nobody sees. Rust's reference repository runs its
# grammar check on the same arrangement -- the check runs on a schedule, and a
# failure opens "Daily Grammar Check Failed - <date>" (rust-lang/reference
# #2332, #2359). Here the title is fixed rather than dated: while an issue
# with the same title is open, a new failure is a comment on it, not a second
# issue.
#
# THE VERDICT LINE (2026-09-30, issue #231). A report that stays red for a
# week used to add seven comments that said the same thing, which is noise
# that teaches people to skip the thread. So every body carries one line
#
#     <!-- verdict: <keys> -->
#
# naming WHY it is red, not by how much: scripts/gate-totals.py writes its
# limit keys there (`ratio`, `ratio-rise`, `shape-growth`, `tile`). A body
# without one gets `<!-- verdict: digest-<sha256 prefix> -->` of its lines
# other than the `Run:` link, so an identical report is not repeated and a
# changed one is. The comment is posted only when the line differs from the
# one in the issue's latest comment (or in the issue body, when there is no
# comment yet); otherwise the step summary says so and nothing is posted.
#
# THE LOOKUP IS REST, NOT SEARCH. `gh issue list --search` goes through the
# GraphQL search index, and on 2026-09-29 it answered 500, so #231 missed that
# night's entry. The open issues are listed with `gh api
# repos/<repo>/issues?state=open&per_page=100` and filtered by exact title
# with jq (pull requests, which that endpoint also returns, are dropped).
# Every API read is tried three times with a backoff (5s, then 15s;
# NIGHTLY_ISSUE_BACKOFF=0 in the self-test).
#
# Needs GH_TOKEN with `issues: write`; the calling job declares it. The
# self-test puts a stub `gh` first on PATH and needs no token and no network.
set -euo pipefail

backoff_unit=${NIGHTLY_ISSUE_BACKOFF:-5}

# gh api with three tries; the output is the last try's.
api() {
  local try out
  for try in 1 2 3; do
    if out=$(gh api "$@"); then
      printf '%s' "$out"
      return 0
    fi
    if [ "$try" -lt 3 ]; then
      echo "gh api $1 failed (try $try of 3); retrying" >&2
      sleep $((backoff_unit * (try == 1 ? 1 : 3)))
    fi
  done
  echo "error: gh api $1 failed three times" >&2
  return 1
}

verdict_of() {
  grep -o '<!-- verdict: [^>]* -->' | tail -n 1 || true
}

summary() {
  echo "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$1" >> "$GITHUB_STEP_SUMMARY"
  fi
}

report() {
  # The repository the workflow runs in, else the one scripts/repo.env names.
  local title=$1 body=$2 repo=${GITHUB_REPOSITORY:-${DAWN_GITHUB_REPO:-}}
  if [ -z "$repo" ]; then
    repo=$(. "$(dirname "$0")/repo.env" && printf '%s' "$DAWN_GITHUB_REPO")
  fi
  local verdict posted listing number comments last
  verdict=$(verdict_of < "$body")
  posted=$(mktemp)
  cp "$body" "$posted"
  if [ -z "$verdict" ]; then
    verdict="<!-- verdict: digest-$(grep -v '^Run: ' "$body" | sha256sum | cut -c1-16) -->"
    printf '\n%s\n' "$verdict" >> "$posted"
  fi

  listing=$(api "repos/$repo/issues?state=open&per_page=100")
  read -r number comments < <(printf '%s' "$listing" | jq -r --arg t "$title" \
    'map(select(.pull_request == null and .title == $t)) | .[0]
     | if . == null then "" else "\(.number) \(.comments)" end') || true

  if [ -z "${number:-}" ]; then
    gh issue create --repo "$repo" --title "$title" --body-file "$posted"
    rm -f "$posted"
    return 0
  fi

  if [ "${comments:-0}" -gt 0 ]; then
    last=$(api "repos/$repo/issues/$number/comments?per_page=1&page=$comments" |
      jq -r '.[0].body // ""' | verdict_of)
  else
    last=$(api "repos/$repo/issues/$number" | jq -r '.body // ""' | verdict_of)
  fi

  if [ "$last" = "$verdict" ]; then
    summary "#$number ($title) is open with the same verdict, $verdict; not commented again"
  else
    gh issue comment "$number" --repo "$repo" --body-file "$posted"
    summary "commented on #$number ($title): verdict ${last:-(none)} -> $verdict"
  fi
  rm -f "$posted"
}

# --- self-test ---------------------------------------------------------------
#
# A stub gh serves fixtures from $STUB: issues.json for the listing,
# comments.json and issue.json for the reads, fail-list=<n> to fail the
# listing n times first; every create and comment is appended to calls.txt.
self_test() {
  local work stub failures=0
  work=$(mktemp -d)
  stub="$work/bin"
  mkdir -p "$stub"
  cat > "$stub/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  api)
    case "$2" in
      */issues\?state=open*)
        if [ -f "$STUB/fail-list" ]; then
          left=$(cat "$STUB/fail-list")
          if [ "$left" -gt 0 ]; then
            echo $((left - 1)) > "$STUB/fail-list"
            echo "HTTP 500" >&2
            exit 1
          fi
        fi
        cat "$STUB/issues.json" ;;
      */comments\?*) cat "$STUB/comments.json" ;;
      */issues/*) cat "$STUB/issue.json" ;;
      *) echo "stub: unexpected api $2" >&2; exit 1 ;;
    esac ;;
  issue) echo "$2 $3" >> "$STUB/calls.txt" ;;
  *) echo "stub: unexpected $*" >&2; exit 1 ;;
esac
STUB
  chmod +x "$stub/gh"

  # case <label> <want calls> <issues.json> <comments.json> <issue.json> <body> [fail-list]
  run_case() {
    local label=$1 want=$2 dir got
    dir=$(mktemp -d "$work/case.XXXX")
    printf '%s' "$3" > "$dir/issues.json"
    printf '%s' "$4" > "$dir/comments.json"
    printf '%s' "$5" > "$dir/issue.json"
    printf '%s\n' "$6" > "$dir/body.md"
    [ -n "${7:-}" ] && echo "$7" > "$dir/fail-list"
    : > "$dir/calls.txt"
    if STUB=$dir PATH="$stub:$PATH" NIGHTLY_ISSUE_BACKOFF=0 GITHUB_STEP_SUMMARY='' \
        GITHUB_REPOSITORY=o/r "$0" "nightly: gate totals over their limits" \
        "$dir/body.md" > "$dir/out.txt" 2>&1; then
      got=$(tr '\n' ';' < "$dir/calls.txt")
    else
      got="exit $?"
    fi
    if [ "$got" = "$want" ]; then
      echo "  $label: ${got:-nothing posted}"
    else
      echo "SELF-TEST FAIL: $label: expected '${want:-nothing posted}', got '$got'" >&2
      sed 's/^/    /' "$dir/out.txt" >&2
      failures=$((failures + 1))
    fi
  }

  local title='nightly: gate totals over their limits'
  local open="[{\"number\":7,\"title\":\"$title\",\"comments\":2}]"
  local fresh="[{\"number\":7,\"title\":\"$title\",\"comments\":0}]"
  local c_tile='[{"body":"old table\n<!-- verdict: tile -->"}]'
  local c_both='[{"body":"old table\n<!-- verdict: ratio,tile -->"}]'
  local i_tile='{"body":"first report\n<!-- verdict: tile -->"}'
  local body_tile
  body_tile=$(printf 'table\n<!-- verdict: tile -->')

  run_case "no open issue: create" "create --repo;" '[]' '[]' '{}' "$body_tile"
  run_case "last comment has the same verdict: silent" "" "$open" "$c_tile" '{}' "$body_tile"
  run_case "last comment has another verdict: comment" "comment 7;" "$open" "$c_both" '{}' "$body_tile"
  run_case "no comment yet, issue body has the same verdict: silent" "" "$fresh" '[]' "$i_tile" "$body_tile"
  run_case "no comment yet, issue body has another verdict: comment" "comment 7;" "$fresh" '[]' \
    '{"body":"first report\n<!-- verdict: ratio -->"}' "$body_tile"
  run_case "a longer title and a pull request are not the issue" "create --repo;" \
    "[{\"number\":8,\"title\":\"$title (old)\",\"comments\":0},{\"number\":9,\"title\":\"$title\",\"comments\":0,\"pull_request\":{}}]" \
    '[]' '{}' "$body_tile"
  run_case "the listing fails twice, then answers" "" "$open" "$c_tile" '{}' "$body_tile" 2
  run_case "the listing fails three times: red" "exit 1" "$open" "$c_tile" '{}' "$body_tile" 3
  run_case "no verdict line, same digest as the last comment: silent" "" "$open" \
    "[{\"body\":\"x\\n<!-- verdict: digest-$(printf 'plain report\n' | sha256sum | cut -c1-16) -->\"}]" \
    '{}' "plain report
Run: https://example/1"
  run_case "no verdict line, different report: comment" "comment 7;" "$open" "$c_tile" '{}' "other report"

  if [ "$failures" -ne 0 ]; then
    echo "self-test: $failures case(s) failed" >&2
    return 1
  fi
  echo "self-test: 10 cases, the verdict and the lookup as documented"
  rm -r -- "${work:?}"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit $?
fi
if [ $# -ne 2 ] || [ ! -f "$2" ]; then
  echo "usage: $0 <title> <body file> | --self-test" >&2
  exit 2
fi
report "$1" "$2"

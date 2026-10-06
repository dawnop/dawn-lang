#!/usr/bin/env bash
# The Emit-Change parser's own gate (#124).
#
# scripts/emitchange.sh decides whether an emit difference is approved. Its
# failure mode is not a crash: a declaration it cannot read becomes a rule that
# matches nothing, and a declaration that is too broad becomes a rule that
# matches everything -- both are silent, and both make every downstream gate
# print a green that means nothing. A parser like that has to be exercised by
# inputs that are *supposed* to fail, or its green is only evidence that it was
# never asked a question.
#
# So: fixed declaration texts in, accept/refuse out. No JVM, no seed, no repo
# history (the range leg cases build a throwaway one) -- EMITCHANGE_SOURCE
# feeds the declarations and EMITCHANGE_LABELS the registry, which is also how
# the gate stays cheap enough to run everywhere.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

# shellcheck source=scripts/emitchange.sh
. scripts/emitchange.sh
# shellcheck source=scripts/emitrange.sh
. scripts/emitrange.sh

OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

cat > "$OUT/labels.txt" <<'EOF'
# a stand-in registry
emit selfhost
emit site
lsp
fmt
doc --builtins
add (maven coordinate)
cli error (doc $TMP/nope)
test playground (with [deps])
EOF
export EMITCHANGE_LABELS="$OUT/labels.txt"

pass=0
fail=0

# `emitchange_load` on one declaration line, in a subshell so a failure cannot
# poison the next case.
load_one() { # text
  printf '%s\n' "$1" > "$OUT/src.txt"
  ( export EMITCHANGE_SOURCE="$OUT/src.txt"; emitchange_load ) > "$OUT/log.txt" 2>&1
}

accepts() { # description, text
  if load_one "$2"; then
    echo "ok   accepts  $1"
    pass=$((pass + 1))
  else
    echo "FAIL accepts  $1 -- refused:"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  fi
}

refuses() { # description, text, expected substring of the message
  if load_one "$2"; then
    echo "FAIL refuses  $1 -- accepted in silence"
    fail=$((fail + 1))
  elif grep -qF -- "$3" "$OUT/log.txt"; then
    echo "ok   refuses  $1"
    pass=$((pass + 1))
  else
    echo "FAIL refuses  $1 -- refused, but not for the stated reason ('$3'):"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  fi
}

# ---- the shapes that must be accepted -----------------------------------
accepts "a plain declaration" \
  'Emit-Change(emit selfhost): the parser is part of the compiler'
accepts "a label containing parentheses" \
  'Emit-Change(add (maven coordinate)): the summary names the resolved version'
accepts "a label containing a flag" \
  'Emit-Change(doc --builtins): bracket joins the builtin table'
accepts "a registered label that spells a bracket (matched by equality, not as a glob)" \
  'Emit-Change(test playground (with [deps])): a test asserts a new message'
accepts "prose that merely mentions the word" \
  'Emit-Change, as REL-02 defines it, is a commit-message line'
accepts "no declarations at all" ''

# ---- the shapes that must be refused ------------------------------------
refuses "the bare wildcard" \
  'Emit-Change(*): the jar layout changed wholesale' \
  'glob in the scope'
# shellcheck disable=SC2016  # the declaration text is data, quoted verbatim
refuses "a trailing wildcard (the #124 shape)" \
  'Emit-Change(emit *): every jar gains the `Index` trait interface class' \
  'glob in the scope'
refuses "a suffix wildcard on a label that needs none" \
  'Emit-Change(lsp*): completion lists all five prelude traits' \
  'glob in the scope'
refuses "a character class" \
  'Emit-Change(emit [sp]*): two corpora' \
  'glob in the scope'
refuses "the unscoped historical wildcard" \
  'Emit-Change: catch_panic no longer catches VirtualMachineError' \
  'unscoped declaration'
refuses "the unscoped form that means the opposite" \
  'Emit-Change: none (docs only)' \
  'unscoped declaration'
refuses "unbalanced parentheses (the real malformed one)" \
  'Emit-Change(cli error (doc*): the usage line names --stdlib' \
  'unbalanced parentheses'
refuses "unbalanced parentheses with no glob to hide behind" \
  'Emit-Change(cli error (doc): the usage line names --stdlib' \
  'unbalanced parentheses'
refuses "no terminator" \
  'Emit-Change(emit selfhost) errors carry offsets' \
  'malformed declaration'
refuses "an empty scope" \
  'Emit-Change(): errors carry offsets' \
  'empty scope'
refuses "no reason" \
  'Emit-Change(emit selfhost): ' \
  'no reason'
refuses "a label no differential prints" \
  'Emit-Change(core *): for..in now lowers through the Iter trait' \
  'glob in the scope'
refuses "a label no differential prints, spelled without a glob" \
  'Emit-Change(core selfhost): for..in now lowers through the Iter trait' \
  'unknown label'
refuses "a typo in a real label" \
  'Emit-Change(emit selhost): errors carry offsets' \
  'unknown label'
refuses "a target that is not in the corpus" \
  'Emit-Change(emit packages/json): errors carry offsets' \
  'unknown label'

# ---- one bad line poisons the window, however many good ones surround it -
refuses "a bad declaration among good ones" \
  'Emit-Change(emit selfhost): fine
Emit-Change(emit *): not fine
Emit-Change(lsp): also fine' \
  'glob in the scope'

# ---- emit_gate: the decision itself -------------------------------------
gate() { # declarations, label, differs
  printf '%s\n' "$1" > "$OUT/src.txt"
  ( export EMITCHANGE_SOURCE="$OUT/src.txt"
    emitchange_load && emit_gate "$2" "$3" ) > "$OUT/log.txt" 2>&1
}

gate_pass() { # description, declarations, label, differs, expected prefix
  if gate "$2" "$3" "$4" && grep -q "^$5" "$OUT/log.txt"; then
    echo "ok   gate     $1"
    pass=$((pass + 1))
  else
    echo "FAIL gate     $1 -- wanted a passing '$5':"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  fi
}

gate_fail() { # description, declarations, label, differs, expected substring
  if gate "$2" "$3" "$4"; then
    echo "FAIL gate     $1 -- passed, and should not have:"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  elif grep -qF -- "$5" "$OUT/log.txt"; then
    echo "ok   gate     $1"
    pass=$((pass + 1))
  else
    echo "FAIL gate     $1 -- failed for the wrong reason ('$5'):"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  fi
}

gate_pass "identical, undeclared" '' 'emit selfhost' 0 'OK'
gate_pass "differs, declared" \
  'Emit-Change(emit selfhost): the parser is part of the compiler' \
  'emit selfhost' 1 'NOTE'
gate_pass "identical, declared (informational, not a gate)" \
  'Emit-Change(emit selfhost): the parser is part of the compiler' \
  'emit selfhost' 0 'OK'
gate_fail "differs, undeclared" '' 'emit selfhost' 1 \
  'no commit since the tag declares it'
gate_fail "differs, and only a *sibling* label is declared" \
  'Emit-Change(emit site): class-file version 61 -> 49' \
  'emit selfhost' 1 'no commit since the tag declares it'
gate_fail "a check whose label is not registered" '' 'emit playground' 0 \
  'not registered'

# ---- the range leg (scripts/emitrange.sh): scope is the change, not the window
#
# The failure this guards is silence in the other direction: a window
# declaration (any commit since the seed tag) must not approve a difference the
# range leg sees, or the second baseline is the first one again. The window text
# goes to EMITCHANGE_SOURCE, the change's own commits to EMITCHANGE_RANGE_SOURCE.
range_gate() { # window declarations, range declarations, label, differs
  printf '%s\n' "$1" > "$OUT/win.txt"
  printf '%s\n' "$2" > "$OUT/rng.txt"
  ( export EMITCHANGE_MODE=range EMITCHANGE_SOURCE="$OUT/win.txt" \
      EMITCHANGE_RANGE_SOURCE="$OUT/rng.txt" EMITCHANGE_RANGE="aaa111..HEAD" \
      EMITCHANGE_BASE=aaa111aaa111aaa111
    emitchange_load && emit_gate "$3" "$4" ) > "$OUT/log.txt" 2>&1
}

range_pass() { # description, window, range, label, differs, expected prefix
  if range_gate "$2" "$3" "$4" "$5" && grep -q "^$6" "$OUT/log.txt"; then
    echo "ok   range    $1"
    pass=$((pass + 1))
  else
    echo "FAIL range    $1 -- wanted a passing '$6':"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  fi
}

range_refused() { # description, window, range, label, differs, expected substring
  if range_gate "$2" "$3" "$4" "$5"; then
    echo "FAIL range    $1 -- passed, and should not have:"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  elif grep -qF -- "$6" "$OUT/log.txt"; then
    echo "ok   range    $1"
    pass=$((pass + 1))
  else
    echo "FAIL range    $1 -- failed for the wrong reason ('$6'):"
    sed 's/^/       /' "$OUT/log.txt"
    fail=$((fail + 1))
  fi
}

# S1: the window declares it, the change does not.
range_refused "a window declaration does not approve a range difference" \
  'Emit-Change(emit selfhost): declared three commits ago' '' \
  'emit selfhost' 1 'no commit in aaa111..HEAD declares it'
range_refused "the failure names the base" \
  'Emit-Change(lsp): declared long ago' '' 'lsp' 1 'vs base aaa111aaa111'
# S2: the change declares it.
range_pass "a range declaration approves a range difference" \
  '' 'Emit-Change(emit selfhost): this change moved it' \
  'emit selfhost' 1 'NOTE emit selfhost differs .*declared in aaa111..HEAD'
range_refused "a sibling label in the range does not approve" \
  '' 'Emit-Change(emit site): another corpus' 'emit selfhost' 1 'no commit in'
range_pass "identical stays OK in range mode" '' '' 'fmt' 0 'OK'
range_refused "an unregistered label still fails in range mode" '' '' 'emit playground' 0 \
  'not registered'
# the range's own declarations are parsed as strictly as the window's
range_refused "a glob in the range's declarations" '' 'Emit-Change(emit *): all of it' \
  'emit selfhost' 1 'glob in the scope'

# range mode with no range at all must fail rather than fall back to the window
if ( export EMITCHANGE_MODE=range EMITCHANGE_SOURCE="$OUT/win.txt"; unset EMITCHANGE_RANGE_SOURCE EMITCHANGE_RANGE
     emitchange_load ) > "$OUT/log.txt" 2>&1; then
  echo "FAIL range    range mode without a range was accepted"
  fail=$((fail + 1))
elif grep -qF 'range mode without a range' "$OUT/log.txt"; then
  echo "ok   range    range mode without a range does not fall back to the window"
  pass=$((pass + 1))
else
  echo "FAIL range    range mode without a range failed for the wrong reason:"
  sed 's/^/       /' "$OUT/log.txt"
  fail=$((fail + 1))
fi

# S4: the short-circuit and the wiring checks, as pure functions
decide_case() { # description, base-sig, head-sig, inputs-changed, want-status, want-substring
  local got status
  got=$(range_decide "$2" "$3" "$4" 2>&1) && status=0 || status=1
  if [ "$status" = "$5" ] && printf '%s' "$got" | grep -qF -- "$6"; then
    echo "ok   range    $1"
    pass=$((pass + 1))
  else
    echo "FAIL range    $1 -- status $status (wanted $5), output: $got"
    fail=$((fail + 1))
  fi
}
decide_case "equal digests and equal inputs skip" 'source=a bootstrap=b' 'source=a bootstrap=b' 0 0 skip
decide_case "different source digest runs" 'source=a bootstrap=b' 'source=c bootstrap=b' 1 0 run
decide_case "different bootstrap digest runs (a seed advance)" 'source=a bootstrap=b' 'source=a bootstrap=c' 0 0 run
decide_case "equal digests while the inputs differ is a failure, not a skip" \
  'source=a bootstrap=b' 'source=a bootstrap=b' 1 1 'digest is blind or the base is mis-wired'
decide_case "an unreadable digest is a failure" '' 'source=a bootstrap=b' 0 1 'could not be read'
base_case() { # description, base, head, base-root-head, want-status, want-substring
  local got status
  got=$(range_check_base "$2" "$3" "$4" 2>&1) && status=0 || status=1
  if [ "$status" = "$5" ] && { [ -z "$6" ] || printf '%s' "$got" | grep -qF -- "$6"; }; then
    echo "ok   range    $1"
    pass=$((pass + 1))
  else
    echo "FAIL range    $1 -- status $status (wanted $5), output: $got"
    fail=$((fail + 1))
  fi
}
base_case "a distinct base whose root is at that base" aaa bbb aaa 0 ''
base_case "a base equal to HEAD is refused (the identity leg)" bbb bbb bbb 1 'the base is HEAD'
base_case "a base root checked out at HEAD instead of the base is refused" aaa bbb bbb 1 'not at the named base'

# base selection and the git cross-check, on a throwaway history:
#   r0 -- r1 (selfhost change) -- r2 (docs only) -- main; side branch p1 from r1
GIT_ENV=(-c user.name=t -c user.email=t@t -c commit.gpgsign=false)
G="$OUT/repo"
git init -q "$G"
(
  cd "$G" || exit 1
  mkdir -p selfhost docs
  echo 0 > selfhost/a; echo 0 > docs/d
  git add -A; git "${GIT_ENV[@]}" commit -q -m r0
  git branch -M main
  echo 1 > selfhost/a; git "${GIT_ENV[@]}" commit -qam r1
  git checkout -q -b side
  echo p > docs/d; git "${GIT_ENV[@]}" commit -qam p1
  git checkout -q main
  echo 2 > docs/d2; git add -A; git "${GIT_ENV[@]}" commit -q -m r2
  git "${GIT_ENV[@]}" merge -q --no-ff side -m merge-ref 2> /dev/null || true
) > /dev/null 2>&1
resolve_case() { # description, want-base-subject, want-range, env...
  local desc=$1 want_base=$2 want_range=$3
  shift 3
  local out base_subject range
  out=$( cd "$G" && env "$@" bash -c '. '"$ROOT_FOR_TEST"'/scripts/emitrange.sh; range_resolve 2>&1; echo "$EMITCHANGE_BASE $EMITCHANGE_RANGE"' ) || true
  base_subject=$(git -C "$G" log -1 --format=%s "$(printf '%s' "$out" | tail -1 | cut -d' ' -f1)" 2> /dev/null)
  range=$(printf '%s' "$out" | tail -1 | cut -d' ' -f2-)
  # a base is named by sha, which the test cannot spell in advance
  case $range in [0-9a-f]*..HEAD) range="<sha>..HEAD" ;; esac
  if [ "$base_subject" = "$want_base" ] && [ "$range" = "$want_range" ]; then
    echo "ok   range    $desc"
    pass=$((pass + 1))
  else
    echo "FAIL range    $desc -- base '$base_subject' (wanted '$want_base'), range '$range' (wanted '$want_range')"
    fail=$((fail + 1))
  fi
}
ROOT_FOR_TEST=$(pwd)
resolve_case "pull_request: base is the first parent, declarations are the PR's commits" \
  r2 'HEAD^1..HEAD^2' GITHUB_EVENT_NAME=pull_request
resolve_case "push: base is the event's before" \
  r1 '<sha>..HEAD' GITHUB_EVENT_NAME=push EMITCHANGE_PUSH_BEFORE="$(git -C "$G" rev-parse HEAD~2)"
resolve_case "push with a zero before falls back to HEAD^1" \
  r2 '<sha>..HEAD' GITHUB_EVENT_NAME=push EMITCHANGE_PUSH_BEFORE=0000000000000000000000000000000000000000
resolve_case "an explicit base wins" \
  r0 '<sha>..HEAD' EMITCHANGE_BASE_REF="$(git -C "$G" rev-list --max-parents=0 HEAD)"

# the digest cross-check's git half: the compiler's inputs, between two commits
changed_case() { # description, base, head, want-status
  local status
  ( cd "$G" && _er_inputs_changed "$2" "$3" ) && status=0 || status=1
  if [ "$status" = "$4" ]; then
    echo "ok   range    $1"
    pass=$((pass + 1))
  else
    echo "FAIL range    $1 -- status $status (wanted $4)"
    fail=$((fail + 1))
  fi
}
changed_case "a selfhost edit is a compiler-input change" main~3 main~2 1
changed_case "a docs-only change is not" main~2 main~1 0

echo
if [ "$fail" != 0 ]; then
  echo "FAIL: $fail of $((pass + fail)) emitchange cases"
  exit 1
fi
echo "OK: $pass emitchange cases (accept, refuse and gate)"

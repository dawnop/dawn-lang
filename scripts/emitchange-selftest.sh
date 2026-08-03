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
# So: fixed declaration texts in, accept/refuse out. No JVM, no seed, no git
# history -- EMITCHANGE_SOURCE feeds the declarations and EMITCHANGE_LABELS the
# registry, which is also how the gate stays cheap enough to run everywhere.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

# shellcheck source=scripts/emitchange.sh
. scripts/emitchange.sh

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

echo
if [ "$fail" != 0 ]; then
  echo "FAIL: $fail of $((pass + fail)) emitchange cases"
  exit 1
fi
echo "OK: $pass emitchange cases (accept, refuse and gate)"

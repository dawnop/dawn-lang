# shellcheck shell=bash
#
# Emit-Change declarations (REL-02, tightened by task #124). Sourced by the
# four differential gates: selfhost-{prev,run,fmt,lsp}-diff.sh.
#
# ============================ THE LANGUAGE ============================
#
#   Emit-Change(<label>): <why>
#
# <label> is one check label, spelled exactly as the differential prints it,
# and it must be listed in scripts/emit-labels.txt. <why> is free text and
# must not be empty. One label per line -- a change that moves four corpora
# writes four lines:
#
#   Emit-Change(emit packages/json): errors carry offsets
#   Emit-Change(emit selfhost): errors carry offsets
#   Emit-Change(lsp): completion offers `Index` among the prelude traits
#
# Declarations are read from the commit messages between scripts/seed-release.txt
# and HEAD, so a release resets the window.
#
# ======================== WHAT IT REFUSES, AND WHY ========================
#
# 1. No globs -- not `emit *`, not `lsp*`, not `doc --builtins*`.
#
#    A glob does not name a fixed set. `emit *` covers labels that did not
#    exist when the message was written, so the same commit message approves
#    more output as the corpus grows. A declaration is a review artifact; it
#    has to mean one thing forever.
#
#    Measured, both ways. Cost of allowing it: 1b8ee7f declared
#    `Emit-Change(emit *)`; for the rest of that seed window all six emit
#    checks printed NOTE, none printed OK, and prev-diff still printed
#    "undeclared-diff check passed" -- during a large backend refactor, which
#    is exactly when that oracle was worth having. Cost of banning it:
#    7de5bd64 moved the class-file version of all six emit corpora and wrote
#    six explicit lines. Six lines. That is the whole price, and it was paid
#    once already (docs/jvm-base-plan.md, K-A4).
#
#    So: if a change really does move every corpus, say so once per corpus.
#    The next person to face a large legitimate change will want to reach for
#    `*` again. Do not. The typing is not the point; the fixed set is.
#
# 2. No bare `Emit-Change:`. REL-02 kept the unscoped form as "the historical
#    wildcard" for compatibility. Its commonest historical spelling is
#    `Emit-Change: none (docs only)` -- a line whose author means *nothing
#    changed* and whose effect was to exempt every label of every differential.
#    An assertion that nothing changed is not a declaration: leave the line out
#    and say it in prose.
#
# 3. An unparseable declaration is an error rather than something silently
#    reinterpreted. `Emit-Change(cli error (doc*): the usage line names
#    --stdlib` once sat in a window with its parentheses unbalanced; the old
#    `[^)]*` scope reader took the scope to be the literal `cli error (doc*`
#    and said nothing. Replayed, that scope did match two labels -- so the
#    author got an approval, just not the one they wrote. The genuinely
#    never-matching ones were `Emit-Change(lsp *)` and `Emit-Change(core *)`,
#    both in 5d45b1e: `lsp *` needs the prefix "lsp " and the only label is
#    `lsp`, and no differential prints a `core ...` label at all. Two
#    declarations that an author believed they had made, silently worth
#    nothing. Whichever way it goes wrong, the fix is the same: say so.
#
# 4. A label scripts/emit-labels.txt does not know is an error. The tension is
#    real -- a strict check like this could red when a label is added or
#    renamed -- and it is resolved by making the registry unable to fall
#    behind: `emit_gate` runs for *every* check, passing or failing, and fails
#    if its own label is unregistered, printing the line to add. A rename that
#    forgets the file reds in the same run, so "unknown label" always means the
#    declaration is wrong.
#
# ==================== CONSIDERED AND REJECTED (#124) ====================
#
# * Keep `*` but require the declaration to pin its expected change set. At
#   label granularity that *is* the enumeration required above. At file
#   granularity it cannot be written uniformly: a class-file-version change
#   touches every class in the corpus, and `fmt`/`lsp`/`run ...` compare text
#   with no file set at all.
#
# * Expire a wildcard at the commit that declares it. Unworkable: the
#   differential compares the previous release against HEAD, so the diff a
#   declaration approves is still present at HEAD. An expiry would red the
#   very next commit and every one after it.
#
# * Red a declaration whose label turns out identical ("over-declared"). It
#   does not address the reported blindness -- at 1b8ee7f all six labels
#   genuinely differed -- and its safety cannot be replayed without rebuilding
#   twenty seed toolchains, so it ships as an informational line, not a gate.
#
# ============================== RESIDUAL ==============================
#
# A label that is declared once stays exempt until the seed advances, even if
# its diff grows. That is the window design, and REL-02 recorded it as the
# caveat that only golden snapshots in-repo can close (docs/codebase-audit.md,
# REL-02). #124 removes something narrower and worse: the exemption of labels
# nobody ever looked at.

# Parsed declarations, one per line, as "<label><TAB><full declaration line>".
_EC_DECLS=
_EC_LOADED=

_ec_root() { git rev-parse --show-toplevel; }

_ec_labels_file() {
  printf '%s\n' "${EMITCHANGE_LABELS:-$(_ec_root)/scripts/emit-labels.txt}"
}

_ec_registered() { # label
  grep -Fxq -- "$1" "$(_ec_labels_file)"
}

# Registry entries whose first word matches the scope's, so a typo or a
# too-broad scope prints the candidates instead of just "unknown". A scope
# with no relative at all -- `core selfhost`, whose family no differential
# prints -- must not print an empty list and read as a broken message.
_ec_suggest() { # scope
  local head=${1%% *} all near
  all=$(grep -v -e '^#' -e '^$' "$(_ec_labels_file)")
  near=$(printf '%s\n' "$all" | { grep -F -- "$head" || true; } | head -8)
  if [ -n "$near" ]; then
    printf '%s\n' "$near" | sed 's/^/         /'
  else
    echo "         (none resemble it; the labels are"
    printf '%s\n' "$all" | sed 's/^/          - /'
    echo "         )"
  fi
}

# The raw commit-message lines the window contains. EMITCHANGE_SOURCE lets the
# self-test drive the parser without inventing commits.
_ec_source_lines() {
  if [ -n "${EMITCHANGE_SOURCE:-}" ]; then
    cat "$EMITCHANGE_SOURCE"
  else
    git log "$EMITCHANGE_TAG..HEAD" --format=%B 2>/dev/null || true
  fi
}

# Parse and validate every declaration in the window. Any bad one is fatal:
# the gate that cannot read its own exemptions has no business granting them.
emitchange_load() {
  local line rest scope why bad=0 opens closes
  _EC_DECLS=
  if [ -n "${EMITCHANGE_SOURCE:-}" ]; then
    EMITCHANGE_TAG=${EMITCHANGE_TAG:-the tag}
  else
    EMITCHANGE_TAG=$(tr -d ' \n' < "$(_ec_root)/scripts/seed-release.txt")
  fi
  while IFS= read -r line; do
    case "$line" in
      'Emit-Change:'*)
        echo "FAIL unscoped declaration: $line" >&2
        echo "     A bare 'Emit-Change:' exempted every label of every differential." >&2
        echo "     Name the label -- 'Emit-Change(emit selfhost): why' -- or, if nothing" >&2
        echo "     changed, leave the line out and say so in prose." >&2
        bad=1
        continue
        ;;
      'Emit-Change('*) ;;
      *) continue ;;
    esac

    rest=${line#Emit-Change(}
    scope=${rest%'): '*}
    if [ "$scope" = "$rest" ]; then
      echo "FAIL malformed declaration: $line" >&2
      echo "     Expected 'Emit-Change(<label>): <why>'; found no '): ' terminator." >&2
      bad=1
      continue
    fi
    why=${rest#"$scope"'): '}

    opens=${scope//[!(]/}
    closes=${scope//[!)]/}
    if [ ${#opens} -ne ${#closes} ]; then
      echo "FAIL unbalanced parentheses in the scope of: $line" >&2
      echo "     Scope read as: '$scope'" >&2
      echo "     Labels may contain parentheses, so the scope ends at the last '): '." >&2
      bad=1
      continue
    fi

    if [ -z "$scope" ]; then
      echo "FAIL empty scope: $line" >&2
      bad=1
      continue
    fi
    if [ -z "$why" ]; then
      echo "FAIL declaration with no reason: $line" >&2
      echo "     'Emit-Change(<label>): <why>' -- the why is the point of the line." >&2
      bad=1
      continue
    fi

    case "$scope" in
      *'*'* | *'?'* | *'['*)
        echo "FAIL glob in the scope of: $line" >&2
        echo "     Scope read as: '$scope'" >&2
        echo "     A glob covers labels that did not exist when it was written, so the" >&2
        echo "     same message approves more output over time. Name each label:" >&2
        _ec_suggest "$scope" >&2
        bad=1
        continue
        ;;
    esac

    if ! _ec_registered "$scope"; then
      echo "FAIL unknown label: '$scope'" >&2
      echo "     in: $line" >&2
      echo "     Not listed in $(_ec_labels_file). Closest entries:" >&2
      _ec_suggest "$scope" >&2
      bad=1
      continue
    fi

    _EC_DECLS+="$scope"$'\t'"$line"$'\n'
  done < <(_ec_source_lines)

  if [ "$bad" != 0 ]; then
    echo "FAIL: the Emit-Change declarations in this window do not parse." >&2
    echo "      Fix the commit message (git rebase -i / --amend); see scripts/emitchange.sh." >&2
    return 1
  fi
  _EC_LOADED=1
  return 0
}

# Every declaration covering this label, one per line.
declared_for() { # label
  [ -n "$_EC_LOADED" ] || emitchange_load || return 1
  printf '%s' "$_EC_DECLS" \
    | awk -F'\t' -v l="$1" '$1 == l { print substr($0, index($0, "\t") + 1) }'
}

# The one place a differential decides whether a check passes.
#   emit_gate <label> <differs: 0|1> [detail]
# Returns 0 to pass, 1 to fail, and prints the OK/NOTE/FAIL line.
emit_gate() { # label differs [detail]
  local label=$1 differs=$2 detail=${3:-} decls
  [ -n "$_EC_LOADED" ] || emitchange_load || return 1

  if ! _ec_registered "$label"; then
    echo "FAIL $label -- this check's label is not registered"
    echo "     Add this line to $(_ec_labels_file):"
    echo "         $label"
    echo "     (declarations are matched against that file, so an unregistered"
    echo "      label can never be declared)"
    return 1
  fi

  decls=$(declared_for "$label")
  if [ "$differs" = 0 ]; then
    if [ -n "$decls" ]; then
      # Informational, not a gate -- see "considered and rejected" above.
      echo "OK   $label (identical, though a declaration covers it)"
      echo "$decls" | sed 's/^/       /'
    else
      echo "OK   $label"
    fi
    return 0
  fi

  if [ -n "$decls" ]; then
    echo "NOTE $label differs${detail:+ ($detail)} — declared since ${EMITCHANGE_TAG:-the tag}:"
    echo "$decls" | sed 's/^/       /'
    return 0
  fi
  echo "FAIL $label differs${detail:+ ($detail)} and no commit since the tag declares it"
  echo "     (declare it with 'Emit-Change(<label>): why' — this label is '$label')"
  return 1
}

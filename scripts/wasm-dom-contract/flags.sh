#!/usr/bin/env bash
# Init flags, both halves, and the mutants that say the assertions are looking.
#
#   ./scripts/wasm-dom-contract/flags.sh
#
# Flags are the one string the page knows and the guest does not, handed to an
# application's `init` on the first turn and never again
# (`tea_dom/reactor.serve_with_flags`). run.sh calls this before it builds
# anything, because neither leg needs a wasm toolchain.
#
# It is here rather than in a gate of its own for the reason keyed-ops.sh and
# payload.sh are: it is about the same files the transcripts are about, and it
# pins what those transcripts cannot reach. Both demo applications start from a
# constant, so their transcripts are byte-identical whether the bridge sends a
# `flags` field, drops one, or invents one -- there is nothing in either tree
# that a flag could change.
#
# Two legs, one per half of the boundary:
#
#   host    node drives `Reactor.init` and `mount` straight (flags.mjs). What
#           it holds is the request line: absent stays absent, a string is
#           carried verbatim, and `mount`'s option reaches the first turn.
#   guest   bin/dawn runs examples/projects/tea_dom_flags over the session
#           pinned in scripts/example-main-contract/registry.json, which is an
#           application whose whole view is a function of its flags.
#
# The guest leg reads that registry rather than keeping a transcript of its
# own. One golden and not two: the registry entry is what CI already enforces
# on every push, and what this adds is the evidence that the pin has teeth --
# a second copy here could only drift away from it.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (it is the bridge's runtime)." >&2
  exit 1
fi
dawn="${DAWN_BIN:-$root/bin/dawn}"
if [ ! -x "$dawn" ]; then
  echo "MISSING: $dawn is not executable (the guest leg compiles Dawn)." >&2
  exit 1
fi

fail=0
holes=0
killed=0

# `name @ file @ sed program`, applied to a copy of the tree and required to
# turn its leg red. The edit is checked for having applied: a sed that matched
# nothing would report a clean tree as a killed mutant, which is how a mutant
# harness goes quietly blind.
try_mutant() { # <plant fn> <check fn> <name> <file> <sed program>
  local plant="$1" check="$2" name="$3" file="$4" prog="$5" target before
  "$plant" "$work/tree"
  target="$work/tree/$file"
  if [ ! -f "$target" ]; then
    echo "NOT APPLIED: $name (the tree has no $file)"
    holes=$((holes + 1))
    return
  fi
  before="$(md5sum "$target")"
  sed -i "$prog" "$target"
  if [ "$before" = "$(md5sum "$target")" ]; then
    echo "NOT APPLIED: $name (the sed matched nothing; the mutant is vacuous)"
    holes=$((holes + 1))
    return
  fi
  if "$check" "$work/tree"; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
}

# ---- the host half --------------------------------------------------------

plant_host() { # <dir>
  rm -rf "$1"
  mkdir -p "$1/scripts"
  cp -r "$root/packages" "$1/"
  cp -r "$here" "$1/scripts/wasm-dom-contract"
}

check_host() { # <dir>
  node --no-warnings "$1/scripts/wasm-dom-contract/flags.mjs" >/dev/null 2>&1
}

if node --no-warnings "$here/flags.mjs" >"$work/host.txt" 2>&1; then
  echo "OK   host flags: $(grep -c '^OK' "$work/host.txt") assertions"
else
  echo "FAIL: the host flag assertions are red before any mutant was applied:" >&2
  cat "$work/host.txt" >&2
  exit 1
fi

# The distinction the guest depends on, dropped: a page with nothing to say
# would send `""`, and an application that reads `Some("")` was told the page
# said something. Assigning `undefined` instead would not be a mutant at all --
# `JSON.stringify` drops such a key, so the line on the wire is the same one.
try_mutant plant_host check_host absent-flag-becomes-empty \
  packages/tea-dom/js/reactor.mjs \
  's#if (flags !== undefined) request.flags = flags;#request.flags = flags === undefined ? "" : flags;#'

# The page's option never reaches the wire. Nothing raises and every later
# turn is unaffected, because flags are read once: the application simply
# starts from the model it would have had if the page had said nothing.
try_mutant plant_host check_host mount-drops-the-flags \
  packages/tea-dom/js/app.mjs \
  's#settle(reactor.init(flags));#settle(reactor.init());#'

# ---- the guest half -------------------------------------------------------

if ! python3 - "$root/scripts/example-main-contract/registry.json" "$work" <<'PY'
import json
import pathlib
import sys

registry, work = sys.argv[1], pathlib.Path(sys.argv[2])
target = "examples/projects/tea_dom_flags"
with open(registry, encoding="utf-8") as source:
    entries = json.load(source)["targets"]
cases = [case for entry in entries if entry["target"] == target for case in entry["cases"]]
if len(cases) != 1:
    sys.exit(f"expected exactly one registered case for {target}, found {len(cases)}")
(work / "stdin.txt").write_text(cases[0]["stdin"], encoding="utf-8")
(work / "expected.txt").write_text(cases[0]["stdout"], encoding="utf-8")
PY
then
  echo "FAIL: could not read the pinned session out of the example-main registry" >&2
  exit 1
fi

# The project's `[deps]` are relative, so the copy keeps the layout that makes
# them resolve. `packages` is copied rather than pointed at, because that is
# what the mutants below edit.
plant_guest() { # <dir>
  rm -rf "$1"
  mkdir -p "$1/examples/projects"
  cp -r "$root/packages" "$1/"
  cp -r "$root/examples/projects/tea_dom_flags" "$1/examples/projects/tea_dom_flags"
}

check_guest() { # <dir>
  "$dawn" run "$1/examples/projects/tea_dom_flags" \
    <"$work/stdin.txt" >"$work/guest-actual.txt" 2>/dev/null &&
    cmp -s "$work/guest-actual.txt" "$work/expected.txt"
}

plant_guest "$work/base"
if check_guest "$work/base"; then
  echo "OK   guest flags: the pinned session replays, byte for byte"
else
  echo "FAIL: the pinned flags session is red before any mutant was applied:" >&2
  diff -u "$work/expected.txt" "$work/guest-actual.txt" | head -20 >&2
  exit 1
fi

# The turn stops handing the flags on. This is the mutant the whole project
# exists for: nothing about the wire moves, the decoder still reads the field,
# and the application is simply started from the model a page with nothing to
# say would have got.
try_mutant plant_guest check_guest flags-ignored-at-the-turn \
  packages/tea-dom/src/reactor.dawn \
  's#      let m0 = init(flags)#      let m0 = init(None)#'

# The decoder stops reading the field, one level earlier: `Init` always
# carries `None`, so every entry point above it is honest about a string that
# was never there. Held separately because the two are one substitution apart
# and an assertion that saw only the first would leave the wire uncovered.
try_mutant plant_guest check_guest flags-never-decoded \
  packages/tea-dom/src/wire.dawn \
  's#match as_opt_string(field(entries, "flags")) {#match as_opt_string(field(entries, "nope")) {#'

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of $((holes + killed)) flag mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "flags ok ($killed/$((holes + killed)) mutants killed)"

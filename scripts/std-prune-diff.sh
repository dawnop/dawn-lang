#!/usr/bin/env bash
# Differential for the pruned std load (docs/check-std-prune-design.md).
#
# `dawnc check` and `dawnc emitc` on the embedded std load only the std modules
# a program reaches. Everything that load leaves out has to be invisible, and
# "invisible" is a claim about output, so this compares output: for every unit
# of the corpus, the pruned load (the default) against the full load
# (`--std std`, a directory, which is never pruned; the round-trip test in
# selfhost/src/driver/stdlib.dawn holds std/ equal to the embedded copy), byte
# for byte:
#
#   check   exit status, stdout, stderr
#   emitc   exit status, stdout, stderr, and the C file
#
# One process per unit and per side, because the load is cut to what one
# program imports; a single `check a b c` would load the union and compare
# almost nothing. The corpus is every unit the repository already treats as a
# program: the checker corpus (190 diagnostic goldens, most of them errors, so
# the messages are compared too), examples/ by the site generator's unit rule,
# the Playground samples, and packages/ (whose path dependencies are where the
# `use std/..` of a dependency, not of the entry file, is the one that
# matters). emitc runs on the units that check clean.
#
# A green diff says nothing if pruning silently stopped happening, so two
# controls run first:
#   speed     an empty program checks at least 20% faster pruned than full
#             (best of 7 each; measured 0.26 s against 0.50 s)
#   planted   a std directory with one byte changed in a module every program
#             loads must make emitc differ from the embedded copy, so the
#             comparison below is able to see a difference at all
#
#   scripts/std-prune-diff.sh                   build nothing: DAWNC_BIN or ./dawnc
#   DAWNC_BIN=path scripts/std-prune-diff.sh
#   scripts/std-prune-diff.sh --one KIND UNIT   (internal, run by xargs)
set -euo pipefail
cd "$(dirname "$0")/.."

BIN=${DAWNC_BIN:-./dawnc}
BIN=$(realpath "$BIN")

one() {
  local kind=$1 unit=$2 work
  work=$(mktemp -d "${TMPDIR:-/tmp}/std-prune-diff.XXXXXX")
  local a="$work/a" b="$work/b"
  local rc_a rc_b
  case $kind in
    check)
      rc_a=0; "$BIN" check "$unit" >"$a.out" 2>"$a.err" || rc_a=$?
      rc_b=0; "$BIN" check --std std "$unit" >"$b.out" 2>"$b.err" || rc_b=$?
      ;;
    emitc)
      rc_a=0; "$BIN" emitc -o "$a.c" "$unit" >"$a.out" 2>"$a.err" || rc_a=$?
      rc_b=0; "$BIN" emitc --std std -o "$b.c" "$unit" >"$b.out" 2>"$b.err" || rc_b=$?
      [ -e "$a.c" ] || : >"$a.c"
      [ -e "$b.c" ] || : >"$b.c"
      ;;
  esac
  echo "$rc_a" >"$a.rc"; echo "$rc_b" >"$b.rc"
  local bad=""
  for part in rc out err; do
    cmp -s "$a.$part" "$b.$part" || bad="$bad $part"
  done
  if [ "$kind" = emitc ]; then cmp -s "$a.c" "$b.c" || bad="$bad c"; fi
  if [ -n "$bad" ]; then
    echo "DIFF $kind $unit:$bad"
    for part in rc out err; do
      cmp -s "$a.$part" "$b.$part" || diff <(head -c 4000 "$a.$part") <(head -c 4000 "$b.$part") | head -8 | sed 's/^/    /'
    done
    if [ "$kind" = emitc ]; then cmp -s "$a.c" "$b.c" || cmp "$a.c" "$b.c" | head -2 | sed 's/^/    /'; fi
    rm -rf "$work"
    return 1
  fi
  echo "$rc_a" >"$work/status"
  # the check rc, for the caller that picks emitc units
  if [ "$kind" = check ]; then echo "OK check $rc_a $unit"; else echo "OK emitc $rc_a $unit"; fi
  rm -rf "$work"
}

if [ "${1:-}" = --one ]; then one "$2" "$3"; exit $?; fi

[ -x "$BIN" ] || { echo "FAIL: no native compiler at $BIN (set DAWNC_BIN)" >&2; exit 2; }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/std-prune-diff-run.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

best_ms() { # best of N wall times, in ms, of: "$@"
  local n=$1; shift
  local best=999999 t0 t1
  for _ in $(seq "$n"); do
    t0=$(date +%s%N); "$@" >/dev/null 2>&1 || true; t1=$(date +%s%N)
    local ms=$(( (t1 - t0) / 1000000 ))
    [ "$ms" -lt "$best" ] && best=$ms
  done
  echo "$best"
}

# ---- controls ---------------------------------------------------------------
: >"$TMP/empty.dawn"
pruned_ms=$(best_ms 7 "$BIN" check "$TMP/empty.dawn")
full_ms=$(best_ms 7 "$BIN" check --std std "$TMP/empty.dawn")
echo "control speed: empty program check ${pruned_ms} ms pruned, ${full_ms} ms full"
if [ $((pruned_ms * 100)) -gt $((full_ms * 80)) ]; then
  echo "FAIL: pruning is not in effect (pruned ${pruned_ms} ms is not 20% under full ${full_ms} ms)" >&2
  exit 1
fi

mkdir -p "$TMP/planted"
cp -R std "$TMP/planted/std"
python3 - "$TMP/planted/std/str.dawn" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = 'pub fn pad_start(s: String, width: Int, pad: String = " ")'
assert old in s, "the planted edit's anchor moved"
p.write_text(s.replace(old, old.replace('" "', '"#"'), 1))
PY
cat >"$TMP/planted/pad.dawn" <<'DAWN'
use std/str

pub fn main() -> Unit !io = println(str.pad_start("a", 3))
DAWN
"$BIN" emitc -o "$TMP/planted/embedded.c" "$TMP/planted/pad.dawn" >/dev/null 2>&1
"$BIN" emitc --std "$TMP/planted/std" -o "$TMP/planted/planted.c" "$TMP/planted/pad.dawn" >/dev/null 2>&1
if cmp -s "$TMP/planted/embedded.c" "$TMP/planted/planted.c"; then
  echo "FAIL: a planted one-byte difference in std/str went unseen by the emitc comparison" >&2
  exit 1
fi
echo "control planted: a one-byte std edit changes the emitted C, so the comparison can see it"

# ---- the corpus ---------------------------------------------------------------
units=()
for f in scripts/checker-corpus/cases/*.dawn; do units+=("$f"); done
for d in scripts/checker-corpus/cases/*.d; do [ -d "$d" ] && units+=("$d/entry.dawn"); done
for group in examples/*/; do
  for entry in "$group"*; do
    if [ -d "$entry" ]; then
      if [ -d "$entry/src" ]; then units+=("${entry%/}"); fi
    elif [ "${entry##*.}" = dawn ]; then
      units+=("$entry")
    fi
  done
done
for f in site/play-ui/samples/*.dawn; do units+=("$f"); done
for d in packages/*/; do [ -d "${d}src" ] && units+=("${d%/}"); done
if [ "${#units[@]}" -lt 230 ]; then
  echo "FAIL: found only ${#units[@]} unit(s); the corpus cannot have shrunk that far (241 on 2026-10-11)" >&2
  exit 1
fi

JOBS=${STD_PRUNE_DIFF_JOBS:-$(nproc)}
export BIN
printf '%s\n' "${units[@]}" | xargs -P "$JOBS" -I{} "$0" --one check {} >"$TMP/check.log" || true
# emitc where the program checks clean
awk '$1 == "OK" && $2 == "check" && $3 == 0 && $4 !~ /^packages\// { print $4 }' "$TMP/check.log" >"$TMP/clean.txt"
xargs -P "$JOBS" -I{} "$0" --one emitc {} <"$TMP/clean.txt" >"$TMP/emitc.log" || true

n_check=$(grep -c '^OK check' "$TMP/check.log" || true)
n_clean=$(grep -c '^OK check 0 ' "$TMP/check.log" || true)
n_emitc=$(grep -c '^OK emitc' "$TMP/emitc.log" || true)
if grep -h '^DIFF' "$TMP/check.log" "$TMP/emitc.log" >/dev/null; then
  grep -hA8 '^DIFF' "$TMP/check.log" "$TMP/emitc.log" | head -80
  echo "FAIL: the pruned std load changed the output of $(cat "$TMP/check.log" "$TMP/emitc.log" | grep -c '^DIFF') unit(s)" >&2
  exit 1
fi
if [ "$n_check" -ne "${#units[@]}" ]; then
  echo "FAIL: ${#units[@]} unit(s) queued, $n_check compared (a worker died)" >&2
  exit 1
fi
if [ "$n_emitc" -ne "$(wc -l <"$TMP/clean.txt")" ]; then
  echo "FAIL: not every clean unit was compared through emitc" >&2
  exit 1
fi
if [ "$n_clean" -lt 50 ] || [ "$n_emitc" -lt 40 ]; then
  echo "FAIL: only $n_clean clean and $n_emitc emitted units; the corpus lost its programs" >&2
  exit 1
fi
echo "OK   pruned and full std agree on $n_check checked units ($n_clean clean) and $n_emitc emitted programs"

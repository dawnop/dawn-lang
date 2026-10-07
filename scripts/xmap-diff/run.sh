#!/usr/bin/env bash
# The package xmap against the script it replaces, and against the Playground's
# own programs.
#
#     scripts/xmap-diff/run.sh
#
# What it holds, in the order it runs:
#
#   1. the differential. site/explorer/record.py runs each compiler once per
#      program and writes both its raw material (what packages/xmap reads) and
#      its own assembly of it (the `.xmap` files the explorer page was built
#      from until now). The package makes the same files from the raw
#      material, and the two sets of files must be byte for byte the same:
#      the two programs the page shows (flash_attn, attend) and the eleven
#      starter programs of the Playground (site/play-ui/samples). That is the
#      transition's proof that moving the pairing from Python into a package
#      changed nothing a reader of the page can see.
#   2. zero gaps. The eleven samples are what a visitor starts from, so
#      the online compile view (docs/playground-compile-design.md) has to map
#      each of them completely. `explore_strict` refuses a program with a gap;
#      a gap here is a defect of a compiler's side table to file, not a state
#      to live with.
#   3. the controls. A check that has only ever been green has not been
#      shown to see anything. Each one below changes a thing a gate rests on
#      and requires the gate to go red, in the words it should use: the
#      package drops one `out` row (the differential must not match), the
#      package's strict entry stops refusing (the defective-input control must
#      stop being refused), and the three defects record.py's own self-test
#      has (a call that moved one place, a pc range outside its method, a name
#      that is not at its span) are put into real maps and must be refused by
#      the package in the words record.py used.
#
# `--no-controls` runs steps 1 and 2 only. The controls build the checker
# against two mutated copies of the package and run it five more times, which
# is most of this script's time.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
DAWN="${DAWN_BIN:-$ROOT/bin/dawn}"
CONTROLS=1
[ "${1:-}" = "--no-controls" ] && CONTROLS=0

W="$(mktemp -d)"
trap 'rm -rf "${W:?}"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# ---- 1. the differential, and 2. zero gaps ----
echo "== recording the page's programs and the Playground's samples =="
python3 site/explorer/record.py --raw "$W/raw" --legacy-out "$W/legacy"
python3 site/explorer/record.py --samples --raw "$W/sraw" --legacy-out "$W/slegacy"

# One run of the checker over one raw directory, into one output directory.
# $1 = checker project, $2 = raw dir, $3 = out dir, then its flags.
check_run() {
  local proj="$1" raw="$2" out="$3"
  shift 3
  mkdir -p "$out"
  "$DAWN" run "$proj" -- "$raw" "$out" "$@"
}

echo "== the package against record.py's own assembly =="
for set in "raw legacy" "sraw slegacy"; do
  set -- $set
  check_run scripts/xmap-diff "$W/$1" "$W/mod-$1" --strict >"$W/mod-$1.log" ||
    { cat "$W/mod-$1.log" >&2; fail "the package refuses a program of $1 (a gap, or an unreadable map)"; }
  grep -q '^gaps .* [1-9]' "$W/mod-$1.log" && fail "a program of $1 has gaps"
  diff -r "$W/$2" "$W/mod-$1" >"$W/diff-$1.txt" ||
    { head -40 "$W/diff-$1.txt" >&2; fail "the package's .xmap differs from record.py's for $1"; }
  echo "ok: $(grep -c '^gaps ' "$W/mod-$1.log") program(s) of $1 byte for byte the same, no gap"
done

[ "$CONTROLS" = 0 ] && { echo "OK: the package matches record.py, no gap (controls skipped)"; exit 0; }

# ---- 3. the controls ----
# A copy of the checker whose package is a mutated copy of xmap. $1 = name,
# $2 = file of the package (under src/), $3 = text to find, $4 = text to put.
mutated_checker() {
  local name="$1" file="$2" from="$3" to="$4"
  mkdir -p "$W/$name/pkg" "$W/$name/cli"
  cp -R packages/xmap/dawn.toml packages/xmap/src "$W/$name/pkg/"
  cp -R scripts/xmap-diff/src "$W/$name/cli/"
  printf 'schema = 1\nname = "xmap_diff"\n\n[deps]\nxmap = "%s"\n' "$W/$name/pkg" >"$W/$name/cli/dawn.toml"
  python3 - "$W/$name/pkg/src/$file" "$from" "$to" <<'PY'
import sys
p, a, b = sys.argv[1:]
s = open(p, encoding="utf-8").read()
if s.count(a) != 1:
    sys.exit(f"the mutation's text is in {p} {s.count(a)} times, not once")
open(p, "w", encoding="utf-8").write(s.replace(a, b))
PY
}

# 3a: the package drops the `out` row of call 3 of every pane
mutated_checker drop xmap.dawn \
  '      rows = rows ++ [out_row(p.kind, c.id, p.outs[c.id])]' \
  '      let kept: List[String] = if c.id == 3 { [] } else { [out_row(p.kind, c.id, p.outs[c.id])] }
      rows = rows ++ kept'
check_run "$W/drop/cli" "$W/raw" "$W/mod-drop" >"$W/drop.log" 2>&1 || { cat "$W/drop.log" >&2; fail "control 3a: the mutated package did not even run"; }
if diff -r "$W/legacy" "$W/mod-drop" >/dev/null; then
  fail "control 3a: a package that drops an out row still matches record.py"
fi
echo "ok: a package that drops an out row does not match record.py"

# A raw directory holding attend with one defect put in some of its maps.
# $1 = name, $2 = the maps to damage, $3 = python run over each map's rows
# with `lo0` bound to the place of the first call of attend in the C map.
defective() {
  local name="$1" files="$2" py="$3"
  mkdir -p "$W/$name"
  cp -R "$W/raw/attend" "$W/$name/attend"
  printf 'attend\n' >"$W/$name/programs.txt"
  for f in $files; do
    python3 - "$W/$name/attend" "$f" <<PY
import sys
d, f = sys.argv[1:]
def load(n):
    return [l.rstrip("\n").split("\t") for l in open(f"{d}/{n}", encoding="utf-8")]
lo0 = next(r[6] for r in load("c.dawnmap") if r[0] == "call" and r[5] == "attend" and r[6] not in ("-", "?"))
rows = load(f)
mine = [r for r in rows if r[0] == "call" and r[5] == "attend" and r[6] == lo0]
$py
open(f"{d}/{f}", "w", encoding="utf-8").write("".join("\t".join(r) + "\n" for r in rows))
PY
  done
}

# the first call of attend: moved one place in the C map only
defective moved c.dawnmap "mine[0][6] = str(int(lo0) + 1)"
# its pc range ends past its method's code
defective pc jvm.dawnmap "mine[0][3] = '100000'"
# its name is at offset 0, in both maps, where no identifier starts
defective renamed "c.dawnmap jvm.dawnmap" "
for r in mine:
    r[8] = '0'"

expect_refused() {
  local label="$1" words="$2"
  if check_run scripts/xmap-diff "$W/$label" "$W/out-$label" --strict >"$W/$label.log" 2>&1; then
    fail "control $label: the defective input was not refused"
  fi
  grep -q "$words" "$W/$label.log" || { cat "$W/$label.log" >&2; fail "control $label: refused, but not in the words '$words'"; }
  echo "ok: $label is refused ($words)"
}

# the positive control: the same program, undamaged, passes
check_run scripts/xmap-diff "$W/raw" "$W/out-pos" --strict >/dev/null 2>&1 || fail "the undamaged input was refused"
expect_refused moved "and not in the other"
expect_refused pc "are outside its method's code"
expect_refused renamed "which is no identifier"

# 3b: the package's strict entry stops refusing
mutated_checker lax xmap.dawn \
  'pub fn strict(b: Built) -> Result[Built, String] = if len(b.gaps) == 0 { Ok(b) } else { Err(b.gaps[0]) }' \
  'pub fn strict(b: Built) -> Result[Built, String] = Ok(b)'
if check_run "$W/lax/cli" "$W/moved" "$W/out-lax" --strict >/dev/null 2>&1; then
  echo "ok: with the strict entry weakened, the defective input is no longer refused (so the controls above can see it)"
else
  fail "control 3b: a weakened strict entry still refuses the defective input"
fi
echo "OK: the package matches record.py, no gap, and each control went red"

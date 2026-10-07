#!/usr/bin/env bash
# The Playground's starter programs map with no gap, and the check that says so
# can go red.
#
#     scripts/xmap-samples/run.sh
#
# Why. The online compile view (docs/playground-compile-design.md) pairs a
# visitor's code with the C and bytecode it compiles to using packages/xmap,
# and drops the lines of any call a compiler's side table has no place for.
# That is the right thing for code nobody has checked, and it hides a defect
# in a compiler's table for the code somebody has: the eleven programs a visitor
# starts from (site/play-ui/samples). So they are held to a mapping with none:
# `explore_strict` refuses a program with a gap, and a gap here is a defect of
# a compiler's side table to file, not a state to live with. (The two programs
# the explorer page shows are held the same way by every site build, whose
# generator maps them strictly.)
#
# What it runs, in order:
#
#   1. site/explorer/record.py asks each compiler for its account of the 11
#      samples, and scripts/xmap-samples pairs each with the package, strictly.
#   2. the controls. A check that has only ever been green has not been shown
#      to see anything. Each one below changes a thing the gate rests on and
#      requires it to go red, in the words it should use: the package drops one
#      `out` row (its own tests, which pin the `.xmap` of a program, must
#      fail), its strict entry stops refusing (a defective input must stop
#      being refused), and three defects are put into real maps (a call that
#      moved one place, a pc range outside its method, a name that is not at
#      its span) and must each be refused by the package in the words that name
#      the fault.
#
# When this replaced record.py's own Python pairing, the package and the
# script were compared on the same raw material, byte for byte, for the 11
# samples and the page's two programs (the commit that removed the script says
# which commit had both).
#
# `--no-controls` runs step 1 only. The controls build the checker against two
# mutated copies of the package and run it four more times.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
DAWN="${DAWN_BIN:-$ROOT/bin/dawn}"
CONTROLS=1
[ "${1:-}" = "--no-controls" ] && CONTROLS=0

W="$(mktemp -d)"
trap 'rm -rf "${W:?}"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# One run of the checker over one raw directory, into one output directory.
# $1 = checker project, $2 = raw dir, $3 = out dir, then its flags.
check_run() {
  local proj="$1" raw="$2" out="$3"
  shift 3
  mkdir -p "$out"
  "$DAWN" run "$proj" -- "$raw" "$out" "$@"
}

echo "== recording the Playground's starter programs =="
python3 site/explorer/record.py --samples "$W/raw"

echo "== every program maps with no gap =="
check_run scripts/xmap-samples "$W/raw" "$W/mod" --strict >"$W/mod.log" ||
  { cat "$W/mod.log" >&2; fail "the package refuses a program (a gap, or an unreadable map)"; }
grep -q '^gaps .* [1-9]' "$W/mod.log" && fail "a program has gaps"
N="$(grep -c '^gaps .* 0$' "$W/mod.log")"
[ "$N" = 11 ] || fail "expected 11 programs with no gap, got $N"
echo "ok: $N programs, no gap"

[ "$CONTROLS" = 0 ] && { echo "OK: every program maps with no gap (controls skipped)"; exit 0; }

# ---- the controls ----
# A copy of the package with one text changed, and a copy of the checker that
# uses it. $1 = name, $2 = file of the package (under src/), $3 = text to
# find, $4 = text to put.
mutated() {
  local name="$1" file="$2" from="$3" to="$4"
  mkdir -p "$W/$name/pkg" "$W/$name/cli"
  cp -R packages/xmap/dawn.toml packages/xmap/src "$W/$name/pkg/"
  cp -R scripts/xmap-samples/src "$W/$name/cli/"
  printf 'schema = 1\nname = "xmap_samples"\n\n[deps]\nxmap = "%s"\n' "$W/$name/pkg" >"$W/$name/cli/dawn.toml"
  python3 - "$W/$name/pkg/src/$file" "$from" "$to" <<'PY'
import sys
p, a, b = sys.argv[1:]
s = open(p, encoding="utf-8").read()
if s.count(a) != 1:
    sys.exit(f"the mutation's text is in {p} {s.count(a)} times, not once")
open(p, "w", encoding="utf-8").write(s.replace(a, b))
PY
}

# the package drops the `out` row of call 1 of every pane: its tests, which
# hold the `.xmap` of a small program, have to notice
mutated drop xmap.dawn \
  '      rows = rows ++ [out_row(p.kind, c.id, p.outs[c.id])]' \
  '      let kept: List[String] = if c.id == 1 { [] } else { [out_row(p.kind, c.id, p.outs[c.id])] }
      rows = rows ++ kept'
if "$DAWN" test "$W/drop/pkg" >"$W/drop.log" 2>&1; then
  fail "control: a package that drops an out row still passes its tests"
fi
grep -q 'FAIL' "$W/drop.log" || { cat "$W/drop.log" >&2; fail "control: the mutated package did not fail by a test"; }
echo "ok: a package that drops an out row fails its own tests"

# A raw directory holding the shapes sample with one defect put in some of its maps.
# $1 = name, $2 = the maps to damage, $3 = python run over each map's rows
# with `lo0` bound to the place of the first call of shapes in the C map.
defective() {
  local name="$1" files="$2" py="$3"
  mkdir -p "$W/$name"
  cp -R "$W/raw/shapes" "$W/$name/shapes"
  printf 'shapes\n' >"$W/$name/programs.txt"
  for f in $files; do
    python3 - "$W/$name/shapes" "$f" <<PY
import sys
d, f = sys.argv[1:]
def load(n):
    return [l.rstrip("\n").split("\t") for l in open(f"{d}/{n}", encoding="utf-8")]
lo0 = next(r[6] for r in load("c.dawnmap") if r[0] == "call" and r[5] == "shapes" and r[6] not in ("-", "?"))
rows = load(f)
mine = [r for r in rows if r[0] == "call" and r[5] == "shapes" and r[6] == lo0]
$py
open(f"{d}/{f}", "w", encoding="utf-8").write("".join("\t".join(r) + "\n" for r in rows))
PY
  done
}

# the first call of shapes: moved one place in the C map only
defective moved c.dawnmap "mine[0][6] = str(int(lo0) + 1)"
# its pc range ends past its method's code
defective pc jvm.dawnmap "mine[0][3] = '100000'"
# its name is said to be at its last character, in both maps, where a closing
# parenthesis is and no identifier starts
defective renamed "c.dawnmap jvm.dawnmap" "
for r in mine:
    r[8] = str(int(r[7]) - 1)"

expect_refused() {
  local label="$1" words="$2"
  if check_run scripts/xmap-samples "$W/$label" "$W/out-$label" --strict >"$W/$label.log" 2>&1; then
    fail "control $label: the defective input was not refused"
  fi
  grep -q "$words" "$W/$label.log" || { cat "$W/$label.log" >&2; fail "control $label: refused, but not in the words '$words'"; }
  echo "ok: $label is refused ($words)"
}

# the positive control: the same program, undamaged, passes
mkdir -p "$W/whole"
printf 'shapes\n' >"$W/whole/programs.txt"
cp -R "$W/raw/shapes" "$W/whole/shapes"
check_run scripts/xmap-samples "$W/whole" "$W/out-whole" --strict >/dev/null 2>&1 || fail "the undamaged input was refused"
expect_refused moved "and not in the other"
expect_refused pc "are outside its method's code"
expect_refused renamed "which is no identifier"

# the package's strict entry stops refusing
mutated lax xmap.dawn \
  'pub fn strict(b: Built) -> Result[Built, String] = if len(b.gaps) == 0 { Ok(b) } else { Err(b.gaps[0]) }' \
  'pub fn strict(b: Built) -> Result[Built, String] = Ok(b)'
if check_run "$W/lax/cli" "$W/moved" "$W/out-lax" --strict >/dev/null 2>&1; then
  echo "ok: with the strict entry weakened, a defective input is no longer refused (so the controls above can see it)"
else
  fail "control: a weakened strict entry still refuses the defective input"
fi
echo "OK: every program maps with no gap, and each control went red"

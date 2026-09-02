#!/usr/bin/env bash
# Layer 2 of docs/tile-backend-design.md 6.2: the vadd kernels (f64 and
# bf16) on this machine's GPU against the fake device, bit for bit, and the
# ledger that says it was done (6.4, decision D4).
#
#   ./scripts/tile-gpu-diff/run.sh            # run, and append a ledger line
#   ./scripts/tile-gpu-diff/run.sh --dry      # run, append nothing
#   ./scripts/tile-gpu-diff/run.sh --check    # the CI gate: no GPU, no tileiras
#
# The run:
#
#   assemble  scripts/tile-golden/vadd.tilebc and vadd_bf16.tilebc (the
#             recorded bytecode goldens) through the pinned tileiras into
#             cubins for toolchain.txt's gpu-name. install-tileiras.sh
#             installs the pin under $TILEIRAS_DIR (default
#             ~/.cache/dawn-tileiras) unless $TILEIRAS names a binary.
#   jvm       vadd_diff.dawn on the JVM stops at the first operation with
#             `gpu.unsupported_backend`: the JVM has no device runtime and
#             says so by construction rather than by a LinkageError.
#   native    vadd_diff.dawn built natively runs four f64 and three bf16
#             input sets under `with_gpu_real` and `with_gpu_fake` and prints a transcript
#             (its header says the format). The last line is the verdict:
#             `pass` (every set bit-identical), `blocked:<kind>@<stage>`
#             (the driver refused at that stage, the same way in every set;
#             on a driver older than the cubin's CUDA generation the runtime
#             refuses the module itself with gpu.driver_too_old, since such
#             a driver's loader answers INVALID_IMAGE or crashes depending on
#             the heap layout) or `fail` (the device answered and the numbers
#             differ, or the memory round trip did).
#   mutant    one rule removed from a copy of std/gpu.dawn's real handler,
#             the program rebuilt against that copy, and the verdict
#             required to move:
#
#     download-short   the handler asks the device for n-1 f64 elements ->
#                      every f64 set's round trip differs, verdict `fail`.
#                      A handler-layer claim, so it is required on every
#                      driver, blocked or not: the memory path is the part
#                      a pre-r580 driver can already run.
#     pack-truncates   the bf16 packer stops rounding and lets
#                      narrow.bf16_bits truncate the Float instead -> every
#                      bf16 set's round trip differs (each set carries
#                      Floats off the grid on purpose), verdict `fail`.
#                      The same layer as download-short, so required on
#                      every driver; the device never sees the difference
#                      between a truncated and a rounded operand as such,
#                      only the fake device does.
#     grid-zero        the handler launches over 0 tile blocks -> the
#                      driver refuses the launch (CUDA_ERROR_INVALID_VALUE)
#                      and the verdict is not `pass`. A launch-layer claim:
#                      required when the clean run passed, and reported as
#                      SKIP, not PASS, on a driver whose clean run is
#                      blocked before the launch, because there the mutant
#                      and the clean run are indistinguishable.
#   ledger    one line appended to ledger.txt:
#               <commit> <date> <driver> <tileiras> <gpu-name> <result> [# note]
#             commit is HEAD (12 hex; refused when the tile paths have
#             uncommitted changes, since the line would name a tree that was
#             not run), driver is nvidia-smi's, and result is the verdict.
#             Refused unless toolchain.txt's `driver` line already says the
#             driver nvidia-smi reports: the three numbers move together
#             (6.3), and the ledger commit adds a line and nothing else.
#
# --check, the gate the `tile` job runs on every push (docs 6.4):
#
#   the last ledger line parses; its commit exists and is an ancestor of
#   HEAD; its date is a day that has happened; its result is `pass` or
#   `blocked:...` (a recorded `fail` may sit in the history but not at the
#   end); no tile path changed between that commit and HEAD, where the tile
#   paths are packages/tileir, std/gpu.dawn, std/narrow.dawn (the bf16
#   reference the fake device rounds with), scripts/tile-golden,
#   scripts/tile-gpu-diff minus the ledger itself, and the GPU section of
#   runtime/c/dawn_rt.c (between its DAWN_RT_GPU_BEGIN / END markers; the
#   rest of the runtime is not a tile path); and toolchain.txt's driver
#   line is the ledger's. It proves that somebody ran this script on a
#   machine with a driver at this tree, and what the driver said. It does
#   not prove the GPU answer reached CI: `blocked` is an allowed state,
#   because the honest record of a machine whose driver cannot load the
#   cubin is worth more than no record. What it refuses is silence.
# shellcheck disable=SC2016  # the mutant anchors are Dawn source, quoted verbatim on purpose
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/tile-gpu-diff"
golden="$root/scripts/tile-golden"
ledger="$here/ledger.txt"
toolchain="$golden/toolchain.txt"
cc_bin="${CC:-cc}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mode=run
append=yes
while [ $# -gt 0 ]; do
  case "$1" in
    --check) mode=check ;;
    --dry) append=no ;;
    *) echo "usage: run.sh [--dry | --check]" >&2; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------- --check

if [ "$mode" = check ]; then
  cd "$root"
  python3 - "$ledger" "$toolchain" <<'PY'
import datetime
import pathlib
import re
import subprocess
import sys

ledger, toolchain = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
TILE_PATHS = ["packages/tileir", "std/gpu.dawn", "std/narrow.dawn", "scripts/tile-golden",
              "scripts/tile-gpu-diff", ":(exclude)scripts/tile-gpu-diff/ledger.txt"]
BEGIN, END = "=== DAWN_RT_GPU_BEGIN ===", "=== DAWN_RT_GPU_END ==="
problems = []


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def gpu_section(rev):
    r = git("show", f"{rev}:runtime/c/dawn_rt.c")
    if r.returncode != 0:
        return None
    text = r.stdout
    if BEGIN not in text or END not in text:
        return None
    return text[text.index(BEGIN):text.index(END)]


lines = [ln for ln in ledger.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
if not lines:
    print("FAIL: scripts/tile-gpu-diff/ledger.txt has no entry. Run scripts/tile-gpu-diff/run.sh on a "
          "machine with a driver and commit the line it appends; a blocked run counts, silence does not.")
    sys.exit(1)
last = lines[-1].split("#", 1)[0].split()
if len(last) != 6:
    print(f"FAIL: the last ledger line has {len(last)} fields, not 6: {lines[-1]!r}")
    sys.exit(1)
commit, date, driver, tileiras, gpu, result = last

if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
    problems.append(f"commit {commit!r} is not a hex id")
elif git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
    problems.append(f"commit {commit} is not in this repository (a shallow checkout cannot run this gate; "
                    f"fetch-depth: 0)")
elif git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
    problems.append(f"commit {commit} is not an ancestor of HEAD: the ledger names a tree this history "
                    f"does not contain")
else:
    r = git("diff", "--name-only", commit, "HEAD", "--", *TILE_PATHS)
    changed = [p for p in r.stdout.split("\n") if p]
    before, now = gpu_section(commit), gpu_section("HEAD")
    if now is None:
        changed.append("runtime/c/dawn_rt.c (the GPU section markers are missing at HEAD)")
    elif before != now:
        changed.append("runtime/c/dawn_rt.c (GPU section)")
    if changed:
        problems.append("tile paths changed since the ledger's commit " + commit + " and nobody re-ran "
                        "scripts/tile-gpu-diff/run.sh: " + ", ".join(changed))

try:
    when = datetime.date.fromisoformat(date)
    if when > datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=1):
        problems.append(f"date {date} has not happened")
except ValueError:
    problems.append(f"date {date!r} is not YYYY-MM-DD")

if result == "fail":
    problems.append("the last ledger line records `fail`: the device answered and disagreed with the fake "
                    "device. Fix it and run again; a red run may stay in the history but not at the end")
elif result != "pass" and not re.fullmatch(r"blocked:[A-Za-z_.0-9]+@[a-z]+", result):
    problems.append(f"result {result!r} is neither `pass` nor `blocked:<kind>@<stage>`")

tc = dict(ln.split(None, 1) for ln in toolchain.read_text().splitlines()
          if ln.strip() and not ln.startswith("#") and len(ln.split(None, 1)) == 2)
if tc.get("driver", "").strip() != driver:
    problems.append(f"toolchain.txt says driver {tc.get('driver', '?').strip()} and the ledger's last line "
                    f"says {driver}: the three numbers of docs 6.3 move together")
if tc.get("tileiras", "").strip() != tileiras:
    problems.append(f"toolchain.txt pins tileiras {tc.get('tileiras', '?').strip()} and the ledger's last "
                    f"line was assembled with {tileiras}")

if problems:
    for p in problems:
        print("FAIL: " + p)
    sys.exit(1)
print(f"PASS  ledger: {commit} ({date}, driver {driver}, tileiras {tileiras}, {gpu}) is an ancestor of HEAD "
      f"with no tile path changed since; result {result}")
PY
  exit $?
fi

# ---------------------------------------------------------------- the run

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$root"

toolchain_value() { # key
  awk -v k="$1" '$1 == k { print $2; exit }' "$toolchain"
}
want_tileiras="$(toolchain_value tileiras)"
gpu_name="$(toolchain_value gpu-name)"
pinned_driver="$(toolchain_value driver)"
if [ -z "$want_tileiras" ] || [ -z "$gpu_name" ]; then fail "toolchain.txt must name tileiras and gpu-name"; fi

tileiras="${TILEIRAS:-}"
if [ -z "$tileiras" ]; then
  tileiras="$("$golden/install-tileiras.sh" "${TILEIRAS_DIR:-$HOME/.cache/dawn-tileiras}")"
fi
[ -x "$tileiras" ] || fail "tileiras is not executable: $tileiras"
"$tileiras" --version > "$work/tileiras.version" 2>&1 || fail "tileiras --version failed"
grep -q "V${want_tileiras}\b" "$work/tileiras.version" ||
  { cat "$work/tileiras.version" >&2; fail "tileiras is not the pinned ${want_tileiras} (toolchain.txt)"; }

for k in vadd vadd_bf16; do
  "$tileiras" --gpu-name "$gpu_name" -o "$work/$k.cubin" "$golden/$k.tilebc" > "$work/assemble.log" 2>&1 ||
    { cat "$work/assemble.log" >&2; fail "tileiras refused scripts/tile-golden/$k.tilebc"; }
  [ "$(head -c 4 "$work/$k.cubin" | od -An -tx1 | tr -d ' \n')" = 7f454c46 ] ||
    fail "tileiras wrote no ELF cubin for $k"
  echo "PASS  assemble: $k.tilebc -> cubin ($(wc -c < "$work/$k.cubin") bytes, tileiras V$want_tileiras, $gpu_name)"
done
cubins=("$work/vadd.cubin" "$work/vadd_bf16.cubin")

driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | tr -d ' ' || true)"
[ -n "$driver" ] || driver=none
echo "      driver: $driver (nvidia-smi); toolchain.txt says $pinned_driver"

"$root/bin/dawn" --version > /dev/null

# The runtime is compiled once; every native build below links this object.
rt_obj="$work/dawn_rt.o"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$root/runtime/c" -c -o "$rt_obj" "$root/runtime/c/dawn_rt.c" ||
  fail "the C runtime does not compile"

build_native() { # std-dir, bin
  "$root/bin/dawn" __emitc --std "$1" "$here/vadd_diff.dawn" -o "$2.c" > "$2.emit" 2>&1 ||
    { cat "$2.emit" >&2; fail "native emit failed against $1"; }
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" -o "$2" "$2.c" "$rt_obj" -lm > "$2.cc" 2>&1 ||
    { cat "$2.cc" >&2; fail "native compile failed against $1"; }
}

verdict_of() { # transcript
  sed -n 's/^tile-gpu-diff: //p' "$1" | tail -n 1
}

# ---- jvm
rc=0
"$root/bin/dawn" run "$here/vadd_diff.dawn" -- "${cubins[@]}" > "$work/jvm.out" 2> "$work/jvm.err" || rc=$?
[ "$rc" = 0 ] || { cat "$work/jvm.err" >&2; fail "vadd_diff did not run on the JVM (exit $rc)"; }
[ "$(verdict_of "$work/jvm.out")" = "blocked:gpu.unsupported_backend@alloc" ] ||
  { cat "$work/jvm.out" >&2; fail "on the JVM the real handler must stop at the first operation with gpu.unsupported_backend"; }
echo "PASS  jvm: the real handler refuses every operation with gpu.unsupported_backend (no device runtime)"

# ---- native, clean std
build_native "$root/std" "$work/clean.bin"
rc=0
"$work/clean.bin" "${cubins[@]}" > "$work/clean.out" 2> "$work/clean.err" || rc=$?
cat "$work/clean.out"
verdict="$(verdict_of "$work/clean.out")"
case "$verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: vadd and vadd_bf16 on the GPU are bit-identical to the fake device in every set" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $verdict" ;;
  fail) cat "$work/clean.err" >&2; fail "the device answered and disagreed with the fake device (see the transcript above)" ;;
  *) cat "$work/clean.err" >&2; fail "vadd_diff printed no verdict (exit $rc)" ;;
esac
note="$(sed -n 's/^  note  //p' "$work/clean.out" | head -n 1)"

# ---- mutants: a copy of std with one anchor rewritten in std/gpu.dawn
if command -v md5sum > /dev/null 2>&1; then
  digest() { md5sum "$1" | cut -d' ' -f1; }
else
  digest() { md5 -q "$1"; }
fi

mutant_std() { # name, old, new  -> prints the std copy's path
  local dir="$work/std-$1"
  rm -rf "$dir"
  cp -r "$root/std" "$dir"
  local before after
  before=$(digest "$dir/gpu.dawn")
  python3 - "$dir/gpu.dawn" "$1" "$2" "$3" <<'PY'
import pathlib
import sys

path, label, old, new = sys.argv[1:]
p = pathlib.Path(path)
text = p.read_text()
if text.count(old) != 1:
    raise SystemExit(f"mutant {label}: anchor is not unique in std/gpu.dawn ({text.count(old)} matches)")
p.write_text(text.replace(old, new))
PY
  after=$(digest "$dir/gpu.dawn")
  echo "      $1: std/gpu.dawn md5 $before -> $after" >&2
  echo "$dir"
}

# A memory-path mutant: the program says `fail` with exit 1, and exactly
# the sets of <dtype> (all <count> of them) say differ:roundtrip, the
# other format's sets being untouched. Required on every driver: alloc,
# upload and download are the part a pre-r580 driver can already run.
roundtrip_mutant_checks() { # name, std-dir, dtype, count
  local name="$1" std_dir="$2" dtype="$3" count="$4" rc=0 hit
  build_native "$std_dir" "$work/m-$name.bin"
  "$work/m-$name.bin" "${cubins[@]}" > "$work/m-$name.out" 2>&1 || rc=$?
  if [ "$(verdict_of "$work/m-$name.out")" != fail ] || [ "$rc" != 1 ]; then
    cat "$work/m-$name.out" >&2
    fail "$name mutant stayed green: the $dtype round trips should differ (verdict $(verdict_of "$work/m-$name.out"), exit $rc)"
  fi
  hit=$(grep -c '^  verdict differ:roundtrip$' "$work/m-$name.out" || true)
  [ "$hit" = "$count" ] ||
    { cat "$work/m-$name.out" >&2; fail "$name: expected all $count $dtype sets and no other to say differ:roundtrip, got $hit"; }
  # every differing set is one of the format's: the other format is untouched
  awk -v dt="$dtype" '/^set /{cur=$3} /^  verdict differ:roundtrip$/ && cur != dt {bad=1} END {exit bad}' "$work/m-$name.out" ||
    { cat "$work/m-$name.out" >&2; fail "$name: a set of the other format moved"; }
  echo "PASS  mutant: $name (every $dtype set's round trip differs, the other format's do not; verdict fail, exit 1)"
}

# 1. download-short: the real handler asks the device for one f64 element
#    fewer than the buffer holds. The round trip is then one element short
#    in every f64 set; the bf16 sets, which download bytes, are untouched.
std_ds="$(mutant_std download-short \
  '          match gpu_download_host(p, n) {' \
  '          match gpu_download_host(p, n - 1) {')"
roundtrip_mutant_checks download-short "$std_ds" f64 4

# 2. pack-truncates: the bf16 packer no longer rounds, so narrow.bf16_bits
#    truncates each Float's extra significand bits instead of rounding them
#    (the mistake a bit-cast of the high half of a binary32 makes). Every
#    bf16 set carries Floats off the grid, so every bf16 round trip differs
#    from what the format holds; the f64 sets are untouched.
std_pt="$(mutant_std pack-truncates \
  '    let bits = narrow.bf16_bits(narrow.round_bf16(x))' \
  '    let bits = narrow.bf16_bits(x)')"
roundtrip_mutant_checks pack-truncates "$std_pt" bf16 3

# 3. grid-zero: the real handler launches over zero tile blocks. Where the
#    clean run passed, the driver must refuse the launch and the verdict must
#    move off `pass`. Where the clean run is blocked before or at the launch,
#    the mutant cannot be told from it, and saying PASS would be the green
#    with no information in it; it is a SKIP with the reason.
std_gz="$(mutant_std grid-zero \
  '                  gpu_launch_host(m, kernel, grid, device_pointers(table, args))' \
  '                  gpu_launch_host(m, kernel, 0, device_pointers(table, args))')"
build_native "$std_gz" "$work/m-grid-zero.bin"
rc=0
"$work/m-grid-zero.bin" "${cubins[@]}" > "$work/m-grid-zero.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-grid-zero.out")"
if [ "$verdict" = pass ]; then
  [ "$mverdict" != pass ] ||
    { cat "$work/m-grid-zero.out" >&2; fail "grid-zero mutant stayed green: a launch over zero blocks still matched the fake device"; }
  echo "PASS  mutant: grid-zero (verdict moved from pass to $mverdict)"
else
  [ "$mverdict" = "$verdict" ] ||
    { cat "$work/m-grid-zero.out" >&2; fail "grid-zero: the clean run is $verdict but the mutant is $mverdict; a mutant before the launch should be indistinguishable"; }
  echo "SKIP  mutant: grid-zero not verifiable on this driver: the clean run is $verdict, before any launch reaches the device"
fi

# ---- ledger
if [ "$append" = no ]; then
  echo "      --dry: ledger not written (would record: $verdict)"
  echo "tile-gpu-diff: $verdict"
  exit 0
fi
[ "$pinned_driver" = "$driver" ] ||
  fail "toolchain.txt says driver $pinned_driver and nvidia-smi says $driver: set the driver line to $driver, commit, and run again (the three numbers move together; the ledger commit adds a line and nothing else)"
dirty="$(git status --porcelain -- packages/tileir std/gpu.dawn std/narrow.dawn runtime/c/dawn_rt.c \
  scripts/tile-golden scripts/tile-gpu-diff/run.sh scripts/tile-gpu-diff/vadd_diff.dawn)"
[ -z "$dirty" ] ||
  { printf '%s\n' "$dirty" >&2; fail "tile paths have uncommitted changes: the ledger line would name a tree that was not run. Commit first."; }
commit="$(git rev-parse --short=12 HEAD)"
today="$(date -u +%F)"
line="$commit $today $driver $want_tileiras $gpu_name $verdict"
[ -z "$note" ] || line="$line # $note"
printf '%s\n' "$line" >> "$ledger"
echo "      ledger: appended: $line"
echo "tile-gpu-diff: $verdict"

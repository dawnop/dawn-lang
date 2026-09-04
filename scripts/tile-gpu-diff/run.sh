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
#   assemble  scripts/tile-golden's recorded bytecode goldens (vadd,
#             vadd_bf16 and the six boundary kernels) through the pinned
#             tileiras into cubins for toolchain.txt's gpu-name. install-tileiras.sh
#             installs the pin under $TILEIRAS_DIR (default
#             ~/.cache/dawn-tileiras) unless $TILEIRAS names a binary.
#   jvm       vadd_diff.dawn on the JVM stops at the first operation with
#             `gpu.unsupported_backend`: the JVM has no device runtime and
#             says so by construction rather than by a LinkageError.
#   native    vadd_diff.dawn built natively runs four f64 and three bf16
#             input sets, mask_diff.dawn the six boundary kernels of
#             knife 7a (each with an output buffer longer than its answer, so
#             that what the mask keeps is compared too), red_diff.dawn the
#             thirteen reduction and transcendental kernels of knife 7b,
#             mm_diff.dawn the seven two-dimensional kernels of knife 8,
#             stride_diff.dawn the nine strided kernels of knife 9,
#             int_diff.dawn the four integer kernels of knife 10 (the first
#             over i32 buffers, and the first family that is exact tier by
#             algebra rather than by a chosen corpus) and wide_diff.dawn the
#             eight wide kernels of knife 11 (the first with more than one
#             output buffer, the first that write a buffer they read, and the
#             first over f16, i8 and u8) and gath_diff.dawn the four gather
#             and scatter kernels of knife 12 (the first whose ADDRESSES are
#             computed rather than recorded, two of them out of a buffer) and
#             scan_diff.dawn the six scan kernels of knife 13 (the first
#             whose region bodies need not commute, and the first family
#             whose float tier is decided by a measurement of the device's
#             fold order rather than by a chosen corpus) and atom_diff.dawn
#             the two atomic kernels of knife 14 (the first in which two
#             lanes may name ONE element, which every scatter here is
#             forbidden to do) and erf_diff.dawn the two error function
#             kernels of knife 15 and seq_diff.dawn the eleven multi-launch
#             problems of knives 16 and 17 (the first whose unit of
#             comparison is a SEQUENCE of launches over shared device buffers
#             rather than a kernel: one allocation, one upload, up to sixteen
#             launches, one download, one verdict, and intermediates that
#             never leave the device),
#             under `with_gpu_real` and `with_gpu_fake` and prints a transcript
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
#             required to move. Knife 16's four are the exception and are
#             not files at all: what they change is the launch SEQUENCE,
#             which seq_diff.dawn carries as data, so they are applied
#             in-process to the real device while the fake device keeps
#             answering the honest sequence. Their red sets are held by
#             name and by count where the seq family runs, below:
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
#     mask-all-true    the package's lowering answers an all-true mask
#                      instead of the comparison -> layers 0 and 1 move but
#                      stay legal (an all-true mask is a mask), and on the
#                      device every boundary kernel writes the lanes past the
#                      end of its vector, so the sentinel in the output
#                      buffer's tail is gone and all six say differ:result.
#                      A launch-layer claim, so SKIP where the clean run is
#                      blocked, for grid-zero's reason
#     grid-y-ignored   the C runtime's cuLaunchKernel forces gridDimY to 1
#                      -> layers 0 and 1 cannot see it at all (a grid is not
#                      in the bytecode) and neither can any earlier program
#                      here (every kernel before knife 8 has a
#                      one-dimensional grid), while on the device the four
#                      kernels with a second grid axis leave the sentinel
#                      where the blocks nobody launched should have written
#     mma-acc-not-carried
#                      the GEMM's K loop starts from a fresh zero tile each
#                      iteration instead of carrying its accumulator ->
#                      layer 0 moves and tileiras accepts the result (it is
#                      a legal kernel), and only the device says matmul
#                      answers the last K slice rather than the product
#     stride-row-major-swapped
#                      the transpose writes with the two stride dimensions
#                      of its OUTPUT layout swapped (the extents of the
#                      input, not of the output) -> layer 0 moves, layer 1
#                      accepts it, and only the device says the values land
#                      in the wrong place. On a SQUARE matrix the two
#                      expressions are the same list and the mutant is not
#                      even a change, which is why stride_diff's matrix is
#                      100 by 60
#     ladder-strides-reversed
#                      the package's LOWERING takes each dimension's stride
#                      from the opposite dimension, so every rank-2 layout
#                      in a kernel is swapped at once -> six of the nine
#                      kernels' bytes move, tileiras accepts all six, and
#                      exactly ONE goes red on the device: reversing every
#                      layout together is a relabelling of the tile's own
#                      axes, which cancels on a square tile.
#                      depthwise_conv1d's tile is 4 by 32 and cannot hide
#                      behind it. Recorded because the surprise is the
#                      evidence: a stride swap in the lowering is invisible
#                      wherever the tile is square
#     halo-one-lane-short
#                      the gaussian blur's tap bound stops one lane early,
#                      so a neighbour at the far edge of the image counts as
#                      padding -> layer 0 moves, layer 1 accepts it (a mask
#                      is a mask) and the device answers a blurred image
#                      that is wrong along two of its four edges.
#                      gaussian_blur is the only kernel with a halo, so the
#                      other eight are the control
#     shri-always-logical
#                      the WRITER gives `shri` the unsigned signedness, so
#                      every arithmetic right shift becomes a logical one ->
#                      layer 0 cannot see it at all (the renderer has its own
#                      table and still prints `signed`), the bytes of the two
#                      kernels that shift right arithmetically move, tileiras
#                      accepts both (a signedness is a signedness), and on the
#                      device exactly those two answer differently. The
#                      corpus is half the claim: the two shifts agree on
#                      every non-negative operand, so int_diff's data spans
#                      the whole i32 range
#     exti-sign-extends
#                      the writer gives `exti` the signed signedness, so a
#                      comparison mask widens to 0 and -1 rather than 0 and 1
#                      -> layer 0 is blind again (the renderer prints
#                      `unsigned` from its own table), the bytes of the two
#                      kernels that widen a mask move, tileiras accepts both,
#                      and on the device `count_eq` answers the negated count
#                      while `int_ops`'s parity term becomes -1. The other two
#                      widen nothing and are the control.
#                      Its sibling `ftoi-rounds-instead-of-truncates` is NOT
#                      here: it is refused at layer 1 (scripts/tile-golden's
#                      mutant list), because `nearest_int_to_zero` is the one
#                      integer rounding mode the dialect accepts and tileiras
#                      says so. Measured, not assumed
#     inplace-writes-copy
#                      the fake device applies a reference's write-back to a
#                      handle NOBODY HAS instead of the argument position the
#                      reference named -> layers 0 and 1 are blind by
#                      construction (std/gpu emits no Tile IR; not one
#                      golden byte moves) and every one of the eight wide
#                      kernels differs, because its answer now lands where
#                      nothing reads it. The two IN-PLACE kernels are where
#                      the mistake is legible rather than merely fatal:
#                      `reverse` and `invert` read back the buffer they were
#                      given, so under the mutant that buffer still holds the
#                      CORPUS, while the six others read back a buffer that
#                      still holds the sentinel. The gate checks both
#                      readings
#     f16-rounds-like-bf16
#                      the f16 packer rounds with `narrow.round_bf16` before
#                      laying down the binary16 pattern, which is the mistake
#                      of copying `pack_bf16` and changing only the codec ->
#                      layer 0 and layer 1 are blind again, and on the device
#                      exactly ONE of the eight goes red. The corpus is the
#                      whole of the difference: bf16 and f16 agree on every
#                      value with eight significand bits, so `dot_f16`'s
#                      small integers and the two GEMMs' multiples of a half
#                      pack identically under both roundings even though all
#                      three upload f16 buffers. Only `f16_ops`, whose corpus
#                      is deliberately off the bf16 grid, can see it. Three
#                      f16 kernels as the control and a fourth that reds is a
#                      stronger statement than four that red
#     u8-reads-signed  the real handler unpacks a u8 buffer with `unpack_i8`,
#                      so an octet above 127 comes back negative -> layers 0
#                      and 1 blind, and `invert` alone reds: it is the only
#                      kernel here over an 8-bit buffer, and its corpus spans
#                      the WHOLE octet range on purpose. A corpus of the low
#                      half would forgive this entirely, which is the same
#                      shape as knife 10's shri-always-logical
#     gather-mask-dropped
#                      the package's `gather_masked` stops passing the mask
#                      and the padding value, so every gather reads every
#                      lane -> layer 0 moves and layer 1 accepts it (a load
#                      without a mask is a load), and only the device says
#                      that `token_embed`'s eleven out-of-range ids read the
#                      table instead of the miss value. It answers a WRONG
#                      NUMBER rather than faulting because the kernel clamps
#                      the address as well as masking the lane, which is
#                      what makes this a layer-2 mutant at all. The other
#                      three kernels gather nothing and are the control, in
#                      the bytes and on the device both
#     scatter-unpermuted
#                      `scatter_perm`'s kernel writes at the LANE index
#                      instead of at the destination it read out of a buffer
#                      -> layer 0 moves, layer 1 accepts it (one index tile
#                      is as legal as another), and the device says 255 of
#                      264 lanes hold the wrong value. The permutation is
#                      the whole of what the kernel does and nothing below
#                      the device knows it
#     rank-scatter-in-lane-order
#                      `sort_rank` stores its values contiguously instead of
#                      scattering them at the ranks it computed -> the ranks
#                      are still computed and still correct, and only the
#                      device says the answer is the input. The scatter is
#                      what turns a rank into a sort
#     scan-reverse-ignored
#                      the writer pins a scan's `reverse` attribute to
#                      false -> layer 0 is blind (the renderer prints the
#                      record's own `reverse=true`) and layer 1 accepts it,
#                      and on the device `gae` alone answers a forward
#                      prefix where leetgpu 110 wants a backward one. It is
#                      also the only kernel whose BYTES move, so the other
#                      six are the control twice over
#     exclusive-scan-as-inclusive
#                      `compact` scatters at the inclusive count of kept
#                      lanes instead of the exclusive one -> every value
#                      lands one place late and element 0 is never written.
#                      The dialect's scan is inclusive and has no attribute
#                      to make it exclusive, so subtracting the lane's own
#                      element is the only spelling and getting it wrong is
#                      a legal kernel. `seg_scan` takes the same step in
#                      floats through a different expression and is the
#                      control
#     atomic-as-plain-store
#                      the package's `atomic_add_masked` stops issuing an
#                      atomic and issues a gather, an addi and a scatter
#                      instead, which is what the operation would be if the
#                      lanes never collided -> layer 0 moves and layer 1
#                      accepts it (a load and a store are a load and a
#                      store), and on the device the histogram loses every
#                      increment but one per bin per block. `cas_swap` does
#                      not use the surface and is the control in the bytes
#                      as well as on the device.
#                      Its CORPUS is the other half of the claim and is
#                      checked as one: the same mutant is run a second time
#                      with atom_diff's `--corpus unique`, one lane a bin
#                      and no bin twice, where it must stay GREEN. Without
#                      that second run "the mutant reds" would not say
#                      whether the atomic or the corpus did the work
#     cas-compare-ignored
#                      `cas_swap` hands the compare-and-swap the value it is
#                      about to write as the value it expects to find, so
#                      the comparison can never decide anything -> layer 0
#                      moves, layer 1 accepts it (one i32 tile is as legal
#                      as another) and only the device says that the 34
#                      slots that should have taken a new value kept the
#                      old one. The histogram is the control and its bytes
#                      do not move
#     erf-tanh-approx  the package's `erf` stops running Abramowitz-Stegun
#                      7.1.26 and runs the tanh formula PyTorch calls
#                      `gelu(approximate="tanh")` instead -> layer 0 moves
#                      and layer 1 accepts it (a `tanh` is as legal as an
#                      `exp`), and on the device both kernels are out by
#                      about 3.6e-4, which is 36 times the `atol = 1e-5`
#                      they are compared under. This one exists to show the
#                      TIER IS NOT LOOSE: a tolerance that forgave it would
#                      forgive an approximation nobody chose
#     erf-sign-not-flipped
#                      the package's `erf` drops the odd symmetry and
#                      answers `erf(|x|)` -> layer 0 moves, layer 1 accepts
#                      it (the `select` and its compare simply are not
#                      there) and on the device every negative lane has the
#                      wrong sign.
#                      Its CORPUS is the other half of the claim and is
#                      checked as one, the way atomic-as-plain-store's is:
#                      the same mutant is run again with erf_diff's
#                      `--corpus positive`, every lane non-negative, where
#                      it must stay GREEN. The tanh mutant is run against
#                      that corpus too and must still RED, which is what
#                      separates "the corpus caught it" from "anything
#                      would have"
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

# The boundary kernels of knife 7a, in the order mask_diff takes them.
masked=(vadd_tail copy relu leaky_relu clip elemops)

# The reduction, transcendental and region kernels of knife 7b, in the order
# red_diff takes them.
reduced=(reduce_sum softmax dot mse monte_carlo rms_norm silu sigmoid ppo_loss dpo_loss mathops foldif argmax
  agent_step)

# The two-dimensional kernels of knife 8, in the order mm_diff takes them.
# The first three run over a grid with more than one axis.
twod=(matmul batched_matmul transpose layer_norm batch_norm group_norm fused_rms_norm matvec)

# The strided kernels of knife 9, in the order stride_diff takes them. Six
# read or write a rank-2 layout and three are rank-1 ladders, which is the
# split stride-row-major-swapped below is held to.
strided=(transpose_tail conv1d conv2d max_pool interleave rgb_gray jacobi depthwise_conv1d gaussian_blur
  conv3d)

# The integer kernels of knife 10, in the order int_diff takes them. The
# first two reduce over one block; the last two are element-wise over eight.
# Only the last two shift right arithmetically, and only the last converts,
# which is the split the two mutants below are held to.
integers=(count_eq subarray_sum rainbow int_ops subarray_sum2d subarray_sum3d)

# The wide kernels of knife 11, in the order wide_diff takes them. Two are
# in place (reverse, invert), one fills two buffers (sum_diff), four upload
# f16 buffers (f16_ops, dot_f16, matmul_f16, batched_matmul_f16) and one is
# over 8-bit buffers (invert), which are the four splits the mutants below
# are held to.
wide=(sum_diff reverse invert f16_ops dot_f16 matmul_f16 batched_matmul_f16 matmul_i8)

# The gather and scatter kernels of knife 12, in the order gath_diff takes
# them. Only `token_embed` gathers, only `scatter_perm` scatters through a
# mask, and the two rank kernels scatter without one, which is the split the
# three mutants below are held to.
gathered=(token_embed sort_rank merge_rank scatter_perm dequant nearest_idx)

# The scan kernels of knife 13, in the order scan_diff takes them. Only
# `gae` scans in reverse and only `compact` turns an inclusive scan into an
# exclusive one at the point where it matters, which are the two splits the
# mutants below are held to. Two are integer scans and exact tier; the five
# float ones are tolerance tier, because the device does not fold a prefix
# the way a host reference does (measured, see the order probe). `ssm_scan`
# is the only one over a rank-2 tile and the only one with a second grid
# axis.
scanned=(prefix_sum max_subarray seg_scan compact linrec gae ssm_scan)

# The atomic kernels of knife 14, in the order atom_diff takes them. Only
# `histogram` has colliding lanes and only `cas_swap` compares, which are
# the two splits the mutants below are held to.
atomic=(histogram cas_swap)

# The error function kernels of knife 15, in the order erf_diff takes them.
# Both go through the package's `erf` composition, so both mutants below
# move both of them: what separates the two mutants is the CORPUS, not the
# kernel, which is why this family has no kernel-level control and runs
# every mutant twice instead.
erfs=(erf_sweep geglu swiglu_half)

# Of those three, the two that go through the package's `erf` composition
# and the one that does not: knife 18's `swiglu_half` has `geglu`'s shape
# (one buffer, two halves, a gate) and a swish where the gate is, so it is
# the family's kernel-level control -- neither erf mutant may move it, at
# layer 0 or on the device -- and the corpus lines below, which count what
# 7.1.26 sees, are held over `erf_red` and not over all three.
erf_red=(erf_sweep geglu)
erf_green=(swiglu_half)

# The multi-launch kernels of knives 16 and 17, in the order seq_diff takes
# them on the command line. These are not eighteen independent kernels the
# way every list above is: they are the STEPS of eleven sequences, and what
# seq_diff compares is one buffer at the end of a sequence, not one buffer
# per kernel. `matpow_step` belongs to two sequences (leetgpu 37 and the
# decoupled control), `swiglu_proj` is launched twice inside one, and
# `attn_softmax` and `attn_context` are steps of five and six of them: knife
# 17's four masked-score problems reuse both, and its decayed one reuses the
# context product. That reuse is why six more problems cost seven kernels.
# Knife 20 spends the same coin harder: `attn_scores` is a step of NINE
# sequences after it (leetgpu 111 launches it twice inside one sequence, on
# different operands), `attn_softmax` of ten, and leetgpu 56's two launches
# of `lin_attn_s` differ only in which buffer is its second argument.
sequenced=(lora_base lora_hidden lora_out attn_scores attn_softmax attn_context
  matpow_step swiglu_proj swiglu_act swiglu_down apsp_step
  attn_causal attn_alibi attn_window attn_sinks attn_decay cce_row cce_mean
  mha_scores mha_context
  xattn_scores xattn_context gqa_scores gqa_context grpo_adv grpo_row
  kmeans_assign kmeans_centroid
  kv_scores kv_context attn_bwd_mmt attn_bwd_ds lin_attn_s lin_attn_out
  ols_gram ols_elim ols_beta)

# tileiras can exit 0 and still print a diagnostic (scripts/tile-golden's
# `assemble` says which one), so the empty error stream is part of the
# verdict here too.
assemble_golden() { # kernel, tilebc, cubin
  "$tileiras" --gpu-name "$gpu_name" -o "$3" "$2" > "$work/assemble.log" 2>&1 ||
    { cat "$work/assemble.log" >&2; fail "tileiras refused $2"; }
  ! grep -q '^error:' "$work/assemble.log" ||
    { cat "$work/assemble.log" >&2; fail "tileiras exited 0 but refused $2"; }
  [ "$(head -c 4 "$3" | od -An -tx1 | tr -d ' \n')" = 7f454c46 ] ||
    fail "tileiras wrote no ELF cubin for $1"
}

for k in vadd vadd_bf16 "${masked[@]}" "${reduced[@]}" "${twod[@]}" "${strided[@]}" "${integers[@]}" \
  "${wide[@]}" "${gathered[@]}" "${scanned[@]}" "${atomic[@]}" "${erfs[@]}" "${sequenced[@]}"; do
  assemble_golden "$k" "$golden/$k.tilebc" "$work/$k.cubin"
  echo "PASS  assemble: $k.tilebc -> cubin ($(wc -c < "$work/$k.cubin") bytes, tileiras V$want_tileiras, $gpu_name)"
done
cubins=("$work/vadd.cubin" "$work/vadd_bf16.cubin")
masked_cubins=()
for k in "${masked[@]}"; do masked_cubins+=("$work/$k.cubin"); done
reduced_cubins=()
for k in "${reduced[@]}"; do reduced_cubins+=("$work/$k.cubin"); done
twod_cubins=()
for k in "${twod[@]}"; do twod_cubins+=("$work/$k.cubin"); done
strided_cubins=()
for k in "${strided[@]}"; do strided_cubins+=("$work/$k.cubin"); done
int_cubins=()
for k in "${integers[@]}"; do int_cubins+=("$work/$k.cubin"); done
wide_cubins=()
for k in "${wide[@]}"; do wide_cubins+=("$work/$k.cubin"); done
gath_cubins=()
for k in "${gathered[@]}"; do gath_cubins+=("$work/$k.cubin"); done
scan_cubins=()
for k in "${scanned[@]}"; do scan_cubins+=("$work/$k.cubin"); done
atom_cubins=()
for k in "${atomic[@]}"; do atom_cubins+=("$work/$k.cubin"); done
erf_cubins=()
for k in "${erfs[@]}"; do erf_cubins+=("$work/$k.cubin"); done
seq_cubins=()
for k in "${sequenced[@]}"; do seq_cubins+=("$work/$k.cubin"); done

driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | tr -d ' ' || true)"
[ -n "$driver" ] || driver=none
echo "      driver: $driver (nvidia-smi); toolchain.txt says $pinned_driver"

"$root/bin/dawn" --version > /dev/null

# The runtime is compiled once; every native build below links this object.
rt_obj="$work/dawn_rt.o"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$root/runtime/c" -c -o "$rt_obj" "$root/runtime/c/dawn_rt.c" ||
  fail "the C runtime does not compile"

build_native() { # std-dir, bin, program (default vadd_diff.dawn)
  local program="${3:-$here/vadd_diff.dawn}"
  "$root/bin/dawn" __emitc --std "$1" "$program" -o "$2.c" > "$2.emit" 2>&1 ||
    { cat "$2.emit" >&2; fail "native emit failed for $program against $1"; }
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" -o "$2" "$2.c" "$rt_obj" -lm > "$2.cc" 2>&1 ||
    { cat "$2.cc" >&2; fail "native compile failed for $program against $1"; }
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

# ---- native, the boundary kernels (knife 7a)
build_native "$root/std" "$work/masked.bin" "$here/mask_diff.dawn"
rc=0
"$work/masked.bin" "${masked_cubins[@]}" > "$work/masked.out" 2> "$work/masked.err" || rc=$?
cat "$work/masked.out"
masked_verdict="$(verdict_of "$work/masked.out")"
case "$masked_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the six boundary kernels on the GPU are bit-identical to the fake device, tail lanes included" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $masked_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $masked_verdict" ;;
  fail) cat "$work/masked.err" >&2; fail "the device answered and disagreed with the fake device on a boundary kernel (see the transcript above)" ;;
  *) cat "$work/masked.err" >&2; fail "mask_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/masked.out" | head -n 1)"

# ---- native, the reduction and transcendental kernels (knife 7b)
build_native "$root/std" "$work/reduced.bin" "$here/red_diff.dawn"
rc=0
"$work/reduced.bin" "${reduced_cubins[@]}" > "$work/reduced.out" 2> "$work/reduced.err" || rc=$?
cat "$work/reduced.out"
reduced_verdict="$(verdict_of "$work/reduced.out")"
case "$reduced_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#reduced[@]} reduction and transcendental kernels agree with the fake device, each under its own tier" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $reduced_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $reduced_verdict" ;;
  fail) cat "$work/reduced.err" >&2; fail "the device answered and disagreed with the fake device on a reduction kernel (see the transcript above)" ;;
  *) cat "$work/reduced.err" >&2; fail "red_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/reduced.out" | head -n 1)"

# ---- native, the two-dimensional kernels (knife 8)
build_native "$root/std" "$work/twod.bin" "$here/mm_diff.dawn"
rc=0
"$work/twod.bin" "${twod_cubins[@]}" > "$work/twod.out" 2> "$work/twod.err" || rc=$?
cat "$work/twod.out"
twod_verdict="$(verdict_of "$work/twod.out")"
case "$twod_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#twod[@]} two-dimensional kernels agree with the fake device, each under its own tier" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $twod_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $twod_verdict" ;;
  fail) cat "$work/twod.err" >&2; fail "the device answered and disagreed with the fake device on a two-dimensional kernel (see the transcript above)" ;;
  *) cat "$work/twod.err" >&2; fail "mm_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/twod.out" | head -n 1)"

# ---- native, the strided kernels (knife 9)
build_native "$root/std" "$work/strided.bin" "$here/stride_diff.dawn"
rc=0
"$work/strided.bin" "${strided_cubins[@]}" > "$work/strided.out" 2> "$work/strided.err" || rc=$?
cat "$work/strided.out"
strided_verdict="$(verdict_of "$work/strided.out")"
case "$strided_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#strided[@]} strided kernels are bit-identical to the fake device, tails included" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $strided_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $strided_verdict" ;;
  fail) cat "$work/strided.err" >&2; fail "the device answered and disagreed with the fake device on a strided kernel (see the transcript above)" ;;
  *) cat "$work/strided.err" >&2; fail "stride_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/strided.out" | head -n 1)"

# ---- native, the integer kernels (knife 10)
build_native "$root/std" "$work/ints.bin" "$here/int_diff.dawn"
rc=0
"$work/ints.bin" "${int_cubins[@]}" > "$work/ints.out" 2> "$work/ints.err" || rc=$?
cat "$work/ints.out"
int_verdict="$(verdict_of "$work/ints.out")"
case "$int_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#integers[@]} integer kernels on the GPU are bit-identical to the fake device, i32 buffers and tails included" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $int_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $int_verdict" ;;
  fail) cat "$work/ints.err" >&2; fail "the device answered and disagreed with the fake device on an integer kernel (see the transcript above)" ;;
  *) cat "$work/ints.err" >&2; fail "int_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/ints.out" | head -n 1)"

# ---- native, the wide kernels (knife 11)
build_native "$root/std" "$work/wide.bin" "$here/wide_diff.dawn"
rc=0
"$work/wide.bin" "${wide_cubins[@]}" > "$work/wide.out" 2> "$work/wide.err" || rc=$?
cat "$work/wide.out"
wide_verdict="$(verdict_of "$work/wide.out")"
case "$wide_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#wide[@]} wide kernels on the GPU are bit-identical to the fake device, both outputs and both in-place buffers included" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $wide_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $wide_verdict" ;;
  fail) cat "$work/wide.err" >&2; fail "the device answered and disagreed with the fake device on a wide kernel (see the transcript above)" ;;
  *) cat "$work/wide.err" >&2; fail "wide_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/wide.out" | head -n 1)"

# ---- native, the gather and scatter kernels (knife 12)
build_native "$root/std" "$work/gath.bin" "$here/gath_diff.dawn"
rc=0
"$work/gath.bin" "${gath_cubins[@]}" > "$work/gath.out" 2> "$work/gath.err" || rc=$?
cat "$work/gath.out"
gath_verdict="$(verdict_of "$work/gath.out")"
case "$gath_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#gathered[@]} gather and scatter kernels on the GPU are bit-identical to the fake device, tails included" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $gath_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $gath_verdict" ;;
  fail) cat "$work/gath.err" >&2; fail "the device answered and disagreed with the fake device on a gather or scatter kernel (see the transcript above)" ;;
  *) cat "$work/gath.err" >&2; fail "gath_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/gath.out" | head -n 1)"

# ---- native, the scan kernels (knife 13)
build_native "$root/std" "$work/scan.bin" "$here/scan_diff.dawn"
rc=0
"$work/scan.bin" "${scan_cubins[@]}" > "$work/scan.out" 2> "$work/scan.err" || rc=$?
cat "$work/scan.out"
scan_verdict="$(verdict_of "$work/scan.out")"
case "$scan_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#scanned[@]} scan kernels agree with the fake device, each under its own tier" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $scan_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $scan_verdict" ;;
  fail) cat "$work/scan.err" >&2; fail "the device answered and disagreed with the fake device on a scan kernel (see the transcript above)" ;;
  *) cat "$work/scan.err" >&2; fail "scan_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/scan.out" | head -n 1)"

# ---- native, the atomic kernels (knife 14)
build_native "$root/std" "$work/atom.bin" "$here/atom_diff.dawn"
rc=0
"$work/atom.bin" "${atom_cubins[@]}" > "$work/atom.out" 2> "$work/atom.err" || rc=$?
cat "$work/atom.out"
atom_verdict="$(verdict_of "$work/atom.out")"
case "$atom_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#atomic[@]} atomic kernels on the GPU are bit-identical to the fake device, colliding lanes and all" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $atom_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $atom_verdict" ;;
  fail) cat "$work/atom.err" >&2; fail "the device answered and disagreed with the fake device on an atomic kernel (see the transcript above)" ;;
  *) cat "$work/atom.err" >&2; fail "atom_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/atom.out" | head -n 1)"

# ---- native, the error function kernels (knife 15)
build_native "$root/std" "$work/erf.bin" "$here/erf_diff.dawn"
rc=0
"$work/erf.bin" "${erf_cubins[@]}" > "$work/erf.out" 2> "$work/erf.err" || rc=$?
cat "$work/erf.out"
erf_verdict="$(verdict_of "$work/erf.out")"
case "$erf_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the ${#erfs[@]} error function kernels agree with the fake device inside the tolerance tier" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $erf_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $erf_verdict" ;;
  fail) cat "$work/erf.err" >&2; fail "the device answered and disagreed with the fake device on an error function kernel (see the transcript above)" ;;
  *) cat "$work/erf.err" >&2; fail "erf_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/erf.out" | head -n 1)"

# The same two kernels on the CONTROL corpus, where no lane is negative and
# the odd symmetry's `select` never chooses its negated arm. The clean run
# must pass there as well -- it is the same kernel -- and what matters is
# the negative count on the index lines, which the erf-sign-not-flipped
# mutant needs to be zero here and nonzero above.
rc=0
"$work/erf.bin" --corpus positive "${erf_cubins[@]}" > "$work/erf-positive.out" 2> "$work/erf-positive.err" || rc=$?
erf_positive_verdict="$(verdict_of "$work/erf-positive.out")"
[ "$erf_positive_verdict" = "$erf_verdict" ] ||
  { cat "$work/erf-positive.out" >&2; fail "the control corpus answers $erf_positive_verdict where the main one answers $erf_verdict"; }

# The same two programs on the CONTROL corpus, where no two lanes share a
# bin. The clean run must pass there as well -- it is the same kernel -- and
# the number that matters is the collision count on the line below, which
# the atomic-as-plain-store mutant needs to be zero here and nonzero above.
rc=0
"$work/atom.bin" --corpus unique "${atom_cubins[@]}" > "$work/atom-unique.out" 2> "$work/atom-unique.err" || rc=$?
atom_unique_verdict="$(verdict_of "$work/atom-unique.out")"
[ "$atom_unique_verdict" = "$atom_verdict" ] ||
  { cat "$work/atom-unique.out" >&2; fail "the control corpus answers $atom_unique_verdict where the main one answers $atom_verdict"; }

# ---- native, the multi-launch sequences (knife 16)
#
# One program, six sequences, and a verdict per sequence rather than per
# kernel: this is the first family here whose unit of comparison is a
# SEQUENCE of launches over shared device buffers. Its mutants are inside
# the program, because the thing being mutated is the launch sequence and a
# launch sequence is data (seq_diff.dawn's header says why); what this
# script does is hold the verdicts, the red sets and the corpus counts the
# program prints.
build_native "$root/std" "$work/seq.bin" "$here/seq_diff.dawn"
rc=0
"$work/seq.bin" "${seq_cubins[@]}" > "$work/seq.out" 2> "$work/seq.err" || rc=$?
cat "$work/seq.out"
seq_verdict="$(verdict_of "$work/seq.out")"
case "$seq_verdict" in
  pass) [ "$rc" = 0 ] || fail "verdict pass with exit $rc"
        echo "PASS  native: the twenty multi-launch problems and the decoupled control agree with the fake device, sequence for sequence" ;;
  blocked:*) [ "$rc" = 0 ] || fail "verdict $seq_verdict with exit $rc"
        echo "BLOCKED  native: the driver refused before a result could be compared: $seq_verdict" ;;
  fail) cat "$work/seq.err" >&2; fail "the device answered and disagreed with the fake device on a sequence (see the transcript above)" ;;
  *) cat "$work/seq.err" >&2; fail "seq_diff printed no verdict (exit $rc)" ;;
esac
[ -n "$note" ] || note="$(sed -n 's/^  note  //p' "$work/seq.out" | head -n 1)"

# An atomic add is only an atomic where two lanes meet. gath_diff holds its
# scatter's repeats DOWN to zero for the opposite reason; here the repeats
# are the point, and a corpus that stopped having them would leave the
# mutant below nothing to catch.
hist_shape="$(awk '/^kernel histogram /{f=1} f && /^  index /{print; exit}' "$work/atom.out")"
case "$hist_shape" in
  *bin_repeated=0*) fail "the histogram's corpus has no repeated bin, so its atomic is not being tested: $hist_shape" ;;
  *cross_block_bins=0*) fail "the histogram's corpus has no bin shared between blocks: $hist_shape" ;;
  *) echo "PASS  corpus: the histogram's bins collide, and across blocks ($hist_shape)" ;;
esac
hist_unique_shape="$(awk '/^kernel histogram /{f=1} f && /^  index /{print; exit}' "$work/atom-unique.out")"
case "$hist_unique_shape" in
  *bin_repeated=0*) echo "PASS  corpus: the control corpus has one lane a bin ($hist_unique_shape)" ;;
  *) fail "the control corpus has repeated bins, so it is not a control: $hist_unique_shape" ;;
esac

# A compare-and-swap whose corpus never matches would forgive a mutant that
# ignores the comparison, and one that never masks would leave half the
# surface untested.
slot_shape="$(awk '/^kernel cas_swap /{f=1} f && /^  index /{print; exit}' "$work/atom.out")"
case "$slot_shape" in
  *matched=0*) fail "no slot in the compare-and-swap's corpus matches, so nothing is ever swapped: $slot_shape" ;;
  *masked=0*) fail "no slot in the compare-and-swap's corpus is masked out: $slot_shape" ;;
  *) echo "PASS  corpus: the compare-and-swap's corpus matches, misses and masks ($slot_shape)" ;;
esac

# A scatter whose lanes name one element twice has NO answer on the device,
# so a corpus that stopped being a permutation would turn every verdict
# above into a coin toss rather than a comparison. gath_diff counts the
# repeats among its IN-RANGE destinations and prints them; this is where the
# count is held to zero. The gather case is the control: its ids repeat 31
# times over and that is legal.
scatter_repeats="$(awk '/^kernel scatter_perm /{f=1} f && /^  index /{print; exit}' "$work/gath.out")"
case "$scatter_repeats" in
  *in_range_repeated=0) echo "PASS  corpus: scatter_perm's destinations are a permutation ($scatter_repeats)" ;;
  *) fail "scatter_perm's corpus is not a permutation, so its verdict means nothing: $scatter_repeats" ;;
esac

# Abramowitz-Stegun 7.1.26 is an approximation, so the corpus is what says
# WHERE it was checked. Three counts, all of them held above zero: the
# negative lanes (the odd symmetry, and the only branch in the
# composition), the lanes past |x| = 4 (the tail, where `t` goes to zero
# and `exp(-x^2)` underflows) and the lanes near zero. Both kernels carry
# all three; `geglu`'s are counted on what its gate hands the composition,
# after the 1/sqrt(2).
for k in "${erf_red[@]}"; do
  erf_shape="$(awk -v want="$k" '$1 == "kernel" && $2 == want {f=1} f && /^  index /{print; exit}' "$work/erf.out")"
  case "$erf_shape" in
    *negative=0\ *) fail "$k's corpus has no negative lane, so the odd symmetry is not being tested: $erf_shape" ;;
    *\ tail=0\ *) fail "$k's corpus never reaches |x| > 4, so 7.1.26's tail is not being tested: $erf_shape" ;;
    *near_zero=0) fail "$k's corpus has no lane near zero: $erf_shape" ;;
    *) echo "PASS  corpus: $k covers the negative half, the tail and the neighbourhood of zero ($erf_shape)" ;;
  esac
  erf_positive_shape="$(awk -v want="$k" '$1 == "kernel" && $2 == want {f=1} f && /^  index /{print; exit}' "$work/erf-positive.out")"
  case "$erf_positive_shape" in
    *negative=0\ *) echo "PASS  corpus: $k's control corpus has no negative lane ($erf_positive_shape)" ;;
    *) fail "$k's control corpus has negative lanes, so it is not a control: $erf_positive_shape" ;;
  esac
done

# leetgpu 14's corpus is two claims in one line. A flock where every agent
# has a neighbour would never take the branch that keeps an agent's own
# velocity, and one where none does would leave all three reductions with
# nothing to fold; both counts are held above zero.
agents_shape="$(sed -n 's/^probe agents //p' "$work/reduced.out" | tail -n 1)"
case "$agents_shape" in
  *isolated=0\ *) fail "no agent in the flocking corpus is alone, so the empty-neighbourhood branch is not being tested: $agents_shape" ;;
  *crowded=0) fail "every agent in the flocking corpus is alone, so nothing is ever averaged: $agents_shape" ;;
  *) echo "PASS  corpus: the flock has isolated agents and crowded ones ($agents_shape)" ;;
esac

# A nearest neighbour is only an answer where it is unique: the fold order
# of a reduction is not specified, so a point with two equally near
# neighbours is the same undefined case as a scatter with two lanes on one
# element. gath_diff counts the ties and this is where the count is held to
# zero.
nearest_ties="$(awk '/^kernel nearest_idx /{f=1} f && /^  index /{print; exit}' "$work/gath.out")"
case "$nearest_ties" in
  *nearest_ties=0) echo "PASS  corpus: no point has two equally near neighbours ($nearest_ties)" ;;
  *) fail "the point cloud has a tie, so nearest_idx's answer is not defined there: $nearest_ties" ;;
esac

# THE SEQUENCE FAMILY'S CORPUS, and it is a measurement rather than a
# sentence. A sequence of launches is only a sequence if a later launch
# reads what an earlier one wrote; a corpus where it does not is a corpus
# where every mutant below would be forgiven and every verdict would still
# be green. seq_diff prints, for each sequence, how many lanes of the
# ANSWER change when the intermediate is put back to what it was uploaded
# with -- both sides the fake device, so this is a property of the corpus
# and the references and not of the GPU.
#
# The twenty problems must be above zero. `decoupled` must be exactly zero:
# it is two launches whose second does not read the first's output, and it
# is the control that says the counter can print a zero at all. Without
# it, "has never printed zero" and "cannot print zero" look the same.
for s in lora attention matpow swiglu apsp causal alibi window sinks decay cce mha xattn gqa grpo kmeans \
  kv attnbwd linattn ols; do
  seq_shape="$(awk -v want="$s" '$1 == "sequence" && $2 == want {f=1} f && /^  index /{print; exit}' "$work/seq.out")"
  case "$seq_shape" in
    *changed_by_first=0) fail "$s's answer does not depend on its earlier launches, so it is not a sequence: $seq_shape" ;;
    *) echo "PASS  corpus: $s's answer depends on what an earlier launch wrote ($seq_shape)" ;;
  esac
done
seq_control_shape="$(awk '$1 == "sequence" && $2 == "decoupled" {f=1} f && /^  index /{print; exit}' "$work/seq.out")"
case "$seq_control_shape" in
  *changed_by_first=0) echo "PASS  corpus: the decoupled control's answer depends on no earlier launch ($seq_control_shape)" ;;
  *) fail "the decoupled control's second launch reads the first's output, so it is not a control: $seq_control_shape" ;;
esac

# `repeat`'s two boundaries. A repetition whose count is a host value can be
# off by one in a way every sequence above would agree with, because they
# would all be off by one together.
seq_repeat="$(sed -n 's/^probe repeat //p' "$work/seq.out" | tail -n 1)"
[ "$seq_repeat" = "one_round_equals_single=true zero_rounds_equals_upload=true" ] ||
  fail "repeat(n) does not agree with itself at its boundaries: $seq_repeat"
echo "PASS  repeat: one round is the single-round sequence and zero rounds leave every buffer as uploaded"

# The mutants of the judgement itself, by NAME and by COUNT. Each is a
# transformation of the sequence applied to the real device while the fake
# device answers the honest one, and the table below is the whole claim:
# which sequences each one reaches, and which it must leave alone.
#
#   second-launch-sees-stale-buffer
#       the driver puts the intermediate's uploaded contents back just
#       before the launch that reads it -> every problem reds. The
#       decoupled control does not, which is the same argument knife 14's
#       collision-free corpus makes: the mutant catches the DEPENDENCY and
#       not the presence of a second launch.
#   launch-order-swapped
#       the launches are issued in reverse -> four of the five problems
#       red. `apsp` does NOT, and not by luck: Floyd-Warshall's rounds
#       commute. Split a shortest path at the LAST of its intermediates to
#       be processed and both halves were finished before that round, in
#       any order, so one pass over every k is correct however the k are
#       ordered. What the sequence owes is that all sixteen run, which is
#       last-launch-dropped's job, not that they run in order. Algebra
#       again, the way knife 10's exact tier and knife 14's were: recorded
#       here because a reader who expected a red would otherwise call this
#       a hole.
#   last-launch-dropped
#       the final launch never happens -> everything reds, the control
#       included. This is the one that says the launches all happen.
#   grid-of-later-launch-copied-from-the-first
#       every launch is given the first one's grid -> `attention` and
#       `swiglu` red, and so do knife 17's four masked-score problems, whose
#       second launch is `attn_softmax` at a grid of ATT_M blocks. `matpow`,
#       `apsp` and `decoupled` launch on one grid throughout, so the mutant
#       is not a change there at all; `lora`'s middle launch IGNORES the
#       second grid axis, so the extra blocks recompute the same tile and
#       store the same bytes. Knife 17 added two more of that last kind:
#       `decay`'s second launch is `attn_context`, which reads only the
#       first grid axis, and `cce`'s second is `cce_mean`, which reads NO
#       block id at all -- sixty-four blocks all compute and store the one
#       answer. A grid mutant is invisible wherever the blocks it adds are
#       idempotent, which is not a fact about this harness but about what a
#       grid means; three of the thirteen sequences here are that case.
#       Knife 18's `mha` is not one of them: its second launch is
#       `attn_softmax` over MHA_H * MHA_N rows, so copying the first launch's
#       2x2x2 grid onto it leaves all but two of those rows unwritten.
#       Knife 20 adds two more of the invisible kind, and both are the FIRST
#       kind rather than the idempotent one: `kv` launches on KV_H blocks
#       three times over (one block a head, and its middle launch is
#       `attn_softmax` over exactly those KV_H rows), and `ols` launches on
#       one block throughout because a Gauss-Jordan step reads the pivot row
#       while it writes every other, so two blocks would race. Neither green
#       is a hole: the mutant copies a grid onto launches that already have
#       it. Its two new reds are `attnbwd` (the first launch is 2x2x1 and the
#       softmax after it wants ATT_M rows) and `linattn` (the first two
#       launches are one block and the third is two).
seq_reds="second-launch-sees-stale-buffer:lora launch-order-swapped:lora last-launch-dropped:lora"
seq_reds="$seq_reds second-launch-sees-stale-buffer:attention launch-order-swapped:attention"
seq_reds="$seq_reds last-launch-dropped:attention grid-of-later-launch-copied-from-the-first:attention"
seq_reds="$seq_reds second-launch-sees-stale-buffer:matpow launch-order-swapped:matpow last-launch-dropped:matpow"
seq_reds="$seq_reds second-launch-sees-stale-buffer:swiglu launch-order-swapped:swiglu"
seq_reds="$seq_reds last-launch-dropped:swiglu grid-of-later-launch-copied-from-the-first:swiglu"
seq_reds="$seq_reds second-launch-sees-stale-buffer:apsp last-launch-dropped:apsp"
for c in causal alibi window sinks; do
  seq_reds="$seq_reds second-launch-sees-stale-buffer:$c launch-order-swapped:$c"
  seq_reds="$seq_reds last-launch-dropped:$c grid-of-later-launch-copied-from-the-first:$c"
done
for c in decay cce; do
  seq_reds="$seq_reds second-launch-sees-stale-buffer:$c launch-order-swapped:$c last-launch-dropped:$c"
done
seq_reds="$seq_reds second-launch-sees-stale-buffer:mha launch-order-swapped:mha"
seq_reds="$seq_reds last-launch-dropped:mha grid-of-later-launch-copied-from-the-first:mha"
for c in xattn gqa grpo; do
  seq_reds="$seq_reds second-launch-sees-stale-buffer:$c launch-order-swapped:$c"
  seq_reds="$seq_reds last-launch-dropped:$c grid-of-later-launch-copied-from-the-first:$c"
done
seq_reds="$seq_reds second-launch-sees-stale-buffer:kmeans launch-order-swapped:kmeans"
seq_reds="$seq_reds last-launch-dropped:kmeans"
seq_reds="$seq_reds second-launch-sees-stale-buffer:kv launch-order-swapped:kv last-launch-dropped:kv"
for c in attnbwd linattn; do
  seq_reds="$seq_reds second-launch-sees-stale-buffer:$c launch-order-swapped:$c"
  seq_reds="$seq_reds last-launch-dropped:$c grid-of-later-launch-copied-from-the-first:$c"
done
seq_reds="$seq_reds second-launch-sees-stale-buffer:ols launch-order-swapped:ols last-launch-dropped:ols"
seq_reds="$seq_reds last-launch-dropped:decoupled"
if [ "$seq_verdict" = pass ]; then
  seq_probe="$(sed -n 's/^probe mutants //p' "$work/seq.out" | tail -n 1)"
  [ "$seq_probe" = "red=72 $seq_reds" ] ||
    { printf 'wanted: red=72 %s\ngot:    %s\n' "$seq_reds" "$seq_probe" >&2
      fail "the sequence mutants' red set moved"; }
  echo "PASS  mutant: the four sequence mutants red on exactly 72 of the 84 (mutant, sequence) pairs, by name"
  seq_controls="$(grep -c '^control intermediate-round-tripped ' "$work/seq.out" || true)"
  seq_controls_moved="$(grep -c '^control intermediate-round-tripped .* verdict differ:result$' "$work/seq.out" || true)"
  if [ "$seq_controls" != 21 ] || [ "$seq_controls_moved" != 0 ]; then
    cat "$work/seq.out" >&2
    fail "the round-trip control moved a verdict: $seq_controls_moved of $seq_controls"
  fi
  echo "PASS  control: sending an intermediate through the host and back changes no sequence's verdict (21 of 21)"
else
  echo "SKIP  mutant: the sequence mutants are not verifiable on this driver: the clean run is $seq_verdict, before any launch reaches the device"
fi

# The measurement the composition's doc comment claims: 7.1.26's absolute
# error is at most 1.5e-7. `erf_sweep` puts the device's erf beside an
# accurate series with nothing multiplied on top, so the number on its
# `error` line IS that error, and this is where the claim is a gate rather
# than a sentence. Held above zero as well: an error of exactly zero would
# mean the reference had become the kernel's own code path.
if [ "$erf_verdict" = pass ]; then
  as_error="$(awk '$1 == "kernel" && $2 == "erf_sweep" {f=1} f && $1 == "error" {print $NF; exit}' "$work/erf.out")"
  python3 -c "
import sys
e = float(sys.argv[1])
if not (0.0 < e <= 1.5e-7):
    print(f'the sweep measured {e:.3e}, outside (0, 1.5e-7]: 7.1.26 does not have the error its doc comment claims')
    sys.exit(1)
print(f'PASS  measured: Abramowitz-Stegun 7.1.26 is out by {e:.3e} on the device, inside its 1.5e-7 bound')
" "$as_error" || fail "the erf composition's measured error is outside the bound it claims ($as_error)"
fi

# The tier summary and the fold-order probe go into the ledger note: the
# probe is a RECORD and not an assertion (docs 6.5), so a tileiras upgrade
# that changes the device's reduction tree shows up in the ledger rather
# than in a red run.
tiers="$(sed -n 's/^tiers //p' "$work/reduced.out" | tail -n 1) 2d:$(sed -n 's/^tiers //p' "$work/twod.out" | tail -n 1)"
tiers="$tiers strided:$(sed -n 's/^tiers //p' "$work/strided.out" | tail -n 1)"
tiers="$tiers int:$(sed -n 's/^tiers //p' "$work/ints.out" | tail -n 1)"
tiers="$tiers wide:$(sed -n 's/^tiers //p' "$work/wide.out" | tail -n 1)"
tiers="$tiers gath:$(sed -n 's/^tiers //p' "$work/gath.out" | tail -n 1)"
tiers="$tiers scan:$(sed -n 's/^tiers //p' "$work/scan.out" | tail -n 1)"
tiers="$tiers atom:$(sed -n 's/^tiers //p' "$work/atom.out" | tail -n 1)"
tiers="$tiers erf:$(sed -n 's/^tiers //p' "$work/erf.out" | tail -n 1)"
tiers="$tiers seq:$(sed -n 's/^tiers //p' "$work/seq.out" | tail -n 1)"
probe="$(sed -n 's/^probe fold-order //p' "$work/reduced.out" | tail -n 1)"
scan_probe="$(awk '/^  order /{sub(/^  order /, ""); print; exit}' "$work/scan.out")"
erf_probe="$(sed -n 's/^probe as-error //p' "$work/erf.out" | tail -n 1)"
seq_launch_probe="$(sed -n 's/^probe launches //p' "$work/seq.out" | tail -n 1)"
echo "      tiers: $tiers; fold-order probe: $probe; scan order: $scan_probe; erf error: $erf_probe;"\
  " sequence launches: $seq_launch_probe"

# The ledger records one verdict for the tree: both programs pass, or the
# first thing that stopped one of them.
if [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ] && [ "$strided_verdict" = pass ] && [ "$int_verdict" = pass ] \
  && [ "$wide_verdict" = pass ] && [ "$gath_verdict" = pass ] && [ "$scan_verdict" = pass ] \
  && [ "$atom_verdict" = pass ]; then
  verdict=pass
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ] && [ "$strided_verdict" = pass ] && [ "$int_verdict" = pass ] \
  && [ "$wide_verdict" = pass ] && [ "$gath_verdict" = pass ] && [ "$scan_verdict" = pass ]; then
  verdict="$atom_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ] && [ "$strided_verdict" = pass ] && [ "$int_verdict" = pass ] \
  && [ "$wide_verdict" = pass ] && [ "$gath_verdict" = pass ]; then
  verdict="$scan_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ] && [ "$strided_verdict" = pass ] && [ "$int_verdict" = pass ] \
  && [ "$wide_verdict" = pass ]; then
  verdict="$gath_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ] && [ "$strided_verdict" = pass ] && [ "$int_verdict" = pass ]; then
  verdict="$wide_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ] && [ "$strided_verdict" = pass ]; then
  verdict="$int_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ] \
  && [ "$twod_verdict" = pass ]; then
  verdict="$strided_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ] && [ "$reduced_verdict" = pass ]; then
  verdict="$twod_verdict"
elif [ "$verdict" = pass ] && [ "$masked_verdict" = pass ]; then
  verdict="$reduced_verdict"
elif [ "$verdict" = pass ]; then
  verdict="$masked_verdict"
fi

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
  '                  gpu_launch_host(m, kernel, gx, gy, gz, device_pointers(table, args))' \
  '                  gpu_launch_host(m, kernel, 0, gy, gz, device_pointers(table, args))')"
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

# 4. mask-all-true: the package's lowering answers an all-true `i1` constant
#    where it should answer the comparison, so every kernel still carries a
#    mask operand and every lane of it is 1. The text and the bytes move (a
#    `--record` would take them), `tileiras` accepts them (an all-true mask
#    is a mask), and on the device the last block reads and writes the lanes
#    past the end of the vector: the sentinel in the output buffer's tail is
#    overwritten and every one of the six kernels differs from the fake
#    device. This is the claim only layer 2 can make, and the reason knife 7a
#    is a boundary knife and not an arithmetic one.
mutant_pkg="$work/pkg-mask-all-true"
rm -rf "$mutant_pkg"
cp -r "$root/packages/tileir" "$mutant_pkg"
before=$(digest "$mutant_pkg/src/lower.dawn")
python3 "$here/mutate.py" "$mutant_pkg/src/lower.dawn" mask-all-true \
  'emit(l1, CmpInt(d, pred, i32_tile(shape), i1_tile(shape), a, b))' \
  'emit(l1, ConstInt(d, i1_tile(shape), 1))'
after=$(digest "$mutant_pkg/src/lower.dawn")
echo "      mask-all-true: packages/tileir/src/lower.dawn md5 $before -> $after"

mkdir -p "$work/mk/src"
cp "$golden/kernels.dawn" "$work/mk/src/main.dawn"
cat > "$work/mk/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$mutant_pkg"
TOML
mutant_cubins=()
for k in "${masked[@]}"; do
  "$root/bin/dawn" run "$work/mk" -- "$k" --bytecode "$work/m-$k.tilebc" > "$work/mk.$k.log" 2>&1 ||
    { cat "$work/mk.$k.log" >&2; fail "mask-all-true: $k did not encode"; }
  cmp -s "$golden/$k.tilebc" "$work/m-$k.tilebc" &&
    fail "mask-all-true mutant stayed green: $k.tilebc is unchanged"
  assemble_golden "$k" "$work/m-$k.tilebc" "$work/m-$k.cubin"
  mutant_cubins+=("$work/m-$k.cubin")
done
echo "      mask-all-true: the six .tilebc files differ from the goldens and tileiras still accepts them"
rc=0
"$work/masked.bin" "${mutant_cubins[@]}" > "$work/m-mask-all-true.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-mask-all-true.out")"
if [ "$masked_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-mask-all-true.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#masked[@]}" ]; then
    cat "$work/m-mask-all-true.out" >&2
    fail "mask-all-true mutant stayed green: expected verdict fail (exit 1) with all ${#masked[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  echo "PASS  mutant: mask-all-true (all ${#masked[@]} kernels write past the end of the vector; verdict fail, exit 1)"
else
  [ "$mverdict" = "$masked_verdict" ] ||
    { cat "$work/m-mask-all-true.out" >&2; fail "mask-all-true: the clean run is $masked_verdict but the mutant is $mverdict; a mutant the driver never runs should be indistinguishable"; }
  echo "SKIP  mutant: mask-all-true not verifiable on this driver: the clean run is $masked_verdict, before any launch reaches the device"
fi

# 5. reduce-identity-wrong: `d_reduce` hands the reduction an identity one
#    greater than the one it was given. A sum's identity becomes 1.0 instead
#    of 0.0; a maximum's stays -inf, since -inf + 1 is -inf, so the mutant
#    lands on the sums alone. Layer 0 MOVES (the text prints
#    `identities=[1.0 : f64]`, and a `--record` would take it), layer 1
#    ACCEPTS it -- tileiras checks the identity's format against the
#    operand's and never its value, measured -- and only the device says the
#    answer is wrong. This is the claim of knife 7b, and the reason a
#    reduction knife needs a device.
#
#    Nine of the fourteen kernels hold a sum reduction, and SIX of those
#    nine go red. `reduce_sum`, `monte_carlo` and knife 19's `agent_step`
#    do not, and that is a measurement rather than an oversight: with a
#    wrong identity they still answer exactly what the clean kernels
#    answer, so on this assembler their reduction never folds the identity
#    in at all.
#
#    Knife 18's reading of this table was that the six that move are the
#    six whose reduction operand is a COMPUTED tile and the two that do not
#    are the two that reduce the loaded tile itself. `agent_step` REFUTES
#    that: all three of its sums fold a `select`, which is as computed as a
#    product, and it is green. What still separates it from the six is the
#    tile's WIDTH -- every red reduces 1024 lanes and its reductions are 64
#    -- and that is an observation and not a mechanism. So the gate names
#    the six and nothing else does; the standing claim is only that a
#    semantically wrong identity is invisible on some kernels even at layer
#    2, which is worth knowing before anyone reads "layer 2 catches it" as
#    "layer 2 catches it everywhere".
#
#    So the gate names the six, and requires the other seven to be
#    untouched. A tileiras upgrade that changes which kernels fold the
#    identity in will red this line, and that is the point: the evidence
#    would have moved.
mutant_pkg_id="$work/pkg-reduce-identity-wrong"
rm -rf "$mutant_pkg_id"
cp -r "$root/packages/tileir" "$mutant_pkg_id"
before=$(digest "$mutant_pkg_id/src/dev.dawn")
python3 "$here/mutate.py" "$mutant_pkg_id/src/dev.dawn" reduce-identity-wrong \
  'let args = t_reduce_begin(0, shape, [IdF(dtype_name(d), identity)], [h])' \
  'let args = t_reduce_begin(0, shape, [IdF(dtype_name(d), identity + 1.0)], [h])'
after=$(digest "$mutant_pkg_id/src/dev.dawn")
echo "      reduce-identity-wrong: packages/tileir/src/dev.dawn md5 $before -> $after"

# The kernels of a mutated package, encoded and assembled into $work/<tag>-<k>.cubin.
mutant_kernels() { # tag, pkgdir, kernels...
  local tag="$1" pkg="$2"
  shift 2
  mkdir -p "$work/proj-$tag/src"
  cp "$golden/kernels.dawn" "$work/proj-$tag/src/main.dawn"
  cat > "$work/proj-$tag/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$pkg"
TOML
  local k
  for k in "$@"; do
    "$root/bin/dawn" run "$work/proj-$tag" -- "$k" --bytecode "$work/$tag-$k.tilebc" > "$work/proj-$tag.$k.log" 2>&1 ||
      { cat "$work/proj-$tag.$k.log" >&2; fail "$tag: $k did not encode"; }
    assemble_golden "$k" "$work/$tag-$k.tilebc" "$work/$tag-$k.cubin"
  done
}

mutant_kernels reduce-identity-wrong "$mutant_pkg_id" "${reduced[@]}"
# the eight kernels with a sum reduction move at layer 0; the five without
# one do not, and that is the mutant's own control
moved=0
for k in "${reduced[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/reduce-identity-wrong-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = 9 ] ||
  fail "reduce-identity-wrong: expected exactly 9 of the ${#reduced[@]} kernels' bytecode to move, got $moved"
echo "      reduce-identity-wrong: 9 of ${#reduced[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
id_cubins=()
for k in "${reduced[@]}"; do id_cubins+=("$work/reduce-identity-wrong-$k.cubin"); done
rc=0
"$work/reduced.bin" "${id_cubins[@]}" > "$work/m-reduce-identity-wrong.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-reduce-identity-wrong.out")"
identity_red=(softmax dot mse rms_norm ppo_loss dpo_loss)
identity_green=(reduce_sum monte_carlo silu sigmoid mathops foldif argmax agent_step)
if [ "$reduced_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-reduce-identity-wrong.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#identity_red[@]}" ]; then
    cat "$work/m-reduce-identity-wrong.out" >&2
    fail "reduce-identity-wrong mutant stayed green: expected verdict fail (exit 1) with exactly ${#identity_red[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${identity_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-reduce-identity-wrong.out" ||
      { cat "$work/m-reduce-identity-wrong.out" >&2; fail "reduce-identity-wrong: $k reduces a computed tile and should differ"; }
  done
  for k in "${identity_green[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-reduce-identity-wrong.out" ||
      { cat "$work/m-reduce-identity-wrong.out" >&2; fail "reduce-identity-wrong: $k should be untouched"; }
  done
  echo "PASS  mutant: reduce-identity-wrong (layer 1 accepts it; on the device ${identity_red[*]} differ and the other ${#identity_green[@]} do not)"
else
  [ "$mverdict" = "$reduced_verdict" ] ||
    { cat "$work/m-reduce-identity-wrong.out" >&2; fail "reduce-identity-wrong: the clean run is $reduced_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: reduce-identity-wrong not verifiable on this driver: the clean run is $reduced_verdict, before any launch reaches the device"
fi

# 6. softmax-no-max-subtract: the softmax kernel stops subtracting the
#    maximum before exponentiating. Every layer below the device is happy --
#    the text and the bytes are a legal, shorter kernel and tileiras
#    assembles it -- and it is even numerically identical on a corpus of
#    small values. On red_diff's corpus, which is around 1000, the device
#    computes exp(1000), overflows to +inf, divides inf by inf and answers
#    NaN, while the reference (which subtracts) is finite. The corpus is
#    part of the claim, which is why it lives beside the kernel.
mutant_kernels_src="$work/kernels-softmax.dawn"
cp "$golden/kernels.dawn" "$mutant_kernels_src"
before=$(digest "$mutant_kernels_src")
python3 "$here/mutate.py" "$mutant_kernels_src" softmax-no-max-subtract \
  '  let mx = spread(F64, [RED_TILE], d_reduce(F64, [RED_TILE], t, neg_inf(), (acc, e) => s_maxf(F64, acc, e)))' \
  '  let mx = f_const(F64, [RED_TILE], 0.0)'
after=$(digest "$mutant_kernels_src")
echo "      softmax-no-max-subtract: scripts/tile-golden/kernels.dawn md5 $before -> $after"
mkdir -p "$work/proj-softmax/src"
cp "$mutant_kernels_src" "$work/proj-softmax/src/main.dawn"
cat > "$work/proj-softmax/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
"$root/bin/dawn" run "$work/proj-softmax" -- softmax --bytecode "$work/softmax-nomax.tilebc" > "$work/proj-softmax.log" 2>&1 ||
  { cat "$work/proj-softmax.log" >&2; fail "softmax-no-max-subtract: softmax did not encode"; }
cmp -s "$golden/softmax.tilebc" "$work/softmax-nomax.tilebc" &&
  fail "softmax-no-max-subtract mutant stayed green: softmax.tilebc is unchanged"
assemble_golden softmax "$work/softmax-nomax.tilebc" "$work/softmax-nomax.cubin"
echo "      softmax-no-max-subtract: softmax.tilebc differs from the golden and tileiras still accepts it"
nomax_cubins=()
for k in "${reduced[@]}"; do
  if [ "$k" = softmax ]; then nomax_cubins+=("$work/softmax-nomax.cubin"); else nomax_cubins+=("$work/$k.cubin"); fi
done
rc=0
"$work/reduced.bin" "${nomax_cubins[@]}" > "$work/m-softmax-no-max.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-softmax-no-max.out")"
if [ "$reduced_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-softmax-no-max.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
    cat "$work/m-softmax-no-max.out" >&2
    fail "softmax-no-max-subtract mutant stayed green: expected verdict fail (exit 1) with softmax alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  awk '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != "softmax" {bad=1} END {exit bad}' \
    "$work/m-softmax-no-max.out" ||
    { cat "$work/m-softmax-no-max.out" >&2; fail "softmax-no-max-subtract: a kernel other than softmax moved"; }
  grep -q 'kernel softmax' "$work/m-softmax-no-max.out" ||
    fail "softmax-no-max-subtract: softmax is not in the transcript"
  echo "PASS  mutant: softmax-no-max-subtract (softmax alone overflows to NaN on a corpus around 1000; the other 12 kernels are untouched)"
else
  [ "$mverdict" = "$reduced_verdict" ] ||
    { cat "$work/m-softmax-no-max.out" >&2; fail "softmax-no-max-subtract: the clean run is $reduced_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: softmax-no-max-subtract not verifiable on this driver: the clean run is $reduced_verdict, before any launch reaches the device"
fi

# 7. grid-y-ignored: the C RUNTIME launches with gridDimY forced to 1. This
#    is the first mutant here below the Dawn source entirely: layer 0 and
#    layer 1 cannot see it (a grid is not in the bytecode, and `tileiras`
#    never launches anything), and the earlier layer-2 programs cannot
#    either, because every kernel before this knife runs on a
#    one-dimensional grid where gridDimY is already 1. Only the four
#    kernels here whose grid has a second axis go red, and they go red by
#    leaving the sentinel where the blocks that were never launched should
#    have written.
mutant_rt="$work/rt-grid-y-ignored"
rm -rf "$mutant_rt"
cp -r "$root/runtime/c" "$mutant_rt"
before=$(digest "$mutant_rt/dawn_rt.c")
python3 "$here/mutate.py" "$mutant_rt/dawn_rt.c" grid-y-ignored \
  '  r = dawn_gpu.launch_kernel(fn, (unsigned int)gx, (unsigned int)gy, (unsigned int)gz, 1, 1, 1, 0,' \
  '  r = dawn_gpu.launch_kernel(fn, (unsigned int)gx, 1, (unsigned int)gz, 1, 1, 1, 0,'
after=$(digest "$mutant_rt/dawn_rt.c")
echo "      grid-y-ignored: runtime/c/dawn_rt.c md5 $before -> $after"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$mutant_rt" -c -o "$work/m-grid-y.o" "$mutant_rt/dawn_rt.c" ||
  fail "grid-y-ignored: the mutated C runtime does not compile"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$mutant_rt" -o "$work/m-grid-y.bin" "$work/twod.bin.c" "$work/m-grid-y.o" -lm ||
  fail "grid-y-ignored: mm_diff does not link against the mutated runtime"
rc=0
"$work/m-grid-y.bin" "${twod_cubins[@]}" > "$work/m-grid-y.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-grid-y.out")"
# the four kernels whose grid has a second axis, and the three that do not
gridy_red=(matmul batched_matmul transpose group_norm)
gridy_green=(layer_norm batch_norm fused_rms_norm matvec)
if [ "$twod_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-grid-y.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#gridy_red[@]}" ]; then
    cat "$work/m-grid-y.out" >&2
    fail "grid-y-ignored mutant stayed green: expected verdict fail (exit 1) with exactly ${#gridy_red[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${gridy_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-grid-y.out" ||
      { cat "$work/m-grid-y.out" >&2; fail "grid-y-ignored: $k has a second grid axis and should differ"; }
  done
  for k in "${gridy_green[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-grid-y.out" ||
      { cat "$work/m-grid-y.out" >&2; fail "grid-y-ignored: $k has a one-dimensional grid and should be untouched"; }
  done
  echo "PASS  mutant: grid-y-ignored (only the ${#gridy_red[@]} kernels with a second grid axis differ: ${gridy_red[*]})"
else
  [ "$mverdict" = "$twod_verdict" ] ||
    { cat "$work/m-grid-y.out" >&2; fail "grid-y-ignored: the clean run is $twod_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: grid-y-ignored not verifiable on this driver: the clean run is $twod_verdict, before any launch reaches the device"
fi

# 8. mma-acc-not-carried: the GEMM's K loop stops carrying its accumulator
#    and starts each iteration from a fresh zero tile, so the answer is the
#    LAST 32-wide slice of the product instead of the whole sum. Layer 0
#    moves (a `--record` would take it), layer 1 accepts it -- it is a
#    legal, equally well typed kernel -- and only the device says the
#    matrix product is wrong. `matmul` alone is edited, so the other six
#    kernels are the mutant's own control.
mutant_mma_src="$work/kernels-mma.dawn"
cp "$golden/kernels.dawn" "$mutant_mma_src"
before=$(digest "$mutant_mma_src")
python3 "$here/mutate.py" "$mutant_mma_src" mma-acc-not-carried \
  '    mmaf(F64, MM_TM, MM_TK, MM_TN, ta, tb, sofar)' \
  '    mmaf(F64, MM_TM, MM_TK, MM_TN, ta, tb, f_const(F64, [MM_TM, MM_TN], 0.0))'
after=$(digest "$mutant_mma_src")
echo "      mma-acc-not-carried: scripts/tile-golden/kernels.dawn md5 $before -> $after"
mkdir -p "$work/proj-mma/src"
cp "$mutant_mma_src" "$work/proj-mma/src/main.dawn"
cat > "$work/proj-mma/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
"$root/bin/dawn" run "$work/proj-mma" -- matmul --bytecode "$work/matmul-noacc.tilebc" > "$work/proj-mma.log" 2>&1 ||
  { cat "$work/proj-mma.log" >&2; fail "mma-acc-not-carried: matmul did not encode"; }
cmp -s "$golden/matmul.tilebc" "$work/matmul-noacc.tilebc" &&
  fail "mma-acc-not-carried mutant stayed green: matmul.tilebc is unchanged"
assemble_golden matmul "$work/matmul-noacc.tilebc" "$work/matmul-noacc.cubin"
echo "      mma-acc-not-carried: matmul.tilebc differs from the golden and tileiras still accepts it"
noacc_cubins=()
for k in "${twod[@]}"; do
  if [ "$k" = matmul ]; then noacc_cubins+=("$work/matmul-noacc.cubin"); else noacc_cubins+=("$work/$k.cubin"); fi
done
rc=0
"$work/twod.bin" "${noacc_cubins[@]}" > "$work/m-mma-noacc.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-mma-noacc.out")"
if [ "$twod_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-mma-noacc.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
    cat "$work/m-mma-noacc.out" >&2
    fail "mma-acc-not-carried mutant stayed green: expected verdict fail (exit 1) with matmul alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  awk '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != "matmul" {bad=1} END {exit bad}' \
    "$work/m-mma-noacc.out" ||
    { cat "$work/m-mma-noacc.out" >&2; fail "mma-acc-not-carried: a kernel other than matmul moved"; }
  echo "PASS  mutant: mma-acc-not-carried (matmul alone answers the last K slice instead of the sum; the other 6 kernels are untouched)"
else
  [ "$mverdict" = "$twod_verdict" ] ||
    { cat "$work/m-mma-noacc.out" >&2; fail "mma-acc-not-carried: the clean run is $twod_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: mma-acc-not-carried not verifiable on this driver: the clean run is $twod_verdict, before any launch reaches the device"
fi

# 9. stride-row-major-swapped: the transpose kernel writes its tile with
#    the two stride dimensions of the OUTPUT layout swapped -- it takes
#    `row_major([rows, cols])` where the output is `cols` by `rows`, so the
#    store's column stride is 60 instead of 100. Layer 0 moves (one
#    constant) and layer 1 accepts it -- a stride is a stride -- so only the
#    device says the values land in the wrong place.
#
#    A SQUARE matrix would not catch this at all: with rows == cols the two
#    expressions are the same list and the mutant is not even a change to
#    the bytes. That is why stride_diff's matrix is 100 by 60, and it is
#    written down beside the corpus (`distinct`, stride_diff.dawn) as well
#    as here.
mutant_ts_src="$work/kernels-transpose.dawn"
cp "$golden/kernels.dawn" "$mutant_ts_src"
before=$(digest "$mutant_ts_src")
python3 "$here/mutate.py" "$mutant_ts_src" stride-row-major-swapped \
  '  store_strided_masked(out, base_out, shape, permute(row_major([TT_COLS, TT_ROWS]), [1, 0]), m, t)' \
  '  store_strided_masked(out, base_out, shape, permute(row_major([TT_ROWS, TT_COLS]), [1, 0]), m, t)'
after=$(digest "$mutant_ts_src")
echo "      stride-row-major-swapped: scripts/tile-golden/kernels.dawn md5 $before -> $after"
mkdir -p "$work/proj-transpose/src"
cp "$mutant_ts_src" "$work/proj-transpose/src/main.dawn"
cat > "$work/proj-transpose/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
"$root/bin/dawn" run "$work/proj-transpose" -- transpose_tail --bytecode "$work/tt-swapped.tilebc" \
  > "$work/proj-transpose.log" 2>&1 ||
  { cat "$work/proj-transpose.log" >&2; fail "stride-row-major-swapped: transpose_tail did not encode"; }
cmp -s "$golden/transpose_tail.tilebc" "$work/tt-swapped.tilebc" &&
  fail "stride-row-major-swapped mutant stayed green: transpose_tail.tilebc is unchanged (is the matrix square again?)"
assemble_golden transpose_tail "$work/tt-swapped.tilebc" "$work/tt-swapped.cubin"
echo "      stride-row-major-swapped: transpose_tail.tilebc differs from the golden and tileiras still accepts it"
swap_cubins=()
for k in "${strided[@]}"; do
  if [ "$k" = transpose_tail ]; then swap_cubins+=("$work/tt-swapped.cubin"); else swap_cubins+=("$work/$k.cubin"); fi
done
rc=0
"$work/strided.bin" "${swap_cubins[@]}" > "$work/m-stride-swapped.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-stride-swapped.out")"
if [ "$strided_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-stride-swapped.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
    cat "$work/m-stride-swapped.out" >&2
    fail "stride-row-major-swapped mutant stayed green: expected verdict fail (exit 1) with transpose_tail alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  awk '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != "transpose_tail" {bad=1} END {exit bad}' \
    "$work/m-stride-swapped.out" ||
    { cat "$work/m-stride-swapped.out" >&2; fail "stride-row-major-swapped: a kernel other than transpose_tail moved"; }
  echo "PASS  mutant: stride-row-major-swapped (transpose_tail alone, and only because the matrix is rectangular)"
else
  [ "$mverdict" = "$strided_verdict" ] ||
    { cat "$work/m-stride-swapped.out" >&2; fail "stride-row-major-swapped: the clean run is $strided_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: stride-row-major-swapped not verifiable on this driver: the clean run is $strided_verdict, before any launch reaches the device"
fi

# 9b. ladder-strides-reversed: the LOWERING takes each dimension's stride
#     from the opposite dimension, so every rank-2 layout in a kernel is
#     swapped at once. Six of the nine kernels' bytecode moves and tileiras
#     accepts every one of them.
#
#     On the device only ONE of the seven goes red, and the reason is worth
#     the line: reversing EVERY layout in a kernel is a relabelling of the
#     tile's own two axes, and a relabelling cancels when the TILE is
#     square. transpose_tail reads a 32 by 32 tile transposed and writes it
#     transposed, and the two swaps compose back to the transpose; the same
#     holds for conv2d, max_pool, jacobi and gaussian_blur, masks included,
#     because each of their masks is built from the same reversed ladder.
#     depthwise_conv1d's tile is 4 by 32, so there is no relabelling to
#     hide behind and it answers the wrong channel.
#
#     Knife 18's conv3d was expected to be the second and MEASURED GREEN,
#     which sharpens "masks included" into something worth writing down.
#     Its tile is square (16 by 16) and its two `axis_mask` limits are NOT
#     equal (10 output rows against 14 output columns), so the guess was
#     that the mask would break the symmetry the tile has. It does not: a
#     mask limit is attached to an AXIS, and `axis_mask` reaches that axis
#     through the same `axis_strides` ladder the loads use, so the mutant
#     swaps which axis each limit applies to along with everything else.
#     The relabelling is total or it is nothing. What defeats it is an
#     unequal tile, and only that.
#
#     So this mutant is not the strong one it looks like, and that is the
#     point of recording it: a stride swap in the lowering is INVISIBLE on
#     square tiles, whatever the masks over them say. The kernel-level swap
#     above is the one that carries the claim.
mutant_pkg_st="$work/pkg-ladder-strides-reversed"
rm -rf "$mutant_pkg_st"
cp -r "$root/packages/tileir" "$mutant_pkg_st"
before=$(digest "$mutant_pkg_st/src/lower.dawn")
python3 "$here/mutate.py" "$mutant_pkg_st/src/lower.dawn" ladder-strides-reversed \
  '        let (le, term) = if strides[k] == 1 {' \
  '        let (le, term) = if strides[len(shape) - 1 - k] == 1 {'
python3 "$here/mutate.py" "$mutant_pkg_st/src/lower.dawn" ladder-strides-reversed \
  '          let ly = emit(lx, ConstInt(c, full, strides[k]))' \
  '          let ly = emit(lx, ConstInt(c, full, strides[len(shape) - 1 - k]))'
after=$(digest "$mutant_pkg_st/src/lower.dawn")
echo "      ladder-strides-reversed: packages/tileir/src/lower.dawn md5 $before -> $after"

mutant_kernels ladder-strides-reversed "$mutant_pkg_st" "${strided[@]}"
# the seven kernels with a rank-2 layout move at layer 0; the three rank-1
# ladders cannot, and that is the mutant's own control at layer 0
moved=0
for k in "${strided[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/ladder-strides-reversed-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = 7 ] ||
  fail "ladder-strides-reversed: expected exactly 7 of the ${#strided[@]} kernels' bytecode to move, got $moved"
echo "      ladder-strides-reversed: 7 of ${#strided[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
rev_cubins=()
for k in "${strided[@]}"; do rev_cubins+=("$work/ladder-strides-reversed-$k.cubin"); done
rc=0
"$work/strided.bin" "${rev_cubins[@]}" > "$work/m-ladder-reversed.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-ladder-reversed.out")"
ladder_red=(depthwise_conv1d)
if [ "$strided_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-ladder-reversed.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#ladder_red[@]}" ]; then
    cat "$work/m-ladder-reversed.out" >&2
    fail "ladder-strides-reversed mutant stayed green: expected verdict fail (exit 1) with exactly ${#ladder_red[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${ladder_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-ladder-reversed.out" ||
      { cat "$work/m-ladder-reversed.out" >&2; fail "ladder-strides-reversed: $k should differ"; }
  done
  awk 'BEGIN{split("depthwise_conv1d", r, " "); for (i in r) red[r[i]]=1}
       /^kernel /{cur=$2} /^  verdict differ:result$/ && !(cur in red) {bad=1} END {exit bad}' \
    "$work/m-ladder-reversed.out" ||
    { cat "$work/m-ladder-reversed.out" >&2; fail "ladder-strides-reversed: a kernel outside the red set moved; a square tile should have hidden it, masks and all"; }
  echo "PASS  mutant: ladder-strides-reversed (seven kernels' bytes move, and only ${ladder_red[*]}'s 4 by 32 tile can see it on the device)"
else
  [ "$mverdict" = "$strided_verdict" ] ||
    { cat "$work/m-ladder-reversed.out" >&2; fail "ladder-strides-reversed: the clean run is $strided_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: ladder-strides-reversed not verifiable on this driver: the clean run is $strided_verdict, before any launch reaches the device"
fi

# 10. halo-one-lane-short: the gaussian blur's tap bound stops one lane
#     early, so the last row (or column) of the image counts as padding for
#     the tap that reaches past it and its contribution is dropped. Layer 0
#     moves (one constant in a mask) and layer 1 accepts it -- an off-by-one
#     mask is a mask -- and only the device says the image is wrong along
#     two of its four edges. `gaussian_blur` is the only kernel here with a
#     halo, so the other eight are the control.
#
#     A boundary claim needs a shape with a boundary INSIDE the tile: the
#     image is 20 by 24 in 16 by 16 tiles, so the edge the mutant drops is
#     not the tile's edge and the per-axis masks are already doing work
#     there.
mutant_blur_src="$work/kernels-blur.dawn"
cp "$golden/kernels.dawn" "$mutant_blur_src"
before=$(digest "$mutant_blur_src")
python3 "$here/mutate.py" "$mutant_blur_src" halo-one-lane-short \
  'fn gb_hi(n: Int, t: Int) -> Int = if t > gb_half() { n - (t - gb_half()) } else { n }' \
  'fn gb_hi(n: Int, t: Int) -> Int = if t > gb_half() { n - (t - gb_half()) - 1 } else { n }'
after=$(digest "$mutant_blur_src")
echo "      halo-one-lane-short: scripts/tile-golden/kernels.dawn md5 $before -> $after"
mkdir -p "$work/proj-blur/src"
cp "$mutant_blur_src" "$work/proj-blur/src/main.dawn"
cat > "$work/proj-blur/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
"$root/bin/dawn" run "$work/proj-blur" -- gaussian_blur --bytecode "$work/blur-short.tilebc" > "$work/proj-blur.log" 2>&1 ||
  { cat "$work/proj-blur.log" >&2; fail "halo-one-lane-short: gaussian_blur did not encode"; }
cmp -s "$golden/gaussian_blur.tilebc" "$work/blur-short.tilebc" &&
  fail "halo-one-lane-short mutant stayed green: gaussian_blur.tilebc is unchanged"
assemble_golden gaussian_blur "$work/blur-short.tilebc" "$work/blur-short.cubin"
echo "      halo-one-lane-short: gaussian_blur.tilebc differs from the golden and tileiras still accepts it"
short_cubins=()
for k in "${strided[@]}"; do
  if [ "$k" = gaussian_blur ]; then short_cubins+=("$work/blur-short.cubin"); else short_cubins+=("$work/$k.cubin"); fi
done
rc=0
"$work/strided.bin" "${short_cubins[@]}" > "$work/m-halo-short.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-halo-short.out")"
if [ "$strided_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-halo-short.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
    cat "$work/m-halo-short.out" >&2
    fail "halo-one-lane-short mutant stayed green: expected verdict fail (exit 1) with gaussian_blur alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  awk '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != "gaussian_blur" {bad=1} END {exit bad}' \
    "$work/m-halo-short.out" ||
    { cat "$work/m-halo-short.out" >&2; fail "halo-one-lane-short: a kernel other than gaussian_blur moved"; }
  echo "PASS  mutant: halo-one-lane-short (gaussian_blur alone drops the far edge of every tap; the other 8 kernels are untouched)"
else
  [ "$mverdict" = "$strided_verdict" ] ||
    { cat "$work/m-halo-short.out" >&2; fail "halo-one-lane-short: the clean run is $strided_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: halo-one-lane-short not verifiable on this driver: the clean run is $strided_verdict, before any launch reaches the device"
fi

# 11. shri-always-logical: the WRITER gives `shri` the unsigned signedness,
#     so every arithmetic right shift in the package becomes a logical one.
#
#     This is the first mutant here that layer 0 cannot see AT ALL: the
#     renderer keeps its own spelling table, so every .mlir still prints
#     `signed` and a `--record` would take nothing. Layer 1 accepts it --
#     `signedness<unsigned>` is as legal as `signedness<signed>` and
#     tileiras has no opinion on which a kernel meant. Only the device
#     answers, and only where an operand is NEGATIVE: the two shifts agree
#     on every non-negative value, so int_diff's corpus spanning the whole
#     i32 range is half of this claim and the mutant would be invisible
#     without it.
#
#     Two of the six kernels shift right arithmetically and go red;
#     count_eq and the three subarray sums shift nothing and are the
#     control, at layer 0 (their bytes do not move) and on the device
#     both.
mutant_pkg_shr="$work/pkg-shri-always-logical"
rm -rf "$mutant_pkg_shr"
cp -r "$root/packages/tileir" "$mutant_pkg_shr"
before=$(digest "$mutant_pkg_shr/src/bytecode.dawn")
python3 "$here/mutate.py" "$mutant_pkg_shr/src/bytecode.dawn" shri-always-logical \
  '  "shri" -> [SIGNED]' \
  '  "shri" -> [UNSIGNED]'
after=$(digest "$mutant_pkg_shr/src/bytecode.dawn")
echo "      shri-always-logical: packages/tileir/src/bytecode.dawn md5 $before -> $after"

mutant_kernels shri-always-logical "$mutant_pkg_shr" "${integers[@]}"
# the two kernels with an arithmetic right shift move at layer 0; the two
# without one cannot, and that is the mutant's own control in the bytes
shri_red=(rainbow int_ops)
moved=0
for k in "${integers[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/shri-always-logical-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = "${#shri_red[@]}" ] ||
  fail "shri-always-logical: expected exactly ${#shri_red[@]} of the ${#integers[@]} kernels' bytecode to move, got $moved"
echo "      shri-always-logical: ${#shri_red[@]} of ${#integers[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
shri_cubins=()
for k in "${integers[@]}"; do shri_cubins+=("$work/shri-always-logical-$k.cubin"); done
rc=0
"$work/ints.bin" "${shri_cubins[@]}" > "$work/m-shri-logical.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-shri-logical.out")"
if [ "$int_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-shri-logical.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#shri_red[@]}" ]; then
    cat "$work/m-shri-logical.out" >&2
    fail "shri-always-logical mutant stayed green: expected verdict fail (exit 1) with exactly ${#shri_red[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${shri_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-shri-logical.out" ||
      { cat "$work/m-shri-logical.out" >&2; fail "shri-always-logical: $k shifts right arithmetically over negative lanes and should differ"; }
  done
  for k in count_eq subarray_sum subarray_sum2d subarray_sum3d; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-shri-logical.out" ||
      { cat "$work/m-shri-logical.out" >&2; fail "shri-always-logical: $k shifts nothing and should be untouched"; }
  done
  echo "PASS  mutant: shri-always-logical (layer 0 blind, layer 1 accepts; on the device ${shri_red[*]} differ and the other four do not)"
else
  [ "$mverdict" = "$int_verdict" ] ||
    { cat "$work/m-shri-logical.out" >&2; fail "shri-always-logical: the clean run is $int_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: shri-always-logical not verifiable on this driver: the clean run is $int_verdict, before any launch reaches the device"
fi

# 12. exti-sign-extends: the writer gives `exti` the signed signedness where
#     it widens a comparison mask, so each selected lane becomes -1 instead
#     of 1. Layer 0 is blind (the renderer prints `unsigned` from its own
#     table) and layer 1 accepts it -- a signed widening is a legal
#     operation, just not this one's -- so the device is again the only
#     place the difference exists: `count_eq` answers the negated count and
#     `int_ops`'s parity term flips sign on every odd lane. The three
#     subarray sums and `rainbow` widen no mask and are the control, at
#     layer 0 (their bytes do not move) and on the device both.
#
#     The conversion mutant the coverage memo named first,
#     ftoi-rounds-instead-of-truncates, is a LAYER 1 mutant rather than a
#     layer 2 one: `nearest_int_to_zero` is the only integer rounding mode
#     `ftoi` accepts and tileiras refuses any other, so it is registered in
#     scripts/tile-golden/run.sh with the other writer mutants. Measured
#     while writing this one.
mutant_pkg_exti="$work/pkg-exti-sign-extends"
rm -rf "$mutant_pkg_exti"
cp -r "$root/packages/tileir" "$mutant_pkg_exti"
before=$(digest "$mutant_pkg_exti/src/bytecode.dawn")
python3 "$here/mutate.py" "$mutant_pkg_exti/src/bytecode.dawn" exti-sign-extends \
  '  "exti" -> [UNSIGNED]' \
  '  "exti" -> [SIGNED]'
after=$(digest "$mutant_pkg_exti/src/bytecode.dawn")
echo "      exti-sign-extends: packages/tileir/src/bytecode.dawn md5 $before -> $after"

mutant_kernels exti-sign-extends "$mutant_pkg_exti" "${integers[@]}"
exti_red=(count_eq int_ops)
moved=0
for k in "${integers[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/exti-sign-extends-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = "${#exti_red[@]}" ] ||
  fail "exti-sign-extends: expected exactly ${#exti_red[@]} of the ${#integers[@]} kernels' bytecode to move, got $moved"
echo "      exti-sign-extends: ${#exti_red[@]} of ${#integers[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
exti_cubins=()
for k in "${integers[@]}"; do exti_cubins+=("$work/exti-sign-extends-$k.cubin"); done
rc=0
"$work/ints.bin" "${exti_cubins[@]}" > "$work/m-exti-signed.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-exti-signed.out")"
if [ "$int_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-exti-signed.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#exti_red[@]}" ]; then
    cat "$work/m-exti-signed.out" >&2
    fail "exti-sign-extends mutant stayed green: expected verdict fail (exit 1) with exactly ${#exti_red[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${exti_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-exti-signed.out" ||
      { cat "$work/m-exti-signed.out" >&2; fail "exti-sign-extends: $k widens a mask and should differ"; }
  done
  for k in subarray_sum subarray_sum2d subarray_sum3d rainbow; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-exti-signed.out" ||
      { cat "$work/m-exti-signed.out" >&2; fail "exti-sign-extends: $k widens nothing and should be untouched"; }
  done
  echo "PASS  mutant: exti-sign-extends (layer 0 blind, layer 1 accepts; on the device ${exti_red[*]} differ and the other four do not)"
else
  [ "$mverdict" = "$int_verdict" ] ||
    { cat "$work/m-exti-signed.out" >&2; fail "exti-sign-extends: the clean run is $int_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: exti-sign-extends not verifiable on this driver: the clean run is $int_verdict, before any launch reaches the device"
fi

# 13. inplace-writes-copy: the fake device applies a reference's write-back
#     to a handle nobody has (a negative one, which `gpu_alloc` never mints)
#     instead of the argument position the reference named. This is the
#     mistake a device makes when it "writes the answer somewhere": every
#     buffer the launch was given comes back holding what it held before.
#
#     Layers 0 and 1 are blind BY CONSTRUCTION rather than by measurement:
#     std/gpu is the host side and emits no Tile IR at all, so not one
#     golden byte can move. That is worth saying out loud, because the
#     earlier mutants here earned their blindness (the renderer's own
#     spelling table, an all-true mask being a legal mask) and this one
#     simply has nowhere to show.
#
#     All eight wide kernels differ, and the two readings are not the same
#     reading: `reverse` and `invert` read back the buffer they were HANDED,
#     so it still holds the corpus, and the other six read back an output
#     buffer that still holds the sentinel. The gate requires both.
std_iw="$(mutant_std inplace-writes-copy \
  '                    store = map.insert(store, args[pos], (dt, list.map(v, x => round_to(dt, x))))' \
  '                    store = map.insert(store, 0 - 1 - pos, (dt, list.map(v, x => round_to(dt, x))))')"
build_native "$std_iw" "$work/m-inplace-writes-copy.bin" "$here/wide_diff.dawn"
rc=0
"$work/m-inplace-writes-copy.bin" "${wide_cubins[@]}" > "$work/m-inplace.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-inplace.out")"
if [ "$wide_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-inplace.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#wide[@]}" ]; then
    cat "$work/m-inplace.out" >&2
    fail "inplace-writes-copy mutant stayed green: expected verdict fail (exit 1) with all ${#wide[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  # the in-place pair reads back its INPUT, not the sentinel: the fake
  # device's line for reverse starts at the corpus's first value (3.0) and
  # invert's at its first octet (0.0)
  grep -q '^kernel reverse ' "$work/m-inplace.out" ||
    { cat "$work/m-inplace.out" >&2; fail "inplace-writes-copy: the transcript has no reverse case"; }
  awk '/^kernel /{cur=$2} /^  fake /&&cur=="reverse"{print}' "$work/m-inplace.out" | grep -q 'head=\[3\.0' ||
    { cat "$work/m-inplace.out" >&2; fail "inplace-writes-copy: reverse should read back its own input under the mutant"; }
  awk '/^kernel /{cur=$2} /^  fake /&&cur=="invert"{print}' "$work/m-inplace.out" | grep -q 'head=\[0\.0' ||
    { cat "$work/m-inplace.out" >&2; fail "inplace-writes-copy: invert should read back its own input under the mutant"; }
  echo "PASS  mutant: inplace-writes-copy (all ${#wide[@]} wide kernels differ; the two in-place buffers come back holding the corpus)"
else
  [ "$mverdict" = "$wide_verdict" ] ||
    { cat "$work/m-inplace.out" >&2; fail "inplace-writes-copy: the clean run is $wide_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: inplace-writes-copy not verifiable on this driver: the clean run is $wide_verdict, before any launch reaches the device"
fi

# 14. f16-rounds-like-bf16: the f16 packer rounds with `narrow.round_bf16`
#     and then lays down the binary16 pattern of THAT. It is the mistake of
#     copying `pack_bf16` and changing only the codec, and it is invisible
#     everywhere but on a device: `round_to("f16", ..)` is a different
#     function and still rounds correctly, so the fake device holds the
#     right number and the real one holds a bf16.
#
#     Exactly ONE of the eight goes red, and the other three f16 kernels are
#     the reason to say it: `dot_f16` uploads small integers and the two
#     GEMMs upload multiples of a half, all of which have eight significand
#     bits and pack the same under both roundings. Only `f16_ops`, whose
#     corpus is tenths rounded to the f16 grid, is off the bf16 grid, and
#     that is why its corpus is written the way it is.
std_f16="$(mutant_std f16-rounds-like-bf16 \
  '    let bits = narrow.fp16_bits(narrow.round_fp16(x))' \
  '    let bits = narrow.fp16_bits(narrow.round_bf16(x))')"
build_native "$std_f16" "$work/m-f16-bf16.bin" "$here/wide_diff.dawn"
rc=0
"$work/m-f16-bf16.bin" "${wide_cubins[@]}" > "$work/m-f16-bf16.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-f16-bf16.out")"
f16_red=(f16_ops)
f16_green=(sum_diff reverse invert dot_f16 matmul_f16 batched_matmul_f16 matmul_i8)
if [ "$wide_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-f16-bf16.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#f16_red[@]}" ]; then
    cat "$work/m-f16-bf16.out" >&2
    fail "f16-rounds-like-bf16 mutant stayed green: expected verdict fail (exit 1) with exactly ${#f16_red[@]} kernel saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${f16_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-f16-bf16.out" ||
      { cat "$work/m-f16-bf16.out" >&2; fail "f16-rounds-like-bf16: $k uploads values off the bf16 grid and should differ"; }
  done
  for k in "${f16_green[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-f16-bf16.out" ||
      { cat "$work/m-f16-bf16.out" >&2; fail "f16-rounds-like-bf16: $k uploads nothing off the bf16 grid and should be untouched"; }
  done
  echo "PASS  mutant: f16-rounds-like-bf16 (layers 0 and 1 blind; ${f16_red[*]} differs and the other three f16 kernels do not, because their corpora are on the bf16 grid)"
else
  [ "$mverdict" = "$wide_verdict" ] ||
    { cat "$work/m-f16-bf16.out" >&2; fail "f16-rounds-like-bf16: the clean run is $wide_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: f16-rounds-like-bf16 not verifiable on this driver: the clean run is $wide_verdict, before any launch reaches the device"
fi

# 15. u8-reads-signed: the real handler unpacks a u8 buffer the way it
#     unpacks an i8 one, so an octet above 127 comes back negative. The
#     bytes on the device are the same bytes; what moves is the reading,
#     which is the whole of the difference between the two 8-bit formats.
#
#     `invert` alone is over an 8-bit buffer and it alone reds -- and only
#     because its corpus covers the WHOLE octet range. Half the lanes of
#     that corpus are above 127; a picture of dark pixels would forgive
#     this mutant completely, which is knife 10's shri-always-logical
#     lesson at another width.
std_u8="$(mutant_std u8-reads-signed \
  '  "u8" -> unpack_u8(raw)' \
  '  "u8" -> unpack_i8(raw)')"
build_native "$std_u8" "$work/m-u8-signed.bin" "$here/wide_diff.dawn"
rc=0
"$work/m-u8-signed.bin" "${wide_cubins[@]}" > "$work/m-u8-signed.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-u8-signed.out")"
if [ "$wide_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-u8-signed.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
    cat "$work/m-u8-signed.out" >&2
    fail "u8-reads-signed mutant stayed green: expected verdict fail (exit 1) with invert alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  awk '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != "invert" {bad=1} END {exit bad}' \
    "$work/m-u8-signed.out" ||
    { cat "$work/m-u8-signed.out" >&2; fail "u8-reads-signed: a kernel other than invert moved, and only invert has an 8-bit buffer"; }
  echo "PASS  mutant: u8-reads-signed (invert alone reds; its corpus spans the whole octet range, and half of it is above 127)"
else
  [ "$mverdict" = "$wide_verdict" ] ||
    { cat "$work/m-u8-signed.out" >&2; fail "u8-reads-signed: the clean run is $wide_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: u8-reads-signed not verifiable on this driver: the clean run is $wide_verdict, before any launch reaches the device"
fi

# 16. gather-mask-dropped: the package's `gather_masked` stops handing the
#     handler the mask and the padding value, so every gather reads every
#     lane of its index tile. Layer 0 MOVES (the load loses two operands and
#     a `--record` would take it) and layer 1 ACCEPTS it -- an unmasked load
#     is a load -- so the device is again the only place the difference
#     exists.
#
#     `token_embed` alone gathers, and it reds because eleven of its 104 ids
#     are outside the table: under the mutant those lanes read the row the
#     kernel's address clamp put them on instead of the miss value, sixteen
#     lanes each. That it answers a WRONG NUMBER rather than faulting is the
#     kernel's clamp doing its job, and the reason this is a layer-2 mutant
#     and not a crash: a gather that read past the allocation would be
#     reported here as `blocked`, which is not a difference.
#
#     The other four kernels gather nothing THROUGH A MASK; their bytes do
#     not move and they are the control on the device too. Knife 18's
#     `dequant` is the sharpest of the four: it DOES gather, with an index
#     it computes from each lane's own coordinates, and the mutant cannot
#     reach it because every index it forms is inside the buffer and its
#     gather is therefore unmasked. A control that gathers says more than
#     three that do not.
mutant_pkg_gm="$work/pkg-gather-mask-dropped"
rm -rf "$mutant_pkg_gm"
cp -r "$root/packages/tileir" "$mutant_pkg_gm"
before=$(digest "$mutant_pkg_gm/src/dev.dawn")
python3 "$here/mutate.py" "$mutant_pkg_gm/src/dev.dawn" gather-mask-dropped \
  '  let h: Tile[D] = t_gather(position(p), param_dtype(p), hi, shape, Some(hm), Some(hp))' \
  '  let h: Tile[D] = t_gather(position(p), param_dtype(p), hi, shape, None, None)'
after=$(digest "$mutant_pkg_gm/src/dev.dawn")
echo "      gather-mask-dropped: packages/tileir/src/dev.dawn md5 $before -> $after"

mutant_kernels gather-mask-dropped "$mutant_pkg_gm" "${gathered[@]}"
gather_red=(token_embed)
moved=0
for k in "${gathered[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/gather-mask-dropped-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = "${#gather_red[@]}" ] ||
  fail "gather-mask-dropped: expected exactly ${#gather_red[@]} of the ${#gathered[@]} kernels' bytecode to move, got $moved"
echo "      gather-mask-dropped: ${#gather_red[@]} of ${#gathered[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
gm_cubins=()
for k in "${gathered[@]}"; do gm_cubins+=("$work/gather-mask-dropped-$k.cubin"); done
rc=0
"$work/gath.bin" "${gm_cubins[@]}" > "$work/m-gather-mask.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-gather-mask.out")"
if [ "$gath_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-gather-mask.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#gather_red[@]}" ]; then
    cat "$work/m-gather-mask.out" >&2
    fail "gather-mask-dropped mutant stayed green: expected verdict fail (exit 1) with exactly ${#gather_red[@]} kernel saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${gather_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-gather-mask.out" ||
      { cat "$work/m-gather-mask.out" >&2; fail "gather-mask-dropped: $k gathers out-of-range ids and should differ"; }
  done
  for k in sort_rank merge_rank scatter_perm dequant nearest_idx; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-gather-mask.out" ||
      { cat "$work/m-gather-mask.out" >&2; fail "gather-mask-dropped: $k gathers through no mask and should be untouched"; }
  done
  echo "PASS  mutant: gather-mask-dropped (layer 1 accepts it; on the device ${gather_red[*]} differs and the other five do not)"
else
  [ "$mverdict" = "$gath_verdict" ] ||
    { cat "$work/m-gather-mask.out" >&2; fail "gather-mask-dropped: the clean run is $gath_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: gather-mask-dropped not verifiable on this driver: the clean run is $gath_verdict, before any launch reaches the device"
fi

# A kernel-source mutant: one anchor rewritten in a copy of
# scripts/tile-golden/kernels.dawn, that kernel re-encoded and assembled,
# and gath_diff run with it in place of the clean cubin. The shape
# softmax-no-max-subtract and halo-one-lane-short use.
gath_kernel_mutant() { # name, kernel, old, new
  local name="$1" k="$2" src="$work/kernels-$1.dawn" before after
  cp "$golden/kernels.dawn" "$src"
  before=$(digest "$src")
  python3 "$here/mutate.py" "$src" "$name" "$3" "$4"
  after=$(digest "$src")
  echo "      $name: scripts/tile-golden/kernels.dawn md5 $before -> $after"
  mkdir -p "$work/proj-$name/src"
  cp "$src" "$work/proj-$name/src/main.dawn"
  cat > "$work/proj-$name/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
  "$root/bin/dawn" run "$work/proj-$name" -- "$k" --bytecode "$work/$name.tilebc" > "$work/proj-$name.log" 2>&1 ||
    { cat "$work/proj-$name.log" >&2; fail "$name: $k did not encode"; }
  cmp -s "$golden/$k.tilebc" "$work/$name.tilebc" &&
    fail "$name mutant stayed green: $k.tilebc is unchanged"
  assemble_golden "$k" "$work/$name.tilebc" "$work/$name.cubin"
  echo "      $name: $k.tilebc differs from the golden and tileiras still accepts it"
}

# Run gath_diff with `kernel`'s cubin replaced by the mutant's, and require
# that kernel and no other to differ.
gath_kernel_check() { # name, kernel
  local name="$1" k="$2" rc=0 mverdict differ cubs=()
  local one
  for one in "${gathered[@]}"; do
    if [ "$one" = "$k" ]; then cubs+=("$work/$name.cubin"); else cubs+=("$work/$one.cubin"); fi
  done
  "$work/gath.bin" "${cubs[@]}" > "$work/m-$name.out" 2>&1 || rc=$?
  mverdict="$(verdict_of "$work/m-$name.out")"
  if [ "$gath_verdict" = pass ]; then
    differ=$(grep -c '^  verdict differ:result$' "$work/m-$name.out" || true)
    if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
      cat "$work/m-$name.out" >&2
      fail "$name mutant stayed green: expected verdict fail (exit 1) with $k alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
    fi
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != want {bad=1} END {exit bad}' \
      "$work/m-$name.out" ||
      { cat "$work/m-$name.out" >&2; fail "$name: a kernel other than $k moved"; }
    echo "PASS  mutant: $name ($k alone reds; the other $(( ${#gathered[@]} - 1 )) gather and scatter kernels are untouched)"
  else
    [ "$mverdict" = "$gath_verdict" ] ||
      { cat "$work/m-$name.out" >&2; fail "$name: the clean run is $gath_verdict but the mutant is $mverdict"; }
    echo "SKIP  mutant: $name not verifiable on this driver: the clean run is $gath_verdict, before any launch reaches the device"
  fi
}

# 17. scatter-unpermuted: `scatter_perm` writes each lane at its own index
#     instead of at the destination it read out of a buffer. The mask is
#     still the one the destinations decided, so the same lanes are written
#     and the same ones are left alone; only WHERE moves. Layer 0 moves,
#     layer 1 accepts it (one index tile is as legal as another), and the
#     device says 255 of 264 lanes hold the wrong value.
gath_kernel_mutant scatter-unpermuted scatter_perm \
  '  scatter_masked(out, dst, s, ok, load(x, blk, s))' \
  '  scatter_masked(out, lanes(blk, s), s, ok, load(x, blk, s))'
gath_kernel_check scatter-unpermuted scatter_perm

# 18. rank-scatter-in-lane-order: `sort_rank` still computes every rank and
#     then stores its values contiguously instead of scattering them there.
#     The comparison tile, the reduction and the conversion are all
#     untouched and all still right; what is gone is the one instruction
#     that turns a rank into a sort. The scatter here carries NO mask, which
#     is the half of the surface scatter-unpermuted does not reach.
gath_kernel_mutant rank-scatter-in-lane-order sort_rank \
  '  scatter(out, float_to_int(F64, s1, rank), s1, load(x, zero, s1))' \
  '  store(out, zero, s1, load(x, zero, s1))'
gath_kernel_check rank-scatter-in-lane-order sort_rank

# A kernel-source mutant for the scan family: the gath_ pair above with
# scan_diff's kernel list. Two helpers rather than one generic pair because
# each closes over its own program's cubin order, and a wrong order here
# would be a silently weaker gate rather than a failure.
scan_kernel_mutant() { # name, kernel, old, new
  local name="$1" k="$2" src="$work/kernels-$1.dawn" before after
  cp "$golden/kernels.dawn" "$src"
  before=$(digest "$src")
  python3 "$here/mutate.py" "$src" "$name" "$3" "$4"
  after=$(digest "$src")
  echo "      $name: scripts/tile-golden/kernels.dawn md5 $before -> $after"
  mkdir -p "$work/proj-$name/src"
  cp "$src" "$work/proj-$name/src/main.dawn"
  cat > "$work/proj-$name/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
  "$root/bin/dawn" run "$work/proj-$name" -- "$k" --bytecode "$work/$name.tilebc" > "$work/proj-$name.log" 2>&1 ||
    { cat "$work/proj-$name.log" >&2; fail "$name: $k did not encode"; }
  cmp -s "$golden/$k.tilebc" "$work/$name.tilebc" &&
    fail "$name mutant stayed green: $k.tilebc is unchanged"
  assemble_golden "$k" "$work/$name.tilebc" "$work/$name.cubin"
  echo "      $name: $k.tilebc differs from the golden and tileiras still accepts it"
}

# Run scan_diff with `kernel`'s cubin replaced by the mutant's, and require
# that kernel and no other to differ.
scan_kernel_check() { # name, kernel
  local name="$1" k="$2" rc=0 mverdict differ cubs=()
  local one
  for one in "${scanned[@]}"; do
    if [ "$one" = "$k" ]; then cubs+=("$work/$name.cubin"); else cubs+=("$work/$one.cubin"); fi
  done
  "$work/scan.bin" "${cubs[@]}" > "$work/m-$name.out" 2>&1 || rc=$?
  mverdict="$(verdict_of "$work/m-$name.out")"
  if [ "$scan_verdict" = pass ]; then
    differ=$(grep -c '^  verdict differ:result$' "$work/m-$name.out" || true)
    if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
      cat "$work/m-$name.out" >&2
      fail "$name mutant stayed green: expected verdict fail (exit 1) with $k alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
    fi
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != want {bad=1} END {exit bad}' \
      "$work/m-$name.out" ||
      { cat "$work/m-$name.out" >&2; fail "$name: a kernel other than $k moved"; }
    echo "PASS  mutant: $name ($k alone reds; the other $(( ${#scanned[@]} - 1 )) scan kernels are untouched)"
  else
    [ "$mverdict" = "$scan_verdict" ] ||
      { cat "$work/m-$name.out" >&2; fail "$name: the clean run is $scan_verdict but the mutant is $mverdict"; }
    echo "SKIP  mutant: $name not verifiable on this driver: the clean run is $scan_verdict, before any launch reaches the device"
  fi
}

# 19. scan-reverse-ignored: the WRITER pins a scan's `reverse` attribute to
#     false, whatever the record says. Layer 0 is blind by construction (the
#     renderer prints `reverse=true` from the record, not from the byte) and
#     layer 1 accepts it -- a forward scan is a legal scan -- so only the
#     device can say the prefix now runs the wrong way.
#
#     Exactly ONE of the seven kernels sets the attribute, and it is the only
#     one whose bytes move: `gae` accumulates from the end of its row, which
#     is what leetgpu 110 asks for and what `reverse` exists for. The other
#     six already wrote a zero there, so they are the control in the bytes
#     as well as on the device -- a stronger statement than six that red.
mutant_pkg_rev="$work/pkg-scan-reverse-ignored"
rm -rf "$mutant_pkg_rev"
cp -r "$root/packages/tileir" "$mutant_pkg_rev"
before=$(digest "$mutant_pkg_rev/src/bytecode.dawn")
python3 "$here/mutate.py" "$mutant_pkg_rev/src/bytecode.dawn" scan-reverse-ignored \
  '    let w3 = emit(emit(emit(w2, dim), if reverse { 1 } else { 0 }), len(identities))' \
  '    let w3 = emit(emit(emit(w2, dim), 0), len(identities))'
after=$(digest "$mutant_pkg_rev/src/bytecode.dawn")
echo "      scan-reverse-ignored: packages/tileir/src/bytecode.dawn md5 $before -> $after"

mutant_kernels scan-reverse-ignored "$mutant_pkg_rev" "${scanned[@]}"
reverse_red=(gae)
moved=0
for k in "${scanned[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/scan-reverse-ignored-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = "${#reverse_red[@]}" ] ||
  fail "scan-reverse-ignored: expected exactly ${#reverse_red[@]} of the ${#scanned[@]} kernels' bytecode to move, got $moved"
echo "      scan-reverse-ignored: ${#reverse_red[@]} of ${#scanned[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
rev_cubins=()
for k in "${scanned[@]}"; do rev_cubins+=("$work/scan-reverse-ignored-$k.cubin"); done
rc=0
"$work/scan.bin" "${rev_cubins[@]}" > "$work/m-scan-reverse.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-scan-reverse.out")"
if [ "$scan_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-scan-reverse.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#reverse_red[@]}" ]; then
    cat "$work/m-scan-reverse.out" >&2
    fail "scan-reverse-ignored mutant stayed green: expected verdict fail (exit 1) with exactly ${#reverse_red[@]} kernel saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${reverse_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-scan-reverse.out" ||
      { cat "$work/m-scan-reverse.out" >&2; fail "scan-reverse-ignored: $k scans in reverse and should differ"; }
  done
  for k in prefix_sum max_subarray seg_scan compact linrec ssm_scan; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
      "$work/m-scan-reverse.out" ||
      { cat "$work/m-scan-reverse.out" >&2; fail "scan-reverse-ignored: $k scans forward and should be untouched"; }
  done
  echo "PASS  mutant: scan-reverse-ignored (layer 1 accepts it; on the device ${reverse_red[*]} differs and the other six do not, and their bytes do not move either)"
else
  [ "$mverdict" = "$scan_verdict" ] ||
    { cat "$work/m-scan-reverse.out" >&2; fail "scan-reverse-ignored: the clean run is $scan_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: scan-reverse-ignored not verifiable on this driver: the clean run is $scan_verdict, before any launch reaches the device"
fi

# 20. exclusive-scan-as-inclusive: `compact` scatters each kept value at the
#     INCLUSIVE count of kept lanes instead of the exclusive one, which is
#     the count with the lane's own bit still in it. Every value moves one
#     place late and element 0 of the output is never written at all.
#
#     This is the one boundary a scan has that a reduction does not. The
#     dialect's scan is inclusive and there is no attribute to make it
#     exclusive; a kernel that wants the exclusive prefix subtracts its own
#     element, and getting that wrong is a legal kernel with a wrong answer.
#     Layer 0 moves (one `subi` disappears), layer 1 accepts it, and only
#     the device says where the values landed. `seg_scan` makes the same
#     step in floats and is untouched here: its exclusive prefix is a
#     different expression, which is why the red set is one kernel and not
#     two.
scan_kernel_mutant exclusive-scan-as-inclusive compact \
  '  scatter_masked(out, sub_i(s, incl, ones), s, keep, t)' \
  '  scatter_masked(out, incl, s, keep, t)'
scan_kernel_check exclusive-scan-as-inclusive compact

# 21. atomic-as-plain-store: the PACKAGE's `atomic_add_masked` issues a
#     gather, an addi and a scatter where it issued an atomic. That is
#     exactly the program an atomic add would be if no two lanes ever met,
#     and layer 1 has no way to prefer one to the other: a masked load and
#     a masked store are as legal as the atomic they replace.
#
#     On the device the histogram loses every increment but one per bin per
#     block, because the lanes of one store are not ordered against each
#     other. `cas_swap` does not go through this surface, so its bytes do
#     not move and it is the control at layer 0 as well as at layer 2.
mutant_pkg_atom="$work/pkg-atomic-as-plain-store"
rm -rf "$mutant_pkg_atom"
cp -r "$root/packages/tileir" "$mutant_pkg_atom"
before=$(digest "$mutant_pkg_atom/src/dev.dawn")
python3 "$here/mutate.py" "$mutant_pkg_atom/src/dev.dawn" atomic-as-plain-store \
  '  let _old = atomic_rmw_masked(p, "add", index, shape, mask, v)
  ()' \
  '  let old = gather_masked(p, index, shape, mask, i_const(shape, 0))
  scatter_masked(p, index, shape, mask, add_i(shape, old, v))'
after=$(digest "$mutant_pkg_atom/src/dev.dawn")
echo "      atomic-as-plain-store: packages/tileir/src/dev.dawn md5 $before -> $after"

mutant_kernels atomic-as-plain-store "$mutant_pkg_atom" "${atomic[@]}"
atom_red=(histogram)
moved=0
for k in "${atomic[@]}"; do
  if cmp -s "$golden/$k.tilebc" "$work/atomic-as-plain-store-$k.tilebc"; then :; else moved=$((moved + 1)); fi
done
[ "$moved" = "${#atom_red[@]}" ] ||
  fail "atomic-as-plain-store: expected exactly ${#atom_red[@]} of the ${#atomic[@]} kernels' bytecode to move, got $moved"
echo "      atomic-as-plain-store: ${#atom_red[@]} of ${#atomic[@]} .tilebc files differ from the goldens and tileiras still accepts every one"
atom_mut_cubins=()
for k in "${atomic[@]}"; do atom_mut_cubins+=("$work/atomic-as-plain-store-$k.cubin"); done
rc=0
"$work/atom.bin" "${atom_mut_cubins[@]}" > "$work/m-atomic-as-plain-store.out" 2>&1 || rc=$?
mverdict="$(verdict_of "$work/m-atomic-as-plain-store.out")"
if [ "$atom_verdict" = pass ]; then
  differ=$(grep -c '^  verdict differ:result$' "$work/m-atomic-as-plain-store.out" || true)
  if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#atom_red[@]}" ]; then
    cat "$work/m-atomic-as-plain-store.out" >&2
    fail "atomic-as-plain-store mutant stayed green: expected verdict fail (exit 1) with exactly ${#atom_red[@]} kernel saying differ:result, got $mverdict (exit $rc, $differ differing)"
  fi
  for k in "${atom_red[@]}"; do
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {seen=1} END {exit !seen}' \
      "$work/m-atomic-as-plain-store.out" ||
      { cat "$work/m-atomic-as-plain-store.out" >&2; fail "atomic-as-plain-store: $k has colliding lanes and should differ"; }
  done
  awk '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == "cas_swap" {bad=1} END {exit bad}' \
    "$work/m-atomic-as-plain-store.out" ||
    { cat "$work/m-atomic-as-plain-store.out" >&2; fail "atomic-as-plain-store: cas_swap does not add and should be untouched"; }
  # THE CONTROL. The same mutant on a corpus with one lane a bin: the
  # atomic and the load-add-store are then the same program, so it must be
  # green. This is what says the mutant is caught by the collisions and
  # not by anything else the kernel does.
  rc=0
  "$work/atom.bin" --corpus unique "${atom_mut_cubins[@]}" > "$work/m-atomic-as-plain-store-unique.out" 2>&1 || rc=$?
  cverdict="$(verdict_of "$work/m-atomic-as-plain-store-unique.out")"
  if [ "$cverdict" != pass ] || [ "$rc" != 0 ]; then
    cat "$work/m-atomic-as-plain-store-unique.out" >&2
    fail "atomic-as-plain-store: the control corpus should forgive the mutant entirely, got $cverdict (exit $rc)"
  fi
  echo "PASS  mutant: atomic-as-plain-store (layer 1 accepts it; on the device ${atom_red[*]} differs, cas_swap does not, and the collision-free corpus forgives it)"
else
  [ "$mverdict" = "$atom_verdict" ] ||
    { cat "$work/m-atomic-as-plain-store.out" >&2; fail "atomic-as-plain-store: the clean run is $atom_verdict but the mutant is $mverdict"; }
  echo "SKIP  mutant: atomic-as-plain-store not verifiable on this driver: the clean run is $atom_verdict, before any launch reaches the device"
fi

# A kernel-source mutant for the atomic family: the gath_ and scan_ pair
# with atom_diff's kernel list.
atom_kernel_mutant() { # name, kernel, old, new
  local name="$1" k="$2" src="$work/kernels-$1.dawn" before after
  cp "$golden/kernels.dawn" "$src"
  before=$(digest "$src")
  python3 "$here/mutate.py" "$src" "$name" "$3" "$4"
  after=$(digest "$src")
  echo "      $name: scripts/tile-golden/kernels.dawn md5 $before -> $after"
  mkdir -p "$work/proj-$name/src"
  cp "$src" "$work/proj-$name/src/main.dawn"
  cat > "$work/proj-$name/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$root/packages/tileir"
TOML
  "$root/bin/dawn" run "$work/proj-$name" -- "$k" --bytecode "$work/$name.tilebc" > "$work/proj-$name.log" 2>&1 ||
    { cat "$work/proj-$name.log" >&2; fail "$name: $k did not encode"; }
  cmp -s "$golden/$k.tilebc" "$work/$name.tilebc" &&
    fail "$name mutant stayed green: $k.tilebc is unchanged"
  assemble_golden "$k" "$work/$name.tilebc" "$work/$name.cubin"
  echo "      $name: $k.tilebc differs from the golden and tileiras still accepts it"
}

# Run atom_diff with `kernel`'s cubin replaced by the mutant's, and require
# that kernel and no other to differ.
atom_kernel_check() { # name, kernel
  local name="$1" k="$2" rc=0 mverdict differ cubs=()
  local one
  for one in "${atomic[@]}"; do
    if [ "$one" = "$k" ]; then cubs+=("$work/$name.cubin"); else cubs+=("$work/$one.cubin"); fi
  done
  "$work/atom.bin" "${cubs[@]}" > "$work/m-$name.out" 2>&1 || rc=$?
  mverdict="$(verdict_of "$work/m-$name.out")"
  if [ "$atom_verdict" = pass ]; then
    differ=$(grep -c '^  verdict differ:result$' "$work/m-$name.out" || true)
    if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != 1 ]; then
      cat "$work/m-$name.out" >&2
      fail "$name mutant stayed green: expected verdict fail (exit 1) with $k alone saying differ:result, got $mverdict (exit $rc, $differ differing)"
    fi
    awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur != want {bad=1} END {exit bad}' \
      "$work/m-$name.out" ||
      { cat "$work/m-$name.out" >&2; fail "$name: a kernel other than $k moved"; }
    echo "PASS  mutant: $name ($k alone reds; the other $(( ${#atomic[@]} - 1 )) atomic kernel is untouched)"
  else
    [ "$mverdict" = "$atom_verdict" ] ||
      { cat "$work/m-$name.out" >&2; fail "$name: the clean run is $atom_verdict but the mutant is $mverdict"; }
    echo "SKIP  mutant: $name not verifiable on this driver: the clean run is $atom_verdict, before any launch reaches the device"
  fi
}

# 22. cas-compare-ignored: `cas_swap` hands the compare-and-swap the value
#     it is about to write as the value it expects to find. The comparison
#     then always fails on this corpus (no slot holds a value near 1000),
#     so no slot takes a new value and the 34 that should have are wrong.
#
#     The comparison is the whole of what separates a compare-and-swap from
#     an exchange, and nothing below the device knows which of the two tile
#     operands is which: `AllTypesMatch<["cmp", "val", "result"]>` is
#     satisfied either way, which is why tileiras accepts it.
atom_kernel_mutant cas-compare-ignored cas_swap \
  '  let prev = atomic_cas_masked(state, lanes(blk, s), s, active, c, v)' \
  '  let prev = atomic_cas_masked(state, lanes(blk, s), s, active, v, v)'
atom_kernel_check cas-compare-ignored cas_swap

# The two mutants of the error function family (knife 15). Both live in the
# PACKAGE's `erf` and therefore move the two kernels that call it; what
# tells them apart is the corpus, so each is run twice, once on erf_diff's
# main corpus and once on its `--corpus positive` control, and the pair of
# verdicts is the claim.
#
# Knife 18 put a third kernel in that program, `swiglu_half`, which has
# `geglu`'s shape and a swish gate instead of an error function. It is this
# family's first KERNEL-LEVEL control: neither mutant may move it, at layer
# 0 or on the device. Until now the only control here was a second corpus,
# which is why the old spelling of these checks was "all of them move".
#
# `want_main` and `want_positive` are `fail` or `pass`.
erf_pkg_mutant() { # name, old, new, want_main, want_positive
  local name="$1" old="$2" new="$3" want_main="$4" want_positive="$5"
  local pkg="$work/pkg-$name" before after k moved=0 rc=0 mverdict differ cubs=()
  rm -rf "$pkg"
  cp -r "$root/packages/tileir" "$pkg"
  before=$(digest "$pkg/src/dev.dawn")
  python3 "$here/mutate.py" "$pkg/src/dev.dawn" "$name" "$old" "$new"
  after=$(digest "$pkg/src/dev.dawn")
  echo "      $name: packages/tileir/src/dev.dawn md5 $before -> $after"

  mutant_kernels "$name" "$pkg" "${erfs[@]}"
  for k in "${erf_red[@]}"; do
    if cmp -s "$golden/$k.tilebc" "$work/$name-$k.tilebc"; then :; else moved=$((moved + 1)); fi
  done
  [ "$moved" = "${#erf_red[@]}" ] ||
    fail "$name: the ${#erf_red[@]} kernels that go through the composition should move at layer 0, got $moved"
  for k in "${erf_green[@]}"; do
    cmp -s "$golden/$k.tilebc" "$work/$name-$k.tilebc" ||
      fail "$name: $k calls no erf, so its bytecode must not move"
  done
  echo "      $name: ${#erf_red[@]} of ${#erfs[@]} .tilebc files differ from the goldens (${erf_green[*]} does not) and tileiras still accepts every one"

  for k in "${erfs[@]}"; do cubs+=("$work/$name-$k.cubin"); done
  if [ "$erf_verdict" != pass ]; then
    rc=0
    "$work/erf.bin" "${cubs[@]}" > "$work/m-$name.out" 2>&1 || rc=$?
    mverdict="$(verdict_of "$work/m-$name.out")"
    [ "$mverdict" = "$erf_verdict" ] ||
      { cat "$work/m-$name.out" >&2; fail "$name: the clean run is $erf_verdict but the mutant is $mverdict"; }
    echo "SKIP  mutant: $name not verifiable on this driver: the clean run is $erf_verdict, before any launch reaches the device"
    return 0
  fi

  erf_mutant_corpus "$name" main "$want_main" "${cubs[@]}"
  erf_mutant_corpus "$name" positive "$want_positive" "${cubs[@]}"
  if [ "$want_main" = fail ] && [ "$want_positive" = pass ]; then
    echo "PASS  mutant: $name (layer 1 accepts it; on the device ${erf_red[*]} differ and ${erf_green[*]} does not, and the corpus with no negative lane forgives it entirely)"
  else
    echo "PASS  mutant: $name (layer 1 accepts it; on the device ${erf_red[*]} differ on both corpora and ${erf_green[*]} on neither, so the tolerance tier is not what is forgiving it)"
  fi
}

# One mutant against one corpus: `want` is the verdict the run must reach,
# and when it is `fail` exactly the kernels of `erf_red` must be the ones
# that red -- both go through the composition, so a mutant that moved only
# one of them would be a mutant of something else, and one that moved
# `swiglu_half` too would be a mutant of something wider than `erf`.
erf_mutant_corpus() { # name, corpus, want, cubins...
  local name="$1" corpus="$2" want="$3"
  shift 3
  local out="$work/m-$name-$corpus.out" rc=0 mverdict differ
  if [ "$corpus" = positive ]; then
    "$work/erf.bin" --corpus positive "$@" > "$out" 2>&1 || rc=$?
  else
    "$work/erf.bin" "$@" > "$out" 2>&1 || rc=$?
  fi
  mverdict="$(verdict_of "$out")"
  differ=$(grep -c '^  verdict differ:result$' "$out" || true)
  if [ "$want" = fail ]; then
    if [ "$mverdict" != fail ] || [ "$rc" != 1 ] || [ "$differ" != "${#erf_red[@]}" ]; then
      cat "$out" >&2
      fail "$name on the $corpus corpus stayed green: expected fail (exit 1) with ${#erf_red[@]} kernels saying differ:result, got $mverdict (exit $rc, $differ differing)"
    fi
    for k in "${erf_green[@]}"; do
      awk -v want="$k" '/^kernel /{cur=$2} /^  verdict differ:result$/ && cur == want {bad=1} END {exit bad}' \
        "$out" || { cat "$out" >&2; fail "$name: $k calls no erf and should be untouched"; }
    done
  else
    if [ "$mverdict" != pass ] || [ "$rc" != 0 ]; then
      cat "$out" >&2
      fail "$name on the $corpus corpus should be forgiven entirely, got $mverdict (exit $rc, $differ differing)"
    fi
  fi
  echo "      $name: the $corpus corpus answers $mverdict ($differ of ${#erfs[@]} kernels differ)"
}

# 23. erf-tanh-approx: the package's `erf` runs the tanh formula PyTorch
#     calls `gelu(approximate="tanh")` instead of Abramowitz-Stegun 7.1.26.
#     Written in terms of erf rather than gelu it is
#     `tanh(1.1283791670955128 x + 0.10091094891335171 x^3)`, and it is
#     what leetgpu 74 (GPT-2 Block) actually asks for -- so this is not a
#     straw man, it is the other formula a reader might reach for.
#
#     It is out by about 3.6e-4, 36 times the atol these kernels are
#     compared under, so both of them red on BOTH corpora. That is the
#     point of it: a tolerance tier wide enough to forgive this would be a
#     tier that had stopped saying anything, and the sign mutant below
#     would have no way to show that its own greenness on the control
#     corpus means something.
erf_pkg_mutant erf-tanh-approx \
  '  let one = f_const(d, shape, 1.0)
  let t = div(d, shape, one, fma(d, shape, f_const(d, shape, AS_P), ax, one))
  let inner = fma(d, shape, t,
    fma(d, shape, t,
      fma(d, shape, t,
        fma(d, shape, t, f_const(d, shape, AS_A5), f_const(d, shape, AS_A4)),
        f_const(d, shape, AS_A3)),
      f_const(d, shape, AS_A2)),
    f_const(d, shape, AS_A1))
  let m = sub(d, shape, one,
    mul(d, shape, mul(d, shape, t, inner), exp(d, shape, neg(d, shape, mul(d, shape, ax, ax)))))' \
  '  let m = tanh(d, shape,
    fma(d, shape, mul(d, shape, ax, mul(d, shape, ax, ax)), f_const(d, shape, 0.10091094891335171),
      mul(d, shape, f_const(d, shape, 1.1283791670955128), ax)))' \
  fail fail

# 24. erf-sign-not-flipped: the package's `erf` drops the odd symmetry and
#     answers `erf(|x|)` on every lane. 7.1.26 is stated for `x >= 0` and
#     for nothing else, and the `select` is the whole of what covers the
#     other half; without it a negative lane gets the positive answer, out
#     by up to 2.
#
#     THE CONTROL IS THE POINT. On erf_diff's `--corpus positive`, where no
#     lane is negative, this mutant is a no-op and the run must pass. That
#     is what says the negative lanes in the main corpus are doing the
#     catching -- the same argument atomic-as-plain-store's collision-free
#     corpus makes for knife 14, run the other way round.
erf_pkg_mutant erf-sign-not-flipped \
  '  select(d, shape, lt(d, shape, a, f_const(d, shape, 0.0)), neg(d, shape, m), m)' \
  '  m' \
  fail pass

# ---- ledger
if [ "$append" = no ]; then
  echo "      --dry: ledger not written (would record: $verdict)"
  echo "tile-gpu-diff: $verdict"
  exit 0
fi
[ "$pinned_driver" = "$driver" ] ||
  fail "toolchain.txt says driver $pinned_driver and nvidia-smi says $driver: set the driver line to $driver, commit, and run again (the three numbers move together; the ledger commit adds a line and nothing else)"
dirty="$(git status --porcelain -- packages/tileir std/gpu.dawn std/narrow.dawn runtime/c/dawn_rt.c \
  scripts/tile-golden scripts/tile-gpu-diff/run.sh scripts/tile-gpu-diff/vadd_diff.dawn \
  scripts/tile-gpu-diff/mask_diff.dawn scripts/tile-gpu-diff/red_diff.dawn scripts/tile-gpu-diff/mm_diff.dawn \
  scripts/tile-gpu-diff/stride_diff.dawn scripts/tile-gpu-diff/int_diff.dawn scripts/tile-gpu-diff/wide_diff.dawn \
  scripts/tile-gpu-diff/gath_diff.dawn scripts/tile-gpu-diff/scan_diff.dawn \
  scripts/tile-gpu-diff/atom_diff.dawn scripts/tile-gpu-diff/erf_diff.dawn \
  scripts/tile-gpu-diff/seq_diff.dawn \
  scripts/tile-gpu-diff/mutate.py)"
[ -z "$dirty" ] ||
  { printf '%s\n' "$dirty" >&2; fail "tile paths have uncommitted changes: the ledger line would name a tree that was not run. Commit first."; }
commit="$(git rev-parse --short=12 HEAD)"
today="$(date -u +%F)"
line="$commit $today $driver $want_tileiras $gpu_name $verdict"
summary="$tiers fold-order=$probe scan-order=$scan_probe as-error=$erf_probe"
summary="$summary seq-launches=$seq_launch_probe"
if [ -n "$note" ]; then line="$line # $note; $summary"; else line="$line # $summary"; fi
printf '%s\n' "$line" >> "$ledger"
echo "      ledger: appended: $line"
echo "tile-gpu-diff: $verdict"

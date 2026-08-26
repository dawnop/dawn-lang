#!/usr/bin/env bash
# Keep comptime failures structured until the diagnostic boundary.
#
# The public leg checks the rendered call shapes and nearest-frame cap. Four
# source mutants then compile and execute a private copy of selfhost: each must
# fail the unit test that owns the rule, rather than merely stop compiling.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
here="$root/scripts/comptime-trace-contract"
work=$(mktemp -d "${TMPDIR:-/tmp}/comptime-trace-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require() {
  local needle=$1 file=$2
  grep -Fq "$needle" "$file" || fail "missing diagnostic text: $needle"
}

# The budget is a knob, not a claim: it has to land the FUEL const's failure
# with the lambda `map` calls on top of the chain, and how many steps that
# takes depends on what the interpreter does per call. It was 200 until a
# function value gained its hidden evidence slot -- the pack a dynamic call
# builds is evaluated like any other argument, so the walk cost a few more
# steps and stopped one frame short of the lambda at 200 -- then 208.
#
# 206 since the evidence semantics flipped, and *down* rather than up, which is
# worth the sentence because the guess was that reads would make it climb. They
# do not here: `trace.dawn:6` is `map(range(0, 100), x => x + 1)`, a pure row
# with no ground atom to look up and no environment to forward, so the pack is
# the empty one and nothing walks it. What moved is that the pack is now built
# by the checker and arrives as a lowered argument rather than being assembled
# in `lower.ev_pack`, and the interpreter counts the two differently.
#
# 204 since `xs ++ [x]` lowers to one `list_push` intrinsic: the per-element
# append inside `map_go` was two evaluated nodes (the one-element list, then
# the concat) and is now one, so the same chain fits in slightly less fuel.
# Measured, not reasoned: the window that satisfies every needle below is
# 203-205, and this is its middle.
cp "$here/trace.dawn" "$work/trace.dawn"
if "$dawn" run --comptime-fuel=204 "$work/trace.dawn" > "$work/trace.out" 2>&1; then
  fail "the diagnostic fixture unexpectedly compiled"
fi

require 'raise it with --comptime-fuel, or simplify the computation' "$work/trace.out"
require 'at direct `std/list.map_go`' "$work/trace.out"
require 'at direct `std/list.map`' "$work/trace.out"
require 'at direct `trace.fuel_outer`' "$work/trace.out"
require 'at default `trace::Defaulted#' "$work/trace.out"
require 'at impl `trace::Required#' "$work/trace.out"
require 'at dynamic `trace.lambda$0`' "$work/trace.out"
require 'at direct `trace.dyn_boom`' "$work/trace.out"
require '  ... outer calls omitted' "$work/trace.out"
require '5 errors' "$work/trace.out"

python3 - "$work/trace.out" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text()
actionable = "raise it with --comptime-fuel, or simplify the computation"
chain = "comptime call chain (innermost first):"
if text.index(actionable) > text.index(chain):
    raise SystemExit("FAIL: actionable hint no longer precedes the call chain")

frames = [
    line.removeprefix("  at direct `trace.").removesuffix("`")
    for line in text.splitlines()
    if line.startswith("  at direct `trace.limit_")
]
expected = [f"limit_{index:02d}" for index in range(19, 3, -1)]
if frames != expected:
    raise SystemExit(f"FAIL: nearest-frame window changed: {frames!r}")
PY
echo "PASS  comptime diagnostics preserve hints and bounded call identities"

mutate() {
  local name=$1 source=$2
  python3 - "$name" "$source" <<'PY'
from pathlib import Path
import sys

name, source = sys.argv[1:]
path = Path(source)
text = path.read_text()

def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"mutation anchor occurs {count} times: {old!r}")
    text = text.replace(old, new)

if name == "overwrite-direct-hint":
    start = text.index("fn call_named(")
    end = text.index("# ---- intrinsics", start)
    section = text[start:end]
    old = "      call_cfun(icx, st1, env, cf, frame, no_caps, args)"
    new = """      match call_cfun(icx, st1, env, cf, frame, no_caps, args) {
        Ok(value) -> Ok(value)
        Err(err) -> {
          let (st2, env2, ctl) = err
          match ctl {
            KErr(failure) -> Err((st2, env2, KErr(CtFailure {
              ..failure,
              hint: \"raised inside the standard library function `\" ++ name ++ \"`\"
            })))
            _ -> Err(err)
          }
        }
      }"""
    if section.count(old) != 1:
        raise SystemExit("call_named mutation anchor drifted")
    text = text[:start] + section.replace(old, new) + text[end:]
elif name == "omit-default-frame":
    replace_once(
        "  let frame = FDefault(owner, trait_frame_name(icx, tid), tid, method)",
        "  let frame = FDirect(owner, method)",
    )
elif name == "omit-impl-frame":
    replace_once(
        "          let frame = FImpl(owner, trait_frame_name(icx, tid), tid, ty_key(subject), m)",
        "          let frame = FDirect(owner, m)",
    )
elif name == "remove-frame-cap":
    replace_once("const MAX_FAILURE_FRAMES: Int = 16", "const MAX_FAILURE_FRAMES: Int = 100000")
else:
    raise SystemExit(f"unknown mutation: {name}")

path.write_text(text)
PY
}

expect_mutant_red() {
  local name=$1 expected=$2 mutant="$work/mutant-$1"
  cp -R "$root/selfhost" "$mutant"
  mutate "$name" "$mutant/src/ir/interp.dawn"
  if "$dawn" test "$mutant" > "$mutant.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  if ! grep -Fq "$expected" "$mutant.out"; then
    cat "$mutant.out" >&2
    fail "$name mutant missed its intended selfhost test"
  fi
  echo "PASS  $name mutant turns its comptime trace test red"
}

cp -R "$root/compiler-plan" "$work/compiler-plan"
ln -s "$root/packages" "$work/packages"

expect_mutant_red overwrite-direct-hint \
  'a standard helper keeps the fuel hint beside its inner and outer frames'
expect_mutant_red omit-default-frame \
  'dynamic, impl, and default failures each carry their real frame'
expect_mutant_red omit-impl-frame \
  'dynamic, impl, and default failures each carry their real frame'
expect_mutant_red remove-frame-cap \
  'comptime call chains retain the nearest sixteen frames'

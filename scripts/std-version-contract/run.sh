#!/usr/bin/env bash
# What a toolchain says when the std it loaded is not the std it shipped with
# (#226).
#
# The bug this replaces: every failure to load std, whatever the cause, came
# out as one sentence. On the native driver that sentence was `bundled std is
# broken`, which is wrong twice over. "Bundled" names two different things,
# because `std_read` prefers a directory and falls back to the copy compiled
# into the binary, and `std` relative to the working directory is the default
# `--std`; so a toolchain run inside somebody else's checkout loads their std
# without being asked to and then reports its own installation as corrupt.
#
# What is asserted here is the taxonomy: a directory stamped with another
# release is refused by its stamp before anything is parsed, a directory with
# no stamp is reported as unstamped rather than as a mismatch, both are the
# user's environment rather than a compiler bug, and none of that fires when
# `--std` simply points at nothing.
#
# Every assertion is owned by exactly one source mutant below, which must
# compile and run before it is judged. Two notes on the decomposition:
#
#   * whether a mismatch is reported at all is ASSERT_SKEW's business, and the
#     two assertions about the wording of that sentence are checked against the
#     sentence when there is one. That is deliberate: it is what lets the
#     mutant that deletes the check own "it is refused" without also owning
#     "the refusal reads well". Each wording assertion has its own mutant, so
#     neither is vacuous in general.
#   * ASSERT_FALLBACK owns nothing and is meant to. It is the control every
#     mutant has to keep green: a version check that also refuses a `--std`
#     pointing at an empty path would pass every other assertion here while
#     making the toolchain unusable.
#
# The embedded half cannot be reached by argument. A shipped binary carries the
# std it was compiled with, so the two can never be out of step, and a copy
# that fails to load really is a compiler bug. It is reached at the bottom by
# corrupting the embedded module in a private tree, which is the only situation
# in which the old sentence was telling the truth.
#
#   ./scripts/std-version-contract/run.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work=$(mktemp -d "${TMPDIR:-/tmp}/std-version-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

command -v python3 > /dev/null || fail "missing required command: python3"

# a built toolchain before anything is timed or run: a cold tree spends
# minutes here, and every failure below would read as the contract's
"$dawn" --version > /dev/null

version=$(sed -n 's/^pub const VERSION: String = "\(.*\)"$/\1/p' "$root/selfhost/src/version.dawn")
[ -n "$version" ] || fail "cannot read VERSION from selfhost/src/version.dawn"

# ---- subjects ---------------------------------------------------------------
#
# hello.dawn lives on its own so no subject is ever loaded from the working
# directory by accident; every run below names its std explicitly.

mkdir -p "$work/proj"
cat > "$work/proj/hello.dawn" <<'EOF'
pub fn main() -> Unit !io = { println("hello") }
EOF

# A std that would load, stamped with a release this toolchain is not, and
# carrying a module that does not parse. Both halves matter: the stamp is what
# should be reported, and the parse error is what would be reported instead if
# the comparison happened anywhere but first.
skew="$work/skew"
mkdir -p "$skew"
cp "$root"/std/*.dawn "$root/std/modules.txt" "$skew/"
printf '0.0.1-contract\n' > "$skew/VERSION"
printf '\npub fn contract_unparseable( = {\n' >> "$skew/str.dawn"

# A std with no stamp at all (every std published before the stamp existed,
# and every one assembled by hand), whose first module fails to check.
unstamped="$work/unstamped"
mkdir -p "$unstamped"
cp "$root"/std/*.dawn "$root/std/modules.txt" "$unstamped/"
printf '\npub fn contract_bad_type() -> Int = "not an Int"\n' >> "$unstamped/str.dawn"

# ---- assertions -------------------------------------------------------------
#
# Each prints exactly one `ASSERT: <sentence>` line when it fails and nothing
# when it holds, so a mutant is attributed to the sentence it broke.

ASSERT_SKEW='a std stamped with another release is refused by its stamp, not by its first symptom'
ASSERT_NAMES='the mismatch line names the std version and the toolchain version'
ASSERT_ACTION='the mismatch says which of the two to change'
ASSERT_ORIGIN='a directory failure names the directory it read'
ASSERT_UNSTAMPED='a directory with no stamp is reported as unstamped, not as a mismatch'
ASSERT_NOT_BUG='a directory failure exits as a user error, not as a compiler panic'
ASSERT_FALLBACK='a --std that holds no std still loads the copy compiled in'

## `check` against one std, capturing stdout, stderr and the exit code.
check_with_std() { # cli std_dir outfile
  local cli=$1 std_dir=$2 out=$3
  set +e
  "$cli" check --std "$std_dir" "$work/proj/hello.dawn" > "$out" 2>&1
  local status=$?
  set -e
  printf '%s' "$status" > "$out.status"
}

has() { grep -Fq "$2" "$1"; }

run_all_assertions() { # cli label
  local cli=$1 label=$2
  local skew_out="$work/$label.skew" un_out="$work/$label.unstamped" fb_out="$work/$label.fallback"

  check_with_std "$cli" "$skew" "$skew_out"
  check_with_std "$cli" "$unstamped" "$un_out"
  check_with_std "$cli" "$work/there-is-no-std-here" "$fb_out"

  # refused, and refused for the reason that is actually wrong with it
  if [ "$(cat "$skew_out.status")" = "0" ] ||
      ! has "$skew_out" 'std version mismatch' ||
      has "$skew_out" 'does not parse'; then
    printf 'ASSERT: %s\n' "$ASSERT_SKEW"
  fi

  # the wording of that sentence, when there is one
  if grep -F 'std version mismatch' "$skew_out" > "$work/$label.mismatch-line" 2>/dev/null; then
    if ! has "$work/$label.mismatch-line" '0.0.1-contract' ||
        ! has "$work/$label.mismatch-line" "$version"; then
      printf 'ASSERT: %s\n' "$ASSERT_NAMES"
    fi
    if ! has "$skew_out" "Use the $version std, or run the 0.0.1-contract toolchain."; then
      printf 'ASSERT: %s\n' "$ASSERT_ACTION"
    fi
  fi

  # the unstamped directory: named, diagnosed as unstamped, and not a panic
  if ! has "$un_out" "$unstamped"; then
    printf 'ASSERT: %s\n' "$ASSERT_ORIGIN"
  fi
  if ! has "$un_out" 'no VERSION stamp' || has "$un_out" 'std version mismatch'; then
    printf 'ASSERT: %s\n' "$ASSERT_UNSTAMPED"
  fi
  if [ "$(cat "$un_out.status")" != "2" ] ||
      ! has "$un_out" 'error: ' ||
      has "$un_out" 'panic: '; then
    printf 'ASSERT: %s\n' "$ASSERT_NOT_BUG"
  fi

  # the control: nothing above may cost a toolchain its embedded std
  if [ "$(cat "$fb_out.status")" != "0" ]; then
    printf 'ASSERT: %s\n' "$ASSERT_FALLBACK"
  fi
}

run_all_assertions "$dawn" subject > "$work/subject.assert"
if [ -s "$work/subject.assert" ]; then
  cat "$work/subject.assert" >&2
  echo "--- skew ---" >&2; cat "$work/subject.skew" >&2
  echo "--- unstamped ---" >&2; cat "$work/subject.unstamped" >&2
  echo "--- fallback ---" >&2; cat "$work/subject.fallback" >&2
  fail "the std load diagnostics do not hold"
fi
echo "PASS  std load diagnostics: version, directory and compiled-in copy are told apart"

# ---- mutants ----------------------------------------------------------------

mutate() {
  local name=$1 dir=$2
  python3 - "$name" "$dir/src/driver/stdlib.dawn" <<'PY'
from pathlib import Path
import sys

name, stdlib_name = sys.argv[1:]
path = Path(stdlib_name)
text = path.read_text()


def replace_once(old: str, new: str) -> None:
    global text
    if text.count(old) != 1:
        raise SystemExit(f"{name}: mutation anchor drifted: {old!r} ({text.count(old)} hits)")
    text = text.replace(old, new)


VERSION_CHECK = """  match declared {
    Some(v) ->
      if v != VERSION {
        return Err(StdLoadError { origin: origin, declared: declared, why: StdVersionSkew })
      }
    None -> ()
  }
"""

if name == "drop-version-check":
    replace_once(VERSION_CHECK, "")
elif name == "anonymous-toolchain":
    replace_once(
        '        "std version mismatch: " ++ head ++ " is " ++ said ++\n'
        '          ", this toolchain is " ++ VERSION,',
        '        "std version mismatch: " ++ head ++ " is " ++ said ++ ",",',
    )
elif name == "drop-skew-advice":
    replace_once(
        '        "  Use the " ++ VERSION ++ " std, or run the " ++ said ++ " toolchain."\n',
        "",
    )
    replace_once(
        '        "  a toolchain only ever checked the std it was released with.",',
        '        "  a toolchain only ever checked the std it was released with."',
    )
elif name == "anonymous-dir":
    replace_once(
        '    StdFromDir(d) -> "the std in " ++ located(d)',
        '    StdFromDir(_) -> "the std"',
    )
elif name == "absent-stamp-means-current":
    replace_once(
        '    Ok(t) -> Some(str.trim(t))\n    Err(_) -> None\n  }',
        "    Ok(t) -> Some(str.trim(t))\n    Err(_) -> Some(VERSION)\n  }",
    )
elif name == "every-failure-is-a-bug":
    replace_once(
        "pub fn std_load_is_bug(e: StdLoadError) -> Bool =\n"
        "  match e.origin {\n"
        "    StdEmbedded -> true\n"
        "    StdFromDir(_) -> false\n"
        "  }",
        "pub fn std_load_is_bug(_e: StdLoadError) -> Bool = true",
    )
else:
    raise SystemExit(f"unknown mutation: {name}")

path.write_text(text)
PY
}

## Build a private compiler from a mutated copy of the tree, then judge it by
## the same assertion set the subject went through. `owns` is the sentence only
## this mutant breaks; ASSERT_FALLBACK is the control every one of them keeps.
check_mutant() {
  local name=$1 owns=$2
  local dir="$work/mutant-$name"
  mkdir -p "$dir"
  cp -R "$root/selfhost" "$dir/selfhost"
  cp -R "$root/compiler-plan" "$dir/compiler-plan"
  ln -s "$root/packages" "$dir/packages"
  mutate "$name" "$dir/selfhost"

  if ! "$dawn" build "$dir/selfhost" -o "$dir/compiler.jar" > "$dir/build.out" 2>&1; then
    cat "$dir/build.out" >&2
    fail "$name mutant did not compile"
  fi

  printf '#!/bin/sh\nexec java -Xss512m -Xmx2g -jar "%s" "$@"\n' "$dir/compiler.jar" > "$dir/cli"
  chmod +x "$dir/cli"

  run_all_assertions "$dir/cli" "$name" > "$dir/assert"
  if ! grep -Fxq "ASSERT: $owns" "$dir/assert"; then
    cat "$dir/assert" >&2
    fail "$name mutant did not turn its owning assertion red: $owns"
  fi
  if grep -Fxq "ASSERT: $ASSERT_FALLBACK" "$dir/assert"; then
    cat "$dir/assert" >&2
    fail "$name mutant also broke the control assertion: $ASSERT_FALLBACK"
  fi
  if [ "$(wc -l < "$dir/assert")" -ne 1 ]; then
    cat "$dir/assert" >&2
    fail "$name mutant reddened more than the assertion it owns"
  fi
  echo "PASS  $name compiles, then reds: $owns"
}

check_mutant drop-version-check "$ASSERT_SKEW"
check_mutant anonymous-toolchain "$ASSERT_NAMES"
check_mutant drop-skew-advice "$ASSERT_ACTION"
check_mutant anonymous-dir "$ASSERT_ORIGIN"
check_mutant absent-stamp-means-current "$ASSERT_UNSTAMPED"
check_mutant every-failure-is-a-bug "$ASSERT_NOT_BUG"

# ---- the compiled-in copy ---------------------------------------------------
#
# No argument reaches this arm: a binary's embedded std is compiled in beside
# the compiler that reads it. Corrupting the embedded module is what makes it
# reachable, and the answer has to be the opposite of every assertion above --
# this one really is the compiler's fault, and says so.

probe="$work/embedded"
mkdir -p "$probe"
cp -R "$root/selfhost" "$probe/selfhost"
cp -R "$root/compiler-plan" "$probe/compiler-plan"
ln -s "$root/packages" "$probe/packages"
python3 - "$probe/selfhost/src/embed/stdsrc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
anchor = '  if name == "modules.txt" {'
if text.count(anchor) != 1:
    raise SystemExit(f"embedded probe: anchor drifted: {anchor!r} ({text.count(anchor)} hits)")
path.write_text(text.replace(anchor, '  if name == "modules.txt-corrupted-by-the-probe" {'))
PY

if ! "$dawn" build "$probe/selfhost" -o "$probe/compiler.jar" > "$probe/build.out" 2>&1; then
  cat "$probe/build.out" >&2
  fail "the embedded-std probe did not compile"
fi
set +e
java -Xss512m -Xmx2g -jar "$probe/compiler.jar" check --std "$work/there-is-no-std-here" \
  "$work/proj/hello.dawn" > "$probe/out" 2>&1
probe_status=$?
set -e
if [ "$probe_status" -eq 0 ] ||
    ! has "$probe/out" 'the std compiled into this toolchain does not load' ||
    ! has "$probe/out" "This is a bug in dawn $version"; then
  cat "$probe/out" >&2
  fail "a corrupt compiled-in std was not reported as a compiler bug"
fi
echo "PASS  a corrupt compiled-in std is the one case that is the compiler's fault"

echo "std-version-contract: OK"

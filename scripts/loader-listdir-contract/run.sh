#!/usr/bin/env bash
# A source directory the loader cannot list must not be taken for an empty one.
#
#   ./scripts/loader-listdir-contract/run.sh
#
# Its own gates.yml step, in the java-member-dispatch job (lsp-workspace, where
# it first sat beside project-plan-contract, had no room for its ~55s).
#
# #759: `walk_sources` answered a directory it could not list with `[]`, so with
# `src/hidden` at mode 000 `dawn check` printed `ok`, `dawn test` passed with
# the tests there never run, and `dawn doc` left the module out. Spec §10.5 says
# a project check covers every module under `src`. This drives the CLI over a
# real unreadable directory, which is the only way to get the host's own refusal
# rather than one the test wrote itself.
#
# What is asserted, and why each half exists:
#
#   control    -- the same tree at mode 755: `check` reports the type error and
#                 `test` reports the failing test. Without it a red result below
#                 could be the fixture being broken rather than the directory.
#   refusal    -- at mode 000, `check`, `test`, `doc` and `build` all exit nonzero
#                 and name the directory, and the language server publishes the
#                 same diagnostic on it (lsp.py).
#   file mode  -- a single file named on the command line never depended on the
#                 walk, so the unreadable sibling is none of its business.
#   mutants    -- the walk answering with nothing again, built into a private
#                 compiler, which must turn the refusal lines and the server red
#                 and leave the readable control alone.
#
# It refuses to run as root: root reads a mode-000 directory, so the case could
# not fail, and a check that cannot fail is worse than none.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/loader-listdir-contract"
work="$(mktemp -d)"
trap 'chmod -R u+rwX "$work" 2>/dev/null || true; rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if [ "$(id -u)" = 0 ]; then
  fail "this contract must not run as root: a mode-000 directory is readable by root"
fi

project() { # dir -- a project with one clean module and src/hidden
  local d="$1"
  rm -rf "$d"
  mkdir -p "$d/src/hidden"
  # The manifest matters to the language server: a directory without one is
  # where a loose file sits, and its other files are not one program with it.
  printf 'schema = 1\nname = "listdir_fixture"\n' > "$d/dawn.toml"
  printf 'pub fn main() -> Unit !io = ()\n\ntest "visible pass" {\n  assert true\n}\n' > "$d/src/main.dawn"
  printf 'fn bad() -> Int = "bad"\n\ntest "hidden fail" {\n  assert false\n}\n' > "$d/src/hidden/bad.dawn"
}

# run <expect-exit: zero|nonzero> <label> <bin> <args...>; output in $work/last.out
run() {
  local want="$1" label="$2"
  shift 2
  local rc=0
  "$@" > "$work/last.out" 2>&1 || rc=$?
  if [ "$want" = zero ] && [ "$rc" != 0 ]; then
    cat "$work/last.out" >&2
    fail "$label: expected exit 0, got $rc"
  fi
  if [ "$want" = nonzero ] && [ "$rc" = 0 ]; then
    cat "$work/last.out" >&2
    fail "$label: expected a nonzero exit"
  fi
}

# probe <dawn-cmd...>: the whole CLI matrix against one compiler, as lines.
probe() {
  local out="$1"
  shift
  : > "$out"
  local p="$work/proj" cmd rc
  project "$p"
  # control: readable
  for cmd in check test; do
    rc=0
    "$@" "$cmd" "$p" > "$work/last.out" 2>&1 || rc=$?
    echo "readable $cmd exit nonzero = $([ "$rc" != 0 ] && echo true || echo false)" >> "$out"
  done
  grep -q 'hidden' "$work/last.out" && echo "readable test saw hidden = true" >> "$out" ||
    echo "readable test saw hidden = false" >> "$out"
  # refusal: unreadable
  project "$p"
  chmod 000 "$p/src/hidden"
  for cmd in check test doc build; do
    rc=0
    case "$cmd" in
      build) "$@" build "$p" -o "$work/out.jar" > "$work/last.out" 2>&1 || rc=$? ;;
      *) "$@" "$cmd" "$p" > "$work/last.out" 2>&1 || rc=$? ;;
    esac
    echo "unreadable $cmd exit nonzero = $([ "$rc" != 0 ] && echo true || echo false)" >> "$out"
    echo "unreadable $cmd names directory = $(
      grep -Fq "$p/src/hidden" "$work/last.out" && echo true || echo false)" >> "$out"
    echo "unreadable $cmd says cannot list = $(
      grep -Fq 'cannot list source directory' "$work/last.out" && echo true || echo false)" >> "$out"
  done
  # file mode: the sibling is not part of a one-file check
  rc=0
  "$@" check "$p/src/main.dawn" > "$work/last.out" 2>&1 || rc=$?
  echo "unreadable file-mode check exit = $rc" >> "$out"
  chmod 755 "$p/src/hidden"
}

private_compiler() { # name [mutation] -- a private selfhost jar, optionally mutated
  local name="$1" mutation="${2:-}" dir="$work/build-$1"
  rm -rf "$dir"
  mkdir -p "$dir"
  cp -R "$root/selfhost" "$dir/selfhost"
  cp -R "$root/compiler-plan" "$dir/compiler-plan"
  ln -s "$root/packages" "$dir/packages"
  [ -z "$mutation" ] || python3 "$here/mutate.py" "$mutation" "$dir"
  "$root/bin/dawn" build "$dir/selfhost" -o "$dir/compiler.jar" --std "$root/std" \
    --vendor org/objectweb/asm --vendor coursierapi > "$dir/build.out" 2>&1 ||
    { cat "$dir/build.out" >&2; fail "$name private selfhost did not compile"; }
  CJAR="$dir/compiler.jar"
}

jar_cmd() { # jar
  CMD=(env DAWN_SELFHOST_CP= java -Xss512m -Xmx2g -jar "$1")
}

private_compiler baseline
jar_cmd "$CJAR"
BASE_JAR="$CJAR"
probe "$work/base.out" "${CMD[@]}"
cmp -s "$here/expected.txt" "$work/base.out" || {
  diff -u "$here/expected.txt" "$work/base.out" >&2 || true
  fail "the loader does not behave as the contract says"
}
echo "PASS  check, test, doc and build refuse an unreadable source directory, naming it"

p="$work/lsp-proj"
project "$p"
chmod 000 "$p/src/hidden"
python3 -I "$here/lsp.py" "${CMD[@]}" lsp "$p" || fail "the language server stayed silent about an unreadable directory"
chmod 755 "$p/src/hidden"
echo "PASS  the language server publishes the same diagnostic on the directory"

# Mutants. `walk-silent` is the original bug; it must turn every refusal line
# red and leave the readable control alone.
expect_red() { # label, out, owned-prefix, untouched-prefix
  cmp -s "$here/expected.txt" "$2" && fail "$1 mutant stayed green"
  diff <(grep "^$3" "$here/expected.txt") <(grep "^$3" "$2") > /dev/null &&
    { diff -u "$here/expected.txt" "$2" >&2 || true; fail "$1 mutant did not move its '$3' lines"; }
  diff <(grep "^$4" "$here/expected.txt") <(grep "^$4" "$2") > /dev/null ||
    { diff -u "$here/expected.txt" "$2" >&2 || true; fail "$1 mutant also moved the '$4' lines"; }
  echo "PASS  mutant: $1 (the '$3' lines turned red; the '$4' lines did not move)"
}

private_compiler walk-silent walk-silent
jar_cmd "$CJAR"
probe "$work/m-walk.out" "${CMD[@]}"
expect_red "unlistable directory answered with nothing" "$work/m-walk.out" 'unreadable ' 'readable '
p="$work/lsp-proj-m"
project "$p"
chmod 000 "$p/src/hidden"
if python3 -I "$here/lsp.py" "${CMD[@]}" lsp "$p" > /dev/null 2>&1; then
  chmod 755 "$p/src/hidden"
  fail "walk-silent mutant stayed green in the language server"
fi
chmod 755 "$p/src/hidden"
echo "PASS  mutant: the language server goes silent with the walk (lsp.py turned red)"

# The other half, a file that was listed and then cannot be read, is owned by
# the tree-local test "a listed file that vanishes before the load" in
# driver/analyze.dawn (`dawn test selfhost`). Its mutant, which skips such a
# file again, was run by hand when it was written and turns that test red; it is
# not rebuilt here because a full `dawn test selfhost` costs about a minute.

echo "OK: loader-listdir contract, one control, four commands, the server, and two mutants"

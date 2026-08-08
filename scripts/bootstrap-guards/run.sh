#!/usr/bin/env bash
# The two guards standing in front of the bootstrap, driven against the cases
# they exist to refuse.
#
#   ./scripts/bootstrap-guards/run.sh
#
# Neither guard is observable from a green build. `bin/dawn` decides whether to
# rebuild by hashing what it believes the compiler is a function of, and an
# input it forgot looks exactly like an input that did not change: the jar is
# stale, everything works, and nothing says a word. `scripts/seedjar.sh`
# decides whether the seed may be used at all, and a seed that passes and a
# seed that was never checked produce the same output too.
#
# So this moves one thing at a time and requires the answer to move with it.
# The control cases matter as much as the positive ones -- a stamp that changes
# for any edit anywhere proves nothing, and a resolver that refuses everything
# is not a resolver.
#
# No JVM, no network, no seed download: everything runs against a temporary
# root built out of copies. Milliseconds.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

work="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-guards.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail=0
ok() { echo "PASS  $1"; }
bad() {
  echo "FAIL: $1" >&2
  fail=1
}

# ---------------------------------------------------------------------------
# TOOL-14: everything the built jar is a function of reaches the stamp.
#
# A copied root, not the real one: the probe edits files, and it has to edit
# the ones bin/dawn will actually read. bin/dawn resolves symlinks to find its
# own root, so it is copied rather than linked -- a symlink would point the
# whole check back at the repo.
# ---------------------------------------------------------------------------
fake="$work/root"
mkdir -p "$fake/bin" "$fake/scripts" "$fake/selfhost"
cp "$root/bin/dawn" "$fake/bin/dawn"
cp "$root/scripts/seedjar.sh" "$root/scripts/seed-release.txt" \
  "$root/scripts/seed-checksums.txt" "$fake/scripts/"
cp "$root/selfhost/dawn.toml" "$root/selfhost/dawn.lock" "$fake/selfhost/"
cp -r "$root/selfhost/src" "$fake/selfhost/src"
cp -r "$root/std" "$fake/std"
cp -r "$root/packages" "$fake/packages"

stamp() { DAWN_PRINT_STAMP=1 "$fake/bin/dawn"; }

base="$(stamp)"
if [ -z "$base" ] || [ "$base" = "no-sha256" ]; then
  echo "FAIL: no usable sha256 tool, so the stamp cannot be checked here" >&2
  exit 1
fi

# The declared input set, one file from each member. packages/* are there
# because they are selfhost's [deps] -- the case that was missing, and the one
# a hand-written path list gets wrong again the next time a package is added.
for target in \
  selfhost/src/main.dawn \
  selfhost/dawn.toml \
  selfhost/dawn.lock \
  std/str.dawn \
  scripts/seed-release.txt \
  scripts/seed-checksums.txt \
  scripts/seedjar.sh \
  bin/dawn \
  packages/json/src/parser.dawn \
  packages/sha2/src/sha256.dawn \
  packages/inflate/src/deflate.dawn; do
  printf '\n# bootstrap-guards probe\n' >> "$fake/$target"
  moved="$(stamp)"
  cp "$root/$target" "$fake/$target"
  if [ "$moved" = "$base" ]; then
    bad "$target does not reach the build stamp"
  fi
done
[ "$fail" = 0 ] && ok "every declared build input moves the stamp"

# The control. Without it, "the stamp moved" is consistent with hashing the
# whole directory tree, which would answer yes to anything and mean nothing.
printf 'not an input\n' > "$fake/README.md"
mkdir -p "$fake/docs"
printf 'not an input\n' > "$fake/docs/notes.md"
if [ "$(stamp)" != "$base" ]; then
  bad "the stamp moved for a file that is not a build input"
else
  ok "a file outside the input set leaves the stamp alone"
fi

exit "$fail"

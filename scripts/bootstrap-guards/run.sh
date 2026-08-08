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
  "$root/scripts/seed-checksums.txt" "$root/scripts/seed-std-checksums.txt" "$fake/scripts/"
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
  scripts/seed-std-checksums.txt \
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

# ---------------------------------------------------------------------------
# TOOL-16: the seed resolver is fail-closed.
#
# Its preconditions -- a recorded digest for the pinned tag, a hasher on PATH
# -- used to warn and return 0 when absent, so the one occurrence that mattered
# (bump seed-release.txt, forget to add the digest) turned the gate off for
# every build and every CI job while looking like a release omission.
#
# Driven through a root of its own with a pre-filled cache, so nothing here
# downloads anything.
# ---------------------------------------------------------------------------
sroot="$work/seedroot"
mkdir -p "$sroot/scripts" "$sroot/.dawn/seeds/v9.9.9"
cp "$root/scripts/seedjar.sh" "$sroot/scripts/"
printf 'v9.9.9\n' > "$sroot/scripts/seed-release.txt"
printf 'this is the seed jar\n' > "$sroot/.dawn/seeds/v9.9.9/seed.jar"
want=$(sha256sum "$sroot/.dawn/seeds/v9.9.9/seed.jar" | cut -d' ' -f1)

# resolve the seed in a subshell so an `exit 1` inside it stops there
try_seed() { # -> exit code, output in $work/seed.txt
  (
    ROOT="$sroot"
    export ROOT
    # shellcheck disable=SC1091
    . "$sroot/scripts/seedjar.sh"
    seed_jar
  ) > "$work/seed.txt" 2>&1
}

printf '%s  v9.9.9\n' "$want" > "$sroot/scripts/seed-checksums.txt"
if try_seed && [ "$(cat "$work/seed.txt")" = "$sroot/.dawn/seeds/v9.9.9/seed.jar" ]; then
  ok "a cached seed with a matching digest resolves"
else
  bad "the resolver refused a seed that matches its recorded digest"
  sed 's/^/  | /' "$work/seed.txt" >&2
fi

printf '%064d  v9.9.9\n' 0 > "$sroot/scripts/seed-checksums.txt"
if try_seed; then
  bad "a seed whose digest does not match was used anyway"
else
  ok "a seed whose digest does not match is refused"
fi

: > "$sroot/scripts/seed-checksums.txt"
if try_seed; then
  bad "a seed with no recorded digest was used anyway (fail-open)"
  sed 's/^/  | /' "$work/seed.txt" >&2
else
  ok "a seed with no recorded digest is refused"
fi

if DAWN_SEED_ALLOW_UNVERIFIED=1 try_seed; then
  ok "DAWN_SEED_ALLOW_UNVERIFIED re-opens the unrecorded case"
else
  bad "the opt-out does not opt out"
  sed 's/^/  | /' "$work/seed.txt" >&2
fi

# No hasher: the other precondition, and the other thing that used to warn and
# continue. seed_sha_of is redefined rather than PATH emptied -- an empty PATH
# also breaks the awk that reads the table, which would make this pass for the
# wrong reason.
printf '%s  v9.9.9\n' "$want" > "$sroot/scripts/seed-checksums.txt"
if (
  ROOT="$sroot"
  export ROOT
  # shellcheck disable=SC1091
  . "$sroot/scripts/seedjar.sh"
  seed_sha_of() { echo ""; }
  seed_jar
) > "$work/seed.txt" 2>&1; then
  bad "a seed was used on a machine with no way to hash it"
else
  ok "no way to hash the seed is refused rather than warned about"
fi

# ---------------------------------------------------------------------------
# TOOL-15: the seed's std is verified on the same terms as its jar.
#
# It used to be verified on no terms at all: `modules.txt` exists, use it. Both
# are stage-1 inputs and the cache is a writable directory, so half the
# bootstrap could be swapped with the jar checksum still green.
# ---------------------------------------------------------------------------
mkdir -p "$sroot/.dawn/seeds/std-v9.9.9"
printf 'str\n' > "$sroot/.dawn/seeds/std-v9.9.9/modules.txt"
printf 'pub fn f() -> Int = 1\n' > "$sroot/.dawn/seeds/std-v9.9.9/str.dawn"
std_want=$(
  ROOT="$sroot"
  export ROOT
  # shellcheck disable=SC1091
  . "$sroot/scripts/seedjar.sh"
  seed_tree_sha "$sroot/.dawn/seeds/std-v9.9.9"
)

try_std() { # -> exit code, output in $work/std.txt
  (
    ROOT="$sroot"
    export ROOT
    # shellcheck disable=SC1091
    . "$sroot/scripts/seedjar.sh"
    seed_std_dir
  ) > "$work/std.txt" 2>&1
}

printf '%s  v9.9.9\n' "$std_want" > "$sroot/scripts/seed-std-checksums.txt"
if try_std && [ "$(cat "$work/std.txt")" = "$sroot/.dawn/seeds/std-v9.9.9" ]; then
  ok "a cached seed std with a matching tree hash resolves"
else
  bad "the resolver refused a seed std that matches its recorded hash"
  sed 's/^/  | /' "$work/std.txt" >&2
fi

# The whole point: a writable cache directory. Edit one byte of it.
printf 'pub fn f() -> Int = 2\n' > "$sroot/.dawn/seeds/std-v9.9.9/str.dawn"
if try_std; then
  bad "an edited seed std was used anyway"
  sed 's/^/  | /' "$work/std.txt" >&2
else
  ok "an edited seed std is refused"
fi
printf 'pub fn f() -> Int = 1\n' > "$sroot/.dawn/seeds/std-v9.9.9/str.dawn"

# A file *added* to the tree, which a per-file check would miss and a tree
# hash cannot.
printf 'extra\n' > "$sroot/.dawn/seeds/std-v9.9.9/extra.dawn"
if try_std; then
  bad "a file added to the seed std went unnoticed"
else
  ok "a file added to the seed std is refused"
fi
rm -f "$sroot/.dawn/seeds/std-v9.9.9/extra.dawn"

: > "$sroot/scripts/seed-std-checksums.txt"
if try_std; then
  bad "a seed std with no recorded hash was used anyway (fail-open)"
  sed 's/^/  | /' "$work/std.txt" >&2
else
  ok "a seed std with no recorded hash is refused"
fi

exit "$fail"

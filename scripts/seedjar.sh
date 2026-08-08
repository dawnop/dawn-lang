# Shared seed-jar resolver, sourced by bin/dawn and the golden-diff scripts.
# The bootstrap seed is the previous release's dawn-selfhost.jar, named by
# scripts/seed-release.txt and cached under .dawn/seeds/ (override the cache
# with DAWN_SEED_CACHE, or point DAWN_SEED at a local jar to skip the
# download entirely — the escape hatch for offline work and seed debugging).
#
# Every seed is checked against scripts/seed-checksums.txt before it is used,
# not merely after it is downloaded. This used to fetch over HTTPS, cache the
# result forever and trust it from then on — so a replaced release asset, a
# corrupted transfer or an edited cache file would swap out the compiler that
# builds every other line of Dawn here, silently. The fixed point cannot catch
# that: B == C proves the compiler reproduces itself, which a substituted
# compiler does just as faithfully.
#
# No `local`: this file is sourced by `#!/bin/sh` scripts and `local` is not
# POSIX. Locals are spelled as prefixed names instead.

## The recorded sha256 for a tag; empty when the tag is not listed.
seed_expected_sha() {
  awk -v tag="$1" '$1 !~ /^#/ && $2 == tag { print $1; exit }' \
    "$ROOT/scripts/seed-checksums.txt" 2>/dev/null
}

seed_sha_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    echo ""
  fi
}

seed_sha_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | cut -d' ' -f1
  else
    echo ""
  fi
}

## A canonical hash of a directory tree: every regular file, sorted by relative
## path, each contributing its size, its path and its bytes. Length-prefixing
## the content is what stops two different trees from concatenating to the same
## stream. LC_ALL fixes the collation so the same tree hashes the same
## everywhere.
##
## The same shape as the compiler's `d1` package hash, in shell, because this
## runs before there is a compiler.
seed_tree_sha() {
  (
    cd "$1" 2>/dev/null || exit 0
    find . -type f | LC_ALL=C sort |
      while IFS= read -r f; do
        printf '%s %s\n' "$(wc -c < "$f" | tr -d ' ')" "$f"
        cat "$f"
      done
  ) | seed_sha_stdin
}

## The opt-out, for the two cases that genuinely cannot verify: replaying a
## pre-v0.8.0 tag, whose published asset was the Kotlin dawn.jar and is
## deliberately absent from the table, and a machine with no SHA-256 tool.
##
## It has to be spelled out, and that is the whole change. Both cases used to
## take the default path: a warning on stderr, exit 0, and a bootstrap from an
## unverified compiler. So the one occurrence that mattered -- bumping
## seed-release.txt to a new tag and forgetting to add its digest -- silently
## turned the gate off for every build and every CI job, and looked like a
## release omission rather than the loss of the trust root that it was.
seed_unverified_ok() { [ -n "${DAWN_SEED_ALLOW_UNVERIFIED:-}" ]; }

seed_refuse() {
  echo "error: $1" >&2
  echo "  This is the compiler that builds every other line of Dawn here, and" >&2
  echo "  a bootstrap that cannot check it is not one this will run." >&2
  echo "  Record the digest in scripts/seed-checksums.txt (the release workflow" >&2
  echo "  prints the line), or set DAWN_SEED_ALLOW_UNVERIFIED=1 to go ahead" >&2
  echo "  without one." >&2
  exit 1
}

## Verify $1 against the recorded hash for tag $2. A mismatch is fatal — at that
## point the only choices are to stop or to run an unknown compiler. So is a
## missing precondition: no recorded hash and no hasher are both "this was not
## checked", which is the state the check exists to prevent.
seed_verify() {
  _sv_want=$(seed_expected_sha "$2")
  if [ -z "$_sv_want" ]; then
    if seed_unverified_ok; then
      echo "warning: no recorded sha256 for seed $2, proceeding unverified" >&2
      echo "  (DAWN_SEED_ALLOW_UNVERIFIED is set)" >&2
      return 0
    fi
    seed_refuse "no recorded sha256 for seed $2 (scripts/seed-checksums.txt)"
  fi
  _sv_got=$(seed_sha_of "$1")
  if [ -z "$_sv_got" ]; then
    if seed_unverified_ok; then
      echo "warning: no sha256sum/shasum on PATH, seed $2 unverified" >&2
      return 0
    fi
    seed_refuse "no sha256sum or shasum on PATH, so seed $2 cannot be verified"
  fi
  if [ "$_sv_got" != "$_sv_want" ]; then
    echo "error: seed $2 failed checksum verification" >&2
    echo "  expected $_sv_want" >&2
    echo "  actual   $_sv_got" >&2
    echo "  file     $1" >&2
    echo "  This is the compiler that builds everything else; refusing to use it." >&2
    exit 1
  fi
}

seed_jar() {
  # An explicitly pointed-at jar is the debugging escape hatch: it is not the
  # pinned release, so there is nothing to check it against. Say so rather than
  # let it pass as if it had been verified.
  if [ -n "${DAWN_SEED:-}" ]; then
    echo "warning: using DAWN_SEED=$DAWN_SEED (unverified)" >&2
    echo "$DAWN_SEED"
    return
  fi
  _sj_tag=$(tr -d ' \n' < "$ROOT/scripts/seed-release.txt")
  _sj_cache=${DAWN_SEED_CACHE:-$ROOT/.dawn/seeds}/$_sj_tag
  if [ ! -f "$_sj_cache/seed.jar" ]; then
    mkdir -p "$_sj_cache"
    echo "fetching $_sj_tag seed jar..." >&2
    curl -fsSL -o "$_sj_cache/seed.jar.tmp" \
      "https://github.com/dawnop/dawn-lang/releases/download/$_sj_tag/dawn-selfhost.jar"
    # verified before it is promoted to the cache, so a bad download cannot
    # become the copy every later run trusts
    seed_verify "$_sj_cache/seed.jar.tmp" "$_sj_tag"
    mv "$_sj_cache/seed.jar.tmp" "$_sj_cache/seed.jar"
  else
    # and again on every cache hit — the cache is a mutable directory on disk
    seed_verify "$_sj_cache/seed.jar" "$_sj_tag"
  fi
  echo "$_sj_cache/seed.jar"
}

## The recorded tree hash for a tag's std; empty when the tag is not listed.
seed_std_expected_sha() {
  awk -v tag="$1" '$1 !~ /^#/ && $2 == tag { print $1; exit }' \
    "$ROOT/scripts/seed-std-checksums.txt" 2>/dev/null
}

## Verify the std tree at $1 against the recorded hash for tag $2, on the same
## terms as the jar: every use, and fail-closed when the check cannot be made.
##
## The jar was checked and the std it pairs with was not — `modules.txt` exists,
## use it. Both are stage-1 inputs, the cache directory is writable, and a tag
## can be moved, so half the bootstrap could be swapped with the jar's checksum
## and the whole trust narrative none the wiser. B == C cannot see it either:
## a substituted std reproduces into the next generation as faithfully as
## anything else.
seed_std_verify() {
  _sd_want=$(seed_std_expected_sha "$2")
  if [ -z "$_sd_want" ]; then
    if seed_unverified_ok; then
      echo "warning: no recorded tree hash for the std of seed $2, proceeding unverified" >&2
      return 0
    fi
    seed_refuse "no recorded tree hash for the std of seed $2 (scripts/seed-std-checksums.txt)"
  fi
  _sd_got=$(seed_tree_sha "$1")
  if [ -z "$_sd_got" ]; then
    if seed_unverified_ok; then
      echo "warning: no sha256sum/shasum on PATH, the std of seed $2 is unverified" >&2
      return 0
    fi
    seed_refuse "no sha256sum or shasum on PATH, so the std of seed $2 cannot be verified"
  fi
  if [ "$_sd_got" != "$_sd_want" ]; then
    echo "error: the std of seed $2 failed verification" >&2
    echo "  expected $_sd_want" >&2
    echo "  actual   $_sd_got" >&2
    echo "  tree     $1" >&2
    echo "  This is half of what builds the compiler that builds everything" >&2
    echo "  else; refusing to use it. Delete the directory and re-run to" >&2
    echo "  re-extract it from the tag." >&2
    exit 1
  fi
}

## The std the pinned seed released with, extracted from its git tag and
## cached beside the jar. The seed pairs with the std it shipped: since #44
## knife 2 the repo's std may use prelude machinery (the Iter trait) that is
## one generation ahead of the seed's checker, so handing the seed today's
## std/ is handing it modules it cannot check. The released pair is also the
## honest reference — it is the combination that release's gates actually ran.
seed_std_dir() {
  _ss_tag=$(tr -d ' \n' < "$ROOT/scripts/seed-release.txt")
  _ss_dir=${DAWN_SEED_CACHE:-$ROOT/.dawn/seeds}/std-$_ss_tag
  if [ ! -f "$_ss_dir/modules.txt" ]; then
    # A fresh CI checkout is shallow and tagless (actions/checkout defaults:
    # depth 1, no tags), so the seed's tag is usually absent there. Fetch just
    # that tag before asking archive for it; offline with the tag already
    # present never reaches the fetch.
    git -C "$ROOT" rev-parse -q --verify "refs/tags/$_ss_tag" > /dev/null ||
      git -C "$ROOT" fetch -q --depth 1 origin tag "$_ss_tag" || true
    rm -rf "$_ss_dir.tmp"
    mkdir -p "$_ss_dir.tmp"
    git -C "$ROOT" archive "$_ss_tag" std | tar -x -C "$_ss_dir.tmp" || {
      echo "error: cannot extract std/ from tag $_ss_tag (the seed's released std)" >&2
      echo "  the tag is not in this clone, and fetching it from origin failed" >&2
      exit 1
    }
    # verified while it is still staged, so a bad extract never becomes the
    # copy every later run trusts — the jar's rule, applied to its other half
    seed_std_verify "$_ss_dir.tmp/std" "$_ss_tag"
    rm -rf "$_ss_dir"
    mv "$_ss_dir.tmp/std" "$_ss_dir"
    rm -rf "$_ss_dir.tmp"
  else
    # and again on every cache hit — the cache is a mutable directory on disk
    seed_std_verify "$_ss_dir" "$_ss_tag"
  fi
  echo "$_ss_dir"
}

## A working root for seed subcommands that read `std` from the cwd and take
## no --std flag (lsp) or take many shapes of argument (the run-diff sweep):
## every top-level repo entry symlinked in place, except std, which is the
## seed's released std. Relative targets resolve unchanged; only the std the
## seed sees moves back one generation.
seed_root() {
  _sr_dir=$1
  _sr_std=$(seed_std_dir)
  mkdir -p "$_sr_dir"
  for _sr_e in "$ROOT"/* "$ROOT"/.dawn; do
    [ -e "$_sr_e" ] || continue
    _sr_b=$(basename "$_sr_e")
    [ "$_sr_b" = "std" ] && continue
    [ -e "$_sr_dir/$_sr_b" ] || ln -s "$_sr_e" "$_sr_dir/$_sr_b"
  done
  ln -s "$_sr_std" "$_sr_dir/std"
}

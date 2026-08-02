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

## Verify $1 against the recorded hash for tag $2. A mismatch is fatal — at that
## point the only choices are to stop or to run an unknown compiler.
seed_verify() {
  _sv_want=$(seed_expected_sha "$2")
  if [ -z "$_sv_want" ]; then
    echo "warning: no recorded sha256 for seed $2 (scripts/seed-checksums.txt)" >&2
    return 0
  fi
  _sv_got=$(seed_sha_of "$1")
  if [ -z "$_sv_got" ]; then
    echo "warning: no sha256sum/shasum on PATH, seed $2 unverified" >&2
    return 0
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
    mkdir -p "$_ss_dir.tmp"
    git -C "$ROOT" archive "$_ss_tag" std | tar -x -C "$_ss_dir.tmp" || {
      echo "error: cannot extract std/ from tag $_ss_tag (the seed's released std)" >&2
      echo "  the tag is not in this clone, and fetching it from origin failed" >&2
      exit 1
    }
    rm -rf "$_ss_dir"
    mv "$_ss_dir.tmp/std" "$_ss_dir"
    rm -rf "$_ss_dir.tmp"
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

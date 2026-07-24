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

# Shared seed-jar resolver, sourced by bin/dawn and the golden-diff scripts.
# The bootstrap seed is the previous release's dawn-selfhost.jar, named by
# scripts/seed-release.txt and cached under .dawn/seeds/ (override the cache
# with DAWN_SEED_CACHE, or point DAWN_SEED at a local jar to skip the
# download entirely — the escape hatch for offline work and seed debugging).
seed_jar() {
  if [ -n "${DAWN_SEED:-}" ]; then
    echo "$DAWN_SEED"
    return
  fi
  local tag cache
  tag=$(tr -d ' \n' < "$ROOT/scripts/seed-release.txt")
  cache=${DAWN_SEED_CACHE:-$ROOT/.dawn/seeds}/$tag
  if [ ! -f "$cache/seed.jar" ]; then
    mkdir -p "$cache"
    echo "fetching $tag seed jar..." >&2
    curl -fsSL -o "$cache/seed.jar.tmp" \
      "https://github.com/dawnop/dawn-lang/releases/download/$tag/dawn-selfhost.jar"
    mv "$cache/seed.jar.tmp" "$cache/seed.jar"
  fi
  echo "$cache/seed.jar"
}

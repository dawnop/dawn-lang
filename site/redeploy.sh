#!/usr/bin/env bash
# Build the site and push to production.
# Prerequisites: SSH key loaded, user added to dawnop.com's known_hosts,
# DEPLOY_USER set to the server login name (not committed: public repo).
#
# The wasm half is why this is more than build-then-rsync (#319). site/build.sh
# treats a missing wasm toolchain as a warning, on purpose: CI has none and the
# rest of the site must still build there. The generator then writes
# placeholder text where the three reactors go, and the Demo page's two demos
# and every page's search panel stop working. That is the right trade for a
# build and the wrong one for a deploy, so this script holds the line the build
# does not: the deploying machine defaults to the compiler known to work
# (clang 18 crashes on the exception tag every reactor carries), and nothing is
# rsynced unless all three reactors were rebuilt by this run and are real wasm.
#
# "Rebuilt by this run", not just "present": site/build/ is not cleaned between
# builds, and build.sh only deletes a reactor whose own build failed. With no
# toolchain at all it skips the step and leaves whatever an older build left,
# so a reactor from last month would pass a presence check. The stamp below is
# what tells the two apart.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DEPLOY_USER:?set DEPLOY_USER to the server login name}@dawnop.com"
export DAWN_WASM_CC="${DAWN_WASM_CC:-clang-20}"
# The public origin, named once in scripts/repo.env (DAWN_SITE_ORIGIN in the
# environment wins). It is what the CDN purge refreshes and what this prints.
site_origin="${DAWN_SITE_ORIGIN:-$(. scripts/repo.env && printf '%s' "$DAWN_SITE_ORIGIN")}"
[ -n "$site_origin" ] || { echo "error: scripts/repo.env names no DAWN_SITE_ORIGIN" >&2; exit 1; }

stamp="$(mktemp)"
trap 'rm -f "$stamp"' EXIT

echo "=== building (DAWN_WASM_CC=$DAWN_WASM_CC) ==="
./site/build.sh

# A reactor is wasm when its first four bytes are the wasm magic, "\0asm".
# The generator's placeholder is a line of text and fails this.
is_wasm() {
  [ "$(head -c 4 "$1" | od -An -tx1 | tr -d ' \n')" = "0061736d" ]
}

bad=0
for name in counter todo search; do
  for f in "site/build/tea/$name.wasm" "site/dist/assets/tea-$name.wasm"; do
    if [ ! -f "$f" ]; then
      echo "error: $f is missing" >&2
      bad=1
    elif ! is_wasm "$f"; then
      echo "error: $f is not wasm (the generator's placeholder?)" >&2
      bad=1
    elif [ "${f#site/build/}" != "$f" ] && [ ! "$f" -nt "$stamp" ]; then
      echo "error: $f was not rebuilt by this run (left over from an older build)" >&2
      bad=1
    fi
  done
done
if [ "$bad" != 0 ]; then
  echo "refusing to deploy: the Demo page and the search panel would ship broken." >&2
  echo "  build.sh printed why above; point DAWN_WASM_CC at a clang that builds" >&2
  echo "  wasm32 reactors (Debian/Ubuntu: clang-20 lld wasi-libc libclang-rt-20-dev-wasm32)." >&2
  exit 1
fi

echo "=== deploying to ${site_origin#https://} ==="
rsync -avz --delete site/dist/ "$HOST:/var/www/dawnlang/dist/"

# The pages sit behind a CDN that caches HTML for ten minutes
# (docs/site-cdn-design.md), so without a purge a deploy is invisible for up
# to that long. Assets need none: their names carry a content hash. The purge
# runs on the deploy host because the CDN credentials live there and never
# leave it; this side only knows the script's path. A failed purge does not
# fail the deploy: the files are already live at the origin and the cache
# expires on its own, so the worst case is the ten-minute wait we had anyway.
# SITE_CDN_PURGE=0 skips it (e.g. a deploy to an origin not behind the CDN).
if [ "${SITE_CDN_PURGE:-1}" != 0 ]; then
  echo "=== purging the CDN page cache ==="
  # shellcheck disable=SC2029  # the URL is this side's; ~ is the host's
  if purge_out="$(ssh "$HOST" "python3 ~/qiniu-cdn-domain.py refresh-dirs $site_origin/" 2>&1)"; then
    echo "$purge_out"
  else
    echo "warning: CDN purge failed; pages refresh when the cache expires (ten minutes)" >&2
    [ -n "$purge_out" ] && echo "$purge_out" >&2
  fi
fi

echo "=== done ==="
echo "$site_origin"

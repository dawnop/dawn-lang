#!/usr/bin/env bash
# Prints the three cache keys CI's actions/cache uses for the site's native
# binaries, as `name=value` lines (append to $GITHUB_OUTPUT):
#
#   dawnc   sha256 of site_dawnc_stamp: the compiler's source stamp + runtime/c
#   gen     site_prog_key site                  (the generator)
#   probe   site_prog_key site/search-budget    (the search budget probe)
#
# They come from the functions site/build.sh itself uses to decide whether its
# local cache is current (site/dawnc.sh), so what CI restores and what the
# script would accept are the same question asked once. A key that moves (any
# compiler source, runtime/c, or any *.dawn/dawn.toml of the project or its path
# dependencies) misses the cache and the script rebuilds; a hit is checked
# against the script's own stored key again, so a restore can only save time.
# Needs ./bin/dawn (the toolchain step comes first); builds nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
. site/dawnc.sh
printf 'dawnc=%s\n' "$(site_dawnc_stamp | sha256sum | cut -d' ' -f1)"
printf 'gen=%s\n' "$(site_prog_key site)"
printf 'probe=%s\n' "$(site_prog_key site/search-budget)"

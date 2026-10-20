#!/usr/bin/env bash
# Prints the one cache key CI's actions/cache uses for the site's native
# binaries, as a `native=<value>` line (append to $GITHUB_OUTPUT). The cache
# holds the directory site/build/native: dawnc built from HEAD plus every
# program in site/native-progs.txt (the generator, the search probe, and
# whatever is listed there later).
#
# The key is a sha256 over the dawnc stamp (compiler source stamp + runtime/c)
# and each program's site_prog_key, from the same functions site/build.sh uses to
# decide whether its local copy is current (site/dawnc.sh), so what CI restores
# and what the script would accept are the same question asked once. Any
# change to a compiler source, runtime/c, or a *.dawn / dawn.toml of a program
# or its path dependencies moves the key. On an exact miss the workflow restores
# the newest older cache by prefix, and the script then keeps what its own
# stored keys still match and rebuilds the rest; so a stale restore can only
# save time. Needs ./bin/dawn (the toolchain step comes first); builds nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
. site/dawnc.sh
printf 'native=%s\n' "$({ site_dawnc_stamp; site_prog_keys; } | sha256sum | cut -d' ' -f1)"

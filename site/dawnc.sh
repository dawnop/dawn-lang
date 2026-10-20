#!/usr/bin/env bash
# Sourced, not run: `site_dawnc` prints the path of the native driver (dawnc)
# that the site's scripts run the generator with. Run from the repo root.
#
# Where dawnc comes from, and why this one of the three candidates:
#
#   DAWNC_BIN=<path>   an explicit binary wins. It is what site/build.sh has
#                      always honoured for the TEA reactors, and it is the
#                      escape hatch for a machine that already has one built.
#   built from HEAD    otherwise, selfhost/src/nmain.dawn is emitted to C and
#                      compiled here, cached under site/build/ and keyed on the
#                      compiler's recursive source stamp plus the C runtime the
#                      link pulls in. The generator is part of this tree and is
#                      compared byte for byte against the JVM backend of this
#                      same tree (scripts/site-dist-diff.sh), so the binary
#                      that runs it has to be this tree's compiler, not an
#                      older one.
#   a release's        not used. `dawnc-linux-x86_64` of a release is the
#   dawnc binary       compiler of that tag, which is one or more commits
#                      behind HEAD while the generator, the language features it
#                      uses and the runtime it links move with HEAD. A site
#                      build that only works once the next release is out is
#                      the failure the seed protocol (docs/bootstrap.md) exists
#                      to prevent. It would also have to be fetched, and the
#                      deploy machine builds offline.
#
# Whether building dawnc from HEAD still goes through the JVM (bin/dawn
# __emitc is the JVM driver) is a toolchain question, not the site's
# (ruling-full-native 2026-10-20, item 1); this file only has to change where
# that stops being true.
#
# Messages go to stderr: stdout is the path, for `$(site_dawnc)`.
site_dawnc() {
  if [ -n "${DAWNC_BIN:-}" ]; then
    printf '%s\n' "$DAWNC_BIN"
    return 0
  fi
  local out=site/build stamp work
  mkdir -p "$out"
  stamp="$(DAWN_PRINT_STAMP=1 ./bin/dawn)/$(
    find runtime/c -type f | sort | xargs cat | sha256sum | cut -d' ' -f1)"
  if [ ! -x "$out/dawnc" ] || [ "$(cat "$out/dawnc.stamp" 2>/dev/null)" != "$stamp" ]; then
    echo "  building the native driver from selfhost/src/nmain.dawn..." >&2
    work="$(mktemp -d)"
    # the units compile in parallel (scripts/cc-units.sh, docs/c-tu-split-design.md)
    if ! { ./bin/dawn __emitc selfhost/src/nmain.dawn --split "$work/nmain" &&
           scripts/cc-units.sh -o "$out/dawnc" "$work/nmain"; } >&2; then
      rm -rf "$work"
      return 1
    fi
    rm -rf "$work"
    printf '%s\n' "$stamp" > "$out/dawnc.stamp"
  fi
  printf '%s\n' "$out/dawnc"
}

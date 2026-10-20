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

# site_prog <project-dir> <name>: prints the path of that project built once
# with `dawnc build <project-dir> -o site/build/<name>` (the way the Playground
# runner is built), so later runs execute the binary instead of paying the
# emit-and-cc of `dawnc run` every time (22s for the generator, 9s for the
# search probe; the programs themselves run in a fraction of that).
#
# The cache key is a sha256 over exactly what `dawnc build` reads:
#   - the dawnc stamp (compiler source + runtime/c), which also stands for std
#     because std is embedded in the dawnc that compiles it (with DAWNC_BIN the
#     binary's own hash stands in for it);
#   - every `*.dawn` and `dawn.toml` under the project directory and under each
#     path dependency, transitively (`[deps]` entries of the form
#     `name = "relative/path"` are followed; these projects have no java-deps
#     or vendored jars, and a dependency of another kind would have to be added
#     here).
# Not in the key, on purpose: data the program reads when it runs (docs/,
# examples/, assets), which the binary reads on every run as `dawnc run` did.
# A changed key, or a missing binary, rebuilds.
site_prog() {
  local proj="$1" name="$2" out="site/build/$2" dawnc stamp key
  local seen=" " queue="$proj" dir toml dep files=""
  dawnc="$(site_dawnc)" || return 1
  if [ -f "$(dirname "$dawnc")/dawnc.stamp" ] && [ -z "${DAWNC_BIN:-}" ]; then
    stamp="$(cat "$(dirname "$dawnc")/dawnc.stamp")"
  else
    stamp="bin:$(sha256sum "$dawnc" | cut -d' ' -f1)"
  fi
  while [ -n "$queue" ]; do
    dir="${queue%%$'\n'*}"
    if [ "$queue" = "$dir" ]; then queue=""; else queue="${queue#*$'\n'}"; fi
    case "$seen" in *" $dir "*) continue ;; esac
    seen="$seen$dir "
    toml="$dir/dawn.toml"
    [ -f "$toml" ] || { echo "error: $toml is missing" >&2; return 1; }
    files="$files$(find "$dir" \( -name build -o -name dist -o -name node_modules \) -prune -o \
      -type f \( -name '*.dawn' -o -name dawn.toml \) -print | sort)"$'\n'
    while IFS= read -r dep; do
      [ -n "$dep" ] || continue
      dep="$(cd "$dir/$dep" 2>/dev/null && pwd -P)" || { echo "error: $toml: a dependency path does not exist" >&2; return 1; }
      dep="${dep#"$(pwd -P)"/}"
      queue="${queue:+$queue$'\n'}$dep"
    done < <(awk '/^\[/ { in_deps = ($0 == "[deps]") }
                  in_deps && /=[ ]*"[^"]*"/ { match($0, /"[^"]*"/); print substr($0, RSTART + 1, RLENGTH - 2) }' "$toml")
  done
  key="$({ printf 'stamp\t%s\n' "$stamp"; printf '%s' "$files" | grep -v '^$' | sort -u | xargs sha256sum; } | sha256sum | cut -d' ' -f1)"
  if [ ! -x "$out" ] || [ "$(cat "$out.key" 2>/dev/null)" != "$key" ]; then
    echo "  building $proj with dawnc build..." >&2
    "$dawnc" build "$proj" -o "$out" >&2 || return 1
    printf '%s\n' "$key" > "$out.key"
  fi
  printf '%s\n' "$out"
}

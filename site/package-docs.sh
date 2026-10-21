#!/usr/bin/env bash
# `dawn doc` for every package under packages/, one JSON document each, into
# <out>/<dir>.json: what gen/packages.dawn reads for packages.html.
#
# Its own file because two callers run it and they must agree on the layout:
# site/build.sh writes into site/build/packages, and scripts/site-dist-diff.sh
# into its snapshot, for the reason it regenerates stdlib.json there (the
# generator only reads files already on disk). A package without a manifest
# is not a package and is skipped, the way gen/packages.package_dirs skips it.
#
# Which driver writes each document (native A2, 2026-10-20):
#
#   dawnc doc          every package whose source, and the source of every
#                      path dependency, has no `use java`. The native driver
#                      writes the same bytes the JVM one does
#                      (scripts/site-dist-diff.sh compares them), so the site
#                      no longer needs a JVM for these documents.
#   ./bin/dawn doc     a package with a `use java`. The native driver cannot
#                      compile Java, and `doc` checks the whole package, so it
#                      would reject the package rather than document it.
#                      Today that is packages/web alone. The test is the
#                      package's text, not a list kept here: a package that
#                      gains a `use java` moves to the JVM by itself, one that
#                      loses its last one moves to dawnc by itself.
#                      EXIT CONDITION: this exception goes away when B1
#                      (ruling-full-native 2026-10-20, item 4) moves web's Java
#                      into its own module. A native `doc` mode that skips Java
#                      signatures was the alternative and was not built: it
#                      would be a branch in the compiler for a transitional
#                      state, dead code the day B1 lands. When B1 merges,
#                      delete has_java and the JVM branch below.
#
# DAWN_DOC_BACKEND=jvm sends every package to the JVM driver: the baseline the
# differential in scripts/site-dist-diff.sh holds the native documents to.
#
# Four at a time: ten packages one after another took 16.9s here on a built
# toolchain, four at a time 8.4s, and a CI runner has four cores. Every run
# writes its own file, so the order they finish in changes nothing.
#
#   site/package-docs.sh <out-dir>     (run from the repository root)
set -euo pipefail

# HotSpot writes its perf-data file (hsperfdata_<user>/<pid>) under /tmp. When
# four JVMs start at once and that directory is contended or full, the JVM
# prints a "warning: ..." line about the shared memory file, and HotSpot prints
# such warnings to STDOUT, not stderr. `dawn doc` writes its document to
# stdout too, so the warning landed at the top of <pkg>.json (main went red
# once on 10-12, a rerun was green). The driver already starts every child JVM
# with -XX:-UsePerfData; the launcher's own JVM is the one left, so give it the
# flag here, for this script only. Not JAVA_TOOL_OPTIONS: that makes every JVM
# print "Picked up ..." on stderr. The value is the launcher's default list
# (bin/dawn DAWN_JVM_OPTS) plus the flag, and a caller's own override is kept.
export DAWN_JVM_OPTS="${DAWN_JVM_OPTS:--Xss512m -Xmx2g -XX:+UseSerialGC} -XX:-UsePerfData"
out="${1:?usage: site/package-docs.sh <out-dir>}"
mkdir -p "$out"
. site/dawnc.sh

# has_java <package-dir>: 0 when the package or a path dependency of it
# (transitively) has a `use java` line. Same `[deps]` reading as
# site_prog_key in site/dawnc.sh.
has_java() {
  local seen=" " queue="$1" dir dep
  while [ -n "$queue" ]; do
    dir="${queue%%$'\n'*}"
    if [ "$queue" = "$dir" ]; then queue=""; else queue="${queue#*$'\n'}"; fi
    case "$seen" in *" $dir "*) continue ;; esac
    seen="$seen$dir "
    if grep -rqE '^[[:space:]]*use[[:space:]]+java\b' --include='*.dawn' "$dir"; then return 0; fi
    while IFS= read -r dep; do
      [ -n "$dep" ] || continue
      dep="$(cd "$dir/$dep" && pwd -P)" || { echo "site/package-docs.sh: $dir/dawn.toml has a dependency path that does not exist" >&2; exit 1; }
      dep="${dep#"$(pwd -P)"/}"
      queue="${queue:+$queue$'\n'}$dep"
    done < <(awk '/^\[/ { in_deps = ($0 == "[deps]") }
                  in_deps && /=[ ]*"[^"]*"/ { match($0, /"[^"]*"/); print substr($0, RSTART + 1, RLENGTH - 2) }' "$dir/dawn.toml")
  done
  return 1
}

# Sort the packages by driver first, so the toolchain that is not needed is not
# started at all (a site build with no java package never starts a JVM here).
jobs_list=""
need_jvm=0
for pkg in packages/*/; do
  pkg="${pkg%/}"
  [ -f "$pkg/dawn.toml" ] || continue
  name="${pkg#packages/}"
  if [ "${DAWN_DOC_BACKEND:-}" != jvm ] && ! has_java "$pkg"; then
    jobs_list="$jobs_list"$'n\t'"$name"$'\n'
  else
    need_jvm=1
    jobs_list="$jobs_list"$'j\t'"$name"$'\n'
    if [ "${DAWN_DOC_BACKEND:-}" != jvm ]; then
      echo "site/package-docs.sh: $name has a use java: documented by the JVM driver (until B1)" >&2
    fi
  fi
done
export DOC_OUT="$out"
if printf '%s' "$jobs_list" | grep -q '^n'; then
  DOC_DAWNC="$(site_dawnc)"
  case "$DOC_DAWNC" in /*) ;; *) DOC_DAWNC="$PWD/$DOC_DAWNC" ;; esac
  export DOC_DAWNC
fi
# Warm the JVM toolchain once, serially, before the parallel section. The
# launcher itself is safe to start concurrently on a cold checkout (the seed
# cache and the rebuild are lock-serialised in bin/dawn and scripts/seedjar.sh),
# but without this the launchers below would all sit behind that one lock and the
# first `dawn doc` would absorb the whole toolchain build. A latency choice and a
# second line of defence, not the fix: it used to be the only thing keeping four
# racing launchers from leaving an empty <pkg>.json behind.
if [ "$need_jvm" = 1 ]; then ./bin/dawn --version > /dev/null; fi
printf '%s' "$jobs_list" | tr '\n\t' '\0\0' | xargs -0 -n 2 -P 4 sh -c '
  if [ "$1" = n ]; then "$DOC_DAWNC" doc "packages/$2" > "$DOC_OUT/$2.json"
  else ./bin/dawn doc "packages/$2" > "$DOC_OUT/$2.json"; fi' sh

# A document that is empty or not JSON stops here, naming the file and what it starts
# with. `dawn doc` writes the document to stdout, so anything else the JVM or
# the launcher prints there (a log line, a rebuild notice) lands in the file
# and would otherwise surface much later as an offset in a parser's error from
# gen/packages.dawn, with nothing to say whose output it was.
for f in "$out"/*.json; do
  if [ ! -s "$f" ]; then
    echo "site/package-docs.sh: $f is empty" >&2
    exit 1
  fi
  if [ "$(head -c 1 "$f")" != "{" ]; then
    echo "site/package-docs.sh: $f does not start with '{', it starts with: $(head -c 200 "$f" | head -n 3)" >&2
    exit 1
  fi
done

#!/usr/bin/env bash
# Build the site into site/dist (run from anywhere).
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p site/build
./bin/dawn doc --stdlib > site/build/stdlib.json

# The cuTile page's line maps: which public call of each golden kernel wrote
# which Tile IR line. The generator reads the recording (site/gpu-map/
# calls.txt), because it is a pure function of files on disk; this traces
# every kernel again through packages/tileir and stops the build when the
# recording is not what tileir says today (site/gpu-map/record.py says why).
echo "=== checking the cuTile line maps ==="
python3 site/gpu-map/record.py

# The Playground editor bundle (CodeMirror 6 + Dawn mode). Built locally with
# node; the server never runs node — it only receives site/dist. Skipped with a
# warning if npm is unavailable, so the rest of the site still builds.
if command -v npm >/dev/null 2>&1; then
  echo "=== building play-ui ==="
  (cd site/play-ui && npm install --silent && npm run build)
else
  echo "warning: npm not found — Playground editor bundle NOT rebuilt" >&2
fi

# The TEA applications, as wasm reactors: the two demos on tea.html, and the
# search panel every page's header mounts. Built here for the same
# reason play-ui is: scripts/site-dist-diff.sh runs the generator twice and
# compares site/dist byte for byte, so everything the generator does has to be
# a pure function of files that are already on disk when it starts. A
# generator that shelled out to a compiler would be comparing two compilers.
#
# Skipped with a warning, like play-ui, when the wasm toolchain is not here --
# which is the case in CI, where this job installs npm and nothing else. The
# generator then writes placeholders and the demo page reports that it could
# not load; the rest of the site is unaffected.
tea_out=site/build/tea
mkdir -p "$tea_out"
tea_work="$(mktemp -d)"
trap 'rm -rf "$tea_work"' EXIT

# Which triple this clang has a sysroot for, and whether it can build what a
# reactor needs: the triple question is scripts/wasm-contract/run.sh's, because
# the answer is the driver's and asking it any other way probes a different
# link. The second half is one file rather than a hello world, and that is the
# lesson of the first run of this script: clang 18 links a trivial wasm program
# and then crashes its own assembler on the exception tag every Dawn reactor
# carries. A probe that a broken compiler passes is worse than no probe.
tea_cc="${DAWN_WASM_CC:-clang}"
tea_ok=0
if command -v "$tea_cc" >/dev/null 2>&1; then
  tea_triple=wasm32-wasi
  tea_crt1="$("$tea_cc" --target=wasm32-wasip1 -print-file-name=crt1.o 2>/dev/null || true)"
  [ -f "$tea_crt1" ] && tea_triple=wasm32-wasip1
  echo 'int main(void){return 0;}' > "$tea_work/probe.c"
  if "$tea_cc" --target="$tea_triple" -o "$tea_work/probe.wasm" "$tea_work/probe.c" \
        2> "$tea_work/probe.err" &&
      "$tea_cc" --target="$tea_triple" -std=c11 -O2 -c runtime/c/dawn_rt_wasi_tag.c \
        -o "$tea_work/tag.o" 2>> "$tea_work/probe.err"; then
    tea_ok=1
  fi
fi

if [ "$tea_ok" = 1 ]; then
  echo "=== building the TEA reactors ==="
  # `--target wasm --reactor` is the native driver's alone (selfhost/src/
  # nmain.dawn); the JVM CLI has no wasm backend. Emitting and linking it costs
  # ~35s, so it is cached beside the artifacts and keyed on what it was built
  # from: the compiler's own recursive source stamp plus the C runtime the link
  # pulls in. Either moves, it is rebuilt.
  tea_dawnc="${DAWNC_BIN:-}"
  if [ -z "$tea_dawnc" ]; then
    tea_stamp="$(DAWN_PRINT_STAMP=1 ./bin/dawn)/$(
      find runtime/c -type f | sort | xargs cat | sha256sum | cut -d' ' -f1)"
    if [ ! -x "$tea_out/dawnc" ] || [ "$(cat "$tea_out/dawnc.stamp" 2>/dev/null)" != "$tea_stamp" ]; then
      echo "  building the native driver from selfhost/src/nmain.dawn..."
      ./bin/dawn __emitc selfhost/src/nmain.dawn -o "$tea_work/nmain.c"
      "${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
        -I runtime/c -o "$tea_out/dawnc" "$tea_work/nmain.c" runtime/c/dawn_rt.c -lm
      printf '%s\n' "$tea_stamp" > "$tea_out/dawnc.stamp"
    fi
    tea_dawnc="$tea_out/dawnc"
  fi
  # A reactor that will not build stops the demo, not the site: the generator
  # writes a placeholder, the demo page says it could not load, and every other
  # page is what it was. Same deal the Playground makes when its editor bundle
  # is missing, and the reason `set -e` is held off here.
  # The search panel is not a demo and is built the same way anyway: it is a
  # reactor, it is mounted by the same bridge, and a checkout with no wasm
  # toolchain gets a placeholder and a header button that says so.
  for tea_demo in tea_dom_counter:counter tea_dom_todo_keyed:todo tea_dom_search:search; do
    tea_project="${tea_demo%%:*}"
    tea_name="${tea_demo##*:}"
    if ! "$tea_dawnc" build --target wasm --reactor "examples/projects/$tea_project" \
        -o "$tea_out/$tea_name.wasm" 2> "$tea_work/build.err"; then
      rm -f "$tea_out/$tea_name.wasm"
      echo "warning: the $tea_project reactor did not build; the demo page will say so" >&2
      sed 's/^/  | /' "$tea_work/build.err" >&2
    fi
  done
else
  echo "warning: no usable wasm toolchain ($tea_cc) — the TEA demo reactors were NOT rebuilt" >&2
  echo "  Debian/Ubuntu: apt install clang-20 lld wasi-libc libclang-rt-20-dev-wasm32" >&2
  echo "  (or point DAWN_WASM_CC at a wasi-sdk clang)" >&2
fi

# What the footer prints as the build (gen/pages.build_stamp): the source
# tree's VERSION and its commit, "-dirty" when the tree has changes git can
# see. Passed as environment rather than read by the generator, because
# scripts/site-dist-diff.sh runs it over a snapshot with neither selfhost/ nor
# .git in it. Either one blank, and the footer prints less or nothing.
DAWN_SITE_VERSION="${DAWN_SITE_VERSION:-$(sed -n 's/^pub const VERSION: String = "\(.*\)"$/\1/p' selfhost/src/version.dawn)}"
if [ -z "${DAWN_SITE_COMMIT:-}" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  DAWN_SITE_COMMIT="$(git rev-parse --short=8 HEAD)"
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    DAWN_SITE_COMMIT="${DAWN_SITE_COMMIT}-dirty"
  fi
fi
export DAWN_SITE_VERSION DAWN_SITE_COMMIT="${DAWN_SITE_COMMIT:-}"

# Where the Playground's API lives (gen/pages.play_origin): empty, the default,
# keeps the page's relative `/api/run`; set to a bare origin such as
# `https://play.example.test`, the page hands the editor absolute URLs on it.
# This is what lets the pages sit behind a CDN that carries no WebSocket while
# `/api/lsp` stays on a host that does (docs/site-cdn-design.md). Environment
# again, so scripts/site-dist-diff.sh's two legs both see whatever the caller
# set.
export DAWN_SITE_PLAY_ORIGIN="${DAWN_SITE_PLAY_ORIGIN:-}"

# The front page's figures (scripts/site-figures.sh), as DAWN_SITE_FIG_<KEY>.
# Environment for the reason the two lines above are: the differential runs the
# generator where neither selfhost/ nor .git exists. Passed through as they
# come, empty ones included -- refusing an empty figure is the generator's job
# (gen/home.read_figure), and a check here would be a second guard nobody
# could tell apart from the first.
. scripts/site-figures-env.sh

rm -rf site/dist
# gen_assets vendors site/play-ui/dist/playground.{js,css}, site/build/tea/
# *.wasm and packages/tea-dom/js/*.mjs into dist/assets
./bin/dawn run site

# The search body indexes' size, raw and gzipped, against the budget in
# docs/site-search-design.md 2.6. The generator prints the raw count itself but
# has no compressor, and the budget is what a reader downloads, so the gzip
# count is taken here. Over budget is reported, not fatal: the remedy (a
# shorter excerpt) is a design change, not something a build should guess.
for search_body in en:120 zh:150; do
  search_lang="${search_body%%:*}"
  search_budget_kb="${search_body##*:}"
  search_file="site/dist/assets/search-body-$search_lang.json"
  search_raw=$(wc -c < "$search_file")
  search_gz=$(gzip -9c "$search_file" | wc -c)
  echo "  search body $search_lang: $search_raw bytes raw, $search_gz bytes gzip (budget ${search_budget_kb} KB)"
  if [ "$search_gz" -gt $((search_budget_kb * 1024)) ]; then
    echo "warning: $search_file is over its ${search_budget_kb} KB gzip budget (docs/site-search-design.md 2.6)" >&2
  fi
done

#!/usr/bin/env bash
# Consume an attested native tool and locked raw metadata into a fresh site.
# Tool bootstrap and JDK extraction belong to site/prepare.sh; this process
# and every child use the verified native binary without a JVM stamp lookup.
set -euo pipefail
cd "$(dirname "$0")/.."
. site/dawnc.sh

DAWNC_BIN="$(python3 site/inputs.py check)"
export DAWNC_BIN
# A previous bundle is never a documentation cache. Promotion happens only
# after every target and output in this fresh staging has been verified.
rm -rf site/build/doc-inputs
python3 site/inputs.py bundle --out site/build/doc-inputs

# The cuTile page's call map: which call of flash_attn wrote which Tile IR
# line, and where that call is in its source. The generator reads the
# recording (site/gpu-map/flash_attn.map), because it is a pure function of
# files on disk; this traces the kernel again through packages/tileir, parses
# kernels.dawn again, and stops the build when the recording is not what the
# two say today (site/gpu-map/record.py says why).
echo "=== checking the cuTile call map ==="
python3 site/gpu-map/record.py

# The Playground editor bundle (CodeMirror 6 + Dawn mode). Built locally with
# node; the server never runs node — it only receives site/dist. Skipped with a
# warning if npm is unavailable, so the rest of the site still builds.
if command -v npm >/dev/null 2>&1; then
  echo "=== building play-ui ==="
  (cd site/play-ui && npm ci --silent && npm run build)
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
  # nmain.dawn); the JVM CLI has no wasm backend. Emitting and linking dawnc
  # costs ~35s, so site/dawnc.sh caches it beside the artifacts.
  # Resolved only here and in site_prog, when something has to be built: with
  # the generator binary current (a CI cache hit) dawnc itself is not needed.
  tea_dawnc="$(site_dawnc)"
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

# Match the independent renderer oracle's version, commit and API origin.
. site/build-env.sh

# The front page's figures (scripts/site-figures.sh), as DAWN_SITE_FIG_<KEY>.
# Environment for the reason the two lines above are: the differential runs the
# generator where neither selfhost/ nor .git exists. Passed through as they
# come, empty ones included -- refusing an empty figure is the generator's job
# (gen/home.read_figure), and a check here would be a second guard nobody
# could tell apart from the first.
. scripts/site-figures-env.sh

python3 site/inputs.py check-bundle --out site/build/doc-inputs
rm -rf site/dist
# gen_assets vendors site/play-ui/dist/playground.{js,css}, site/build/tea/
# *.wasm and packages/tea-dom/js/*.mjs into dist/assets
# Native, and the only generator the shipped dist comes from (see the header).
"$(site_prog site_gen)"

# The search assets against their budgets (docs/site-search-design.md 13.7):
# the index's gzip size, the largest text fragment's, and the worst first-query
# bytes over the sample in site/search-queries.txt, which is measured by running
# the panel's own code on this dist (site/search-budget/). The generator prints
# raw sizes and has no compressor, and the budget is what a reader downloads,
# so the gzip counts are taken here. Over budget stops the build: the remedy is
# a design decision (13.9 lists the levers), and failing here puts it on the
# change that crossed the line rather than on whoever builds next.
site/search-budget.sh site/dist

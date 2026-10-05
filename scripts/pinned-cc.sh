#!/usr/bin/env bash
# Point CC at the one C compiler CI and the release build with: the runner
# image's clang 18.1.3, held to that exact version (ruling ffi-llvm 4.b,
# 2026-10-04).
#
# Why clang at all. Every native job's wall clock is mostly cc (#239: 75% of
# native-selfhost-tests), and until now cc was whatever `cc` meant on
# ubuntu-latest, gcc 13.3. Measured on one machine on 2026-10-05, building the
# whole native compiler (nmain's 379k lines of C plus the runtime) at -O2,
# two rounds each, and running the result on its own bootstrap load
# (`dawnc emitc selfhost/src/nmain.dawn`, user seconds, four runs):
#
#   gcc 13.3.0    51.9 / 51.4 s   12.73 12.81 12.71 12.83
#   clang 18.1.3  43.1 / 41.3 s   11.72 11.63 11.73 11.68   -18% / -9%
#   clang 20.1.2  39.8 / 37.8 s   11.63 11.64 11.87 11.59   -25% / -9%
#
# Why 18 and not 20, which compiles another 8% faster. clang 18 is already on
# the ubuntu-24.04 image (actions/runner-images, "Clang: 16.0.6, 17.0.6,
# 18.1.3", with its compiler-rt sanitizer runtimes, which spike-native's ASan
# leg needs), so pinning it costs no step time. clang 20 is an apt install of
# about 60 MB into every job that compiles C, roughly 20-30 s each, more than
# its 8% buys back on all but the two or three jobs that build the whole
# compiler more than once. And 18.1.3-1ubuntu1 is the version noble shipped
# with and still carries in noble-updates, so it does not drift under an SRU
# the way noble's clang-20 has (20.1.2-0ubuntu1~24.04.3 today).
#
# Why the version is checked rather than trusted. "The image has it" is a
# promise about today's image. If a later ubuntu-latest drops clang-18 or
# moves it, this fails the job by name instead of quietly building with
# something else, and the release, whose dawnc bytes are a function of the
# compiler, would otherwise change without anyone choosing it.
#
# Where it runs: first in every gates.yml job that compiles C, and before
# release.yml's native binary. Not yet in nightly's native-asan: clang's UBSan
# reports one real defect in every test binary there (nightly.yml says which),
# and that leg stays on gcc until the fix lands.
#
# Why only on a GitHub runner, or where DAWN_PINNED_CC names the compiler.
# Off a runner (a laptop), CC stays whatever the caller set and the scripts
# keep their own default, `cc`; this prints which and changes nothing.
# GITHUB_ACTIONS is the runner's own variable, and the external runner
# (scripts/gates-external) does not fake it. It names the clang 18.1.3 of its
# input pack in DAWN_PINNED_CC instead (conda-forge's build of the same
# release, since a prefix cannot apt install), and this script holds that
# compiler to the same version and writes CC the same way, so an external
# run's C jobs build with the compiler CI's do.
#
#   ./scripts/pinned-cc.sh        # in a workflow step; appends CC to $GITHUB_ENV
set -euo pipefail

want_bin=clang-18
want_version=18.1.3

if [ -n "${DAWN_PINNED_CC:-}" ]; then
  path=$DAWN_PINNED_CC
  if [ ! -x "$path" ]; then
    echo "FAIL: DAWN_PINNED_CC=$path is not an executable" >&2
    exit 1
  fi
elif [ "${GITHUB_ACTIONS:-}" != true ]; then
  echo "pinned-cc: not a GitHub runner, CC left as ${CC:-unset (cc)}"
  exit 0
elif ! path=$(command -v "$want_bin"); then
  echo "FAIL: $want_bin is not on this runner; the image no longer carries it" >&2
  exit 1
fi
got=$("$path" -dumpversion)
if [ "$got" != "$want_version" ]; then
  echo "FAIL: $path is $got, pinned to $want_version" >&2
  exit 1
fi
if [ -z "${GITHUB_ENV:-}" ]; then
  echo "FAIL: a pinned compiler was found but GITHUB_ENV is not set" >&2
  exit 1
fi
echo "CC=$path" >>"$GITHUB_ENV"
echo "pinned-cc: CC=$path ($("$path" --version | sed -n 1p))"

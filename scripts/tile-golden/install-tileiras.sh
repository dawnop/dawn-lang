#!/usr/bin/env bash
# Install the pinned `tileiras` into a directory and print the binary's path.
#
#   scripts/tile-golden/install-tileiras.sh <dir> [wheel-dir]
#   TILEIRAS=$(scripts/tile-golden/install-tileiras.sh ~/.cache/dawn-tileiras)
#
# The pin is toolchain.txt's `wheel` lines: each wheel is downloaded from the
# package index by exact version, its sha256 is checked against the one
# written down here (a checksum from the same place as the file it checks is
# not a check; the rule .dawn-version.sha256 and the wasi-sdk step of
# gates.yml already follow), and only then installed, with no index and no
# dependency resolution, into a virtual environment under <dir>. The optional
# wheel directory can be restored by CI without restoring a virtual environment.
# Even an existing install is reused only after wheel hashes, installed package
# versions and the assembler's own version have been checked again.
#
# PIP_INDEX_URL is respected, so a mirror works. Nothing here needs a GPU or a
# driver: tileiras is an offline assembler (it links libc, libm and libpthread
# only, and at run time reads libnvvm.so.4 and execs ptxas from the wheels
# beside it).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
toolchain="$here/toolchain.txt"

fail() {
  echo "install-tileiras: $*" >&2
  exit 1
}

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  fail "usage: install-tileiras.sh <dir> [wheel-dir]"
fi
dest="$1"
dl="${2:-$dest/.wheels}"

specs=()
while read -r key spec hash; do
  [ "$key" = wheel ] || continue
  [[ "$spec" =~ ^[a-zA-Z0-9_-]+==[0-9]+(\.[0-9]+)*$ ]] || fail "invalid wheel pin: $spec"
  [[ "$hash" =~ ^sha256=[0-9a-f]{64}$ ]] || fail "invalid wheel hash for $spec"
  specs+=("$spec ${hash#sha256=}")
done < "$toolchain"
[ "${#specs[@]}" -gt 0 ] || fail "no wheel lines in $toolchain"

# The stamp is a hint to reuse the environment, never a substitute for checking
# the wheels or the installed versions. It includes the assembler version too.
stamp="$dest/.pin"
want="$(sha256sum "$toolchain" | cut -d ' ' -f 1)"
want_tileiras="$(awk '$1 == "tileiras" { print $2 }' "$toolchain")"
[ -n "$want_tileiras" ] || fail "no tileiras version in $toolchain"
tileiras_of() { find "$1" -type f -path '*/nvidia/cu13/bin/tileiras' | head -n 1; }

# Only the pinned packages need replacing when the pin changes. Do not erase
# the wheels, or recreate an existing environment's read-only activation files.
if ! [ -x "$dest/bin/python" ] || ! [ -x "$dest/bin/pip" ]; then
  python3 -m venv "$dest" >&2
fi
pip="$dest/bin/pip"
mkdir -p "$dl"
shopt -s nullglob
wheels=()

for entry in "${specs[@]}"; do
  read -r spec hash <<< "$entry"
  name="${spec%%==*}"
  name="${name//-/_}"
  matches=("$dl/$name-${spec##*==}-"*.whl)
  if [ "${#matches[@]}" -eq 0 ]; then
    # A warm cache never enters pip's download command. On a miss, each
    # connection has a finite timeout and retry count.
    "$pip" download --quiet --disable-pip-version-check --no-deps --only-binary=:all: \
      --retries 3 --timeout 30 --dest "$dl" "$spec" >&2
    matches=("$dl/$name-${spec##*==}-"*.whl)
  fi
  [ "${#matches[@]}" -eq 1 ] || fail "expected exactly one wheel for $spec"
  whl="${matches[0]}"
  echo "$hash  $whl" | sha256sum -c - >&2 ||
    fail "$spec: the cached or downloaded wheel is not the one toolchain.txt pins"
  wheels+=("$whl")
done

check_versions() {
  "$dest/bin/python" - "${specs[@]}" <<'PY'
import importlib.metadata
import sys

for entry in sys.argv[1:]:
    spec = entry.split()[0]
    name, expected = spec.split("==")
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        sys.exit(f"install-tileiras: missing installed package {spec}")
    if actual != expected:
        sys.exit(f"install-tileiras: {name} is {actual}, expected {expected}")
PY
}

if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
  check_versions
else
  "$pip" install --quiet --disable-pip-version-check --no-index --no-deps \
    --force-reinstall "${wheels[@]}" >&2
  check_versions
fi
bin="$(tileiras_of "$dest")"
if [ -z "$bin" ] || ! [ -x "$bin" ]; then fail "no tileiras binary under $dest after install"; fi
version="$("$bin" --version)" || fail "tileiras --version failed"
awk -v want="V$want_tileiras" '
  { for (i = 1; i <= NF; i++) if ($i == want) found = 1 }
  END { exit !found }
' <<< "$version" || fail "tileiras is not the pinned $want_tileiras"
printf '%s' "$want" > "$stamp"
echo "$bin"

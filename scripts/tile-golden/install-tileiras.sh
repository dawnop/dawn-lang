#!/usr/bin/env bash
# Install the pinned `tileiras` into a directory and print the binary's path.
#
#   scripts/tile-golden/install-tileiras.sh <dir>
#   TILEIRAS=$(scripts/tile-golden/install-tileiras.sh ~/.cache/dawn-tileiras)
#
# The pin is toolchain.txt's `wheel` lines: each wheel is downloaded from the
# package index by exact version, its sha256 is checked against the one
# written down here (a checksum from the same place as the file it checks is
# not a check; the rule .dawn-version.sha256 and the wasi-sdk step of
# gates.yml already follow), and only then installed, with no index and no
# dependency resolution, into a virtual environment under <dir>. A second run
# on the same <dir> with the same pin is a no-op.
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

[ $# -eq 1 ] || fail "usage: install-tileiras.sh <dir>"
dest="$1"

specs=()
while read -r key spec hash; do
  [ "$key" = wheel ] || continue
  specs+=("$spec ${hash#sha256=}")
done < "$toolchain"
[ "${#specs[@]}" -gt 0 ] || fail "no wheel lines in $toolchain"

# The pin as one string; if <dir> was installed from the same pin, keep it.
stamp="$dest/.pin"
want="$(printf '%s\n' "${specs[@]}")"
tileiras_of() { find "$1" -type f -path '*/nvidia/cu13/bin/tileiras' | head -n 1; }
if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
  bin="$(tileiras_of "$dest")"
  [ -n "$bin" ] && [ -x "$bin" ] && { echo "$bin"; exit 0; }
fi

rm -rf "$dest"
python3 -m venv "$dest" >&2
pip="$dest/bin/pip"
dl="$dest/.wheels"
mkdir -p "$dl"

for entry in "${specs[@]}"; do
  read -r spec hash <<< "$entry"
  "$pip" download --quiet --disable-pip-version-check --no-deps --only-binary=:all: \
    --dest "$dl" "$spec" >&2
  whl="$(find "$dl" -name "$(echo "${spec%%==*}" | tr - _)-${spec##*==}-*.whl" | head -n 1)"
  [ -n "$whl" ] || fail "downloaded nothing for $spec"
  echo "$hash  $whl" | sha256sum -c - >&2 ||
    fail "$spec: the downloaded wheel is not the one toolchain.txt pins"
done

"$pip" install --quiet --disable-pip-version-check --no-index --no-deps "$dl"/*.whl >&2
rm -rf "$dl"
bin="$(tileiras_of "$dest")"
if [ -z "$bin" ] || ! [ -x "$bin" ]; then fail "no tileiras binary under $dest after install"; fi
printf '%s' "$want" > "$stamp"
echo "$bin"

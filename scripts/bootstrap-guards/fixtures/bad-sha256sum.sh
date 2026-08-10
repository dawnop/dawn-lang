#!/bin/bash
# The known vector is allowed to pass in status/shape modes; the next real
# digest then fails so the launcher proves it validates every invocation.
set -euo pipefail

payload=$(mktemp "${TMPDIR:-/tmp}/dawn-bad-hash.XXXXXX")
trap 'rm -f "$payload"' EXIT
cat > "$payload"
abc=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad

case ${FAKE_HASH_MODE:-zero} in
  zero)
    printf '%064d  -\n' 0
    ;;
  status)
    if [[ $(cat "$payload") == abc ]]; then
      printf '%s  -\n' "$abc"
    else
      printf '%064d  -\n' 0
      exit 7
    fi
    ;;
  shape)
    if [[ $(cat "$payload") == abc ]]; then
      printf '%s  -\n' "$abc"
    else
      printf 'not-a-digest  -\n'
    fi
    ;;
  valid)
    "$REAL_SHA256SUM" < "$payload"
    ;;
  *) exit 8 ;;
esac

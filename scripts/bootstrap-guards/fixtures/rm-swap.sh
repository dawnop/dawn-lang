#!/bin/bash
# Swap only when the launcher's full-validation workspace is cleaned. Earlier
# hash-temp removals must not trigger the execution-pair race fixture.
set -euo pipefail

"$REAL_RM" "$@"
target=${!#}
case ${target##*/} in
  dawn-launcher.*)
    if [[ -n ${FAKE_RM_SWAP_JAR:-} && ! -e $FAKE_RM_SWAP_MARKER ]]; then
      : > "$FAKE_RM_SWAP_MARKER"
      printf 'rogue\n' > "$FAKE_RM_SWAP_JAR"
    fi
    ;;
esac

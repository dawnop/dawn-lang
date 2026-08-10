#!/bin/bash
# Corrupt the promoted jar immediately after the marker rename. A companion rm
# fixture restores it only when validation workspace cleanup begins.
set -euo pipefail

destination=${!#}
"$REAL_MV" "$@"
if [[ $destination == "$FAKE_PROMOTION_STAMP" && ! -e $FAKE_PROMOTION_SWAP_MARKER ]]; then
  : > "$FAKE_PROMOTION_SWAP_MARKER"
  printf 'rogue\n' > "$FAKE_PROMOTION_JAR"
fi

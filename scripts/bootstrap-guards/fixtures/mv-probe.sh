#!/bin/bash
# Promotion probes observe destination order and can terminate immediately
# after one rename, making the commit-marker crash boundary reproducible.
set -euo pipefail

destination=${!#}
if [[ -n ${FAKE_MV_LOG:-} ]]; then
  printf '%s\n' "$destination" >> "$FAKE_MV_LOG"
fi
"$REAL_MV" "$@"
if [[ -n ${FAKE_MV_CRASH_AFTER:-} && $destination == "$FAKE_MV_CRASH_AFTER" ]]; then
  kill -KILL "$PPID"
fi

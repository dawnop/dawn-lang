#!/bin/bash
# Restore the known fake candidate at validation-workspace cleanup and record
# each cleanup, separating post-promotion validation from the pre-exec check.
set -euo pipefail

"$REAL_RM" "$@"
target=${!#}
case ${target##*/} in
  dawn-launcher.*)
    printf 'cleanup\n' >> "$FAKE_CLEANUP_LOG"
    if [[ ! -e $FAKE_RESTORE_MARKER ]]; then
      : > "$FAKE_RESTORE_MARKER"
      printf 'candidate\n' > "$FAKE_PROMOTION_JAR"
    fi
    ;;
esac

# shellcheck shell=bash
# Internal complete phases used by the required syntax worker dispatcher.
# A phase is a diagnostic result, not a complete family coverage verdict.
syntax_phase=all
syntax_case_name=
syntax_phase_rest=()
syntax_phase_parse() {
  syntax_phase_rest=("$@")
  case "${1:-}" in
    --fixtures-only)
      [ "$#" -eq 1 ] || { echo 'FAIL: --fixtures-only takes no other arguments' >&2; exit 2; }
      syntax_phase=fixtures
      syntax_phase_rest=()
      ;;
    --case-only)
      [ "$#" -eq 2 ] && [ -n "$2" ] || { echo 'FAIL: --case-only needs one case' >&2; exit 2; }
      syntax_phase=case
      syntax_case_name=$2
      syntax_phase_rest=()
      ;;
  esac
}

syntax_phase_begin() {
  if [ "$syntax_phase" = case ]; then printf 'BEGIN syntax oracle %s %s at=%s\n' "$1" "$syntax_case_name" "$(date +%s.%N)"; fi
}
syntax_phase_end() {
  if [ "$syntax_phase" != case ]; then return; fi
  printf 'END syntax oracle %s %s status=0 at=%s\n' "$1" "$syntax_case_name" "$(date +%s.%N)"
  # Keep the existing owning-test assertion and additionally pin its entire
  # failure set. The complete private test run has already finished.
  case "$1/$syntax_case_name" in
    syntax-small-contract/drop-opaque-anchor|syntax-small-contract/drop-rbracket-return-boundary)
      printf 'BEGIN syntax red control %s at=%s\n' "$syntax_case_name" "$(date +%s.%N)"
      case "$syntax_case_name" in
        drop-opaque-anchor) expected_reds="$root/scripts/syntax-pool/drop-opaque-anchor.reds" ;;
        drop-rbracket-return-boundary) expected_reds="$root/scripts/syntax-pool/drop-rbracket-return-boundary.reds" ;;
      esac
      LC_ALL=C awk '/^FAIL  /' "$mdir/test.out" | LC_ALL=C sort > "$mdir/red.actual"
      if ! diff -u "$expected_reds" "$mdir/red.actual"; then
        echo "FAIL: $syntax_case_name changed its complete failure set" >&2
        exit 1
      fi
      while IFS= read -r red; do printf 'RED_SET %s\t%s\n' "$syntax_case_name" "$red"; done < "$mdir/red.actual"
      printf 'END syntax red control %s status=0 at=%s\n' "$syntax_case_name" "$(date +%s.%N)"
      ;;
  esac
}

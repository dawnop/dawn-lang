# shellcheck shell=bash
# One complete independent contract may overlap the caller's next work.
# Join it before reusing any of its inputs. EXIT always collects an outstanding
# result before removing OUT, including when foreground work failed.
native_parallel_pid=
native_parallel_name=
native_parallel_log=
native_parallel_enabled=
native_parallel_starting=0
native_parallel_pending_status=0
native_parallel_keep=

native_parallel_signal() {
  if [ "$native_parallel_starting" = 1 ]; then
    # The owner must register the just-forked child before honoring a signal.
    if [ "$native_parallel_pending_status" = 0 ]; then
      native_parallel_pending_status=$1
    fi
  else
    exit "$1"
  fi
}

native_parallel_enable() {
  if [ -n "$native_parallel_enabled" ] || [ -z "${OUT:-}" ] || [ ! -d "$OUT" ]; then
    echo "FAIL: native parallel work needs one existing output directory" >&2
    return 2
  fi
  native_parallel_keep=${KEEP:-}
  native_parallel_enabled=1
  trap 'native_parallel_cleanup "$?"' EXIT
  trap 'native_parallel_signal 129' HUP
  trap 'native_parallel_signal 130' INT
  trap 'native_parallel_signal 143' TERM
}

native_parallel_start() {
  if [ -z "$native_parallel_enabled" ] || [ -n "$native_parallel_pid" ] ||
      [ "$#" -lt 2 ] || [[ ! "$1" =~ ^[a-z][a-z0-9-]*$ ]]; then
    echo "FAIL: native parallel work permits one complete child at a time" >&2
    return 2
  fi
  native_parallel_starting=1
  native_parallel_name=$1
  shift
  native_parallel_log="$OUT/$native_parallel_name.parallel.log"
  printf 'BEGIN native parallel %s\n' "$native_parallel_name"
  (
    # A subshell must never inherit the owner's output cleanup trap.
    trap - EXIT HUP INT TERM
    # Keep a function callback outside a tested command so errexit applies
    # to every command it contains, including a failure before its last one.
    trap 'status=$?; trap - EXIT; printf "END native parallel %s status=%s\n" "$native_parallel_name" "$status"; exit "$status"' EXIT
    "$@" > "$native_parallel_log" 2>&1
  ) &
  native_parallel_pid=$!
  native_parallel_starting=0
  if [ "$native_parallel_pending_status" -ne 0 ]; then
    exit "$native_parallel_pending_status"
  fi
}

native_parallel_finish() {
  if [ -z "$native_parallel_pid" ]; then
    echo "FAIL: native parallel result was not started" >&2
    return 2
  fi
  local status=0
  printf 'JOIN native parallel %s\n' "$native_parallel_name"
  wait "$native_parallel_pid" || status=$?
  native_parallel_pid=
  if ! cat "$native_parallel_log"; then
    [ "$status" -ne 0 ] || status=1
  fi
  printf 'RESUME native parallel %s status=%s\n' "$native_parallel_name" "$status"
  return "$status"
}

native_parallel_cleanup() {
  local status=$1 child_status=0
  trap - EXIT
  # Collect the original bounded contract even when its caller was interrupted.
  trap '' HUP INT TERM
  if [ -n "$native_parallel_pid" ]; then
    native_parallel_finish || child_status=$?
    [ "$status" -ne 0 ] || status=$child_status
  fi
  if [ -z "$native_parallel_keep" ]; then
    if ! rm -rf "$OUT"; then
      [ "$status" -ne 0 ] || status=1
    fi
  fi
  exit "$status"
}

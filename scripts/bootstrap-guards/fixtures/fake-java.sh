#!/bin/bash
# A process-boundary compiler double: jar role is the first text line, while
# every invocation is logged so cache hits and forbidden seed calls are visible.
set -euo pipefail

while [[ $# -gt 0 && $1 != -jar ]]; do
  shift
done
[[ $# -ge 3 ]]
shift
jar=$1
shift
command_name=$1
shift

role=$(head -n 1 "$jar")
output=-
previous=
for argument in "$@"; do
  if [[ $previous == -o ]]; then
    output=$argument
    break
  fi
  previous=$argument
done
printf '%s\t%s\t%s\t%s\n' "$role" "$command_name" "$output" "$jar" >> "$FAKE_JAVA_LOG"

if [[ $command_name == build ]]; then
  [[ $output != - ]]
  if [[ $role == seed ]]; then
    if [[ -n ${FAKE_BUILD_BARRIER:-} ]]; then
      mkdir -p "$FAKE_BUILD_BARRIER"
      transaction=$(basename "$(dirname "$output")")
      : > "$FAKE_BUILD_BARRIER/$transaction.$PPID"
      for _ in $(seq 1 250); do
        count=$(find "$FAKE_BUILD_BARRIER" -type f | wc -l)
        [[ $count -ge 2 ]] && break
        sleep 0.02
      done
      [[ $(find "$FAKE_BUILD_BARRIER" -type f | wc -l) -ge 2 ]]
    fi
    printf 'stage1\n' > "$output"
  elif [[ $role == stage1 ]]; then
    printf 'candidate\n' > "$output"
    if [[ -n ${FAKE_MUTATE_SOURCE_ON_FINAL:-} ]]; then
      printf '%s\n' "${FAKE_MUTATE_SOURCE_TEXT:-changed during final build}" \
        > "$FAKE_MUTATE_SOURCE_ON_FINAL"
    fi
  else
    exit 31
  fi
  exit 0
fi

if [[ $command_name == __source-inputs ]]; then
  case $role in
    stage1) cat "$FAKE_MANIFEST_PRE" ;;
    candidate) cat "${FAKE_MANIFEST_POST:-$FAKE_MANIFEST_PRE}" ;;
    seed) cat "$FAKE_MANIFEST_PRE" ;;
    *) exit 32 ;;
  esac
  exit 0
fi

if [[ $role == rogue ]]; then
  exit 44
fi
[[ $role == candidate ]]
printf 'fake dawn\n'

#!/usr/bin/env python3
"""Construct one compiling launcher regression for each TOOL-14 assertion."""

from __future__ import annotations

import pathlib
import sys


MUTATIONS = (
    "no-hasher-mtime",
    "skip-known-vector",
    "ignore-hasher-status",
    "ignore-hasher-shape",
    "legacy-concat",
    "ignore-missing-inputs",
    "omit-bootstrap-digest",
    "omit-inputs-digest",
    "omit-jar-digest",
    "seed-hidden-command",
    "no-final-replan",
    "inputs-only-replan",
    "shared-staging",
    "stamp-first",
    "no-post-promotion-pair",
    "no-pre-exec-pair",
    "omit-static-input",
    "track-unrelated-file",
    "accept-bad-header",
    "lax-repo-relative-path",
    "follow-symlinks",
)


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"mutation anchor matched {count} times")
    return text.replace(old, new, 1)


def replace_region(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index) + len(end)
    return text[:start_index] + replacement + text[end_index:]


if len(sys.argv) == 2 and sys.argv[1] == "--list":
    print("\n".join(MUTATIONS))
    raise SystemExit(0)
if len(sys.argv) != 3 or sys.argv[2] not in MUTATIONS:
    raise SystemExit("usage: mutate-launcher.py <launcher> <mutation>")

path = pathlib.Path(sys.argv[1])
mutation = sys.argv[2]
text = path.read_text()

if mutation == "no-hasher-mtime":
    text = replace_once(
        text,
        '''else
  echo "error: no sha256sum or shasum on PATH" >&2
  exit 1
fi
''',
        '''else
  if [ -f "$SJAR" ] &&
      ! find "$ROOT/selfhost/src" -type f -newer "$SJAR" -print -quit | grep -q .; then
    exec "$JAVA" $DAWN_JVM_OPTS -jar "$SJAR" "$@"
  fi
  echo "error: no sha256sum or shasum on PATH" >&2
  exit 1
fi
''',
    )
elif mutation == "skip-known-vector":
    text = replace_once(
        text,
        'if [ "$sha_known" != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" ]; then',
        'if [ "$sha_known" != "0000000000000000000000000000000000000000000000000000000000000000" ]; then',
    )
elif mutation == "ignore-hasher-status":
    text = replace_once(
        text,
        'if ! sha256sum > "$sha_output"; then',
        'if ! { sha256sum > "$sha_output" || true; }; then',
    )
elif mutation == "ignore-hasher-shape":
    text = replace_once(
        text,
        'if ! is_sha256_digest "$sha_digest"; then',
        'if false; then',
    )
elif mutation == "legacy-concat":
    start = "write_source_stream() (\n"
    end = "\n)\n\ncompute_manifest_digests() {"
    replacement = '''write_source_stream() (
  source_manifest=$1
  source_stream=$2
  source_work=$3
  records=$(mktemp "$source_work/legacy-records.XXXXXX") || exit 1
  merged=$(mktemp "$source_work/legacy-merged.XXXXXX") || exit 1
  files=$(mktemp "$source_work/legacy-files.XXXXXX") || exit 1
  sorted=$(mktemp "$source_work/legacy-sorted.XXXXXX") || exit 1
  write_manifest_records "$source_manifest" "$records" || exit 1
  cat "$records" > "$merged" || exit 1
  write_static_records >> "$merged" || exit 1
  : > "$files" || exit 1
  tab=$(printf '\\t')
  while IFS= read -r record || [ -n "$record" ]; do
    scope=${record%%"$tab"*}
    rest=${record#*"$tab"}
    kind=${rest%%"$tab"*}
    path=${rest#*"$tab"}
    case $scope in R) absolute=$ROOT/$path ;; A) absolute=$path ;; esac
    case $kind in
      F) printf '%s\\n' "$absolute" >> "$files" ;;
      O) [ ! -f "$absolute" ] || printf '%s\\n' "$absolute" >> "$files" ;;
      T) find "$absolute" -type f -print >> "$files" || exit 1 ;;
    esac
  done < "$merged"
  LC_ALL=C sort -u "$files" > "$sorted" || exit 1
  : > "$source_stream" || exit 1
  while IFS= read -r file || [ -n "$file" ]; do
    printf '%s\\n' "$file" >> "$source_stream" || exit 1
    cat "$file" >> "$source_stream" || exit 1
  done < "$sorted"
)

compute_manifest_digests() {'''
    text = replace_region(text, start, end, replacement)
elif mutation == "ignore-missing-inputs":
    text = replace_once(
        text,
        "validate_cache_full() {\n",
        '''validate_cache_full() {
  if [ ! -f "$INPUTS" ] && read_stamp "$STAMP"; then
    LOCKED_SOURCE=$PARSED_SOURCE
    LOCKED_BOOTSTRAP=$PARSED_BOOTSTRAP
    LOCKED_INPUTS=$PARSED_INPUTS
    LOCKED_JAR=$PARSED_JAR
    return 0
  fi
''',
    )
    text = replace_once(
        text,
        "cache_pair_matches_locked() {\n",
        '''cache_pair_matches_locked() {
  [ -f "$INPUTS" ] || return 0
''',
    )
elif mutation == "omit-bootstrap-digest":
    text = replace_once(
        text,
        '''      [ "$cache_bootstrap_now" != "$cache_bootstrap" ] ||
''',
        "",
    )
elif mutation == "omit-inputs-digest":
    text = replace_once(
        text,
        '''      [ "$cache_inputs_now" != "$cache_inputs" ] ||
''',
        "",
    )
    text = replace_once(
        text,
        '''  if [ "$pair_inputs_now" != "$LOCKED_INPUTS" ] ||
      [ "$pair_jar_now" != "$LOCKED_JAR" ]; then
''',
        '''  if [ "$pair_jar_now" != "$LOCKED_JAR" ]; then
''',
    )
elif mutation == "omit-jar-digest":
    text = replace_once(
        text,
        '''      [ "$cache_jar_now" != "$cache_jar" ]; then
''',
        '''      false; then
''',
    )
    text = replace_once(
        text,
        '''  if [ "$pair_inputs_now" != "$LOCKED_INPUTS" ] ||
      [ "$pair_jar_now" != "$LOCKED_JAR" ]; then
''',
        '''  if [ "$pair_inputs_now" != "$LOCKED_INPUTS" ]; then
''',
    )
elif mutation == "seed-hidden-command":
    text = replace_once(
        text,
        'if ! produce_manifest "$stage1" "$inputs_pre"; then',
        'if ! produce_manifest "$SEED" "$inputs_pre"; then',
    )
elif mutation == "no-final-replan":
    text = replace_once(
        text,
        '''  if ! produce_manifest "$candidate" "$inputs_post"; then
    return 1
  fi
''',
        '''  if ! cp "$inputs_pre" "$inputs_post"; then
    return 1
  fi
''',
    )
elif mutation == "inputs-only-replan":
    text = replace_once(
        text,
        '''  if ! cmp -s "$inputs_pre" "$inputs_post" ||
      ! cmp -s "$pre_stream" "$post_stream" ||
      [ "$pre_inputs" != "$post_inputs" ] ||
      [ "$pre_source" != "$post_source" ]; then
''',
        '''  if ! cmp -s "$inputs_pre" "$inputs_post" ||
      [ "$pre_inputs" != "$post_inputs" ]; then
''',
    )
elif mutation == "shared-staging":
    text = replace_once(
        text,
        '''  TXN=$(mktemp -d "$ROOT/build/.dawn-selfhost.XXXXXX") || {
    echo "error: cannot create selfhost staging directory" >&2
    return 1
  }
''',
        '''  TXN="$ROOT/build/.dawn-selfhost.shared"
  rm -rf "$TXN"
  mkdir -p "$TXN" || return 1
''',
    )
elif mutation == "stamp-first":
    text = replace_once(
        text,
        '''  if ! mv "$candidate" "$SJAR"; then
    echo "error: cannot promote selfhost candidate jar" >&2
    return 1
  fi
  if ! mv "$inputs_post" "$INPUTS"; then
    echo "error: cannot promote selfhost input manifest" >&2
    return 1
  fi
  if ! mv "$stamp_candidate" "$STAMP"; then
    echo "error: cannot commit selfhost generation marker" >&2
    return 1
  fi
''',
        '''  if ! mv "$stamp_candidate" "$STAMP"; then
    echo "error: cannot commit selfhost generation marker" >&2
    return 1
  fi
  if ! mv "$candidate" "$SJAR"; then
    echo "error: cannot promote selfhost candidate jar" >&2
    return 1
  fi
  if ! mv "$inputs_post" "$INPUTS"; then
    echo "error: cannot promote selfhost input manifest" >&2
    return 1
  fi
''',
    )
elif mutation == "no-post-promotion-pair":
    old = '''    cache_status=0
    if validate_cache_full; then
      cache_status=0
    else
      cache_status=$?
    fi
    if [ "$cache_status" -eq 2 ]; then
      exit 1
    fi
    if [ "$cache_status" -ne 0 ]; then
      cleanup_attempt
      launcher_attempt=$((launcher_attempt + 1))
      continue
    fi
'''
    new = '''    LOCKED_SOURCE=$post_source
    LOCKED_BOOTSTRAP=$build_bootstrap_after
    LOCKED_INPUTS=$post_inputs
    LOCKED_JAR=$candidate_jar
'''
    text = replace_once(text, old, new)
elif mutation == "no-pre-exec-pair":
    text = replace_once(
        text,
        '  if cache_pair_matches_locked; then\n',
        '  if true; then\n',
    )
elif mutation == "omit-static-input":
    text = replace_once(
        text,
        "  printf 'R\\tF\\tscripts/seedjar.sh\\n'\n",
        "",
    )
elif mutation == "track-unrelated-file":
    text = replace_once(
        text,
        "  printf 'R\\tF\\tbin/dawn\\n'\n",
        "  printf 'R\\tF\\tbin/dawn\\n'\n  printf 'R\\tO\\tREADME.md\\n'\n",
    )
elif mutation == "accept-bad-header":
    text = replace_once(
        text,
        '  if [ "$header" != "dawn-source-inputs-v1" ]; then',
        '  if false; then',
    )
elif mutation == "lax-repo-relative-path":
    text = replace_once(
        text,
        "          ''|.|/*|./*|../*|*/.|*/./*|..|*/..|*/../*|*//*|*/)\n",
        "          __launcher-mutant-never__)\n",
    )
elif mutation == "follow-symlinks":
    text = replace_once(
        text,
        '''      if [ -L "$entry" ]; then
        printf "%s\\n" "tree contains a symbolic link: $entry" > "$problem"
        exit 1
      fi
''',
        "",
    )
    text = replace_once(
        text,
        '          if [ -L "$leaf_file" ] || [ ! -f "$leaf_file" ]; then',
        '          if [ ! -e "$leaf_file" ]; then',
    )

path.write_text(text)

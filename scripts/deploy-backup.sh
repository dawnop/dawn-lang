#!/usr/bin/env bash
# Keep a rollback copy of what a deploy is about to replace.
#
#   deploy-backup.sh <backup-dir> <src-base> <tag> <version-spec> <src>...
#
# This file is not run from a checkout on the server: site/redeploy.sh and
# playground/deploy/redeploy.sh feed it to `ssh <host> bash -s -- ...` on
# stdin, so it must stay self-contained (no sourcing, no repo paths). It exists
# as its own file, and not as a string inside the two deploy scripts, so that
# scripts/deploy-guards/run.sh can run the very same text against a scratch
# directory and see it rotate, refuse and clean up.
#
# Why a script of its own. The backups of 2026-10-08, 10-13 and 10-14 were made
# by hand, and the rollback they bought was only as good as the memory of the
# person deploying. Three things are decided here once:
#
#  * The name is .prev-<version>-<UTC stamp>-<tag> (tag: runner or site). The
#    version is whatever the live artifact says it is, or `unknown`. Rotation
#    keeps the newest 3 per tag and sorts on the stamp, not on the whole name,
#    because "0.9.0" sorts after "0.10.0" as text.
#  * Nothing is removed except a directory this script can name exactly: a
#    direct child of <backup-dir> whose name matches the full pattern above for
#    this tag. The names are checked, never trusted, before any rm.
#  * It fails closed. The copy lands in a .partial directory and is renamed
#    only when whole, so a half copy is never mistaken for a rollback point;
#    any failure exits non-zero and the deploy stops before it replaces
#    anything. A disk too small to hold the copy twice over is a failure too:
#    filling the disk under a running service is worse than not deploying.
#
# <version-spec> is cmd:<path> (run `<path> version`, take its second word, as
# in "dawnc 0.89.0 (native) b1:...") or file:<path> (first line).
set -euo pipefail

if [ "$#" -lt 5 ]; then
  echo "usage: deploy-backup.sh <backup-dir> <src-base> <tag> <version-spec> <src>..." >&2
  exit 2
fi
backup_dir=$1 src_base=$2 tag=$3 spec=$4
shift 4

case "$tag" in
  runner|site) ;;
  *) echo "backup: unknown tag '$tag'" >&2; exit 2 ;;
esac
[ -d "$backup_dir" ] || { echo "backup: $backup_dir is not a directory" >&2; exit 1; }
[ -d "$src_base" ] || { echo "backup: $src_base is not a directory" >&2; exit 1; }
keep=3

# --- what is live now -------------------------------------------------------
version=unknown
case "$spec" in
  cmd:*)
    bin=${spec#cmd:}
    if [ -x "$bin" ]; then
      out=$(timeout 10 "$bin" version 2>/dev/null | head -n 1 || true)
      version=$(printf '%s\n' "$out" | awk '{print $2}')
    fi ;;
  file:*)
    f=${spec#file:}
    if [ -f "$f" ]; then
      version=$(head -n 1 "$f" 2>/dev/null | tr -d '[:space:]' || true)
    fi ;;
  *) echo "backup: bad version spec '$spec'" >&2; exit 2 ;;
esac
# A name goes on disk: only a plain version string is let through.
if ! printf '%s' "$version" | grep -Eq '^[0-9A-Za-z][0-9A-Za-z._+]{0,31}$'; then
  version=unknown
fi

# --- what to copy -----------------------------------------------------------
present=()
for rel in "$@"; do
  case "$rel" in
    ''|/*|*..*) echo "backup: refusing source '$rel'" >&2; exit 2 ;;
  esac
  if [ -e "$src_base/$rel" ]; then present+=("$rel"); fi
done
if [ "${#present[@]}" -eq 0 ]; then
  echo "backup: nothing under $src_base to keep (first deploy?); skipping"
  exit 0
fi

# DEPLOY_BACKUP_STAMP is for the test that makes several in one second.
stamp=${DEPLOY_BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
name=".prev-$version-$stamp-$tag"
dest="$backup_dir/$name"
partial="$dest.partial"
name_re="^\\.prev-[0-9A-Za-z._+]+-[0-9]{8}T[0-9]{6}Z-$tag\$"
printf '%s' "$name" | grep -Eq "$name_re" || { echo "backup: bad name $name" >&2; exit 1; }
if [ -e "$dest" ] || [ -e "$partial" ]; then
  echo "backup: $name already exists" >&2
  exit 1
fi

# --- room for it ------------------------------------------------------------
need_kb=$(cd "$src_base" && du -sk -- "${present[@]}" | awk '{s += $1} END {print s + 0}')
have_kb=$(df -Pk "$backup_dir" | awk 'NR == 2 {print $4}')
if [ -z "$have_kb" ] || [ "$have_kb" -lt $((need_kb * 2)) ]; then
  echo "backup: ${have_kb:-?} KB free in $backup_dir, need twice ${need_kb} KB" >&2
  exit 1
fi

# --- copy, then rename ------------------------------------------------------
# Only this script's own, just-validated partial path is ever removed here.
fail_partial() {
  case "$partial" in
    "$backup_dir"/.prev-?*.partial) rm -rf -- "$partial" ;;
  esac
  echo "backup: failed; nothing was deployed" >&2
  exit 1
}
mkdir -- "$partial" || fail_partial
(cd "$src_base" && cp -a --parents -- "${present[@]}" "$partial/") || fail_partial
mv -- "$partial" "$dest" || fail_partial
echo "backup: kept $dest ($version, ${need_kb} KB)"

# --- rotation ---------------------------------------------------------------
# The newest $keep stay. Candidates are the exact-pattern children of
# backup_dir; the stamp (the 8+T+6+Z field before the tag) orders them.
list=$(
  for p in "$backup_dir"/.prev-*-"$tag"; do
    [ -d "$p" ] || continue
    n=${p##*/}
    printf '%s' "$n" | grep -Eq "$name_re" || continue
    ts=${n%-"$tag"}
    ts=${ts##*-}
    printf '%s %s\n' "$ts" "$n"
  done | sort
)
total=$(printf '%s\n' "$list" | grep -c . || true)
if [ "$total" -gt "$keep" ]; then
  printf '%s\n' "$list" | head -n $((total - keep)) | while read -r _ old; do
    printf '%s' "$old" | grep -Eq "$name_re" || continue
    victim="$backup_dir/$old"
    case "$victim" in
      "$backup_dir"/.prev-?*) rm -rf -- "$victim"; echo "backup: removed old $old" ;;
    esac
  done
fi

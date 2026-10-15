# Shared seed-jar resolver, sourced by bin/dawn and the golden-diff scripts.
# The bootstrap seed is the previous release's dawn-selfhost.jar, named by
# scripts/seed-release.txt and cached under .dawn/seeds/ (override the cache
# with DAWN_SEED_CACHE, or point DAWN_SEED at a local jar to skip the
# download entirely — the escape hatch for offline work and seed debugging).
#
# Every seed is checked against scripts/seed-checksums.txt before it is used,
# not merely after it is downloaded. This used to fetch over HTTPS, cache the
# result forever and trust it from then on — so a replaced release asset, a
# corrupted transfer or an edited cache file would swap out the compiler that
# builds every other line of Dawn here, silently. The fixed point cannot catch
# that: B == C proves the compiler reproduces itself, which a substituted
# compiler does just as faithfully.
#
# No `local`: this file is sourced by `#!/bin/sh` scripts and `local` is not
# POSIX. Locals are spelled as prefixed names instead.

## The recorded sha256 for a tag; empty when the tag is not listed.
seed_expected_sha() {
  awk -v tag="$1" '$1 !~ /^#/ && $2 == tag { print $1; exit }' \
    "$ROOT/scripts/seed-checksums.txt" 2>/dev/null
}

seed_sha_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    echo ""
  fi
}

seed_sha_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | cut -d' ' -f1
  else
    echo ""
  fi
}

## A canonical hash of a directory tree: every regular file, sorted by relative
## path, each contributing its size, its path and its bytes. Length-prefixing
## the content is what stops two different trees from concatenating to the same
## stream. LC_ALL fixes the collation so the same tree hashes the same
## everywhere.
##
## The same shape as the compiler's `d1` package hash, in shell, because this
## runs before there is a compiler.
seed_tree_sha() {
  (
    cd "$1" 2>/dev/null || exit 0
    find . -type f | LC_ALL=C sort |
      while IFS= read -r f; do
        printf '%s %s\n' "$(wc -c < "$f" | tr -d ' ')" "$f"
        cat "$f"
      done
  ) | seed_sha_stdin
}

## The opt-out, for the two cases that genuinely cannot verify: replaying a
## pre-v0.8.0 tag, whose published asset was the Kotlin dawn.jar and is
## deliberately absent from the table, and a machine with no SHA-256 tool.
##
## It has to be spelled out, and that is the whole change. Both cases used to
## take the default path: a warning on stderr, exit 0, and a bootstrap from an
## unverified compiler. So the one occurrence that mattered -- bumping
## seed-release.txt to a new tag and forgetting to add its digest -- silently
## turned the gate off for every build and every CI job, and looked like a
## release omission rather than the loss of the trust root that it was.
seed_unverified_ok() { [ -n "${DAWN_SEED_ALLOW_UNVERIFIED:-}" ]; }

seed_refuse() {
  echo "error: $1" >&2
  echo "  This is the compiler that builds every other line of Dawn here, and" >&2
  echo "  a bootstrap that cannot check it is not one this will run." >&2
  echo "  Record the digest in scripts/seed-checksums.txt (the release workflow" >&2
  echo "  prints the line), or set DAWN_SEED_ALLOW_UNVERIFIED=1 to go ahead" >&2
  echo "  without one." >&2
  exit 1
}

## Verify $1 against the recorded hash for tag $2. A mismatch is fatal — at that
## point the only choices are to stop or to run an unknown compiler. So is a
## missing precondition: no recorded hash and no hasher are both "this was not
## checked", which is the state the check exists to prevent.
seed_verify() {
  _sv_want=$(seed_expected_sha "$2")
  if [ -z "$_sv_want" ]; then
    if seed_unverified_ok; then
      echo "warning: no recorded sha256 for seed $2, proceeding unverified" >&2
      echo "  (DAWN_SEED_ALLOW_UNVERIFIED is set)" >&2
      return 0
    fi
    seed_refuse "no recorded sha256 for seed $2 (scripts/seed-checksums.txt)"
  fi
  _sv_got=$(seed_sha_of "$1")
  if [ -z "$_sv_got" ]; then
    if seed_unverified_ok; then
      echo "warning: no sha256sum/shasum on PATH, seed $2 unverified" >&2
      return 0
    fi
    seed_refuse "no sha256sum or shasum on PATH, so seed $2 cannot be verified"
  fi
  if [ "$_sv_got" != "$_sv_want" ]; then
    echo "error: seed $2 failed checksum verification" >&2
    echo "  expected $_sv_want" >&2
    echo "  actual   $_sv_got" >&2
    echo "  file     $1" >&2
    echo "  This is the compiler that builds everything else; refusing to use it." >&2
    exit 1
  fi
}

## The java that runs a seed jar: the one bin/dawn runs its own toolchain on.
## A differential that puts the seed on PATH's java and the head on
## bin/dawn's JDK compares two JDKs as well as two compilers, and a JDK
## difference then reads as a toolchain one (issue #267). bin/dawn owns the
## probe; this asks it rather than keeping a second copy that could drift.
seed_java() {
  DAWN_LAUNCHER_PRINT_JAVA=1 "$ROOT/bin/dawn"
}

## Where a tagged release's assets are downloaded from. The repository is
## named once, in scripts/repo.env (DAWN_GITHUB_REPO in the environment wins).
## Read only when a download is about to happen, so a root that never
## downloads (the contract harnesses copy this file alone) needs no repo.env.
## Not a recorded bootstrap input (bin/dawn's write_static_records): the URL
## does not decide which seed is trusted, seed-checksums.txt does.
seed_release_base() {
  _sr_repo=${DAWN_GITHUB_REPO:-$(. "$ROOT/scripts/repo.env" && printf '%s' "$DAWN_GITHUB_REPO")}
  if [ -z "$_sr_repo" ]; then
    echo "error: scripts/repo.env names no DAWN_GITHUB_REPO" >&2
    exit 1
  fi
  echo "https://github.com/$_sr_repo/releases/download"
}

## Cold-cache concurrency. Several launchers starting at once on a fresh
## checkout all find the seed cache empty and all fill it; with fixed temp
## names one reads seed.jar.tmp while another still writes it (the first
## symptom was "SHA-256 input is not a regular non-symbolic-link file" and
## "cannot resolve bootstrap seed" out of four parallel `dawn doc` runs).
## Two rules fix it: every writer stages under a name of its own (mktemp in the
## destination directory, so the final rename never crosses a filesystem), and
## the fetch is serialised by a lock directory, so the download happens once
## and the others wait for the published file instead of racing it.
##
## mkdir as the lock rather than flock(1): macOS ships no flock, mkdir is
## atomic everywhere, and the one thing flock buys -- the kernel dropping the
## lock when its holder dies -- is replaced by a pid file: a lock whose
## holder is gone is taken over. The holder is a pid on this host, which is
## the only place two launchers can share a checkout.
seed_lock_acquire() {
  _sl_dir=$1
  _sl_done=${2:-}
  _sl_deadline=$(($(date +%s) + ${DAWN_LOCK_TIMEOUT:-900}))
  while ! mkdir "$_sl_dir" 2>/dev/null; do
    # a waiter that sees the holder's result stops waiting: queueing every
    # waiter through the lock just to find the work done costs a poll tick each
    if [ -n "$_sl_done" ] && [ -f "$_sl_done" ]; then
      return 2
    fi
    _sl_pid=$(cat "$_sl_dir/pid" 2>/dev/null || true)
    if [ -n "$_sl_pid" ] && ! kill -0 "$_sl_pid" 2>/dev/null; then
      # holder is gone; two takers may both get here, but only one mkdir wins
      rm -f "$_sl_dir/pid"
      rmdir "$_sl_dir" 2>/dev/null || true
      continue
    fi
    if [ "$(date +%s)" -ge "$_sl_deadline" ]; then
      echo "error: timed out waiting for $_sl_dir" >&2
      echo "  if no other dawn is running, remove that directory and retry" >&2
      return 1
    fi
    # fractional sleep is not POSIX but GNU and macOS both have it
    sleep 0.2 2>/dev/null || sleep 1
  done
  echo "$$" > "$_sl_dir/pid"
}

seed_lock_release() {
  rm -f "$1/pid"
  rmdir "$1" 2>/dev/null || true
}

## Run "$@" holding the lock directory $1, unless the file $2 appears first
## (the result being waited for), in which case there is nothing left to do.
## A subshell, so that the `exit 1` the verify helpers use on a bad seed still
## releases the lock (the trap) and surfaces as a nonzero status for the caller.
seed_locked() {
  _sk_lock=$1
  _sk_done=$2
  shift 2
  (
    _sk_rc=0
    seed_lock_acquire "$_sk_lock" "$_sk_done" || _sk_rc=$?
    [ "$_sk_rc" -eq 2 ] && exit 0
    [ "$_sk_rc" -eq 0 ] || exit 1
    trap 'seed_lock_release "$_sk_lock"' 0
    trap 'exit 1' 1 2 15
    "$@"
  )
}

## Download, verify and publish the seed jar; run under the cache lock.
seed_jar_fetch() {
  [ -f "$1/seed.jar" ] && return 0
  mkdir -p "$1"
  echo "fetching $2 seed jar..." >&2
  _sf_tmp=$(mktemp "$1/seed.jar.XXXXXX") || return 1
  if ! curl -fsSL -o "$_sf_tmp" "$(seed_release_base)/$2/dawn-selfhost.jar"; then
    rm -f "$_sf_tmp"
    return 1
  fi
  # verified before it is promoted to the cache, so a bad download cannot
  # become the copy every later run trusts
  if ! (seed_verify "$_sf_tmp" "$2"); then
    rm -f "$_sf_tmp"
    return 1
  fi
  mv "$_sf_tmp" "$1/seed.jar"
}

seed_jar() {
  # An explicitly pointed-at jar is the debugging escape hatch: it is not the
  # pinned release, so there is nothing to check it against. Say so rather than
  # let it pass as if it had been verified.
  if [ -n "${DAWN_SEED:-}" ]; then
    echo "warning: using DAWN_SEED=$DAWN_SEED (unverified)" >&2
    echo "$DAWN_SEED"
    return
  fi
  _sj_tag=$(tr -d ' \n' < "$ROOT/scripts/seed-release.txt")
  _sj_cache=${DAWN_SEED_CACHE:-$ROOT/.dawn/seeds}/$_sj_tag
  if [ ! -f "$_sj_cache/seed.jar" ]; then
    mkdir -p "$_sj_cache"
    seed_locked "$_sj_cache.lock" "$_sj_cache/seed.jar" seed_jar_fetch "$_sj_cache" "$_sj_tag" || exit 1
  fi
  # verified on every use, including the run that just fetched it: the
  # cache is a mutable directory on disk, and a waiter that did not download
  # has not checked anything yet
  seed_verify "$_sj_cache/seed.jar" "$_sj_tag"
  echo "$_sj_cache/seed.jar"
}

## The recorded tree hash for a tag's std; empty when the tag is not listed.
seed_std_expected_sha() {
  awk -v tag="$1" '$1 !~ /^#/ && $2 == tag { print $1; exit }' \
    "$ROOT/scripts/seed-std-checksums.txt" 2>/dev/null
}

## Verify the std tree at $1 against the recorded hash for tag $2, on the same
## terms as the jar: every use, and fail-closed when the check cannot be made.
##
## The jar was checked and the std it pairs with was not — `modules.txt` exists,
## use it. Both are stage-1 inputs, the cache directory is writable, and a tag
## can be moved, so half the bootstrap could be swapped with the jar's checksum
## and the whole trust narrative none the wiser. B == C cannot see it either:
## a substituted std reproduces into the next generation as faithfully as
## anything else.
seed_std_verify() {
  _sd_want=$(seed_std_expected_sha "$2")
  if [ -z "$_sd_want" ]; then
    if seed_unverified_ok; then
      echo "warning: no recorded tree hash for the std of seed $2, proceeding unverified" >&2
      return 0
    fi
    seed_refuse "no recorded tree hash for the std of seed $2 (scripts/seed-std-checksums.txt)"
  fi
  _sd_got=$(seed_tree_sha "$1")
  if [ -z "$_sd_got" ]; then
    if seed_unverified_ok; then
      echo "warning: no sha256sum/shasum on PATH, the std of seed $2 is unverified" >&2
      return 0
    fi
    seed_refuse "no sha256sum or shasum on PATH, so the std of seed $2 cannot be verified"
  fi
  if [ "$_sd_got" != "$_sd_want" ]; then
    echo "error: the std of seed $2 failed verification" >&2
    echo "  expected $_sd_want" >&2
    echo "  actual   $_sd_got" >&2
    echo "  tree     $1" >&2
    echo "  This is half of what builds the compiler that builds everything" >&2
    echo "  else; refusing to use it. Delete the directory and re-run to" >&2
    echo "  re-extract it from the tag." >&2
    exit 1
  fi
}

## Extract and publish the seed's std; run under the cache lock. Staged in a
## directory of its own and renamed into place only once verified, so no
## reader ever sees a half-written tree.
seed_std_extract() {
  [ -f "$1/modules.txt" ] && return 0
  # A fresh CI checkout is shallow and tagless (actions/checkout defaults:
  # depth 1, no tags), so the seed's tag is usually absent there. Fetch just
  # that tag before asking archive for it; offline with the tag already
  # present never reaches the fetch.
  git -C "$ROOT" rev-parse -q --verify "refs/tags/$2" > /dev/null ||
    git -C "$ROOT" fetch -q --depth 1 origin tag "$2" || true
  _se_stage=$(mktemp -d "$1.XXXXXX") || return 1
  if ! git -C "$ROOT" archive "$2" std | tar -x -C "$_se_stage"; then
    echo "error: cannot extract std/ from tag $2 (the seed's released std)" >&2
    echo "  the tag is not in this clone, and fetching it from origin failed" >&2
    rm -rf "$_se_stage"
    return 1
  fi
  # verified while it is still staged, so a bad extract never becomes the
  # copy every later run trusts: the jar's rule, applied to its other half
  if ! (seed_std_verify "$_se_stage/std" "$2"); then
    rm -rf "$_se_stage"
    return 1
  fi
  # a directory without modules.txt is debris from an older interrupted run
  rm -rf "$1"
  mv "$_se_stage/std" "$1"
  rmdir "$_se_stage"
}

## The std the pinned seed released with, extracted from its git tag and
## cached beside the jar. The seed pairs with the std it shipped: since #44
## knife 2 the repo's std may use prelude machinery (the Iter trait) that is
## one generation ahead of the seed's checker, so handing the seed today's
## std/ is handing it modules it cannot check. The released pair is also the
## honest reference — it is the combination that release's gates actually ran.
seed_std_dir() {
  _ss_tag=$(tr -d ' \n' < "$ROOT/scripts/seed-release.txt")
  _ss_dir=${DAWN_SEED_CACHE:-$ROOT/.dawn/seeds}/std-$_ss_tag
  if [ ! -f "$_ss_dir/modules.txt" ]; then
    mkdir -p "$(dirname "$_ss_dir")"
    seed_locked "$_ss_dir.lock" "$_ss_dir/modules.txt" seed_std_extract "$_ss_dir" "$_ss_tag" || exit 1
  fi
  # and on every use: the cache is a mutable directory on disk
  seed_std_verify "$_ss_dir" "$_ss_tag"
  echo "$_ss_dir"
}

## A working root for seed subcommands that read `std` from the cwd and take
## no --std flag (lsp) or take many shapes of argument (the run-diff sweep):
## every top-level repo entry symlinked in place, except std, which is the
## seed's released std. Relative targets resolve unchanged; only the std the
## seed sees moves back one generation.
seed_root() {
  _sr_dir=$1
  _sr_std=$(seed_std_dir)
  mkdir -p "$_sr_dir"
  for _sr_e in "$ROOT"/* "$ROOT"/.dawn; do
    [ -e "$_sr_e" ] || continue
    _sr_b=$(basename "$_sr_e")
    [ "$_sr_b" = "std" ] && continue
    [ -e "$_sr_dir/$_sr_b" ] || ln -s "$_sr_e" "$_sr_dir/$_sr_b"
  done
  ln -s "$_sr_std" "$_sr_dir/std"
}

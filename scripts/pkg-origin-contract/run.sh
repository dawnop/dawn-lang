#!/usr/bin/env bash
# The url/hash guard on the package cache, end to end through the CLI.
#
#   ./scripts/pkg-origin-contract/run.sh
#
# The cache is content-addressed, so a manifest that bumps `[deps.x] url` to a
# new tag and leaves `hash` alone resolves the *old* tree out of a warm cache
# and builds green with nothing to read. Measured against v0.57.0 on
# 2026-08-07, case 3 below printed the previous package's output and exited 0.
# Only a warm cache can do it — a cold one fetches the new url and the hash
# mismatch is caught already — which is why the fixture builds the cache first
# and why every case runs against the same $DAWN_PKG_CACHE.
#
# Everything is a file:// url, so this needs no network and no curl: the
# fetcher reads the bytes off disk, which exercises the same decision.
#
# What that sentence leaves out is that `download` short-circuits a file:// url
# and never enters `http_get`, so nothing here has ever seen a command line.
# The counterpart is in the tree: compiler-plan/src/pkgfetch.dawn's tests
# answer `Proc` from `procmem.with_proc_table` and assert curl's argv element
# by element, its refusal text, and the fetch chain on a non-file:// url. They
# run in `dawn test compiler-plan`; the check below only holds the pointer to
# them from going stale, because running them again here would repeat a job CI
# already has.
#
# Case 2 proves the warm path does *not* re-fetch by deleting the archive
# first: a run that still succeeds cannot have gone back to the url.
#
# DAWN_BIN points it at another toolchain, which is how the mutation check was
# run (v0.57.0 fails case 3 and passes the rest). It is a JVM-side gate: the
# native driver has neither `__pkghash` nor `cache verify`, and without the
# fixture hashes every case would pass vacuously -- so the hashes are checked
# for shape before anything else runs.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}

out=$(mktemp -d "${TMPDIR:-/tmp}/pkg-origin-contract.XXXXXX")
trap 'rm -rf "$out"' EXIT

fail=0
check() { # label expected-exit actual-exit transcript
  if [ "$2" = "$3" ]; then
    echo "PASS  $1"
  else
    echo "FAIL: $1 (expected exit $2, got $3)" >&2
    sed 's/^/  | /' "$4" >&2
    fail=1
  fi
}

# The in-tree counterpart named in the header. A rename is fine; a deletion
# leaves the claim above unbacked, and that is what this refuses.
counterpart="$root/compiler-plan/src/pkgfetch.dawn"
for t in "curl is asked for exactly the command line" \
         "a curl refusal is reported" \
         "unpacks, hashes and lands in the cache"; do
  grep -qF "$t" "$counterpart" || {
    echo "FAIL: no in-tree test for \"$t\" in $counterpart" >&2
    echo "  the header's \"no network and no curl\" claim has no counterpart any more" >&2
    exit 1; }
done

mk_pkg() { # dir greeting
  mkdir -p "$1/src"
  printf 'schema = 1\nname = "greeter"\nversion = "1.0.0"\n' > "$1/dawn.toml"
  printf 'pub fn greet(who: String) -> String = "%s, " ++ who\n' "$2" > "$1/src/hello.dawn"
}

zip_of() { # srcdir dst
  python3 - "$1" "$2" <<'EOF'
import os, sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dst, 'w') as z:
    for root, _, files in os.walk(src):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, src))
EOF
}

manifest() { # url hash
  cat > "$out/app/dawn.toml" <<EOF
schema = 1
name = "urlapp"

[deps.g]
url = "$1"
version = "1.0.0"
hash = "$2"
EOF
}

run_app() { # -> exit code, transcript in $out/t.txt
  DAWN_PKG_CACHE="$out/cache" "$dawn" run "$out/app" > "$out/t.txt" 2>&1
}

mk_pkg "$out/v1" hello
mk_pkg "$out/v2" goodbye
zip_of "$out/v1" "$out/v1.zip"
zip_of "$out/v2" "$out/v2.zip"
h1=$("$dawn" __pkghash "$out/v1" 2>/dev/null)
h2=$("$dawn" __pkghash "$out/v2" 2>/dev/null)
for h in "$h1" "$h2"; do
  case "$h" in
    d1:*) ;;
    *) echo "FAIL: $dawn printed no package hash -- this gate needs a toolchain with \`__pkghash\`" >&2
       exit 1 ;;
  esac
done
[ "$h1" != "$h2" ] || { echo "FAIL: the two fixture packages hash the same" >&2; exit 1; }

mkdir -p "$out/app/src"
cat > "$out/app/src/main.dawn" <<'EOF'
use g/hello

pub fn main() -> Unit !io = println(hello.greet("x"))
EOF

# 1. cold cache: the ordinary fetch, which is also what records the origin
manifest "file://$out/v1.zip" "$h1"
run_app && e=0 || e=$?
check "cold cache fetches and verifies" 0 "$e" "$out/t.txt"
[ "$(cat "$out/t.txt")" = "hello, x" ] || { echo "FAIL: wrong package linked" >&2; fail=1; }

# 2. warm cache, nothing changed: no re-fetch, so the archive can be gone
mv "$out/v1.zip" "$out/v1.hidden"
run_app && e=0 || e=$?
check "warm cache resolves without going back to the url" 0 "$e" "$out/t.txt"
mv "$out/v1.hidden" "$out/v1.zip"

# 3. the trap: url bumped, hash left behind. Refused, naming both hashes.
manifest "file://$out/v2.zip" "$h1"
run_app && e=0 || e=$?
check "url bumped with a stale hash is refused" 1 "$e" "$out/t.txt"
grep -q "url changed but hash did not" "$out/t.txt" || {
  echo "FAIL: the refusal does not name the cause" >&2; sed 's/^/  | /' "$out/t.txt" >&2; fail=1; }
grep -q "$h2" "$out/t.txt" || {
  echo "FAIL: the refusal does not print the actual hash to copy" >&2; fail=1; }

# 4. url and hash bumped together: the ordinary upgrade, and the new package
manifest "file://$out/v2.zip" "$h2"
run_app && e=0 || e=$?
check "url and hash bumped together upgrade" 0 "$e" "$out/t.txt"
[ "$(cat "$out/t.txt")" = "goodbye, x" ] || { echo "FAIL: wrong package linked" >&2; fail=1; }

# 5. a mirror: a different url serving the same bytes is legitimate, and the
#    guard must not turn it into an error
cp "$out/v2.zip" "$out/mirror.zip"
manifest "file://$out/mirror.zip" "$h2"
run_app && e=0 || e=$?
check "a mirror url for the same bytes is accepted" 0 "$e" "$out/t.txt"

# 6. ... and is remembered, so it costs one fetch and not one per build
mv "$out/mirror.zip" "$out/mirror.hidden"
run_app && e=0 || e=$?
check "the accepted mirror is recorded, not re-fetched" 0 "$e" "$out/t.txt"
mv "$out/mirror.hidden" "$out/mirror.zip"

# 7. the record is metadata beside the entries, never inside one: a file under
#    an entry would change its tree hash and fail `dawn cache verify`
origins="$out/cache/.origins/$(printf '%s' "$h2" | tr ':' '-')"
[ -f "$origins" ] || { echo "FAIL: no origin record at $origins" >&2; fail=1; }
[ "$(wc -l < "$origins")" = "2" ] || {
  echo "FAIL: expected two urls recorded for $h2" >&2; cat "$origins" >&2; fail=1; }
DAWN_PKG_CACHE="$out/cache" "$dawn" cache verify > "$out/t.txt" 2>&1 && e=0 || e=$?
check "the cache still verifies with origin records present" 0 "$e" "$out/t.txt"

# 8. TOOL-09: a planted entry whose *name* is a legitimate hash. The guard
#    fetches the url, gets the right bytes, and used to drop them on the floor
#    because a directory of that name was already there -- then record the url
#    against the hash anyway. One cache injection, blessed forever, by the very
#    code that exists to notice. The record is deleted first because that is
#    what makes check_origin fetch at all; an entry with a record is trusted
#    without content verification either way (PKG-02's stated scope).
entry="$out/cache/$(printf '%s' "$h1" | tr ':' '-')"
rm -f "$out/cache/.origins/$(printf '%s' "$h1" | tr ':' '-')"
printf 'pub fn greet(who: String) -> String = "tampered, " ++ who\n' > "$entry/src/hello.dawn"
manifest "file://$out/v1.zip" "$h1"
run_app && e=0 || e=$?
check "a planted cache entry is refused, not blessed" 1 "$e" "$out/t.txt"
grep -q "does not match its own name" "$out/t.txt" || {
  echo "FAIL: the refusal does not say the entry disagrees with its own name" >&2
  sed 's/^/  | /' "$out/t.txt" >&2; fail=1; }
[ ! -f "$out/cache/.origins/$(printf '%s' "$h1" | tr ':' '-')" ] || {
  echo "FAIL: an origin record was written for the planted entry" >&2; fail=1; }

exit "$fail"

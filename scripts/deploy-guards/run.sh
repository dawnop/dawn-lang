#!/usr/bin/env bash
# The refusals in site/redeploy.sh and playground/deploy/redeploy.sh, driven
# against the cases they exist to refuse, without touching a server.
#
#   ./scripts/deploy-guards/run.sh              # every case, then every mutant
#   ./scripts/deploy-guards/run.sh --no-mutants # cases only
#
# A deploy guard is invisible when it works: the run that should have been
# refused is the one that ships the wrong commit, and a green deploy and an
# unguarded deploy print the same thing. So each case here is a deploy that
# must stop, with the evidence that it stopped for the stated reason (the
# refusal text) and before the step it protects (no rsync or ssh in the call
# log). The controls matter as much: a script that refuses everything passes
# every refusal case, so the green runs must reach rsync and exit 0.
#
# How it stays offline. Both scripts resolve their repo from their own
# location, so each case builds a throwaway git checkout holding a copy of the
# real script plus stubs for what it calls (bin/dawn, site/build.sh, a
# "native" binary); ssh, rsync, scp, curl and sudo are PATH shims that only
# append to a call log (and fail on demand, by pattern, to stand in for a
# server that lacks something). The environment is cleared per run, so a
# DEPLOY_USER or DAWN_* in the caller's shell cannot leak in.
#
# Mutants. For each refusal case a mutant removes exactly the guard it covers
# (a literal substitution in the script copy; one that matches nothing is an
# error, so a reworded guard cannot quietly void its mutant) and the same case
# must then FAIL. That is the negative control: the case is shown to be able
# to see the guard go.
#
# The two scripts repeat the commit check verbatim on purpose: each must be
# runnable alone from a checkout, and a sourced helper would put a third file
# between the guard and the thing it guards. They are tested by the same case
# shapes instead.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/deploy-guards.XXXXXX")"
trap 'rm -rf "$work"' EXIT

shims="$work/shims"
mkdir -p "$shims" "$work/home"
for t in ssh rsync scp curl sudo; do
  cat >"$shims/$t" <<'SH'
#!/bin/sh
printf '%s %s\n' "$(basename "$0")" "$*" >>"$STUB_LOG"
if [ -n "${SSH_FAIL:-}" ] && printf '%s' "$*" | grep -q -- "$SSH_FAIL"; then
  exit 1
fi
# The routing read (redeploy.sh REMOTE_ROUTING, marked by `: nginx-routing`)
# gets what the stubbed server's nginx would print: $STUB_ROUTING is the
# proxy_pass target of its /api/run location, or unset when it has none.
if [ "$(basename "$0")" = ssh ] && [ -n "${STUB_ROUTING:-}" ] &&
    printf '%s' "$*" | grep -q -- ': nginx-routing'; then
  printf '%s\n' "$STUB_ROUTING"
fi
exit 0
SH
  chmod +x "$shims/$t"
done

NOMUT=0
[ "${1:-}" = "--no-mutants" ] && NOMUT=1

fail=0
ok() { echo "PASS  $1"; }
bad() { echo "FAIL: $1" >&2; fail=1; }

# --- a throwaway checkout ---------------------------------------------------
# mkrepo <site|play>: sets R. $MUT, if set, is "from=>to" applied once.
n=0
mkrepo() {
  n=$((n + 1))
  R="$work/r$n"
  mkdir -p "$R/site" "$R/scripts" "$R/bin" "$R/selfhost/src" "$R/playground/deploy"
  cp "$root/scripts/repo.env" "$R/scripts/"
  cp "$root/site/redeploy.sh" "$R/site/redeploy.sh"
  cp "$root/playground/deploy/redeploy.sh" "$R/playground/deploy/redeploy.sh"
  if [ -n "${MUT:-}" ]; then
    local f="$R/site/redeploy.sh"
    [ "$1" = play ] && f="$R/playground/deploy/redeploy.sh"
    local from="${MUT%%=>*}" to="${MUT#*=>}" body new
    body="$(cat "$f"; printf x)"; body="${body%x}"
    new="${body/"$from"/"$to"}"
    if [ "$new" = "$body" ]; then
      echo "error: mutant '$from' matches nothing in $f" >&2
      exit 2
    fi
    printf '%s' "$new" >"$f"
  fi
  printf '#!/bin/sh\necho "dawn 9.9.9 b1:aaaaaaaaaaaa (selfhost)"\n' >"$R/bin/dawn"
  printf 'pub const VERSION: String = "9.9.9"\n' >"$R/selfhost/src/version.dawn"
  cat >"$R/site/build.sh" <<'SH'
#!/bin/sh
# Stub generator. BUILD_MODE picks what it leaves behind.
echo build >>"$STUB_LOG"
echo "$DAWN_WASM_CC" >"$STUB_LOG.cc"
mkdir -p site/build/tea site/dist/assets site/dist/zh
magic() { printf '\000asm\001\000\000\000' >"$1"; }
for name in counter todo search; do
  case "$BUILD_MODE:$name" in
    stale:counter) magic site/dist/assets/tea-$name.wasm ;; # leave the old build/ file
    missing:todo) magic site/build/tea/$name.wasm ;;   # dist copy never written
    placeholder:search) echo "wasm unavailable" >site/build/tea/$name.wasm
                        magic site/dist/assets/tea-$name.wasm ;;
    *) magic site/build/tea/$name.wasm; magic site/dist/assets/tea-$name.wasm ;;
  esac
done
o="$DAWN_SITE_PLAY_ORIGIN"
echo "<div data-endpoint=\"$o/api/run\"></div>" >site/dist/playground.html
if [ "$BUILD_MODE" = badpage ]; then o=https://elsewhere.test; fi
echo "<div data-endpoint=\"$o/api/run\"></div>" >site/dist/zh/playground.html
SH
  chmod +x "$R/bin/dawn" "$R/site/build.sh"
  git -C "$R" init -q
  git -C "$R" -c user.name=t -c user.email=t@t -c commit.gpgsign=false \
    -c core.hooksPath=/dev/null add -A
  git -C "$R" -c user.name=t -c user.email=t@t -c commit.gpgsign=false \
    -c core.hooksPath=/dev/null commit -q -m fixture
  HEAD_SHA="$(git -C "$R" rev-parse HEAD)"
}

# mknative <path> <version line> <health body>
mknative() {
  cat >"$1" <<SH
#!/bin/sh
case "\$1" in
  version) echo '$2' ;;
  serve) cat >/dev/null; printf 'HTTP/1.1 200 OK\r\n\r\n%s' '$3' ;;
esac
SH
  chmod +x "$1"
}

# deploy <site|play> [env args...]: run the copy in $R with a cleared
# environment plus a good baseline; later args (VAR=x, -u VAR) win.
OUT="$work/out"; ERR="$work/err"; LOG="$work/log"
deploy() {
  local kind="$1"; shift
  : >"$LOG"; rm -f "$LOG.cc"
  local script="$R/site/redeploy.sh"
  [ "$kind" = play ] && script="$R/playground/deploy/redeploy.sh"
  env -i PATH="$shims:/usr/bin:/bin" HOME="$work/home" STUB_LOG="$LOG" \
    DEPLOY_USER=u DAWN_DEPLOY_COMMIT="$HEAD_SHA" \
    DAWN_SITE_PLAY_ORIGIN=https://play.example.test BUILD_MODE=ok \
    DAWN_NATIVE_BIN="$work/dawnc" DAWN_PLAY_NATIVE_BIN="$work/dawn-play" \
    env "$@" bash "$script" >"$OUT" 2>"$ERR"
  RC=$?
}

# refused <stderr pattern> <call-log pattern that must NOT appear>
refused() {
  [ "$RC" -ne 0 ] || { echo "  exit 0, wanted a refusal" >&2; return 1; }
  grep -Eq -- "$1" "$ERR" || { echo "  stderr lacks /$1/: $(head -c 300 "$ERR")" >&2; return 1; }
  if grep -Eq -- "$2" "$LOG"; then
    echo "  step ran that the guard protects: $(grep -E -- "$2" "$LOG" | head -1)" >&2
    return 1
  fi
}
shipped() { # exit 0, reached rsync, printed the closing line
  [ "$RC" -eq 0 ] && grep -q '^rsync' "$LOG" && grep -q '=== done ===' "$OUT"
}
GOODNATIVE() {
  mknative "$work/dawnc" 'dawnc 9.9.9 (native) b1:0123456789ab' x
  mknative "$work/dawn-play" x '{"ok":true,"version":"9.9.9"}'
}
NOSHIP='^(rsync|ssh)'
NOBUILD='^(build|rsync|ssh)'
OTHER=0123456789012345678901234567890123456789

# --- cases: each returns 0 when the script behaved ---------------------------
c_s_commit_unset()   { mkrepo site; deploy site -u DAWN_DEPLOY_COMMIT; refused 'DAWN_DEPLOY_COMMIT must be the full 40-hex' "$NOBUILD"; }
c_s_commit_short()   { mkrepo site; deploy site DAWN_DEPLOY_COMMIT="${HEAD_SHA:0:12}"; refused 'DAWN_DEPLOY_COMMIT must be the full 40-hex' "$NOBUILD"; }
c_s_commit_other()   { mkrepo site; deploy site DAWN_DEPLOY_COMMIT=$OTHER; refused 'is not the requested commit' "$NOBUILD"; }
c_s_dirty()          { mkrepo site; echo x >>"$R/scripts/repo.env"; deploy site; refused 'uncommitted changes to tracked files' "$NOBUILD"; }
c_s_no_user()        { mkrepo site; deploy site -u DEPLOY_USER; refused 'set DEPLOY_USER' "$NOBUILD"; }
c_s_origin_unset()   { mkrepo site; deploy site -u DAWN_SITE_PLAY_ORIGIN; refused 'DAWN_SITE_PLAY_ORIGIN is unset or empty' "$NOBUILD"; }
c_s_origin_empty()   { mkrepo site; deploy site DAWN_SITE_PLAY_ORIGIN=; refused 'DAWN_SITE_PLAY_ORIGIN is unset or empty' "$NOBUILD"; }
c_s_origin_path()    { mkrepo site; deploy site DAWN_SITE_PLAY_ORIGIN=https://play.example.test/; refused 'not an origin' "$NOBUILD"; }
c_s_wasm_missing()   { mkrepo site; deploy site BUILD_MODE=missing; refused 'tea-todo.wasm is missing' "$NOSHIP"; }
c_s_wasm_placeholder() { mkrepo site; deploy site BUILD_MODE=placeholder; refused 'tea/search.wasm is not wasm' "$NOSHIP"; }
c_s_wasm_stale() {
  mkrepo site; mkdir -p "$R/site/build/tea"
  printf '\000asm\001\000\000\000' >"$R/site/build/tea/counter.wasm"
  touch -d '2020-01-01' "$R/site/build/tea/counter.wasm"
  deploy site BUILD_MODE=stale
  refused 'tea/counter.wasm was not rebuilt by this run' "$NOSHIP"
}
c_s_page_origin()    { mkrepo site; deploy site BUILD_MODE=badpage; refused 'zh/playground.html does not carry' "$NOSHIP"; }
c_s_cc_default() {
  mkrepo site; deploy site; shipped || return 1
  [ "$(cat "$LOG.cc")" = clang-20 ] || { echo "  build saw DAWN_WASM_CC=$(cat "$LOG.cc")" >&2; return 1; }
}
c_s_cc_override() {
  mkrepo site; deploy site DAWN_WASM_CC=clang-99; shipped || return 1
  [ "$(cat "$LOG.cc")" = clang-99 ]
}
c_s_green_purge_fails() { mkrepo site; deploy site SSH_FAIL=refresh-dirs; shipped && grep -q 'CDN purge failed' "$ERR"; }

c_p_commit_unset()   { mkrepo play; GOODNATIVE; deploy play -u DAWN_DEPLOY_COMMIT; refused 'DAWN_DEPLOY_COMMIT must be the full 40-hex' "$NOSHIP"; }
c_p_commit_other()   { mkrepo play; GOODNATIVE; deploy play DAWN_DEPLOY_COMMIT=$OTHER; refused 'is not the requested commit' "$NOSHIP"; }
c_p_dirty()          { mkrepo play; GOODNATIVE; echo x >>"$R/scripts/repo.env"; deploy play; refused 'uncommitted changes to tracked files' "$NOSHIP"; }
c_p_no_user()        { mkrepo play; GOODNATIVE; deploy play -u DEPLOY_USER; refused 'set DEPLOY_USER' "$NOSHIP"; }
c_p_native_missing() { mkrepo play; GOODNATIVE; rm "$work/dawnc"; deploy play; refused 'release-native.sh' "$NOSHIP"; }
c_p_native_version() { mkrepo play; GOODNATIVE; mknative "$work/dawnc" 'dawnc 0.0.1 (native)' x; deploy play; refused 'native artifact says' "$NOSHIP"; }
c_p_native_tail()    { mkrepo play; GOODNATIVE; mknative "$work/dawnc" 'dawnc 9.9.9 (native) b1:zzz' x; deploy play; refused 'native artifact says' "$NOSHIP"; }
c_p_runner_missing() { mkrepo play; GOODNATIVE; rm "$work/dawn-play"; deploy play; refused 'DAWN_PLAY_NATIVE=0' "$NOSHIP"; }
c_p_runner_health()  { mkrepo play; GOODNATIVE; mknative "$work/dawn-play" x '{"ok":true,"version":"0.0.1"}'; deploy play; refused 'does not answer /health as release 9.9.9' "$NOSHIP"; }
c_p_remote_cmds()    { mkrepo play; GOODNATIVE; deploy play SSH_FAIL='command -v'; refused 'server lacks a command' '^rsync'; }
c_p_jdk()            { mkrepo play; GOODNATIVE; deploy play SSH_FAIL='-version'; refused 'install the pinned JDK' '^rsync'; }
c_p_canary() {
  mkrepo play; GOODNATIVE; deploy play SSH_FAIL='canary-check'
  refused 'native canary failed its check' 'NEVER_MATCHES_ZZZ' && grep -q 'systemctl restart dawn-play' "$LOG"
}
c_p_native_off() { mkrepo play; GOODNATIVE; rm "$work/dawn-play"; deploy play DAWN_PLAY_NATIVE=0; shipped; }
c_p_green()      { mkrepo play; GOODNATIVE; deploy play; shipped && grep -q 'canary-check' "$LOG"; }

# The routing line is read from the server, not assumed (#682). The stub prints
# the /api/run proxy_pass target; the deploy must say what it is.
c_p_route_jvm() {
  mkrepo play; GOODNATIVE; deploy play STUB_ROUTING=http://127.0.0.1:8087/run
  shipped && grep -q 'nginx routes /api/run to the JVM runner' "$OUT" && ! grep -q 'native runner (' "$OUT"
}
c_p_route_native() {
  mkrepo play; GOODNATIVE; deploy play STUB_ROUTING=http://unix:/run/dawn-play/http.sock:/run
  shipped && grep -q 'nginx routes /api/run to the native runner' "$OUT" && ! grep -q 'JVM runner (' "$OUT"
}
c_p_route_unknown() {
  mkrepo play; GOODNATIVE; deploy play
  shipped && grep -q 'cannot tell which runner nginx routes' "$OUT" && ! grep -q 'nginx routes /api/run to the' "$OUT"
}
c_p_route_odd() {
  mkrepo play; GOODNATIVE; deploy play STUB_ROUTING=http://10.9.9.9:1/run
  shipped && grep -q 'unrecognised upstream' "$OUT"
}
c_p_route_native_off() { # the line is printed without a canary too
  mkrepo play; GOODNATIVE; rm "$work/dawn-play"
  deploy play DAWN_PLAY_NATIVE=0 STUB_ROUTING=http://unix:/run/dawn-play/http.sock:/run
  shipped && grep -q 'to the native runner' "$OUT"
}

# What each mutant removes, as "from=>to". "-" = a control: nothing to remove.
mutant_for() {
  case "$1" in
    c_s_commit_unset|c_s_commit_short|c_p_commit_unset)
      echo "if ! printf '%s' \"\$want_commit\" | grep -Eq '^[0-9a-f]{40}\$'; then=>if false; then" ;;
    c_s_commit_other|c_p_commit_other) echo '[ "$have_commit" != "$want_commit" ]=>false' ;;
    c_s_dirty|c_p_dirty)
      echo 'if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then=>if false; then' ;;
    c_s_no_user|c_p_no_user) echo '${DEPLOY_USER:?set DEPLOY_USER to the server login name}=>${DEPLOY_USER:-u}' ;;
    c_s_origin_unset|c_s_origin_empty) echo 'if [ -z "$play_origin" ]; then=>if false; then' ;;
    c_s_origin_path) echo "if ! printf '%s' \"\$play_origin\" | grep -Eq=>if false; then : | grep -Eq" ;;
    c_s_wasm_missing) echo 'if [ ! -f "$f" ]; then=>if false; then' ;;
    c_s_wasm_placeholder) echo 'elif ! is_wasm "$f"; then=>elif false; then' ;;
    c_s_wasm_stale) echo '[ ! "$f" -nt "$stamp" ]=>false' ;;
    c_s_page_origin) echo 'if ! grep -qF "data-endpoint=\"$play_origin/api/run\"" "$page" 2>/dev/null; then=>if false; then' ;;
    c_s_cc_default) echo '${DAWN_WASM_CC:-clang-20}=>${DAWN_WASM_CC:-clang}' ;;
    c_p_native_missing) echo 'if [ ! -x "$NATIVE_BIN" ]; then=>if false; then' ;;
    c_p_native_version) echo 'NATIVE_BUILD=${NATIVE_VERSION#"dawnc $VERSION (native)"}=>NATIVE_BUILD=' ;;
    c_p_native_tail) echo '[0123456789abcdef]{12}=>.*' ;;
    c_p_runner_missing) echo 'if [ ! -x "$PLAY_NATIVE_BIN" ]; then=>if false; then' ;;
    c_p_runner_health) echo "*'\"ok\":true,\"version\":\"'\"\$VERSION\"'\"'*) ;;=>*) ;;" ;;
    c_p_remote_cmds) echo "if ! ssh \"\$HOST\" 'PATH=/usr=>if ! true \"\$HOST\" 'PATH=/usr" ;;
    c_p_jdk) echo "if ! ssh \"\$HOST\" \"'\$PLAY_JDK_REMOTE/bin/java'=>if ! true \"\$HOST\" \"'\$PLAY_JDK_REMOTE/bin/java'" ;;
    c_p_canary) echo 'if ! ssh "$HOST" "$REMOTE_CANARY"; then=>if ! true "$HOST" "$REMOTE_CANARY"; then' ;;
    # the old hard-coded claim: native and unknown must then fail
    c_p_route_jvm|c_p_route_native|c_p_route_unknown|c_p_route_odd|c_p_route_native_off)
      echo 'echo "$ROUTING_LINE"=>echo "nginx still routes to the JVM runner."' ;;
    *) echo - ;;
  esac
}

cases="$(declare -F | awk '$3 ~ /^c_/ {print $3}')"
for c in $cases; do
  MUT=""
  if "$c"; then ok "$c"; else bad "$c"; fi
done

if [ "$NOMUT" = 0 ]; then
  for c in $cases; do
    m="$(mutant_for "$c")"
    [ "$m" = - ] && continue
    MUT="$m"
    if "$c" 2>/dev/null; then
      bad "mutant of $c survived: the case does not see its guard go"
    else
      ok "mutant of $c is caught"
    fi
  done
fi
MUT=""
exit "$fail"

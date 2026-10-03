#!/bin/sh
# Contract test for dawn-play: boots the runner in local (direct) mode, drives
# /run through every branch, checks the JSON responses, then shuts it down.
# Requires: a built dawn.jar, a JDK, python3 (for JSON assertions), curl.
set -e
cd "$(dirname "$0")/.."
ROOT=$(cd .. && pwd)

# The WebSocket/LSP bridge has an independent stdlib-only fake child, so its
# framing, lifecycle and admission contract does not depend on a Dawn build.
./test/lsp-contract.sh

# Both layouts: macOS bundles the JDK under Contents/Home, Linux tarballs put
# bin/ at the top level. Same probe as bin/dawn.
if [ -z "$JAVA_HOME" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home "$HOME"/tools/graalvm-*; do
    [ -x "$d/bin/java" ] && JAVA_HOME="$d" && break
  done
fi
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
export DAWN_BIN="$ROOT/bin/dawn"
export PLAY_JAVA="$JAVA_HOME/bin/java"
export PLAY_TIMEOUT=3
export PLAY_COMPILE_TIMEOUT=60
# The sandbox is on unless something opts out (config.sandbox_enabled is
# fail-closed since the audit). There is no systemd-run wrapper on a dev box or
# in CI, so this harness is exactly the caller that has to say so.
export PLAY_UNSAFE_LOCAL=1
# The work root is this run's own, so the run-output case below can name the
# exact directory that must not reach a response (dawn-lang #401).
WORK=$(mktemp -d "${TMPDIR:-/tmp}/dawn-play-work.XXXXXX")
export PLAY_WORK_ROOT="$WORK"
# The port is asked of the kernel, not fixed: two copies of this test on one
# machine (another checkout, an external gate run) would otherwise race for it,
# and a fixed low port also collides with WSL2's WinNAT reservations (the bind
# fails with "Address already in use" against a port `ss` shows as free).
# Binding 127.0.0.1:0 is the same address the runner listens on, so a port the
# kernel hands out here is one the runner can take. The window between this
# probe closing and the runner binding is not closed; the stale-server check
# below turns a lost race into a red run, never a green one against someone
# else's server. PLAY_TEST_PORT still pins it explicitly.
if [ -n "${PLAY_TEST_PORT:-}" ]; then
  PORT=$PLAY_TEST_PORT
else
  PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
fi
export PLAY_PORT=$PORT
echo "port: $PORT"

# A stale server on the port would answer every check while the fresh one
# dies on bind — fail fast instead of green-lighting an orphan.
if curl -s --noproxy '*' "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "FAIL: something already listens on $PORT (stale server?)"; exit 1
fi

LOG=$(mktemp "${TMPDIR:-/tmp}/dawn-play-test.XXXXXX")
# The runner starts in a session (and so a process group) of its own, whose id
# is its pid: `dawn run` executes the program in a child JVM that outlives its
# parent, and killing the group reaches that child without looking anyone up
# by port. The old cleanup ran `fuser -k` on the port, which on a shared
# machine kills whatever else holds it. python3 does the setsid because it is
# already required here and, unlike setsid(1), exists on macOS.
python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' \
  "$DAWN_BIN" run "$ROOT/playground" >"$LOG" 2>&1 &
SRV=$!
# Guards keep a failed kill from turning into the script's exit status (dash:
# set -e applies inside an EXIT trap). The log is kept on failure only. The
# runner is outside the terminal's process group now, so ^C no longer reaches
# it; the signal traps route through exit so the EXIT trap still kills it.
# `kill -TERM -PGID`, not `kill -- -PGID`: dash's builtin rejects the latter.
trap 'kill -TERM "-$SRV" 2>/dev/null; rm -rf "${WORK:?}"; [ "${fail:-1}" = "0" ] && rm -f "$LOG" || echo "runner log: $LOG"; true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
# the runner prints "listening" once the socket is open
for _ in $(seq 1 30); do
  curl -s --noproxy '*' "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 0.3
done

pass=0
fail=0
# The assertion sees the parsed body as `d` and the bytes as `raw`: a JSON
# parser reads 0 and 0.0 as equal, so the integer fields are checked on `raw`.
check() { # name, curl-data, python-assertion, [endpoint (default: run)]
  body=$(curl -s --noproxy '*' -X POST --data "$2" "http://127.0.0.1:$PORT/${4:-run}")
  if printf '%s' "$body" | python3 -c "import os,sys,json,re; raw=sys.stdin.read(); d=json.loads(raw); assert ($3), d" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $body"
  fi
}

health=$(curl -s --noproxy '*' "http://127.0.0.1:$PORT/health" || true)
echo "health: $health"
# The editor's toolbar shows this version; a release always has three parts.
# `build` is the short build-manifest digest the runner's compiler prints last
# on its --version line (docs/build-info-design.md); the runner here compiles
# with $DAWN_BIN, so the two must be the same word.
want_build=$("$DAWN_BIN" --version 2>/dev/null | sed -n 's/^dawn .* \(b1:[0-9a-f]*\)$/\1/p' | tail -n 1)
if printf '%s' "$health" | WANT_BUILD="$want_build" python3 -c "import os,sys,json,re; d=json.load(sys.stdin); assert d['ok'] is True and re.fullmatch(r'[0-9]+[.][0-9]+[.][0-9]+', d['version']) and re.fullmatch(r'b1:[0-9a-f]{12}', d['build']) and d['build'] == os.environ['WANT_BUILD'], d" 2>/dev/null; then
  pass=$((pass + 1)); echo "  ok  health carries the compiler version and build"
else
  fail=$((fail + 1)); echo "FAIL  health carries the compiler version and build (want build '$want_build')"
fi

check "hello runs, exit 0" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  'd["ok"] and d["phase"]=="run" and d["exit"]==0 and d["output"]=="hi\n"'

check "exit and ms are JSON integers" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  '"\"exit\":0" in raw and "\"exit\":0." not in raw and re.search(r"\"ms\":[0-9]+[,}]", raw)'

check "compile error, path sanitized" \
  '{"code":"pub fn main() -> Unit !io = println(nope)"}' \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn" in d["output"] and "/var/" not in d["output"] and "T/dawn-play" not in d["output"]'

# The panic names where it was called (spec 8.2), from the tree's own path,
# so the user sees the line and column of the program they typed.
check "runtime panic names its call site, exit 1" \
  '{"code":"pub fn main() -> Unit !io = panic(\"boom\")"}' \
  'd["phase"]=="run" and d["exit"]==1 and "panic: boom at prog.dawn:1:29\n" in d["output"]'

# A failing `x!` prints the position the compiler baked into the program.
# That used to be the path the runner handed `dawn build`, which is under the
# work root, so a user saw the server's directory. The position is now the
# file's own name, and the run output goes through the same strip as the
# compile output, so neither the work root nor the staging directory shows.
check "run output never names the work root" \
  '{"code":"fn f() -> Option[Int] = None\npub fn main() -> Unit !io = println(to_string(f()!))"}' \
  'd["phase"]=="run" and d["exit"]==1 and "unwrapped None from f() at prog.dawn:2" in d["output"] and os.environ["PLAY_WORK_ROOT"] not in d["output"] and "dawn-play-" not in d["output"]'

check "infinite loop times out" \
  '{"code":"fn s(n: Int) -> Unit !io = s(n+1)\npub fn main() -> Unit !io = {\n  println(\"x\")\n  s(0)\n}"}' \
  'not d["ok"] and d["phase"]=="timeout" and d["output"]=="x\n"'

check "/check on good code -> all-clear, no run" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  'd["ok"] and d["phase"]=="check" and "output" not in d and re.search(r"\"ms\":[0-9]+[,}]", raw)' \
  check

check "/check on bad code -> compile diagnostics" \
  '{"code":"pub fn main() -> Unit !io = println(nope)"}' \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn" in d["output"] and "undefined" in d["output"]' \
  check

check "bad JSON -> error" \
  'not json at all' \
  'not d["ok"] and d["phase"]=="error"'

check "missing code -> error" \
  '{"foo":1}' \
  'not d["ok"] and "code" in d["output"]'

# large body -> 413 (checked via status, not JSON body)
big=$(python3 -c 'print("{\"code\":\"" + "/"*70000 + "\"}")')
code=$(printf '%s' "$big" | curl -s --noproxy '*' -o /dev/null -w '%{http_code}' -X POST --data @- "http://127.0.0.1:$PORT/run")
[ "$code" = "413" ] && { pass=$((pass+1)); echo "  ok  oversized body -> 413"; } || { fail=$((fail+1)); echo "FAIL  oversized body -> $code"; }

# GET -> 405
code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/run")
[ "$code" = "405" ] && { pass=$((pass+1)); echo "  ok  GET -> 405"; } || { fail=$((fail+1)); echo "FAIL  GET -> $code"; }

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" = "0" ]

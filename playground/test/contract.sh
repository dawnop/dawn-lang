#!/bin/sh
# Contract test for dawn-play: boots the runner in local (direct) mode, drives
# /run through every branch, checks the JSON responses, then shuts it down.
# Requires: a built dawn.jar, a JDK, python3 (for JSON assertions), curl.
set -e
cd "$(dirname "$0")/.."
ROOT=$(cd .. && pwd)

if [ -z "$JAVA_HOME" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home; do
    [ -x "$d/bin/java" ] && JAVA_HOME="$d" && break
  done
fi
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
export DAWN_BIN="$ROOT/bin/dawn"
export PLAY_JAVA="$JAVA_HOME/bin/java"
export PLAY_TIMEOUT=3
PORT=8097
export PLAY_PORT=$PORT

"$DAWN_BIN" run "$ROOT/playground" >/tmp/dawn-play-test.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
# the runner prints "listening" once the socket is open
for _ in $(seq 1 30); do
  curl -s --noproxy '*' "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 0.3
done

pass=0
fail=0
check() { # name, curl-data, python-assertion, [endpoint (default: run)]
  body=$(curl -s --noproxy '*' -X POST --data "$2" "http://127.0.0.1:$PORT/${4:-run}")
  if printf '%s' "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); assert ($3), d" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $body"
  fi
}

echo "health: $(curl -s --noproxy '*' "http://127.0.0.1:$PORT/health")"

check "hello runs, exit 0" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  'd["ok"] and d["phase"]=="run" and d["exit"]==0 and d["output"]=="hi\n"'

check "compile error, path sanitized" \
  '{"code":"pub fn main() -> Unit !io = println(nope)"}' \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn" in d["output"] and "/var/" not in d["output"] and "T/dawn-play" not in d["output"]'

check "runtime panic, exit 1" \
  '{"code":"pub fn main() -> Unit !io = panic(\"boom\")"}' \
  'd["phase"]=="run" and d["exit"]==1 and "panic: boom" in d["output"]'

check "infinite loop times out" \
  '{"code":"fn s(n: Int) -> Unit !io = s(n+1)\npub fn main() -> Unit !io = {\n  println(\"x\")\n  s(0)\n}"}' \
  'not d["ok"] and d["phase"]=="timeout" and d["output"]=="x\n"'

check "/check on good code -> all-clear, no run" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  'd["ok"] and d["phase"]=="check" and "output" not in d' \
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

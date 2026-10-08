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

# The run wrapper's argument contract, which is all of it that runs without
# sudo and systemd: an action, a 32-hex unit id, and for `run` a work dir and
# a command. Everything else is refused (exit 2) before anything is executed,
# and a work dir outside the work roots is refused with 3.
WRAP=sandbox/run-sandboxed.sh
sh -n "$WRAP"
ID=0123456789abcdef0123456789abcdef
wrap_refuses() { # expected-status, args...
  want=$1; shift
  st=0; sh "$WRAP" "$@" >/dev/null 2>&1 || st=$?
  [ "$st" = "$want" ] || { echo "FAIL: run-sandboxed.sh $* exited $st, expected $want"; exit 1; }
}
wrap_refuses 2
wrap_refuses 2 /tmp/dawn-play-x true
wrap_refuses 2 run abc /tmp/dawn-play-x true
wrap_refuses 2 run "$ID" /tmp/dawn-play-x
wrap_refuses 2 stop ../../x
wrap_refuses 2 stop 0123456789ABCDEF0123456789abcdef
wrap_refuses 2 stop "$ID" extra
wrap_refuses 3 run "$ID" /etc true
echo "  ok  the run wrapper takes only run/stop with a unit id"

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
# /compile lists the class with javap, which belongs to the same JDK as java.
export PLAY_JAVAP="$JAVA_HOME/bin/javap"
# The Tile IR view imports the packages the runner's manifest names.
export PLAY_PACKAGES="$ROOT/packages"
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
#
# It also starts in the POSIX locale with no LANG, which is the environment a
# systemd unit gives the compilers it starts: file names are then ASCII to the
# JVM, and the /compile cases with non-ASCII names only pass because the
# runner asks for a UTF-8 locale on those commands (play/exec.utf8_env).
python3 -c 'import os, sys; os.setsid(); os.environ.pop("LANG", None); os.environ["LC_ALL"] = "POSIX"; os.execvp(sys.argv[1], sys.argv[1:])' \
  "$DAWN_BIN" run "$ROOT/playground" >"$LOG" 2>&1 &
SRV=$!
# Guards keep a failed kill from turning into the script's exit status (dash:
# set -e applies inside an EXIT trap). The log is kept on failure only. The
# runner is outside the terminal's process group now, so ^C no longer reaches
# it; the signal traps route through exit so the EXIT trap still kills it.
# `kill -TERM -PGID`, not `kill -- -PGID`: dash's builtin rejects the latter.
trap 'kill -TERM "-$SRV" 2>/dev/null; rm -rf "${WORK:?}" "${WORK:?}.cases"; rm -f "${WORK:?}.canary"; [ "${fail:-1}" = "0" ] && rm -f "$LOG" || echo "runner log: $LOG"; true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
# Wait for /health against a deadline, not a count of tries. `dawn run`
# compiles the runner before the socket opens, and the old 30 tries of 0.3 s
# (9 s) were gone before that finished on a loaded machine: every check after
# then failed against a closed port, and /health reported an empty build that
# read like another runner's. A runner that never answers is still red, at
# the deadline, with its own log rather than fifteen downstream failures; one
# that dies is red as soon as neither its pid nor its process group is
# left (the pid alone right after the fork: setsid may not have run yet).
# PLAY_TEST_HEALTH_WAIT moves the deadline (seconds).
HEALTH_WAIT=${PLAY_TEST_HEALTH_WAIT:-60}
wait_started=$(date +%s)
deadline=$((wait_started + HEALTH_WAIT))
waited=""
until curl -s --noproxy '*' --max-time 5 -o /dev/null "http://127.0.0.1:$PORT/health"; do
  if ! kill -0 "$SRV" 2>/dev/null && ! kill -0 "-$SRV" 2>/dev/null; then
    waited="exited before /health answered"; break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    waited="did not answer /health within ${HEALTH_WAIT}s"; break
  fi
  sleep 0.3
done
if [ -n "$waited" ]; then
  echo "FAIL: the runner $waited (PLAY_TEST_HEALTH_WAIT=$HEALTH_WAIT)"
  echo "---- runner log, last 40 lines"
  tail -n 40 "$LOG" || true
  exit 1
fi
echo "runner answered /health after $(($(date +%s) - wait_started))s"

pass=0
fail=0
# Every request is bounded, so a runner that never answers is a red case and
# not a hung test: the compile budget, the run budget and a margin.
REQ_MAX=$((PLAY_COMPILE_TIMEOUT + PLAY_TIMEOUT + 10))
# The assertion sees the parsed body as `d` and the bytes as `raw`: a JSON
# parser reads 0 and 0.0 as equal, so the integer fields are checked on `raw`.
check() { # name, curl-data, python-assertion, [endpoint (default: run)]
  body=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$2" "http://127.0.0.1:$PORT/${4:-run}" || true)
  if printf '%s' "$body" | python3 -c "import os,sys,json,re; raw=sys.stdin.read(); d=json.loads(raw); assert ($3), d" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $body"
  fi
}

health=$(curl -s --noproxy '*' --max-time 10 "http://127.0.0.1:$PORT/health" || true)
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

# The child's output files live beside its box, not in it, and the runner
# reads them back without following a link or opening anything but a regular
# file. Unsandboxed, the program runs as the runner's own user and can reach
# them, which is what lets these cases swap them; under the sandbox it cannot
# write that directory at all. `code_json` builds the request from a program
# with the canary path or the swap command spliced in. The output is empty
# rather than "before the swap": the runner refuses what it finds at the name,
# and an empty answer is also the proof that the swap happened.
CANARY="$WORK.canary"
printf 'canary-%s\n' "$$" >"$CANARY"
code_json() { # program text with @CMD@ replaced by a shell command
  python3 -c 'import json,sys; print(json.dumps({"code": sys.stdin.read().replace("@CMD@", sys.argv[1].replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34)).replace("$", chr(92) + "$"))}))' "$1" <<'DAWN'
use std/str
use java "java.lang.ProcessBuilder"
use java "java.lang.System"

pub fn main() -> Unit !io = {
  println("before the swap")
  let jar = System.getProperty("java.class.path").expect("cp")
  let here = str.take(jar, str.len(jar) - str.len("/prog.jar"))
  let cmd = "for f; do [ -e \"\$f\" ] && { @CMD@; }; done; true"
  ProcessBuilder.new(["sh", "-c", cmd, "sh", here ++ "/run.txt", here ++ "/../run.txt"]).start().expect("sh").waitFor()
  println("after the swap")
}
DAWN
}

check "an output file swapped for a link does not leak its target" \
  "$(code_json "ln -sf '$CANARY' \"\$f\"")" \
  'd["phase"]=="run" and d["output"]==""'

# A FIFO never reaches end of file. Twice, because MAX_CONCURRENT is 2: a
# runner that blocked on each would hold both permits and the hello after
# them would wait out the queue and answer 429.
check "an output file swapped for a FIFO does not hang the request" \
  "$(code_json 'rm -f "$f" && mkfifo "$f"')" \
  'd["phase"]=="run" and d["output"]==""'
check "a second FIFO swap does not hang it either" \
  "$(code_json 'rm -f "$f" && mkfifo "$f"')" \
  'd["phase"]=="run" and d["output"]==""'
check "the gate is free after both" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  'd["ok"] and d["output"]=="hi\n"'

# A thousand times the output limit. The runner reads one byte past the limit
# and no more, so this answers truncated with the response capped, where the
# old read held the whole file before truncating it.
check "huge output answers truncated, capped at the limit" \
  '{"code":"use std/str\npub fn main() -> Unit !io = {\n  let s = str.repeat(\"x\", 65536)\n  for i in range(0, 1000) { print(s) }\n}"}' \
  'd["phase"]=="run" and d["exit"]==0 and d["truncated"] is True and len(d["output"].encode()) <= 65536 + 64 and d["output"].endswith("(output truncated)")'

check "/check on good code -> all-clear, no run" \
  '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}' \
  'd["ok"] and d["phase"]=="check" and "output" not in d and re.search(r"\"ms\":[0-9]+[,}]", raw)' \
  check

check "/check on bad code -> compile diagnostics" \
  '{"code":"pub fn main() -> Unit !io = println(nope)"}' \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn" in d["output"] and "undefined" in d["output"]' \
  check

# ---- POST /compile: the program's C text or JVM listing, paired with the source
#
# The programs the cases send are files, built here, so a program is read once
# and sent as exactly what it is: a starter, a program of odd names, and two
# generated ones that are over the answer's limits.
CASES="$WORK.cases"
mkdir -p "$CASES"
python3 - "$CASES" "$ROOT" <<'PY'
import sys
out, root = sys.argv[1], sys.argv[2]
open(f"{out}/starter.dawn", "w", encoding="utf-8").write(open(f"{root}/site/play-ui/samples/fizzbuzz.dawn", encoding="utf-8").read())
# non-ASCII names for a function, a type and a constructor, a string with an
# astral character and every escape, and a comment with a tab
open(f"{out}/odd.dawn", "w", encoding="utf-8").write(
    '# comment with a tab\there and a 中文 word\n'
    'type Wéird = | A_1 | B\n'
    'fn größe(x: Int) -> Int = x + 1\n'
    'fn _a__b(x: Int) -> Int = größe(x) * 2\n'
    'pub fn main() -> Unit !io = {\n'
    '  let s = "line1\\nline2 \\"q\\" \\\\ \U0001F600 中"\n'
    '  println(s ++ to_string(_a__b(3)))\n'
    '}\n')
# 1,500 small functions: far more listing than a pane may carry
open(f"{out}/wide.dawn", "w").write(
    "".join(f"pub fn f{i}(x: Int) -> Int = x * {i} + x\n" for i in range(1500))
    + 'pub fn main() -> Unit !io = println(to_string(f1(2)))\n')
# 2,500 calls: more than an answer carries
open(f"{out}/many.dawn", "w").write(
    'pub fn main() -> Unit !io = {\n' + '  println("x")\n' * 2500 + '}\n')
open(f"{out}/fresh.dawn", "w").write('pub fn main() -> Unit !io = println("fresh")\n')
open(f"{out}/broken.dawn", "w").write('pub fn main() -> Unit !io = println(nope)\n')
# a Tile IR program, and the same program that also imports a package the
# manifest does not name
tile = open(f"{root}/playground/test/tile_vadd.dawn", encoding="utf-8").read()
open(f"{out}/tile.dawn", "w", encoding="utf-8").write(tile)
open(f"{out}/tile_smuggle.dawn", "w", encoding="utf-8").write("use json/value.{Json}\npub fn smuggled(j: Json) -> Json = j\n" + tile)
PY
compile_body() { # program file, target
  python3 -c 'import json,sys; print(json.dumps({"code": open(sys.argv[1], encoding="utf-8").read(), "target": sys.argv[2]}))' "$1" "$2"
}
# One /compile request whose answer is kept (in $CASES/resp.N, the previous
# one's name in $PREV) for the next case to compare with.
RESP_N=0
PREV=""
ccheck() { # name, program file, target, python-assertion
  RESP_N=$((RESP_N + 1))
  out="$CASES/resp.$RESP_N"
  curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$(compile_body "$2" "$3")" \
    "http://127.0.0.1:$PORT/compile" >"$out" || true
  if PREV="$PREV" python3 -c "import os,sys,json,re; raw=sys.stdin.read(); d=json.loads(raw); prev=json.load(open(os.environ['PREV'])) if os.environ['PREV'] else None; assert ($4), d" <"$out" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $(head -c 600 "$out")"
  fi
  PREV="$out"
}

# What a good answer is made of, whichever target: the head, a call table whose
# ids are its rows, a pane whose accounts of its lines stay inside its text and
# whose marks stay inside their lines, and no trace of where the runner works.
SOUND='d["ok"] is True and d["phase"]=="compile-view" and d["gaps"]["count"]==0 and [c["id"] for c in d["calls"]]==list(range(len(d["calls"]))) and all(c["parent"]<c["id"] for c in d["calls"]) and d["pane"]["shown"]==len(d["pane"]["text"]) and [o["call"] for o in d["pane"]["outs"]]==list(range(len(d["pane"]["outs"]))) and all(1<=a<z<=d["pane"]["shown"]+1 for o in d["pane"]["outs"] for a,z in o["lines"]) and all(1<=l<=d["pane"]["shown"] and 0<=a<=z<=len(d["pane"]["text"][l-1]) for o in d["pane"]["outs"] for l,a,z in o["marks"]) and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw and re.search(r"\"ms\":[0-9]+[,}]", raw)'

ccheck "compile: the C text of a starter, no gap, its calls placed in it" "$CASES/starter.dawn" c \
  "$SOUND"' and d["target"]=="c" and d["cached"] is False and d["pane"]["kind"]=="c" and len(d["calls"])>=1 and any("prog__main" in l for l in d["pane"]["text"]) and any(o["marks"] for o in d["pane"]["outs"]) and re.fullmatch(r"b1:[0-9a-f]{12}", d["build"])'

ccheck "compile: the same program again is a hit that differs only in its head" "$CASES/starter.dawn" c \
  'd["cached"] is True and prev is not None and {k:v for k,v in d.items() if k not in ("cached","ms")}=={k:v for k,v in prev.items() if k not in ("cached","ms")}'

ccheck "compile: the JVM listing of it is the other half of the same build, already kept" "$CASES/starter.dawn" jvm \
  "$SOUND"' and d["target"]=="jvm" and d["cached"] is True and d["pane"]["kind"]=="jvm" and any(o["key"] for o in d["pane"]["outs"]) and any("invokestatic" in l for l in d["pane"]["text"]) and d["calls"]==prev["calls"]'

ccheck "compile: names outside ASCII map with no gap (JVM)" "$CASES/odd.dawn" jvm \
  "$SOUND"' and any("größe" in l for l in d["pane"]["text"]) and d["cached"] is False'
ccheck "compile: and so does the C text of them" "$CASES/odd.dawn" c \
  "$SOUND"' and d["cached"] is True and len(d["calls"])>=3'

# The program that does not compile gets /check's diagnostics, word for word,
# and the same for either target, the second from the cache.
ccheck "compile: an error carries the diagnostics, without the work directory" "$CASES/broken.dawn" c \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn:1" in d["output"] and "undefined variable: nope" in d["output"] and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw and "cached" not in d'
checked=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$(python3 -c 'import json,sys; print(json.dumps({"code": open(sys.argv[1]).read()}))' "$CASES/broken.dawn")" "http://127.0.0.1:$PORT/check" || true)
if printf '%s' "$checked" | CASE="$PREV" python3 -c "import os,sys,json; assert json.load(sys.stdin) == json.load(open(os.environ['CASE']))" 2>/dev/null; then
  pass=$((pass + 1)); echo "  ok  compile: the diagnostics are /check's, byte for byte"
else
  fail=$((fail + 1)); echo "FAIL  compile: the diagnostics are /check's, byte for byte"; echo "        $checked"
fi
ccheck "compile: the same error for the other target" "$CASES/broken.dawn" jvm \
  'not d["ok"] and d["phase"]=="compile" and d == prev'

# ---- the Tile IR view: the program is run, its output is the pane.
#
# Expected text: what `dawn run` prints for the same program as a project with
# the same two package dependencies.
TILE_PROJ="$CASES/tileproj"
mkdir -p "$TILE_PROJ/src"
cp "$CASES/tile.dawn" "$TILE_PROJ/src/main.dawn"
printf 'schema = 1\nname = "tp"\nversion = "0.0.0"\n\n[deps]\ntileir = "%s/packages/tileir"\ntileref = "%s/packages/tileref"\n' "$ROOT" "$ROOT" >"$TILE_PROJ/dawn.toml"
"$DAWN_BIN" run "$TILE_PROJ" >"$CASES/tile.expected" 2>/dev/null || true
tile_ccheck() { # name, program file, extra request fields (JSON object), assertion
  RESP_N=$((RESP_N + 1))
  out="$CASES/resp.$RESP_N"
  curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST \
    --data "$(python3 -c 'import json,sys; d={"code": open(sys.argv[1], encoding="utf-8").read(), "target": "tile"}; d.update(json.loads(sys.argv[2])); print(json.dumps(d))' "$2" "$3")" \
    "http://127.0.0.1:$PORT/compile" >"$out" || true
  if EXPECTED="$CASES/tile.expected" python3 -c "import os,sys,json,re; raw=sys.stdin.read(); d=json.loads(raw); expected=open(os.environ['EXPECTED'], encoding='utf-8').read(); assert ($4), d" <"$out" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $(head -c 600 "$out")"
  fi
}
tile_ccheck "compile: a tileir program's pane is the text dawn run prints" "$CASES/tile.dawn" '{}' \
  'len(expected)>200 and d["ok"] is True and d["phase"]=="compile-view" and d["target"]=="tile" and d["cached"] is False and d["pane"]["kind"]=="tile" and "\n".join(d["pane"]["text"])+"\n"==expected and d["pane"]["shown"]==len(d["pane"]["text"]) and d["pane"]["truncated"] is False and "calls" not in d and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw'
tile_ccheck "compile: a dependency the visitor supplies is not honoured, so another package does not resolve" "$CASES/tile_smuggle.dawn" "{\"dawn_toml\": \"schema = 1\\nname = \\\"x\\\"\\nversion = \\\"0.0.0\\\"\\n[deps]\\ntileir = \\\"$ROOT/packages/tileir\\\"\\njson = \\\"$ROOT/packages/json\\\"\\n\"}" \
  'd["ok"] is False and d["phase"]=="compile" and "json" in d["output"] and "pane" not in d'

# The two limits. 1,500 functions list to more than 256 KB; 2,500 calls are
# more than 2,000. Each answer is cut, says so, and is still a sound answer.
ccheck "compile: a pane past its byte limit is cut at a line and says so" "$CASES/wide.dawn" jvm \
  "$SOUND"' and d["pane"]["truncated"] is True and d["pane"]["shown"]<d["pane"]["total"] and sum(len(l.encode())+1 for l in d["pane"]["text"])<=262144 and sum(len(l.encode())+1 for l in d["pane"]["text"])>262144-400'
ccheck "compile: calls past 2,000 are left out, counted and the rest stays whole" "$CASES/many.dawn" c \
  "$SOUND"' and d["calls_truncated"] is True and len(d["calls"])==2000 and d["calls_total"]==2500 and len(d["pane"]["outs"])==2000'
ccheck "compile: a program inside both limits is not marked cut" "$CASES/starter.dawn" c \
  'd["pane"]["truncated"] is False and d["calls_truncated"] is False and d["calls_total"]==len(d["calls"])'

# Refusals before anything runs.
body_status() { # data, expected status
  got=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -o "$CASES/refusal" -w '%{http_code}' -X POST --data "$1" "http://127.0.0.1:$PORT/compile" || true)
  [ "$got" = "$2" ]
}
refuses() { # name, data, status, text the refusal must name
  if body_status "$2" "$3" && grep -q "$4" "$CASES/refusal" && grep -q '"phase":"error"' "$CASES/refusal"; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1 (wanted $3 naming $4)"; echo "        $(head -c 300 "$CASES/refusal")"
  fi
}
refuses "compile: a target that is not offered is 400" '{"code":"x","target":"asm"}' 400 'target'
refuses "compile: tile for a program that does not import tileir is 400, in one sentence" '{"code":"pub fn main() -> Unit !io = println(\"hi\")","target":"tile"}' 400 'imports tileir'
refuses "compile: no target is 400" '{"code":"x"}' 400 'missing field'
refuses "compile: a target that is not a string is 400" '{"code":"x","target":3}' 400 'must be a string'
refuses "compile: no code is 400" '{"target":"c"}' 400 'code'
refuses "compile: bad JSON is 400" 'not json' 400 'invalid JSON'
bigc=$(python3 -c 'print("{\"target\":\"c\",\"code\":\"" + "/"*70000 + "\"}")')
if body_status "$bigc" 413; then
  pass=$((pass + 1)); echo "  ok  compile: an oversized body is 413"
else
  fail=$((fail + 1)); echo "FAIL  compile: an oversized body is 413 (got $got)"
fi
code=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/compile" || true)
[ "$code" = "405" ] && { pass=$((pass+1)); echo "  ok  compile: GET -> 405"; } || { fail=$((fail+1)); echo "FAIL  compile: GET -> $code"; }

# /compile shares /check's two permits and its two-second patience. Two runs of
# a program that never ends hold both permits for the run budget (3 s) and the
# compile before it; a compile that arrives meanwhile is turned away at two
# seconds. A /compile with a gate of its own would be let in and answer 200.
SPIN='{"code":"fn s(n: Int) -> Unit !io = s(n+1)\npub fn main() -> Unit !io = {\n  println(\"x\")\n  s(0)\n}"}'
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$SPIN" "http://127.0.0.1:$PORT/run" >/dev/null &
SPIN1=$!
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$SPIN" "http://127.0.0.1:$PORT/run" >/dev/null &
SPIN2=$!
sleep 0.7
unique=$(python3 -c 'import json; print(json.dumps({"code": "pub fn main() -> Unit !io = println(\"saturated\")", "target": "c"}))')
if body_status "$unique" 429 && grep -q 'server busy' "$CASES/refusal"; then
  pass=$((pass + 1)); echo "  ok  compile: with both permits held it is turned away with 429"
else
  fail=$((fail + 1)); echo "FAIL  compile: with both permits held it is turned away with 429 (got $got)"; echo "        $(head -c 300 "$CASES/refusal")"
fi
wait "$SPIN1" "$SPIN2" || true
ccheck "compile: the permits come back" "$CASES/fresh.dawn" c 'd["ok"] is True and d["cached"] is False'

check "bad JSON -> error" \
  'not json at all' \
  'not d["ok"] and d["phase"]=="error"'

check "missing code -> error" \
  '{"foo":1}' \
  'not d["ok"] and "code" in d["output"]'

# large body -> 413 (checked via status, not JSON body)
big=$(python3 -c 'print("{\"code\":\"" + "/"*70000 + "\"}")')
code=$(printf '%s' "$big" | curl -s --noproxy '*' --max-time "$REQ_MAX" -o /dev/null -w '%{http_code}' -X POST --data @- "http://127.0.0.1:$PORT/run" || true)
[ "$code" = "413" ] && { pass=$((pass+1)); echo "  ok  oversized body -> 413"; } || { fail=$((fail+1)); echo "FAIL  oversized body -> $code"; }

# GET -> 405
code=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/run" || true)
[ "$code" = "405" ] && { pass=$((pass+1)); echo "  ok  GET -> 405"; } || { fail=$((fail+1)); echo "FAIL  GET -> $code"; }

# Every request above, including the ones that timed out, failed to compile
# or had their output swapped, removed its own directory.
left=$(find "$WORK" -mindepth 1 -maxdepth 1 -name 'dawn-play-*' | head -n 5)
if [ -z "$left" ]; then
  pass=$((pass + 1)); echo "  ok  no request directory left in the work root"
else
  fail=$((fail + 1)); echo "FAIL  request directories left in the work root:"; echo "$left"
fi

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" = "0" ]

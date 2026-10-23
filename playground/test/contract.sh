#!/bin/sh
# Contract test for dawn-play: boots the runner in local (direct) mode, drives
# /run, /check and /compile through every branch, checks the JSON responses
# and the access log, then shuts it down.
# Requires: a built dawn.jar, a JDK, a C compiler (CC, default cc), python3
# (for JSON assertions and the socket), curl.
#
# The runner is the process-per-request binary, exactly as under
# dawn-play-native.socket: test/inetd.py accepts on a unix socket and starts
# `<binary> serve` per connection with the connection as stdin and stdout, so
# every request is a fresh process, and curl reaches it with
# --abstract-unix-socket.
# (`systemd-socket-activate -a --inetd` does the same, but is not on every
# machine this runs on.) The binary is built here from this tree with the JVM
# toolchain (`dawn __emitc playground` and scripts/cc-units.sh), so the test
# needs no native `dawnc`; PLAY_TEST_NATIVE_BIN names one built elsewhere
# (`dawnc build playground -o dawn-play-linux-x86_64`, what a deploy ships).
# Until K5 (docs/playground-native-runner-design.md) the default was the
# long-lived JVM server on a TCP port and this was a second mode; that server
# is gone, and with it the cases that were about it (its startup sweep and
# its answer cache).
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

# The deploy pieces that run without a server. The canary check's pure parts
# (percentile, the latency gate, the normalization of the timing field, the
# expectations it holds a candidate runner to); the nginx snippet: the four
# runner locations go to the runner's unix socket, the three POSTs cut a slow
# body at 10 s (the runner process blocks reading a declared body), nothing
# goes to the JVM runner's old port, and the WebSocket gateway keeps its own.
python3 -I -B deploy/canary-check.py --self-test >/dev/null || { echo "FAIL: canary-check.py self-test"; exit 1; }
conf_count() { grep -c "$1" deploy/nginx-play.conf; }
if [ "$(conf_count 'proxy_pass http://unix:/run/dawn-play/http.sock:/')" != 4 ] ||
    [ "$(conf_count '127.0.0.1:8087')" != 0 ] ||
    [ "$(conf_count 'proxy_pass http://127.0.0.1:8088/lsp')" != 1 ] ||
    [ "$(conf_count 'client_body_timeout 10s')" != 3 ]; then
  echo "FAIL: nginx-play.conf does not send exactly the four runner locations to the runner's socket"; exit 1
fi
# Every runner route keeps the CORS headers production sends (the site is on
# another origin); the self-test proves the check goes red.
python3 -I -B deploy/nginx-cors-check.py --self-test >/dev/null || { echo "FAIL: nginx-cors-check.py self-test"; exit 1; }
python3 -I -B deploy/nginx-cors-check.py deploy/nginx-play.conf || { echo "FAIL: nginx-play.conf CORS"; exit 1; }
echo "  ok  canary check self-test; nginx routes the runner to its socket; nginx CORS on every runner route"

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
# The native compiler preferred by /check, C emission and Tile IR parsing.
# The runner only uses one of the release `dawn` is, so the cases below skip
# unless PLAY_TEST_DAWNC (default: ./dawnc-linux-x86_64, what
# scripts/release-native.sh writes) says the same version. It runs behind a
# wrapper that logs the subcommand each call was made with, which is how the
# cases tell "dawnc answered" from "the JVM compiler answered".
DAWNC_REAL="${PLAY_TEST_DAWNC:-$ROOT/dawnc-linux-x86_64}"
NATIVE_DIR=""
want_ver=$("$DAWN_BIN" --version 2>/dev/null | sed -n 's/^dawn \([0-9][0-9.]*\) .*/\1/p' | tail -n 1)
have_ver=""
[ -x "$DAWNC_REAL" ] && have_ver=$("$DAWNC_REAL" --version 2>/dev/null | sed -n 's/^dawnc \([0-9][0-9.]*\) .*/\1/p' | tail -n 1)
if [ -n "$want_ver" ] && [ "$want_ver" = "$have_ver" ]; then
  NATIVE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/dawn-play-native.XXXXXX")
  NATLOG="$NATIVE_DIR/calls"
  : >"$NATLOG"
  printf '#!/bin/sh\nprintf "%%s\\n" "$1" >>"%s"\nexec "%s" "$@"\n' "$NATLOG" "$DAWNC_REAL" >"$NATIVE_DIR/dawnc"
  chmod 755 "$NATIVE_DIR/dawnc"
  export DAWNC_BIN="$NATIVE_DIR/dawnc"
  JVMLOG="$NATIVE_DIR/jvm-calls"
  : >"$JVMLOG"
  printf '#!/bin/sh\nprintf "%%s\\n" "$1" >>"%s"\nexec "%s" "$@"\n' "$JVMLOG" "$ROOT/bin/dawn" >"$NATIVE_DIR/dawn"
  chmod 755 "$NATIVE_DIR/dawn"
  export DAWN_BIN="$NATIVE_DIR/dawn"
else
  echo "note: no dawnc of release '$want_ver' (PLAY_TEST_DAWNC=$DAWNC_REAL, found '$have_ver'); the native cases are skipped"
  export DAWNC_BIN=/nonexistent/dawnc
fi
# The work root is this run's own, so the run-output case below can name the
# exact directory that must not reach a response (dawn-lang #401). The socket
# is named after it in the abstract namespace: a fresh name, so no other copy
# of this test (another checkout, an external gate run) can be listening on
# it, and no path, because a socket path is limited to 107 bytes and a gate
# runner's TMPDIR alone can be longer (it was, on the first external run).
WORK=$(mktemp -d "${TMPDIR:-/tmp}/dawn-play-work.XXXXXX")
export PLAY_WORK_ROOT="$WORK"
# The sample answer store the runner reads (play/answers): empty until the
# store cases below fill it with the runner's own `warm`, so every earlier case
# is a request with no store to find.
ANSWERS="$WORK.answers"
mkdir -p "$ANSWERS"
export PLAY_ANSWERS="$ANSWERS"
SOCK="dawn-play-test-$$-${WORK##*.}"
LOG=$(mktemp "${TMPDIR:-/tmp}/dawn-play-test.XXXXXX")
# Guards keep a failed kill from turning into the script's exit status (dash:
# set -e applies inside an EXIT trap). The log is kept on failure only.
# `kill -TERM -PGID`, not `kill -- -PGID`: dash's builtin rejects the latter.
trap 'kill -TERM "-$SRV" 2>/dev/null || true; rm -rf "${WORK:?}" "${WORK:?}.cases" "${WORK:?}.bin" "${WORK:?}.answers" "${WORK:?}.samples" "${WORK:?}.badsamples"; rm -f "${WORK:?}.canary"; { [ -z "$NATIVE_DIR" ] || rm -rf "$NATIVE_DIR"; }; { [ -z "${SRV2:-}" ] || kill -TERM "-$SRV2" 2>/dev/null || true; }; [ "${fail:-1}" = "0" ] && rm -f "$LOG" || echo "runner log: $LOG"; true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if [ -n "${PLAY_TEST_NATIVE_BIN:-}" ]; then
  NATIVE_BIN=$PLAY_TEST_NATIVE_BIN
  [ -x "$NATIVE_BIN" ] || { echo "FAIL: PLAY_TEST_NATIVE_BIN=$NATIVE_BIN is not an executable"; exit 1; }
else
  # The runner of this tree, built the way the toolchain builds any native
  # program without dawnc: the C text, then the shared compile and link.
  mkdir -p "$WORK.bin/c"
  "$DAWN_BIN" __emitc "$ROOT/playground" -o "$WORK.bin/c/main.c" >"$WORK.bin/build.log" 2>&1 &&
    "$ROOT/scripts/cc-units.sh" -o "$WORK.bin/dawn-play" "$WORK.bin/c" >>"$WORK.bin/build.log" 2>&1 ||
    { echo "FAIL: cannot build the runner"; tail -n 20 "$WORK.bin/build.log"; exit 1; }
  NATIVE_BIN="$WORK.bin/dawn-play"
fi
echo "runner: $NATIVE_BIN"

# A deploy writes this from the tree it ships (redeploy.sh); /health then
# answers without a child, as in production.
PLAY_TOOLCHAIN_ID=$("$DAWN_BIN" --version 2>/dev/null | tail -n 1 | sed -e 's/^dawn //' -e 's/ (selfhost)//')
export PLAY_TOOLCHAIN_ID
# The runner starts in a session (and so a process group) of its own, whose id
# is its pid, so the cleanup reaches every request process it started without
# looking anyone up. python3 does the setsid because it is already required
# here and, unlike setsid(1), exists on macOS.
#
# It also starts in the POSIX locale with no LANG, which is the environment a
# systemd unit gives the compilers it starts: file names are then ASCII to the
# JVM, and the /compile cases with non-ASCII names only pass because the
# runner asks for a UTF-8 locale on those commands (play/exec.utf8_env).
start_runner() { # socket, log
  python3 -c 'import os, sys; os.setsid(); os.environ.pop("LANG", None); os.environ["LC_ALL"] = "POSIX"; os.execvp(sys.argv[1], sys.argv[1:])' \
    python3 -I -B "$ROOT/playground/test/inetd.py" "$1" "$NATIVE_BIN" serve >"$2" 2>&1 &
}
start_runner "$SOCK" "$LOG"
SRV=$!
# Every case below talks to the runner with curl; this makes the same command
# line reach the socket. The URL's host is then only the Host header.
URL=http://localhost
curl() { command curl --abstract-unix-socket "$SOCK" "$@"; }
# Wait for /health against a deadline, not a count of tries. A runner that
# never answers is still red, at the deadline, with its own log rather than
# fifteen downstream failures; one that dies is red as soon as neither its pid
# nor its process group is left (the pid alone right after the fork: setsid
# may not have run yet). PLAY_TEST_HEALTH_WAIT moves the deadline (seconds).
HEALTH_WAIT=${PLAY_TEST_HEALTH_WAIT:-60}
wait_started=$(date +%s)
deadline=$((wait_started + HEALTH_WAIT))
waited=""
until curl -s --noproxy '*' --max-time 5 -o /dev/null "$URL/health"; do
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
  body=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$2" "$URL/${4:-run}" || true)
  if printf '%s' "$body" | python3 -c "import os,sys,json,re; raw=sys.stdin.read(); d=json.loads(raw); assert ($3), d" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $body"
  fi
}

health=$(curl -s --noproxy '*' --max-time 10 "$URL/health" || true)
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
  '{"code":"fn s(n: Int) -> Unit !io = if n < 0 { () } else { s(n + 1) }\npub fn main() -> Unit !io = {\n  println(\"x\")\n  s(0)\n}"}' \
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
  let here = str.take(jar, len(jar) - len("/prog.jar"))
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
for name in ("tile_hostif", "tile_broken"):
    open(f"{out}/{name}.dawn", "w", encoding="utf-8").write(open(f"{root}/playground/test/{name}.dawn", encoding="utf-8").read())
open(f"{out}/tile_syntax.dawn", "w", encoding="utf-8").write(tile + "\nfn broken(\n")
# the flash attention starter: the Playground's own sample, not a copy of it
open(f"{out}/tile_attn.dawn", "w", encoding="utf-8").write(open(f"{root}/site/play-ui/samples/flash_attn.dawn", encoding="utf-8").read())
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
    "$URL/compile" >"$out" || true
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

# The runner keeps no answers (the process is the request), so a repeat is
# compiled again and must answer the same bytes but for the timing.
ccheck "compile: the same program again answers the same, uncached" "$CASES/starter.dawn" c \
  'd["cached"] is False and prev is not None and {k:v for k,v in d.items() if k not in ("cached","ms")}=={k:v for k,v in prev.items() if k not in ("cached","ms")}'

ccheck "compile: the JVM listing of it is the other half of the same build" "$CASES/starter.dawn" jvm \
  "$SOUND"' and d["target"]=="jvm" and d["cached"] is False and d["pane"]["kind"]=="jvm" and any(o["key"] for o in d["pane"]["outs"]) and any("invokestatic" in l for l in d["pane"]["text"]) and d["calls"]==prev["calls"]'

ccheck "compile: names outside ASCII map with no gap (JVM)" "$CASES/odd.dawn" jvm \
  "$SOUND"' and any("größe" in l for l in d["pane"]["text"]) and d["cached"] is False'
ccheck "compile: and so does the C text of them" "$CASES/odd.dawn" c \
  "$SOUND"' and d["cached"] is False and len(d["calls"])>=3'

# The program that does not compile gets /check's diagnostics, word for word,
# and the same for either target.
ccheck "compile: an error carries the diagnostics, without the work directory" "$CASES/broken.dawn" c \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn:1" in d["output"] and "undefined variable: nope" in d["output"] and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw and "cached" not in d'
checked=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$(python3 -c 'import json,sys; print(json.dumps({"code": open(sys.argv[1]).read()}))' "$CASES/broken.dawn")" "$URL/check" || true)
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
printf 'schema = 1\nname = "tp"\nversion = "0.0.0"\n\n[deps]\ntileir = "%s/packages/tileir"\ntileref = "%s/packages/tileref"\ntileinterp = "%s/packages/tileinterp"\n' "$ROOT" "$ROOT" "$ROOT" >"$TILE_PROJ/dawn.toml"
"$DAWN_BIN" run "$TILE_PROJ" >"$CASES/tile.expected" 2>/dev/null || true
tile_ccheck() { # name, program file, extra request fields (JSON object), assertion
  RESP_N=$((RESP_N + 1))
  out="$CASES/resp.$RESP_N"
  curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST \
    --data "$(python3 -c 'import json,sys; d={"code": open(sys.argv[1], encoding="utf-8").read(), "target": "tile"}; d.update(json.loads(sys.argv[2])); print(json.dumps(d))' "$2" "$3")" \
    "$URL/compile" >"$out" || true
  if EXPECTED="$CASES/tile.expected" python3 -c "import os,sys,json,re; raw=sys.stdin.read(); d=json.loads(raw); expected=open(os.environ['EXPECTED'], encoding='utf-8').read(); assert ($4), d" <"$out" 2>/dev/null; then
    pass=$((pass + 1)); echo "  ok  $1"
  else
    fail=$((fail + 1)); echo "FAIL  $1"; echo "        $(head -c 600 "$out")"
  fi
}
tile_ccheck "compile: a tileir program's pane is the text dawn run prints, and its calls are paired with the source" "$CASES/tile.dawn" '{}' \
  'len(expected)>200 and d["ok"] is True and d["phase"]=="compile-view" and d["target"]=="tile" and d["cached"] is False and d["pane"]["kind"]=="tile" and "\n".join(d["pane"]["text"])+"\n"==expected and d["pane"]["shown"]==len(d["pane"]["text"]) and d["pane"]["truncated"] is False and "unmapped" not in d and [c["name"] for c in d["calls"]]==["store_cell","add","load_cell","load_cell"] and [c["parent"] for c in d["calls"]]==[-1,0,1,1] and len(d["pane"]["outs"])==4 and all(o["lines"] for o in d["pane"]["outs"]) and d["gaps"]["count"]==0 and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw and "explore_probe" not in raw and "@@tile" not in raw'
TILE_EXPECTED="$CASES/tile.expected"
ATTN_GOLDEN="$ROOT/site/play-ui/samples/flash_attn.out"
export TILE_EXPECTED ATTN_GOLDEN
ATTN_FIRST=$(grep -n '^fn flash_attn\[' "$CASES/tile_attn.dawn" | cut -d: -f1)
export ATTN_FIRST
tile_ccheck "compile: a kernel with a loop and carried variables is paired call by call" "$CASES/tile_attn.dawn" '{}' \
  'd["ok"] is True and "unmapped" not in d and d["calls_total"]==26 and d["gaps"]["count"]==0 and any(c["name"]=="d_range" for c in d["calls"]) and any(c["parent"]>=0 and d["calls"][c["parent"]]["name"]=="d_range" for c in d["calls"]) and len(d["pane"]["outs"])==26 and d["pane"]["text"][1].lstrip().startswith("entry @flash_attn") and d["src"]["first"]==int(os.environ["ATTN_FIRST"])'
tile_ccheck "compile: a kernel the pairing cannot follow keeps its plain pane and says why" "$CASES/tile_hostif.dawn" '{}' \
  'd["ok"] is True and d["phase"]=="compile-view" and "calls" not in d and "host control flow" in d["unmapped"] and d["pane"]["kind"]=="tile" and any("cuda_tile.module" in l for l in d["pane"]["text"]) and "@@tile" not in raw'
tile_ccheck "compile: a tileir program with a compile error answers a diagnostic, not a pane" "$CASES/tile_broken.dawn" '{}' \
  'd["ok"] is False and d["phase"]=="compile" and "nope" in d["output"] and "pane" not in d and "@@tile" not in raw and "explore_probe" not in raw'
SMUGGLE="{\"dawn_toml\": \"schema = 1\\nname = \\\"x\\\"\\nversion = \\\"0.0.0\\\"\\n[deps]\\ntileir = \\\"$ROOT/packages/tileir\\\"\\njson = \\\"$ROOT/packages/json\\\"\\n\"}"
tile_ccheck "compile: a dependency the visitor supplies is not honoured, so another package does not resolve" "$CASES/tile_smuggle.dawn" "$SMUGGLE" \
  'd["ok"] is False and d["phase"]=="compile" and "json" in d["output"] and "pane" not in d'

# ---- a tileir program is a project on every route, not only the Tile IR view.
#
# /run, /check and the C and JVM views stage a program that imports tileir the
# way the Tile IR view does (src/main.dawn and the runner's own dawn.toml), so
# `use tileir/` resolves wherever the program is sent; every other program is
# the single file it was. The expected text is what `dawn run` prints for the
# same program as a project, and for the flash attention starter the golden the
# kernel is pinned to.
run_data() { # program file, extra request fields (JSON object)
  python3 -c 'import json,sys; d={"code": open(sys.argv[1], encoding="utf-8").read()}; d.update(json.loads(sys.argv[2])); print(json.dumps(d))' "$1" "$2"
}
check "run: a tileir program runs and prints its Tile IR" "$(run_data "$CASES/tile.dawn" '{}')" \
  'd["ok"] is True and d["phase"]=="run" and d["exit"]==0 and d["truncated"] is False and d["output"]==open(os.environ["TILE_EXPECTED"], encoding="utf-8").read() and len(d["output"])>200 and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw'
check "run: the flash attention starter records, interprets and prints the answer its .out pins" "$(run_data "$CASES/tile_attn.dawn" '{}')" \
  'd["ok"] is True and d["phase"]=="run" and d["exit"]==0 and d["output"]==open(os.environ["ATTN_GOLDEN"], encoding="utf-8").read()'
check "run: a tileir program with a compile error answers a diagnostic" "$(run_data "$CASES/tile_broken.dawn" '{}')" \
  'd["ok"] is False and d["phase"]=="compile" and "nope" in d["output"] and os.environ["PLAY_WORK_ROOT"] not in raw and "dawn-play-" not in raw'
check "run: a dependency the visitor supplies is not honoured, so another package does not resolve" \
  "$(run_data "$CASES/tile_smuggle.dawn" "$SMUGGLE")" \
  'd["ok"] is False and d["phase"]=="compile" and "json" in d["output"]'
check "check: a tileir program has no diagnostics" "$(run_data "$CASES/tile.dawn" '{}')" \
  'd["ok"] is True and d["phase"]=="check"' check
check "run: a program that does not import tileir is still the single file it was" \
  '{"code":"pub fn main() -> Unit !io = println(nope)"}' \
  'not d["ok"] and d["phase"]=="compile" and "prog.dawn" in d["output"] and "src/main.dawn" not in d["output"]'
ccheck "compile: the C text of a tileir program is its own module's, no gap, its calls placed in it" "$CASES/tile.dawn" c \
  "$SOUND"' and d["target"]=="c" and d["cached"] is False and d["pane"]["kind"]=="c" and d["calls_total"]>=4 and d["pane"]["total"]>1000 and d["pane"]["shown"]<200 and any("main__vadd" in l for l in d["pane"]["text"])'
ccheck "compile: and so is its JVM listing" "$CASES/tile.dawn" jvm \
  "$SOUND"' and d["target"]=="jvm" and d["pane"]["kind"]=="jvm" and d["cached"] is False and d["calls_total"]>=4 and any("invokestatic" in l for l in d["pane"]["text"])'
# Its kernel is written with operators on tiles (`a * b` is a call of `Mul`'s
# impl, its name the `*`) and a literal where a tile is expected (`0.0`, a
# call of `from_float`): each of them is a call of the table with no gap. The
# C text is read with every line outside the program's own functions empty, so
# its line count is still the whole text's (docs/playground-compile-design.md K8).
# The starter's `main` interprets the kernel and checks it against plain attention,
# which adds calls of its own to the table (86 in all, including the factory and numeric policy),
# so the operator count is a floor: the kernel's seven are there, and no gap.
ccheck "compile: the flash attention starter's C text pairs its operators, no gap" "$CASES/tile_attn.dawn" c \
  "$SOUND"' and d["pane"]["kind"]=="c" and d["calls_total"]==86 and sum(c["name"] in ("mul","sub","add","div") for c in d["calls"])>=7 and any(c["name"]=="from_float" for c in d["calls"]) and d["pane"]["total"]>80000 and d["pane"]["shown"]>100 and any("main__flash_1attn" in l for l in d["pane"]["text"])'
ccheck "compile: the JVM listing of it pairs the same calls" "$CASES/tile_attn.dawn" jvm \
  "$SOUND"' and d["pane"]["kind"]=="jvm" and d["cached"] is False and d["calls"]==prev["calls"]'
ccheck "compile: a dependency the visitor supplies is not honoured by the C view either" "$CASES/tile_smuggle.dawn" c \
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
  got=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -o "$CASES/refusal" -w '%{http_code}' -X POST --data "$1" "$URL/compile" || true)
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
code=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -o /dev/null -w '%{http_code}' "$URL/compile" || true)
[ "$code" = "405" ] && { pass=$((pass+1)); echo "  ok  compile: GET -> 405"; } || { fail=$((fail+1)); echo "FAIL  compile: GET -> $code"; }

# /compile shares /check's two permits and its two-second patience. Two runs of
# a program that never ends hold both permits for the run budget (3 s) and the
# compile before it; a compile that arrives meanwhile is turned away at two
# seconds. A /compile with a gate of its own would be let in and answer 200.
SPIN='{"code":"fn s(n: Int) -> Unit !io = if n < 0 { () } else { s(n + 1) }\npub fn main() -> Unit !io = {\n  println(\"x\")\n  s(0)\n}"}'
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$SPIN" "$URL/run" >/dev/null &
SPIN1=$!
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$SPIN" "$URL/run" >/dev/null &
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

# ---- native /check and C view (the dawnc step) ----
# Cases: a plain program is checked by dawnc; a `use java` program, which dawnc
# refuses, still passes /check through the JVM compiler; a broken program's
# diagnostics and a program's C view are the same bytes whichever compiler
# answered (a second runner without dawnc is the reference); and the refusal
# the fallback keys on is what the real binary says.
if [ -n "$NATIVE_DIR" ]; then
  calls() { wc -l <"$NATLOG" | tr -d ' '; }
  post() { # socket, endpoint, data
    command curl --abstract-unix-socket "$1" -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$3" "$URL/$2" || true
  }
  ok_case() { # name, condition-exit-status
    if [ "$2" = "0" ]; then pass=$((pass + 1)); echo "  ok  $1"; else fail=$((fail + 1)); echo "FAIL  $1"; fi
  }

  n0=$(calls)
  body=$(post "$SOCK" check '{"code":"pub fn main() -> Unit !io = println(\"hi\")"}')
  st=0; printf '%s' "$body" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d["ok"] is True, d' || st=1
  [ "$(calls)" -gt "$n0" ] && [ "$(tail -n 1 "$NATLOG")" = "check" ] || st=1
  ok_case "native check: a plain program is checked by dawnc" "$st"

  n0=$(calls)
  jcode='use java \"java.lang.System\"\npub fn main() -> Unit !io = println(System.getProperty(\"java.class.path\").expect(\"cp\"))'
  body=$(post "$SOCK" check "{\"code\":\"$jcode\"}")
  st=0; printf '%s' "$body" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d["ok"] is True, d' || st=1
  [ "$(calls)" -gt "$n0" ] || st=1
  ok_case "native check: a use java program is refused by dawnc and passes through the JVM compiler" "$st"

  # `dawnc` answered as the fallback keys on: status 1 and the sentence.
  printf 'use java "java.lang.System"\npub fn main() -> Unit !io = println("x")\n' >"$NATIVE_DIR/uj.dawn"
  st=0
  for sub in check emitc; do
    out=$("$DAWNC_REAL" $sub "$NATIVE_DIR/uj.dawn" 2>&1) && st=1
    case $out in *'`use java` is not available in this compiler'*) : ;; *) st=1 ;; esac
  done
  ok_case "dawnc refuses use java with status 1 and the sentence play/exec.dawn keys on" "$st"

  # The reference: the same runner with no dawnc, so every answer is the JVM's.
  SOCK2="$SOCK-2"
  LOG2=$(mktemp "${TMPDIR:-/tmp}/dawn-play-test2.XXXXXX")
  DAWNC_BIN=/nonexistent/dawnc start_runner "$SOCK2" "$LOG2"
  SRV2=$!
  deadline2=$(($(date +%s) + HEALTH_WAIT))
  until command curl --abstract-unix-socket "$SOCK2" -s --noproxy '*' --max-time 5 -o /dev/null "$URL/health"; do
    [ "$(date +%s)" -ge "$deadline2" ] && { echo "FAIL: the reference runner did not answer /health"; tail -n 20 "$LOG2"; exit 1; }
    sleep 0.3
  done

  bad='{"code":"type T = A | B\nfn f(t: T) -> Int = match t { A -> 1 }\npub fn main() -> Unit !io = println(nope + f(A))"}'
  n0=$(calls)
  a=$(post "$SOCK" check "$bad"); b=$(post "$SOCK2" check "$bad")
  st=0
  [ "$(calls)" -gt "$n0" ] || st=1
  [ "$a" = "$b" ] || st=1
  printf '%s' "$a" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d["ok"] is False and "undefined variable: nope" in d["output"] and "non-exhaustive" in d["output"], d' || st=1
  [ "$st" = "0" ] || { echo "        dawnc: $a"; echo "        dawn:  $b"; }
  ok_case "native check: a broken program's /check JSON is byte-identical to the JVM compiler's" "$st"
  grep -q 'no native dawnc' "$LOG2" && st=0 || st=1
  ok_case "the runner without dawnc says so in its log" "$st"

  prog='{"code":"pub fn main() -> Unit !io = println(\"hi\")","target":"c"}'
  n0=$(calls)
  a=$(post "$SOCK" compile "$prog"); b=$(post "$SOCK2" compile "$prog")
  st=0
  [ "$(tail -n 1 "$NATLOG")" = "emitc" ] || st=1
  A="$a" B="$b" python3 -c '
import os,json
def drop(t):
    d=json.loads(t); d.pop("ms",None); d.pop("cached",None); return d
a,b=drop(os.environ["A"]),drop(os.environ["B"])
assert a["ok"] is True and a==b, (a,b)' || st=1
  ok_case "native emitc: the C view (text and map) equals the JVM compiler's" "$st"

  # Projects use the same native commands as files. Count the subcommand,
  # not --version (every request probes that even if it then uses the JVM).
  # Compare wire bytes, including diagnostics, with only timing normalized.
  st=0
  for name in tile tile_broken; do
    n0=$(grep -c '^check$' "$NATLOG" || true)
    data=$(run_data "$CASES/$name.dawn" '{}')
    post "$SOCK" check "$data" >"$CASES/$name.native-check"
    post "$SOCK2" check "$data" >"$CASES/$name.jvm-check"
    n1=$(grep -c '^check$' "$NATLOG" || true)
    [ "$n1" -eq "$((n0 + 1))" ] || st=1
    python3 - "$CASES/$name.native-check" "$CASES/$name.jvm-check" "$name" <<'PY' || st=1
import json, re, sys
a, b = [open(p, "rb").read() for p in sys.argv[1:3]]
d = json.loads(a)
assert d["ok"] is (sys.argv[3] == "tile"), d
assert d["phase"] == ("check" if d["ok"] else "compile"), d
if not d["ok"]:
    assert "undefined function: nope" in d["output"], d
assert re.sub(rb'"ms":[0-9]+', b'"ms":0', a) == re.sub(rb'"ms":[0-9]+', b'"ms":0', b), (a, b)
PY
  done
  ok_case "native check: tileir projects use dawnc and match the JVM response bytes, including errors" "$st"

  st=0
  for name in tile tile_broken; do
    n0=$(grep -c '^emitc$' "$NATLOG" || true)
    data=$(compile_body "$CASES/$name.dawn" c)
    post "$SOCK" compile "$data" >"$CASES/$name.native-c"
    post "$SOCK2" compile "$data" >"$CASES/$name.jvm-c"
    n1=$(grep -c '^emitc$' "$NATLOG" || true)
    [ "$n1" -eq "$((n0 + 1))" ] || st=1
    python3 - "$CASES/$name.native-c" "$CASES/$name.jvm-c" "$name" <<'PY' || st=1
import json, re, sys
a, b = [open(p, "rb").read() for p in sys.argv[1:3]]
d = json.loads(a)
assert d["ok"] is (sys.argv[3] == "tile"), d
if d["ok"]:
    assert d["target"] == "c" and d["pane"]["kind"] == "c" and d["gaps"]["count"] == 0, d
else:
    assert d["phase"] == "compile" and "undefined function: nope" in d["output"], d
assert re.sub(rb'"ms":[0-9]+', b'"ms":0', a) == re.sub(rb'"ms":[0-9]+', b'"ms":0', b), (a, b)
PY
  done
  ok_case "native emitc: tileir C views use dawnc and match the JVM response bytes, including errors" "$st"

  # Count parse itself on both tools. A --version call cannot satisfy this,
  # and the probe still has to compile with the JVM after a native parse.
  st=0
  for name in tile tile_hostif tile_broken tile_syntax; do
    n0=$(grep -c '^parse$' "$NATLOG" || true)
    j0=$(grep -c '^parse$' "$JVMLOG" || true)
    b0=$(grep -c '^build$' "$JVMLOG" || true)
    data=$(compile_body "$CASES/$name.dawn" tile)
    post "$SOCK" compile "$data" >"$CASES/$name.native-tile"
    n1=$(grep -c '^parse$' "$NATLOG" || true)
    j1=$(grep -c '^parse$' "$JVMLOG" || true)
    b1=$(grep -c '^build$' "$JVMLOG" || true)
    [ "$n1" -eq "$((n0 + 1))" ] && [ "$j1" -eq "$j0" ] && [ "$b1" -gt "$b0" ] || st=1
    post "$SOCK2" compile "$data" >"$CASES/$name.jvm-tile"
    python3 - "$CASES/$name.native-tile" "$CASES/$name.jvm-tile" "$name" <<'PYTILE' || st=1
import json, re, sys
a, b = [open(p, "rb").read() for p in sys.argv[1:3]]
d = json.loads(a)
assert d["ok"] is (sys.argv[3] in ("tile", "tile_hostif")), d
if sys.argv[3] == "tile":
    assert d["target"] == "tile" and d["gaps"]["count"] == 0 and "unmapped" not in d, d
elif sys.argv[3] == "tile_hostif":
    assert "host control flow" in d["unmapped"], d
else:
    assert d["phase"] == "compile" and "pane" not in d, d
norm = lambda t: re.sub(rb'"ms":[0-9]+', b'"ms":0', t)
assert norm(a) == norm(b), (a, b)
PYTILE
  done
  ok_case "native parse: Tile IR uses one dawnc parse, no JVM parse, and matches JVM response bytes" "$st"

  # Tool selection and parse failures keep their existing categories. Only
  # an empty failure or the native refusal retries parse with the JVM.
  cat >"$NATIVE_DIR/parse-fault" <<'FAULT'
#!/bin/sh
if [ "$1" = --version ]; then
  if [ "$PLAY_TEST_PARSE_FAULT" = wrong ]; then echo 'dawnc 0.0.0 (native)'; exit 0; fi
  exec "$PLAY_TEST_DAWNC_REAL" "$@"
fi
printf '%s\n' "$1" >>"$PLAY_TEST_PARSE_LOG"
case "$PLAY_TEST_PARSE_FAULT" in
  timeout) exec sleep 6 ;;
  empty) exit 1 ;;
  refusal) echo 'error: `use java` is not available in this compiler'; exit 1 ;;
  diagnostic) echo 'error: parse failed'; exit 1 ;;
esac
exec "$PLAY_TEST_DAWNC_REAL" "$@"
FAULT
  chmod 755 "$NATIVE_DIR/parse-fault"
  st=0
  data=$(compile_body "$CASES/tile.dawn" tile)
  for fault in missing wrong timeout empty refusal diagnostic; do
    tool="$NATIVE_DIR/parse-fault"
    [ "$fault" != missing ] || tool=/nonexistent/dawnc
    : >"$NATIVE_DIR/fault-calls"
    j0=$(grep -c '^parse$' "$JVMLOG" || true)
    printf 'POST /compile HTTP/1.1\r\nHost: x\r\nConnection: close\r\nContent-Length: %s\r\n\r\n%s' "${#data}" "$data" |
      PLAY_TEST_DAWNC_REAL="$DAWNC_REAL" PLAY_TEST_PARSE_LOG="$NATIVE_DIR/fault-calls" \
      PLAY_TEST_PARSE_FAULT="$fault" DAWNC_BIN="$tool" PLAY_COMPILE_TIMEOUT=3 \
      "$NATIVE_BIN" serve >"$CASES/$fault.http" 2>"$CASES/$fault.log"
    n1=$(grep -c '^parse$' "$NATIVE_DIR/fault-calls" || true)
    j1=$(grep -c '^parse$' "$JVMLOG" || true)
    case "$fault" in
      missing|wrong) [ "$n1" -eq 0 ] && [ "$j1" -eq "$((j0 + 1))" ] || st=1 ;;
      empty|refusal) [ "$n1" -eq 1 ] && [ "$j1" -eq "$((j0 + 1))" ] || st=1 ;;
      *) [ "$n1" -eq 1 ] && [ "$j1" -eq "$j0" ] || st=1 ;;
    esac
    python3 - "$CASES/$fault.http" "$CASES/tile.jvm-tile" "$fault" <<'PYFAULT' || st=1
import json, re, sys
a = open(sys.argv[1], "rb").read().split(b"\r\n\r\n", 1)[1]
b = open(sys.argv[2], "rb").read()
d = json.loads(a)
assert d["ok"] is True and d["cached"] is False, d
if sys.argv[3] in ("timeout", "diagnostic"):
    assert d["unmapped"] == ("the parse timed out" if sys.argv[3] == "timeout" else "the program does not parse"), d
    assert "calls" not in d and d["pane"]["kind"] == "tile", d
else:
    norm = lambda t: re.sub(rb'"ms":[0-9]+', b'"ms":0', t)
    assert norm(a) == norm(b), (a, b)
PYFAULT
  done
  ok_case "native parse: missing or wrong tools fall back, refusals retry, and timeouts or diagnostics keep the plain pane" "$st"

  # The answer key names the toolchain and staging form, not which compiler
  # executable supplied the identical text and mapping. A native-warmed
  # project answer must also serve the JVM-only runner, with the same bytes.
  mkdir -p "$NATIVE_DIR/samples"
  cp "$CASES/tile.dawn" "$NATIVE_DIR/samples/tile.dawn"
  st=0
  "$NATIVE_BIN" warm "$NATIVE_DIR/samples" "$NATIVE_DIR/answers" >"$NATIVE_DIR/warm.log" 2>&1 || st=1
  for target in c tile; do
    data=$(compile_body "$CASES/tile.dawn" "$target")
    printf 'POST /compile HTTP/1.1\r\nHost: x\r\nConnection: close\r\nContent-Length: %s\r\n\r\n%s' "${#data}" "$data" |
      PLAY_ANSWERS="$NATIVE_DIR/answers" DAWNC_BIN=/nonexistent/dawnc "$NATIVE_BIN" serve 2>/dev/null >"$CASES/tile.hit-http"
    python3 - "$CASES/tile.hit-http" "$CASES/tile.native-$target" <<'PY' || st=1
import json, re, sys
hit = open(sys.argv[1], "rb").read().split(b"\r\n\r\n", 1)[1]
live = open(sys.argv[2], "rb").read()
assert json.loads(hit)["cached"] is True and json.loads(live)["cached"] is False
norm = lambda t: re.sub(rb'"ms":[0-9]+', b'"ms":0', t).replace(b'"cached":true', b'"cached":false')
assert norm(hit) == norm(live), (hit, live)
PY
  done
  ok_case "store: tileir C and Tile IR views warmed with dawnc are reusable by the JVM-only runner" "$st"

  kill -TERM "-$SRV2" 2>/dev/null || true
  rm -f "$LOG2"
fi

check "bad JSON -> error" \
  'not json at all' \
  'not d["ok"] and d["phase"]=="error"'

check "missing code -> error" \
  '{"foo":1}' \
  'not d["ok"] and "code" in d["output"]'

# large body -> 413 (checked via status, not JSON body)
big=$(python3 -c 'print("{\"code\":\"" + "/"*70000 + "\"}")')
code=$(printf '%s' "$big" | curl -s --noproxy '*' --max-time "$REQ_MAX" -o /dev/null -w '%{http_code}' -X POST --data @- "$URL/run" || true)
[ "$code" = "413" ] && { pass=$((pass+1)); echo "  ok  oversized body -> 413"; } || { fail=$((fail+1)); echo "FAIL  oversized body -> $code"; }

# GET -> 405
code=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -o /dev/null -w '%{http_code}' "$URL/run" || true)
[ "$code" = "405" ] && { pass=$((pass+1)); echo "  ok  GET -> 405"; } || { fail=$((fail+1)); echo "FAIL  GET -> $code"; }

# ---- the sample answer store (docs/playground-native-runner-design.md 4.4)
#
# A sample's answer is made at deploy time by `dawn-play warm` and read by the
# serving runner. The program below is the one "sample": its answer is taken
# live first (the store is empty), then the warm-up fills the store, then the
# same request is a hit. A hit and the live answer must be the same bytes but
# for `ms` and the `"cached":true` member a hit adds. The negative controls are
# the point of the cases after it: one byte more is a miss, another toolchain
# id is a miss, and a sample that gets no answer fails the warm-up.
SAMPLES="$WORK.samples"
mkdir -p "$SAMPLES"
printf 'pub fn main() -> Unit !io = println("answer-store-sample")\n' >"$SAMPLES/store.dawn"
STORE_RUN=$(python3 -c 'import json,sys; print(json.dumps({"code": open(sys.argv[1], encoding="utf-8").read()}))' "$SAMPLES/store.dawn")
STORE_RUN_PLUS=$(python3 -c 'import json,sys; print(json.dumps({"code": open(sys.argv[1], encoding="utf-8").read() + " "}))' "$SAMPLES/store.dawn")
STORE_C=$(python3 -c 'import json,sys; print(json.dumps({"code": open(sys.argv[1], encoding="utf-8").read(), "target": "c"}))' "$SAMPLES/store.dawn")
live_run=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$STORE_RUN" "$URL/run" || true)
live_c=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$STORE_C" "$URL/compile" || true)
st=0
[ -z "$(ls -A "$ANSWERS")" ] || st=1
LIVE="$live_run" python3 -c 'import os,json; d=json.loads(os.environ["LIVE"]); assert d["ok"] is True and d["output"]=="answer-store-sample\n" and "cached" not in d, d' || st=1
LIVE="$live_c" python3 -c 'import os,json; d=json.loads(os.environ["LIVE"]); assert d["ok"] is True and d["cached"] is False, d' || st=1
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: with no answers kept, a sample is compiled and run"; else fail=$((fail + 1)); echo "FAIL  store: with no answers kept, a sample is compiled and run"; fi

if "$NATIVE_BIN" warm "$SAMPLES" "$ANSWERS" >"$WORK.warm.log" 2>&1; then st=0; else st=1; fi
# one program: its run, and the C and JVM views of one compile
[ "$(ls -A "$ANSWERS" | wc -l)" -eq 3 ] || st=1
[ "$st" = "0" ] || cat "$WORK.warm.log"
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: warm keeps the run and both compile views of a sample"; else fail=$((fail + 1)); echo "FAIL  store: warm keeps the run and both compile views of a sample"; fi
rm -f "$WORK.warm.log"

hit_run=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$STORE_RUN" "$URL/run" || true)
st=0
LIVE="$live_run" HIT="$hit_run" python3 -c '
import os,re
live, hit = os.environ["LIVE"], os.environ["HIT"]
norm = lambda t: re.sub(r"\"ms\":[0-9]+", "\"ms\":0", t)
assert hit.endswith(",\"cached\":true}"), hit
assert norm(hit[:-len(",\"cached\":true}")] + "}") == norm(live), (live, hit)' || st=1
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: a hit on /run is the live answer plus cached:true, byte for byte"; else fail=$((fail + 1)); echo "FAIL  store: a hit on /run is the live answer plus cached:true, byte for byte"; echo "        live: $live_run"; echo "        hit:  $hit_run"; fi

hit_c=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$STORE_C" "$URL/compile" || true)
st=0
LIVE="$live_c" HIT="$hit_c" python3 -c '
import os,json
def drop(t):
    d=json.loads(t); d.pop("ms",None); c=d.pop("cached"); return d, c
(a, ca), (b, cb) = drop(os.environ["LIVE"]), drop(os.environ["HIT"])
assert ca is False and cb is True and a == b and a["ok"] is True, (ca, cb)' || st=1
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: a hit on /compile is the live view with cached:true"; else fail=$((fail + 1)); echo "FAIL  store: a hit on /compile is the live view with cached:true"; fi

# Negative controls: the program with one more byte, and the same program under
# another toolchain id, are not in the store, so they compile and run for real.
miss_run=$(curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$STORE_RUN_PLUS" "$URL/run" || true)
st=0
MISS="$miss_run" python3 -c 'import os,json; d=json.loads(os.environ["MISS"]); assert d["ok"] is True and d["output"]=="answer-store-sample\n" and "cached" not in d, d' || st=1
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: one more byte in the source is a miss"; else fail=$((fail + 1)); echo "FAIL  store: one more byte in the source is a miss"; echo "        $miss_run"; fi

other_tc=$(printf 'POST /run HTTP/1.1\r\nHost: x\r\nConnection: close\r\nContent-Length: %s\r\n\r\n%s' "${#STORE_RUN}" "$STORE_RUN" |
  PLAY_TOOLCHAIN_ID="0.0.0 b1:000000000000" "$NATIVE_BIN" serve 2>/dev/null | python3 -c 'import sys; print(sys.stdin.buffer.read().split(b"\r\n\r\n", 1)[1].decode())')
st=0
MISS="$other_tc" python3 -c 'import os,json; d=json.loads(os.environ["MISS"]); assert d["ok"] is True and d["output"]=="answer-store-sample\n" and "cached" not in d, d' || st=1
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: another toolchain id is a miss"; else fail=$((fail + 1)); echo "FAIL  store: another toolchain id is a miss"; echo "        $other_tc"; fi

# A sample that does not compile gets no answer, and the warm-up says so by
# failing: a deploy must stop there rather than ship a sample page that is slow.
BAD="$WORK.badsamples"
mkdir -p "$BAD"
printf 'pub fn main() -> Unit !io = println(nope)\n' >"$BAD/broken.dawn"
st=0
if "$NATIVE_BIN" warm "$BAD" "$WORK.badsamples/out" >"$WORK.warm.log" 2>&1; then st=1; fi
grep -q 'no answer was kept for: broken.dawn run' "$WORK.warm.log" || st=1
[ "$st" = "0" ] || cat "$WORK.warm.log"
rm -f "$WORK.warm.log"
if [ "$st" = "0" ]; then pass=$((pass + 1)); echo "  ok  store: a sample that gets no answer fails the warm-up"; else fail=$((fail + 1)); echo "FAIL  store: a sample that gets no answer fails the warm-up"; fi

# The access log names each program by the SHA-256 of its `code` field, with
# the toolchain that answered it, and never by its text: a program carrying a
# marker is run, compiled for the C view and checked, and the marker must be
# nowhere in the log while three lines carry its digest (ruling 4 of
# 2026-10-19; the digests are what a later answer cache is decided on).
MARK_CODE='pub fn main() -> Unit !io = println("k5-access-log-marker")'
MARK_JSON=$(python3 -c 'import json,sys; print(json.dumps({"code": sys.argv[1]}))' "$MARK_CODE")
MARK_C=$(python3 -c 'import json,sys; print(json.dumps({"code": sys.argv[1], "target": "c"}))' "$MARK_CODE")
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$MARK_JSON" "$URL/run" >/dev/null || true
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$MARK_C" "$URL/compile" >/dev/null || true
curl -s --noproxy '*' --max-time "$REQ_MAX" -X POST --data "$MARK_JSON" "$URL/check" >/dev/null || true
curl -s --noproxy '*' --max-time 10 -o /dev/null "$URL/health" || true
if MARK_CODE="$MARK_CODE" python3 - "$LOG" <<'PY'
import hashlib, os, re, sys
log = open(sys.argv[1], encoding="utf-8", errors="replace").read()
code = os.environ["MARK_CODE"]
digest = hashlib.sha256(code.encode()).hexdigest()
tc = os.environ["PLAY_TOOLCHAIN_ID"].replace(" ", "/")
assert "k5-access-log-marker" not in log, "the log carries the program's text"
for want in (f"200 POST /run toolchain={tc} src_sha256={digest}\n",
             f"200 POST /compile toolchain={tc} src_sha256={digest} target=c\n",
             f"200 POST /check toolchain={tc} src_sha256={digest}\n",
             f"200 GET /health toolchain={tc}\n"):
    assert want in log, (want, log[-2000:])
# every access line carries the toolchain, and every POST to a route a digest or `-`
lines = [l for l in log.splitlines() if re.match(r"^[0-9]{3} (GET|POST) /", l)]
assert lines and all(" toolchain=" in l for l in lines), lines
assert all(re.search(r" src_sha256=([0-9a-f]{64}|-)( |$)", l) for l in lines if re.match(r"^[0-9]{3} POST /(run|check|compile) ", l)), lines
PY
then
  pass=$((pass + 1)); echo "  ok  the access log names each program by its digest and toolchain, never by its text"
else
  fail=$((fail + 1)); echo "FAIL  the access log names each program by its digest and toolchain, never by its text"
fi

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

#!/usr/bin/env bash
# Golden diff for the self-hosted language server: a scripted LSP session
# (initialize, open/change/close, hover, definition, completion, symbols,
# formatting over a two-module project + a standalone buffer) runs against
# both `dawn lsp` implementations and every JSON message must agree after
# normalization (parsed and re-serialized with sorted keys — key order and
# whitespace are transport detail, values and message order are not).
set -euo pipefail
cd "$(dirname "$0")/.."

# the Kotlin reference CLI (bin/dawn runs selfhost since M8 phase 3)
KOTLIN=${DAWN_BIN:-./bin/dawn-kotlin}
SELF=./bin/dawn
OUT=${TMPDIR:-/tmp}/selfhost-lsp-diff.$$
mkdir -p "$OUT/proj/src"
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

cat > "$OUT/proj/src/util.dawn" <<'EOF'
pub type Shape =
  | Circle(radius: Float)
  | Rect(w: Float, h: Float)

pub type Point = { x: Int, y: Int }

pub const LIMIT: Int = 42

pub fn area(s: Shape) -> Float =
  match s {
    Circle(r) -> 3.14 * r * r
    Rect(w, h) -> w * h
  }

pub fn helper(n: Int) -> Int = n + LIMIT
EOF

cat > "$OUT/proj/src/app.dawn" <<'EOF'
use std/str
use util.{Shape, Circle, Rect, area, helper, LIMIT, Point}

trait Greet[T] {
  fn hi(x: T) -> String
}

impl Greet[Point] {
  fn hi(x: Point) -> String = "p"
}

fn compute(n: Int) -> Int = {
  fn double(k: Int) -> Int = k * 2
  let s = Circle(1.5)
  let a = area(s)
  let p = Point { x: n, y: helper(n) }
  let t = str.trim("  hi  ")
  let xs = [1, 2, 3]
  let total = fold(xs, 0, fn(acc, x) => acc + x)
  # a comment line
  let msg = "sum ${total} of ${p.x}"
  match s {
    Circle(r) -> p.x + to_int(r) + double(n)
    Rect(w, h) -> to_int(w * h)
  }
}

fn main() -> Unit !io = {
  println(to_string(compute(LIMIT)))
}

test "adds" {
  assert compute(1) > 0
}
EOF

cat > "$OUT/proj/src/messy.dawn" <<'EOF'
fn   messy( a : Int )  ->  Int =  a  +  1
EOF

run_session() { # server-cmd... > transcript
  python3 - "$OUT" "$@" <<'PYEOF'
import json, subprocess, sys

out_dir = sys.argv[1]
server = sys.argv[2:]

app_path = f"{out_dir}/proj/src/app.dawn"
messy_path = f"{out_dir}/proj/src/messy.dawn"
app_uri = "file://" + app_path
messy_uri = "file://" + messy_path
app_text = open(app_path).read()
messy_text = open(messy_path).read()

def pos(text, needle, occ=1, delta=0):
    i = -1
    for _ in range(occ):
        i = text.index(needle, i + 1)
    i += delta
    line = text.count("\n", 0, i)
    col = i - (text.rfind("\n", 0, i) + 1)
    return {"line": line, "character": col}

msgs = []
_id = [0]
def req(method, params):
    _id[0] += 1
    msgs.append({"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params})
def note(method, params):
    msgs.append({"jsonrpc": "2.0", "method": method, "params": params})
def tdoc(uri):
    return {"textDocument": {"uri": uri}}
def at(uri, text, needle, occ=1, delta=0):
    return {"textDocument": {"uri": uri}, "position": pos(text, needle, occ, delta)}

req("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
note("initialized", {})
note("textDocument/didOpen", {"textDocument": {
    "uri": app_uri, "languageId": "dawn", "version": 1, "text": app_text}})

# hover: decls, params, locals, calls across every resolution class
for needle, occ, delta in [
    ("compute", 1, 1),      # own fn decl name
    ("n: Int) -> Int = {", 1, 0),   # parameter
    ("Circle(1.5)", 1, 1),  # ctor call (imported)
    ("area(s)", 1, 1),      # cross-module call
    ("helper(n)", 1, 1),    # cross-module call in ctor arg
    ("trim", 1, 1),         # std module-qualified call
    ("fold(xs", 1, 1),      # prelude call
    ("to_int(r)", 1, 1),    # builtin call
    ("LIMIT))", 1, 1),      # imported const use
    ("p.x + to_int", 1, 2), # field access
    ("area(s)", 1, 6),      # local var use
    ("Shape", 1, 1),        # selective import name (use line)
    ("use util", 1, 5),     # module path on use line
    ("total} of", 1, 1),    # interpolated var
    ("acc + x", 1, 1),      # lambda param use
    ("Circle(r) -> p.x", 1, 8),  # match binder
    ("Greet[T]", 1, 1),     # trait decl name
    ("hi(x: Point)", 1, 0), # impl method name
    ("double(n)", 1, 1),    # local fn call
    ("Point { x:", 1, 1),   # record ctor
]:
    req("textDocument/hover", at(app_uri, app_text, needle, occ, delta))

# definition: same-file, cross-file, std-quirk, builtin (empty)
for needle, occ, delta in [
    ("compute(LIMIT)", 1, 1),
    ("helper(n)", 1, 1),
    ("Circle(1.5)", 1, 1),
    ("LIMIT))", 1, 1),
    ("area(s)", 1, 6),
    ("trim", 1, 1),
    ("fold(xs", 1, 1),
    ("to_int(r)", 1, 1),
    ("use util", 1, 5),
]:
    req("textDocument/definition", at(app_uri, app_text, needle, occ, delta))

# completion: code, effect row, dot, comment, string, interpolation, fresh
# name, use line, mid-word
req("textDocument/completion", at(app_uri, app_text, "acc + x", 1, 7))
req("textDocument/completion", at(app_uri, app_text, "!io", 1, 1))
req("textDocument/completion", at(app_uri, app_text, "str.trim", 1, 4))
req("textDocument/completion", at(app_uri, app_text, "a comment line", 1, 3))
req("textDocument/completion", at(app_uri, app_text, "  hi  ", 1, 2))
req("textDocument/completion", at(app_uri, app_text, "total} of", 1, 3))
req("textDocument/completion", at(app_uri, app_text, "fn main", 1, 3))
req("textDocument/completion", at(app_uri, app_text, "use util.{Shape", 1, 4))
req("textDocument/completion", at(app_uri, app_text, "compute(LIMIT)", 1, 4))

req("textDocument/documentSymbol", tdoc(app_uri))

# didChange: introduce a type error, diagnostics update
bad_text = app_text.replace('let t = str.trim("  hi  ")', 'let t: Int = str.trim("  hi  ")')
note("textDocument/didChange", {"textDocument": {"uri": app_uri, "version": 2},
    "contentChanges": [{"text": bad_text}]})
req("textDocument/hover", at(app_uri, bad_text, "area(s)", 1, 1))

# a standalone buffer (no file behind the uri): the analyze(text) path
solo_text = "fn twice(v: Int) -> Int = v + v\n\nfn go() -> Int = twice(21)\n"
solo_uri = "untitled:Untitled-1"
note("textDocument/didOpen", {"textDocument": {
    "uri": solo_uri, "languageId": "dawn", "version": 1, "text": solo_text}})
req("textDocument/hover", at(solo_uri, solo_text, "twice(21)", 1, 1))
req("textDocument/definition", at(solo_uri, solo_text, "twice(21)", 1, 1))

# formatting: a lexable but unformatted file
note("textDocument/didOpen", {"textDocument": {
    "uri": messy_uri, "languageId": "dawn", "version": 1, "text": messy_text}})
req("textDocument/formatting", {"textDocument": {"uri": messy_uri},
    "options": {"tabSize": 2, "insertSpaces": True}})
note("textDocument/didClose", tdoc(messy_uri))

req("shutdown", None)
note("exit", {})

payload = b""
for m in msgs:
    body = json.dumps(m).encode()
    payload += b"Content-Length: %d\r\n\r\n%s" % (len(body), body)

proc = subprocess.run(server, input=payload, stdout=subprocess.PIPE,
                      stderr=subprocess.DEVNULL, timeout=300)
data = proc.stdout
frames = []
i = 0
while True:
    j = data.find(b"\r\n\r\n", i)
    if j < 0:
        break
    headers = data[i:j].decode("utf-8", "replace")
    clen = None
    for line in headers.split("\r\n"):
        if line.lower().startswith("content-length:"):
            clen = int(line.split(":", 1)[1].strip())
    body = data[j + 4:j + 4 + clen]
    frames.append(json.loads(body.decode()))
    i = j + 4 + clen

# Completion arrays: the Kotlin tables are HashMaps, so item order inside one
# rank is JVM hash-bucket order — semantically void (clients sort by
# sortText). Normalize by (sortText, label); everything else keeps its order.
for f in frames:
    r = f.get("result")
    if isinstance(r, list) and r and all(isinstance(x, dict) and "label" in x for x in r):
        f["result"] = sorted(r, key=lambda x: (x.get("sortText", ""), x["label"]))
    print(json.dumps(f, sort_keys=True, ensure_ascii=False))
PYEOF
}

run_session "$KOTLIN" lsp > "$OUT/kotlin.txt"
run_session "$SELF" lsp > "$OUT/self.txt"

if ! diff "$OUT/kotlin.txt" "$OUT/self.txt" > "$OUT/diff.txt" 2>&1; then
  head -30 "$OUT/diff.txt"
  echo "FAIL: lsp transcripts differ ($(grep -c '^[<>]' "$OUT/diff.txt") lines)"
  exit 1
fi
n=$(wc -l < "$OUT/kotlin.txt")
echo "OK: lsp transcripts agree over $n messages"

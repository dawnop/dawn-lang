#!/usr/bin/env python3
"""Which public call of each golden kernel wrote which line of its Tile IR.

    python3 site/gpu-map/record.py            # check calls.txt against a fresh trace
    python3 site/gpu-map/record.py --record   # rewrite calls.txt

The cuTile page (site/src/gen/gpu.dawn) lines every Dawn line of a kernel up
with the Tile IR lines it produced. The Dawn half of that is text the
generator can read; the other half needs packages/tileir to run the kernel,
and the generator is a pure function of files on disk (site/build.sh says
why: scripts/site-dist-diff.sh runs it on two backends and compares). So the
trace is RECORDED here, into calls.txt beside this file, and site/build.sh
runs this script without `--record` on every build: a recording that no
longer matches what tileir says is a red build, never a stale page.

Why a copy of kernels.dawn and not an import: its kernels are private and its
`trace` answers the program alone, while `prog.trace_calls` answers the
program and the side table. So the copy is edited, and every edit is an exact
text that must match exactly as often as stated, or this script stops and
names it: a kernels.dawn that moved under it is a failure here, not a
recording of something else.

  1. `trace_kernel(` becomes `trace_calls(` in every dispatch arm, and
     `trace` answers `(TileProg, List[Call])`;
  2. the imports only the old `main` used are dropped, and its `main` and
     `trace_twice` are cut;
  3. a `main` is appended that traces every kernel the dispatch names, in
     the dispatch's order, and prints its line map.

The dispatch is read for the kernel names too (`"<name>" ->`), so a kernel
added to kernels.dawn is in the next recording without anybody listing it.

calls.txt, one block per kernel in dispatch order:

    kernel vadd
    head 1-4                 lines no call wrote: module, entry, make_token
      block_id 1-2 4-5       a call: its TileOps [1, 2), its lines [4, 5)
      tile_at 2-4 5-7
      ...
    tail 24-27               return and the two closing braces

Every range is half-open; lines count from 1 and operations from 0 (the
entry token is operation 0). A kernel the line map refuses has one
`error <why>` line instead of the rest, and the page leaves it out.
"""

from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"
GOLDEN = ROOT / "scripts" / "tile-golden"
OUT = Path(__file__).resolve().parent / "calls.txt"

TRACE_SIG = "fn trace(name: String) -> TileProg = match name {\n"
CUT_AT = "# Trace `name` twice and answer the record, or panic if the two runs differ.\n"

# (old, new, how many times old must occur)
EDITS = [
    ("use tileir/prog.{TileProg, trace_kernel}\n",
     "use tileir/prog.{TileProg, Call, trace_calls}\n", 1),
    ("use tileir/render.{render}\n",
     "use tileir/render.{render, line_map}\n", 1),
    ("use tileir/bytecode.{encode, bytecode_version}\n", "", 1),
    ("use std/io.{with_fs_real, write_bytes}\n", "", 1),
    (TRACE_SIG, "fn trace(name: String) -> (TileProg, List[Call]) = match name {\n", 1),
]

MAIN = '''
fn spans(rs: List[(Int, Int)]) -> String =
  list.fold(rs, "", (acc, r) => {
    let (a, b) = r
    acc ++ " ${a}-${b}"
  })

fn kernel_names() -> List[String] = [
%NAMES%
]

pub fn main() -> Unit !io = {
  for name in kernel_names() {
    let (p, calls) = trace(name)
    println("kernel ${name}")
    match line_map(p, calls) {
      Ok(m) -> {
        if m.text != render(p) { panic("${name}: the line map's text is not render's") } else { () }
        println("head${spans(m.head)}")
        for k in range(0, len(calls)) {
          let c = calls[k]
          println("  ${c.name} ${c.ops_from}-${c.ops_to}${spans(m.calls[k].lines)}")
        }
        let (ta, tb) = m.tail
        println("tail ${ta}-${tb}")
      }
      Err(e) -> println("error ${e}")
    }
  }
}
'''


def fail(msg: str) -> None:
    print(f"site/gpu-map/record.py: {msg}", file=sys.stderr)
    sys.exit(1)


def harness_source() -> tuple[str, list[str]]:
    src = KERNELS.read_text(encoding="utf-8")
    for old, new, times in EDITS:
        if src.count(old) != times:
            fail(f"kernels.dawn has {src.count(old)} of {old.strip()!r}, expected {times}")
        src = src.replace(old, new)
    if src.count(CUT_AT) != 1:
        fail(f"kernels.dawn has {src.count(CUT_AT)} of {CUT_AT.strip()!r}, expected 1")
    src = src[:src.index(CUT_AT)]
    start = src.index("fn trace(name: String) -> (TileProg, List[Call]) = match name {\n")
    end = src.index("\n}\n", start)
    body = src[start:end]
    names = re.findall(r'^  "([A-Za-z0-9_]+)" ->', body, re.M)
    arms = body.count("trace_kernel(")
    if arms != len(names) or src.count("trace_kernel(") != arms:
        fail(f"the dispatch has {len(names)} arms and {arms} trace_kernel calls; "
             f"the file has {src.count('trace_kernel(')}")
    src = src[:start] + body.replace("trace_kernel(", "trace_calls(") + src[end:]
    listed = ",\n".join(f'  "{n}"' for n in names)
    return src + MAIN.replace("%NAMES%", listed), names


def trace() -> str:
    src, names = harness_source()
    with tempfile.TemporaryDirectory(prefix="gpu-map.") as work:
        proj = Path(work)
        (proj / "src").mkdir()
        (proj / "src" / "main.dawn").write_text(src, encoding="utf-8")
        (proj / "dawn.toml").write_text(
            "schema = 1\nname = \"gpu_map\"\n\n[deps]\n"
            f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
            f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n",
            encoding="utf-8")
        r = subprocess.run([str(ROOT / "bin" / "dawn"), "run", str(proj)],
                           capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        fail("the harness did not run:\n" + (r.stderr or r.stdout)[-2000:])
    out = r.stdout
    seen = re.findall(r"^kernel (\S+)$", out, re.M)
    if seen != names:
        fail(f"the harness printed {len(seen)} kernels, the dispatch names {len(names)}")
    # Every mapped kernel's ranges must end where its golden ends.
    for block in out.split("kernel ")[1:]:
        name, _, rest = block.partition("\n")
        tail = re.search(r"^tail \d+-(\d+)$", rest, re.M)
        if tail:
            golden = (GOLDEN / f"{name}.mlir").read_text(encoding="utf-8")
            if int(tail.group(1)) - 1 != golden.count("\n"):
                fail(f"{name}: the map ends at line {int(tail.group(1)) - 1}, "
                     f"{name}.mlir has {golden.count(chr(10))} lines")
    return out


def main() -> None:
    record = sys.argv[1:] == ["--record"]
    if sys.argv[1:] not in ([], ["--record"]):
        fail("usage: record.py [--record]")
    fresh = trace()
    if record:
        OUT.write_text(fresh, encoding="utf-8")
        print(f"recorded {fresh.count('kernel ')} kernels into {OUT.relative_to(ROOT)}")
        return
    if not OUT.exists() or OUT.read_text(encoding="utf-8") != fresh:
        fail(f"{OUT.relative_to(ROOT)} is not what packages/tileir traces today; "
             "run `python3 site/gpu-map/record.py --record` and commit the result")
    print(f"OK: {OUT.relative_to(ROOT)} matches a fresh trace of {fresh.count('kernel ')} kernels")


if __name__ == "__main__":
    main()

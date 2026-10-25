#!/usr/bin/env python3
"""Exercise fresh six-argument source maps and typed launch mutations.

This is one work item of the existing golden matrix. The real Playground
planner produces the probe, the compiler executes it, and the real strict
pairer consumes its recording. Generated probe mutations therefore cannot
pass by comparing expected source strings alone.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DAWN = ROOT / "bin/dawn"

DRIVER = '''# Use the real planner and pairer on fresh compiler parser output.
use std/io
use std/io.{with_fs_real, read_file, write_file}
use playground/play/tilemap
fn read(path: String) -> String !io.Fs = match read_file(path) {
  Ok(s) -> s
  Err(e) -> panic(e.message)
}
pub fn main() -> Unit !io = with_fs_real(() => {
  let a = args()
  let code = read(a[1])
  let dump = read(a[2])
  let dev = tilemap.dev_names(read(a[3]))
  let p = match tilemap.plan(code, dump, dev) {
    Ok(p) -> p
    Err(e) -> panic("source plan: " ++ e)
  }
  if a[0] == "prepare" {
    let _p = write_file(a[4] ++ "/src/main.dawn", p.program)
    let _q = write_file(a[4] ++ "/src/explore_probe.dawn", tilemap.probe_source())
    println("PASS source plan")
  } else {
    let rec = match tilemap.read_recording(read(a[4])) {
      Ok(r) -> r
      Err(e) -> panic("source recording: " ++ e)
    }
    match tilemap.tile_map(code, p, rec) {
      Ok(m) -> print(m)
      Err(e) -> panic("source pairing: " ++ e)
    }
  }
})
'''


def main():
    with tempfile.TemporaryDirectory(prefix="entry6-source-") as tmp:
        work = Path(tmp)
        evidence = Path(os.environ.get("ENTRY6_CONTROL_EVIDENCE", work / "evidence"))
        evidence.mkdir(parents=True, exist_ok=True)
        receipts = []

        def run(tag, command, expect=0, fragment=None):
            result = subprocess.run([str(x) for x in command], cwd=ROOT,
                                    text=True, capture_output=True)
            (evidence / (tag + ".out")).write_text(result.stdout)
            (evidence / (tag + ".err")).write_text(result.stderr)
            good = (result.returncode == 0) if expect == 0 else (result.returncode != 0)
            if fragment is not None:
                good = good and fragment in result.stdout + result.stderr
            if not good:
                sys.exit(f"FAIL {tag}: exit={result.returncode}\n{result.stdout}\n{result.stderr}")
            receipts.append({"name": tag, "exit": result.returncode, "oracle": fragment})
            return result.stdout

        def project(path, source, playground=ROOT / "playground"):
            (path / "src").mkdir(parents=True, exist_ok=True)
            (path / "src/main.dawn").write_text(source)
            (path / "dawn.toml").write_text(
                'schema = 1\nname = "entry6_source"\n[deps]\n'
                f'tileir = "{ROOT / "packages/tileir"}"\n'
                f'playground = "{playground}"\n')

        driver = work / "driver"
        project(driver, DRIVER)
        run("driver-check", [DAWN, "check", driver])
        fixture = ROOT / "playground/test/tile_entry6.dawn"
        old = ROOT / "playground/test/tile_vadd.dawn"
        dev = ROOT / "packages/tileir/src/dev.dawn"

        def prepare(tag, source, tool=driver):
            dump = work / (tag + ".parse")
            dump.write_text(run(tag + "-parse", [DAWN, "parse", source]))
            proj = work / tag
            project(proj, "pub fn main() -> Unit = ()\n")
            run(tag + "-plan", [DAWN, "run", tool, "--", "prepare", source, dump, dev, proj])
            return proj, dump

        def verify(tag, proj, dump, source, tool=driver, refusal=None):
            output = work / (tag + ".record")
            output.write_text(run(tag + "-execute", [DAWN, "run", proj]))
            return run(tag + "-pair", [DAWN, "run", tool, "--", "verify", source, dump, dev, output],
                       expect=1 if refusal else 0, fragment=refusal)

        clean, dump = prepare("six-clean", fixture)
        mapped = verify("six-clean", clean, dump, fixture)
        if "tile_shape" not in mapped or "scalar" not in mapped:
            sys.exit("FAIL six-clean: actual zero IR/source calls missing")
        old_proj, old_dump = prepare("old-clean", old)
        verify("old-clean", old_proj, old_dump, old)

        read_fixture = ROOT / "playground/test/tile_read_layout.dawn"
        read_proj, read_dump = prepare("read-clean", read_fixture)
        read_map = verify("read-clean", read_proj, read_dump, read_fixture)
        for api in ["read_prefix", "read_blocks", "read_at", "tile_shape"]:
            if api not in read_map:
                sys.exit("FAIL read-clean: source API missing: " + api)
        lost_read = work / "read-missing-call"
        shutil.copytree(read_proj, lost_read)
        probe = lost_read / "src/explore_probe.dawn"
        old_loop = "for k in range(0, len(calls)) {"
        text = probe.read_text()
        if text.count(old_loop) != 1:
            sys.exit("read call anchor is not unique")
        probe.write_text(text.replace(old_loop, old_loop + '\n        if calls[k].name == "read_at" { continue }'))
        verify("read-missing-call", lost_read, read_dump, read_fixture, refusal="source ")

        # Remove grouping while expanding marker capacity so the altered tap
        # still records legally. Equality must detect its different layout.
        ungrouped = work / "read-lost-grouping"
        shutil.copytree(read_proj, ungrouped)
        probe = ungrouped / "src/explore_probe.dawn"
        text = probe.read_text()
        at = text.index("pub fn tap6[")
        prefix, six = text[:at], text[at:]
        helper = """use std/gpu
use tileir/prog
fn ungrouped[D](a: Arg[D]) -> Arg[D] = match a {
  In(d, prog.Grid(e, t, p, along, sq)) -> {
    let expanded = list.map(range(0, len(e)), j => match along[j] { gpu.Grouped(_k, g) -> e[j] * g, _ -> e[j] })
    let axes = list.map(along, axis => match axis { gpu.Grouped(k, _g) -> gpu.Axis(k), other -> other })
    In(d, prog.Grid(expanded, t, p, axes, sq))
  }
  other -> other
}
"""
        for marker in "abcdefg":
            six = six.replace(f"erase({marker})", f"erase(ungrouped({marker}))")
        probe.write_text(helper + prefix + six)
        verify("read-lost-grouping", ungrouped, read_dump, read_fixture,
               refusal="call marks changed the program")

        for tag, altered_probe in [("read-call-old", lost_read / "src/explore_probe.dawn"),
                                   ("read-group-old", ungrouped / "src/explore_probe.dawn")]:
            control = work / tag
            shutil.copytree(old_proj, control)
            (control / "src/explore_probe.dawn").write_text(altered_probe.read_text())
            verify(tag, control, old_dump, old)

        # Keep the sixth Param the same dtype as the fifth, so the misplaced
        # position is type-correct and reaches the recording-equality oracle.
        same = work / "six_same.dawn"
        text = fixture.read_text().replace("use std/int/i32.{I32}\n", "")
        text = text.replace(", int_to_float,", ",").replace("Param[I32]", "Param[F32]")
        text = text.replace("int_to_float(scalar(bias), F32)", "scalar(bias)").replace("Scalar(I32)", "Scalar(F32)")
        same.write_text(text)
        same_proj, same_dump = prepare("same-clean", same)
        verify("same-clean", same_proj, same_dump, same)

        def change_once(text, old, new):
            if text.count(old) != 1:
                sys.exit("generated probe anchor is not unique")
            return text.replace(old, new)

        for tag, source_proj, source_dump, source in [
                ("sixth-param", same_proj, same_dump, same),
                ("sixth-marker", clean, dump, fixture),
                ("lost-projection", clean, dump, fixture),
                ("wrong-axis", clean, dump, fixture),
                ("missing-call", clean, dump, fixture)]:
            proj = work / tag
            shutil.copytree(source_proj, proj)
            probe = proj / "src/explore_probe.dawn"
            text = probe.read_text()
            a = text.index("pub fn tap6[")
            prefix, six = text[:a], text[a:]
            if tag == "sixth-param":
                six = change_once(six, "param(dt(g), 5)", "param(dt(g), 4)")
            elif tag == "sixth-marker":
                six = change_once(six, "erase(g)", "erase(a)")
            elif tag in ("lost-projection", "wrong-axis"):
                transform = "[]" if tag == "lost-projection" else "sq"
                along = "along" if tag == "lost-projection" else "[gpu.Axis(0), gpu.Axis(2), gpu.Axis(1)]"
                helper = f'''fn altered[D](a: Arg[D]) -> Arg[D] = match a {{
  In(d, tileir.prog.Grid(e, t, p, along, sq)) -> In(d, tileir.prog.Grid(e, t, p, {along}, {transform}))
  Out(d, tileir.prog.Grid(e, t, p, along, sq)) -> Out(d, tileir.prog.Grid(e, t, p, {along}, {transform}))
  other -> other
}}
'''
                # Use a module alias for the existing public Cells constructors.
                helper = ("use std/gpu\n" if tag == "wrong-axis" else "") + "use tileir/prog\n" + helper.replace("tileir.prog.Grid", "prog.Grid")
                prefix = helper + prefix
                for marker in "abcdefg":
                    if f"erase({marker})" in six:
                        six = six.replace(f"erase({marker})", f"erase(altered({marker}))")
            else:
                prefix = change_once(prefix, "for k in range(0, len(calls)) {",
                                     'for k in range(0, len(calls)) {\n        if calls[k].name == "tile_shape" { continue }')
            probe.write_text(prefix + six)
            if tag == "sixth-marker":
                run(tag + "-execute", [DAWN, "run", proj], expect=1,
                    fragment="a scalar read takes a parameter passed by value")
            else:
                verify(tag, proj, source_dump, source,
                       refusal="source " if tag == "missing-call" else "call marks changed the program")

        # The recognition mutant leaves every old arity active. Both the
        # refused six-argument source and the real old three-argument map run.
        private = work / "recognition"
        shutil.copytree(ROOT / "playground", private / "playground",
                        ignore=shutil.ignore_patterns("build", ".dawn", "node_modules"))
        manifest = private / "playground/dawn.toml"
        manifest.write_text(manifest.read_text().replace("../packages/", str(ROOT / "packages") + "/"))
        run("recognition-mutate", [sys.executable, ROOT / "scripts/tile-golden/mutate.py",
                                   "entry6-map-unrecognized", private])
        tool = work / "recognition-driver"
        project(tool, DRIVER, private / "playground")
        run("recognition-check", [DAWN, "check", tool])
        refused = work / "refused"
        project(refused, "pub fn main() -> Unit = ()\n")
        run("recognition-red", [DAWN, "run", tool, "--", "prepare", fixture, dump, dev, refused],
            expect=1, fragment="does not record a kernel")
        p, d = prepare("recognition-old", old, tool)
        verify("recognition-old", p, d, old, tool)

        for mutation in ["entry6-launch-dropped", "entry6-launch-duplicated"]:
            private = work / mutation
            shutil.copytree(ROOT / "std", private / "std")
            run(mutation + "-mutate", [sys.executable, ROOT / "scripts/tile-golden/mutate.py", mutation, private])
            run(mutation + "-check", [DAWN, "check", "--std", private / "std", private / "std/gpu.dawn"])
            failed = run(mutation + "-red", [DAWN, "test", "--std", private / "std", private / "std/gpu.dawn"],
                         expect=1, fragment="FAIL  K3-0: six typed launch positions")
            if failed.count("FAIL  ") != 1:
                sys.exit(f"FAIL {mutation}: an older launch control also failed")
        run("read-unit-clean", [DAWN, "test", ROOT / "packages/tileir"])
        for mutation in ["read-prefix-cache", "read-drop-squeeze"]:
            private = work / mutation
            shutil.copytree(ROOT / "packages/tileir", private / "packages/tileir")
            run(mutation + "-mutate", [sys.executable, ROOT / "scripts/tile-golden/mutate.py", mutation, private])
            run(mutation + "-check", [DAWN, "check", private / "packages/tileir"])
            failed = run(mutation + "-red", [DAWN, "test", private / "packages/tileir"],
                         expect=1, fragment="FAIL  prog :: K3-G: distinct prefix views")
            if failed.count("FAIL  ") != 1:
                sys.exit("FAIL " + mutation + ": an unrelated unit control also failed")
        (evidence / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
        print("PASS entry6 source controls: fresh map, sixth position, projection, axis, call, recognition and launch order")


if __name__ == "__main__":
    main()

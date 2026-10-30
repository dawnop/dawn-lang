#!/usr/bin/env python3
"""Pin scaled MMA acceptance and semantic refusals using live bytecode.

The generator records through the current package, rather than patching a
golden. Every rejected case has an assembled positive control, and replaying
that control as the rejected case must fail the refusal classifier. Tool
failures, timeouts and unrelated diagnostics cannot count as a refusal.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


VALID = {
    "e4m3-e8m0": ("sm_100", "f8E4M3FN", "f8E8M0FNU"),
    "e5m2-e8m0": ("sm_100", "f8E5M2", "f8E8M0FNU"),
    "fp4-e8m0-v16": ("sm_100", "f4E2M1FN", "f4E2M1FN"),
    "fp4-e8m0-v32": ("sm_100", "f4E2M1FN", "f4E2M1FN"),
    "fp4-e4m3": ("sm_100", "f4E2M1FN", "f4E2M1FN"),
    "fp4-e5m3-v16": ("sm_107", "f4E2M1FN", "f4E2M1FN"),
    "fp4-e5m3-v32": ("sm_107", "f4E2M1FN", "f4E2M1FN"),
}

# Each diagnostic names the semantic seam, not the generic final failure.
INVALID = {
    "e4m3-e4m3": ("e4m3-e8m0", "unsupported combination of element types. Scale type 'f8E4M3FN'"),
    "e5m2-e4m3": ("e5m2-e8m0", "unsupported combination of element types. Scale type 'f8E4M3FN'"),
    "e4m3-e5m3": ("e4m3-e8m0", "unsupported combination of element types. Scale type 'fnv8E5M3FNU'"),
    "e5m2-e5m3": ("e5m2-e8m0", "unsupported combination of element types. Scale type 'fnv8E5M3FNU'"),
    "wide-operand": ("e4m3-e8m0", "operand #0 must be mmaf_scaled operand tile type"),
    "wide-scale": ("fp4-e4m3", "operand #3 must be mmaf_scaled scale tile type"),
    "mixed-operands": ("e4m3-e8m0", "all of {lhs, rhs} have the same element type"),
    "mixed-scales": ("fp4-e8m0-v16", "all of {lhs_scale, rhs_scale} have the same element type"),
    "fp8-v16": ("e4m3-e8m0", "f8 element type requires block scale factor of lhs_scale and rhs_scale to be 32"),
    "fp4-e8m0-v8": ("fp4-e8m0-v16", "f4E2M1FN element type with f8E8M0FNU scales requires block scale factor of lhs_scale and rhs_scale to be 16 or 32"),
    "fp4-e4m3-v32": ("fp4-e4m3", "f4E2M1FN element type with f8E4M3FN scales requires block scale factor of lhs_scale and rhs_scale to be 16"),
    "fp4-e5m3-v8": ("fp4-e5m3-v16", "f4E2M1FN element type with fnv8E5M3FNU scales requires block scale factor of lhs_scale and rhs_scale to be 16 or 32"),
    "rhs-block": ("fp4-e8m0-v16", "dim 1 of lhs_scale (4) and dim 0 of rhs_scale (2) must match"),
}


def accepted(row):
    return row["rc"] == 0 and "error:" not in row["log"] and row["cubin_bytes"] > 0


def refused(row, diagnostic):
    return (row["rc"] not in (0, 124, 137) and row["cubin_bytes"] == 0
            and any(line.startswith("error:") and diagnostic in line
                    for line in row["log"].splitlines()))


def run(cmd, log):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    log.write_text(p.stdout + p.stderr)
    return {"cmd": cmd, "rc": p.returncode, "log": p.stdout + p.stderr}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--producer-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tileiras")
    ap.add_argument("--arch", choices=("sm_100", "sm_90", "sm_86"))
    a = ap.parse_args()
    producer = json.loads(a.producer_json)
    if not isinstance(producer, list) or not producer or not all(isinstance(s, str) for s in producer):
        raise SystemExit("scaled combinations: producer must be a nonempty command array")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    generated = {}
    recording_control = None
    for name in [*VALID, *INVALID, "nondividing-block"]:
        tilebc = out / (name + ".tilebc")
        tilebc.unlink(missing_ok=True)
        row = run([*producer, "--scaled-probe", name, str(tilebc)], out / (name + ".record.log"))
        if name == "nondividing-block":
            expected = "mmaf_scaled over K=64 in blocks of 0, which does not divide it"
            if row["rc"] != 1 or expected not in row["log"] or tilebc.exists():
                raise SystemExit(f"scaled combinations: missing recording refusal: {row}")
            if recording_control is None or recording_control["rc"] != 0 or expected in recording_control["log"]:
                raise SystemExit("scaled combinations: missing accepted recording control")
            print("PASS scaled recording refusal: nondividing-block; repaired shape records", flush=True)
            continue
        if row["rc"] != 0 or not tilebc.exists() or not tilebc.stat().st_size:
            raise SystemExit(f"scaled combinations: could not generate {name}: {row}")
        generated[name] = tilebc
        if name == "fp4-e8m0-v16":
            recording_control = row
    if not a.tileiras:
        print("SKIP scaled assembly: no assembler supplied")
        return

    rows = []
    controls = {}

    def assemble(name, arch):
        cubin = out / (name + "." + arch + ".cubin")
        cubin.unlink(missing_ok=True)
        cmd = [a.tileiras, "--gpu-name", arch, "-o", str(cubin), str(generated[name])]
        row = run(cmd, out / (name + "." + arch + ".log"))
        row.update(case=name, arch=arch, input_sha256=hashlib.sha256(generated[name].read_bytes()).hexdigest(),
                   cubin_bytes=cubin.stat().st_size if cubin.exists() else 0,
                   cubin_sha256=hashlib.sha256(cubin.read_bytes()).hexdigest() if cubin.exists() else None)
        rows.append(row)
        (out / "receipts.json").write_text(json.dumps(rows, indent=2) + "\n")
        return row

    # A real accepted counterpart is required even on a rejecting target.
    for name, (floor, _, _) in VALID.items():
        row = assemble(name, floor)
        if not accepted(row):
            raise SystemExit(f"scaled combinations: positive control failed for {name}: {row}")
        controls[name] = row

    arches = [a.arch] if a.arch else ["sm_100", "sm_90", "sm_86"]
    for arch in arches:
        for name, (floor, ampere_type, hopper_type) in VALID.items():
            if arch == floor:
                row = controls[name]
                print(f"PASS scaled assembly: {name}@{arch}", flush=True)
                continue
            dt = ("fnv8E5M3FNU" if floor == "sm_107" and arch == "sm_100" else
                  ampere_type if arch == "sm_86" else hopper_type)
            diagnostic = f"Incompatibility with architecture '{arch}': unsupported type '{dt}'"
            row = assemble(name, arch)
            if not refused(row, diagnostic) or refused(controls[name], diagnostic):
                raise SystemExit(f"scaled combinations: architecture refusal/control failed for {name}@{arch}: {row}")
            print(f"PASS scaled refusal: {name}@{arch} type={dt}; accepted counterpart rejected as refusal control", flush=True)
        for name, (control, diagnostic) in INVALID.items():
            row = assemble(name, arch)
            if not refused(row, diagnostic) or refused(controls[control], diagnostic):
                raise SystemExit(f"scaled combinations: semantic refusal/control failed for {name}@{arch}: {row}")
            if generated[name].read_bytes() == generated[control].read_bytes():
                raise SystemExit(f"scaled combinations: {name} did not change the control bytes")
            print(f"PASS scaled refusal: {name}@{arch}; repaired type/shape control assembles", flush=True)

    # An unrelated compiler failure and an accepted output must not satisfy
    # any row. Real receipts provide both, with no synthetic exit-code oracle.
    wrong = next(row for row in rows if row["case"] == "wide-operand")
    for name, (_, diagnostic) in INVALID.items():
        if name != "wide-operand" and refused(wrong, diagnostic):
            raise SystemExit(f"scaled combinations: unrelated failure accepted for {name}")
    print(f"PASS scaled matrix: {len(rows)} assembly receipts; named refusals and accepted controls", flush=True)


if __name__ == "__main__":
    main()

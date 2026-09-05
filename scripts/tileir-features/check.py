#!/usr/bin/env python3
"""The Tile IR feature ledger's gate: every opcode is accounted for.

    scripts/tileir-features/check.py              # check features.txt
    scripts/tileir-features/check.py --self-test  # negative control

`features.txt` says, for each of the 100 public opcodes of the frozen table,
whether this backend implements it, which knife did it, and how far the
evidence goes. Its own header explains the columns and the three layers;
this turns each row into things a machine can look up.

The expected set is the OP_ table in packages/tileir/src/bytecode.dawn, held
in both directions: an OP_ constant with no `implemented` row is red, and so
is an `implemented` row the writer does not emit. That is what makes the
ledger shrink knife by knife instead of drifting: adding an opcode to the
writer without saying what covers it does not compile past this gate.

The rest of the file is not in the OP_ table and cannot be checked against
it, so the completeness of the 100 rows is pinned another way: the frozen
codes are 0x00 to 0x75 with two frozen gaps, and the set of codes here has
to be exactly that. A dropped row leaves a hole, and a hole is red.

What it does not check: that an opcode is emitted CORRECTLY. That is what
the layers themselves are for, and the evidence column names them.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLE = ROOT / "scripts" / "tileir-features" / "features.txt"
BYTECODE = ROOT / "packages" / "tileir" / "src" / "bytecode.dawn"
GOLDEN = ROOT / "scripts" / "tile-golden"
DIFF = ROOT / "scripts" / "tile-gpu-diff"
LEDGER = DIFF / "ledger.txt"

STATUSES = ("implemented", "unimplemented", "deferred", "structural")

# The coverage plan's knives that have LANDED. Every other `T` name is a
# knife the prestudy planned and nobody has cut, so the two directions are:
# an `implemented` row may not name an unlanded knife, and an
# `unimplemented` row may not name a landed one (the knife would have owed
# it). T0 built the ledger itself and added no opcode, so it names no row
# here; it is listed because the set is the record of which knives are done
# and not only of which ones a row may cite.
LANDED_KNIVES = {"T0", "T1", "T2"}

# The frozen public range and its two frozen gaps (BytecodeOpcodes.td), which
# together are the 100 opcodes this file has to carry a row for.
GAPS = set(range(0x19, 0x25)) | set(range(0x34, 0x3A))
EXPECTED_CODES = {c for c in range(0x00, 0x76) if c not in GAPS}

# The version deltas, so that a row cannot quietly claim 13.1 for an opcode
# that needs a newer assembler. Everything not named here entered at 13.1.
SINCE_13_2 = {"atan2"}
SINCE_13_3 = {"pack", "unpack", "alloca", "mmaf_scaled", "make_gather_scatter_view",
              "make_strided_view", "atomic_red_view_tko"}


def op_table(bytecode_text):
    """The writer's opcodes: mnemonic -> code, read off its OP_ constants."""
    return {name.lower(): int(code, 16) for name, code in
            re.findall(r"^const OP_([A-Z0-9_]+): Int = (0x[0-9A-Fa-f]+)", bytecode_text, re.M)}


def rows(text):
    """The table's data lines, as lists of fields."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append((n, [f.strip() for f in s.split("|")]))
    return out


def read(path):
    return path.read_text() if path.exists() else ""


def check(table_text, bytecode_text, files, ledger_text):
    """The opcodes the table lists, and what is wrong with it.

    `files` maps a repository path to its contents (the .mlir goldens, the
    layer-2 programs and the two mutant scripts); `ledger_text` is the
    layer-2 ledger. Everything the checker reads arrives here, so the
    self-test can hand it a tree nobody would commit.
    """
    problems = []
    ops = op_table(bytecode_text)
    if not ops:
        problems.append("packages/tileir/src/bytecode.dawn has no OP_ constants at all")

    mutants = files.get("scripts/tile-golden/run.sh", "") + \
        files.get("scripts/tile-gpu-diff/run.sh", "")
    devices = "\n".join(v for k, v in files.items() if k.startswith("scripts/tile-gpu-diff/")
                        and k.endswith(".dawn"))

    seen = {}
    codes = {}
    counts = {s: 0 for s in STATUSES}
    layers = {}
    for n, fields in rows(table_text):
        if len(fields) != 8:
            problems.append(f"line {n}: {len(fields)} fields, not 8")
            continue
        name, code, since, status, knife, layer, evidence, exemption = fields

        if name in seen:
            problems.append(f"line {n}: opcode {name} is already listed on line {seen[name]}")
            continue
        seen[name] = n

        if not re.fullmatch(r"0x[0-9A-F]{2}", code):
            problems.append(f"line {n}: code {code!r} is not a two-digit upper-case hex byte")
            continue
        value = int(code, 16)
        if value in codes:
            problems.append(f"line {n}: code {code} is already {codes[value]}'s")
        else:
            codes[value] = name

        want_since = "13.2" if name in SINCE_13_2 else "13.3" if name in SINCE_13_3 else "13.1"
        if since != want_since:
            problems.append(f"line {n}: {name} entered at {want_since}, not {since}")

        if status not in STATUSES:
            problems.append(f"line {n}: status {status!r} is not one of {', '.join(STATUSES)}")
            continue
        counts[status] += 1

        if not layer.isdigit() or int(layer) > 3:
            problems.append(f"line {n}: layer {layer!r} is not 0, 1, 2 or 3")
            continue
        layer = int(layer)
        layers[layer] = layers.get(layer, 0) + 1

        if not knife:
            problems.append(f"line {n}: {name} names no knife")
        planned = knife.startswith("T") and knife not in LANDED_KNIVES

        # The two directions against the writer's own table.
        if status == "implemented":
            if name not in ops:
                problems.append(
                    f"line {n}: {name} is marked implemented but packages/tileir/src/bytecode.dawn "
                    f"has no OP_{name.upper()}")
            elif ops[name] != value:
                problems.append(
                    f"line {n}: {name} is {code} here and 0x{ops[name]:02X} in bytecode.dawn")
            if planned:
                problems.append(
                    f"line {n}: {name} is implemented, so knife {knife!r} cannot be a planned one")
        else:
            if name in ops:
                problems.append(
                    f"line {n}: {name} is marked {status} but bytecode.dawn emits OP_{name.upper()}")

        if status in ("unimplemented", "deferred"):
            if layer != 0:
                problems.append(f"line {n}: {name} is {status}, so its layer is 0, not {layer}")
            if evidence != "-":
                problems.append(f"line {n}: {name} is {status} but names evidence {evidence!r}")
            if status == "unimplemented" and not planned:
                problems.append(
                    f"line {n}: {name} is unimplemented, so its knife is a planned one (T...), "
                    f"not {knife!r}")
        if status == "deferred" and exemption == "-":
            problems.append(f"line {n}: {name} is deferred with no named reason")

        if status not in ("implemented", "structural"):
            continue
        if layer < 1:
            problems.append(f"line {n}: {name} is {status}, so it is covered at layer 1 at least")

        tokens = [t for t in evidence.split(",") if t]
        goldens = [t.split(":", 1)[1] for t in tokens if t.startswith("golden:")]
        named = [t.split(":", 1)[1] for t in tokens if t.startswith("mutant:")]
        writers = [t.split(":", 1)[1] for t in tokens if t.startswith("writer:")]
        for t in tokens:
            if not t.startswith(("golden:", "mutant:", "writer:")):
                problems.append(f"line {n}: {name} names evidence {t!r}, which is not "
                                f"golden:, mutant: or writer:")

        if layer >= 2 and not goldens:
            problems.append(
                f"line {n}: {name} claims layer {layer} and names no golden. Layer 2 is a device "
                f"answer, and a device only ran the kernels the goldens hold")
        if layer == 1 and goldens:
            problems.append(
                f"line {n}: {name} claims only layer 1 and yet names a golden {goldens[0]}")
        for g in goldens:
            path = f"scripts/tile-golden/{g}.mlir"
            if path not in files:
                problems.append(f"line {n}: {name} names golden {g}, which has no .mlir")
                continue
            if not re.search(r"(?<![\w])%s(?![\w])" % re.escape(name), files[path]):
                problems.append(
                    f"line {n}: {name} names golden {g}, whose .mlir does not contain the op")
            if f'"{g}"' not in devices:
                problems.append(
                    f"line {n}: {name} names golden {g}, which no scripts/tile-gpu-diff program "
                    f"launches, so no device has answered for it")

        if layer == 3 and not named:
            problems.append(
                f"line {n}: {name} claims layer 3 and names no mutant. Layer 3 IS the mutant")
        for m in named:
            if m not in mutants:
                problems.append(
                    f"line {n}: {name} names mutant {m}, which neither scripts/tile-golden/run.sh "
                    f"nor scripts/tile-gpu-diff/run.sh defines")

        if status == "structural" and not writers:
            problems.append(
                f"line {n}: {name} is structural and names no writer: it is not in the instruction "
                f"stream, so the function that emits it is the evidence")
        for fn in writers:
            if not re.search(r"^(pub )?fn %s\b" % re.escape(fn), bytecode_text, re.M):
                problems.append(f"line {n}: {name} names writer {fn}, which bytecode.dawn does "
                                f"not define")

    missing = sorted(EXPECTED_CODES - set(codes))
    extra = sorted(set(codes) - EXPECTED_CODES)
    for c in missing:
        problems.append(f"opcode 0x{c:02X} of the frozen table has no row")
    for c in extra:
        problems.append(f"0x{c:02X} ({codes[c]}) is not a public opcode of the frozen table")

    for name, value in sorted(ops.items()):
        if name not in seen:
            problems.append(
                f"bytecode.dawn emits OP_{name.upper()} (0x{value:02X}) and the ledger has no row "
                f"for it")

    entries = [ln.split("#", 1)[0].split() for ln in ledger_text.splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    if any(layer >= 2 for layer in layers if layers[layer]):
        if not entries:
            problems.append("scripts/tile-gpu-diff/ledger.txt has no entry: nothing has run on a "
                            "device, so no row here may claim layer 2")
        elif len(entries[-1]) != 6:
            problems.append("the last line of scripts/tile-gpu-diff/ledger.txt does not parse")
        elif entries[-1][5] != "pass":
            problems.append(
                f"the last layer-2 run recorded {entries[-1][5]!r}, not `pass`: an opcode is "
                f"covered at layer 2 only while a device has agreed")
    return counts, layers, problems


def gather():
    files = {}
    for golden in GOLDEN.glob("*.mlir"):
        files[f"scripts/tile-golden/{golden.name}"] = golden.read_text()
    for program in DIFF.glob("*.dawn"):
        files[f"scripts/tile-gpu-diff/{program.name}"] = program.read_text()
    files["scripts/tile-golden/run.sh"] = read(GOLDEN / "run.sh")
    files["scripts/tile-gpu-diff/run.sh"] = read(DIFF / "run.sh")
    return files


def self_test():
    """Every verdict above, on a ledger built to trip it, and a clean control."""
    files = gather()
    good = TABLE.read_text()
    bytecode = BYTECODE.read_text()
    ledger = read(LEDGER)
    _counts, _layers, problems = check(good, bytecode, files, ledger)
    if problems:
        print("FAIL: --self-test needs the real ledger to be clean first:")
        for p in problems:
            print("  " + p)
        return 1

    # An opcode no golden holds, for the layer-2 control below. It has to be
    # one no knife has implemented (knife T2 took the one T0 used here) and
    # whose mnemonic does not occur in vadd's text.
    absent = "assume"

    cases = [
        ("a row with too few fields",
         good + "\nnope | 0x76 | 13.1 | unimplemented | T1 | 0\n", "fields, not 8"),
        ("the same opcode twice",
         good + "\nabsf | 0x00 | 13.1 | unimplemented | T1 | 0 | - | -\n", "is already listed"),
        ("a row whose code disagrees with bytecode.dawn",
         good.replace("addf                     | 0x02", "addf                     | 0x03"),
         "0x03 here and 0x02 in bytecode.dawn"),
        ("a ledger with one row missing",
         "\n".join(ln for ln in good.splitlines() if not ln.startswith("tanh ")) + "\n",
         "opcode 0x6A of the frozen table has no row"),
        ("an opcode the writer emits and the ledger calls unimplemented",
         good.replace("tanh                     | 0x6A | 13.1 | implemented   | 7b ",
                      "tanh                     | 0x6A | 13.1 | unimplemented | T1 "),
         "bytecode.dawn emits OP_TANH"),
        ("a row claiming an opcode the writer does not emit",
         good.replace("break                    | 0x0A | 13.1 | unimplemented | T5  | 0 | -",
                      "break                    | 0x0A | 13.1 | implemented   | 7b  | 2 | "
                      "golden:mathops"),
         "has no OP_BREAK"),
        ("a version the deltas contradict",
         good.replace("atan2                    | 0x6E | 13.2", "atan2                    | 0x6E | 13.1"),
         "atan2 entered at 13.2, not 13.1"),
        ("a layer-2 claim for an op no golden contains",
         good.replace(f"{absent:24s} | 0x06 | 13.1 | unimplemented | T6  | 0 | -",
                      f"{absent:24s} | 0x06 | 13.1 | implemented   | 3   | 2 | golden:vadd"),
         "whose .mlir does not contain the op"),
        ("an implemented row whose knife has not landed",
         good.replace("tanh                     | 0x6A | 13.1 | implemented   | 7b ",
                      "tanh                     | 0x6A | 13.1 | implemented   | T9 "),
         "cannot be a planned one"),
        ("an unimplemented row whose knife is not a planned one",
         good.replace(f"{absent:24s} | 0x06 | 13.1 | unimplemented | T6 ",
                      f"{absent:24s} | 0x06 | 13.1 | unimplemented | 3  "),
         "so its knife is a planned one"),
        ("a layer-3 claim with no mutant named",
         good.replace("| 3 | golden:histogram,mutant:atomic-rmw-claims-weak-ordering,"
                      "mutant:atomic-as-plain-store",
                      "| 3 | golden:histogram                                        "),
         "claims layer 3 and names no mutant"),
        ("a mutant nobody defines",
         good.replace("mutant:addf-no-rounding", "mutant:addf-no-rounder "),
         "names mutant addf-no-rounder"),
        ("a structural row with no writer",
         good.replace("golden:ols_beta,writer:encode_kernel", "golden:ols_beta                 ", 1),
         "is structural and names no writer"),
        ("a deferred row with no reason",
         re.sub(r"^(\S+ +\| .* \| deferred .*\| )ruling 2$", r"\1-", good, count=1, flags=re.M),
         "is deferred with no named reason"),
        ("an implemented row under a knife nobody has cut",
         good.replace("sin                      | 0x62 | 13.1 | implemented   | T1 ",
                      "sin                      | 0x62 | 13.1 | implemented   | T5 "),
         "knife 'T5' cannot be a planned one"),
        ("an unimplemented row under a knife that has landed",
         good.replace("break                    | 0x0A | 13.1 | unimplemented | T5 ",
                      "break                    | 0x0A | 13.1 | unimplemented | T1 "),
         "so its knife is a planned one"),
        ("an empty ledger", "# nothing\n", "of the frozen table has no row"),
    ]
    bad = 0
    for name, text, want in cases:
        if text == good:
            print(f"FAIL  self-test: {name} did not change the ledger (the anchor moved)")
            bad += 1
            continue
        _c, _l, found = check(text, bytecode, files, ledger)
        if any(want in p for p in found):
            print(f"PASS  self-test: {name}")
        else:
            print(f"FAIL  self-test: {name} was accepted (wanted {want!r}, got {found})")
            bad += 1

    # The other input: an OP_ the writer grew and nobody wrote down.
    grown = bytecode.replace("const OP_TANH: Int = 0x6A",
                             "const OP_TANH: Int = 0x6A\nconst OP_ASSUME: Int = 0x06")
    _c, _l, found = check(good, grown, files, ledger)
    if any("OP_ASSUME (0x06) and the ledger has no row" in p or "marked unimplemented but" in p
           for p in found):
        print("PASS  self-test: an OP_ constant the ledger does not call implemented")
    else:
        print(f"FAIL  self-test: an unrecorded OP_ was accepted (got {found})")
        bad += 1

    _c, _l, found = check(good, bytecode, files, "# only a comment\n")
    if any("has no entry" in p for p in found):
        print("PASS  self-test: an empty layer-2 ledger under layer-2 claims")
    else:
        print(f"FAIL  self-test: an empty device ledger was accepted (got {found})")
        bad += 1

    _c, _l, found = check(good, bytecode, files, ledger)
    if found:
        print(f"FAIL  self-test: the real ledger stopped being clean: {found}")
        bad += 1
    else:
        print("PASS  self-test: the real ledger is clean (the positive control)")
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ["--self-test"]:
        return self_test()
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 2
    counts, layers, problems = check(TABLE.read_text(), BYTECODE.read_text(), gather(),
                                     read(LEDGER))
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    hist = " ".join(f"layer{k}={layers[k]}" for k in sorted(layers))
    print(f"PASS  tileir features: {sum(counts.values())} opcode(s): "
          f"implemented={counts['implemented']} unimplemented={counts['unimplemented']} "
          f"deferred={counts['deferred']} structural={counts['structural']}; {hist}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

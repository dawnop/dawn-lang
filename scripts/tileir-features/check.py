#!/usr/bin/env python3
"""The Tile IR coverage ledgers' gate: every opcode, every type tag and
every attribute value is accounted for.

    scripts/tileir-features/check.py              # check all three ledgers
    scripts/tileir-features/check.py --self-test  # negative control

`features.txt` says, for each of the 100 public opcodes of the frozen table,
whether this backend implements it, which knife did it, and how far the
evidence goes. `types.txt` says the same for each of the 23 type tags, and
`attrs.txt` (knife T4) for each of the 44 values of the attribute domains.
Their own headers explain the columns and the three layers; this turns each
row into things a machine can look up.

ONE PARSER, THREE TABLES. All three files have the same eight columns and
the same rules about statuses, knives and layers (`parse_rows` and
`common_checks` below); what differs is the expected set each is held to and
what a piece of evidence looks like. Knife T3 wrote that the third table
should need neither of those two functions changed, and knife T4 confirmed
it: `attrs.txt` is one more `Ledger` entry, one `check_attrs` and one
`attr_cases`.

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
TYPES = ROOT / "scripts" / "tileir-features" / "types.txt"
ATTRS = ROOT / "scripts" / "tileir-features" / "attrs.txt"
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
LANDED_KNIVES = {"T0", "T1", "T2", "T3", "T4", "T5", "T6"}


class Ledger:
    """One coverage ledger: where it lives, what its rows count, the
    function that holds it to the writer, and its self-test's cases.

    Adding a table is one entry in TABLES below. What a table cannot share
    is its RULES -- an opcode's evidence and a type tag's are different
    shapes -- so each brings its own `check` and its own `cases`; what they
    do share is the parser (`parse_rows`), the status / knife / layer rules
    (`common_checks`) and the evidence splitter (`evidence_of`).
    """

    def __init__(self, name, path, unit, check, cases):
        self.name = name
        self.path = path
        self.unit = unit
        self.check = check
        self.cases = cases

# The frozen public range and its two frozen gaps (BytecodeOpcodes.td), which
# together are the 100 opcodes this file has to carry a row for.
GAPS = set(range(0x19, 0x25)) | set(range(0x34, 0x3A))
EXPECTED_CODES = {c for c in range(0x00, 0x76) if c not in GAPS}

# The version deltas, so that a row cannot quietly claim 13.1 for an opcode
# that needs a newer assembler. Everything not named here entered at 13.1.
SINCE_13_2 = {"atan2"}
SINCE_13_3 = {"pack", "unpack", "alloca", "mmaf_scaled", "make_gather_scatter_view",
              "make_strided_view", "atomic_red_view_tko"}


# The frozen TYPE tags (BytecodeTypeOpcodes.td): 0 to 22, and unlike the
# opcode table there are no gaps in it.
EXPECTED_TAGS = set(range(0, 23))

# The type versions, read the same way the opcode ones are.
TYPES_SINCE_13_2 = {"f8E8M0FNU"}
TYPES_SINCE_13_3 = {"f4E2M1FN", "GatherScatterView", "StridedViewType", "i4"}


# Every value of every attribute domain AttrDefs.td defines, as
# `family.value -> (code, version)`. The six enums are read off their
# `CudaTileI32EnumAttrCase` lists; the unit attributes are read off Ops.td,
# and a UnitAttr's code is the flags BIT it sets rather than an enum value.
# `ComparisonPredicate` and `Signedness` are left out for the reason
# attrs.txt's header gives.
EXPECTED_ATTRS = {}


def _attr_family(family, version, values):
    for value, code in values:
        EXPECTED_ATTRS[f"{family}.{value}"] = (code, version)


_attr_family("rounding", "13.1", [("nearest_even", 0), ("zero", 1), ("negative_inf", 2),
                                  ("positive_inf", 3), ("approx", 4), ("full", 5),
                                  ("nearest_int_to_zero", 6)])
_attr_family("overflow", "13.1", [("none", 0), ("nsw", 1), ("nuw", 2), ("nw", 3)])
_attr_family("ordering", "13.1", [("unordered", 0), ("ordered", 1)])
_attr_family("scope", "13.1", [("tl_blk", 0), ("device", 1), ("sys", 2)])
_attr_family("memsem", "13.1", [("weak", 0), ("relaxed", 1), ("acquire", 2), ("release", 3),
                                ("acq_rel", 4)])
_attr_family("rmw", "13.1", [("and", 0), ("or", 1), ("xor", 2), ("add", 3), ("addf", 4),
                             ("max", 5), ("min", 6), ("umax", 7), ("umin", 8), ("xchg", 9)])
_attr_family("unit", "13.1", [("flush_to_zero", 1), ("propagate_nan", 1)])
_attr_family("unit", "13.2", [("unsignedCmp", 1)])
_attr_family("unit", "13.3", [("fast_acc", 1), ("constant", 1), ("global", 1)])
_attr_family("padding", "13.1", [("zero", 0), ("neg_zero", 1), ("nan", 2), ("pos_inf", 3),
                                 ("neg_inf", 4)])
_attr_family("visibility", "13.1", [("public", 0), ("private", 1)])
# The bytecode ATTRIBUTE TAGS (BytecodeAttrOpcodes.td), which are a third
# authority: AttrDefs.td says what an attribute MEANS and this says which byte
# announces it where one is written self-contained. Knife T6 writes four of
# the twelve; `Integer` (1) and `Float` (2) are knife 3's reduction identities
# and are not in ruling 6's list.
_attr_family("tag", "13.1", [("String", 5), ("DivBy", 8), ("SameElements", 9),
                             ("Bounded", 12)])


def parse_rows(text):
    """The eight fields of every data line, and what is malformed about one.

    Shared by both ledgers: they have the same columns, and a third table
    (knife T4's attribute values) is expected to have them too.
    """
    out = []
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        fields = [f.strip() for f in s.split("|")]
        if len(fields) != 8:
            problems.append(f"line {n}: {len(fields)} fields, not 8")
            continue
        out.append((n, fields))
    return out, problems


def common_checks(n, name, status, knife, layer, seen):
    """The rules both ledgers share: no duplicate name, a known status, a
    layer in range, and a knife that is either landed or planned to match
    the status. Answers the problems and whether the knife is a planned one.
    """
    problems = []
    if name in seen:
        problems.append(f"line {n}: {name} is already listed on line {seen[name]}")
        return problems, False, None
    seen[name] = n
    if status not in STATUSES:
        problems.append(f"line {n}: status {status!r} is not one of {', '.join(STATUSES)}")
        return problems, False, None
    if not layer.isdigit() or int(layer) > 3:
        problems.append(f"line {n}: layer {layer!r} is not 0, 1, 2 or 3")
        return problems, False, None
    if not knife:
        problems.append(f"line {n}: {name} names no knife")
    planned = knife.startswith("T") and knife not in LANDED_KNIVES
    if status == "implemented" and planned:
        problems.append(
            f"line {n}: {name} is implemented, so knife {knife!r} cannot be a planned one")
    if status == "unimplemented" and not planned:
        problems.append(
            f"line {n}: {name} is unimplemented, so its knife is a planned one (T...), "
            f"not {knife!r}")
    return problems, planned, int(layer)


def evidence_of(n, name, evidence, kinds):
    """The evidence tokens by kind, and a complaint for a kind this table
    does not have."""
    problems = []
    found = {k: [] for k in kinds}
    for token in [t for t in evidence.split(",") if t]:
        kind, _, rest = token.partition(":")
        if kind in found and rest:
            found[kind].append(rest)
        else:
            problems.append(f"line {n}: {name} names evidence {token!r}, which is not "
                            + " or ".join(k + ":" for k in kinds))
    return found, problems


def tag_table(bytecode_text):
    """The writer's type tags: spelling -> tag. `num_tag`'s arms give the
    scalar formats and the `TAG_` constants give the constructors, and the
    constants are named after the C++ type (TAG_FUNC is FunctionType), so
    the ledger's own spelling for those four is what maps them."""
    body = re.search(r"^fn num_tag\(.*?\{\n(.*?)^\}", bytecode_text, re.M | re.S)
    if not body:
        return {}
    tags = {name: int(value) for name, value in
            re.findall(r'^\s*"([A-Za-z0-9]+)" -> (\d+)$', body.group(1), re.M)}
    for name, value in re.findall(r"^const TAG_([A-Z]+): Int = (\d+)", bytecode_text, re.M):
        tags[CONSTRUCTOR_SPELLING[name]] = int(value)
    return tags


# The ledger's spelling of each constructor the writer names with a `TAG_`
# constant. `ptr`, `tile` and `token` are how a .mlir prints them;
# FunctionType has no textual spelling here (the entry's signature is a
# type-section entry and never appears in the text), so it keeps the
# dialect's C++ name, as the view types do.
CONSTRUCTOR_SPELLING = {"PTR": "ptr", "TILE": "tile", "FUNC": "FunctionType",
                        "TOKEN": "token"}


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


def check_types(table_text, bytecode_text, files, ledger_text):
    """The type tags the table lists, and what is wrong with it.

    The same shape as `check` above and the same inputs, so the self-test
    can hand it a tree nobody would commit. What is different is the
    expected set (the writer's tag table rather than its OP_ table) and the
    evidence kinds: a type has a `device:` token where an opcode's
    `golden:` carries both jobs at once, because a type can be spelled in a
    kernel the device cannot run -- which is exactly the fp8 case this
    ledger exists to record.
    """
    problems = []
    tags = tag_table(bytecode_text)
    if not tags:
        problems.append("packages/tileir/src/bytecode.dawn has no type tag table at all")

    mutants = files.get("scripts/tile-golden/run.sh", "") + \
        files.get("scripts/tile-gpu-diff/run.sh", "")
    devices = "\n".join(v for k, v in files.items() if k.startswith("scripts/tile-gpu-diff/")
                        and k.endswith(".dawn"))

    rows_, problems_ = parse_rows(table_text)
    problems += problems_
    seen = {}
    codes = {}
    counts = {s: 0 for s in STATUSES}
    layers = {}
    for n, fields in rows_:
        name, tag, since, status, knife, layer, evidence, exemption = fields

        shared, planned, layer = common_checks(n, name, status, knife, layer, seen)
        problems += shared
        if layer is None:
            continue
        counts[status] += 1
        layers[layer] = layers.get(layer, 0) + 1

        if not re.fullmatch(r"\d{1,2}", tag):
            problems.append(f"line {n}: tag {tag!r} is not a one or two digit decimal number")
            continue
        value = int(tag)
        if value in codes:
            problems.append(f"line {n}: tag {tag} is already {codes[value]}'s")
        else:
            codes[value] = name

        want = "13.2" if name in TYPES_SINCE_13_2 else \
            "13.3" if name in TYPES_SINCE_13_3 else "13.1"
        if since != want:
            problems.append(f"line {n}: {name} entered at {want}, not {since}")

        # The two directions against the writer's own tag table.
        if status == "implemented":
            if name not in tags:
                problems.append(
                    f"line {n}: {name} is marked implemented but packages/tileir/src/"
                    f"bytecode.dawn writes no tag for it")
            elif tags[name] != value:
                problems.append(
                    f"line {n}: {name} is tag {value} here and {tags[name]} in bytecode.dawn")
        elif name in tags:
            problems.append(
                f"line {n}: {name} is marked {status} but bytecode.dawn writes its tag")

        if status in ("unimplemented", "deferred"):
            if layer != 0:
                problems.append(f"line {n}: {name} is {status}, so its layer is 0, not {layer}")
            if evidence != "-":
                problems.append(f"line {n}: {name} is {status} but names evidence {evidence!r}")
        if status == "deferred" and exemption == "-":
            problems.append(f"line {n}: {name} is deferred with no named reason")
        if status not in ("implemented", "structural"):
            continue

        if layer < 1:
            problems.append(f"line {n}: {name} is {status}, so it is covered at layer 1 at least")
        # The bar is layer 2 (ruling 1), so a row below it owes a reason and
        # a row at or above it may not carry one.
        if layer < 2 and exemption == "-":
            problems.append(
                f"line {n}: {name} stops at layer {layer} and names no reason. The bar is layer 2, "
                f"so anything short of it is an exemption and not a gap")
        if layer >= 2 and exemption != "-":
            problems.append(
                f"line {n}: {name} reaches layer {layer} and still claims the exemption "
                f"{exemption!r}")

        found, ev_problems = evidence_of(n, name, evidence,
                                         ("golden", "device", "mutant", "writer"))
        problems += ev_problems
        goldens, launched, named, writers = (found["golden"], found["device"],
                                             found["mutant"], found["writer"])

        if not goldens and not writers:
            problems.append(
                f"line {n}: {name} names neither a golden nor a writer. A type with a textual "
                f"spelling names the kernel that spells it; one without names the function that "
                f"emits its tag")
        for g in goldens:
            path = f"scripts/tile-golden/{g}.mlir"
            if path not in files:
                problems.append(f"line {n}: {name} names golden {g}, which has no .mlir")
            elif not spelled(files[path], name):
                problems.append(
                    f"line {n}: {name} names golden {g}, whose .mlir does not spell the type")

        if layer >= 2 and not launched:
            problems.append(
                f"line {n}: {name} claims layer {layer} and names no device kernel. Layer 2 is a "
                f"device answer, and a device only ran the kernels a tile-gpu-diff program "
                f"launches")
        if layer < 2 and launched:
            problems.append(
                f"line {n}: {name} stops at layer {layer} and yet names the device kernel "
                f"{launched[0]}")
        for d in launched:
            if f'"{d}"' not in devices:
                problems.append(
                    f"line {n}: {name} names device kernel {d}, which no scripts/tile-gpu-diff "
                    f"program launches")

        if layer == 3 and not named:
            problems.append(
                f"line {n}: {name} claims layer 3 and names no mutant. Layer 3 IS the mutant")
        for m in named:
            if m not in mutants:
                problems.append(
                    f"line {n}: {name} names mutant {m}, which neither scripts/tile-golden/run.sh "
                    f"nor scripts/tile-gpu-diff/run.sh defines")
        for fn in writers:
            if not re.search(r"^(pub )?fn %s\b" % re.escape(fn), bytecode_text, re.M):
                problems.append(f"line {n}: {name} names writer {fn}, which bytecode.dawn does "
                                f"not define")

    for c in sorted(EXPECTED_TAGS - set(codes)):
        problems.append(f"type tag {c} of the frozen table has no row")
    for c in sorted(set(codes) - EXPECTED_TAGS):
        problems.append(f"{c} ({codes[c]}) is not a type tag of the frozen table")
    for name in sorted(tags):
        if name not in seen:
            problems.append(
                f"bytecode.dawn writes a tag for {name} ({tags[name]}) and the ledger has no row "
                f"for it")

    entries = [ln.split("#", 1)[0].split() for ln in ledger_text.splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    if any(layer >= 2 for layer in layers if layers[layer]):
        if not entries:
            problems.append("scripts/tile-gpu-diff/ledger.txt has no entry: nothing has run on a "
                            "device, so no row here may claim layer 2")
        elif entries[-1][5:6] != ["pass"]:
            problems.append(
                "the last layer-2 run in scripts/tile-gpu-diff/ledger.txt did not pass: a type "
                "is covered at layer 2 only while a device has agreed")
    return counts, layers, problems


def const_table(bytecode_text):
    """The writer's named integer constants: NAME -> value. This is what
    binds attrs.txt to the writer, the way `op_table` binds features.txt
    and `tag_table` binds types.txt."""
    return {name: int(value, 0) for name, value in
            re.findall(r"^const ([A-Z0-9_]+): Int = (0x[0-9A-Fa-f]+|\d+)", bytecode_text, re.M)}


def check_attrs(table_text, bytecode_text, files, ledger_text):
    """The attribute values the table lists, and what is wrong with it.

    The same shape and the same inputs as the two above. What is its own:
    the expected set is AttrDefs.td's enums rather than anything in the
    writer, so the binding to the writer is per row (`const:` names a
    constant whose VALUE must be the row's code); and `golden:` is not held
    to the .mlir spelling the value, because most of these values are the
    dialect's defaults and its printer leaves them out.
    """
    problems = []
    consts = const_table(bytecode_text)
    if not consts:
        problems.append("packages/tileir/src/bytecode.dawn has no integer constants at all")

    mutants = files.get("scripts/tile-golden/run.sh", "") + \
        files.get("scripts/tile-gpu-diff/run.sh", "")
    devices = "\n".join(v for k, v in files.items() if k.startswith("scripts/tile-gpu-diff/")
                        and k.endswith(".dawn"))

    rows_, problems_ = parse_rows(table_text)
    problems += problems_
    seen = {}
    counts = {s: 0 for s in STATUSES}
    layers = {}
    for n, fields in rows_:
        name, code, since, status, knife, layer, evidence, exemption = fields

        shared, _planned, layer = common_checks(n, name, status, knife, layer, seen)
        problems += shared
        if layer is None:
            continue
        counts[status] += 1
        layers[layer] = layers.get(layer, 0) + 1

        if name not in EXPECTED_ATTRS:
            problems.append(f"line {n}: {name} is not a value of any attribute domain "
                            f"AttrDefs.td defines")
            continue
        want_code, want_since = EXPECTED_ATTRS[name]
        if not re.fullmatch(r"\d+", code):
            problems.append(f"line {n}: code {code!r} is not a decimal enum value or flag bit")
            continue
        if int(code) != want_code:
            problems.append(f"line {n}: {name} is {want_code} in AttrDefs.td and {code} here")
        if since != want_since:
            problems.append(f"line {n}: {name} entered at {want_since}, not {since}")

        if status in ("unimplemented", "deferred"):
            if layer != 0:
                problems.append(f"line {n}: {name} is {status}, so its layer is 0, not {layer}")
            if evidence != "-":
                problems.append(f"line {n}: {name} is {status} but names evidence {evidence!r}")
        if status == "deferred" and exemption == "-":
            problems.append(f"line {n}: {name} is deferred with no named reason")
        if status != "implemented":
            continue

        if layer < 1:
            problems.append(f"line {n}: {name} is implemented, so it is covered at layer 1 "
                            f"at least")
        if layer < 2 and exemption == "-":
            problems.append(
                f"line {n}: {name} stops at layer {layer} and names no reason. The bar is layer 2, "
                f"so anything short of it is an exemption and not a gap")
        if layer >= 2 and exemption != "-":
            problems.append(
                f"line {n}: {name} reaches layer {layer} and still claims the exemption "
                f"{exemption!r}")

        found, ev_problems = evidence_of(n, name, evidence,
                                         ("const", "writer", "golden", "device", "mutant"))
        problems += ev_problems
        constants, writers, goldens, launched, named = (found["const"], found["writer"],
                                                        found["golden"], found["device"],
                                                        found["mutant"])

        if not constants and not writers:
            problems.append(
                f"line {n}: {name} names neither a const: nor a writer:. Something in "
                f"bytecode.dawn holds this value, and naming it is what keeps the ledger and the "
                f"writer one thing")
        for c in constants:
            if c not in consts:
                problems.append(f"line {n}: {name} names const {c}, which bytecode.dawn does not "
                                f"define")
            elif consts[c] != int(code):
                problems.append(f"line {n}: {name} is {code} here and {c} is {consts[c]} in "
                                f"bytecode.dawn")
        for fn in writers:
            if not re.search(r"^(pub )?fn %s\b" % re.escape(fn), bytecode_text, re.M):
                problems.append(f"line {n}: {name} names writer {fn}, which bytecode.dawn does "
                                f"not define")
        for g in goldens:
            if f"scripts/tile-golden/{g}.mlir" not in files:
                problems.append(f"line {n}: {name} names golden {g}, which has no .mlir")

        if layer >= 2 and not launched:
            problems.append(
                f"line {n}: {name} claims layer {layer} and names no device kernel. Layer 2 is a "
                f"device answer that DEPENDS on the value, and a device only ran the kernels a "
                f"tile-gpu-diff program launches")
        if layer < 2 and launched:
            problems.append(
                f"line {n}: {name} stops at layer {layer} and yet names the device kernel "
                f"{launched[0]}")
        for d in launched:
            if f'"{d}"' not in devices:
                problems.append(
                    f"line {n}: {name} names device kernel {d}, which no scripts/tile-gpu-diff "
                    f"program launches")

        if layer == 3 and not named:
            problems.append(
                f"line {n}: {name} claims layer 3 and names no mutant. Layer 3 IS the mutant")
        for m in named:
            if m not in mutants:
                problems.append(
                    f"line {n}: {name} names mutant {m}, which neither scripts/tile-golden/run.sh "
                    f"nor scripts/tile-gpu-diff/run.sh defines")

    for name in sorted(set(EXPECTED_ATTRS) - set(seen)):
        problems.append(f"{name} is a value of an attribute domain and has no row")

    entries = [ln.split("#", 1)[0].split() for ln in ledger_text.splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    if any(layer >= 2 for layer in layers if layers[layer]):
        if not entries:
            problems.append("scripts/tile-gpu-diff/ledger.txt has no entry: nothing has run on a "
                            "device, so no row here may claim layer 2")
        elif entries[-1][5:6] != ["pass"]:
            problems.append(
                "the last layer-2 run in scripts/tile-gpu-diff/ledger.txt did not pass: an "
                "attribute value is covered at layer 2 only while a device has agreed")
    return counts, layers, problems


def spelled(mlir, name):
    """Whether a .mlir spells the type. Not a word boundary: a tile's
    element format is written against the extent (`tile<128xi16>`), so the
    character before it is a word character on purpose."""
    return re.search(r"(?:^|[<x,:( ])%s(?![A-Za-z0-9_])" % re.escape(name), mlir, re.M) is not None


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
    """Every verdict above, on a ledger built to trip it, and a clean control.

    One loop over TABLES. A case is (name, table text, bytecode text, ledger
    text, the fragment the checker must answer with); a `want` of None is a
    positive control, which must come back clean.
    """
    files = gather()
    bytecode = BYTECODE.read_text()
    ledger = read(LEDGER)
    dirty = []
    for table in TABLES:
        _c, _l, problems = table.check(table.path.read_text(), bytecode, files, ledger)
        dirty += [f"{table.name}: {p}" for p in problems]
    if dirty:
        print("FAIL: --self-test needs the real ledgers to be clean first:")
        for p in dirty:
            print("  " + p)
        return 1

    bad = 0
    for table in TABLES:
        good = table.path.read_text()
        for name, text, bc, led, want in table.cases(good, bytecode, files, ledger):
            label = f"{table.name}: {name}"
            if want is not None and (text, bc, led) == (good, bytecode, ledger):
                print(f"FAIL  self-test: {label} did not change anything (the anchor moved)")
                bad += 1
                continue
            _c, _l, found = table.check(text, bc, files, led)
            if want is None:
                if found:
                    print(f"FAIL  self-test: {label} should be clean, got {found}")
                    bad += 1
                else:
                    print(f"PASS  self-test: {label}")
            elif any(want in p for p in found):
                print(f"PASS  self-test: {label}")
            else:
                print(f"FAIL  self-test: {label} was accepted (wanted {want!r}, got {found})")
                bad += 1
    return 1 if bad else 0


def feature_cases(good, bytecode, files, ledger):
    """The opcode ledger's verdicts, each on a table built to trip it."""
    # An opcode no golden holds, for the layer-2 control below. It has to be
    # an UNIMPLEMENTED one, so it moves knife by knife: knife T5 took it off
    # `break`, knife T6 takes it off `assume`, and the next one to implement
    # `global` moves it again.
    absent = "global"
    plain = [

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
         good.replace("alloca                   | 0x71 | 13.3 | unimplemented | T10 | 0 | -",
                      "alloca                   | 0x71 | 13.3 | implemented   | 7b  | 2 | "
                      "golden:mathops"),
         "has no OP_ALLOCA"),
        ("a version the deltas contradict",
         good.replace("atan2                    | 0x6E | 13.2", "atan2                    | 0x6E | 13.1"),
         "atan2 entered at 13.2, not 13.1"),
        ("a layer-2 claim for an op no golden contains",
         good.replace(f"{absent:24s} | 0x31 | 13.1 | unimplemented | T7  | 0 | -",
                      f"{absent:24s} | 0x31 | 13.1 | implemented   | 3   | 2 | golden:vadd"),
         "whose .mlir does not contain the op"),
        ("an implemented row whose knife has not landed",
         good.replace("tanh                     | 0x6A | 13.1 | implemented   | 7b ",
                      "tanh                     | 0x6A | 13.1 | implemented   | T9 "),
         "cannot be a planned one"),
        ("an unimplemented row whose knife is not a planned one",
         good.replace(f"{absent:24s} | 0x31 | 13.1 | unimplemented | T7 ",
                      f"{absent:24s} | 0x31 | 13.1 | unimplemented | 3  "),
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
                      "sin                      | 0x62 | 13.1 | implemented   | T7 "),
         "knife 'T7' cannot be a planned one"),
        ("an unimplemented row under a knife that has landed",
         good.replace("global                   | 0x31 | 13.1 | unimplemented | T7 ",
                      "global                   | 0x31 | 13.1 | unimplemented | T6 "),
         "so its knife is a planned one"),
        ("an empty ledger", "# nothing\n", "of the frozen table has no row"),
    ]
    cases = [(name, text, bytecode, ledger, want) for name, text, want in plain]
    # The other input: an OP_ the writer grew and nobody wrote down.
    grown = bytecode.replace("const OP_TANH: Int = 0x6A",
                             "const OP_TANH: Int = 0x6A\nconst OP_GLOBAL: Int = 0x31")
    cases.append(("an OP_ constant the ledger does not call implemented", good, grown, ledger,
                  "is marked unimplemented but bytecode.dawn emits OP_GLOBAL"))
    invented = bytecode.replace("const OP_TANH: Int = 0x6A",
                                "const OP_TANH: Int = 0x6A\nconst OP_BOGUS: Int = 0x76")
    cases.append(("an OP_ constant the ledger has no row for", good, invented, ledger,
                  "and the ledger has no row for it"))
    cases.append(("an empty layer-2 ledger under layer-2 claims", good, bytecode,
                  "# only a comment\n", "has no entry"))
    cases.append(("the real ledger is clean (the positive control)", good, bytecode, ledger, None))
    return cases


def type_cases(good, bytecode, files, ledger):
    """The type ledger's verdicts, each on a table built to trip it."""
    plain = [

        ("a row with too few fields",
         good + "\nnope | 23 | 13.1 | unimplemented | T9 | 0\n", "fields, not 8"),
        ("the same type twice",
         good + "\ni16 | 2 | 13.1 | unimplemented | T9 | 0 | - | -\n", "is already listed"),
        ("a ledger with one row missing",
         "\n".join(ln for ln in good.splitlines() if not ln.startswith("tf32 ")) + "\n",
         "type tag 8 of the frozen table has no row"),
        ("a tag that disagrees with bytecode.dawn",
         good.replace("i16                |  2 |", "i16                |  6 |"),
         "i16 is tag 6 here and 2 in bytecode.dawn"),
        ("a tag the writer writes and the ledger calls unimplemented",
         good.replace("tf32               |  8 | 13.1 | implemented   | T3  | 3 |",
                      "tf32               |  8 | 13.1 | unimplemented | T9  | 0 |"),
         "bytecode.dawn writes its tag"),
        ("a row claiming a tag the writer does not write",
         good.replace("i4                 | 22 | 13.3 | unimplemented | T9  | 0 | -",
                      "i4                 | 22 | 13.3 | implemented   | T3  | 2 | golden:vadd"),
         "writes no tag for it"),
        ("a version the deltas contradict",
         good.replace("f8E8M0FNU          | 18 | 13.2", "f8E8M0FNU          | 18 | 13.1"),
         "f8E8M0FNU entered at 13.2, not 13.1"),
        ("a layer-2 claim with no device kernel",
         good.replace("| 2 | golden:int_ops,device:int_ops", "| 2 | golden:int_ops          "),
         "claims layer 2 and names no device kernel"),
        ("a golden whose .mlir does not spell the type",
         good.replace("golden:dtype_tf32,device:dtype_tf32", "golden:vadd,device:dtype_tf32     "),
         "whose .mlir does not spell the type"),
        ("a layer-3 claim with no mutant",
         good.replace(",mutant:f64-tag-as-i64", "                      "),
         "claims layer 3 and names no mutant"),
        ("a mutant nobody defines",
         good.replace("mutant:tf32-tag-as-f32", "mutant:tf32-tag-as-f16"),
         "names mutant tf32-tag-as-f16"),
        ("a row below the bar with no reason for it",
         good.replace("golden:vadd_f32                                                      | "
                      "no host channel",
                      "golden:vadd_f32                                                      | -"),
         "stops at layer 1 and names no reason"),
        ("a row at the bar that still claims an exemption",
         good.replace("golden:int_ops,device:int_ops                                        | -",
                      "golden:int_ops,device:int_ops                                        | "
                      "architecture"),
         "reaches layer 2 and still claims the exemption"),
        ("an implemented row under a knife nobody has cut",
         good.replace("i16                |  2 | 13.1 | implemented   | T3 ",
                      "i16                |  2 | 13.1 | implemented   | T9 "),
         "knife 'T9' cannot be a planned one"),
        ("an unimplemented row under a knife that has landed",
         good.replace("i4                 | 22 | 13.3 | unimplemented | T9 ",
                      "i4                 | 22 | 13.3 | unimplemented | T3 "),
         "so its knife is a planned one"),
        ("a deferred row with no reason",
         good.replace("TensorViewType     | 14 | 13.1 | deferred      | -   | 0 | -"
                      "                                                                    | "
                      "ruling 2",
                      "TensorViewType     | 14 | 13.1 | deferred      | -   | 0 | -"
                      "                                                                    | -"),
         "is deferred with no named reason"),
        ("an empty ledger", "# nothing\n", "of the frozen table has no row"),
    ]
    cases = [(name, text, bytecode, ledger, want) for name, text, want in plain]
    grown = bytecode.replace('  "f8E8M0FNU" -> 18', '  "f8E8M0FNU" -> 18\n  "i4" -> 22')
    cases.append(("a type tag the ledger does not call implemented", good, grown, ledger,
                  "is marked unimplemented but bytecode.dawn writes its tag"))
    # and the other direction of the same input: a tag with no row at all
    invented = bytecode.replace('  "f8E8M0FNU" -> 18', '  "f8E8M0FNU" -> 18\n  "bogus" -> 5')
    cases.append(("a type tag the ledger has no row for", good, invented, ledger,
                  "and the ledger has no row for it"))
    cases.append(("an empty layer-2 ledger under layer-2 claims", good, bytecode,
                  "# only a comment\n", "has no entry"))
    cases.append(("the real ledger is clean (the positive control)", good, bytecode, ledger, None))
    return cases



def attr_cases(good, bytecode, files, ledger):
    """The attribute ledger's verdicts, each on a table built to trip it."""
    plain = [
        ("a row with too few fields",
         good + "\nrounding.nope | 9 | 13.1 | unimplemented | T7 | 0\n", "fields, not 8"),
        ("the same value twice",
         good + "\nrounding.approx | 4 | 13.1 | unimplemented | T7 | 0 | - | -\n",
         "is already listed"),
        ("a value AttrDefs.td does not define",
         good + "\nrounding.nope | 9 | 13.1 | unimplemented | T7 | 0 | - | -\n",
         "is not a value of any attribute domain"),
        ("a code that disagrees with AttrDefs.td",
         good.replace("rounding.approx              | 4 |", "rounding.approx              | 5 |"),
         "rounding.approx is 4 in AttrDefs.td and 5 here"),
        ("a ledger with one row missing",
         "\n".join(ln for ln in good.splitlines() if not ln.startswith("scope.sys")) + "\n",
         "scope.sys is a value of an attribute domain and has no row"),
        ("a version the domain contradicts",
         good.replace("unit.unsignedCmp             | 1 | 13.2",
                      "unit.unsignedCmp             | 1 | 13.1"),
         "unit.unsignedCmp entered at 13.2, not 13.1"),
        ("a const the writer does not define",
         good.replace("const:SCOPE_SYS", "const:SCOPE_UNIVERSE"),
         "names const SCOPE_UNIVERSE"),
        ("a const whose value is not the row's",
         good.replace("scope.sys                    | 2 |", "scope.sys                    | 1 |"),
         "SCOPE_SYS is 2 in bytecode.dawn"),
        ("an implemented row with neither a const nor a writer",
         good.replace("const:ROUND_APPROX,golden:attr_approx", "golden:attr_approx"),
         "names neither a const: nor a writer:"),
        ("a golden with no .mlir",
         good.replace("golden:attr_approx", "golden:attr_nonesuch"),
         "names golden attr_nonesuch, which has no .mlir"),
        ("a layer-2 claim with no device kernel",
         good.replace("const:ROUND_FULL,golden:mathops,device:mathops",
                      "const:ROUND_FULL,golden:mathops             "),
         "claims layer 2 and names no device kernel"),
        ("a device kernel no program launches",
         good.replace("device:mathops", "device:vadd_f32"),
         "names device kernel vadd_f32, which no scripts/tile-gpu-diff program launches"),
        ("a row below the bar that names a device kernel",
         good.replace("const:SCOPE_SYS,golden:attr_memsem,mutant:atomic-memory-attrs-swapped",
                      "const:SCOPE_SYS,device:attr_memsem,mutant:atomic-memory-attrs-swapped"),
         "stops at layer 1 and yet names the device kernel"),
        ("a layer-3 claim with no mutant named",
         good.replace(",mutant:cmpf-always-ordered", "                           "),
         "claims layer 3 and names no mutant"),
        ("a mutant nobody defines",
         good.replace("mutant:ftz-bit-dropped", "mutant:ftz-bit-kept   "),
         "names mutant ftz-bit-kept"),
        ("a row below the bar with no reason for it",
         good.replace("| assumption-not-arithmetic", "| -"),
         "stops at layer 1 and names no reason"),
        ("a row at the bar that still claims an exemption",
         re.sub(r"^(scope\.device .*)\| -$", r"\1| no-race-in-corpus", good, count=1, flags=re.M),
         "reaches layer 2 and still claims the exemption"),
        ("an implemented row under a knife nobody has cut",
         good.replace("rounding.approx              | 4 | 13.1 | implemented   | T4 ",
                      "rounding.approx              | 4 | 13.1 | implemented   | T9 "),
         "knife 'T9' cannot be a planned one"),
        ("an unimplemented row under a knife that has landed",
         good.replace("unit.fast_acc                | 1 | 13.3 | unimplemented | T8 ",
                      "unit.fast_acc                | 1 | 13.3 | unimplemented | T4 "),
         "so its knife is a planned one"),
        ("a deferred row with no reason",
         good.replace("| no-client-kernel", "| -"),
         "is deferred with no named reason"),
        ("an empty ledger", "# nothing\n",
         "is a value of an attribute domain and has no row"),
    ]
    cases = [(name, text, bytecode, ledger, want) for name, text, want in plain]
    cases.append(("an empty layer-2 ledger under layer-2 claims", good, bytecode,
                  "# only a comment\n", "has no entry"))
    cases.append(("the real ledger is clean (the positive control)", good, bytecode, ledger, None))
    return cases


TABLES = (
    Ledger("features", TABLE, "opcode", lambda *a: check(*a), lambda *a: feature_cases(*a)),
    Ledger("types", TYPES, "type tag", lambda *a: check_types(*a), lambda *a: type_cases(*a)),
    Ledger("attrs", ATTRS, "attribute value", lambda *a: check_attrs(*a),
           lambda *a: attr_cases(*a)),
)


def main(argv):
    if argv[1:] == ["--self-test"]:
        return self_test()
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 2
    files = gather()
    bytecode = BYTECODE.read_text()
    ledger = read(LEDGER)
    results = [(table, table.check(table.path.read_text(), bytecode, files, ledger))
               for table in TABLES]
    bad = False
    for table, (_counts, _layers, problems) in results:
        for p in problems:
            print(f"FAIL: {table.name}: " + p)
            bad = True
    if bad:
        return 1
    for table, (counts, layers, _p) in results:
        hist = " ".join(f"layer{k}={layers[k]}" for k in sorted(layers))
        kinds = " ".join(f"{s}={counts[s]}" for s in STATUSES if counts[s])
        print(f"PASS  tileir {table.name}: {sum(counts.values())} {table.unit}(s): "
              f"{kinds}; {hist}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

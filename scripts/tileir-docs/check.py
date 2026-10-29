#!/usr/bin/env python3
"""The two reference tables of packages/tileir are held to the source they describe.

    scripts/tileir-docs/check.py              # check both tables
    scripts/tileir-docs/check.py --self-test  # negative controls

packages/tileir/OPERATIONS.md says, for every public function of `tileir/dev`
and `tileir/prog`, which `cuda_tile` operation it records. packages/tileir/
ERRORS.md says which of four layers an error comes from, what it looks like
and how to fix it, and lists every `gpu.*` error kind. A table like that is
read once and then trusted, and a trusted table that nothing reads rots: the
same shape as the builtin mirror (selfhost/builtins.dawn, whose gate holds it
to the checker's table in both directions) and the three coverage ledgers
beside this directory. So both are checked here, and the rule for each is
"a row too few is red, and a row too many is red".

## OPERATIONS.md

  * Surface. The functions are the `pub fn` of dev.dawn and prog.dawn, plus
    the bitwise, shift and staged-if prelude trait methods implemented on Tile. Each
    has exactly one row, and each row names a function that is there. A new
    public function does not compile past this gate until it has said what it
    records (a function that records nothing says `-`).
  * Vocabulary. Every operation a row names is one of the opcodes of
    scripts/tileir-features/features.txt (the frozen dialect table), so a
    misspelled mnemonic is red.
  * Reach. Every opcode that ledger calls `implemented` or `structural` is
    named by some row, so an operation the backend writes but no function is
    documented to record is red. The other direction, which operation a given
    function really records, is the goldens' to say (scripts/tile-golden), not
    a text file's; the rows were written against `render.line_map`'s
    attribution over those goldens.

## ERRORS.md

  * Kinds. The table holds the union of the `gpu.*` kinds constructed by
    std/gpu before its tests, the marked C GPU runtime and the JVM GPU class
    generator. Comments and unrelated strings do not count. Each kind keeps
    all its source files, even when two implementations build the same kind;
    the table owes one row per kind, not one per source. There is no runtime
    kind allowlist to forget when adding the next refusal. The dynamic
    `cuda.*` family owes exactly one representative row.
  * Fragments. The type-check, recording and emitting layers have no codes,
    only messages, so their rows are keyed by a fragment of the message that
    is a literal in the source (the checker's for the first, packages/tileir's
    for the other two). A fragment the source no longer contains is red,
    which is how a reworded message finds the row that quotes it.
  * Layers. The four layers are named, each is present, and every row says
    which one it belongs to.

## README.md

  * The first example. README.md shows a whole program, from `trace3` to an
    assertion on the fake device's answer, and says it is
    examples/projects/gpu_fake/src/first.dawn. CI compiles that file and runs
    its tests, but not the README, so the README's functions are compared with
    the file's, text for text (the `##` comments above them aside). Edit one and
    not the other and this is red, which is what keeps the example in the README
    a program that runs.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = ROOT / "packages" / "tileir"
OPERATIONS = PKG / "OPERATIONS.md"
ERRORS = PKG / "ERRORS.md"
README = PKG / "README.md"
FIRST = ROOT / "examples" / "projects" / "gpu_fake" / "src" / "first.dawn"
DEV = PKG / "src" / "dev.dawn"
PROG = PKG / "src" / "prog.dawn"
SRC = PKG / "src"
GPU = ROOT / "std" / "gpu.dawn"
FEATURES = ROOT / "scripts" / "tileir-features" / "features.txt"
RUNTIME_C = ROOT / "runtime" / "c" / "dawn_rt.c"
RUNTIME_JVM = ROOT / "selfhost" / "src" / "jvm" / "rtclasses.dawn"
CHECKER = ROOT / "selfhost" / "src" / "check" / "checker.dawn"

LAYERS = ("type check", "record", "emit", "device")
# The items of the example file the README shows verbatim: "fn <name>" or
# 'test "<name>"'. The README's first example is that program, and it stays so
# because this gate compares the text.
SHOWN = ("fn vadd", "fn record", "fn run", "fn xs", "fn ys", "fn expected",
         "fn answer_error", "fn finish", "fn on_real", "fn assembly_error", "fn assemble_run",
         'test "the kernel launched through its entry on the fake device adds the vectors"')


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def table_rows(text):
    """Every `| ... |` row that starts with a backticked cell, as its cells."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out.append((n, cells))
    return out


def ticked(cell):
    return re.findall(r"`([^`]+)`", cell)


# ---- OPERATIONS.md ----

def pub_fns(text):
    return re.findall(r"^pub fn ([a-z][a-z0-9_]*)", text, re.M)


def feature_names(text):
    """The opcode names of features.txt and the ones its rows call implemented
    or structural."""
    names, owed = set(), set()
    for line in text.splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        f = [c.strip() for c in line.split("|")]
        if len(f) < 4:
            continue
        names.add(f[0])
        if f[3] in ("implemented", "structural"):
            owed.add(f[0])
    return names, owed


def check_operations(table_text, dev_text, prog_text, features_text):
    problems = []
    dev, prog = pub_fns(dev_text), pub_fns(prog_text)
    # Operator methods are public through their prelude traits, rather than
    # through top-level function exports. Each still owes one operation row.
    blocks = re.findall(
        r"^impl[^\n]*\b(?:BitAnd|BitOr|BitXor|BitNot|Shl|Shr|Ushr|StagedCond|StagedResult)"
        r"\[Tile\[\w+\]\]\s*\{(.*?)^\}", dev_text, re.M | re.S)
    operators = [method for block in blocks for method in re.findall(r"^  fn (\w+)\(", block, re.M)]
    surface = set(dev) | set(prog) | set(operators)
    both = sorted(set(dev) & set(prog))
    if both:
        problems.append(f"{', '.join(both)} is public in both dev.dawn and prog.dawn, so a row cannot say which")
    names, owed = feature_names(features_text)
    if not names:
        problems.append("scripts/tileir-features/features.txt has no opcode rows")
    rows = table_rows(table_text)
    if not rows:
        problems.append("OPERATIONS.md has no table rows")
    seen = {}
    named = set()
    for n, cells in rows:
        if len(cells) != 3:
            problems.append(f"OPERATIONS.md:{n}: a row has {len(cells)} cells, expected Function, Operation, Also")
            continue
        fn_cell, op_cell, also_cell = cells
        fns = ticked(fn_cell)
        if len(fns) != 1 or fn_cell != f"`{fns[0]}`":
            problems.append(f"OPERATIONS.md:{n}: the first cell is one backticked function name, got {fn_cell!r}")
            continue
        fn = fns[0]
        if fn in seen:
            problems.append(f"OPERATIONS.md:{n}: `{fn}` already has a row on line {seen[fn]}")
        seen[fn] = n
        if fn not in surface:
            problems.append(f"OPERATIONS.md:{n}: `{fn}` is not a public function of dev.dawn or prog.dawn")
        for label, cell in (("Operation", op_cell), ("Also", also_cell)):
            if cell == "-":
                continue
            if not cell:
                problems.append(f"OPERATIONS.md:{n}: `{fn}` has an empty {label} cell; write `-` for none")
                continue
            ops = ticked(cell)
            rebuilt = ", ".join(f"`{o}`" for o in ops)
            if rebuilt != cell:
                problems.append(f"OPERATIONS.md:{n}: `{fn}`'s {label} cell is not a list of backticked operations or `-`: {cell!r}")
            for o in ops:
                named.add(o)
                if o not in names:
                    problems.append(f"OPERATIONS.md:{n}: `{fn}` names `{o}`, which is not an opcode of features.txt")
    for fn in sorted(surface - set(seen)):
        problems.append(f"`{fn}` is a public function and OPERATIONS.md has no row for it")
    for o in sorted(owed - named):
        problems.append(f"the backend writes `{o}` and no row of OPERATIONS.md names it")
    return problems


# ---- ERRORS.md ----

def code_tokens(text, dawn=False):
    """Keep string literals atomic, so examples inside them are never code.

    These are the current literal constructor protocols, not a C/Dawn parser.
    Source boundaries and nonempty inventories fail closed if those protocols
    disappear; the controls exercise every form read below.
    """
    pattern = r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|/\*[\s\S]*?\*/|//[^\n]*'''
    if dawn:
        pattern += r"|\#[^\n]*"
    pattern += r"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]"
    return [m.group() for m in re.finditer(pattern, text)
            if not m.group().startswith(("//", "/*", "#"))]


def literal_kinds(tokens, prefix):
    """Literal first arguments of a particular constructor, not all strings."""
    kinds = set()
    for i in range(len(tokens) - len(prefix)):
        if tokens[i:i + len(prefix)] != list(prefix):
            continue
        literal = tokens[i + len(prefix)]
        if re.fullmatch(r'"gpu\.[a-z][a-z0-9_]*"', literal):
            kinds.add(literal[1:-1])
    return kinds


def brace_bodies(tokens):
    """Outermost C blocks, so an allocation cannot lend its local to another function."""
    depth = 0
    for i, token in enumerate(tokens):
        if token == "{":
            if depth == 0:
                start = i
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0:
                yield tokens[start + 1:i]


def function_bodies(tokens):
    """GPU generator bodies, with nested braces balanced outside literals."""
    for i, token in enumerate(tokens[:-1]):
        if token != "fn" or not tokens[i + 1].startswith("gen_gpu_"):
            continue
        try:
            start = tokens.index("{", i + 2)
        except ValueError:
            raise ValueError(f"{tokens[i + 1]}: GPU generator has no block body") from None
        depth = 1
        for end in range(start + 1, len(tokens)):
            depth += (tokens[end] == "{") - (tokens[end] == "}")
            if depth == 0:
                yield tokens[i + 1], tokens[start + 1:end]
                break
        else:
            raise ValueError("unterminated Dawn function body")


def gpu_kinds(text):
    tokens = code_tokens(text, dawn=True)
    if "test" in tokens:
        tokens = tokens[:tokens.index("test")]
    return (literal_kinds(tokens, ("refuse", "("))
            | literal_kinds(tokens, ("Err", "(", "(")))


def c_gpu_kinds(text):
    begin, end = "=== DAWN_RT_GPU_BEGIN ===", "=== DAWN_RT_GPU_END ==="
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) >= text.index(end):
        raise ValueError("C GPU section needs exactly one ordered pair of boundary markers")
    tokens = code_tokens(text[text.index(begin) + len(begin):text.index(end)])
    kinds = literal_kinds(tokens, ("dawn_gpu_refuse", "("))
    # The WASI branch constructs ForeignError directly. Follow the tagged
    # allocation to its kind field, rather than treating DAWN_LIT as an error.
    for body in brace_bodies(tokens):
        for i in range(1, len(body) - 4):
            # CUDA's names are dynamic, but this formatting result is passed
            # to the same refusal constructor. It is one family, not a list.
            if body[i:i + 2] == ["snprintf", "("]:
                owner = body[i + 2]
                prefix = ["snprintf", "(", owner, ",", "sizeof", owner, ",", '"cuda.%s"', ","]
                refusal = ["dawn_gpu_refuse", "(", owner, ","]
                if body[i:i + len(prefix)] == prefix and any(
                        body[j:j + len(refusal)] == refusal for j in range(i, len(body))):
                    kinds.add("cuda.*")
            if body[i:i + 4] != ["=", "dawn_adt_new", "(", "DAWN_TAG_FOREIGN_ERROR"]:
                continue
            owner = body[i - 1]
            kinds |= literal_kinds(body[i:], (owner, "-", ">", "fields", "[", "0", "]", ".", "p",
                                              "=", "DAWN_LIT", "("))
    return kinds


def jvm_gpu_kinds(text):
    kinds = set()
    for name, body in function_bodies(code_tokens(text, dawn=True)):
        # The first string pushed for a newly allocated ForeignError is its
        # kind. A later LDC (the message) or an unrelated LDC is not a kind.
        for i, visitor in enumerate(body):
            prefix = [visitor, ".", "visitTypeInsn", "(", "OP_NEW", ",", "FERR_CLASS", ")",
                      visitor, ".", "visitInsn", "(", "OP_DUP", ")",
                      visitor, ".", "visitLdcInsn", "("]
            if body[i:i + len(prefix)] != prefix:
                continue
            init = [visitor, ".", "visitMethodInsn", "(", "OP_INVOKESPECIAL", ",", "FERR_CLASS",
                    ",", '"<init>"', ","]
            if not any(body[j:j + len(init)] == init for j in range(i + len(prefix), len(body))):
                raise ValueError(f"{name}: ForeignError allocation has no constructor invocation")
            kinds |= literal_kinds(body[i:], prefix)
    return kinds


def error_sources(gpu_text, runtime_texts):
    """The kind union with every producer retained, including shared kinds."""
    origins = {}
    for path, extractor, text in ((GPU, gpu_kinds, gpu_text),
                                  (RUNTIME_C, c_gpu_kinds, runtime_texts.get(RUNTIME_C, "")),
                                  (RUNTIME_JVM, jvm_gpu_kinds, runtime_texts.get(RUNTIME_JVM, ""))):
        kinds = extractor(text)
        if not kinds:
            raise ValueError(f"{path.relative_to(ROOT)} builds no gpu.* error kind: the constructor reader is stale")
        for kind in kinds:
            origins.setdefault(kind, set()).add(path)
    return origins


def check_errors(table_text, gpu_text, src_texts, runtime_texts, checker_text):
    """`src_texts` is the concatenated source of packages/tileir/src,
    `checker_text` the type checker's, and `runtime_texts` maps each runtime
    file to its text."""
    problems = []
    try:
        origins = error_sources(gpu_text, runtime_texts)
    except ValueError as e:
        return [str(e)]
    want = set(origins)
    rows = table_rows(table_text)
    kinds_seen = {}
    layers_seen = set()
    for n, cells in rows:
        first = ticked(cells[0]) if cells else []
        if len(cells) < 2 or len(first) != 1:
            problems.append(f"ERRORS.md:{n}: a row starts with one backticked key")
            continue
        key = first[0]
        layer = cells[1].strip()
        if layer not in LAYERS:
            problems.append(f"ERRORS.md:{n}: `{key}` names the layer {layer!r}, expected one of {', '.join(LAYERS)}")
            continue
        layers_seen.add(layer)
        if re.fullmatch(r"gpu\.[a-z][a-z0-9_]*", key) or key.startswith("cuda."):
            if layer != "device":
                problems.append(f"ERRORS.md:{n}: `{key}` is an error kind of the device layer, not {layer!r}")
            # One representative documents the dynamic CUresult family.
            if key.startswith("cuda."):
                key = "cuda.*"
            if key in kinds_seen:
                problems.append(f"ERRORS.md:{n}: `{key}` already has a row on line {kinds_seen[key]}")
            kinds_seen[key] = n
            continue
        # a message fragment: a literal of packages/tileir/src
        if layer in ("record", "emit"):
            if key not in src_texts:
                problems.append(f"ERRORS.md:{n}: the fragment `{key}` is not in packages/tileir/src, so the message was reworded or removed")
        elif layer == "type check":
            if key not in checker_text:
                problems.append(f"ERRORS.md:{n}: the fragment `{key}` is not in selfhost/src/check/checker.dawn, so the message was reworded or removed")
    for kind in sorted(want - set(kinds_seen)):
        files = ", ".join(str(p.relative_to(ROOT)) for p in sorted(origins[kind]))
        problems.append(f"{kind} is an error kind and ERRORS.md has no row for it (built by {files})")
    for kind in sorted(set(kinds_seen) - want):
        problems.append(f"ERRORS.md:{kinds_seen[kind]}: `{kind}` is not an error kind std/gpu.dawn or the runtime builds")
    for layer in LAYERS:
        if layer not in layers_seen:
            problems.append(f"ERRORS.md has no row for the {layer!r} layer")
    return problems


def item_text(text, header):
    """The lines of the top-level item whose first line starts with `header`: the
    line itself, then every line that is indented or a closing brace."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(header + "(") or line.startswith(header + " ") or line.startswith(header + "["):
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith(" ") or nxt == "}":
                    out.append(nxt)
                else:
                    break
            return "\n".join(out)
    return None


def check_readme(readme_text, first_text):
    problems = []
    if "examples/projects/gpu_fake/src/first.dawn" not in readme_text:
        problems.append("README.md does not say the example it shows is examples/projects/gpu_fake/src/first.dawn")
    for header in SHOWN:
        body = item_text(first_text, header)
        if body is None:
            problems.append(f"first.dawn has no `{header}`; this gate expects it, update SHOWN with the README")
        elif body not in readme_text:
            problems.append(f"README.md does not show `{header}` the way first.dawn writes it")
    # Text equality alone would accept changing both copies to the fake
    # backend. Hold the execution seam as well as the documented snippets.
    real = item_text(first_text, "fn on_real") or ""
    tokens = code_tokens(real, dawn=True)
    if (tokens.count("with_gpu_real") != 1 or "with_gpu_fake" in tokens
            or "reference_kernels" in tokens):
        problems.append("first.dawn: on_real must call with_gpu_real exactly once and never the fake backend")
    assembled = item_text(first_text, "fn assemble_run") or ""
    cli = item_text(first_text.replace("pub fn cli", "fn cli"), "fn cli") or ""
    for call in ("assemble(prog, gpu_name, tileiras)", 'finish("real", on_real(cubin, e))'):
        if call not in assembled:
            problems.append(f"first.dawn: assemble_run must call `{call}`")
    for call in ('argv[0] == "assemble"', "assemble_run(prog, e, argv[1], argv[2])",
                 'finish("real", on_real(read_cubin(argv[1]), e))'):
        if call not in cli:
            problems.append(f"first.dawn: CLI must call `{call}`")
    for command in ('"$DAWNC" build examples/projects/gpu_fake -o gpu_fake',
                    './gpu_fake assemble sm_86 "$TILEIRAS"', './gpu_fake fake',
                    './gpu_fake emit vadd.tilebc', './gpu_fake real vadd.cubin'):
        if command not in readme_text:
            problems.append(f"README.md has no public command `{command}`")
    return problems


def sources():
    src = "\n".join(read(p) for p in sorted(SRC.glob("*.dawn")))
    runtime = {RUNTIME_C: read(RUNTIME_C), RUNTIME_JVM: read(RUNTIME_JVM)}
    return src, runtime


# ---- self-test ----

def error_controls(errs, gpu, runtime):
    """In-memory source mutations; no test ever edits a real runtime file."""
    def replace(text, old, new):
        # Positive controls must prove their noise was inserted as well. A
        # missing source fixture is a broken self-test, never a clean pass.
        assert old in text, f"self-test fixture is stale: {old!r}"
        return text.replace(old, new, 1)

    c_refusal = 'dawn_gpu_refuse("gpu.control_c2", "control")'
    c_added = replace(runtime[RUNTIME_C],
        'return dawn_gpu_refuse("gpu.no_driver", message);',
        f'if (name == NULL) return {c_refusal};\n'
        '  return dawn_gpu_refuse("gpu.no_driver", message);')
    jvm_added = replace(runtime[RUNTIME_JVM],
        'm.visitLdcInsn("gpu.unsupported_backend")',
        'm.visitLdcInsn("gpu.control_jvm2")')
    yield ("a new C runtime kind needs a row", errs, gpu,
           {**runtime, RUNTIME_C: c_added}, "gpu.control_c2 is an error kind")
    yield ("a documented new C runtime kind is accepted",
           errs + "| `gpu.control_c2` | device | control | control |\n", gpu,
           {**runtime, RUNTIME_C: c_added}, None)
    yield ("a new JVM runtime kind needs a row", errs, gpu,
           {**runtime, RUNTIME_JVM: jvm_added}, "gpu.control_jvm2 is an error kind")
    yield ("a documented new JVM runtime kind is accepted",
           errs + "| `gpu.control_jvm2` | device | control | control |\n", gpu,
           {**runtime, RUNTIME_JVM: jvm_added}, None)
    yield ("a new std refusal needs a row", errs,
           'fn control() -> Result[Unit, ForeignError] = refuse("gpu.control_std2", "control")\n' + gpu,
           runtime, "gpu.control_std2 is an error kind")
    yield ("a new std launch-plan error needs a row", errs,
           'fn control() -> Result[Unit, (String, String)] = Err(("gpu.control_plan2", "control"))\n' + gpu,
           runtime, "gpu.control_plan2 is an error kind")
    direct = replace(runtime[RUNTIME_C],
        'a->fields[0].p = DAWN_LIT("gpu.unsupported_backend");',
        'a->fields[0].p = DAWN_LIT("gpu.control_wasi2");')
    yield ("a new direct C ForeignError kind needs a row", errs, gpu,
           {**runtime, RUNTIME_C: direct}, "gpu.control_wasi2 is an error kind")
    for kind in ("gpu.driver_too_old", "gpu.bad_kernel_name", "gpu.bad_symbol_name"):
        table = "\n".join(line for line in errs.splitlines()
                          if not line.startswith(f"| `{kind}` |")) + "\n"
        yield (f"removing {kind} is rejected", table, gpu, runtime,
               f"{kind} is an error kind and ERRORS.md has no row")
    yield ("a runtime device error cannot be filed under emit",
           errs.replace("| `gpu.bad_symbol_name` | device |", "| `gpu.bad_symbol_name` | emit |", 1),
           gpu, runtime, "`gpu.bad_symbol_name` is an error kind of the device layer")
    yield ("the dynamic CUDA family needs its representative row",
           "\n".join(line for line in errs.splitlines() if not line.startswith("| `cuda.")) + "\n",
           gpu, runtime, "cuda.* is an error kind and ERRORS.md has no row")
    yield ("two CUDA representatives duplicate one dynamic family",
           errs + "| `cuda.CUDA_ERROR_UNKNOWN` | device | control | control |\n",
           gpu, runtime, "`cuda.*` already has a row")
    # Use the same spelling as each real mutation above, in comments and
    # strings (including complete constructor examples), within the read scope.
    c_noise = ('/* return ' + c_refusal + '; */\n// return ' + c_refusal + ';\n'
               'const char *kind_example = "gpu.control_c2";\n'
               r'const char *call_example = "dawn_gpu_refuse(\"gpu.control_c2\", \"control\")";' + '\n'
               'const char *literal_example = DAWN_LIT("gpu.control_wasi2");\n')
    c_noisy = replace(runtime[RUNTIME_C], "#ifndef __wasi__", c_noise + "#ifndef __wasi__")
    yield ("C comments and ordinary strings do not invent kinds", errs, gpu,
           {**runtime, RUNTIME_C: c_noisy}, None)
    c_unrelated = replace(runtime[RUNTIME_C],
        "#ifndef __wasi__", 'static void control(void) {\n'
        '  dawn_adt *a = dawn_adt_new(DAWN_TAG_SOME, 1, DAWN_MASK_ONE_BOXED);\n'
        '  a->fields[0].p = DAWN_LIT("gpu.control_wasi2");\n}\n#ifndef __wasi__')
    yield ("a C field on another ADT is not an error kind", errs, gpu,
           {**runtime, RUNTIME_C: c_unrelated}, None)
    jvm_noise = ('  ## m.visitLdcInsn("gpu.control_jvm2")\n'
                 '  let example = "gpu.control_jvm2"\n'
                 r'  let call_example = "m.visitLdcInsn(\"gpu.control_jvm2\")"' + '\n'
                 '  m.visitLdcInsn("gpu.control_jvm2")\n')
    jvm_noisy = replace(runtime[RUNTIME_JVM],
        '  let m = open_static(cw, name, desc)\n',
        '  let m = open_static(cw, name, desc)\n' + jvm_noise)
    yield ("JVM comments and unrelated LDC strings do not invent kinds", errs, gpu,
           {**runtime, RUNTIME_JVM: jvm_noisy}, None)
    std_noise = ('## refuse("gpu.control_std2", "control")\n'
                 '## Err(("gpu.control_plan2", "control"))\n'
                 'const example = "gpu.control_std2"\n'
                 r'const call_example = "refuse(\"gpu.control_std2\", \"control\")"' + '\n')
    yield ("std comments and ordinary strings do not invent kinds", errs,
           std_noise + gpu, runtime, None)
    yield ("std test fixtures do not invent kinds", errs,
           gpu + '\ntest "control" { refuse("gpu.control_std2", "control") }\n', runtime, None)
    yield ("C code outside the GPU section does not invent kinds", errs, gpu,
           {**runtime, RUNTIME_C: runtime[RUNTIME_C] + '\n' + c_refusal + ';\n'}, None)
    other_jvm = item_text(runtime[RUNTIME_JVM], "fn gen_gpu_refusal")
    other_jvm = other_jvm.replace('"gpu.unsupported_backend"', '"gpu.control_jvm2"')
    other_jvm = other_jvm.replace("gen_gpu_", "gen_unrelated_")
    yield ("other JVM generators do not invent GPU kinds", errs, gpu,
           {**runtime, RUNTIME_JVM: runtime[RUNTIME_JVM] + '\n' + other_jvm}, None)
    yield ("a missing C GPU boundary fails closed", errs, gpu,
           {**runtime, RUNTIME_C: runtime[RUNTIME_C].replace("=== DAWN_RT_GPU_END ===", "")},
           "C GPU section needs exactly one ordered pair")
    yield ("a duplicated C GPU boundary fails closed", errs, gpu,
           {**runtime, RUNTIME_C: runtime[RUNTIME_C] + "\n// === DAWN_RT_GPU_BEGIN ===\n"},
           "C GPU section needs exactly one ordered pair")
    yield ("a stale JVM constructor reader fails closed", errs, gpu,
           {**runtime, RUNTIME_JVM: runtime[RUNTIME_JVM].replace("gen_gpu_", "gen_other_")},
           "builds no gpu.* error kind")


def self_test():
    ops, errs = read(OPERATIONS), read(ERRORS)
    readme, first = read(README), read(FIRST)
    dev, prog, feats, gpu = read(DEV), read(PROG), read(FEATURES), read(GPU)
    src, runtime = sources()
    checker = read(CHECKER)

    def drop(text, key):
        out = [l for l in text.splitlines() if not l.startswith(f"| `{key}` |")]
        assert len(out) == len(text.splitlines()) - 1, key
        return "\n".join(out) + "\n"

    first_gpu = re.search(r"^\| `(gpu\.[a-z_]+)` \|", errs, re.M).group(1)
    first_frag = next(c[0] for _n, c in table_rows(errs) if c[1] in ("record", "emit"))
    first_frag = ticked(first_frag)[0]
    first_tc = ticked(next(c[0] for _n, c in table_rows(errs) if c[1] == "type check"))[0]
    cases = [
        ("the real tables are clean (the positive control)", "ops", ops, None),
        ("a public function with no row", "ops", drop(ops, "add"), "`add` is a public function and OPERATIONS.md has no row"),
        ("an operator method with no row", "ops", drop(ops, "bit_and"), "`bit_and` is a public function and OPERATIONS.md has no row"),
        ("a shift method with no row", "ops", drop(ops, "shl"), "`shl` is a public function and OPERATIONS.md has no row"),
        ("a staged condition method with no row", "ops", drop(ops, "staged_if"), "`staged_if` is a public function and OPERATIONS.md has no row"),
        ("a second result method with no row", "ops", drop(ops, "result_set"), "`result_set` is a public function and OPERATIONS.md has no row"),
        ("a row for a function that is not there", "ops", ops + "| `no_such_fn` | `addf` | - |\n",
         "`no_such_fn` is not a public function"),
        ("a misspelled operation", "ops", ops.replace("| `add` | `addf` |", "| `add` | `addff` |", 1),
         "`addff`, which is not an opcode"),
        ("an operation that no row names", "ops", ops.replace("`print_tko`", "`assert`"),
         "no row of OPERATIONS.md names it"),
        ("a duplicated row", "ops", ops + "| `add` | `addf` | - |\n", "`add` already has a row"),
        ("an empty operation cell", "ops", ops.replace("| `add` | `addf` |", "| `add` |  |", 1), "empty Operation cell"),
        ("the real errors table is clean (the positive control)", "err", errs, None),
        ("an error kind with no row", "err", drop(errs, first_gpu), f"{first_gpu} is an error kind and ERRORS.md has no row"),
        ("a row for a kind nothing builds", "err", errs + "| `gpu.no_such_kind` | device | x | y |\n",
         "`gpu.no_such_kind` is not an error kind"),
        ("a kind filed under the wrong layer", "err",
         errs.replace(f"| `{first_gpu}` | device |", f"| `{first_gpu}` | record |", 1), "is an error kind of the device layer"),
        ("a quoted type-check fragment the checker no longer has", "err",
         errs.replace(f"`{first_tc}`", "`this message was reworded`", 1), "selfhost/src/check/checker.dawn"),
        ("a quoted fragment the source no longer has", "err",
         errs.replace(f"`{first_frag}`", "`this message was reworded`", 1), "was reworded or removed"),
        ("the real README example is clean (the positive control)", "readme", readme, None),
        ("a README function that parted from the example", "readme", readme.replace("  sync()?\n", "  sync()?\n  sync()?\n", 1),
         "does not show `fn run`"),
        ("a README with no example", "readme", readme.replace("fn xs() -> List[Float]", "fn ws() -> List[Float]", 1),
         "does not show `fn xs`"),
        ("a layer with no row", "err", "\n".join(l for l in errs.splitlines() if "| emit |" not in l) + "\n",
         "no row for the 'emit' layer"),
    ]
    bad = 0
    for name, which, text, want in cases:
        if which == "ops":
            problems = check_operations(text, dev, prog, feats)
        elif which == "readme":
            problems = check_readme(text, first)
        else:
            problems = check_errors(text, gpu, src, runtime, checker)
        if want is None:
            ok = not problems
        else:
            ok = any(want in p for p in problems)
        print(("PASS  " if ok else "FAIL  ") + name)
        if not ok:
            bad += 1
            for p in problems[:5]:
                print("      " + p)
            if want:
                print(f"      wanted a problem containing: {want}")
    real = item_text(first, "fn on_real")
    fake = real.replace('with_gpu_real(map.from([("vadd", cubin)])',
                        'with_gpu_fake(reference_kernels()')
    assert real != fake, "stale real-backend mutation anchor"
    controls = [
        ("the real assembly path is clean", readme, first, None),
        ("an assembly snippet changed in README", readme.replace("assemble(prog, gpu_name, tileiras)",
            "assemble(prog, gpu_name, other_tool)"), first, "does not show `fn assemble_run`"),
        ("an assembly call changed in the example", readme, first.replace(
            "assemble(prog, gpu_name, tileiras)", "assemble(prog, gpu_name, other_tool)", 1),
            "assemble_run must call"),
        ("even both copies cannot replace the real backend with fake", readme.replace(real, fake),
            first.replace(real, fake), "on_real must call with_gpu_real"),
        ("a missing public assemble command", readme.replace('./gpu_fake assemble sm_86 "$TILEIRAS"',
            './gpu_fake fake'), first, "has no public command"),
    ]
    for name, doc, example, want in controls:
        problems = check_readme(doc, example)
        ok = not problems if want is None else any(want in p for p in problems)
        print(("PASS  " if ok else "FAIL  ") + name)
        if not ok:
            bad += 1
            print(f"      got {problems!r}, wanted {want!r}")
    for name, table, gpu_fixture, runtime_fixture, want in error_controls(errs, gpu, runtime):
        problems = check_errors(table, gpu_fixture, src, runtime_fixture, checker)
        ok = not problems if want is None else any(want in p for p in problems)
        print(("PASS  " if ok else "FAIL  ") + name)
        if not ok:
            bad += 1
            print(f"      got {problems!r}, wanted {want!r}")
    origins = error_sources(gpu, runtime)
    shared = (origins["gpu.bad_length"] == {GPU, RUNTIME_C}
              and origins["gpu.bad_grid"] == {GPU, RUNTIME_C}
              and origins["gpu.unsupported_backend"] == {RUNTIME_C, RUNTIME_JVM})
    print(("PASS  " if shared else "FAIL  ") + "shared kinds retain every producer")
    bad += not shared
    # the pattern of gpu_kinds is itself read: one of the kinds it finds is not
    # a test fixture
    if "gpu.test" in gpu_kinds(gpu):
        print("FAIL  a test fixture kind leaked into the production kinds")
        bad += 1
    return 1 if bad else 0


# The summary line says `tileir-docs` and not `tileir docs` on purpose: site/src/
# gen/gpu.dawn reads scripts/tileir-features/check.py's output for the lines that
# start `PASS  tileir <name>:` and counts each as a coverage ledger.
def main(argv):
    if argv[1:] == ["--self-test"]:
        return self_test()
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 2
    src, runtime = sources()
    problems = [f"operations: {p}" for p in check_operations(
        read(OPERATIONS), read(DEV), read(PROG), read(FEATURES))]
    problems += [f"errors: {p}" for p in check_errors(read(ERRORS), read(GPU), src, runtime, read(CHECKER))]
    problems += [f"readme: {p}" for p in check_readme(read(README), read(FIRST))]
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    n_fn = len(table_rows(read(OPERATIONS)))
    n_err = len(table_rows(read(ERRORS)))
    print(f"PASS  tileir-docs: {n_fn} function row(s) in OPERATIONS.md, {n_err} error row(s) in ERRORS.md, "
          f"{len(SHOWN)} item(s) of the README's example")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

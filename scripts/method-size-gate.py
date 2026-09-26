#!/usr/bin/env python3
"""Method-size gate: no method of the compiler may be too big for the JIT.

HotSpot refuses to compile any method whose bytecode is longer than
HugeMethodLimit, 8000 bytes, unless -XX:-DontCompileHugeMethods is given
(compilationPolicy.cpp, `can_be_compiled`; OSR goes through the same test).
C1, C2 and Graal as a JVMCI compiler all ask that one question, so a method
over the line runs in the interpreter for the life of the process. Four
checker methods were over it on 2026-09-26 and cold checking was 20 to 27%
slower for it (issue #241); the ruling there was to split the source rather
than change the JVM flags, and to hold the split with this gate.

The rule is a rule, not a ratchet: every method in the built selfhost jar is
at most 8000 bytes, except
  * classes under `embed/`, the generated Unicode tables, which run once at
    class initialization and are expected to be large (their distance from the
    JVM's hard 65535-byte limit is reported instead, since that one is fatal);
  * test blocks, `dawn$test$N`, which run once per `dawn test`;
  * the vendored Java dependencies (ASM, the coursier interface), which are
    not ours to split. Which packages those are is read from the `--vendor`
    arguments of the two recipes that build this jar, bin/dawn and
    scripts/build-release-jar.sh, so the exemption is the build's own
    statement of what it copied in and cannot drift from it. (A `SourceFile`
    attribute does not tell them apart: the shaded jsoniter classes inside
    coursierapi carry none, exactly like the classes Dawn emits.)
There is no allow list and no recorded count. A lifted closure is named
`lambda$N` by position, so its name moves with any unrelated edit above it,
and a list or count keyed on names would go red on changes that did not touch
the method.

How it measures: the `code_length` of each method's Code attribute, read from
the class files in the jar with the struct module -- no JVM, no javap, no ASM
(the same reason as constpool-scan.py: a check that used the emitter's own
library would go blind exactly where the library is wrong). `code_length` is
what the JVM compares with HugeMethodLimit (`Method::code_size`). The whole
jar, about 43,000 methods with the vendored ones, reads in under a second.

    scripts/method-size-gate.py [--jar build/dawn-selfhost.jar] [--limit 8000] [--top N]
    scripts/method-size-gate.py --selftest

The self-test builds class files in memory for each case of the rule and
requires the expected verdict, then re-runs the real jar with the limit set
one byte under its largest checked method and requires red: a reader that
stopped seeing methods would pass every other case.
"""

import argparse
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JAR = ROOT / "build" / "dawn-selfhost.jar"
RECIPES = [ROOT / "bin" / "dawn", ROOT / "scripts" / "build-release-jar.sh"]
VENDOR_ARG = re.compile(r"--vendor\s+([A-Za-z0-9_/$.-]+)")
LIMIT = 8000
CODE_MAX = 65535
TEST_BLOCK = re.compile(r"^dawn\$test\$\d+$")
# a package's classes sit under `dawn$pkg$<name>/`; the module path follows
PKG_PREFIX = re.compile(r"^dawn\$pkg\$[^/]+/")

# constant tag -> bytes after the tag byte, for the fixed-width entries
FIXED = {
    3: 4, 4: 4, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
    15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2,
}


def read_class(data):
    """(class name, source file or None, [(method name + descriptor, code_length)])."""
    if len(data) < 10 or data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a class file")
    count = struct.unpack_from(">H", data, 8)[0]
    utf8 = {}
    classes = {}
    off, i = 10, 1
    while i < count:
        tag = data[off]
        off += 1
        if tag == 1:
            n = struct.unpack_from(">H", data, off)[0]
            utf8[i] = data[off + 2:off + 2 + n].decode("utf-8", "replace")
            off += 2 + n
        elif tag in (5, 6):  # Long and Double take two slots
            off += 8
            i += 1
        elif tag in FIXED:
            if tag == 7:
                classes[i] = struct.unpack_from(">H", data, off)[0]
            off += FIXED[tag]
        else:
            raise ValueError(f"unknown constant tag {tag} at pool index {i}")
        i += 1
    this_class = struct.unpack_from(">H", data, off + 2)[0]
    name = utf8[classes[this_class]]
    off += 6
    interfaces = struct.unpack_from(">H", data, off)[0]
    off += 2 + 2 * interfaces

    def members(off, want_code):
        n = struct.unpack_from(">H", data, off)[0]
        off += 2
        out = []
        for _ in range(n):
            _, name_i, desc_i, attrs = struct.unpack_from(">HHHH", data, off)
            off += 8
            for _ in range(attrs):
                attr_i, length = struct.unpack_from(">HI", data, off)
                if want_code and utf8.get(attr_i) == "Code":
                    # Code: max_stack u2, max_locals u2, code_length u4
                    code_length = struct.unpack_from(">I", data, off + 10)[0]
                    out.append((utf8[name_i] + utf8[desc_i], code_length))
                off += 6 + length
        return off, out

    off, _ = members(off, False)
    off, methods = members(off, True)
    source = None
    attrs = struct.unpack_from(">H", data, off)[0]
    off += 2
    for _ in range(attrs):
        attr_i, length = struct.unpack_from(">HI", data, off)
        if utf8.get(attr_i) == "SourceFile":
            source = utf8[struct.unpack_from(">H", data, off + 6)[0]]
        off += 6 + length
    return name, source, methods


def vendored_packages():
    """The `--vendor` packages the build recipes copy into the jar."""
    found = set()
    for recipe in RECIPES:
        found |= set(VENDOR_ARG.findall(recipe.read_text(encoding="utf-8")))
    return sorted(found)


def classify(class_name, method, vendored):
    """'vendored', 'embed', 'test' or 'checked'."""
    if any(class_name.startswith(p.rstrip("/") + "/") for p in vendored):
        return "vendored"
    if PKG_PREFIX.sub("", class_name).startswith("embed/"):
        return "embed"
    if TEST_BLOCK.match(method.split("(", 1)[0]):
        return "test"
    return "checked"


def measure(entries, vendored):
    """entries: iterable of class-file bytes. Returns {kind: [(size, class, method)]}."""
    out = {"vendored": [], "embed": [], "test": [], "checked": []}
    for data in entries:
        name, _, methods = read_class(data)
        for method, size in methods:
            out[classify(name, method, vendored)].append((size, name, method))
    for rows in out.values():
        rows.sort(reverse=True)
    return out


def jar_entries(jar):
    with zipfile.ZipFile(jar) as z:
        for n in z.namelist():
            if n.endswith(".class"):
                yield z.read(n)


def shown(row):
    size, cls, method = row
    return f"{size:>6}  {cls}.{method.split('(', 1)[0]}"


def verdict(m, limit, top=0, quiet=False):
    """Print the report; return 0 when no checked method exceeds `limit`."""
    over = [r for r in m["checked"] if r[0] > limit]
    say = (lambda *a: None) if quiet else print
    n = sum(len(v) for v in m.values())
    if top:
        say(f"largest checked methods (limit {limit}):")
        for r in m["checked"][:top]:
            say("  " + shown(r))
    if m["embed"]:
        big = m["embed"][0]
        say(f"embed/ tables: largest {big[0]} bytes ({big[1]}.{big[2].split('(', 1)[0]}), "
            f"{CODE_MAX - big[0]} under the JVM's {CODE_MAX}-byte Code limit")
    if over:
        if not quiet:
            for r in over:
                print(f"METHOD SIZE FAIL {shown(r).strip()} bytes > {limit}", file=sys.stderr)
            print(f"FAIL: {len(over)} method(s) over {limit} bytes of bytecode, which HotSpot "
                  f"will never JIT-compile (HugeMethodLimit); split them (issue #241)",
                  file=sys.stderr)
        return 1
    largest = shown(m["checked"][0]).strip() if m["checked"] else "none"
    say(f"OK: {len(m['checked'])} checked methods of {n} at most {limit} bytes "
        f"(largest {largest}); skipped {len(m['embed'])} embed/, {len(m['test'])} test-block "
        f"and {len(m['vendored'])} vendored methods")
    return 0


# ---- self-test ----

def synth(name, methods, source=None):
    """A minimal class file: `name`, the given (method, code_length) pairs, and
    a pool that exercises the two-slot and fixed-width tags the reader skips."""
    pool = []
    seen = {}

    def utf(s):
        if s not in seen:
            b = s.encode()
            pool.append(b"\x01" + struct.pack(">H", len(b)) + b)
            seen[s] = len(pool)
        return seen[s]

    def slot(entry, width=1):
        pool.append(entry)
        index = len(pool)
        for _ in range(width - 1):
            pool.append(b"")
        return index

    slot(b"\x05" + struct.pack(">q", 1 << 40), 2)       # Long
    slot(b"\x06" + struct.pack(">d", 0.5), 2)           # Double
    nat = slot(b"\x0c" + struct.pack(">HH", utf("x"), utf("I")))
    slot(b"\x0f\x06" + struct.pack(">H", nat))          # MethodHandle
    slot(b"\x12" + struct.pack(">HH", 0, nat))          # InvokeDynamic
    this = slot(b"\x07" + struct.pack(">H", utf(name)))
    sup = slot(b"\x07" + struct.pack(">H", utf("java/lang/Object")))
    for s in ["Code", "SourceFile", "Deprecated", "f", "()V"] + [m for m, _ in methods]:
        utf(s)
    if source is not None:
        utf(source)
    # every entry exists now; the rest only looks indices up
    body = b""
    for mname, size in methods:
        code = struct.pack(">HHI", 1, 1, size) + b"\x00" * size + struct.pack(">HH", 0, 0)
        body += struct.pack(">HHHH", 9, utf(mname), utf("()V"), 2)
        body += struct.pack(">HI", utf("Deprecated"), 0)
        body += struct.pack(">HI", utf("Code"), len(code)) + code
    cls_attrs = b""
    if source is not None:
        cls_attrs = struct.pack(">HIH", utf("SourceFile"), 2, utf(source))
    out = b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 52, len(pool) + 1)
    out += b"".join(pool)
    out += struct.pack(">HHHH", 0x21, this, sup, 0)
    out += struct.pack(">H", 1) + struct.pack(">HHHH", 2, utf("f"), utf("I"), 0)
    out += struct.pack(">H", len(methods)) + body
    out += struct.pack(">H", 1 if source is not None else 0) + cls_attrs
    return out


def selftest(jar):
    cases = [
        ("a method at the limit", [synth("check/a", [("f", LIMIT)])], 0),
        ("one byte over", [synth("check/a", [("f", LIMIT + 1)])], 1),
        ("a lifted closure over", [synth("lsp/server", [("lambda$29", 9000)])], 1),
        ("a package class over", [synth("dawn$pkg$json2/json", [("parse", 9000)])], 1),
        ("an embed/ table", [synth("embed/unicode_case", [("upper", 19783)])], 0),
        ("an embed/ table in a package",
         [synth("dawn$pkg$selfhost/embed/unicode_case", [("upper", 19783)])], 0),
        ("a test block", [synth("check/checker", [("dawn$test$11", 9000)])], 0),
        ("a name like a test block", [synth("check/checker", [("dawn$test$x", 9000)])], 1),
        ("a vendored class", [synth("org/objectweb/asm/Frame", [("big", 9000)])], 0),
        ("a shaded class of a vendored package",
         [synth("coursierapi/shaded/x/Y", [("<clinit>", 16217)])], 0),
        ("a vendored name is a package, not a prefix",
         [synth("coursierapix/Y", [("big", 9000)])], 1),
        ("a Java source file exempts nothing", [synth("check/a", [("f", 9000)], "a.java")], 1),
        ("embedded is not a prefix of the module", [synth("check/embed", [("f", 9000)])], 1),
    ]
    bad = 0
    fake_vendor = ["org/objectweb/asm", "coursierapi"]
    for label, entries, want in cases:
        got = verdict(measure(entries, fake_vendor), LIMIT, quiet=True)
        if got != want:
            print(f"SELFTEST FAIL {label}: exit {got}, wanted {want}", file=sys.stderr)
            bad += 1
    reread = read_class(synth("check/a", [("f", 1234), ("g", 7)]))
    if reread[2] != [("f()V", 1234), ("g()V", 7)]:
        print(f"SELFTEST FAIL reader: {reread}", file=sys.stderr)
        bad += 1
    vendored = vendored_packages()
    if not vendored:
        print(f"SELFTEST FAIL no --vendor argument found in {', '.join(map(str, RECIPES))}",
              file=sys.stderr)
        bad += 1
    if jar.is_file():
        m = measure(jar_entries(jar), vendored)
        present = {p for p in vendored for r in m["vendored"] if r[1].startswith(p + "/")}
        for p in vendored:
            if p not in present:
                print(f"SELFTEST FAIL {jar}: the recipes vendor {p}, the jar has no class of it",
                      file=sys.stderr)
                bad += 1
        if not m["checked"]:
            print(f"SELFTEST FAIL {jar}: no checked methods read", file=sys.stderr)
            bad += 1
        else:
            top = m["checked"][0][0]
            # the threshold mutant: one byte under the jar's largest checked method
            if verdict(m, top - 1, quiet=True) != 1 or verdict(m, top, quiet=True) != 0:
                print(f"SELFTEST FAIL {jar}: the limit {top - 1} did not red "
                      f"or {top} did not pass", file=sys.stderr)
                bad += 1
    else:
        print(f"note: {jar} not built, threshold mutant on the real jar skipped")
    if bad:
        return 1
    print(f"OK: method-size gate self-test, {len(cases)} synthetic cases, reader round trip"
          + (", threshold mutant on the real jar" if jar.is_file() else ""))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jar", type=Path, default=DEFAULT_JAR)
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--top", type=int, default=0, help="list the N largest checked methods")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return selftest(a.jar)
    if not a.jar.is_file():
        print(f"FAIL: {a.jar} not found; build it with ./bin/dawn --version", file=sys.stderr)
        return 2
    return verdict(measure(jar_entries(a.jar), vendored_packages()), a.limit, a.top)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

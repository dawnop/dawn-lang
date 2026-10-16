#!/usr/bin/env python3
"""Programs at and over the JVM's 255 argument-slot limit (JVMS 4.3.3).

A method whose descriptor needs more than 255 slots is rejected when the class
loads, not when it is written, so `dawn build` used to print `wrote ...jar` for
a jar that could not run. The compiler now refuses it with a source location.
Which side of the line a program falls on depends on how the slots are counted
(Int and Float take two, a receiver, a type-class dictionary and an effect
evidence record one each, a closure's captures are parameters of its body), so
the cases come in pairs that differ by exactly one slot: every `accept` entry is
the 255-slot twin of a `refused` entry at 256. A check that refused everything
would fail the first group; one that refused nothing, the second.

    slot_cases.py <outdir>

writes <outdir>/accept.dawn with its stdout in accept.expect, and one
<outdir>/refused/<name>.dawn per refused case, with <outdir>/refused.txt
listing `<name> <line>`: the line the error must point at.
"""

import os
import sys


def ints(n, pre="a"):
    return ", ".join(f"{pre}{i}: Int" for i in range(n))


def ones(n):
    return ", ".join("1" for _ in range(n))


def bools(n, pre="b"):
    return ", ".join(f"{pre}{i}: Bool" for i in range(n))


def trues(n):
    return ", ".join("true" for _ in range(n))


def lets(n):
    return "\n".join(f"  let v{i} = {i + 1}" for i in range(n))


TICK = "effect Tick {\n  fn tick() -> Int\n}\n"


def params_fn(n_int, n_bool, name="wide"):
    sig = ints(n_int) + ((", " + bools(n_bool)) if n_bool else "")
    args = ones(n_int) + ((", " + trues(n_bool)) if n_bool else "")
    return (f"fn {name}({sig}) -> Int = a0 + a{n_int - 1}\n", f"{name}({args})")


def dict_fn(n_t, name="wide"):
    ts = ", ".join(f"t{i}: T" for i in range(n_t))
    args = ones(126) + ", " + ", ".join("1" for _ in range(n_t))
    return (f"fn {name}[T: Eq]({ints(126)}, {ts}) -> Int = if t0 == t1 {{ a0 }} else {{ a125 }}\n",
            f"{name}({args})")


def evidence_fn(n_bool, name="wide"):
    extra = (", " + bools(n_bool)) if n_bool else ""
    args = ones(127) + ((", " + trues(n_bool)) if n_bool else "")
    # the handler wraps the call in its own function so `main` stays plain
    decl = (TICK + f"\nfn {name}({ints(127)}{extra}) -> Int !Tick = a0 + tick()\n"
            f"\nfn {name}_handled() -> Int = {{\n  with handle Tick {{\n    tick() => 1\n  }}\n"
            f"  {name}({args})\n}}\n")
    return decl, f"{name}_handled()"


def capture_main(n_int, n_bool):
    body = lets(n_int) + "\n" + "\n".join(f"  let w{i} = true" for i in range(n_bool))
    used = " + ".join([f"v{i}" for i in range(n_int)] +
                      [f"(if w{i} {{ 1 }} else {{ 0 }})" for i in range(n_bool)])
    return body.rstrip("\n"), used


def main(out):
    os.makedirs(os.path.join(out, "refused"), exist_ok=True)

    # ---- accept: every one at exactly 255 slots ----
    parts, calls, expect = [], [], []

    def add(label, decl, call, value):
        parts.append(decl)
        calls.append(f'  println("{label} " ++ to_string({call}))')
        expect.append(f"{label} {value}")

    d, c = params_fn(127, 0, "p127")
    add("params", d, c, 2)  # 127 Int = 254
    d, c = params_fn(126, 3, "mixed255")
    add("mixed", d, c, 2)  # 126 Int + 3 Bool = 255
    d, c = dict_fn(2, "dict255")
    add("dict", d, c, 1)  # 252 + 2 + dictionary = 255
    d, c = evidence_fn(0, "ev255")
    add("evidence", d, c, 2)  # 254 + evidence = 255

    cap_body, cap_sum = capture_main(127, 0)  # 254 + evidence = 255
    cap_mixed_body, cap_mixed_sum = capture_main(126, 2)  # 252 + 2 + evidence = 255
    text = "\n".join(parts)
    text += f"\nfn captures() -> Int = {{\n{cap_body}\n  let f = () => {cap_sum}\n  f()\n}}\n"
    text += (f"\nfn captures_mixed() -> Int = {{\n{cap_mixed_body}\n"
             f"  let f = () => {cap_mixed_sum}\n  f()\n}}\n")
    text += "\npub fn main() -> Unit !io = {\n" + "\n".join(calls) + "\n"
    text += '  println("captures " ++ to_string(captures()))\n'
    text += '  println("captures_mixed " ++ to_string(captures_mixed()))\n}\n'
    expect.append(f"captures {sum(range(1, 128))}")
    expect.append(f"captures_mixed {sum(range(1, 127)) + 2}")
    with open(os.path.join(out, "accept.dawn"), "w") as f:
        f.write(text)
    with open(os.path.join(out, "accept.expect"), "w") as f:
        f.write("\n".join(expect) + "\n")

    # ---- refused: each one slot over ----
    refused = []

    def refuse(name, src, marker):
        line = next(i + 1 for i, l in enumerate(src.split("\n")) if l.startswith(marker))
        with open(os.path.join(out, "refused", name + ".dawn"), "w") as f:
            f.write(src)
        refused.append((name, line))

    def with_main(decl, call):
        return decl + f"\npub fn main() -> Unit !io = println(to_string({call}))\n"

    d, c = params_fn(128, 0)
    refuse("params", with_main(d, c), "fn wide")
    d, c = params_fn(126, 4)
    refuse("mixed", with_main(d, c), "fn wide")
    d, c = dict_fn(3)
    refuse("dict", with_main(d, c), "fn wide")
    d, c = evidence_fn(1)
    refuse("evidence", with_main(d, c), "fn wide")

    body, used = capture_main(128, 0)
    refuse("captures", f"pub fn main() -> Unit !io = {{\n{body}\n  let f = () => {used}\n"
           "  println(to_string(f()))\n}\n", "pub fn main")
    body, used = capture_main(126, 3)
    refuse("captures_mixed", f"pub fn main() -> Unit !io = {{\n{body}\n  let f = () => {used}\n"
           "  println(to_string(f()))\n}\n", "pub fn main")

    # a trait method is an interface method: the receiver is one more slot
    # than the static an impl compiles to, so this is 255 there and 256 here
    src = (f"trait Wide[T] {{\n  fn go(x: T, {ints(126)}, {bools(2)}) -> Int\n}}\n\n"
           'pub fn main() -> Unit !io = println("unused")\n')
    refuse("trait", src, "trait Wide")

    with open(os.path.join(out, "refused.txt"), "w") as f:
        for name, line in refused:
            f.write(f"{name} {line}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: slot_cases.py <outdir>")
    main(sys.argv[1])

#!/usr/bin/env python3
"""Break one rule of the io primitives in a copy of the repository tree.

    scripts/io-prims-contract/mutate.py <mutation> <tree-root>

run.sh applies one mutation to a private copy of runtime/c and std, and requires
the contract to go red for it. The anchors live here, in the registry shape
mutation-anchor-preflight.py discovers, so they have two consumers: run.sh
applies them, and the preflight proves each exactly-once against the checkout
before anything is built. A rename of one of these lines then fails the cheap
job, not the one that builds the binaries.

Two layers are broken, because the contract has two ways to see:

  native runtime (runtime/c/dawn_rt.c)   no-flush, append-truncates,
                                          range-off-by-one: caught by the native
                                          builds, which link the broken runtime
  std (std/io.dawn)                       std-append-truncates,
                                          std-range-off-by-one: caught on the JVM
                                          backend too, which run.sh drives with
                                          `--std <copy>`; a primitive of the JVM
                                          runtime is a class the compiler writes,
                                          and breaking one would take a compiler
                                          rebuild per control

There is no JVM flush mutation: System.out is an auto-flushing PrintStream, so
the JVM delivers a byte write at once whether or not flush_stdout does
anything, and a control that could not go red would prove nothing.
"""

from pathlib import Path
import sys

RT = "runtime/c/dawn_rt.c"
IO = "std/io.dawn"

MUTATIONS = {
    # flush_stdout stops flushing: bytes sit in the 64 KiB stdio buffer
    "no-flush": ((
        RT,
        "dawn_unit dawn_io_flush_stdout(void) {\n  fflush(stdout);\n",
        "dawn_unit dawn_io_flush_stdout(void) {\n",
    ),),
    # an append replaces the file instead of extending it
    "append-truncates": ((
        RT,
        "int fd = open(p, O_WRONLY | O_CREAT | O_APPEND | DAWN_O_CLOEXEC, 0666);",
        "int fd = open(p, O_WRONLY | O_CREAT | O_TRUNC | DAWN_O_CLOEXEC, 0666);",
    ),),
    # a range read starts one byte late
    "range-off-by-one": ((
        RT,
        "pread(fd, buf + got, (size_t)(want - got), (off_t)(off + got));",
        "pread(fd, buf + got, (size_t)(want - got), (off_t)(off + got + 1));",
    ),),
    # the same two, one layer up, where the JVM backend sees them too
    "std-append-truncates": ((
        IO,
        "fs_append_bytes(path, content) => catch_fault(() => io_append_bytes(path, content))",
        "fs_append_bytes(path, content) => catch_fault(() => io_write_bytes(path, content))",
    ),),
    "std-range-off-by-one": ((
        IO,
        "fs_read_range(path, off, n) => catch_fault(() => io_read_range(path, off, n))",
        "fs_read_range(path, off, n) => catch_fault(() => io_read_range(path, off + 1, n))",
    ),),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()

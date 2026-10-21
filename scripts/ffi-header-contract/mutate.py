#!/usr/bin/env python3
"""Break one rule of dawn_ffi.h in a copy of the repository tree.

    scripts/ffi-header-contract/mutate.py <mutation> <tree-root>

run.sh applies one mutation to a private copy of runtime/c and requires the
contract to go red for it. The anchors live here, in the registry shape
mutation-anchor-preflight.py discovers, so they have two consumers: run.sh
applies them, and the preflight proves each exactly-once against the checkout
before anything is built.

What each one breaks, and what must see it:

  abi-mismatch      the ABI number moves; the stub still asks for the old one,
                    so its compile must fail
  cstr-truncates    a string with an embedded NUL is handed to the library as
                    the C string up to the NUL instead of being refused
  err-mask-short    the ForeignError the header builds hides two of its three
                    reference fields from the drop: leaked, and the mask is
                    not the runtime's
  bytes-cut-at-nul  bytes copied from C stop at the first zero byte
  fence-open        dawn_fault leaves the poison list, so a stub that calls it
                    compiles (fault_stub.c must then build, which is what
                    proves its red under the real header was the fence)
"""

from pathlib import Path
import sys

H = "runtime/c/dawn_ffi.h"

MUTATIONS = {
    "abi-mismatch": ((
        H,
        "#define DAWN_FFI_ABI 1\n",
        "#define DAWN_FFI_ABI 2\n",
    ),),
    "cstr-truncates": ((
        H,
        "  if (s->len > 0 && memchr(s->p, 0, (size_t)s->len) != NULL) {\n    return NULL;\n  }\n",
        "",
    ),),
    "err-mask-short": ((
        H,
        "dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_THREE_BOXED)",
        "dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_ONE_BOXED)",
    ),),
    "bytes-cut-at-nul": ((
        H,
        "dawn_bytes_utf8(dawn_str_lit((const char *)p, n))",
        "dawn_bytes_utf8(dawn_str_lit((const char *)p, memchr(p, 0, (size_t)n) ? (int64_t)((const char *)memchr(p, 0, (size_t)n) - (const char *)p) : n))",
    ),),
    "fence-open": ((
        H,
        "#pragma GCC poison dawn_fault dawn_panic dawn_dup",
        "#pragma GCC poison dawn_panic dawn_dup",
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

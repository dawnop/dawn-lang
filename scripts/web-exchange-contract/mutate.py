#!/usr/bin/env python3
"""Break one rule of web/exchange in a copy of the repository tree.

    scripts/web-exchange-contract/mutate.py <mutation> <tree-root>

run.sh applies one mutation to a private copy of packages/web and requires the
contract to go red on the fixtures that exist for that rule. The anchors live
here, in the registry shape mutation-anchor-preflight.py discovers, so they have
two consumers: run.sh applies them, and the preflight proves each exactly-once
against the checkout before any build. A rename of one of these lines in
exchange.dawn then fails the cheap job, not the one that builds six binaries.

The paths are relative to the tree root the caller passes; run.sh lays the copy
out as `<root>/packages/web`, so the preflight can hand this script the checkout.
"""

from pathlib import Path
import sys

EXCHANGE = "packages/web/src/exchange.dawn"

MUTATIONS = {
    # chunked request bodies are not decoded: the body is empty
    "no-chunked-decoding": ((
        EXCHANGE,
        "ChunkedBody -> read_chunked(t, pos, limit, fmt)",
        'ChunkedBody -> Ok(bytes.utf8(""))',
    ),),
    # a HEAD response writes its body like a GET
    "head-writes-its-body": ((
        EXCHANGE,
        "  if head_only {\n    drop_body(body)\n  } else {",
        "  if false {\n    drop_body(body)\n  } else {",
    ),),
    # a dot segment is no longer refused
    "no-dot-segment-check": ((
        EXCHANGE,
        "if has_dot_segment(h.raw_path) {",
        "if has_dot_segment(h.raw_path) && false {",
    ),),
    # the route's guard is never consulted
    "guard-not-consulted": ((
        EXCHANGE,
        "run_guard(guard_of(d), base, errors, log)?",
        "run_guard(None, base, errors, log)?",
    ),),
}

# The same faults must be visible in each backend, including the JVM pump
# whose InputStream adapter would otherwise mask a bad position.
for side, path, read in (
    ("native", EXCHANGE, "src.read(total, READ_CHUNK)"),
    ("jvm", "packages/web-jvm/src/server.dawn", "src.read(total, PUMP_CHUNK)"),
):
    MUTATIONS[f"{side}-offset-stuck"] = ((path, read, read.replace("total,", "0,")),)
    MUTATIONS[f"{side}-offset-plus-one"] = ((path, read, read.replace("total,", "total + 1,")),)
    # Ownership is shared by the servers, but each built arm is exercised.
    MUTATIONS[f"{side}-no-source-close"] = ((
        EXCHANGE, "let _ = catch_fault(() => s.close())",
        "let _ = catch_fault(() => { let _ = s\n      () })",
    ),)
    MUTATIONS[f"{side}-head-reads-source"] = ((
        EXCHANGE, "Stream(s, _) -> close_source(s)",
        "Stream(s, _) -> { let _ = s.read(0, 1)\n      close_source(s) }",
    ),)



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

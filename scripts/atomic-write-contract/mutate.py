#!/usr/bin/env python3
"""Apply one atomic-write injection or mutant to a copy of the repository tree.

    scripts/atomic-write-contract/mutate.py <mutation> <tree-root>

The anchors used to be arguments to run.sh's `patch_std` shell helper, one
close-injection heredoc and one call-site heredoc, each refusing a non-unique
match. That made them self-once: correct, but checked only when this contract
ran, which builds three private compilers and a dozen probes first. They quote
std/io.dawn, runtime/c/dawn_rt.c, pkg/add.dawn and pkg/pkgcmd.dawn. Declared here,
in the registry shape mutation-anchor-preflight.py already discovers, the same
anchors have two consumers: run.sh applies one mutation per private tree, and
the preflight proves every one of them exactly-once before any build (#254).
The fault helpers some injections call are appended by run.sh after the
mutation; an append has no anchor to prove.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. `skip-verify` is the corrupting writer with the read-back check
removed, so it repeats `inject-corrupt-write`'s edit before its own. The paths
are relative to the tree root the caller passes: run.sh lays each private
std out as `<root>/std`, the close-injection runtime as `<root>/runtime/c`
and each call-site compiler as `<root>/selfhost`, so the preflight can hand
this script the checkout.
"""

from pathlib import Path
import sys

IO = "std/io.dawn"

WRITE = "  match write_file(tmp, content) {"
CORRUPT = (IO, WRITE, '  match write_file(tmp, content ++ "corrupt") {')
PERMISSION = "  if exists(path) { copy_permissions(path, tmp) } else { Ok(()) }"
STAGING_FAILED = '''      Err(e) -> Err(ForeignError {
        kind: "io.atomic_write_staging_failed",
        message: "io.atomic_write_file: cannot create a staging file in "
          ++ parent_dir(path),
        cause: Some(e.kind ++ ": " ++ e.message)
      })'''
ATOMIC_CALL = ("io.atomic_write_file(", "io.write_file(")

MUTATIONS = {
    # Injections: a failure forced at one step.
    "inject-write": ((IO, WRITE, '  match inject_fault("write") {'),),
    "inject-close": ((
        "runtime/c/dawn_rt.c",
        '''  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(DAWN_LIT("io_write_file: write failed"));''',
        '''  if (fclose(f) != 0) bad = true;
  bad = true; /* injected: the close step reports failure */
  if (bad) {
    dawn_fault(DAWN_LIT("io_write_file: write failed"));''',
    ),),
    "inject-readback": ((IO, "      match read_bytes(tmp) {",
                         '      match inject_bytes_fault("readback") {'),),
    "inject-corrupt-write": (CORRUPT,),
    "inject-permission": ((IO, PERMISSION,
                           '  if exists(path) { inject_fault("permission") } else { Ok(()) }'),),
    # Mutants: one promise removed from std/io.dawn.
    "direct-fallback": ((
        IO,
        STAGING_FAILED + "\n      Ok(tmp) -> stage_replace(path, content, tmp)",
        "      Err(_) -> write_file(path, content)\n"
        "      Ok(tmp) -> stage_replace(path, content, tmp)",
    ),),
    "fixed-temp-name": ((IO, '    match temp_file(parent_dir(path), ".dawn-atomic-") {',
                         "    match fixed_temp(parent_dir(path)) {"),),
    "skip-verify": (CORRUPT, (IO, "          if seen != bytes_utf8(content) {",
                              "          if false {")),
    "delete-before-rename": ((IO, "                match rename(tmp, path) {",
                              "                match rename_after_delete(tmp, path) {"),),
    "follow-symlink": ((IO, "  } else if is_symlink(path) {", "  } else if false {"),),
    "no-cleanup": ((
        IO,
        """fn abandon(tmp: String, e: ForeignError) -> Result[Unit, ForeignError] !Fs = {
  let _ = delete(tmp)
  Err(e)
}""",
        """fn abandon(tmp: String, e: ForeignError) -> Result[Unit, ForeignError] !Fs = {
  let _ = tmp
  Err(e)
}""",
    ),),
    "no-permission-copy": ((IO, PERMISSION,
                            "  if false { copy_permissions(path, tmp) } else { Ok(()) }"),),
    "staging-message-passthrough": ((
        IO,
        STAGING_FAILED,
        '''      Err(e) -> Err(ForeignError {
        kind: "io.atomic_write_staging_failed",
        message: e.message,
        cause: None
      })''',
    ),),
    # Call sites: one compiler writer put back to a plain overwrite.
    "add-plain-write": (("selfhost/src/pkg/add.dawn", *ATOMIC_CALL),),
    "lock-plain-write": (("selfhost/src/pkg/pkgcmd.dawn", *ATOMIC_CALL),),
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

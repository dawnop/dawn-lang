#!/usr/bin/env python3
"""Apply one delete-contract mutation to a copy of the repository tree.

The anchors used to live in heredocs inside run.sh, each one refusing a
non-unique match when the contract ran. That made them self-once: correct, but
checked only by whoever ran this build-heavy contract. #248 rewrote
`dawn_cpath` in runtime/c/dawn_rt.c, mutation-anchor-preflight.py said OK, and
the stale anchor was found by the contract's first local run (#249). Declaring
them here, in the registry shape the preflight already reads, gives the same
anchors two consumers: run.sh applies one per mutant, and the preflight proves
every one of them exactly-once before any build.

Paths are relative to the tree root the caller passes. run.sh lays each mutant
copy out with the repository's own relative paths, so the preflight can hand
this script the checkout itself.
"""

from pathlib import Path
import sys

RUNTIME = "runtime/c/dawn_rt.c"
RTCLASSES = "selfhost/src/jvm/rtclasses.dawn"
IO = "std/io.dawn"


def query_guard(function):
    # The three Bool queries share one shape; only the function name differs.
    return (
        RUNTIME,
        f"""bool {function}(dawn_str *path) {{
  if (dawn_has_nul(path)) return false;
  char *p = dawn_cpath(path);""",
        f"""bool {function}(dawn_str *path) {{
  char *p = dawn_cpath(path);""",
    )


MUTATIONS = {
    # The C path bridge without its embedded-NUL rejection silently stops at
    # the first zero byte, so delete acts on the prefix.
    "c-cpath-nul": (
        RUNTIME,
        """static char *dawn_cpath(dawn_str *s) {
  dawn_reject_nul(s);
  char *p = (char *)dawn_alloc((size_t)s->len + 1);""",
        """static char *dawn_cpath(dawn_str *s) {
  char *p = (char *)dawn_alloc((size_t)s->len + 1);""",
    ),
    # Each Bool query loses its own preflight; the shared bridge then faults.
    "c-query-exists": query_guard("dawn_io_exists"),
    "c-query-is_dir": query_guard("dawn_io_is_dir"),
    "c-query-is_symlink": query_guard("dawn_io_is_symlink"),
    # getenv's Option result loses its preflight the same way.
    "c-getenv-nul": (
        RUNTIME,
        """dawn_adt *dawn_io_getenv(dawn_str *name) {
  if (dawn_has_nul(name)) return dawn_none();
  char *p = dawn_cpath(name);""",
        """dawn_adt *dawn_io_getenv(dawn_str *name) {
  char *p = dawn_cpath(name);""",
    ),
    # The old collapse where every remove(3) failure returned false.
    "c-delete-collapse": (
        RUNTIME,
        """bool dawn_io_delete(dawn_str *path) {
  char *p = dawn_cpath(path);
  int rc = remove(p);
  int saved_errno = errno;
  free(p);
  if (rc == 0) return true;
  if (saved_errno == ENOENT) return false;
  dawn_fault(DAWN_LIT("io_delete: cannot delete path"));
  return false;
}""",
        """bool dawn_io_delete(dawn_str *path) {
  char *p = dawn_cpath(path);
  bool gone = remove(p) == 0;
  free(p);
  return gone;
}""",
    ),
    # The JVM runtime generator back on File.delete.
    "jvm-file-delete": (
        RTCLASSES,
        """  push_path(dv, 0)
  dv.visitMethodInsn(OP_INVOKESTATIC, "java/nio/file/Files", "deleteIfExists",
    "(Ljava/nio/file/Path;)Z", false)""",
        """  dv.visitTypeInsn(OP_NEW, "java/io/File")
  dv.visitInsn(OP_DUP)
  dv.visitVarInsn(OP_ALOAD, 0)
  dv.visitMethodInsn(OP_INVOKESPECIAL, "java/io/File", "<init>", "(Ljava/lang/String;)V", false)
  dv.visitMethodInsn(OP_INVOKEVIRTUAL, "java/io/File", "delete", "()Z", false)""",
    ),
    # Files.isSymbolicLink reaches Path and throws for NUL, unlike
    # File.exists/isDirectory, so this preflight is the only thing between a
    # NUL path and a fault.
    "jvm-is-symlink-nul": (
        RTCLASSES,
        """  return_false_if_nul_path(sv, 0)
  push_path(sv, 0)""",
        """  push_path(sv, 0)""",
    ),
    # std's two public preflight branches, removed together.
    "std-delete-preflight": (
        IO,
        """pub fn delete(path: String) -> Result[DeleteOutcome, ForeignError] !Fs =
  if path == "" {
    Err(ForeignError {
      kind: "io.invalid_delete_path",
      message: "io.delete: path must not be empty",
      cause: None
    })
  } else if str.ends_with(path, "/") {
    Err(ForeignError {
      kind: "io.invalid_delete_path",
      message: "io.delete: path must not end with '/'",
      cause: None
    })
  } else {
    match fs_delete(path) {
      Ok(gone) -> if gone { Ok(Deleted) } else { Ok(NotFound) }
      Err(e) -> Err(e)
    }
  }""",
        """pub fn delete(path: String) -> Result[DeleteOutcome, ForeignError] !Fs =
  match fs_delete(path) {
    Ok(gone) -> if gone { Ok(Deleted) } else { Ok(NotFound) }
    Err(e) -> Err(e)
  }""",
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    rel, old, new = MUTATIONS[mutation]
    path = root / rel
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                         f"({count} matches)")
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()

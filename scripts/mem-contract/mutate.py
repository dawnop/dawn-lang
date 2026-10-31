#!/usr/bin/env python3
"""K3a controls change a built checker, the JVM emitter, or the C runtime."""
from pathlib import Path
import sys

CHECKER = "selfhost/src/check/checker.dawn"
EMIT = "selfhost/src/jvm/emit.dawn"
RUNTIME = "runtime/c/dawn_rt.c"
MUTATIONS = {
    "allow-scope-escape": ((CHECKER,
        "  let escaped = reject_scope_escape(cx1, s, at, m, em, e_lo(a), e_hi(a))",
        "  let escaped = cx1"),
        ("selfhost/src/check/types.dawn",
         "    if list.any(ty_scope_refs(source), member => match member {",
         "    if false && list.any(ty_scope_refs(source), member => match member {"),),
    "allocate-in-outer-scope": ((CHECKER,
        "bindings = map.insert(bindings, region.id, ambient[len(ambient) - 1])",
        "bindings = map.insert(bindings, region.id, ambient[0])"),),
    "jvm-ignore-domain": ((EMIT,
        "    ev_field(g1, cls, p_slot, c.fields[3].name, key_desc)\n"
        "    g1.mv.visitVarInsn(OP_LLOAD, scope_slot)\n"
        "    g1.mv.visitInsn(OP_LCMP)\n"
        "    g1.mv.visitJumpInsn(OP_IFNE, step)",
        "    # Mutant: compare only the effect atom."),),
    "jvm-reuse-instance": ((EMIT,
        '    invoke_rt(g.mv, rt_scope_new_key())',
        '    g.mv.visitInsn(OP_LCONST_0 + 1)'),
        (EMIT, 'RtMethod, invoke_rt, rt_scope_new_key, rt_array_new,',
         'RtMethod, invoke_rt, rt_array_new,'),),
    "native-ignore-domain": ((RUNTIME,
        "node->fields[0].i == key && node->fields[3].i == scope",
        "node->fields[0].i == key"),),
    "native-reuse-instance": ((RUNTIME,
        "return (int64_t)(old + 1);", "return 1;", 2),),
}


def apply(name, root):
    for edit in MUTATIONS[name]:
        relative, old, new, *count = edit
        path = Path(root) / relative
        source = path.read_text()
        expected = count[0] if count else 1
        if source.count(old) != expected:
            raise SystemExit(f"{name}: anchor in {relative} matches {source.count(old)}, expected {expected}")
        path.write_text(source.replace(old, new))


if __name__ == "__main__":
    apply(sys.argv[1], Path(sys.argv[2]))

#!/usr/bin/env python3
"""Keep the C request and selection regressions anchored for preflight.

Controls build the mutated runner before requiring an assertion failure, so a
compiler error cannot masquerade as evidence that the contract sees a defect.
"""
from pathlib import Path
import sys

R = 'playground/src/play/routes.dawn'
MUTATIONS = {
    'javap-before-c': (
        (R, 'let javap = target != "c" && tool_present(javap_bin())', 'let javap = tool_present(javap_bin())'),
        (R, 'target == "jvm" && not view.javap', '(target == "jvm" || target == "c") && not view.javap'),
    ),
    'paired-c-job': (('playground/src/play/job.dawn',
        'JCView(code) -> JCViewRaw(c_view_raw(code))',
        'JCView(code) -> { let _ = view_raw(code, true); JCViewRaw(c_view_raw(code)) }'),),
    'native-fallback': (('playground/src/play/exec.dawn',
        'let diags = diagnostics(dir, box, "emitc")',
        'let diags = diagnostics(dir, box, "emitc")\n        if native_declined(diags) { let _ = emitc_unit(dir, box, prog, true, started); () }'),),
    'old-key': (('playground/src/play/view.dawn',
        'cache_key(schema ++ "\\n" ++ toolchain, code)',
        'cache_key(if schema == "" { "" } else { toolchain }, code)'),),
    'jvm-writes-c': ((R,
        'Mapped(_c, jvm, gaps) -> shown(host, view, target, key, started, jvm, gaps)',
        'Mapped(_c, jvm, gaps) -> { host.keep_put(compile_key("c", view.toolchain, "code"), kept_line(200, "S", _c)); shown(host, view, target, key, started, jvm, gaps) }'),),
    'numeric-pick': (
        ('site/play-ui/src/compile-view.ts',
         'private clearActive() {\n    this.clearMarks()\n    this.picked = null',
         'private clearActive() {\n    this.clearMarks()'),
        ('site/play-ui/src/compile-view.ts',
         'private reapply() {\n    this.picked = null',
         'private reapply() {'),
        ('site/play-ui/src/compile-view.ts',
         'this.picked = matchIdentity(this.selection, a.code, a.build, m.view.calls)',
         'this.picked = this.picked !== null && m.view.calls[this.picked] ? this.picked : null'),
    ),
}


def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    for rel, old, new in MUTATIONS[name]:
        path = root / rel
        text = path.read_text()
        assert text.count(old) == 1, (name, rel, text.count(old))
        path.write_text(text.replace(old, new))


if __name__ == '__main__':
    main()

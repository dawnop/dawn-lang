# packages/xmap

Pairs a program's source with the C text and the JVM bytecode it compiles to: which call wrote which lines. A function of strings and records, with no I/O.

```dawn
use xmap/xmap

let built = xmap.explore(spec, raw)           # Result[Built, String], gaps inside
let c = xmap.explore_c(spec, source, ctext, cmap) # independent C table and pane
let strict = xmap.explore_strict(spec, raw)   # the first gap as the error
let text = xmap.to_xmap(b)                    # the `.xmap` rows the Playground's compile view reads
```

`spec` names the program (`Spec`) and `raw` is what the compilers printed
(`Raw`): the source, the C text and `dawn __emitc --map`'s table, the JVM
table of `dawn __emit --map`, the listing `javap -c -p -s` wrote, and for a
Tile IR kernel its recording and golden text. The caller runs the compilers;
nothing here starts a process or reads a file.

| Function | What it answers |
|---|---|
| `explore(spec, raw)` | the program mapped, with every gap listed in `gaps`; an error only when a part of `raw` cannot be read at all |
| `explore_c(spec, source, ctext, cmap)` | C calls and one C pane; local C gaps only, with no JVM input |
| `explore_strict(spec, raw)` | the same, or the first gap as the error |
| `parse_raw(spec, raw)`, `map_program(spec, inputs)` | the two halves of `explore`, for a caller that wants to change one part in between |
| `to_xmap(built)`, `pane_text(pane)` | the `.xmap` text and a pane's text |
| `parse_spec(name, text)`, `raw_files()` | the `spec.txt` convention the static page's raw directory uses |

A gap is a place where the maps and the text do not line up: a call one map
has and the other lacks, a pc range with no instruction, a column past the end
of its line, a method `javap` does not list. A call with a gap is shown without
its lines in that pane; the pane's text is always whole.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

The C-only entry deduplicates `(lo, hi, nlo)` and derives parents from spans.
Its ids, parents, ownership and gaps can differ from the paired entry. A zero
gap count here proves only local C mapping. The paired entry and strict oracle
retain their intersection and cross-backend diagnostics. Pane aggregation by
`(lo, hi)` and identifier naming from source are shared intentionally.

Tile 调用记录保留录制 id 与 parent，因此具名数值 helper `fa_exp` 与
`fa_divide` 可同时展示实际调用与定义，同一定义的重复调用分别保留。
子 span 必须位于同文件唯一的具名定义内；其它 parent 继续使用词法包含规则。
没有引入通用 host branch 求值器。

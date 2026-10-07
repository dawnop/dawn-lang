# packages/xmap

Pairs a program's source with the C text and the JVM bytecode it compiles to: which call wrote which lines. A function of strings and records, with no I/O.

```dawn
use xmap/xmap

let built = xmap.explore(spec, raw)           # Result[Built, String], gaps inside
let strict = xmap.explore_strict(spec, raw)   # the first gap as the error
let text = xmap.to_xmap(b)                    # the `.xmap` rows the explorer page reads
```

`spec` names the program (`Spec`) and `raw` is what the compilers printed
(`Raw`): the source, the C text and `dawn __emitc --map`'s table, the JVM
table of `dawn __emit --map`, the listing `javap -c -p -s` wrote, and for a
Tile IR kernel its recording and golden text. The caller runs the compilers;
nothing here starts a process or reads a file.

| Function | What it answers |
|---|---|
| `explore(spec, raw)` | the program mapped, with every gap listed in `gaps`; an error only when a part of `raw` cannot be read at all |
| `explore_strict(spec, raw)` | the same, or the first gap as the error |
| `parse_raw(spec, raw)`, `map_program(spec, inputs)` | the two halves of `explore`, for a caller that wants to change one part in between |
| `to_xmap(built)`, `pane_text(pane)` | the `.xmap` text and a pane's text |
| `parse_spec(name, text)`, `raw_files()` | the `spec.txt` convention the static page's raw directory uses |

A gap is a place where the maps and the text do not line up: a call one map
has and the other lacks, a pc range with no instruction, a column past the end
of its line, a method `javap` does not list. A call with a gap is shown without
its lines in that pane; the pane's text is always whole.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

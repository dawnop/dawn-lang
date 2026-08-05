// Curated starter programs, shown as "files" in the explorer sidebar.
//
// The code lives in ../samples/*.dawn, as real files, and is inlined here at
// build time by Vite's `?raw`. That is the point of the arrangement rather than
// a detail of it: these programs used to be TypeScript template literals, and a
// template literal is invisible to every tool that finds Dawn by looking for
// `.dawn`. The `fn`-prefixed lambda retired in v0.43.0 was migrated at ~323 call
// sites and missed here, so the sidebar shipped a program the compiler had
// rejected for eight releases -- caught in 2026-08-05 by hand, not by a gate.
// As files they are reached by `dawn fmt site --check` and by doc-check's
// samples check, which runs each one and compares stdout with the recorded
// .out beside it.
//
// The escaping trap goes away with them: in a template literal every Dawn
// `${...}` interpolation had to be written `\${...}`, so the sidebar's text and
// the source differed by an escape that only the sample with string
// interpolation ever needed.
import hello from '../samples/hello.dawn?raw'
import shapes from '../samples/shapes.dawn?raw'
import comptime from '../samples/comptime.dawn?raw'
import effects from '../samples/effects.dawn?raw'
import traits from '../samples/traits.dawn?raw'

export interface Sample {
  label: string
  file: string
  code: string
}

export const SAMPLES: Sample[] = [
  { label: 'Hello', file: 'hello.dawn', code: hello },
  { label: 'ADT + match', file: 'shapes.dawn', code: shapes },
  { label: 'comptime', file: 'comptime.dawn', code: comptime },
  { label: 'effects', file: 'effects.dawn', code: effects },
  { label: 'traits', file: 'traits.dawn', code: traits },
]

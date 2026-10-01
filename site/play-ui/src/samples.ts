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
import fizzbuzz from '../samples/fizzbuzz.dawn?raw'
import records from '../samples/records.dawn?raw'
import shapes from '../samples/shapes.dawn?raw'
import generics from '../samples/generics.dawn?raw'
import narrow from '../samples/narrow.dawn?raw'
import chars from '../samples/chars.dawn?raw'
import traits from '../samples/traits.dawn?raw'
import effects from '../samples/effects.dawn?raw'
import barriers from '../samples/barriers.dawn?raw'
import comptime from '../samples/comptime.dawn?raw'

export interface Sample {
  label: string
  file: string
  code: string
}

// Shallow to deep: the sidebar is a reading order, so the first few programs
// need nothing but loops, records and pattern matching, and the ones that
// lean on traits, effects and compile-time evaluation come last.
export const SAMPLES: Sample[] = [
  { label: 'Hello', file: 'hello.dawn', code: hello },
  { label: 'FizzBuzz', file: 'fizzbuzz.dawn', code: fizzbuzz },
  { label: 'records', file: 'records.dawn', code: records },
  { label: 'ADT + match', file: 'shapes.dawn', code: shapes },
  { label: 'generics', file: 'generics.dawn', code: generics },
  { label: 'narrow floats', file: 'narrow.dawn', code: narrow },
  { label: 'strings + chars', file: 'chars.dawn', code: chars },
  { label: 'traits', file: 'traits.dawn', code: traits },
  { label: 'effects', file: 'effects.dawn', code: effects },
  { label: 'Result + bracket', file: 'barriers.dawn', code: barriers },
  { label: 'comptime', file: 'comptime.dawn', code: comptime },
]

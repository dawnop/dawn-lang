// The Playground draft: what an edited buffer is saved as, and what a later
// visit makes of it. Kept apart from main.ts so the decision runs under the
// self-test without a browser.
//
// A draft records `src`, a digest of the sample text it started from, and no
// copy of that text. That is enough for both questions a release raises: the
// sample changed iff `src` differs from the digest of the sample now, and the
// draft was never edited iff the digest of its own code equals `src`. So
// "unedited copy of last release's sample" is decidable without keeping the old
// sample around. A draft written before `src` existed has no identity: it is
// kept only if it differs from the current sample, and then reported as stale,
// since there is no telling what it started from.

export interface Draft { file: number; code: string; base: string; src?: string }

// FNV-1a over UTF-16 code units, synchronous (crypto.subtle is async and
// absent on insecure origins). It is an identity check on a few KB of text
// against accidental drift, not a defence; a collision only means one stale
// draft is trusted.
export function digest(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0') + text.length.toString(16)
}

export type Restore =
  | { kind: 'open' } // no draft, or one to discard: open the default sample
  | { kind: 'draft'; src: string; stale: boolean }

// `sample` is the current text of the sample the draft is for, or null for a
// scratch draft (file -1 or out of range), which has no sample to go stale.
export function resolveDraft(d: Draft | null, sample: string | null): Restore {
  if (!d) return { kind: 'open' }
  if (sample == null) return { kind: 'draft', src: '', stale: false }
  const now = digest(sample)
  if (d.src === undefined) {
    return d.code === sample ? { kind: 'draft', src: now, stale: false } : { kind: 'draft', src: '', stale: true }
  }
  if (d.src === now) return { kind: 'draft', src: now, stale: false }
  if (digest(d.code) === d.src) return { kind: 'open' } // untouched copy of an old sample
  return { kind: 'draft', src: d.src, stale: true }
}

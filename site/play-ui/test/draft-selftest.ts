// The draft restore decision (src/draft.ts): a draft survives a release that
// changes its sample only if the user edited it. selftest.ts runs this after
// its own cases and adds the failures up.
import { digest, resolveDraft, type Draft } from '../src/draft'

type Expect = (name: string, got: unknown, want: unknown) => void

export function draftTests(expect: Expect): number {
  let fails = 0
  const t: Expect = (name, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) fails++
    expect(name, got, want)
  }
  const oldSample = 'fn main() {\n  FREE_AXIS\n}\n'
  const newSample = 'fn main() {\n  CellAxis\n}\n'
  const mine = oldSample + '// mine\n'
  const draft = (code: string, src?: string): Draft => ({ file: 0, code, base: '', ...(src === undefined ? {} : { src }) })

  t('digest is stable and text-sensitive', [digest(oldSample) === digest(oldSample), digest(oldSample) === digest(newSample)], [true, false])
  t('no draft opens the default sample', resolveDraft(null, newSample), { kind: 'open' })

  // unchanged sample
  t('unchanged sample, edited draft: restored, not stale', resolveDraft(draft(mine, digest(oldSample)), oldSample), { kind: 'draft', src: digest(oldSample), stale: false })
  t('unchanged sample, untouched draft: restored, not stale', resolveDraft(draft(oldSample, digest(oldSample)), oldSample), { kind: 'draft', src: digest(oldSample), stale: false })

  // changed sample, untouched draft
  t('changed sample, untouched draft: dropped, the same file opens', resolveDraft(draft(oldSample, digest(oldSample)), newSample), { kind: 'sample', file: 0 })
  t('the file is the draft\'s own', resolveDraft({ ...draft(oldSample, digest(oldSample)), file: 3 }, newSample), { kind: 'sample', file: 3 })

  // changed sample, edited draft
  t('changed sample, edited draft: kept and stale', resolveDraft(draft(mine, digest(oldSample)), newSample), { kind: 'draft', src: digest(oldSample), stale: true })

  // legacy {file, code, base}
  t('legacy draft equal to the current sample: restored, not stale', resolveDraft(draft(newSample), newSample), { kind: 'draft', src: digest(newSample), stale: false })
  t('legacy draft differing from the current sample: kept and stale', resolveDraft(draft(oldSample), newSample), { kind: 'draft', src: '', stale: true })

  // scratch
  t('scratch draft has no sample to go stale', resolveDraft({ file: -1, code: 'x', base: 'x' }, null), { kind: 'draft', src: '', stale: false })
  return fails
}

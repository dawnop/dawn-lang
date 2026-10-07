// Does the Playground page stay as wide as the screen with the compile pane
// open? Measured in a real browser, because no rule about flex shrinking is
// evidence of a width: selftest.ts holds the CSS rules that make it so, this
// holds the width.
//
// Run by hand, not in CI (the docs job has no browser driver, and adding one
// for a layout check would cost more than the check). It needs the built site
// served somewhere and `playwright-core` (`npm i --no-save playwright-core` in
// this directory's parent, which leaves package.json and the lockfile alone):
//
//   PLAY_PAGE=http://127.0.0.1:8000/playground.html \
//   CHROME=/path/to/chrome node test/layout-check.mjs
//
// The compile service is not needed: /api/compile is answered here with a
// canned listing whose lines are far wider than any screen, and with a canned
// compile error whose lines are too, which are the two things that can make a
// page grow sideways. Exit status is the number of widths that were exceeded.
import { chromium } from 'playwright-core'

const page = process.env.PLAY_PAGE
if (!page) throw new Error('set PLAY_PAGE to the built playground page')
const wide = 'x'.repeat(600)

function listing(target) {
  return {
    ok: true, phase: 'compile-view', target, build: 'b1:x', cached: false, ms: 1,
    src: { first: 1, last: 3 }, calls_total: 1, calls_truncated: false,
    calls: [{ id: 0, parent: -1, name: 'println', from: [3, 3], to: [3, 32], nfrom: [3, 3], nto: [3, 10] }],
    pane: {
      kind: target, total: 3, shown: 3,
      truncated: false,
      text: ['int main(void) {', `  ${wide}`, '}'],
      outs: [{ call: 0, lines: [[2, 3]], marks: [], key: [] }],
    },
    gaps: { count: 0, first: [] },
  }
}
const diagnostics = { ok: false, phase: 'compile', output: `error: ${wide}\n  --> prog.dawn:1:1` }

const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {})
let over = 0
for (const [w, h] of [[375, 667], [320, 568], [1280, 800]]) {
  for (const answer of ['listing', 'diagnostics']) {
    const p = await (await browser.newContext({ viewport: { width: w, height: h } })).newPage()
    await p.route('**/api/check', (r) => r.abort())
    await p.route('**/api/compile', async (r) => {
      const target = JSON.parse(r.request().postData() || '{}').target || 'c'
      await r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(answer === 'listing' ? listing(target) : diagnostics) })
    })
    await p.goto(`${page}?view=c`)
    await p.waitForSelector(answer === 'listing' ? '.dp-view .xl' : '.dp-viewerr:not([hidden])')
    if (answer === 'listing') await p.locator('.dp-view .xl[data-o]').first().click()
    const m = await p.evaluate(() => ({ page: document.documentElement.scrollWidth, body: document.body.scrollWidth, screen: innerWidth }))
    const fits = m.page <= m.screen && m.body <= m.screen
    if (!fits) over++
    console.log(`${fits ? '  ok ' : 'FAIL '} ${w}px, ${answer}: page ${m.page}, body ${m.body}, screen ${m.screen}`)
    await p.context().close()
  }
}
await browser.close()
process.exit(over)

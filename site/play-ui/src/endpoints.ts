// The Playground's five service URLs, all derived from the one the page hands
// over in `data-endpoint`.
//
// Kept apart from main.ts so the derivation can be tested without a DOM, and
// kept a derivation rather than four data attributes because the generator
// only ever writes the run URL (site/src/gen/pages.dawn, play_endpoint): one
// attribute cannot disagree with itself, five could. The page may be served
// from a CDN origin while the service sits on another (DAWN_SITE_PLAY_ORIGIN,
// docs/site-cdn-design.md), so the run URL is either relative (`/api/run`) or
// absolute (`https://host/api/run`), and every derived URL is resolved against
// the page here instead of being concatenated onto `location.origin` anywhere.
import { lspWebSocketUrl } from './lsp'

export type PlayEndpoints = {
  run: string
  check: string
  compile: string
  health: string
  lsp: string
}

// `run` must end in `/run`; the siblings replace that last segment, so a path
// or origin in front of it is kept as is. The four HTTP URLs are absolute
// after this, and the LSP one is the same URL with http(s) turned into ws(s).
export function playEndpoints(run: string, baseHref: string): PlayEndpoints {
  if (!/\/run$/.test(run)) throw new Error(`Playground endpoint does not end in /run: ${run}`)
  const at = (seg: string) => new URL(run.replace(/\/run$/, '/' + seg), baseHref).toString()
  return {
    run: at('run'),
    check: at('check'),
    compile: at('compile'),
    health: at('health'),
    lsp: lspWebSocketUrl(run.replace(/\/run$/, '/lsp'), baseHref),
  }
}

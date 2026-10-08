// The doc renderer's XSS surface. A hover or completion doc is Markdown the
// user wrote in their own comment; lsp-client turns it into HTML with `marked`
// (which passes raw HTML through) and assigns it to innerHTML, so everything
// here goes through the same `LSPPlugin.docToHTML` the editor calls, with the
// sanitizer the client was configured with. linkedom stands in for the browser
// DOM (a dev dependency; nothing of it is in the bundle). Each hostile input
// is also run through a client WITHOUT the sanitizer, so the payload is proven
// to be live before the filter is credited with removing it: a test whose
// control stays clean would pass for the wrong reason.
import { LSPClient, LSPPlugin } from '@codemirror/lsp-client'
import { EditorState } from '@codemirror/state'
import { DOMParser, parseHTML } from 'linkedom'
import { DawnLspClient } from '../src/lsp'
import { sanitizeHTML } from '../src/sanitize'

type Expect = (name: string, got: unknown, want: unknown) => void

// Allowed after sanitizing: these elements, and no attribute but a span's class.
const ALLOWED = new Set(['p', 'pre', 'code', 'em', 'strong', 'ul', 'ol', 'li', 'a', 'span', 'br'])

export function sanitizeTests(expect: Expect): number {
  let fails = 0
  const check: Expect = (name, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) fails++
    expect(name, got, want)
  }
  const { document: dom } = parseHTML('<!doctype html><html><body></body></html>')
  const parse = (html: string) => new DOMParser().parseFromString(html, 'text/html') as unknown as Document
  const clean = (html: string) => sanitizeHTML(html, parse)
  // Parsed as a browser would parse what innerHTML is handed: is there an
  // element or attribute a script could ride on? Escaped text is not live,
  // which a regular expression over the string cannot tell.
  const LIVE = {
    test(html: string): boolean {
      const doc = parse(`<!doctype html><html><body>${html}`)
      return [...doc.body.querySelectorAll('*')].some((el) => (
        !ALLOWED.has(el.tagName.toLowerCase())
        || [...el.attributes].some((a) => !(el.tagName === 'SPAN' && a.name === 'class'))
      ))
    },
  }
  const flat = (html: string) => html.replace(/>\n(?=<)/g, '>').replace(/\n$/, '')

  const exact: [string, string, string][] = [
    ['plain text passes', 'just words', 'just words'],
    ['text entities stay escaped', 'a &lt;img src=x onerror=1&gt; b', 'a &lt;img src=x onerror=1&gt; b'],
    ['script element goes with its body', 'a<script>alert(1)</script>b', 'ab'],
    ['upper-case script', '<SCRIPT SRC=//evil/x.js></SCRIPT>ok', 'ok'],
    ['img onerror', '<img src=x onerror=alert(1)>', ''],
    ['on* attribute on an allowed tag', '<p onclick="x()" id=a>hi</p>', '<p>hi</p>'],
    ['javascript: link keeps its label, loses the target', '<a href="javascript:alert(1)">go</a>', '<a>go</a>'],
    ['entity-obfuscated javascript: link', '<a href="jav&#x61;script:alert(1)">go</a>', '<a>go</a>'],
    ['https link loses its target too', '<a href="https://example.test/">site</a>', '<a>site</a>'],
    ['svg onload and nested script', '<svg onload=alert(1)><script>alert(1)</script></svg>x', 'x'],
    ['svg link with xlink:href', '<svg><a xlink:href="javascript:alert(1)"><text>t</text></a></svg>', ''],
    ['svg animate set', '<svg><animate onbegin=alert(1) attributeName=x dur=1s></svg>', ''],
    ['math payload', '<math><mi xlink:href="javascript:alert(1)">x</mi></math>', ''],
    ['iframe srcdoc', '<iframe srcdoc="<script>alert(1)</script>"></iframe>', ''],
    ['object and embed', '<object data="javascript:alert(1)"></object><embed src="x">', ''],
    ['style element', '<style>@import "https://evil/x.css"</style>t', 't'],
    ['style attribute on span', '<span style="background:url(javascript:x)">t</span>', '<span>t</span>'],
    ['span keeps a token class', '<span class="ͼ1 tok-keyword">let</span>', '<span class="ͼ1 tok-keyword">let</span>'],
    ['span class cannot carry an attribute break-out', '<span class="a&quot; onmouseover=&quot;x">t</span>', '<span>t</span>'],
    ['form and button unwrap', '<form action="javascript:x"><button formaction="javascript:y">b</button></form>', 'b'],
    ['noscript attribute trick', '<noscript><p title="</noscript><img src=x onerror=alert(1)>"></p></noscript>', ''],
    ['mXSS: style inside math inside table', '<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>', ''],
    ['base and meta', '<base href="//evil/"><meta http-equiv="refresh" content="0;url=javascript:x">t', 't'],
    ['comment dropped', 'a<!-- <script>alert(1)</script> -->b', 'ab'],
    ['unknown element unwraps, keeps text', '<h2>Head</h2><custom-el onx=1>c</custom-el>', 'Headc'],
    ['nested allowed tags survive', '<ul><li><strong>a</strong> <em>b</em></li></ul>', '<ul><li><strong>a</strong> <em>b</em></li></ul>'],
    ['pre and code lose class', '<pre><code class="language-dawn">let x</code></pre>', '<pre><code>let x</code></pre>'],
    ['br survives', 'a<br>b', 'a<br>b'],
    ['unclosed tags are closed by the parser', '<p><a href=x><em>t', '<p><a><em>t</em></a></p>'],
  ]
  for (const [name, input, want] of exact) check(`sanitize: ${name}`, clean(input), want)
  for (const [name, input] of exact) {
    check(`sanitize: ${name} leaves nothing live`, LIVE.test(clean(input)), false)
  }
  // idempotent: a second pass over the output changes nothing
  check('sanitize is idempotent', exact.every(([, input]) => clean(clean(input)) === clean(input)), true)

  // the client path: marked, then the sanitizer the client was configured with
  const render = (lsp: LSPClient, markdown: string): string => {
    const view = { state: EditorState.create({ doc: '' }) }
    return LSPPlugin.prototype.docToHTML.call({ view, client: lsp } as unknown as LSPPlugin, markdown, 'markdown')
  }
  const configured = (new DawnLspClient('ws://example.test/api/lsp') as unknown as { lsp: LSPClient }).lsp
  const bare = new LSPClient()
  const original = globalThis.DOMParser
  Object.assign(globalThis, { DOMParser })
  try {
    const docs: [string, string][] = [
      ['heading with an onerror image', '## <img src=x onerror=alert(1)>\n\nword'],
      ['raw script in prose', 'Returns a value.\n\n<script>alert(document.cookie)</script>'],
      ['markdown link to javascript:', 'see [the docs](javascript:alert(1))'],
      ['raw anchor with javascript:', '<a href="javascript:alert(1)">x</a>'],
      ['raw svg', '<svg onload=alert(1)><circle r=1 /></svg>'],
      ['inline html in a list', '- one\n- <img src=x onerror=alert(1)>'],
    ]
    for (const [name, markdown] of docs) {
      check(`client control: ${name} is live without the sanitizer`, LIVE.test(render(bare, markdown)), true)
      check(`client: ${name} is clean`, LIVE.test(render(configured, markdown)), false)
    }
    check('client: ordinary doc markup is kept', flat(render(configured, 'Use `map` on a **list**:\n\n- one\n- two\n')),
      '<p>Use <code>map</code> on a <strong>list</strong>:</p><ul><li>one</li><li>two</li></ul>')
    check('client: markup inside a code fence stays text', render(configured, '```dawn\nlet x = "<img src=x onerror=alert(1)>"\n```').includes('&lt;img'), true)
    check('client: a code fence keeps its text, escaped', flat(render(configured, '```\na < b\n```')),
      '<pre><code>a &lt; b\n</code></pre>')
  } finally {
    Object.assign(globalThis, { DOMParser: original })
  }
  return fails
}

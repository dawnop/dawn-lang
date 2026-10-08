// The HTML filter between @codemirror/lsp-client's Markdown renderer and the
// page. The client turns a hover or completion doc into HTML with `marked`
// and assigns it to innerHTML; `marked` passes raw HTML through, and the doc
// is the user's own comment (a Playground share link loads arbitrary code), so
// without this filter a `## <img src=x onerror=...>` line is script execution
// from a link (docs/play-lsp-client-design.md, stage 2). DOMPurify would cost
// 11.4 KiB gzip for a tag set this small, so this is an allow-list copy: the
// input is parsed inertly by DOMParser (no scripts run, no images load), and
// a new tree is built from the
// few elements a doc needs. Nothing is deleted in place, so nothing the walker
// does not understand can survive; an element it does not know is replaced by
// its children (the text stays), and a handful of containers whose text is not
// prose (script, style, svg, ...) go with their contents.
//
// The output is re-serialised from that new tree, so the string handed back
// holds only these tags, the `class` of a <span> (the syntax highlighter's
// token classes) and escaped text. <a> keeps its label and loses `href`: a
// doc link names a path on the server, which no browser tab can open.

const KEEP = new Set(['P', 'PRE', 'CODE', 'EM', 'STRONG', 'UL', 'OL', 'LI', 'A', 'SPAN', 'BR'])

// Elements whose contents are not prose: dropped with everything inside.
const DROP = new Set([
  'SCRIPT', 'STYLE', 'IFRAME', 'FRAME', 'FRAMESET', 'OBJECT', 'EMBED', 'APPLET', 'SVG', 'MATH',
  'TEMPLATE', 'NOSCRIPT', 'TEXTAREA', 'SELECT', 'TITLE', 'HEAD', 'XMP', 'NOEMBED', 'NOFRAMES',
  'AUDIO', 'VIDEO', 'CANVAS', 'LINK', 'META', 'BASE',
])

// Token classes are CodeMirror's generated names (`ͼ1`, `tok-keyword`): word
// characters, hyphens and non-ASCII letters, space separated.
const CLASS = /^[\w\-Ͱ-￿]+(?: [\w\-Ͱ-￿]+)*$/

function copyChildren(from: Node, into: Node, doc: Document): void {
  for (let node = from.firstChild; node != null; node = node.nextSibling) {
    if (node.nodeType === 3) {
      into.appendChild(doc.createTextNode(node.nodeValue ?? ''))
    } else if (node.nodeType === 1) {
      const element = node as Element
      const name = element.tagName.toUpperCase()
      if (DROP.has(name)) continue
      if (KEEP.has(name)) {
        const copy = doc.createElement(name.toLowerCase())
        const cls = name === 'SPAN' ? element.getAttribute('class') : null
        if (cls != null && CLASS.test(cls)) copy.setAttribute('class', cls)
        copyChildren(element, copy, doc)
        into.appendChild(copy)
      } else {
        copyChildren(element, into, doc)
      }
    }
  }
}

/** Parse markup into an inert document; the body holds the nodes. */
export type ParseHTML = (html: string) => Document

const parseInert: ParseHTML = (html) => new DOMParser().parseFromString(html, 'text/html')

export function sanitizeHTML(html: string, parse: ParseHTML = parseInert): string {
  // `<body>` first, so a leading <style>, <meta> or <link> is parsed as body
  // content and reaches the walker instead of vanishing into <head>
  const doc = parse(`<!doctype html><html><body>${html}`)
  const out = doc.createElement('div')
  copyChildren(doc.body, out, doc)
  return out.innerHTML
}

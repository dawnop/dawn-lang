// A document that records instead of rendering.
//
// The bridge takes its document as a parameter, so this is the whole of what
// a headless run needs: six factory/mutation methods and an element that
// remembers what was done to it. Every mutation appends a line to a log, and
// that log is the transcript the contract asserts on.
//
// Recording the *mutations* rather than the patch list is deliberate. A
// transcript of the patches would only say that the guest computed the right
// edits; this says the bridge performed the right edits, which is the half
// that lives in JavaScript and the half a mutant can break silently. The
// patches are in the transcript too, as the reply lines.

export class Recorder {
  constructor() {
    this.lines = [];
  }

  log(line) {
    this.lines.push(line);
  }
}

class StubNode {
  constructor(doc) {
    this.doc = doc;
    this.parentNode = null;
    this.childNodes = [];
    // Whether the node is in the tree under a mount point. Custom element
    // reactions key off transitions of this flag, as they do in a browser.
    this._connected = false;
  }
}

class StubText extends StubNode {
  constructor(doc, value) {
    super(doc);
    this.nodeType = 3;
    this.nodeName = '#text';
    this._value = value;
    doc.rec.log(`create text ${JSON.stringify(value)}`);
  }

  get nodeValue() {
    return this._value;
  }

  set nodeValue(v) {
    this.doc.rec.log(`text ${JSON.stringify(this._value)} -> ${JSON.stringify(v)}`);
    this._value = v;
  }
}

export class StubElement extends StubNode {
  constructor(doc, tag) {
    super(doc);
    this.nodeType = 1;
    this.nodeName = tag;
    this.tagName = tag;
    // Insertion-ordered, which is what makes the transcript stable.
    this._attrs = new Map();
    this._listeners = new Map();
    doc.rec.log(`create <${tag}>`);
  }

  // A browser answers a live NamedNodeMap; the bridge only ever reads a
  // length and an index, so an array of the same shape is enough.
  get attributes() {
    return [...this._attrs.entries()].map(([name, value]) => ({ name, value }));
  }

  getAttribute(name) {
    return this._attrs.has(name) ? this._attrs.get(name) : null;
  }

  setAttribute(name, value) {
    this.doc.rec.log(`attr <${this.tagName}> ${name}=${JSON.stringify(value)}`);
    this._attrs.set(name, value);
  }

  removeAttribute(name) {
    this.doc.rec.log(`unattr <${this.tagName}> ${name}`);
    this._attrs.delete(name);
  }

  addEventListener(name, fn) {
    this.doc.rec.log(`listen <${this.tagName}> ${name}`);
    const fns = this._listeners.get(name) || [];
    fns.push(fn);
    this._listeners.set(name, fns);
  }

  removeEventListener(name, fn) {
    this.doc.rec.log(`unlisten <${this.tagName}> ${name}`);
    const fns = (this._listeners.get(name) || []).filter((f) => f !== fn);
    if (fns.length === 0) this._listeners.delete(name);
    else this._listeners.set(name, fns);
  }

  appendChild(child) {
    this.doc.rec.log(`append ${describe(child)} to <${this.tagName}>`);
    detach(child);
    child.parentNode = this;
    this.childNodes.push(child);
    if (this._connected) connect(child);
    return child;
  }

  // What `move` and `insert` are performed with. A reference of `null` means
  // the end, which is what the DOM says and what the bridge relies on.
  insertBefore(child, ref) {
    const where = ref ? `before ${describe(ref)}` : 'at the end';
    this.doc.rec.log(`insert ${describe(child)} into <${this.tagName}> ${where}`);
    detach(child);
    const i = ref === null || ref === undefined ? this.childNodes.length : this.childNodes.indexOf(ref);
    if (i < 0) throw new Error('insertBefore: the reference is not a child');
    this.childNodes.splice(i, 0, child);
    child.parentNode = this;
    if (this._connected) connect(child);
    return child;
  }

  removeChild(child) {
    this.doc.rec.log(`remove ${describe(child)} from <${this.tagName}>`);
    const i = this.childNodes.indexOf(child);
    if (i < 0) throw new Error('removeChild: not a child');
    this.childNodes.splice(i, 1);
    child.parentNode = null;
    disconnect(child);
    return child;
  }

  replaceChild(fresh, old) {
    this.doc.rec.log(`replace ${describe(old)} with ${describe(fresh)} in <${this.tagName}>`);
    const i = this.childNodes.indexOf(old);
    if (i < 0) throw new Error('replaceChild: not a child');
    detach(fresh);
    this.childNodes[i] = fresh;
    fresh.parentNode = this;
    old.parentNode = null;
    disconnect(old);
    if (this._connected) connect(fresh);
    return old;
  }

  /**
   * Fire what a browser would fire: every listener registered for `name`.
   *
   * `extra` goes on the event object, which is how a case supplies the half of
   * an event that is not the element -- `{ key: 'a' }` for a keystroke. The
   * element half needs nothing: `target` is this element, so a listener that
   * asked for a value reads the one this stub is holding, and a case that
   * wants a different one types into the element first, as a user would.
   */
  fire(name, extra = {}) {
    const fns = this._listeners.get(name) || [];
    if (fns.length === 0) throw new Error(`<${this.tagName}> has no ${name} listener`);
    for (const fn of fns.slice()) {
      fn({ type: name, target: this, preventDefault() {}, ...extra });
    }
  }
}

// An `<input>`, which is the element where the attribute and the property are
// two different things and only one of them is what the user sees.
//
// WHATWG HTML: writing the `value` *content attribute* sets the live value
// only while the control's dirty value flag is false, and that flag is set for
// good the first time the user changes the value. So this stub does what a
// browser does -- `setAttribute('value', ...)` writes through until
// `typeInto()` has been called and is inert afterwards -- and a bridge that
// renders a model into a field with `setAttribute` is one that stops being
// able to correct it after the first keystroke. Nothing raises when it happens,
// which is why it needs an element that models the rule rather than an
// assertion that the right method was called.
class StubInput extends StubElement {
  constructor(doc, tag) {
    super(doc, tag);
    this._value = '';
    this._checked = false;
    this._dirty = false;
  }

  // A browser reflects `type` as a property with `"text"` as the default, and
  // the bridge reads it to decide whether a value is a tick or a string.
  get type() {
    return this._attrs.has('type') ? this._attrs.get('type') : 'text';
  }

  get value() {
    return this._value;
  }

  set value(v) {
    this.doc.rec.log(`prop <${this.tagName}> value=${JSON.stringify(String(v))}`);
    this._value = String(v);
  }

  get checked() {
    return this._checked;
  }

  set checked(v) {
    this.doc.rec.log(`prop <${this.tagName}> checked=${v ? 'true' : 'false'}`);
    this._checked = !!v;
  }

  setAttribute(name, value) {
    super.setAttribute(name, value);
    if (this._dirty) return;
    if (name === 'value') this._value = value;
    if (name === 'checked') this._checked = value !== '' && value !== 'false';
  }

  /**
   * What the user does. The dirty value flag is one way.
   *
   * Not `type`: that name belongs to the content attribute a browser reflects
   * as a property, and the bridge reads it to tell a tick from a string.
   */
  typeInto(text) {
    this._value = String(text);
    this._dirty = true;
  }

  /** The other half of it: a checkbox the user clicked. */
  check(on) {
    this._checked = !!on;
    this._dirty = true;
  }
}

// The tags that hold a live value. `<select>` and `<textarea>` have the same
// split; neither demo reaches one, so they are not modelled rather than
// modelled wrongly.
const INPUTS = new Set(['input']);

function detach(node) {
  if (node.parentNode) {
    const kids = node.parentNode.childNodes;
    const i = kids.indexOf(node);
    if (i >= 0) kids.splice(i, 1);
    node.parentNode = null;
    disconnect(node);
  }
}

// ---- custom element reactions ---------------------------------------------
//
// The two lifecycle transitions, fired in tree order (a parent before its
// children), which is the order the DOM's insertion and removing steps run
// custom element reactions in. The flag makes each transition fire once per
// crossing: a callback that appends a child while running sees the child
// connect immediately through `appendChild`, and the walk below then skips it.
//
// Moving a connected node (`insertBefore` on a node already in the document)
// goes through `detach` first, so it fires disconnected and then connected,
// exactly as a browser does -- a widget that cannot survive that is a widget
// the foreign contract wants to catch.

function connect(node) {
  if (node._connected) return;
  node._connected = true;
  if (typeof node.connectedCallback === 'function') {
    node.doc.rec.log(`connected <${node.tagName}>`);
    node.connectedCallback();
  }
  for (const kid of [...node.childNodes]) connect(kid);
}

function disconnect(node) {
  if (!node._connected) return;
  node._connected = false;
  if (typeof node.disconnectedCallback === 'function') {
    node.doc.rec.log(`disconnected <${node.tagName}>`);
    node.disconnectedCallback();
  }
  for (const kid of [...node.childNodes]) disconnect(kid);
}

function describe(node) {
  return node.nodeType === 3 ? `text ${JSON.stringify(node.nodeValue)}` : `<${node.tagName}>`;
}

export class StubDocument {
  constructor(rec) {
    this.rec = rec;
    // The custom element registry, shaped like the browser's: a class per
    // tag, constructed when `createElement` meets the tag. A stub class
    // extends `StubElement` and may define `connectedCallback` and
    // `disconnectedCallback`; the reactions above dispatch and record them.
    this._customElements = new Map();
    this.customElements = {
      define: (tag, cls) => {
        if (this._customElements.has(tag)) {
          throw new Error(`custom element <${tag}> is already defined`);
        }
        this._customElements.set(tag, cls);
      },
    };
  }

  createElement(tag) {
    const cls = this._customElements.get(tag);
    if (cls) return new cls(this, tag);
    return INPUTS.has(tag) ? new StubInput(this, tag) : new StubElement(this, tag);
  }

  createTextNode(value) {
    return new StubText(this, value);
  }

  /** A detached element to mount into; not part of the tree the guest owns. */
  mountPoint() {
    const el = new StubElement(this, 'main');
    this.rec.lines.pop(); // the mount is scaffolding, not a recorded mutation
    // The mount stands for the live document: what is under it is connected,
    // which is what makes custom element reactions fire under it.
    el._connected = true;
    return el;
  }
}

/** The subtree as HTML-ish text, for the "and this is what it looks like" line. */
export function serialize(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.nodeValue;
  const attrs = [...node._attrs.entries()]
    .map(([k, v]) => ` ${k}="${v}"`)
    .join('');
  // An input's live value is a property, so it is nowhere in `_attrs`, and a
  // tree line without it would not show what the user is looking at.
  const live = node instanceof StubInput ? ` value="${node.value}"` : '';
  const on = [...node._listeners.keys()].sort().map((n) => ` @${n}`).join('');
  const kids = node.childNodes.map(serialize).join('');
  return `<${node.tagName}${attrs}${live}${on}>${kids}</${node.tagName}>`;
}

/** The first element in pre-order whose own text is `label`. */
export function findByText(node, tag, label) {
  if (node.nodeType === 1 && node.tagName === tag && textOf(node) === label) return node;
  for (const kid of node.childNodes) {
    const hit = findByText(kid, tag, label);
    if (hit) return hit;
  }
  return null;
}

function textOf(node) {
  if (node.nodeType === 3) return node.nodeValue;
  return node.childNodes.map(textOf).join('');
}

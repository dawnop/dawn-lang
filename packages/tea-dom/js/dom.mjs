// The other consumer of the reconciler contract.
//
// `tea_term` interprets a patch into terminal cells. This interprets the same
// seven ops into DOM mutations, and that is the whole of the file: an op table
// with seven entries, a builder, and an address walk. There is no eighth op
// and no special case -- if this file ever needs one, the contract in
// `packages/tea-core/src/diff.dawn` is what should have grown, not this.
//
// Three of the seven exist so that an element can survive a change to the list
// it sits in. `move` in particular must move the node the document already
// has: everything the browser is holding inside it -- focus, a caret, a
// selection, a scroll offset, a half-typed IME composition -- is state the
// tree cannot see and a rebuilt element does not have.
//
// Addressing. A `path` is a chain of child indices, and `kids` in the DOM
// vocabulary is exactly an element's children in order, so `path` walks
// `childNodes` and nothing has to be stored on a node to make it addressable.
// The reverse walk matters more: a click arrives at an element, and the
// address is recovered by walking up to the root counting siblings. Recovering
// it beats recording it, because a recorded address is stale the moment a
// sibling is inserted, and an event handler that fires with a stale address
// dispatches the wrong message.
//
// Listeners. One DOM listener per (element, event name) the tree asked for.
// They are tracked in a WeakMap rather than on the element, so a node this
// bridge did not create carries nothing and nothing outlives the document.
//
// Properties, not attributes, for two names. An `<input>` keeps a live value
// beside its `value` content attribute, and the attribute stops writing
// through to the live one as soon as the user touches the control -- WHATWG
// HTML: "When the `value` content attribute is added, set, or removed, if the
// control's dirty value flag is false, the user agent must set the value of
// the element to the value of the `value` content attribute", and the dirty
// value flag "must be set to true whenever the user interacts with the control
// in a way that changes the value". A bridge that only ever calls
// `setAttribute` therefore renders a model into a field exactly once: after
// the first keystroke the model can never correct it again, and nothing
// raises. `checked` has the same split for the same reason.

const LISTENERS = new WeakMap();

// The two names above. Small and closed on purpose: every other property a
// browser exposes is either derived from an attribute or is not something a
// view describes, and a bridge that guessed would be guessing per element.
const PROPERTIES = new Set(['value', 'checked']);

export class DomHost {
  /**
   * `mount` is the element the document is built inside; it is never itself
   * part of the tree, so the tree root is its single child and the empty path
   * addresses that child.
   *
   * `dispatch(path, event)` is called with a recovered address whenever a
   * listened-for event fires. `doc` is the document to create nodes with,
   * and is a parameter so a test can pass a recording stub -- the bridge
   * uses six methods of it and no global.
   */
  constructor(mount, dispatch, doc = globalThis.document) {
    this.mount = mount;
    this.dispatch = dispatch;
    this.doc = doc;
    this.root = null;
  }

  /** Replay a patch list in order, which is the order `diff` emitted it. */
  apply(patches) {
    for (const patch of patches) {
      const op = OPS[patch.op];
      if (!op) throw new Error(`unknown patch op \`${patch.op}\``);
      op(this, patch);
    }
  }

  // ---- addressing ------------------------------------------------------

  /** The DOM node at `path`, or a throw: `diff` never emits a bad address. */
  at(path) {
    let node = this.root;
    for (const i of path) {
      if (!node || !node.childNodes || i >= node.childNodes.length) {
        throw new Error(`no node at address [${path}]`);
      }
      node = node.childNodes[i];
    }
    return node;
  }

  /** The address of `node`, recovered by counting siblings up to the root. */
  addressOf(node) {
    const path = [];
    let cur = node;
    while (cur && cur !== this.root) {
      const parent = cur.parentNode;
      if (!parent) return null;
      const kids = parent.childNodes;
      let i = 0;
      while (i < kids.length && kids[i] !== cur) i++;
      if (i === kids.length) return null;
      path.unshift(i);
      cur = parent;
    }
    return cur === this.root ? path : null;
  }

  // ---- building --------------------------------------------------------

  /** A wire node to a fresh DOM node, listeners and children included. */
  build(node) {
    if (node.t === 'text') return this.doc.createTextNode(node.s);
    const el = this.doc.createElement(node.tag);
    this.setSelf(el, node);
    for (const kid of node.kids) el.appendChild(this.build(kid));
    return el;
  }

  /**
   * A node's own data onto an existing element: the props it should have and
   * no others, the listeners it asked for and no others. Children are not
   * touched, which is what makes this the applier for `set-self` (`apply` is
   * `rekid(donor, kids(target))`, and the donor's children are not part of
   * what it donates).
   *
   * A prop reaches the element as an attribute unless it is one of the two in
   * `PROPERTIES`, which reach it as properties; see the note at the top.
   */
  setSelf(el, node) {
    if (node.t === 'text') {
      el.nodeValue = node.s;
      return;
    }
    const want = new Map(node.props);
    for (const name of attributeNames(el)) {
      if (!want.has(name)) el.removeAttribute(name);
    }
    for (const [name, value] of want) {
      if (PROPERTIES.has(name)) writeProperty(el, name, value);
      else if (el.getAttribute(name) !== value) el.setAttribute(name, value);
    }
    // "and no others" has to hold for the property half too. A property is
    // reset only where the element has one: `'value' in el` is false for a
    // `<div>`, and assigning to it there would invent an expando the document
    // did not have.
    for (const name of PROPERTIES) {
      if (want.has(name) || !(name in el)) continue;
      writeProperty(el, name, '');
    }

    const attached = LISTENERS.get(el) || new Map();
    const wanted = new Set(node.on);
    for (const [name, fn] of attached) {
      if (!wanted.has(name)) {
        el.removeEventListener(name, fn);
        attached.delete(name);
      }
    }
    for (const name of wanted) {
      if (attached.has(name)) continue;
      const fn = (ev) => {
        if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
        const path = this.addressOf(el);
        if (path !== null) this.dispatch(path, name);
      };
      el.addEventListener(name, fn);
      attached.set(name, fn);
    }
    LISTENERS.set(el, attached);
  }

  // ---- the ops ---------------------------------------------------------

  replaceAt(path, node) {
    const fresh = this.build(node);
    if (path.length === 0) {
      if (this.root) this.mount.replaceChild(fresh, this.root);
      else this.mount.appendChild(fresh);
      this.root = fresh;
      return;
    }
    const parent = this.at(path.slice(0, -1));
    parent.replaceChild(fresh, parent.childNodes[path[path.length - 1]]);
  }
}

// The interpretation table. Seven entries, one per `tea_core/diff.Op`.
const OPS = {
  replace: (host, p) => host.replaceAt(p.path, p.node),
  'set-self': (host, p) => host.setSelf(host.at(p.path), p.node),
  append: (host, p) => {
    const el = host.at(p.path);
    for (const node of p.nodes) el.appendChild(host.build(node));
  },
  truncate: (host, p) => {
    const el = host.at(p.path);
    while (el.childNodes.length > p.keep) el.removeChild(el.childNodes[el.childNodes.length - 1]);
  },
  insert: (host, p) => {
    const el = host.at(p.path);
    // `at` is a position in the list after the insert, so `at === length` is
    // the end and `insertBefore(node, null)` is what the DOM calls that.
    el.insertBefore(host.build(p.node), el.childNodes[p.at] ?? null);
  },
  remove: (host, p) => {
    const el = host.at(p.path);
    el.removeChild(el.childNodes[p.at]);
  },
  // Never a removal and a rebuild. `insertBefore` on a node that is already in
  // the document moves it, and moving is the whole reason this op exists.
  //
  // The reference child is read off the list as it is *now*, with the moving
  // node still in it, while `to` counts positions in the list as it will be.
  // So a node travelling right skips over itself and needs `to + 1`; a node
  // travelling left does not. Getting this wrong puts the element one place
  // off and raises nothing.
  move: (host, p) => {
    const el = host.at(p.path);
    const node = el.childNodes[p.from];
    const settled = el.childNodes.length - 1;
    const ref = p.to >= settled ? null : el.childNodes[p.to < p.from ? p.to : p.to + 1];
    el.insertBefore(node, ref);
  },
};

// A prop is a pair of strings, and `checked` is a boolean, so the two meet
// here. Presence means checked, which is the attribute's own rule, and the two
// spellings a view would reach for to say otherwise are honoured rather than
// read as truthy.
function writeProperty(el, name, value) {
  const next = name === 'checked' ? value !== '' && value !== 'false' : value;
  if (el[name] !== next) el[name] = next;
}

// `el.attributes` is a live NamedNodeMap in a browser and whatever a stub
// wants elsewhere; both answer to a length and an index, and copying the
// names out first is required in a browser anyway, since removing an
// attribute mutates the collection being iterated.
function attributeNames(el) {
  const attrs = el.attributes;
  if (!attrs) return [];
  const names = [];
  for (let i = 0; i < attrs.length; i++) names.push(attrs[i].name);
  return names;
}

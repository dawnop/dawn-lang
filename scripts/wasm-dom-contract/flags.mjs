// The host half of an init's flags, at the bridge, with no wasm and no
// browser.
//
// Why this exists separately from the two transcripts. Flags are the one
// string the page knows and the guest does not, and the only turn that can
// carry them is the first one. Neither demo application takes any -- both
// start from a constant -- so a transcript of either is byte-identical
// whether the bridge sends the field, drops it, or invents one. What the
// three assertions below are about is the request line itself.
//
//   1. `Reactor.init()` sends the line every host has always sent, with no
//      `flags` key at all: absent and empty are different answers here, for
//      the reason they are different for an event's payload, and the guest
//      can only tell them apart if the host keeps them apart
//   2. `Reactor.init(text)` carries the text verbatim, the empty string
//      included, since only the page can know whether "" meant something
//   3. `mount(wasm, el, { flags })` hands its flags to that first turn, and
//      omits them when the caller did not pass any -- the plumbing between
//      the page's option bag and the wire, which is the piece a page actually
//      touches
//
// The guest half is the other leg of flags.sh: a session over
// examples/projects/tea_dom_flags, held to the pin in
// scripts/example-main-contract/registry.json.
//
// Run it through flags.sh, which adds the mutants; run.sh calls that.

import { mount } from '../../packages/tea-dom/js/app.mjs';
import { Reactor } from '../../packages/tea-dom/js/reactor.mjs';
import { Recorder, StubDocument } from './domstub.mjs';

let failures = 0;

function check(what, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) {
    console.log(`OK   ${what}`);
  } else {
    console.log(`FAIL ${what}\n  got  ${g}\n  want ${w}`);
    failures += 1;
  }
}

// One init line, without a wasm module: `Reactor.init` is the only thing
// between a page's argument and the bytes, and the constructor holds nothing
// but its two arguments.
function initLine(...args) {
  const reactor = new Reactor(null, null);
  let seen = null;
  reactor.request = (req) => {
    seen = req;
    return { ok: true, model: 'M', patches: [] };
  };
  reactor.init(...args);
  return seen;
}

// ---- 1. no flags, no field ------------------------------------------------
{
  // The key list and not the object: `JSON.stringify` drops a key whose value
  // is `undefined`, so an object comparison would report a line that does
  // carry the field as one that does not.
  check('an init with no flags is the line every host already sends',
    Object.keys(initLine()), ['op']);
  check('and it is an init', initLine(), { op: 'init' });
}

// ---- 2. flags are carried verbatim ----------------------------------------
{
  check('an init with flags carries them', initLine('{"name":"dawn"}'), {
    op: 'init',
    flags: '{"name":"dawn"}',
  });
  // Opaque: the bridge never parses what it is handed, so a string that is
  // not JSON crosses exactly as one that is.
  check('and does not read them', initLine('not json at all'), {
    op: 'init',
    flags: 'not json at all',
  });
  check('an empty flag is carried rather than dropped', initLine(''), {
    op: 'init',
    flags: '',
  });
}

// ---- 3. mount's option reaches the first turn -----------------------------
//
// `Reactor.load` is replaced rather than given a module: what is under test is
// the wiring between `mount`'s option bag and the first request, and a real
// instance would need a wasm toolchain this leg deliberately does not have.
// What is recorded is the whole argument list rather than the first argument,
// because "called with `undefined`" and "called with nothing" are the two
// answers this leg has to keep apart and they are the same value.
async function initArgsFor(options) {
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const asked = [];
  const real = Reactor.load;
  Reactor.load = async () => ({
    init(...args) {
      asked.push(args);
      return { ok: true, model: 'M', patches: [] };
    },
    event() {
      return { ok: true, model: 'M', patches: [] };
    },
  });
  try {
    await mount(null, doc.mountPoint(), { doc, ...options });
  } finally {
    Reactor.load = real;
  }
  return asked;
}

check('mount hands its flags to the first turn',
  await initArgsFor({ flags: '{"name":"dawn"}' }), [['{"name":"dawn"}']]);
check('and still calls init with one argument when the page named none',
  await initArgsFor({}), [[undefined]]);

if (failures !== 0) {
  console.log(`FAIL: ${failures} assertion(s)`);
  process.exit(1);
}
console.log('tea-dom flags ok');

// The page's half of the search panel: a button, a keyboard shortcut, and a
// lazy mount. Everything a reader sees inside the panel is drawn by a wasm
// reactor built from examples/projects/tea_dom_search; nothing here knows what
// a result is.
//
// A classic script and not a module, so that it runs on every page without a
// second network request and without `type=module`'s deferred-only semantics
// mattering. The bridge it loads IS a module, reached with a dynamic import
// once the reader has asked for the panel.
//
// Lazy is the whole point of the file. The reactor is ~150KB gzipped and the
// index is tens of kilobytes; a reader who never searches must not pay for
// either, so nothing is fetched until the button is pressed or the shortcut is
// used. That also makes the failure case cheap: on a checkout with no wasm
// toolchain the reactor is a placeholder, the mount throws, and the page is
// exactly the page it was with one line of text in the panel.
//
// The three URLs and the page's own distance from the site root arrive as data
// attributes on the button, because gen/links.dawn checks markup and cannot
// read a string inside a program.
(function () {
  'use strict';

  var btn = document.querySelector('.search-open');
  var host = document.getElementById('dawn-search');
  if (!btn || !host) return;

  // On anything but a Mac the hint is Ctrl. Rewritten here rather than
  // generated, because the generator writes one document for every reader and
  // this is a fact about the machine in front of one of them.
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  if (!isMac) {
    var hint = btn.querySelector('kbd');
    if (hint) hint.textContent = 'Ctrl K';
  }

  var mounted = null; // the promise, so a second press does not mount twice
  var app = null; // { reactor, host, dispatch }
  var flags = null;

  function fail(message) {
    host.textContent = message;
  }

  async function boot() {
    var d = btn.dataset;
    var bridge = await import(d.searchApp);
    var responses = await Promise.all([fetch(d.searchWasm), fetch(d.searchIndex)]);
    if (!responses[0].ok || !responses[1].ok) {
      throw new Error('search: the reactor or the index could not be fetched');
    }
    var index = await responses[1].text();
    // String concatenation and not a re-serialised object: the index is
    // already JSON and parsing it here only to print it again would double the
    // work and could not improve on the bytes.
    flags = '{"root":' + JSON.stringify(d.searchRoot) + ',"index":' + index + '}';
    app = await bridge.mount(responses[0], host, {
      flags: flags,
      onError: function (reply) {
        fail(reply.kind + ': ' + reply.error);
      },
    });
    return app;
  }

  function focusInput() {
    var field = host.querySelector('.search-input');
    if (field) field.focus();
  }

  function open() {
    host.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    if (!mounted) {
      mounted = boot().catch(function (e) {
        fail(String(e));
        // A failed mount is not retried on the next press: the reactor is
        // missing or broken, and asking for it again would be one more failed
        // request per keystroke.
        app = null;
        return null;
      });
    } else if (app) {
      // Escape leaves the guest with an empty tree, so reopening is a fresh
      // init from the flags the page still holds -- one turn, no refetch.
      var reply = app.reactor.init(flags);
      if (reply.ok) app.host.apply(reply.patches);
    }
    mounted.then(focusInput);
  }

  function close() {
    host.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  }

  btn.addEventListener('click', function () {
    if (host.hidden) open();
    else close();
  });

  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      if (host.hidden) open();
      else close();
      return;
    }
    if (host.hidden) return;
    // The guest's own listener has already run and the patch is already in the
    // document, because a turn is synchronous inside the DOM event that
    // started it. So the answer to "where did Enter mean to go" is a question
    // about the document, and the guest never has to be handed a URL bar.
    var go = host.querySelector('a[data-goto]');
    if (go) {
      close();
      window.location.assign(go.href);
      return;
    }
    if (ev.key === 'Escape') close();
  });
})();

// The page's half of the search panel: a button, a keyboard shortcut, and a
// lazy mount. Everything a reader sees inside the panel is drawn by a wasm
// reactor built from examples/projects/tea_dom_search; nothing here knows what
// a result is.
//
// What is here is what a dialog owes the document around it, which the guest
// cannot reach: the scrim, focus (kept inside while open, handed back to the
// button on close), and the scroll position that keeps the selected row in
// view. None of it says a word to the reader, so none of it needs a language.
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

  // Not the panel, but where the panel's results land. An entry inside a
  // closed <details> (the stdlib page folds std/gpu's reference kernels into
  // one) stays hidden when a link or a search result names it, in every
  // browser that does not reveal such a target itself. So every <details>
  // around the target is opened first, and the target is scrolled to once it
  // has a box to scroll to.
  function reveal() {
    var id;
    try {
      id = decodeURIComponent(location.hash.slice(1));
    } catch (e) {
      return;
    }
    var el = id && document.getElementById(id);
    if (!el) return;
    var opened = false;
    for (var d = el.parentElement; d; d = d.parentElement) {
      if (d.tagName === 'DETAILS' && !d.open) {
        d.open = true;
        opened = true;
      }
    }
    if (opened) el.scrollIntoView();
  }
  window.addEventListener('hashchange', reveal);
  reveal();

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
    // The data attributes are page-relative ("./assets/..." or "../assets/...").
    // fetch() resolves those against the document, but dynamic import() resolves
    // against THIS module's URL, which already lives under /assets/ -- the raw
    // attribute would load /assets/assets/... (the first production failure of
    // this panel, 2026-08-31). Resolve all three against the document instead.
    var abs = function (u) { return new URL(u, document.baseURI).href; };
    var bridge = await import(abs(d.searchApp));
    var responses = await Promise.all([fetch(abs(d.searchWasm)), fetch(abs(d.searchIndex))]);
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

  // Focus goes back where it came from: the button that opened the panel.
  function close() {
    host.hidden = true;
    host.classList.remove('is-keying');
    btn.setAttribute('aria-expanded', 'false');
    btn.focus({ preventScroll: true });
  }

  // Whether the guest has left: it answers an empty tree for the second
  // Escape and for its Cancel button, and the page follows by hiding the
  // host. No panel at all is a mount that failed or has not finished, which
  // Escape also closes.
  function guestLeft() {
    var panel = host.querySelector('.search-panel');
    return !panel || panel.classList.contains('is-closed');
  }

  // The selected row, kept in view. The guest owns which row that is; where
  // the list is scrolled to is a fact about this document.
  function follow() {
    var row = host.querySelector('.search-row.is-selected');
    if (row) row.scrollIntoView({ block: 'nearest' });
  }

  // What Tab can reach inside the panel: the field, and the Cancel button
  // where it is shown. The rows are out of the tab order on purpose (the
  // arrows move through them), and a hidden element has no client rects.
  function focusables() {
    return Array.prototype.filter.call(
      host.querySelectorAll('input, button, a[href]:not([tabindex="-1"])'),
      function (el) { return el.getClientRects().length > 0; }
    );
  }

  btn.addEventListener('click', function () {
    if (host.hidden) open();
    else close();
  });

  // The host is the scrim. A click on it, outside the panel, closes; a click
  // inside has already been heard by the guest, and if that was Cancel the
  // guest has left. A row is a link and the browser follows it; the panel
  // closes so that a link into this same page does not leave it open.
  host.addEventListener('click', function (ev) {
    var row = ev.target.closest && ev.target.closest('.search-row a');
    if (ev.target === host || guestLeft() || row) close();
  });

  host.addEventListener('mousemove', function () {
    host.classList.remove('is-keying');
  });

  host.addEventListener('input', follow);

  // The panel is modal: focus that lands outside it while it is open is
  // brought back to the field.
  document.addEventListener('focusin', function (ev) {
    if (!host.hidden && !host.contains(ev.target)) focusInput();
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
    if (ev.key === 'Escape') {
      // The guest hears Escape only in its field, and there the first press
      // empties the query and leaves the panel open.
      var heard = ev.target && ev.target.classList && ev.target.classList.contains('search-input');
      if (!heard || guestLeft()) close();
      return;
    }
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      // Not the caret's move to either end of the field: the arrows are the
      // list's while the panel is open.
      ev.preventDefault();
      host.classList.add('is-keying');
      follow();
      return;
    }
    if (ev.key === 'Tab') {
      var f = focusables();
      if (!f.length) return;
      var i = f.indexOf(document.activeElement);
      if (ev.shiftKey && i <= 0) {
        ev.preventDefault();
        f[f.length - 1].focus();
      } else if (!ev.shiftKey && (i === -1 || i === f.length - 1)) {
        ev.preventDefault();
        f[0].focus();
      }
    }
  });
})();

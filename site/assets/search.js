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
//
// Two pieces of state outlive one opening of the panel, and both are the
// page's because the guest can reach neither. The query is in the address as
// `?q=` while the panel is open (replaceState, so typing is not history), and a
// page loaded with one opens on its results: a search can be shared as a
// link. `?q=` and not `#q=` because the fragment on this site is an anchor --
// headings, API entries, the Playground's code -- and reveal() below reads it
// as one. The reader's recent queries are in localStorage. Both reach the
// guest as flags, and the guest only reads them.
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
  var index = null; // the index text, kept to build flags again on reopen

  function fail(message) {
    host.textContent = message;
  }

  // ---- recent queries ------------------------------------------------------
  //
  // Newest first, deduplicated, at most five, under one key. Every read and
  // write is guarded: storage can be absent, full or refused (a private
  // window, blocked site data), and a panel without history is still a panel.
  var RECENT_KEY = 'dawn-search-recent';
  var RECENT_MAX = 5;

  function readRecent() {
    try {
      var list = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
      if (!Array.isArray(list)) return [];
      return list.filter(function (q) {
        return typeof q === 'string' && q.trim() !== '';
      }).slice(0, RECENT_MAX);
    } catch (e) {
      return [];
    }
  }

  function writeRecent(list) {
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
    } catch (e) {
      // nothing to do: the list simply does not persist
    }
  }

  function remember(query) {
    var q = (query || '').trim();
    if (!q) return;
    writeRecent([q].concat(readRecent().filter(function (r) { return r !== q; })));
  }

  // ---- the query in the address --------------------------------------------

  function queryInUrl() {
    try {
      return new URLSearchParams(location.search).get('q') || '';
    } catch (e) {
      return '';
    }
  }

  // The address follows the field: `?q=` while there is a query, nothing when
  // there is not. replaceState, so a reader's Back button is not a list of
  // every prefix they typed; the rest of the URL (path, other parameters,
  // fragment) is left as it was.
  function writeQuery(q) {
    try {
      var url = new URL(location.href);
      if (q) url.searchParams.set('q', q);
      else url.searchParams.delete('q');
      if (url.href !== location.href) history.replaceState(history.state, '', url.href);
    } catch (e) {
      // an address that cannot be rewritten (a file: page in some browsers)
      // is one where the query is simply not shared
    }
  }

  function field() {
    return host.querySelector('.search-input');
  }

  // Called after every turn the page can see: the guest writes the field
  // (Escape empties it, a recent query fills it) without an input event.
  function syncQuery() {
    if (host.hidden) return;
    var f = field();
    if (f) writeQuery(f.value.trim() ? f.value : '');
  }

  // What the guest is told when it starts: where the page is, which modifier
  // this keyboard has, the query a shared link carried, the recent queries,
  // and the index. String concatenation and not a re-serialised object: the
  // index is already JSON and parsing it here only to print it again would
  // double the work and could not improve on the bytes.
  function flagsFor(q) {
    return '{"root":' + JSON.stringify(btn.dataset.searchRoot)
      + ',"mod":' + JSON.stringify(isMac ? '\u2318' : 'Ctrl')
      + ',"q":' + JSON.stringify(q || '')
      + ',"recent":' + JSON.stringify(readRecent())
      + ',"index":' + index + '}';
  }

  // A fresh guest from new flags: one turn, no refetch.
  function restart(q) {
    var reply = app.reactor.init(flagsFor(q));
    if (reply.ok) app.host.apply(reply.patches);
  }

  async function boot(q) {
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
    index = await responses[1].text();
    app = await bridge.mount(responses[0], host, {
      flags: flagsFor(q),
      onError: function (reply) {
        fail(reply.kind + ': ' + reply.error);
      },
    });
    return app;
  }

  function focusInput() {
    var f = field();
    if (f) f.focus();
  }

  // `q` is the query to open on: a shared link's, or none.
  function open(q) {
    host.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    if (!mounted) {
      mounted = boot(q).catch(function (e) {
        fail(String(e));
        // A failed mount is not retried on the next press: the reactor is
        // missing or broken, and asking for it again would be one more failed
        // request per keystroke.
        app = null;
        return null;
      });
    } else if (app) {
      // Escape leaves the guest with an empty tree, so reopening is a fresh
      // init -- with the recent queries as they are now.
      restart(q);
    }
    mounted.then(focusInput);
  }

  // Focus goes back where it came from: the button that opened the panel.
  function close() {
    writeQuery('');
    host.hidden = true;
    host.classList.remove('is-keying');
    btn.setAttribute('aria-expanded', 'false');
    btn.focus({ preventScroll: true });
  }

  // A result in a new tab, for Cmd-Enter or Ctrl-Enter. A real link with a
  // target, clicked, and not window.open: the click is inside the keydown
  // that asked for it, so it carries the reader's activation, and a link is
  // what the browser already knows how to open beside the page.
  function newTab(href) {
    var a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
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
    if (host.hidden) open('');
    else close();
  });

  // Forgetting a recent query. The guest's delete and Clear buttons have no
  // listener; they name what to forget in a data attribute, and this writes
  // the stored list and starts the guest again from it.
  //
  // A restart rather than a message carrying the new list back in, because
  // there is no way in for one: a message reaches the guest only through a
  // listener in its own tree, or as flags at init. Keeping the list in the
  // flags keeps it out of the model, so it never crosses the wire on a
  // keystroke, and leaves one writer of the stored list -- this script. The
  // restart costs one init (the index is parsed again), on a click that
  // happens rarely, with an empty field and so nothing else to lose.
  function forget(ev) {
    var one = ev.target.closest && ev.target.closest('[data-forget]');
    var all = ev.target.closest && ev.target.closest('[data-forget-all]');
    if (!app || (!one && !all)) return false;
    if (all) writeRecent([]);
    else {
      var q = one.getAttribute('data-forget');
      writeRecent(readRecent().filter(function (r) { return r !== q; }));
    }
    restart('');
    focusInput();
    return true;
  }

  // The host is the scrim. A click on it, outside the panel, closes; a click
  // inside has already been heard by the guest, and if that was Cancel the
  // guest has left. A row is a link and the browser follows it; the panel
  // closes so that a link into this same page does not leave it open, and
  // the query that found it is remembered.
  host.addEventListener('click', function (ev) {
    if (forget(ev)) return;
    var row = ev.target.closest && ev.target.closest('.search-row a');
    if (row) {
      var f = field();
      if (f) remember(f.value);
    }
    if (ev.target === host || guestLeft() || row) close();
    else syncQuery();
  });

  // A scope pill is a button, and a pressed button takes focus; the field
  // has to keep it, or the arrows and Enter stop reaching the guest after a
  // click. The click itself still happens.
  host.addEventListener('mousedown', function (ev) {
    if (ev.target.closest && ev.target.closest('.search-pill')) ev.preventDefault();
  });

  host.addEventListener('mousemove', function () {
    host.classList.remove('is-keying');
  });

  host.addEventListener('input', function () {
    follow();
    syncQuery();
  });

  // The panel is modal: focus that lands outside it while it is open is
  // brought back to the field.
  document.addEventListener('focusin', function (ev) {
    if (!host.hidden && !host.contains(ev.target)) focusInput();
  });

  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      if (host.hidden) open('');
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
      var f = field();
      if (f) remember(f.value);
      close();
      if (ev.metaKey || ev.ctrlKey) newTab(go.href);
      else window.location.assign(go.href);
      return;
    }
    if (ev.key === 'Escape') {
      // The guest hears Escape only in its field, and there the first press
      // empties the query and leaves the panel open.
      var heard = ev.target && ev.target.classList && ev.target.classList.contains('search-input');
      if (!heard || guestLeft()) close();
      else syncQuery();
      return;
    }
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp' || ev.key === 'Home' || ev.key === 'End') {
      // Not the caret's move to either end of the field: the arrows, Home and
      // End are the list's while the panel is open.
      ev.preventDefault();
      host.classList.add('is-keying');
      follow();
      return;
    }
    if (ev.key === 'Enter') {
      // Enter on a recent query fills the field rather than leaving.
      syncQuery();
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

  // A page opened from a shared link opens on its query.
  var shared = queryInUrl();
  if (shared.trim()) open(shared);
})();

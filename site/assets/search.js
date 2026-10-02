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
// The reactor does not run on this page's thread. It runs in a module worker
// (packages/tea-dom/js/worker.mjs), and the page keeps only the document:
// the bridge's `Remote` applies the patches a turn sends back. Compiling the
// module, init (which parses the indexes, a few hundred milliseconds on a slow
// machine once the text index is in) and every keystroke's turn are therefore
// time the page can spend painting and taking the next key. The price is that
// a turn is no longer finished when the DOM event that caused it returns, so
// what this script used to read off the document right after an event --
// whether Enter chose a link, whether the guest has left -- it now reads in
// `afterTurn`, which the bridge calls once each reply is in the document. See
// docs/site-search-design.md, section 12, for the measurements and for why
// there is no main-thread fallback.
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
// The documents' text is a second index (search-body-<lang>.json, named by
// `data-search-body` on the panel's host), about a hundred kilobytes gzipped,
// and it is lazier still: it is fetched the first time the field holds a
// query, not when the panel opens. Not on an idle timer after opening either,
// because a reader who opens the panel to pick a recent search or a
// suggestion, or to close it again, never needs the text, and the first
// characters of a query are answered from the titles while the text is on
// its way. Once it is here and says it is format 1, the guest is started
// again with it in the flags (see restart below for why that and not a
// message); a fetch that fails or an asset of another format leaves the
// panel searching titles, which its foot says.
//
// Two pieces of state outlive one opening of the panel, and both are the
// page's because the guest can reach neither. A page loaded with `?q=` opens
// on that query's results, so a search can be shared as a link, and the link
// is made when the reader asks for it: the foot's Copy link writes `?q=` into
// the address (replaceState, so it is not history) and copies the address.
// Typing does not touch the address -- an address that changed with every
// keystroke was a link nobody had asked for, and the one in the bar when the
// reader copied it by hand was whatever prefix they had reached -- and
// closing the panel takes `?q=` out again. `?q=` and not `#q=` because the
// fragment on this site is an anchor -- headings, API entries, the
// Playground's code -- and reveal() below reads it as one. The reader's recent
// queries are in localStorage. Both reach the guest as flags, and the guest
// only reads them.
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

  var warming = null; // the promise of the loaded worker and the title index
  var mounted = null; // the promise, so a second press does not mount twice
  var app = null; // { host, dispatch, init }
  var goNewTab = false; // whether the last key the panel heard asked for a new tab
  var index = null; // the index text, kept to build flags again on reopen
  var body = null; // the body index text, once fetched and found to be format 1
  var bodyAsked = false; // so the body index is fetched once per page
  var guestHasBody = false; // whether the running guest was started with it

  // The data attributes are page-relative ("./assets/..." or "../assets/...").
  // fetch() resolves those against the document, but dynamic import() resolves
  // against THIS module's URL, which already lives under /assets/ -- the raw
  // attribute would load /assets/assets/... (the first production failure of
  // this panel, 2026-08-31). Resolve every one against the document instead.
  function abs(u) {
    return new URL(u, document.baseURI).href;
  }

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

  // `?q=` set to a query, or taken out for none. Called with the field's
  // query by Copy link and with none on close, and from nowhere else: typing
  // leaves the address alone. replaceState, so the link a reader copied is not
  // also a history entry; the rest of the URL (path, other parameters,
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

  // ---- copy link -----------------------------------------------------------
  //
  // The guest's Copy link button has no listener, like delete and Clear: it
  // names itself with `data-copy-link`, and this does the rest, because the
  // address and the clipboard are the page's. The query goes into the address
  // first and the address is what is copied, so the link in the clipboard and
  // the one in the bar are the same link.
  //
  // What the reader is told is the guest's words in the page's hands. Both
  // labels and a status line are already in the guest's tree, in the page's
  // language; `is-copied` on the host (the page's element, as `is-keying` is)
  // makes the stylesheet show "Copied" on the button and the status line,
  // which a screen reader announces, and a moment later it is taken off. Not a
  // message to the guest: a message reaches it only through a listener in its
  // own tree, a listener would claim the copy before the clipboard had
  // answered, and the guest has no clock to take the word back with.
  //
  // A clipboard that is missing or refuses (no permission, an insecure origin)
  // gets the address in a read-only field under the panel, selected, for the
  // reader to copy themselves: no alert, and no words of this script's own --
  // the field is labelled by the button.
  var copiedTimer = null;

  function uncopied() {
    clearTimeout(copiedTimer);
    host.classList.remove('is-copied');
    var manual = host.querySelector('.search-copy-manual');
    if (manual) manual.remove();
  }

  function copied() {
    uncopied();
    host.classList.add('is-copied');
    copiedTimer = setTimeout(function () { host.classList.remove('is-copied'); }, 1600);
  }

  function copyByHand(href) {
    uncopied();
    var box = document.createElement('input');
    box.type = 'text';
    box.readOnly = true;
    box.value = href;
    box.className = 'search-copy-manual';
    box.setAttribute('aria-labelledby', 'dawn-search-copy');
    host.appendChild(box);
    box.focus({ preventScroll: true });
    box.select();
  }

  function copyLink(ev) {
    var b = ev.target.closest && ev.target.closest('[data-copy-link]');
    if (!b) return false;
    var f = field();
    var q = f ? f.value : '';
    if (!q.trim()) return true;
    writeQuery(q);
    var href = location.href;
    var clip = navigator.clipboard;
    // The clipboard answers later; a query typed meanwhile is a different
    // search, and the word for this one no longer belongs on screen.
    var still = function () {
      var g = field();
      return !host.hidden && g && g.value === q;
    };
    if (clip && clip.writeText) {
      clip.writeText(href).then(function () {
        if (still()) copied();
      }, function () {
        if (still()) copyByHand(href);
      });
    } else {
      copyByHand(href);
    }
    return true;
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
      + ',"index":' + index
      + (body ? ',"body":' + body : '') + '}';
  }

  // A fresh guest from new flags: one turn, no refetch. The promise is
  // settled once the new document is in place.
  //
  // This is also how the body index gets in. There is no message that could
  // carry it: a message reaches the guest only through a listener in its own
  // tree, and a message's data would be part of the model, which crosses the
  // wire on every keystroke -- three hundred kilobytes each way. Flags are
  // read once, by init, into the guest's retained state, which never crosses.
  // The price is one init that parses both indexes again; it is measured in
  // docs/site-search-design.md.
  //
  // init draws a new field, and the turn takes a while on the worker (a
  // quarter of a second with the text index on a fast machine), during which
  // the reader may go on typing -- or press Enter, or an arrow. Those land in
  // the old field, and their turns are dropped by the bridge once the old
  // field has left the document, since their address would name an element
  // in a tree that no longer exists. So when the old field has focus as the
  // restart is asked for, what happens to it until the new field arrives is
  // written down -- each key, and each value it took -- and played to the new
  // field in the same order, with focus and caret carried over. The replayed
  // events do not bubble: the page's own handlers have heard the originals,
  // and only the guest's listener on the field has not. The selection goes
  // back to the first row, which is where typing leaves it anyway.
  function restart(q) {
    guestHasBody = !!body;
    var f = field();
    var kept = !!f && document.activeElement === f;
    var heard = [];
    var onKey = function (ev) {
      if (ev.isTrusted) heard.push({ key: ev.key });
    };
    var onInput = function (ev) {
      if (ev.isTrusted) heard.push({ value: f.value });
    };
    if (kept) {
      f.addEventListener('keydown', onKey);
      f.addEventListener('input', onInput);
    }
    return app.init(flagsFor(q)).then(function () {
      if (!kept) return;
      f.removeEventListener('keydown', onKey);
      f.removeEventListener('input', onInput);
      var g = field();
      if (!g || g === f) return;
      g.focus({ preventScroll: true });
      heard.forEach(function (h) {
        if (h.key !== undefined) {
          g.dispatchEvent(new KeyboardEvent('keydown', { key: h.key }));
        } else {
          g.value = h.value;
          g.dispatchEvent(new Event('input'));
        }
      });
      try {
        g.setSelectionRange(f.selectionStart, f.selectionEnd);
      } catch (e) {
        // a field that takes no selection keeps the caret where focus put it
      }
    }, function (e) {
      fail(String(e));
      app = null;
    });
  }

  // The body index has arrived while the reader is typing: the guest is
  // started again on the field as it is now (restart keeps what is typed
  // meanwhile).
  function takeBody() {
    if (!app || host.hidden || guestHasBody) return;
    var f = field();
    restart(f ? f.value : '').then(follow);
  }

  // Fetch the body index, once. Anything short of a format 1 asset leaves
  // `body` empty and the guest as it is.
  function wantBody() {
    if (bodyAsked) return;
    bodyAsked = true;
    var url = host.dataset.searchBody;
    if (!url) return;
    fetch(abs(url))
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (text) {
        if (!text) return;
        var v = JSON.parse(text);
        if (!Array.isArray(v) || v[0] !== 1) return;
        body = text;
        if (mounted) mounted.then(takeBody);
      })
      .catch(function () {
        // no text index: the panel goes on searching titles and says so
      });
  }

  // Everything the panel needs before it can draw, and nothing it draws: the
  // worker started on its module, the page's half of the bridge, the reactor
  // compiled and instantiated on the worker's thread, and the title index.
  // All four are asked for at once rather than one after another; the module
  // graphs are one file each for the same reason (gen/pages.emit_bridge).
  // Started by the click, or earlier by a pointer or focus arriving on the
  // button -- a reader who is about to press it has said so -- and at most
  // once per page, a failure included.
  //
  // The worker's own failure to load is an `error` event, which can fire
  // before the bridge is here to listen for it; it is held until then.
  function warm() {
    if (warming) return warming;
    var d = btn.dataset;
    warming = (async function () {
      if (typeof Worker !== 'function') throw new Error('search: this browser cannot run the search in a worker');
      var early = null;
      var worker = new Worker(abs(d.searchWorker), { type: 'module' });
      worker.onerror = function (ev) {
        early = ev;
      };
      var bridgeP = import(abs(d.searchApp));
      var wasmP = fetch(abs(d.searchWasm));
      var indexP = fetch(abs(d.searchIndex));
      var bridge = await bridgeP;
      var remote = new bridge.Remote(worker);
      if (early) throw new Error('search: the worker could not be started');
      var wasm = await wasmP;
      if (!wasm.ok) throw new Error('search: the reactor could not be fetched');
      var loaded = remote.load(wasm);
      var res = await indexP;
      if (!res.ok) throw new Error('search: the index could not be fetched');
      var text = await res.text();
      await loaded;
      return { remote: remote, index: text };
    })();
    return warming;
  }

  function prewarm() {
    warm().catch(function () {
      // reported by the click that needs it, if one comes
    });
  }

  async function boot(q) {
    var w = await warm();
    index = w.index;
    guestHasBody = !!body;
    app = await w.remote.mount(host, {
      flags: flagsFor(q),
      onError: function (reply) {
        fail(reply.kind + ': ' + reply.error);
      },
      onTurn: afterTurn,
    });
    return app;
  }

  // What the page reads off the document once a turn's patches are in it.
  // Enter's choice is a link with `data-goto`, which the guest draws and the
  // page follows; a guest that has left (the second Escape, Cancel) is a panel
  // the page closes. Before the reactor moved to a worker both were read in
  // the keydown or click that caused the turn, when the turn was already over.
  function afterTurn() {
    if (host.hidden) return;
    follow();
    var go = host.querySelector('a[data-goto]');
    if (go) {
      var f = field();
      if (f) remember(f.value);
      close();
      if (goNewTab) newTab(go.href);
      else window.location.assign(go.href);
      return;
    }
    if (guestLeft()) close();
  }

  function focusInput() {
    var f = field();
    if (f) f.focus();
  }

  // `q` is the query to open on: a shared link's, or none.
  function open(q) {
    host.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    if (q && q.trim()) wantBody();
    if (!mounted) {
      mounted = boot(q).catch(function (e) {
        fail(String(e));
        // A failed mount is not retried on the next press: the reactor is
        // missing or broken, and asking for it again would be one more failed
        // request per keystroke.
        app = null;
        return null;
      });
      mounted.then(focusInput);
    } else if (app) {
      // Escape leaves the guest with an empty tree, so reopening is a fresh
      // init -- with the recent queries as they are now. Until it answers,
      // the panel the reader last closed is still the document; `is-starting`
      // keeps it out of sight rather than showing an old query for a frame.
      host.classList.add('is-starting');
      restart(q).then(function () {
        host.classList.remove('is-starting');
        focusInput();
      });
    } else {
      mounted.then(focusInput);
    }
  }

  // Focus goes back where it came from: the button that opened the panel.
  function close() {
    writeQuery('');
    host.classList.remove('is-starting');
    uncopied();
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

  // The button and the shortcut toggle, and whether the panel is open is a
  // question about every turn the reader has already asked for: an Escape
  // still on its way to the guest may be the one that closes it. So a toggle
  // waits for the turns in flight, as it would have found them finished when
  // turns were synchronous; otherwise Escape-then-Cmd-K, pressed together,
  // would shut the panel the reader was reopening. While it waits the panel
  // on screen is one the reader has already dismissed or is about to see
  // replaced, so it is out of sight (`is-starting`) and takes no typing.
  function toggle() {
    var go = function () {
      host.classList.remove('is-starting');
      if (host.hidden) open('');
      else close();
    };
    if (app && !host.hidden) {
      host.classList.add('is-starting');
      app.idle().then(go);
    } else {
      go();
    }
  }

  btn.addEventListener('click', toggle);
  btn.addEventListener('pointerenter', prewarm);
  btn.addEventListener('focus', prewarm);

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
    // Focus first, into the field that is there now, so that what the reader
    // types while the guest restarts is carried into the new one.
    focusInput();
    restart('');
    return true;
  }

  // The host is the scrim. A click on it, outside the panel, closes; a click
  // inside has already been heard by the guest, and if that was Cancel the
  // guest has left. A row is a link and the browser follows it; the panel
  // closes so that a link into this same page does not leave it open, and
  // the query that found it is remembered.
  host.addEventListener('click', function (ev) {
    if (copyLink(ev)) return;
    if (ev.target.closest && ev.target.closest('.search-copy-manual')) return;
    if (forget(ev)) return;
    var row = ev.target.closest && ev.target.closest('.search-row a');
    if (row) {
      var f = field();
      if (f) remember(f.value);
    }
    if (ev.target === host || guestLeft() || row) close();
    // The suggested query, taken from the keyboard: the button that had focus
    // is gone with the empty state it was in, so focus goes back to the field
    // that now holds the query.
    if (ev.target.closest && ev.target.closest('.search-fix-term')) focusInput();
  });

  // A scope pill is a button, and so are a suggested query and Copy link; a pressed button
  // takes focus, and the field has to keep it, or the arrows and Enter stop
  // reaching the guest after a click. The click itself still happens.
  host.addEventListener('mousedown', function (ev) {
    if (ev.target.closest && ev.target.closest('.search-pill, .search-fix-term, .search-copy')) ev.preventDefault();
  });

  host.addEventListener('mousemove', function () {
    host.classList.remove('is-keying');
  });

  // A new query makes the link that was copied, and the word that says so,
  // about a different search; both go. The address keeps what was copied
  // until the panel closes.
  host.addEventListener('input', function () {
    follow();
    uncopied();
    var f = field();
    if (f && f.value.trim()) wantBody();
  });

  // The panel is modal: focus that lands outside it while it is open is
  // brought back to the field.
  document.addEventListener('focusin', function (ev) {
    if (!host.hidden && !host.contains(ev.target)) focusInput();
  });

  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      toggle();
      return;
    }
    if (host.hidden) return;
    // Where Enter meant to go is a question about the document once the
    // guest's answer is in it (afterTurn), so the guest never has to be handed
    // a URL bar. What the keydown still knows and the document will not is
    // whether the reader asked for a new tab. Opening one from afterTurn is
    // still inside the activation this keypress gave the page.
    if (ev.key === 'Enter') goNewTab = !!(ev.metaKey || ev.ctrlKey);
    if (ev.key === 'Escape') {
      // The guest hears Escape only in its field, and there the first press
      // empties the query and leaves the panel open; the second leaves an
      // empty tree, which afterTurn closes.
      var heard = ev.target && ev.target.classList && ev.target.classList.contains('search-input');
      if (!heard || guestLeft()) close();
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

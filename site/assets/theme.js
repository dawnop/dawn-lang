/* Every page's script: the theme, and the contents fold on a narrow screen.
   Loaded by every page (html/page.head_html) as a plain blocking script in
   <head>, because the first thing it does has to happen before the first
   paint: put a theme the reader chose last time on <html>, or the page would
   flash the system theme first. Everything that needs the body waits for
   DOMContentLoaded.

   It is a file and not an inline <script>, for the reasons home.js was one
   before it: no page needs 'unsafe-inline' for it, and what runs is one
   fingerprinted asset rather than text spliced into a hundred HTML files.

   It carries no words. Both language trees load it, and the toggle's two
   labels are attributes on the button, written by the generator in the
   page's language (gen/assets.dawn holds shared bundles to having no
   Chinese).

   Switching: the new theme opens as a circle from the toggle, through a view
   transition, so no pixel is ever half one theme and half the other and no
   element runs a colour tween of its own (docs/site-pages-design.md says
   why that matters). Without view transitions, or under reduced motion, the
   theme simply switches. A page with a switch of its own registers it as
   `window.dawnTheme.turn` before the body is parsed (home.js does: the
   front page turns its sun and moon), and then this hands the click to it.

   Without this script every page is complete: the toggle stays hidden, the
   page follows the system theme and the contents stay open. */
(function () {
  "use strict";
  var root = document.documentElement;
  var KEY = "dawn-theme";

  /* storage can throw (a private window, blocked site data); the page then
     simply follows the system */
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) {}

  /* lets the stylesheet hold the contents fold shut on a narrow screen until
     the fold is fitted below, rather than showing it open for a frame */
  root.classList.add("js");

  function query(q) { return window.matchMedia ? window.matchMedia(q) : null; }
  var darkQuery = query("(prefers-color-scheme: dark)");
  var stillQuery = query("(prefers-reduced-motion: reduce)");

  function current() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return darkQuery && darkQuery.matches ? "dark" : "light";
  }
  function still() { return !!(stillQuery && stillQuery.matches); }

  var api = window.dawnTheme = { current: current, still: still, darkQuery: darkQuery, turn: null };

  function wireToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    function label() {
      var dark = current() === "dark";
      var text = dark ? btn.getAttribute("data-label-light") : btn.getAttribute("data-label-dark");
      if (text) btn.setAttribute("aria-label", text);
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
    }
    function apply(next) {
      root.setAttribute("data-theme", next);
      try { localStorage.setItem(KEY, next); } catch (e) {}
      label();
    }
    label();
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      if (api.turn) { api.turn(next, apply); return; }
      if (still() || !document.startViewTransition) { apply(next); return; }
      var r = btn.getBoundingClientRect();
      var x = r.left + r.width / 2;
      var y = r.top + r.height / 2;
      var radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      var vt = document.startViewTransition(function () { apply(next); });
      vt.ready.then(function () {
        root.animate(
          { clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + radius + "px at " + x + "px " + y + "px)"] },
          { duration: 560, easing: "cubic-bezier(0.45, 0, 0.25, 1)", pseudoElement: "::view-transition-new(root)" });
      }, function () {});
    });
  }

  /* The contents rail is a sidebar on a wide screen and a fold at the top of
     the page on a narrow one; the breakpoint is the stylesheet's, and the two
     must move together. Open in the markup, so a reader without this script
     loses nothing. */
  function fitFold() {
    var fold = document.querySelector(".toc-fold");
    if (!fold) return;
    var narrow = query("(max-width: 959px)");
    function fit() { fold.open = !(narrow && narrow.matches); }
    fit();
    fold.classList.add("is-fit");
    if (narrow && narrow.addEventListener) narrow.addEventListener("change", fit);
  }

  function ready() { wireToggle(); fitFold(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();

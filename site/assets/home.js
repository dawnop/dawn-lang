/* The front page's script: the theme toggle, the hero's colours trailing it,
   the sun-and-moon orbit, and the figures' count-up. Loaded by that page alone
   (gen/home.dawn), as a plain blocking script in <head>, because the first
   thing it does has to happen before the first paint: put a theme the reader
   chose last time on <html>, or the page would flash the system theme first.
   Everything that needs the body waits for DOMContentLoaded.

   It is a file and not an inline <script>: the site serves no inline script
   on this page, so that a Content-Security-Policy without 'unsafe-inline' can
   be put in front of it, and so that what runs is one fingerprinted asset the
   generator hashed rather than text spliced into two HTML files.

   It carries no words. Both language trees load it, and the toggle's two
   labels are attributes on the button, written by the generator in the page's
   language (gen/assets.dawn holds shared bundles to having no Chinese, and
   this is how the Chinese page still gets Chinese labels).

   The page is complete without it: the toggle stays hidden, the hero follows
   the system theme, and every figure is already its final number. */
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

  var darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var still = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false;

  function current() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return darkQuery && darkQuery.matches ? "dark" : "light";
  }

  /* data-sky drives the hero's colours (home.css says why it is a second
     attribute); it trails data-theme by part of the night fade when the
     toggle is used, and matches it otherwise */
  root.setAttribute("data-sky", current());
  if (darkQuery && darkQuery.addEventListener) {
    darkQuery.addEventListener("change", function () {
      if (!root.getAttribute("data-theme")) root.setAttribute("data-sky", current());
    });
  }

  function wireToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    function label() {
      var dark = current() === "dark";
      var text = dark ? btn.getAttribute("data-label-light") : btn.getAttribute("data-label-dark");
      if (text) btn.setAttribute("aria-label", text);
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
    }
    label();
    btn.hidden = false;

    /* The orbit's phase only ever grows, so day and night always turn the
       same way round instead of rocking back and forth. */
    var orbit = document.getElementById("orbit");
    var phase = current() === "dark" ? 50 : 0;
    var skyTimer = null;
    var animTimer = null;
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.classList.add("theme-anim");
      root.setAttribute("data-theme", next);
      clearTimeout(skyTimer);
      if (still) {
        root.setAttribute("data-sky", next);
      } else {
        skyTimer = setTimeout(function () { root.setAttribute("data-sky", next); }, 420);
        root.classList.remove("code-dip");
        void root.offsetWidth;
        setTimeout(function () { root.classList.add("code-dip"); }, 190);
        setTimeout(function () { root.classList.remove("code-dip"); }, 700);
      }
      phase += 50;
      if (orbit) orbit.style.setProperty("--phase", phase + "%");
      try { localStorage.setItem(KEY, next); } catch (e) {}
      label();
      clearTimeout(animTimer);
      animTimer = setTimeout(function () { root.classList.remove("theme-anim"); }, 1500);
    });
  }

  /* A short count-up on the figures, once, when they first come into view.
     The final numbers are in the markup, so without script, without
     IntersectionObserver or with reduced motion they stand as written. */
  function countUp() {
    var els = document.querySelectorAll("[data-count]");
    if (still || !("IntersectionObserver" in window) || !els.length) return;
    var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
    function run(el) {
      var end = +el.getAttribute("data-count");
      var t0 = null;
      var dur = 900;
      function step(t) {
        if (t0 === null) t0 = t;
        var k = Math.min(1, (t - t0) / dur);
        el.textContent = fmt(end * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(step); else el.textContent = fmt(end);
      }
      requestAnimationFrame(step);
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { io.unobserve(e.target); run(e.target); }
      });
    }, { threshold: 0.6 });
    Array.prototype.forEach.call(els, function (el) { io.observe(el); });
  }

  function ready() { wireToggle(); countUp(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();

/* The front page's script: the hero's colours trailing the theme, the
   sun-and-moon orbit, and the figures' count-up. Loaded by that page alone
   (gen/home.dawn), as a plain blocking script in <head> right after the
   shared theme.js, which has already put the saved theme on <html> and
   which owns the toggle: its label, what is stored, and the click.

   What this adds is the front page's own way of switching. It registers
   `dawnTheme.turn`, and theme.js hands every click to it instead of running
   its view transition: here the switch is the hero's performance (the orbit
   turns half a lap, night fades in over the day, the hero's inks change half
   way into the fade and the code dims for a moment), and a view transition
   would freeze all of that inside a snapshot (docs/site-pages-design.md).

   It carries no words, for the reason theme.js carries none. The page is
   complete without it: the hero follows the system theme, and every figure
   is already its final number. */
(function () {
  "use strict";
  var root = document.documentElement;
  var theme = window.dawnTheme;
  if (!theme) return;
  var current = theme.current;
  var still = theme.still();

  /* data-sky drives the hero's colours (home.css says why it is a second
     attribute); it trails data-theme by part of the night fade when the
     toggle is used, and matches it otherwise */
  root.setAttribute("data-sky", current());
  if (theme.darkQuery && theme.darkQuery.addEventListener) {
    theme.darkQuery.addEventListener("change", function () {
      if (!root.getAttribute("data-theme")) root.setAttribute("data-sky", current());
    });
  }

  /* The orbit's phase only ever grows, so day and night always turn the
     same way round instead of rocking back and forth. */
  var phase = current() === "dark" ? 50 : 0;
  var skyTimer = null;
  var animTimer = null;
  theme.turn = function (next, apply) {
    root.classList.add("theme-anim");
    apply(next);
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
    var orbit = document.getElementById("orbit");
    if (orbit) orbit.style.setProperty("--phase", phase + "%");
    clearTimeout(animTimer);
    animTimer = setTimeout(function () { root.classList.remove("theme-anim"); }, 1500);
  };

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

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", countUp);
  else countUp();
})();

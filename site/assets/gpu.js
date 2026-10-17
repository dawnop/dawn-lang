/* The cuTile page's script (gen/gpu.dawn links it, deferred): the keepdims
   card's two links into the call map, and the coverage cards' count-up.

   The page is complete without it. The call map is a source and the Tile IR
   beside it, every line already marked with the call that wrote it; picking
   a call, the tab order and the arrow keys in a listing are
   site/assets/explorer.js's, the script the explorer page runs, which this
   page loads too (the map is that page's figure with two listings in view
   and no tabs). This file only adds what is the GPU page's own.

   The keepdims card links two lines of the source (`#kl-<line>`, `data-pick`
   the call). Without a script the link is a jump to the line; with it the
   line is brought to the middle and the call picked, as a click on its name
   would, so the lines it wrote show in the Tile IR beside it.

   It carries no words. With reduced motion the cards are their end state, as
   home.js does it. */
(function () {
  "use strict";
  var theme = window.dawnTheme;
  var still = theme ? theme.still() : true;

  function each(root, sel, f) { Array.prototype.forEach.call(root.querySelectorAll(sel), f); }

  /* ---- the keepdims card's links ---- */

  function links() {
    each(document, "a[data-pick]", function (a) {
      a.addEventListener("click", function (ev) {
        var id = a.getAttribute("data-pick");
        var map = document.querySelector(".xp-flash");
        var name = map && map.querySelector('.xc[data-c="' + id + '"]');
        var line = name && name.closest(".xl");
        if (!line) return;
        ev.preventDefault();
        if (line.scrollIntoView) line.scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
        /* explorer.js picks on a click, and a click on a picked name lets go */
        if (name.getAttribute("aria-pressed") !== "true") name.click();
        if (window.history && history.replaceState) history.replaceState(null, "", a.getAttribute("href"));
      });
    });
  }

  /* ---- the coverage cards ---- */

  /* Each card's number counts up from zero and its bar fills, once, when the
     card comes into view. The final number is the markup's, and the bar's
     width is its `--p`; this only starts both from nothing. */
  function cards() {
    var figs = document.querySelectorAll(".gpu-fig[data-count]");
    if (still || !("IntersectionObserver" in window) || !figs.length) return;
    Array.prototype.forEach.call(figs, function (f) {
      f.classList.add("gf-wait");
      f.querySelector("strong b").textContent = 0;
    });
    function run(f) {
      var el = f.querySelector("strong b");
      var end = +f.getAttribute("data-count");
      var t0 = null;
      f.classList.remove("gf-wait");
      function step(t) {
        if (t0 === null) t0 = t;
        var k = Math.min(1, (t - t0) / 1100);
        el.textContent = Math.round(end * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(step); else el.textContent = end;
      }
      requestAnimationFrame(step);
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { io.unobserve(e.target); run(e.target); }
      });
    }, { threshold: 0.5 });
    Array.prototype.forEach.call(figs, function (f) { io.observe(f); });
  }

  function start() { links(); cards(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

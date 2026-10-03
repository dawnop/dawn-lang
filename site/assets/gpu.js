/* The cuTile page's script (gen/gpu.dawn links it, deferred): picking a call
   on the call map, and the coverage cards' count-up.

   The page is complete without it. Every row of flash_attn already has the
   Tile IR its calls wrote beside it, and every card is at its final number;
   this only lets a reader point at one call. Clicking a call's name marks
   its whole span in the source and the Tile IR lines it wrote itself; a
   region call (a loop, a scan) marks its header, terminator and brace, and
   the lines its body's calls wrote more faintly. Clicking it again, or
   pressing Escape, lets go; clicking a line of Tile IR picks the call that
   wrote it. Nothing moves and nothing is filled: an underline and an edge.

   It carries no words: the one sentence about clicking is in the markup,
   `hidden` until this shows it. With reduced motion the cards are their end
   state, as home.js does it. */
(function () {
  "use strict";
  var theme = window.dawnTheme;
  var still = theme ? theme.still() : true;

  function each(root, sel, f) { Array.prototype.forEach.call(root.querySelectorAll(sel), f); }

  /* ---- the call map ---- */

  function callMap() {
    var map = document.querySelector(".km");
    if (!map) return;
    var parent = {};
    each(map, ".km-c", function (c) { parent[c.getAttribute("data-c")] = c.getAttribute("data-p"); });
    /* whether call `k` is `id` or inside it, by the recording's tree */
    function under(k, id) {
      for (var n = 0; k !== null && k !== undefined && n < 64; n++) {
        if (k === id) return true;
        k = parent[k];
      }
      return false;
    }
    var picked = null;
    function clear() {
      each(map, ".km-on", function (e) { e.classList.remove("km-on"); });
      each(map, ".km-hit, .km-in", function (e) { e.classList.remove("km-hit", "km-in"); });
      each(map, '.km-c[aria-pressed="true"]', function (e) { e.setAttribute("aria-pressed", "false"); });
      picked = null;
    }
    function pick(id) {
      var again = picked === id;
      clear();
      if (again || id === null) return;
      picked = id;
      each(map, ".km-c[data-c=\"" + id + "\"]", function (e) { e.setAttribute("aria-pressed", "true"); });
      each(map, "[data-k]", function (e) {
        if (e.getAttribute("data-k").split(" ").indexOf(id) >= 0) e.classList.add("km-on");
      });
      var first = null;
      each(map, ".km-ir .km-l[data-o]", function (e) {
        var o = e.getAttribute("data-o");
        if (o === id) {
          e.classList.add("km-hit");
          if (!first) first = e;
        } else if (+o >= 0 && under(o, id)) {
          e.classList.add("km-in");
        }
      });
      if (first && first.scrollIntoView) first.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
    }
    each(map, ".km-c", function (c) {
      c.setAttribute("role", "button");
      c.setAttribute("tabindex", "0");
      c.setAttribute("aria-pressed", "false");
    });
    map.addEventListener("click", function (ev) {
      var c = ev.target.closest(".km-c");
      if (c) { pick(c.getAttribute("data-c")); return; }
      var l = ev.target.closest(".km-ir .km-l[data-o]");
      if (l && +l.getAttribute("data-o") >= 0) pick(l.getAttribute("data-o"));
    });
    map.addEventListener("keydown", function (ev) {
      var c = ev.target.closest && ev.target.closest(".km-c");
      if (c && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); pick(c.getAttribute("data-c")); }
      else if (ev.key === "Escape") clear();
    });
    map.classList.add("km-live");
    each(map, ".km-note", function (n) { n.hidden = false; });
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

  function start() { callMap(); cards(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

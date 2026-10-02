/* The cuTile page's script (gen/gpu.dawn links it, deferred): the kernel
   picker and the replay on the line map, the coverage cards' count-up, and
   the mutants' flight into the gate that catches them.

   The page is complete without it. The map of `vadd`, every figure at its
   final number and every mutant at its gate are in the markup; the picker
   and the replay button are `hidden` there and shown from here, because
   without a script they would be controls that do nothing.

   It carries no words. Every label is in the markup, in the page's language,
   and a kernel fetched from gpu/k/<name>.json brings numbers, names and code,
   which read the same in both. With reduced motion every animation is its
   end state, as home.js does it. */
(function () {
  "use strict";
  var theme = window.dawnTheme;
  var still = theme ? theme.still() : true;

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function line(n, html) { return '<span class="gm-l"><i>' + n + "</i>" + html + "</span>"; }
  function codes(xs) {
    return xs.map(function (x) { return "<code>" + esc(x) + "</code>"; }).join("");
  }

  /* ---- the line map ---- */

  /* A fetched kernel, drawn the way gen/gpu.map_rows draws vadd: the same
     classes, the same per-line pieces (`src` is already highlighted by the
     generator), so the two cannot look different. */
  function draw(map, k) {
    var rows = k.rows.map(function (r, i) {
      var d = [];
      for (var n = r.d[0]; n < r.d[1]; n++) d.push(line(k.first + n, k.src[n]));
      var t = [];
      r.i.forEach(function (g) {
        for (var n = g[0]; n < g[1]; n++) t.push(line(n, esc(k.ir[n - 1])));
      });
      var calls = r.c.length ? '<span class="gm-calls">' + codes(r.c) + "</span>" : "";
      return '<li class="gm-row g' + (i % 6) + '" tabindex="0" data-ops="' + r.o +
        '" aria-describedby="gm-t' + i + '"><div class="gm-d"><pre><code>' + d.join("\n") +
        "</code></pre>" + calls + '</div><div class="gm-t" id="gm-t' + i + '"><pre><code>' +
        t.join("\n") + "</code></pre></div></li>";
    });
    map.querySelector(".gm-rows").innerHTML = rows.join("\n");
    var set = function (key, html) {
      var el = map.querySelector('[data-f="' + key + '"]');
      if (el) el.innerHTML = html;
    };
    set("src", "kernels.dawn:" + k.first + "–" + (k.first + k.src.length - 1));
    set("ir", esc(k.name) + ".mlir");
    set("count", k.ops);
    set("calls", k.calls);
    set("ops", k.ops);
    set("lines", k.lines);
    set("bytes", k.bytes);
    set("rows", k.cites.length);
    set("cites", codes(k.cites));
    set("mutantn", k.mutants.length);
    set("mutants", codes(k.mutants));
    map.querySelectorAll(".gm-names").forEach(function (p, i) {
      p.hidden = (i === 0 ? k.cites : k.mutants).length === 0;
    });
  }

  /* The recording, replayed: the Tile IR column empties, then each row in
     source order lights up and its lines come back one at a time while the
     counter adds the operations that row's calls recorded. */
  var playing = 0;
  function replay(map) {
    var token = ++playing;
    var rows = Array.prototype.slice.call(map.querySelectorAll(".gm-row"));
    var count = map.querySelector('[data-f="count"]');
    var total = rows.reduce(function (n, r) { return n + +r.getAttribute("data-ops"); }, 0);
    var finish = function () {
      map.classList.remove("gm-playing");
      rows.forEach(function (r) { r.classList.remove("gm-on"); });
      map.querySelectorAll(".gm-t .gm-l").forEach(function (l) { l.classList.remove("gm-off"); });
      count.textContent = total;
    };
    if (still) { finish(); return; }
    map.classList.add("gm-playing");
    map.querySelectorAll(".gm-t .gm-l").forEach(function (l) { l.classList.add("gm-off"); });
    var lines = map.querySelectorAll(".gm-t .gm-l").length || 1;
    var per = Math.max(18, Math.min(90, 2600 / lines));
    var ops = 0;
    count.textContent = 0;
    var r = 0;
    function nextRow() {
      if (token !== playing) return;
      if (r > 0) rows[r - 1].classList.remove("gm-on");
      if (r >= rows.length) { setTimeout(finish, 350); return; }
      var row = rows[r++];
      row.classList.add("gm-on");
      var ls = row.querySelectorAll(".gm-t .gm-l");
      var add = +row.getAttribute("data-ops");
      var j = 0;
      function nextLine() {
        if (token !== playing) return;
        if (j < ls.length) {
          ls[j++].classList.remove("gm-off");
          count.textContent = ops + Math.round(add * j / ls.length);
          setTimeout(nextLine, per);
        } else {
          ops += add;
          count.textContent = ops;
          setTimeout(nextRow, per * 2);
        }
      }
      nextLine();
    }
    nextRow();
  }

  function lineMap() {
    var map = document.querySelector(".gpu-map");
    if (!map) return;
    var pick = map.querySelector(".gm-pick");
    var select = pick && pick.querySelector("select");
    var button = map.querySelector(".gm-replay");
    if (button) {
      button.hidden = false;
      button.addEventListener("click", function () { replay(map); });
    }
    if (!select || !window.fetch) return;
    pick.hidden = false;
    var base = map.getAttribute("data-map-base");
    select.addEventListener("change", function () {
      var name = select.value;
      playing++;
      map.classList.add("gm-loading");
      fetch(base + encodeURIComponent(name) + ".json")
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (k) {
          if (select.value !== name) return;
          draw(map, k);
          map.classList.remove("gm-loading");
          replay(map);
        })
        .catch(function () { map.classList.remove("gm-loading"); });
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

  /* ---- the mutants ---- */

  /* Every mutant is a dot already sitting in the gate that catches it. With
     motion, they start at the left edge and fly in, once, staggered, when the
     pipeline comes into view; each one's gate is the markup's. */
  function trap() {
    var net = document.querySelector(".gpu-trap");
    if (!net || still || !("IntersectionObserver" in window)) return;
    net.classList.add("gt-wait");
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        void net.offsetWidth;
        net.classList.remove("gt-wait");
        net.classList.add("gt-fly");
      });
    }, { threshold: 0.4 });
    io.observe(net);
  }

  function start() { lineMap(); cards(); trap(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

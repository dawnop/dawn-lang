/* The explorer page's script (gen/explorer.dawn links it, deferred): picking a
   call and following it from the source into every listing and back, the
   tabs, and the keyboard.

   The page is complete without it. The source and the three listings are all
   in the markup, one under another, and every line already says which calls
   own it (`data-o`, the innermost first) and whose instruction it is
   (`data-i`); this only lets a reader point. Picking a call underlines its
   whole span in the source and marks, in every listing, the lines it wrote
   itself (an accent edge and number) and, fainter, the lines the calls inside
   it wrote. In C the columns it holds are underlined, in the bytecode the
   instruction that implements it is bold. Picking a line of a listing picks
   the innermost call that owns it. Nothing moves and nothing is filled.

   Tabs are the ARIA tabs pattern with automatic activation: a tab shows its
   listing and keeps what is picked, so the same call can be followed from
   one backend to the next. Without this script every listing is shown.

   Keyboard: the calls' names are in the tab order; Enter or Space picks. A
   listing is entered once, on its first owned line, and the arrow keys, Home
   and End move between the owned lines (a roving tabindex), Enter or Space
   picks, Escape lets go. The status line is a polite live region and says
   what was picked and where it landed.

   It carries no words: the status line's are `data-w-*` on the figure. */
(function () {
  "use strict";
  var theme = window.dawnTheme;
  var still = theme ? theme.still() : true;

  function each(root, sel, f) { Array.prototype.forEach.call(root.querySelectorAll(sel), f); }
  function has(list, x) { return list.indexOf(x) >= 0; }
  function words(s) { return s ? s.split(" ") : []; }

  function explorer(fig) {
    var parent = {};
    var calls = {};
    each(fig, ".xc", function (c) {
      var id = c.getAttribute("data-c");
      parent[id] = c.getAttribute("data-p");
      calls[id] = c;
    });
    var panes = {};
    each(fig, ".xp-pane", function (p) { panes[p.getAttribute("data-kind")] = p; });
    var tabs = Array.prototype.slice.call(fig.querySelectorAll(".xp-tab"));
    var status = fig.querySelector(".xp-status");
    var picked = null;

    /* whether call `k` is `id` or inside it, by the recording's tree */
    function under(k, id) {
      for (var n = 0; k !== null && k !== undefined && k !== "-1" && n < 64; n++) {
        if (k === id) return true;
        k = parent[k];
      }
      return false;
    }

    function active() {
      for (var i = 0; i < tabs.length; i++) if (tabs[i].getAttribute("aria-selected") === "true") return tabs[i].getAttribute("data-kind");
      return null;
    }

    /* a pane's own scroll, never the page's */
    function reveal(line) {
      var box = line && line.closest(".xp-code");
      if (!box) return;
      var top = line.offsetTop, h = line.offsetHeight;
      if (top < box.scrollTop || top + h > box.scrollTop + box.clientHeight) {
        var to = Math.max(0, top - box.clientHeight / 3);
        if (box.scrollTo) box.scrollTo({ top: to, behavior: still ? "auto" : "smooth" });
        else box.scrollTop = to;
      }
    }

    function runs(ns) {
      var out = [], a = null, b = null;
      ns.forEach(function (n) {
        if (a !== null && n === b + 1) b = n;
        else { if (a !== null) out.push([a, b]); a = b = n; }
      });
      if (a !== null) out.push([a, b]);
      return out.map(function (r) { return r[0] === r[1] ? "" + r[0] : r[0] + "–" + r[1]; }).join(", ");
    }

    function say() {
      if (!status) return;
      if (picked === null) { status.textContent = ""; return; }
      var c = calls[picked];
      var kind = active();
      var pane = kind && panes[kind];
      var ns = [];
      if (pane) each(pane, ".xl.xp-hit", function (l) { ns.push(+l.getAttribute("data-n")); });
      var label = "";
      tabs.forEach(function (t) { if (t.getAttribute("data-kind") === kind) label = t.textContent; });
      var where = ns.length
        ? label + " " + (ns.length > 1 ? fig.getAttribute("data-w-lines") : fig.getAttribute("data-w-line")) + " " + runs(ns)
        : label + ": " + fig.getAttribute("data-w-none");
      status.textContent = c.textContent + " · " + c.getAttribute("data-s") + " → " + where;
    }

    function clear() {
      each(fig, ".xp-on", function (e) { e.classList.remove("xp-on"); });
      each(fig, ".xp-hit, .xp-in, .xp-ipc", function (e) { e.classList.remove("xp-hit", "xp-in", "xp-ipc"); });
      each(fig, '.xc[aria-pressed="true"]', function (e) { e.setAttribute("aria-pressed", "false"); });
      each(fig, '.xl[aria-pressed="true"]', function (e) { e.setAttribute("aria-pressed", "false"); });
      picked = null;
      say();
    }

    function pick(id, quiet) {
      var again = picked === id;
      clear();
      if (again || id === null) return;
      picked = id;
      if (calls[id]) calls[id].setAttribute("aria-pressed", "true");
      each(fig, "[data-k]", function (e) {
        if (has(words(e.getAttribute("data-k")), id)) e.classList.add("xp-on");
      });
      each(fig, ".xl[data-o]", function (l) {
        var os = words(l.getAttribute("data-o"));
        if (has(os, id)) l.classList.add("xp-hit");
        else if (os.some(function (o) { return under(o, id); })) l.classList.add("xp-in");
        l.setAttribute("aria-pressed", has(os, id) ? "true" : "false");
      });
      each(fig, ".xl[data-i]", function (l) {
        if (has(words(l.getAttribute("data-i")), id)) l.classList.add("xp-ipc");
      });
      say();
      var kind = active();
      var first = kind && panes[kind] && panes[kind].querySelector(".xl.xp-hit");
      if (!quiet && first) reveal(first);
    }

    /* ---- the source ---- */
    each(fig, ".xc", function (c) {
      c.setAttribute("role", "button");
      c.setAttribute("tabindex", "0");
      c.setAttribute("aria-pressed", "false");
    });

    /* ---- the listings: owned lines are the buttons, one stop each pane ---- */
    function owned(pane) { return Array.prototype.slice.call(pane.querySelectorAll(".xl[data-o]")); }
    Object.keys(panes).forEach(function (k) {
      var ls = owned(panes[k]);
      ls.forEach(function (l, i) {
        l.setAttribute("role", "button");
        l.setAttribute("tabindex", i === 0 ? "0" : "-1");
        l.setAttribute("aria-pressed", "false");
      });
    });
    function focusLine(pane, to) {
      var ls = owned(pane);
      ls.forEach(function (l) { l.setAttribute("tabindex", l === to ? "0" : "-1"); });
      to.focus();
      reveal(to);
    }

    /* ---- the tabs ---- */
    function show(kind, focus) {
      tabs.forEach(function (t) {
        var on = t.getAttribute("data-kind") === kind;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.setAttribute("tabindex", on ? "0" : "-1");
        if (on && focus) t.focus();
      });
      Object.keys(panes).forEach(function (k) { panes[k].hidden = k !== kind; });
      say();
      var first = picked !== null && panes[kind].querySelector(".xl.xp-hit");
      if (first) reveal(first);
    }
    if (tabs.length) {
      var strip = fig.querySelector(".xp-tabs");
      strip.hidden = false;
      show(active() || tabs[0].getAttribute("data-kind"), false);
      tabs.forEach(function (t, i) {
        t.addEventListener("click", function () { show(t.getAttribute("data-kind"), false); });
        t.addEventListener("keydown", function (ev) {
          var to = null;
          if (ev.key === "ArrowRight") to = tabs[(i + 1) % tabs.length];
          else if (ev.key === "ArrowLeft") to = tabs[(i + tabs.length - 1) % tabs.length];
          else if (ev.key === "Home") to = tabs[0];
          else if (ev.key === "End") to = tabs[tabs.length - 1];
          if (to) { ev.preventDefault(); show(to.getAttribute("data-kind"), true); }
        });
      });
    }

    /* ---- picking ---- */
    fig.addEventListener("click", function (ev) {
      var sel = window.getSelection && window.getSelection();
      if (sel && !sel.isCollapsed && fig.contains(sel.anchorNode)) return;
      var c = ev.target.closest(".xc");
      if (c) { ev.preventDefault(); pick(c.getAttribute("data-c")); return; }
      var l = ev.target.closest(".xl[data-o]");
      if (l) pick(words(l.getAttribute("data-o"))[0]);
    });
    fig.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { clear(); return; }
      var c = ev.target.closest && ev.target.closest(".xc");
      var l = ev.target.closest && ev.target.closest(".xl[data-o]");
      if ((c || l) && (ev.key === "Enter" || ev.key === " ")) {
        ev.preventDefault();
        pick(c ? c.getAttribute("data-c") : words(l.getAttribute("data-o"))[0]);
        return;
      }
      if (l) {
        var pane = l.closest(".xp-pane");
        var ls = owned(pane);
        var at = ls.indexOf(l);
        var to = null;
        if (ev.key === "ArrowDown") to = ls[Math.min(ls.length - 1, at + 1)];
        else if (ev.key === "ArrowUp") to = ls[Math.max(0, at - 1)];
        else if (ev.key === "Home") to = ls[0];
        else if (ev.key === "End") to = ls[ls.length - 1];
        if (to) { ev.preventDefault(); focusLine(pane, to); }
      }
    });
    fig.classList.add("xp-live");
    each(fig, ".xp-note", function (n) { n.hidden = false; });
  }

  each(document, ".xp", explorer);
})();

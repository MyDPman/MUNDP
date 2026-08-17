/* Typed headers — ported from modelundp.org's hero-type.js (the rotating
   line on the conference homepage hero).

   Two modes:
   1) #home-type (homescreen hero): the site's full rotating treatment —
      type, hold, delete, next phrase — with the exact same cadence.
      Extra phrases come from data-phrases (JSON array).
   2) Every other page: the .page-header h1 (or the sign-in card's h1)
      types itself out once with a blinking caret, then the caret fades
      away. Badges and other elements inside the h1 hold back and fade in
      after the title lands.

   The markup always ships with the real text, so no-JS visitors,
   crawlers, and reduced-motion users get a static line; this script only
   takes over when it's safe to animate. */
(function () {
  "use strict";

  if (
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return;
  }

  var TYPE_MS = 45; // per character while typing (rotating mode)
  var DELETE_MS = 22; // per character while deleting
  var HOLD_MS = 4000; // full phrase on screen
  var GAP_MS = 400; // empty line before the next phrase starts

  // setTimeout chain instead of rAF: the cadence is slow enough that frame
  // sync doesn't matter, and a hidden tab just parks on the pending step
  function wait(ms, fn) {
    setTimeout(function () {
      if (document.hidden) {
        document.addEventListener("visibilitychange", function onVis() {
          document.removeEventListener("visibilitychange", onVis);
          fn();
        });
      } else {
        fn();
      }
    }, ms);
  }

  /* ---------- rotating homescreen hero ---------- */
  var rot = document.getElementById("home-type");
  if (rot) {
    var PHRASES = [rot.textContent.replace(/\s+/g, " ").trim()];
    try {
      var more = JSON.parse(rot.getAttribute("data-phrases") || "[]");
      for (var m = 0; m < more.length; m++) PHRASES.push(String(more[m]));
    } catch (e) { /* original phrase only */ }

    rot.setAttribute("aria-label", PHRASES[0]);
    var rwrap = document.createElement("span");
    rwrap.setAttribute("aria-hidden", "true");
    var rtext = document.createElement("span");
    rtext.className = "hero-type-text";
    rwrap.appendChild(rtext);

    // reserve the height of the tallest phrase so nothing below shifts
    function reserveHeight() {
      var block = rot.parentNode;
      var probe = rot.cloneNode(false);
      probe.removeAttribute("id");
      probe.style.cssText =
        "position:absolute;visibility:hidden;pointer-events:none;min-height:0;width:" +
        rot.clientWidth + "px";
      block.appendChild(probe);
      var max = 0;
      for (var i = 0; i < PHRASES.length; i++) {
        probe.textContent = PHRASES[i];
        if (probe.offsetHeight > max) max = probe.offsetHeight;
      }
      block.removeChild(probe);
      block.style.minHeight = "";
      block.style.minHeight = block.offsetHeight + (max - rot.offsetHeight) + "px";
    }

    reserveHeight();
    rot.textContent = "";
    rot.appendChild(rwrap);
    rtext.textContent = PHRASES[0];

    var resizeTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(reserveHeight, 150);
    }, { passive: true });

    var index = 0;

    function deletePhrase() {
      var current = rtext.textContent;
      if (current.length === 0) {
        index = (index + 1) % PHRASES.length;
        wait(GAP_MS, typePhrase);
        return;
      }
      rtext.textContent = current.slice(0, -1);
      wait(DELETE_MS, deletePhrase);
    }

    function typePhrase() {
      var target = PHRASES[index];
      var current = rtext.textContent;
      if (current.length >= target.length) {
        wait(HOLD_MS, deletePhrase);
        return;
      }
      rtext.textContent = target.slice(0, current.length + 1);
      wait(TYPE_MS, typePhrase);
    }

    wait(HOLD_MS, deletePhrase);
    return; // the homescreen has no .page-header — done
  }

  /* ---------- one-shot typed page titles ---------- */
  var h1 =
    document.querySelector(".page-header h1") ||
    document.querySelector(".auth-card h1");
  if (!h1) return;

  // type only the leading text node; badges and other children inside the
  // h1 stay intact and fade in after the title finishes
  var textNode = null;
  for (var i = 0; i < h1.childNodes.length; i++) {
    var n = h1.childNodes[i];
    if (n.nodeType === 3 && n.textContent.trim()) { textNode = n; break; }
  }
  if (!textNode) return;
  var full = textNode.textContent.replace(/\s+/g, " ").trim();
  if (!full) return;

  // freeze the header's height so content below never shifts while typing
  var header = h1.closest(".page-header");
  if (header) header.style.minHeight = header.offsetHeight + "px";
  h1.setAttribute("aria-label", full);

  var span = document.createElement("span");
  span.className = "type-text";
  span.setAttribute("aria-hidden", "true");
  var caret = document.createElement("span");
  caret.className = "type-caret";
  caret.setAttribute("aria-hidden", "true");
  h1.replaceChild(span, textNode);
  h1.insertBefore(caret, span.nextSibling);

  var extras = [];
  Array.prototype.slice.call(h1.children).forEach(function (el) {
    if (el !== span && el !== caret) {
      el.classList.add("type-extra");
      extras.push(el);
    }
  });

  // brisk cadence, scaled so long document titles never drag (~0.7s total)
  var per = Math.max(14, Math.min(38, Math.round(680 / full.length)));
  var pos = 0;

  function step() {
    pos += 1;
    span.textContent = full.slice(0, pos);
    if (pos < full.length) {
      wait(per, step);
      return;
    }
    extras.forEach(function (el) { el.classList.add("type-extra-in"); });
    caret.classList.add("type-caret-done");
    setTimeout(function () { caret.remove(); }, 1100);
  }

  wait(140, step);
})();

/* MUNDP 2027 — welcome experience, ported verbatim from modelundp.org's
   intro.js for MyDP. Adaptations are marked "MyDP port": the collage reads
   its image base from a data attribute (24 photos), and the overlay keeps
   MyDP's trigger behavior — it autoplays once per browser session on the
   sign-in page (data-autoplay omitted) and only opens on demand where
   data-autoplay="off" (the homescreen's Intro button).
   Drives the full-screen, scroll-linked intro overlay.
   Progressive enhancement only: without this script .intro-overlay stays
   in normal document flow (see the base rules in intro.css), so nothing
   here is load-bearing for reaching the site.

   Architecture: .intro-overlay is promoted to a fixed lightbox covering the
   whole viewport; .intro-scroll is ITS OWN scrollable box (not the page) —
   scrolling that box, not window, drives the story. The real page scroll
   position never moves, so the homepage underneath is simply revealed the
   instant the overlay closes.

   The overlay never auto-opens: a head-script sets .mundp-intro-seen
   before first paint so every load renders the homepage straight away
   with zero flash, and the experience plays only on demand via the
   floating play button.

   Motion is driven by a lerped "smooth" progress value that trails the raw
   scroll position (smooth += (raw - smooth) * EASE each frame) rather than
   binding 1:1 to scroll — the same trick behind the silky, slightly
   trailing feel of Apple's product pages. The ticker keeps running for a
   few frames after the user stops scrolling so everything glides to rest
   instead of snapping.

   Text doesn't just fade in as a block: every beat past the welcome is
   split into individual words (wrapWords), and each word's opacity/blur/
   chromatic fringe is driven continuously by scroll position within that
   beat's own window — the classic Apple "the words write themselves in as
   you scroll" effect, rather than sliding between static pages. */
(function () {
  "use strict";

  var overlay = document.getElementById("intro-overlay");
  var scrollEl = document.getElementById("intro-scroll");
  var section = document.getElementById("intro-experience");
  var replayBtn = document.getElementById("intro-replay");
  if (!overlay || !scrollEl || !section) return;

  var reduceMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduceMotion) {
    /* stays in the static, in-flow fallback (see intro.css) — no overlay,
       no scroll-jacking, just a calm welcome panel at the top of the page */
    return;
  }

  var stage = section.querySelector(".intro-stage");
  var mark = section.querySelector(".intro-mark");
  var cue = section.querySelector(".intro-scrollcue");
  var beats = Array.prototype.slice.call(section.querySelectorAll(".intro-beat"));
  var dots = Array.prototype.slice.call(section.querySelectorAll(".intro-dot"));
  var count = beats.length || 1;
  var EASE = 0.1;
  var SETTLE_EPSILON = 0.0006;
  var REVEAL_WINDOW = 0.6; // words finish writing by 60% through a beat's window, leaving a calm hold before it exits
  var REVEAL_BAND = 0.5;   // how many words are mid-transition at once (softness of the writing band)

  section.classList.add("intro-js");
  overlay.classList.add("intro-js");
  document.documentElement.classList.add("intro-js-ready");

  function clamp01(v) {
    return Math.min(Math.max(v, 0), 1);
  }

  /* splits an element's text into per-word spans (.intro-word), leaving
     <br> and child elements (e.g. .intro-shine) intact as single reveal
     units — used so every beat past the welcome can "write itself in"
     word by word as you scroll, rather than appearing as a solid block. */
  function wrapWords(el) {
    Array.prototype.slice.call(el.childNodes).forEach(function (node) {
      if (node.nodeType === 3) {
        var frag = document.createDocumentFragment();
        node.textContent.split(/(\s+)/).forEach(function (part) {
          if (part === "") return;
          if (/^\s+$/.test(part)) {
            frag.appendChild(document.createTextNode(part));
          } else {
            var span = document.createElement("span");
            span.className = "intro-word";
            span.textContent = part;
            frag.appendChild(span);
          }
        });
        el.replaceChild(frag, node);
      } else if (node.nodeType === 1 && node.tagName !== "BR") {
        node.classList.add("intro-word");
      }
    });
  }

  beats.forEach(function (beat, i) {
    beat.__feature = beat.querySelector(".intro-feature");
    beat.__featureInner = beat.querySelector(".intro-feature-inner");
    beat.__cta = beat.querySelector(".intro-cta");
    if (i === 0) return; // the welcome moment stays static — nothing to "write in" before any scroll
    Array.prototype.slice
      .call(beat.querySelectorAll(".intro-eyebrow, .intro-heading, .intro-sub"))
      .forEach(wrapWords);
    beat.__words = Array.prototype.slice.call(beat.querySelectorAll(".intro-word"));
  });

  /* photo collage backdrop: every supplied conference photo, tiled into
     vertical reels that roll past at low opacity behind the beats (see
     .intro-collage in intro.css). Each reel is built taller than the
     viewport and alternates roll direction, driven purely off the same
     --intro-progress custom property everything else in the backdrop
     already reacts to — no per-frame JS needed for the motion itself.
     There are far more tiles than source photos, so tiles repeat freely,
     but every photo is guaranteed at least one appearance per lap through
     the shuffled deck (see COLLAGE_PHOTOS below — bump it whenever photos
     are added to assets/img/collage), and each tile gets its own random
     crop (position + zoom) so repeats never look identical. Rebuilt on
     resize (debounced). */
  var collage = document.getElementById("intro-collage");
  if (collage) {
    /* MyDP port: Flask static path + full 24-photo deck */
    var IMG_BASE = collage.getAttribute("data-img-base") || "/static/img/collage/";
    var COLLAGE_PHOTOS = 24;
    var TILE_H = 190; // px — keep in sync with --intro-tile-h in intro.css
    var REEL_OVERSHOOT = 0.9; // extra reel height, as a fraction of viewport height, available to roll through

    function shuffledDeck() {
      var deck = [];
      for (var i = 1; i <= COLLAGE_PHOTOS; i++) deck.push(i);
      for (var j = deck.length - 1; j > 0; j--) {
        var k = Math.floor(Math.random() * (j + 1));
        var tmp = deck[j]; deck[j] = deck[k]; deck[k] = tmp;
      }
      return deck;
    }

    var buildCollage = function () {
      var w = collage.clientWidth || window.innerWidth;
      var h = collage.clientHeight || window.innerHeight;
      var reelCount = Math.max(4, Math.round(w / 200));
      var rows = Math.ceil((h * (1 + REEL_OVERSHOOT)) / TILE_H) + 1;
      var reelHeight = rows * TILE_H;
      var overshootPx = Math.max(reelHeight - h, 0);

      if (collage.childElementCount === reelCount && collage.__rows === rows) return;
      collage.__rows = rows;

      // a running shuffled deck consumed across every tile in every reel —
      // guarantees each photo surfaces an equal number of times (once per
      // lap through the deck) rather than leaving inclusion to plain chance.
      var deck = shuffledDeck();
      var deckPos = 0;
      function nextPhoto() {
        if (deckPos >= deck.length) {
          deck = shuffledDeck();
          deckPos = 0;
        }
        return deck[deckPos++];
      }

      var frag = document.createDocumentFragment();
      for (var r = 0; r < reelCount; r++) {
        var reel = document.createElement("div");
        reel.className = "intro-collage-reel";
        var dir = r % 2 === 0 ? -1 : 1;
        reel.style.setProperty("--intro-reel-base", (dir === 1 ? -overshootPx : 0) + "px");
        reel.style.setProperty("--intro-reel-shift", (dir === 1 ? overshootPx : -overshootPx) + "px");

        for (var i = 0; i < rows; i++) {
          var n = nextPhoto();
          var img = document.createElement("img");
          img.loading = "lazy";
          img.decoding = "async";
          img.alt = "";
          img.src = IMG_BASE + "c" + (n < 10 ? "0" + n : n) + ".jpg";
          img.style.setProperty("--intro-tile-scale", (1.05 + Math.random() * 0.35).toFixed(3));
          img.style.objectPosition =
            (10 + Math.random() * 80).toFixed(0) + "% " + (10 + Math.random() * 80).toFixed(0) + "%";
          reel.appendChild(img);
        }
        frag.appendChild(reel);
      }
      collage.innerHTML = "";
      collage.appendChild(frag);
    };

    /* built lazily by openIntro() — the overlay only plays on demand, so
       building ~80 tiles at page load just stalled the homepage's first
       paint for nothing */
    var collageResizeTimer = null;
    window.addEventListener("resize", function () {
      if (!collage.childElementCount) return; // never opened yet
      clearTimeout(collageResizeTimer);
      collageResizeTimer = setTimeout(buildCollage, 200);
    }, { passive: true });
  }

  function rawProgress() {
    var total = scrollEl.scrollHeight - scrollEl.clientHeight;
    return total > 0 ? clamp01(scrollEl.scrollTop / total) : 0;
  }

  var smooth = 0;
  var raf = null;
  var running = false;
  var isOpen = false;

  function render(progress) {
    stage.style.setProperty("--intro-progress", progress.toFixed(4));

    var scaled = progress * count;
    var halfFade = 0.16;

    beats.forEach(function (beat, i) {
      var opacity = 1;

      // fade out toward the next beat as we approach the shared boundary
      if (i < count - 1) {
        var rb = i + 1;
        var rt0 = rb - halfFade, rt1 = rb + halfFade;
        if (scaled > rt0) {
          opacity = Math.min(opacity, 1 - clamp01((scaled - rt0) / (rt1 - rt0)));
        }
      }

      // fade in from the previous beat across that same shared boundary
      if (i > 0) {
        var lb = i;
        var lt0 = lb - halfFade, lt1 = lb + halfFade;
        if (scaled < lt1) {
          opacity = Math.min(opacity, clamp01((scaled - lt0) / (lt1 - lt0)));
        }
      }

      var lift = (1 - opacity) * 26;
      var scale = 0.97 + opacity * 0.03;
      beat.style.opacity = opacity.toFixed(3);
      beat.style.transform = "translateY(" + lift.toFixed(1) + "px) scale(" + scale.toFixed(3) + ")";
      beat.classList.toggle("is-active", opacity > 0.5);

      // local progress through this beat's own dedicated window (0 → 1),
      // independent of the container crossfade above — this is what drives
      // the continuous "writing" and card reveal, so scrolling a pixel
      // further always writes a little more, never jumps a whole segment
      var local = clamp01(scaled - i);

      // continuous word-by-word "writing" reveal
      if (beat.__words && beat.__words.length) {
        var reveal = clamp01(local / REVEAL_WINDOW) * beat.__words.length;
        beat.__words.forEach(function (word, k) {
          var wp = clamp01((reveal - k) / REVEAL_BAND);
          word.style.opacity = (0.22 + wp * 0.78).toFixed(3);
          word.style.filter = wp < 1 ? "blur(" + ((1 - wp) * 3).toFixed(2) + "px)" : "";
          word.style.textShadow =
            wp < 0.999
              ? (1 - wp) * 2.2 + "px 0 rgba(255,70,120,.55), " + (-(1 - wp) * 2.2) + "px 0 rgba(70,190,255,.55)"
              : "";
        });
      }

      // the feature peek / CTA fade in right after the words finish writing
      // — continuously, from the same local progress, never a fixed-time pop
      var afterText = clamp01((local - REVEAL_WINDOW) / 0.2);
      if (beat.__feature) {
        beat.__feature.style.opacity = afterText.toFixed(3);
        beat.__feature.style.transform = "translateY(" + ((1 - afterText) * 14).toFixed(1) + "px)";
        beat.__feature.classList.toggle("is-revealed", afterText > 0.03);
      }
      if (beat.__featureInner) {
        beat.__featureInner.style.setProperty("--sheen", (afterText * 260 - 130).toFixed(1));
      }
      if (beat.__cta) {
        beat.__cta.style.opacity = afterText.toFixed(3);
        beat.__cta.style.transform = "translateY(" + ((1 - afterText) * 14).toFixed(1) + "px)";
      }
    });

    var activeIndex = Math.min(Math.floor(scaled), count - 1);
    dots.forEach(function (dot, i) {
      dot.classList.toggle("is-active", i === activeIndex);
    });

    if (mark) {
      var markScale = 1 - progress * 0.35;
      var markOpacity = progress < 0.22 ? 1 : Math.max(1 - (progress - 0.22) / 0.22, 0.16);
      mark.style.transform = "translateX(-50%) translateY(" + (-progress * 46).toFixed(1) + "px) scale(" + markScale.toFixed(3) + ")";
      mark.style.opacity = markOpacity.toFixed(3);
    }

    if (cue) {
      cue.style.opacity = progress > 0.045 ? "0" : "1";
    }
  }

  function tick() {
    raf = null;
    var target = rawProgress();
    var delta = target - smooth;

    if (Math.abs(delta) < SETTLE_EPSILON) {
      smooth = target;
      render(smooth);
      running = false;
      return;
    }

    smooth += delta * EASE;
    render(smooth);
    raf = requestAnimationFrame(tick);
  }

  function kick() {
    if (!isOpen || running) return;
    running = true;
    raf = requestAnimationFrame(tick);
  }

  function lockPage() {
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
  }

  function unlockPage() {
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
  }

  function openIntro() {
    isOpen = true;
    if (typeof buildCollage === "function") buildCollage(); // deferred from page load
    document.documentElement.classList.remove("mundp-intro-seen");
    overlay.classList.remove("is-closed");
    overlay.setAttribute("aria-hidden", "false");
    lockPage();
    scrollEl.scrollTop = 0;
    smooth = 0;
    render(0);
    running = true;
    raf = requestAnimationFrame(tick);
  }

  /* MyDP port: closing marks the intro seen for this browser session so
     the sign-in page only autoplays it once (see the head guard script in
     _intro.html, which applies .mundp-intro-seen before first paint) */
  function markSeen() {
    try { sessionStorage.setItem("mydp-intro-seen", "1"); } catch (e) { /* ignore */ }
    document.documentElement.classList.add("mundp-intro-seen");
  }

  function closeIntro() {
    if (!isOpen) return;
    isOpen = false;
    overlay.classList.add("is-closed");
    overlay.setAttribute("aria-hidden", "true");
    markSeen();
    unlockPage();
    if (raf !== null) {
      cancelAnimationFrame(raf);
      raf = null;
    }
    running = false;
  }

  scrollEl.addEventListener("scroll", kick, { passive: true });
  window.addEventListener("resize", kick, { passive: true });

  // MyDP port: the sign-in page autoplays the intro once per browser
  // session (the site itself only plays on demand); pages carrying
  // data-autoplay="off" — the homescreen — open it only via their button.
  var autoplay = overlay.getAttribute("data-autoplay") !== "off";
  var alreadySeen = false;
  try { alreadySeen = !!sessionStorage.getItem("mydp-intro-seen"); } catch (e) { /* ignore */ }
  if (autoplay && !alreadySeen) {
    openIntro();
  } else {
    document.documentElement.classList.add("mundp-intro-seen");
  }

  Array.prototype.slice
    .call(section.querySelectorAll(".intro-skip, .intro-cta"))
    .forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        closeIntro();
      });
    });

  if (replayBtn) {
    replayBtn.addEventListener("click", openIntro);
  }

  /* pointer-reactive tilt on the card-style feature peeks (fine pointers
     only) — only the currently active beat is ever hit-testable (inactive
     beats inherit pointer-events: none), so this naturally only responds
     to whichever card is on screen. */
  if (window.matchMedia && window.matchMedia("(pointer: fine)").matches) {
    Array.prototype.slice
      .call(section.querySelectorAll(".intro-feature-inner"))
      .forEach(function (el) {
        el.addEventListener("mousemove", function (e) {
          var r = el.getBoundingClientRect();
          var x = (e.clientX - r.left) / r.width - 0.5;
          var y = (e.clientY - r.top) / r.height - 0.5;
          el.style.transform =
            "perspective(700px) rotateX(" + (y * -8).toFixed(2) + "deg) rotateY(" + (x * 8).toFixed(2) + "deg)";
        });
        el.addEventListener("mouseleave", function () {
          el.style.transform = "";
        });
      });
  }
})();

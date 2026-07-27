/* MyDP — sign-in page "welcome" intro.
   Trimmed port of the reference marketing site's scroll-lerp intro engine
   (see static/css/intro.css for the full design note). Progressive
   enhancement only: without this script .intro-overlay stays in normal
   document flow showing beat one (see the base rules in intro.css), so
   nothing here is load-bearing for reaching the sign-in form.

   Architecture: .intro-overlay is promoted to a fixed lightbox covering the
   whole viewport; .intro-scroll is ITS OWN scrollable box (not the page) —
   scrolling that box, not window, drives the story. The real page never
   scrolls, so the sign-in form underneath is simply revealed the instant
   the overlay closes.

   Motion is driven by a lerped ("trailing") progress value rather than a
   1:1 scroll bind: smooth += (raw - smooth) * EASE each frame, the same
   trick behind the silky feel of the reference site's product-page-style
   scroll animation. The ticker keeps running a few frames after scrolling
   stops so everything glides to rest instead of snapping.

   Every element lookup is defensive (null-checked) — a missing or renamed
   element in the markup should never throw, only quietly disable the
   affected bit of the experience. */
(function () {
  "use strict";

  var SEEN_KEY = "mydp-intro-seen";
  var html = document.documentElement;

  var overlay = document.getElementById("intro-overlay");
  var scrollEl = document.getElementById("intro-scroll");
  var experience = document.getElementById("intro-experience");
  var replayBtn = document.getElementById("intro-replay");

  // Nothing to enhance at all — bail out entirely, leaving the static
  // in-flow fallback exactly as intro.css rendered it.
  if (!overlay || !scrollEl || !experience) return;

  // Pages that host the intro for on-demand replay only (the signed-in
  // homepage) mark the overlay data-autoplay="off": never self-open there,
  // only the "Intro" button does.
  var autoplay = overlay.getAttribute("data-autoplay") !== "off";

  // ---------------- photo collage ----------------
  // Builds the vertical-reel photo collage from the conference photos listed
  // in #intro-collage-data. Runs unconditionally (even under reduced-motion
  // or an already-seen session) so the backdrop looks right the moment the
  // overlay is shown again via the "Bored?" replay button, or statically
  // under reduced motion. Even distribution / minimal repetition: deal
  // images round-robin from a shuffled pool, reshuffling whenever the pool
  // is exhausted (so repeats never fall into a predictable cycle), and
  // guard against the same photo landing twice in a row within one reel.
  (function buildCollage() {
    var collageEl = document.getElementById("intro-collage");
    var dataEl = document.getElementById("intro-collage-data");
    if (!collageEl || !dataEl) return;

    var urls;
    try {
      urls = JSON.parse(dataEl.textContent || "[]");
    } catch (e) {
      urls = [];
    }
    if (!urls.length) return;

    var reelCount = window.innerWidth <= 640 ? 3 : (window.innerWidth <= 900 ? 5 : 7);
    var tileH = window.innerWidth <= 640 ? 150 : 210;
    var shiftRange = 240;
    var tilesPerReel = Math.max(4, Math.ceil((window.innerHeight + shiftRange * 2) / tileH) + 1);

    function shuffled(arr) {
      var a = arr.slice();
      for (var i = a.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = a[i];
        a[i] = a[j];
        a[j] = tmp;
      }
      return a;
    }

    var pool = shuffled(urls);
    var poolIndex = 0;
    function nextImage(lastForReel) {
      if (poolIndex >= pool.length) {
        pool = shuffled(urls);
        poolIndex = 0;
      }
      var candidate = pool[poolIndex++];
      if (candidate === lastForReel && urls.length > 1) {
        if (poolIndex >= pool.length) {
          pool = shuffled(urls);
          poolIndex = 0;
        }
        var swap = pool[poolIndex - 1];
        pool[poolIndex - 1] = pool[poolIndex];
        pool[poolIndex] = swap;
        candidate = pool[poolIndex - 1];
        poolIndex++;
      }
      return candidate;
    }

    var frag = document.createDocumentFragment();
    for (var r = 0; r < reelCount; r++) {
      var reel = document.createElement("div");
      reel.className = "intro-collage-reel";
      reel.style.setProperty("--intro-tile-h", tileH + "px");
      // Reels alternate direction. The translate must never go positive —
      // a reel whose content top slides below the viewport top leaves a
      // blank band above it at the end of the journey. Downward-moving
      // (even) reels therefore start pre-lifted by their full travel, so
      // they end exactly at their stagger offset instead of +shiftRange.
      var stagger = (r * 47) % 140;
      var base = r % 2 === 0 ? -(shiftRange + stagger) : -stagger;
      reel.style.setProperty("--intro-reel-shift", (r % 2 === 0 ? shiftRange : -shiftRange) + "px");
      reel.style.setProperty("--intro-reel-base", base + "px");
      var last = null;
      for (var t = 0; t < tilesPerReel; t++) {
        var src = nextImage(last);
        last = src;
        var img = document.createElement("img");
        img.src = src;
        img.alt = "";
        img.loading = "lazy";
        reel.appendChild(img);
      }
      frag.appendChild(reel);
    }
    collageEl.appendChild(frag);
  })();

  function markSeen() {
    try { sessionStorage.setItem(SEEN_KEY, "1"); } catch (e) { /* ignore */ }
    html.classList.add("mydp-intro-seen");
  }

  var alreadySeen = false;
  try { alreadySeen = !!sessionStorage.getItem(SEEN_KEY); } catch (e) { /* ignore */ }
  if (alreadySeen) {
    html.classList.add("mydp-intro-seen");
  }

  // "Skip intro" and "Enter the site" both point at #main-content. Wire
  // them so the anchor jump isn't fighting a still-visible fixed overlay —
  // close it and remember the session regardless of which state the
  // engine below ends up in.
  var exitEls = overlay.querySelectorAll(".intro-skip, .intro-cta");
  for (var i = 0; i < exitEls.length; i++) {
    exitEls[i].addEventListener("click", function () {
      overlay.classList.add("is-closed");
      markSeen();
    });
  }

  var reduceMotion = false;
  try {
    reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (e) { /* ignore */ }

  if (reduceMotion) {
    // No scroll-jacking, no lightbox promotion, no rAF loop. intro.css's
    // reduced-motion + default rules already render beat one statically in
    // normal flow. There is nothing to replay, so .intro-js-ready (which
    // reveals the "Bored?" pill) is intentionally never added.
    return;
  }

  // ---------------- full engine (motion allowed) ----------------

  var stage = experience.querySelector(".intro-stage");
  var mark = experience.querySelector(".intro-mark");
  var cue = experience.querySelector(".intro-scrollcue");
  var beats = Array.prototype.slice.call(experience.querySelectorAll(".intro-beat"));
  var dots = Array.prototype.slice.call(experience.querySelectorAll(".intro-dot"));
  var count = beats.length || 1;

  var EASE = 0.1;
  var SETTLE_EPSILON = 0.0006;
  var REVEAL_AT = 0.4; // fraction into a beat's own window before its chip row reveals

  function clamp01(v) {
    return Math.min(Math.max(v, 0), 1);
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
    if (stage) stage.style.setProperty("--intro-progress", progress.toFixed(4));

    // Total scroll range divided evenly across the beat count — each beat
    // "owns" the viewport for one full unit of `scaled`.
    var scaled = progress * count;
    var activeIndex = Math.min(Math.floor(scaled), count - 1);

    beats.forEach(function (beat, idx) {
      var isActive = idx === activeIndex;
      beat.classList.toggle("is-active", isActive);

      var local = clamp01(scaled - idx);
      var chipRow = beat.querySelector(".intro-feature--stats, .intro-feature--highlights");
      if (chipRow) {
        chipRow.classList.toggle("is-revealed", local >= REVEAL_AT);
      }
    });

    dots.forEach(function (dot, idx) {
      dot.classList.toggle("is-active", idx === activeIndex);
    });

    var pastWelcome = progress > 0.035;
    if (mark) mark.classList.toggle("is-hidden", pastWelcome);
    if (cue) cue.classList.toggle("is-hidden", pastWelcome);
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
    overlay.classList.add("intro-js");
    experience.classList.add("intro-js");
    isOpen = true;
    html.classList.remove("mydp-intro-seen");
    overlay.classList.remove("is-closed");
    overlay.setAttribute("aria-hidden", "false");
    lockPage();
    scrollEl.scrollTop = 0;
    smooth = 0;
    render(0);
    running = true;
    raf = requestAnimationFrame(tick);
  }

  function closeIntro() {
    if (!isOpen) return;
    isOpen = false;
    overlay.classList.add("is-closed");
    overlay.setAttribute("aria-hidden", "true");
    unlockPage();
    if (raf !== null) {
      cancelAnimationFrame(raf);
      raf = null;
    }
    running = false;
  }

  // Re-close on the same click that already marked the session seen above.
  for (var j = 0; j < exitEls.length; j++) {
    exitEls[j].addEventListener("click", closeIntro);
  }

  scrollEl.addEventListener("scroll", kick, { passive: true });
  window.addEventListener("resize", kick, { passive: true });

  // If the tab is backgrounded mid-animation (alt-tab, app switch, minimize),
  // the rAF loop is paused/dropped by the browser and never fires again —
  // `running` would otherwise stay stuck true forever, silently ignoring
  // every scroll event once the user comes back. Reset and re-kick on return.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && isOpen) {
      running = false;
      kick();
    }
  });

  html.classList.add("intro-js-ready");

  if (replayBtn) {
    replayBtn.addEventListener("click", function () {
      try { sessionStorage.removeItem(SEEN_KEY); } catch (e) { /* ignore */ }
      openIntro();
    });
  }

  // Only auto-open on a genuinely fresh session, and only on pages that
  // want autoplay (the login page). An already-seen session leaves the
  // overlay in its default (static, in-flow) state — hidden outright by
  // the .mydp-intro-seen rule in intro.css — so the sign-in form
  // underneath renders immediately. The homepage "Intro" button (wired
  // above) can still bring the full experience back at any time.
  if (!alreadySeen && autoplay) {
    markSeen();
    openIntro();
  }
})();

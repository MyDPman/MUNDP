/* Floating collage — a double-helix "spiral staircase" of tiny conference
   photos (static/img/collage/c01–c24), ported verbatim from modelundp.org's
   hero-float.js. Cards are the steps of two intertwined strands (offset half
   a turn, so consecutive cards face each other across the axis like the
   logo's ribbon pairs); the helix slowly rotates on its own, leans toward
   the mouse with depth parallax, and each card keeps a small personal
   wobble so the structure stays alive without falling apart. Depth drives
   scale, stacking and the navy fog veil. Styles live in hero-float.css.

   Every element with class "hero-float" becomes a helix host — full-page
   heroes and shorter in-flow bands alike. Set data-img-base on the host
   to point at the collage directory. Card count scales with the host's
   area (a short band gets proportionally fewer tiles); data-count pins an
   exact number instead.

   Under prefers-reduced-motion a single static frame is rendered — the
   helix still appears, it just holds still. */
(function () {
  "use strict";

  var hosts = document.querySelectorAll(".hero-float");
  if (!hosts.length) return;

  var PHOTO_COUNT = 24;
  var MAX_CARDS = PHOTO_COUNT * 6; // six copies of each photo, at most
  var TWIST = Math.PI * 3; // total twist per strand → three ribbon crossings, like the logo

  var reduceMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Portrait / landscape / square-ish mix, like a real pinboard.
  var ASPECTS = [0.74, 0.78, 1, 1.28, 1.42];

  function rand(a, b) {
    return a + Math.random() * (b - a);
  }

  function shuffle(arr) {
    for (var j = arr.length - 1; j > 0; j--) {
      var k = Math.floor(Math.random() * (j + 1));
      var tmp = arr[j]; arr[j] = arr[k]; arr[k] = tmp;
    }
    return arr;
  }

  // Repeat the photo deck (freshly shuffled each pass) until the card
  // count is filled — copies of one photo end up ~a deck apart, never bunched.
  function photoPool(count) {
    var pool = [];
    while (pool.length < count) {
      var deck = [];
      for (var n = 1; n <= PHOTO_COUNT; n++) deck.push(n);
      pool = pool.concat(shuffle(deck));
    }
    return pool.slice(0, count);
  }

  // Shared mouse-parallax target; each host eases toward it in its own loop.
  var mxT = 0, myT = 0;
  if (!reduceMotion && window.matchMedia && window.matchMedia("(pointer: fine)").matches) {
    window.addEventListener("pointermove", function (e) {
      mxT = (e.clientX / window.innerWidth) * 2 - 1;
      myT = (e.clientY / window.innerHeight) * 2 - 1;
    }, { passive: true });
  }

  function setup(host) {
    var imgBase = host.getAttribute("data-img-base") || "/static/img/collage/";
    var pinnedCount = parseInt(host.getAttribute("data-count"), 10) || 0;

    // pro variant: calmer, more deliberate motion, slightly right-shifted
    // axis on wide screens, staggered entrance, film grain
    var pro = host.classList.contains("hero-float--pro");
    var CALM = pro ? 0.6 : 1;
    var YAW_SPEED = pro ? 0.085 : 0.12;
    var MOUSE_YAW = pro ? 0.28 : 0.3;
    var MOUSE_PITCH = pro ? 0.2 : 0.22;
    var PITCH_AMP = pro ? 0.07 : 0.1;
    var OX = 0; // horizontal offset of the helix axis, set in layout()
    var TANG_DY = 0; // ribbon slope constant, set in layout()

    var cards = [];
    var W = 0, H = 0, RX = 0, RY = 0, sizeScale = 1;
    var startShift = rand(0, Math.PI * 2); // a different arrangement every visit

    var inView = true;
    var raf = null;
    var last = null;
    var elapsed = 0;

    // eased mouse-parallax state for this host
    var mx = 0, my = 0;
    var prevT = 0;

    function build() {
      W = host.clientWidth;
      H = host.clientHeight;
      if (W < 50 || H < 50) {
        // measured before the section had real dimensions — try again next frame
        requestAnimationFrame(build);
        return;
      }

      // scale tile count with the section's area: the full-height hero gets
      // the whole deck-of-six, a short band proportionally fewer
      var TOTAL = pinnedCount ||
        Math.max(38, Math.min(MAX_CARDS, Math.round(MAX_CARDS * (W * H) / (1440 * 900))));

      var pool = photoPool(TOTAL);
      for (var i = 0; i < TOTAL; i++) {
        var photo = pool[i];
        var fig = document.createElement("figure");
        fig.className = "hero-float-card";
        var img = document.createElement("img");
        img.src = imgBase + "c" + (photo < 10 ? "0" + photo : photo) + ".jpg";
        img.alt = "";
        img.decoding = "async";
        img.style.objectPosition = rand(20, 80).toFixed(0) + "% " + rand(15, 60).toFixed(0) + "%";
        var fog = document.createElement("span");
        fog.className = "hero-float-fog";
        fig.appendChild(img);
        fig.appendChild(fog);
        host.appendChild(fig);

        // Double-helix step: even cards on strand A, odd on strand B (half a
        // turn apart), each strand descending top→bottom while twisting.
        var strand = i % 2;
        var strandCount = strand === 0 ? Math.ceil(TOTAL / 2) : Math.floor(TOTAL / 2);
        var hf = (Math.floor(i / 2) + 0.5) / strandCount; // 0 = top … 1 = bottom

        cards.push({
          el: fig,
          fog: fog,
          theta0: strand * Math.PI + hf * TWIST,
          h: hf * 2 - 1, // vertical position along the axis, in [-1, 1]
          baseW: pro ? rand(58, 96) : rand(52, 92),
          aspect: ASPECTS[i % ASPECTS.length],
          // near-rigid: the staircase must turn as one piece, with only a
          // whisper of shear so it doesn't feel machine-made
          yawScale: rand(0.995, 1.005),
          wobXAmp: rand(3, 8) * CALM,
          wobYAmp: rand(3, 7) * CALM,
          wobXFreq: rand(0.25, 0.6),
          wobYFreq: rand(0.22, 0.55),
          wobXPhase: rand(0, Math.PI * 2),
          wobYPhase: rand(0, Math.PI * 2),
          rot0: rand(-4, 4) * CALM,
          rotAmp: rand(1, 3) * CALM,
          rotFreq: rand(0.15, 0.4),
          rotPhase: rand(0, Math.PI * 2),
          zIndex: null
        });

        // entrance cascade: tiles fade in top-to-bottom along the strands
        if (pro && !reduceMotion) {
          fig.style.animationDelay = (i * 12) + "ms";
        }
      }

      if (pro) {
        var grain = document.createElement("span");
        grain.className = "hero-float-grain";
        host.appendChild(grain);
      }

      layout();
      requestAnimationFrame(function () {
        host.classList.add("is-live");
      });

      var resizeTimer = null;
      window.addEventListener("resize", function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(layout, 150);
      }, { passive: true });

      if (reduceMotion) return; // static helix only

      if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (entries) {
          inView = entries[0].isIntersecting;
          if (inView) schedule();
          else halt();
        }, { threshold: 0.02 }).observe(host);
      }

      schedule();
    }

    function layout() {
      W = host.clientWidth || W;
      H = host.clientHeight || H;
      RX = Math.min(Math.max(W * 0.34, 150), 520); // helix radius
      RY = H * 0.5; // half-height of the staircase (slight top/bottom overshoot)
      sizeScale = Math.min(Math.max(W / 1440, 0.52), 1.12);
      // pro: nudge the axis right on wide screens, clearing the headline column
      OX = pro && W >= 900 ? W * 0.07 : 0;
      // vertical screen distance a strand covers per radian of twist —
      // used to align pro tiles with the ribbon's local direction
      TANG_DY = (2 * RY) / TWIST;

      var compact = W < 640;
      for (var i = 0; i < cards.length; i++) {
        var c = cards[i];
        // cap width against the helix radius so the two strands stay
        // visually separate instead of smearing into one column
        var w = Math.min(c.baseW * sizeScale * (compact ? 0.82 : 1), RX * 0.72);
        c.el.style.width = w.toFixed(0) + "px";
        c.el.style.height = (w / c.aspect).toFixed(0) + "px";
      }
      render(elapsed); // reposition immediately, even when the loop is idle
    }

    function render(t) {
      var dt = Math.min(Math.max(t - prevT, 0), 0.1);
      prevT = t;
      var ease = Math.min(1, dt * 6.5);
      mx += (mxT - mx) * ease;
      my += (myT - my) * ease;

      // the whole staircase turns on its own and leans toward the cursor…
      var yaw = startShift + t * YAW_SPEED + mx * MOUSE_YAW;
      var pitch = PITCH_AMP * Math.sin(t * 0.07) - my * MOUSE_PITCH;
      var cosP = Math.cos(pitch);
      var sinP = Math.sin(pitch);

      for (var i = 0; i < cards.length; i++) {
        var c = cards[i];

        // position on the turning helix, then a slight pitch around X
        var th = c.theta0 + yaw * c.yawScale;
        var x = Math.cos(th) * RX;
        var z3 = Math.sin(th) * RX;
        var y3 = c.h * RY;
        var y = y3 * cosP - z3 * sinP;
        var z = y3 * sinP + z3 * cosP;

        var depth = Math.min(Math.max((z / RX + 1) / 2, 0), 1); // 0 = far, 1 = near

        // …and near cards slide more than far ones, for real depth parallax
        // (CALM tames only the idle wobble — mouse response stays full)
        var px = OX + x + c.wobXAmp * Math.sin(t * c.wobXFreq + c.wobXPhase) -
          mx * (16 + 66 * depth);
        var py = y + c.wobYAmp * Math.sin(t * c.wobYFreq + c.wobYPhase) -
          my * (12 + 50 * depth);
        var scale = 0.5 + 0.62 * depth;
        var rot;
        if (pro) {
          // align each tile with the ribbon's local direction, like the
          // flat angled segments of the logo — clamped so photos stay
          // legible where the strand turns near-vertical at the sides
          var dxd = -Math.sin(th) * RX;
          var dyd = TANG_DY;
          if (dxd < 0) { dxd = -dxd; dyd = -dyd; }
          var tang = Math.atan2(dyd, dxd) * 57.29578;
          if (tang > 32) tang = 32; else if (tang < -32) tang = -32;
          rot = tang * 0.9 + c.rotAmp * Math.sin(t * c.rotFreq + c.rotPhase);
        } else {
          rot = c.rot0 + c.rotAmp * Math.sin(t * c.rotFreq + c.rotPhase);
        }

        c.el.style.transform =
          "translate(-50%, -50%) translate3d(" + px.toFixed(1) + "px, " + py.toFixed(1) +
          "px, 0) rotate(" + rot.toFixed(2) + "deg) scale(" + scale.toFixed(3) + ")";

        // photos stay opaque — far ones sink into the navy via the fog veil;
        // write only on real change so the fogs don't dirty style every frame
        var fogOp = 0.8 * (1 - depth);
        if (c.fogOp === undefined || Math.abs(fogOp - c.fogOp) > 0.012) {
          c.fogOp = fogOp;
          c.fog.style.opacity = fogOp.toFixed(3);
        }

        // hysteresis: reorder only on a clear depth change, so two tiles at
        // near-equal depth stop swapping stacking order every other frame
        var zi = Math.round(depth * 48);
        if (c.zIndex === null || Math.abs(zi - c.zIndex) >= 2) {
          c.zIndex = zi;
          c.el.style.zIndex = zi;
        }
      }
    }

    // Run the loop only while the host is actually on screen. (No
    // document.hidden gating — browsers already stop rAF in hidden tabs,
    // and some embedded webviews report hidden while clearly visible.)
    function frame(now) {
      raf = null;
      if (last !== null) elapsed += Math.min(now - last, 100) / 1000;
      last = now;
      render(elapsed);
      schedule();
    }

    function schedule() {
      if (inView && raf === null) {
        raf = requestAnimationFrame(frame);
      }
    }

    function halt() {
      if (raf !== null) {
        cancelAnimationFrame(raf);
        raf = null;
      }
      last = null;
    }

    build();
  }

  hosts.forEach(setup);
})();

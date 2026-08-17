/* Masked spiral hero — the MUNDP logo mark itself (static/img/logo-mask.png,
   used as a CSS alpha mask in hero-quilt.css) filled with the intro
   overlay's photo collage, reel for reel, so the helix shape is
   unmistakable and the fill matches the intro exactly. Ported verbatim
   from modelundp.org's hero-spiral.js; the only adaptations are the
   24-photo collage deck and the data-img-base attribute for Flask static
   paths. This script builds the reels; the collage itself is static — no
   motion, no cursor interaction. */
(function () {
  "use strict";

  var host = document.getElementById("hero-spiral");
  if (!host) return;

  var IMG_BASE = host.getAttribute("data-img-base") || "/static/img/collage/";
  var PHOTO_COUNT = 24;

  function shuffle(arr) {
    for (var j = arr.length - 1; j > 0; j--) {
      var k = Math.floor(Math.random() * (j + 1));
      var tmp = arr[j]; arr[j] = arr[k]; arr[k] = tmp;
    }
    return arr;
  }

  // structure: positioner → mask box → parallax wrapper
  // → reel container (intro-style rolling columns) → tiles
  var pos = document.createElement("div");
  pos.className = "hero-spiral-pos";
  var mask = document.createElement("div");
  mask.className = "hero-spiral-mask";
  var par = document.createElement("div");
  par.className = "hero-spiral-par";
  var reels = document.createElement("div");
  reels.className = "hero-spiral-reels";
  par.appendChild(reels);
  mask.appendChild(par);
  pos.appendChild(mask);
  host.appendChild(pos);

  var grain = document.createElement("span");
  grain.className = "hero-float-grain";
  host.appendChild(grain);

  // The fill replicates the intro overlay's collage exactly (see intro.js /
  // intro.css): vertical reels of tiles, 2px gaps, random crop and random
  // zoom per tile, whole collage at low opacity over the navy ground.
  var TILE_H = 132; // px — keep in sync with .hero-spiral-reel img
  var OVERSHOOT = 0; // reels are static; no extra height to roll through

  function buildReels() {
    var w = par.clientWidth || 900;
    var h = par.clientHeight || 900;
    var reelCount = Math.max(5, Math.round(w / 150));
    var rows = Math.ceil((h * (1 + OVERSHOOT)) / TILE_H) + 1;
    var overshootPx = Math.max(rows * TILE_H - h, 0);
    reels.innerHTML = "";

    // running shuffled deck, like the intro: every photo surfaces once per
    // lap before any photo repeats
    var deck = [];
    function nextPhoto() {
      if (!deck.length) {
        for (var n = 1; n <= PHOTO_COUNT; n++) deck.push(n);
        shuffle(deck);
      }
      return deck.pop();
    }

    var frag = document.createDocumentFragment();
    for (var r = 0; r < reelCount; r++) {
      var reel = document.createElement("div");
      reel.className = "hero-spiral-reel";
      // center the overshoot so the static crop shows the middle of each reel
      reel.style.transform = "translate3d(0, " + (-overshootPx / 2).toFixed(0) + "px, 0)";

      for (var i = 0; i < rows; i++) {
        var photo = nextPhoto();
        var img = document.createElement("img");
        img.src = IMG_BASE + "c" + (photo < 10 ? "0" + photo : photo) + ".jpg";
        img.alt = "";
        img.decoding = "async";
        img.style.objectPosition =
          (10 + Math.random() * 80).toFixed(0) + "% " + (10 + Math.random() * 80).toFixed(0) + "%";
        reel.appendChild(img);
      }
      frag.appendChild(reel);
    }
    reels.appendChild(frag);
  }

  buildReels();
  requestAnimationFrame(function () {
    host.classList.add("is-live");
  });

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(buildReels, 200);
  }, { passive: true });
})();

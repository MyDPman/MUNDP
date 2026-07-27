/* MyDP — ambient photo-collage backdrop (sign-in page + homepage).
   Fills #ambient-collage with slow, self-rolling vertical reels of the
   conference photos, reusing the exact image list the intro overlay embeds
   in #intro-collage-data. Purely decorative: the layer is fixed behind the
   page (pointer-events: none, very low opacity — see style.css), reels
   loop seamlessly by animating translateY(-50%) over two identical tile
   halves, and the global prefers-reduced-motion rules freeze the roll.
   Defensive throughout — missing markup or data just means no backdrop. */
(function () {
  "use strict";

  var host = document.getElementById("ambient-collage");
  var dataEl = document.getElementById("intro-collage-data");
  if (!host || !dataEl) return;

  var urls;
  try {
    urls = JSON.parse(dataEl.textContent || "[]");
  } catch (e) {
    urls = [];
  }
  if (!urls.length) return;

  // Guard against a zero/absurd measurement (hidden or not-yet-rendered
  // tab): build for at least a tall laptop viewport so reels are never
  // degenerate, whatever the window reports at script time.
  var vw = Math.max(window.innerWidth || 0, 360);
  var vh = Math.max(window.innerHeight || 0, 820);
  var reelCount = vw <= 640 ? 3 : (vw <= 1024 ? 5 : 7);
  var tileH = vw <= 640 ? 140 : 190;
  var gap = 2;
  // Each half must cover the viewport on its own so the -50% loop never
  // exposes a blank band.
  var perHalf = Math.ceil(vh / (tileH + gap)) + 1;

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
  function nextImage(last) {
    if (poolIndex >= pool.length) {
      pool = shuffled(urls);
      poolIndex = 0;
    }
    var candidate = pool[poolIndex++];
    if (candidate === last && urls.length > 1) {
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

  host.style.setProperty("--ambient-tile-h", tileH + "px");

  var frag = document.createDocumentFragment();
  for (var r = 0; r < reelCount; r++) {
    var reel = document.createElement("div");
    reel.className = "ambient-collage-reel";

    // Build one viewport-covering half, avoiding an immediate repeat both
    // between neighbours and across the loop seam (last tile → first tile).
    var half = [];
    var last = null;
    for (var t = 0; t < perHalf; t++) {
      var src = nextImage(t === perHalf - 1 ? half[0] || last : last);
      half.push(src);
      last = src;
    }

    var seq = half.concat(half);
    for (var k = 0; k < seq.length; k++) {
      var img = document.createElement("img");
      img.src = seq[k];
      img.alt = "";
      img.decoding = "async";
      reel.appendChild(img);
    }

    // Alternate direction; stagger speed and phase so reels drift out of
    // sync like adjacent strips of film. Negative delays start each loop
    // mid-flight instead of all-together at frame zero.
    reel.style.animationName = r % 2 === 0 ? "ambientRollUp" : "ambientRollDown";
    reel.style.animationDuration = (75 + ((r * 13) % 36)) + "s";
    reel.style.animationDelay = "-" + ((r * 19) % 47) + "s";
    frag.appendChild(reel);
  }
  host.appendChild(frag);
})();

// strip_images.js — Remove images to save bandwidth on Windows instances
// Injected via manifest, runs in MAIN world on all PokerBet frames
// Does NOT touch w4p.js or game controls — visual cleanup only
(function() {
  'use strict';

  var STYLE_ID = '_w4p_strip_images';
  if (document.getElementById(STYLE_ID)) return; // already injected

  var style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = [
    'img { display: none !important; }',
    'video { display: none !important; }',
    'svg image { display: none !important; }',
    '[style*="background-image"] { background-image: none !important; }',
    '.banner, .promo, .advertisement, .carousel, [class*="banner"], [class*="promo"] { display: none !important; }',
    '.lobby-banner, .casino-banner, [class*="slider-banner"] { display: none !important; }',
    '.control-b-view-p img, sg-poker-betting-slider img, .f-right-column-p img { display: revert !important; }',
    '.control-b-view-p video, sg-poker-betting-slider video { display: revert !important; }'
  ].join('\n');
  document.head.appendChild(style);

  // Also nuke existing img/video elements to free memory
  function strip() {
    var imgs = document.querySelectorAll('img, video, picture, source[type*="image"]');
    for (var i = 0; i < imgs.length; i++) {
      // Don't remove card images, game-critical elements, or control buttons
      if (imgs[i].closest('.control-b-view-p, sg-poker-betting-slider, .f-right-column-p')) continue;
      var cls = (imgs[i].className || '') + ' ' + (imgs[i].parentElement ? imgs[i].parentElement.className : '');
      if (/card|chip|dealer|avatar|icon-layer|suit/i.test(cls)) continue;
      if (imgs[i].src) imgs[i].src = '';
      if (imgs[i].srcset) imgs[i].srcset = '';
    }
  }

  strip();
  // Re-run periodically as SPA loads new content
  setInterval(strip, 5000);

  console.log('[W4P][STRIP] Image/video removal active — saving bandwidth');
})();

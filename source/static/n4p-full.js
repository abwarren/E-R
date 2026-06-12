(function(){
  'use strict';

  // === N4P-FULL LOAD GUARD ===
  if (window._n4p_full_injected) {
    console.log('[N4P-FULL] Clearing old instance - upgrading');
    if (window._n4p_full_timer) {
      clearInterval(window._n4p_full_timer);
      window._n4p_full_timer = null;
    }
    window._n4p_full_injected = false;
  }

  // === CONFIGURATION ===
  var API_URL = 'http://localhost:5000/api/snapshot';
  var API_KEY = 'trk_default';
  var TICK_MS = 1500;
  var DEBOUNCE_MS = 500;
  var HERO_NAME = 'rollo267';
  var LOG_PREFIX = '[N4P-FULL]';

  // === STATE ===
  var lastHash = '';
  var lastPostTime = 0;
  var postCount = 0;
  var errorCount = 0;

  // === PAGE VISIBILITY ===
  var pageVisible = !document.hidden;
  document.addEventListener('visibilitychange', function() {
    pageVisible = !document.hidden;
    console.log(LOG_PREFIX + ' Page ' + (pageVisible ? 'visible - resuming' : 'hidden - pausing'));
  });

  // === UTILITY: simple string hash for change detection ===
  function hashStr(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) {
      h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    }
    return String(h);
  }

  // === IFRAME DETECTION ===
  function getRootDoc() {
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
      var src = String(frames[i].src || '');
      if (src.indexOf('skillgames') !== -1 || src.indexOf('18751019') !== -1) {
        try {
          var doc = frames[i].contentDocument || (frames[i].contentWindow && frames[i].contentWindow.document);
          if (doc) return doc;
        } catch (e) { /* cross-origin - ignore */ }
      }
    }
    return document;
  }

  // === CARD PARSING ===
  // Parse PokerBet card CSS class: icon-layer2_{suit}{rank}_p-c-d -> "Ah", "Td", etc.
  var RANK_MAP = { a: 'A', k: 'K', q: 'Q', j: 'J', '10': 'T' };
  var CARD_RE = /icon-layer2_([hdcs])(a|k|q|j|10|[2-9])_p-c-d/i;

  function parseCard(cls) {
    if (!cls) return null;
    var tokens = cls.split(/\s+/);
    for (var i = 0; i < tokens.length; i++) {
      var m = tokens[i].match(CARD_RE);
      if (m) {
        var rank = RANK_MAP[m[2].toLowerCase()] || m[2].toUpperCase();
        return rank + m[1].toLowerCase();
      }
    }
    return null;
  }

  function getCardsFromElement(el) {
    if (!el) return [];
    var cards = [], seen = {};
    var els = el.querySelectorAll('.single-cart-view-p');
    for (var i = 0; i < els.length; i++) {
      var c = parseCard(els[i].getAttribute('class') || '');
      if (c && !seen[c]) {
        seen[c] = true;
        cards.push(c);
      }
    }
    return cards;
  }

  // === BOARD CARDS ===
  function getBoard(doc) {
    // Primary: .center-cards-v-p
    var center = doc.querySelector('.center-cards-v-p');
    if (center) {
      var cards = getCardsFromElement(center);
      if (cards.length > 0) return cards;
    }
    // Fallback: sg-poker-board, excluding player cards
    var boardEl = doc.querySelector('sg-poker-board');
    if (boardEl) {
      var cards2 = [], seen2 = {};
      var els = boardEl.querySelectorAll('.single-cart-view-p');
      for (var i = 0; i < els.length; i++) {
        if (els[i].closest('sg-poker-table-seat') || els[i].closest('.player-mini-container-p')) continue;
        var c = parseCard(els[i].getAttribute('class') || '');
        if (c && !seen2[c]) { seen2[c] = true; cards2.push(c); }
      }
      if (cards2.length > 0) return cards2;
    }
    return [];
  }

  // === POT ===
  function getPot(doc) {
    var el = doc.querySelector('.pot-w-view-p p b');
    if (el) return el.innerText.trim() || null;
    // Fallback: any .pot-w-view-p text
    var pot = doc.querySelector('.pot-w-view-p');
    if (pot) {
      var txt = pot.innerText.trim();
      if (txt) return txt;
    }
    return null;
  }

  // === DEALER BUTTON ===
  function getDealerSeat(doc) {
    var dealer = doc.querySelector('.dealer-icon-view');
    if (!dealer) return null;
    var m = String(dealer.className || '').match(/position-(\d+)/);
    return m ? Number(m[1]) : null;
  }

  // === HAND ID ===
  function getHandId(doc) {
    var el = doc.querySelector('.table-header-v-left p i');
    if (el) return el.innerText.trim() || null;
    return null;
  }

  // === TABLE INFO ===
  function getTableInfo(doc) {
    var el = doc.querySelector('.tab-info-view-p i');
    if (el) {
      var txt = el.innerText.trim();
      // Parse: "MULTAN | ZAR 0.1 / ZAR 0.2 - PL OMAHA 4"
      var result = { name: null, blinds: null, game_type: null, raw: txt };
      var pipeIdx = txt.indexOf('|');
      if (pipeIdx !== -1) {
        result.name = txt.substring(0, pipeIdx).trim();
        var rest = txt.substring(pipeIdx + 1).trim();
        var dashIdx = rest.lastIndexOf('-');
        if (dashIdx !== -1) {
          result.game_type = rest.substring(dashIdx + 1).trim();
          var blindsStr = rest.substring(0, dashIdx).trim();
          // Extract numeric blinds: "ZAR 0.1 / ZAR 0.2" -> "0.1/0.2"
          var blindParts = blindsStr.split('/');
          if (blindParts.length === 2) {
            var sb = blindParts[0].replace(/[^0-9.]/g, '').trim();
            var bb = blindParts[1].replace(/[^0-9.]/g, '').trim();
            if (sb && bb) result.blinds = sb + '/' + bb;
          }
        }
      }
      // Normalize game type
      if (result.game_type) {
        var gt = result.game_type.toUpperCase();
        if (gt.indexOf('OMAHA 4') !== -1 || gt.indexOf('PLO4') !== -1) result.game_type = 'PLO4';
        else if (gt.indexOf('OMAHA 5') !== -1 || gt.indexOf('PLO5') !== -1) result.game_type = 'PLO5';
        else if (gt.indexOf('OMAHA 6') !== -1 || gt.indexOf('PLO6') !== -1) result.game_type = 'PLO6';
        else if (gt.indexOf('OMAHA') !== -1) result.game_type = 'PLO';
      }
      return result;
    }
    return { name: null, blinds: null, game_type: null, raw: null };
  }

  // === TABLE ID from URL ===
  function getTableId(doc) {
    try {
      // Try from iframe's location
      var win = doc.defaultView;
      if (win && win.location && win.location.href) {
        var m = win.location.href.match(/\/tbl\/(\d+)/);
        if (m) return m[1];
      }
    } catch (e) { /* cross-origin */ }
    // Fallback: try top window
    try {
      var m2 = window.location.href.match(/\/tbl\/(\d+)/);
      if (m2) return m2[1];
    } catch (e) {}
    return null;
  }

  // === TIMER for a seat ===
  function getSeatTimer(seatEl) {
    var timerEl = seatEl.querySelector('.time-line-animation-v span');
    if (timerEl) {
      var val = timerEl.innerText.trim();
      if (val) return val;
    }
    var timeLeft = seatEl.querySelector('.time_left');
    if (timeLeft) {
      var val2 = timeLeft.innerText.trim();
      if (val2) return val2;
    }
    return null;
  }

  // === TIME BANK for a seat ===
  function getSeatTimeBank(seatEl) {
    var el = seatEl.querySelector('.bank-timer-view span');
    if (el) {
      var val = el.innerText.trim();
      if (val) return val;
    }
    return null;
  }

  // === PLAYER BET (chips near seat) ===
  function getPlayerBet(doc, seatNum) {
    var chipEl = doc.querySelector('sg-chips-view.player-' + seatNum + '-chips .chip-container-view-p p i');
    if (chipEl) {
      var val = chipEl.innerText.trim();
      if (val) return val;
    }
    return null;
  }

  // === ACTION BUTTONS ===
  var ACTION_TYPES = ['fold', 'check', 'call', 'raise', 'bet', 'cash_out', 'show', 'run_it_twice', 'resume_hand', 'back_to_game'];

  function getActions(doc) {
    var result = {
      available: [],
      buttons: [],
      slider: null
    };

    for (var a = 0; a < ACTION_TYPES.length; a++) {
      var type = ACTION_TYPES[a];
      var btn = doc.querySelector('.control-b-view-p.' + type + '-c');
      if (btn) {
        result.available.push(type);
        var textEl = btn.querySelector('span');
        var amountEl = btn.querySelector('i');
        result.buttons.push({
          type: type,
          text: textEl ? textEl.innerText.trim() : type.toUpperCase(),
          amount: amountEl ? amountEl.innerText.trim() : ''
        });
      }
    }

    // Slider
    var slider = doc.querySelector('sg-poker-betting-slider');
    if (slider) {
      var presets = [];
      var presetEls = slider.querySelectorAll('.limits-buttons-v-p li p');
      for (var p = 0; p < presetEls.length; p++) {
        var ptxt = presetEls[p].innerText.trim();
        if (ptxt) presets.push(ptxt);
      }
      var inputEl = slider.querySelector('.limit-count-v-p input');
      var currentVal = inputEl ? (inputEl.value || '') : '';

      // Extract min/max from presets or input attributes
      var sliderMin = '';
      var sliderMax = '';
      if (inputEl) {
        sliderMin = inputEl.getAttribute('min') || '';
        sliderMax = inputEl.getAttribute('max') || '';
      }

      result.slider = {
        min: sliderMin,
        max: sliderMax,
        presets: presets,
        current: currentVal
      };
    }

    return result;
  }

  // === STREET DETECTION from board length ===
  function detectStreet(boardCards) {
    var len = boardCards.length;
    if (len === 0) return 'preflop';
    if (len === 3) return 'flop';
    if (len === 4) return 'turn';
    if (len >= 5) return 'river';
    return 'preflop';
  }

  // === PARSE BOARD into API format ===
  function formatBoard(boardCards) {
    var result = { flop: [], turn: null, river: null };
    if (boardCards.length >= 3) {
      result.flop = boardCards.slice(0, 3);
    }
    if (boardCards.length >= 4) {
      result.turn = boardCards[3];
    }
    if (boardCards.length >= 5) {
      result.river = boardCards[4];
    }
    return result;
  }

  // === PARSE ZAR AMOUNT to numeric ===
  function parseZar(text) {
    if (!text) return 0;
    var num = String(text).replace(/[^0-9.]/g, '');
    return parseFloat(num) || 0;
  }

  // === SEAT SCANNING ===
  function scanSeats(doc) {
    var seats = [];
    var dealerSeat = getDealerSeat(doc);

    for (var seatNum = 1; seatNum <= 9; seatNum++) {
      var seatEl = doc.querySelector('sg-poker-table-seat.player-' + seatNum);
      if (!seatEl) continue;

      // Check if seat is empty
      var emptyEl = seatEl.querySelector('.empty-p-view-b.grey-view-p');
      if (emptyEl) continue; // skip truly empty seats

      // Check for player presence
      var playerContainer = seatEl.querySelector('.player-mini-container-p');
      if (!playerContainer) continue; // no player here

      // Player name
      var nameEl = seatEl.querySelector('p.single-win-item-sizes');
      var name = nameEl ? nameEl.innerText.trim() : null;
      if (!name) continue; // no name = no player

      // Stack
      var stackEl = seatEl.querySelector('.player-text-info-p span b');
      var stackText = stackEl ? stackEl.innerText.trim() : null;

      // Cards
      var cartsContainer = seatEl.querySelector('.carts-container-p');
      var cards = getCardsFromElement(cartsContainer);

      // Is hero?
      var isHero = false;
      if (playerContainer.classList.contains('self-player')) {
        isHero = true;
      } else if (name && name.toLowerCase() === HERO_NAME.toLowerCase()) {
        isHero = true;
      }

      // Sitting out?
      var sittingOut = false;
      var seatOutEl = seatEl.querySelector('.seat-out-v');
      if (seatOutEl) sittingOut = true;

      // Player bet
      var bet = getPlayerBet(doc, seatNum);

      // Timer
      var timer = getSeatTimer(seatEl);

      // Time bank
      var timeBank = getSeatTimeBank(seatEl);

      // Is dealer?
      var isDealer = (dealerSeat === seatNum);

      seats.push({
        seat: seatNum,
        seat_index: seatNum - 1, // 0-indexed for API compatibility
        name: name,
        stack: stackText,
        stack_zar: parseZar(stackText),
        cards: cards.length > 0 ? cards : [],
        hole_cards: cards.length > 0 ? cards : [],
        is_hero: isHero,
        is_dealer: isDealer,
        sitting_out: sittingOut,
        status: sittingOut ? 'sitting_out' : 'active',
        bet: bet,
        timer: timer,
        time_bank: timeBank
      });
    }

    return seats;
  }

  // === BUILD FULL SNAPSHOT ===
  function buildSnapshot() {
    var doc;
    try {
      doc = getRootDoc();
    } catch (e) {
      console.error(LOG_PREFIX + ' getRootDoc failed:', e.message);
      return null;
    }

    var seats = scanSeats(doc);
    if (seats.length === 0) return null;

    // Must have hero
    var hasHero = false;
    for (var i = 0; i < seats.length; i++) {
      if (seats[i].is_hero) { hasHero = true; break; }
    }
    if (!hasHero) return null;

    var board = getBoard(doc);
    var pot = getPot(doc);
    var dealerSeat = getDealerSeat(doc);
    var handId = getHandId(doc);
    var tableInfo = getTableInfo(doc);
    var tableId = getTableId(doc) || 'unknown';
    var actions = getActions(doc);
    var street = detectStreet(board);

    // Build the rich snapshot matching the Flask API format
    var snapshot = {
      // Fields the Flask /api/snapshot endpoint expects
      table_id: tableId,
      dealer_seat: dealerSeat,
      deal_id: handId,
      street: street,
      pot_zar: parseZar(pot),
      board: formatBoard(board),
      variant: (tableInfo.game_type || 'PLO4').toLowerCase().replace(/[0-9]/g, '') || 'plo',
      seats: seats,

      // Rich metadata fields (extra, for UI/debugging)
      table_name: tableInfo.name,
      game_type: tableInfo.game_type || 'PLO4',
      blinds: tableInfo.blinds,
      hand_id: handId,
      pot: pot,
      board_cards: board,
      actions: actions,
      source: HERO_NAME,
      timestamp: new Date().toISOString()
    };

    return snapshot;
  }

  // === POST SNAPSHOT ===
  function postSnapshot(snapshot) {
    var now = Date.now();
    if (now - lastPostTime < DEBOUNCE_MS) return;

    var json = JSON.stringify(snapshot);
    var h = hashStr(json);
    if (h === lastHash) return; // no change

    lastPostTime = now;
    lastHash = h;

    var xhr = new XMLHttpRequest();
    xhr.open('POST', API_URL, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('X-API-Key', API_KEY);
    xhr.timeout = 5000;

    xhr.onload = function() {
      if (xhr.status === 200 || xhr.status === 201) {
        postCount++;
        try {
          var resp = JSON.parse(xhr.responseText);
          if (resp.ignored || resp.dup) {
            // Ignored or duplicate - don't log verbosely
          } else {
            console.log(LOG_PREFIX + ' POST #' + postCount + ' OK | table=' + snapshot.table_id +
              ' | seats=' + snapshot.seats.length + ' | street=' + snapshot.street +
              ' | board=' + snapshot.board_cards.length + ' | pot=' + snapshot.pot);
          }
        } catch (e) {
          console.log(LOG_PREFIX + ' POST #' + postCount + ' OK (status ' + xhr.status + ')');
        }
      } else if (xhr.status === 401) {
        console.error(LOG_PREFIX + ' AUTH FAILED (401) - check API key');
        errorCount++;
      } else {
        console.warn(LOG_PREFIX + ' POST failed: status=' + xhr.status, xhr.responseText);
        errorCount++;
      }
    };

    xhr.onerror = function() {
      errorCount++;
      console.error(LOG_PREFIX + ' Network error (is tunnel running?) errors=' + errorCount);
    };

    xhr.ontimeout = function() {
      errorCount++;
      console.warn(LOG_PREFIX + ' POST timeout (5s)');
    };

    try {
      xhr.send(json);
    } catch (e) {
      errorCount++;
      console.error(LOG_PREFIX + ' Send exception:', e.message);
    }
  }

  // === MAIN TICK ===
  function tick() {
    if (!pageVisible) return;

    try {
      var snapshot = buildSnapshot();
      if (!snapshot) return;
      postSnapshot(snapshot);
    } catch (e) {
      console.error(LOG_PREFIX + ' tick error:', e.message, e.stack);
    }
  }

  // === PUBLIC API ===
  window._n4p_full_getSnapshot = function() {
    try { return buildSnapshot(); } catch (e) { return null; }
  };

  window._n4p_full_status = function() {
    return {
      injected: true,
      posts: postCount,
      errors: errorCount,
      lastHash: lastHash,
      lastPostTime: lastPostTime ? new Date(lastPostTime).toISOString() : null,
      apiUrl: API_URL,
      hero: HERO_NAME,
      tickMs: TICK_MS
    };
  };

  // === START ===
  window._n4p_full_timer = setInterval(tick, TICK_MS);
  window._n4p_full_injected = true;

  // Run first tick immediately
  tick();

  console.log(LOG_PREFIX + ' v1.0 loaded | hero=' + HERO_NAME + ' | API=' + API_URL + ' | tick=' + TICK_MS + 'ms');
  console.log(LOG_PREFIX + ' Status: window._n4p_full_status() | Manual snapshot: window._n4p_full_getSnapshot()');
})();

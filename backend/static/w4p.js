// W4P Injectable v16 - PLO Remote Table Control (pure native clicks - mirrors PokerBet exactly)
// W4P injectable script (local copy) — fetch from local engine if needed.
// v16: ALL betting via native PokerBet button clicks — no slider manipulation
// No chrome.runtime deps — pure fetch-based

(function(){
  'use strict';

  // ── Cleanup prior instances ──────────────────────────────────
  if (window._w4p_timer) { clearTimeout(window._w4p_timer); window._w4p_timer = null; }
  if (window._w4p_cmdTimer) { clearTimeout(window._w4p_cmdTimer); window._w4p_cmdTimer = null; }
  if (window._w4p_bbTimer) { clearInterval(window._w4p_bbTimer); window._w4p_bbTimer = null; }
  if (window._w4p) { clearInterval(window._w4p); window._w4p = null; }
  window._w4p_injected = false;

  // ── Config ───────────────────────────────────────────────────
  // Local engine API proxy (served under /engine by the local Express on port 4002)
  var API_BASE = '/engine/api';
  var API_KEY  = '';

  var POLL_MS = { HERO_TURN: 200, HAND_ACTIVE: 300, IDLE: 600, NO_TABLE: 2000 };
  var CMD_MS  = { HERO_TURN: 80, HAND_ACTIVE: 100, IDLE: 400 };
  var HEARTBEAT_MS = 8000;

  var _mode = 'IDLE';
  var _seatToken = null;
  var _preAction = null;    // 'check_fold' | 'check_call' | null
  var _lastHash = null;
  var _lastSendTime = 0;
  var _n = 0;
  var _sessionId = 'w4p_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);

  var RANK_MAP = { 'a':'A', 'k':'K', 'q':'Q', 'j':'J', 't':'T', '10':'T' };

  // ── Action button selectors (PokerBet / BetConstruct DOM) ───
  var BTN_SEL = {
    fold:         '.control-b-view-p.fold-c',
    check:        '.control-b-view-p.check-c',
    call:         '.control-b-view-p.call-c',
    raise:        '.control-b-view-p.raise-c',
    bet:          '.control-b-view-p.bet-c',
    cashout:      '.control-b-view-p.cash_out-c',
    show:         '.control-b-view-p.show-c',
    run_it_twice: '.control-b-view-p.run_it_twice-c',
    resume_hand:  '.control-b-view-p.resume_hand-c',
    back_to_game: '.control-b-view-p.back_to_game-c'
  };

  // ── Card parser ──────────────────────────────────────────────
  function parseCard(cls) {
    if (!cls) return null;
    var m = cls.match(/icon-layer2_([shdc])(10|[akqjt2-9])_p-c-d/i);
    if (!m) return null;
    var suit = m[1].toLowerCase();
    var rank = m[2].toLowerCase();
    rank = RANK_MAP[rank] || rank;
    return rank + suit;
  }

  // ── Table ID from URL ────────────────────────────────────────
  function getTableId() {
    var url = location.href;
    var m = url.match(/\/tbl\/(\d+)/);
    if (m) return 'pb_' + m[1];
    m = url.match(/\/poker\/(\d+)/);
    if (m) return 'pb_' + m[1];
    m = url.match(/openGames=(\d+)/);
    if (m) return 'pb_' + m[1];
    m = url.match(/game[_-]?id[=\/](\d+)/i);
    if (m) return 'pb_' + m[1];
    if (url.indexOf('skillgames') !== -1 || url.indexOf('18751019') !== -1) {
      var idm = url.match(/(\d{4,})/);
      return 'pb_' + (idm ? idm[1] : 'sg');
    }
    if (document.querySelector('.player-mini-container-p') || document.querySelector('sg-poker-table-seat')) {
      var idm2 = url.match(/(\d{3,})/);
      return 'pb_' + (idm2 ? idm2[1] : '0');
    }
    return null;
  }

  // ── Player bet (chips near seat) ──────────────────────────────
  function getPlayerBet(seatNum) {
    var chipEl = document.querySelector('sg-chips-view.player-' + seatNum + '-chips .chip-container-view-p p i');
    if (chipEl) {
      var val = (chipEl.innerText || chipEl.textContent || '').trim();
      if (val) {
        var n = parseFloat(val.replace(/[^0-9.]/g, ''));
        return isNaN(n) ? 0 : n;
      }
    }
    return 0;
  }

  // ── Available actions (hero only — gated on .active turn) ────
  function getAvailableActions() {
    var heroSeat = document.querySelector('sg-poker-table-seat.self-player') || document.querySelector('.player-mini-container-p.self-player');
    if (heroSeat) {
      var turnActive = heroSeat.classList.contains('active') || !!heroSeat.querySelector('.active-turn');
      if (!turnActive) return [];
    }
    var avail = [];
    for (var name in BTN_SEL) {
      var btn = document.querySelector(BTN_SEL[name]);
      if (btn && (btn.offsetParent !== null || btn.offsetWidth > 0)) {
        avail.push(name);
      }
    }
    if (avail.length === 0) {
      var actionMap = {fold:'fold', check:'check', call:'call', raise:'raise', bet:'bet', cashout:'cashout', show:'show'};
      var candidates = document.querySelectorAll('[class*="fold"], [class*="check"], [class*="call"], [class*="raise"], [class*="bet-c"], [class*="cash_out"]');
      for (var i = 0; i < candidates.length; i++) {
        var el = candidates[i];
        if (el.offsetParent === null && el.offsetWidth === 0) continue;
        var cls = el.className.toLowerCase();
        for (var key in actionMap) {
          if (cls.indexOf(key) !== -1 && avail.indexOf(key) === -1) {
            avail.push(key);
          }
        }
      }
      if (avail.length === 0) {
        var btns = document.querySelectorAll('button, [role="button"], .btn, [class*="control"]');
        for (var j = 0; j < btns.length; j++) {
          var b = btns[j];
          if (b.offsetParent === null && b.offsetWidth === 0) continue;
          var txt = (b.textContent || '').trim().toLowerCase();
          for (var key2 in actionMap) {
            if (txt === key2 && avail.indexOf(key2) === -1) avail.push(key2);
          }
        }
      }
      if (avail.length > 0 && _n <= 5) {
        console.log('[W4P] actions found via fallback:', avail.join(','));
      }
    }
    return avail;
  }

  // ── Build full snapshot — ALL seats ──────────────────────────
  function buildSnapshot() {
    var tableId = getTableId();
    if (!tableId) {
      if (_n <= 5 || _n % 30 === 0) console.log('[W4P] no tableId');
      return null;
    }

    var containers = document.querySelectorAll('sg-poker-table-seat');
    if (!containers.length) containers = document.querySelectorAll('.player-mini-container-p');
    if (!containers.length) {
      if (_n <= 5 || _n % 30 === 0) console.log('[W4P] no seat containers');
      return null;
    }

    var dealerEl = document.querySelector('.dealer-icon-view');
    var dMatch = dealerEl ? dealerEl.className.match(/position-(\d+)/) : null;
    var dealerSeat = dMatch ? parseInt(dMatch[1]) : null;

    var potEl = document.querySelector('.pot-w-view-p') || document.querySelector('.pot-amount') || document.querySelector('.total-pot');
    var potText = potEl ? (potEl.innerText || potEl.textContent || '') : '';
    var pMatch = potText.match(/([\d.,]+)/);
    var potZar = pMatch ? parseFloat(pMatch[1].replace(',', '')) : 0;

    var boardCards = [];
    var boardEl = document.querySelector('sg-poker-board');
    if (boardEl) {
      var bcEls = boardEl.querySelectorAll('.single-cart-view-p');
      for (var i = 0; i < bcEls.length; i++) {
        if (bcEls[i].closest('sg-poker-table-seat') || bcEls[i].closest('.player-mini-container-p')) continue;
        var c = parseCard(bcEls[i].className);
        if (c) boardCards.push(c);
      }
    }
    if (boardCards.length < 3) {
      var allCardEls = document.querySelectorAll('.single-cart-view-p');
      boardCards = [];
      for (var i = 0; i < allCardEls.length; i++) {
        if (allCardEls[i].closest('.player-mini-container-p') || allCardEls[i].closest('sg-poker-table-seat')) continue;
        var c2 = parseCard(allCardEls[i].className);
        if (c2) boardCards.push(c2);
      }
    }

    var street = 'PREFLOP';
    if (boardCards.length >= 5) street = 'RIVER';
    else if (boardCards.length >= 4) street = 'TURN';
    else if (boardCards.length >= 3) street = 'FLOP';

    var avail = getAvailableActions();

    var seats = [];
    var heroName = null;

    for (var i = 0; i < containers.length; i++) {
      var ct = containers[i];
      var isHero = ct.classList.contains('self-player') || !!ct.querySelector('.self-player');

      var posMatch = ct.className.match(/position-(\d+)/);
      var seatIdx = posMatch ? parseInt(posMatch[1]) : i;

      var nameEl = ct.querySelector('p.single-win-item-sizes') || ct.querySelector('.player-name');
      var name = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : null;
      if (!name || name === '') name = null;

      var stackEl = ct.querySelector('.player-text-info-p span b') || ct.querySelector('.player-text-info-p b') || ct.querySelector('.player-stack');
      var stackText = stackEl ? (stackEl.innerText || stackEl.textContent || '') : '';
      var sMatch = stackText.match(/([\d.,]+)/);
      var stackZar = sMatch ? parseFloat(sMatch[1].replace(',', '')) : 0;

      var holeCards = [];
      var cardsContainer = ct.querySelector('.carts-container-p');
      var hcEls = (cardsContainer || ct).querySelectorAll('.single-cart-view-p');
      for (var j = 0; j < hcEls.length; j++) {
        var hc = parseCard(hcEls[j].className);
        if (hc) holeCards.push(hc);
      }

      if (isHero) heroName = name;
      if (!isHero) continue;

      var sittingOut = ct.classList.contains('seat-out-v') || !!ct.querySelector('.seat-out-v');
      var isFolded = ct.classList.contains('folded') || !!ct.querySelector('.folded');
      var isActive = ct.classList.contains('active') || !!ct.querySelector('.active-turn');

      var status = 'playing';
      if (sittingOut) status = 'sitting_out';
      else if (isFolded) status = 'folded';
      else if (holeCards.length === 0 && street !== 'PREFLOP') status = 'folded';

      seats.push({
        seat_index:        seatIdx,
        name:              name,
        stack_zar:         stackZar,
        hole_cards:        holeCards,
        is_hero:           true,
        is_self_player:    true,
        is_dealer:         seatIdx === dealerSeat,
        status:            status,
        sitting_out:       sittingOut,
        is_active:         isActive,
        available_actions: avail,
        bet:               getPlayerBet(seatIdx)
      });
    }

    if (!heroName) {
      if (_n <= 5 || _n % 30 === 0) {
        var seatClasses = [];
        for (var d = 0; d < containers.length; d++) {
          var dct = containers[d];
          var dname = dct.querySelector('p.single-win-item-sizes') || dct.querySelector('.player-name');
          var dnameText = dname ? dname.textContent.trim() : 'EMPTY';
          seatClasses.push(dnameText + ':' + dct.className.replace(/\s+/g, '.'));
        }
        console.log('[W4P] no hero | ' + containers.length + ' seats | ' + seatClasses.join(' | '));
      }
      return null;
    }

    return {
      table_id:      tableId,
      bot_id:        heroName,
      session_id:    _sessionId,
      seats:         seats,
      board: {
        flop:  boardCards.slice(0, 3),
        turn:  boardCards[3] || null,
        river: boardCards[4] || null
      },
      pot_zar:       potZar,
      dealer_seat:   dealerSeat,
      street:        street,
      variant:       'plo',
      available_actions: avail,
      ts:            new Date().toISOString(),
      source_key:    'w4p_inject'
    };
  }

  // ── State hash for dedup ─────────────────────────────────────
  function stateHash(snap) {
    var hero = null;
    for (var i = 0; i < snap.seats.length; i++) {
      if (snap.seats[i].is_hero) { hero = snap.seats[i]; break; }
    }
    if (!hero) return '';
    return JSON.stringify({
      si: hero.seat_index, n: hero.name, st: hero.stack_zar,
      hc: hero.hole_cards.join(''), stat: hero.status,
      act: hero.is_active, aa: hero.available_actions.join(','),
      b: snap.board, p: snap.pot_zar, str: snap.street, d: snap.dealer_seat
    });
  }

  // ── Snapshot response handler ────────────────────────────────
  function handleSnapshotResponse(data) {
    if (data.ok) {
      if (data.seat_token) {
        if (!_seatToken) {
          console.log('[W4P] Connected! seat_no=' + data.seat_no + ' token=' + data.seat_token.substr(0, 8) + '...');
          _seatToken = data.seat_token;
          pollCommands();
        } else {
          _seatToken = data.seat_token;
        }
      }
    } else {
      console.log('[W4P] API error:', data.error);
    }
  }

  // ── Send snapshot (direct fetch) ─────────────────────────────
  function sendSnapshot(snap) {
    fetch(API_BASE + '/snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
      body: JSON.stringify(snap)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) { handleSnapshotResponse(data); })
    .catch(function(e) {
      console.log('[W4P] fetch error:', e.message);
    });
  }

  // ═══════════════════════════════════════════════════════════════
  // ══ NATIVE BUTTON CLICKING — Mirrors PokerBet exactly ════════
  // ═══════════════════════════════════════════════════════════════
  // All betting actions work by clicking PokerBet's own buttons,
  // exactly as a human would. No slider value manipulation.
  //
  // Flow: Click RAISE/BET → Click preset (MIN/½/POT/MAX) → Click RAISE/BET to confirm
  // ═══════════════════════════════════════════════════════════════

  // ── Find and click a preset button matching a regex ──────────
  function clickPreset(regex) {
    var selectorSets = [
      'sg-poker-betting-slider .limits-buttons-v-p li',
      '.limits-buttons-v-p li',
      'sg-poker-betting-slider .limits-buttons-v-p ul li',
      'sg-poker-betting-slider li',
      'sg-poker-betting-slider button',
      'sg-poker-betting-slider [class*="preset"]',
      'sg-poker-betting-slider [class*="limit"] button',
      'sg-poker-betting-slider [class*="limit"] span',
      '[class*="betting-slider"] li',
      '[class*="betting-slider"] button'
    ];

    for (var s = 0; s < selectorSets.length; s++) {
      var els = document.querySelectorAll(selectorSets[s]);
      for (var i = 0; i < els.length; i++) {
        var txt = (els[i].textContent || '').trim();
        if (regex.test(txt)) {
          els[i].dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
          var inner = els[i].querySelector('span, p, button, a, div, i');
          if (inner) inner.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
          console.log('[W4P] Clicked preset: "' + txt + '" via ' + selectorSets[s]);
          return true;
        }
      }
    }

    // MAX fallback: click the last preset (rightmost = MAX in BetConstruct)
    if (/max|all/i.test(regex.source || '')) {
      var lastPreset = document.querySelector('.limits-buttons-v-p li:last-child')
                    || document.querySelector('sg-poker-betting-slider li:last-child');
      if (lastPreset && lastPreset.offsetParent !== null) {
        lastPreset.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        var inner2 = lastPreset.querySelector('span, p, button, a, div, i');
        if (inner2) inner2.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        console.log('[W4P] MAX fallback: clicked last preset "' + (lastPreset.textContent || '').trim() + '"');
        return true;
      }
    }

    // MIN fallback: click the first preset
    if (/min/i.test(regex.source || '')) {
      var firstPreset = document.querySelector('.limits-buttons-v-p li:first-child')
                     || document.querySelector('sg-poker-betting-slider li:first-child');
      if (firstPreset && firstPreset.offsetParent !== null) {
        firstPreset.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        console.log('[W4P] MIN fallback: clicked first preset');
        return true;
      }
    }

    console.log('[W4P] No preset found for: ' + regex);
    return false;
  }

  // ── Type amount into the betting input via execCommand ────────
  function typeAmount(val) {
    val = String(val);
    var amtInput = document.querySelector('sg-poker-betting-slider input[type="number"]')
      || document.querySelector('sg-poker-betting-slider input[type="text"]')
      || document.querySelector('sg-poker-betting-slider input');
    if (!amtInput) {
      var inputs = document.querySelectorAll('input[type="number"], input[type="text"]');
      for (var i = 0; i < inputs.length; i++) {
        if (inputs[i].offsetParent !== null && !inputs[i].closest('sg-buy-in-modal')) {
          amtInput = inputs[i];
          break;
        }
      }
    }
    if (!amtInput) {
      console.log('[W4P] typeAmount: no input field found');
      return false;
    }

    amtInput.focus();
    if (amtInput.select) amtInput.select();
    else if (amtInput.setSelectionRange) amtInput.setSelectionRange(0, amtInput.value.length);

    var ok = document.execCommand('insertText', false, val);
    if (!ok || amtInput.value !== val) {
      var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSet.call(amtInput, val);
      try {
        amtInput.dispatchEvent(new InputEvent('input', {bubbles: true, data: val, inputType: 'insertText'}));
      } catch(e) {
        amtInput.dispatchEvent(new Event('input', {bubbles: true}));
      }
      amtInput.dispatchEvent(new Event('change', {bubbles: true}));
    }
    console.log('[W4P] typeAmount: input=' + amtInput.value + ' (wanted=' + val + ')');
    return true;
  }

  // ── Drag slider all the way to max via pointer events ─────────
  function dragSliderMax() {
    var slider = document.querySelector('sg-poker-betting-slider input[type="range"]')
              || document.querySelector('input[type="range"]');
    if (!slider || slider.offsetParent === null) {
      console.log('[W4P] dragSliderMax: no visible range slider');
      return false;
    }

    var rect = slider.getBoundingClientRect();
    if (rect.width <= 0) return false;

    var startX = rect.left + 5;
    var endX = rect.right - 2;
    var midY = rect.top + rect.height / 2;

    try {
      slider.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, cancelable:true, clientX:startX, clientY:midY, pointerId:1, pointerType:'mouse'}));
      slider.dispatchEvent(new PointerEvent('pointermove', {bubbles:true, cancelable:true, clientX:endX, clientY:midY, pointerId:1, pointerType:'mouse'}));
      slider.dispatchEvent(new PointerEvent('pointerup',   {bubbles:true, cancelable:true, clientX:endX, clientY:midY, pointerId:1, pointerType:'mouse'}));
    } catch(e) {}

    slider.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, clientX:startX, clientY:midY}));
    slider.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, cancelable:true, clientX:endX, clientY:midY}));
    slider.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, clientX:endX, clientY:midY}));

    var maxAttr = parseFloat(slider.getAttribute('max') || slider.max);
    if (maxAttr > 0) {
      var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSet.call(slider, String(maxAttr));
      slider.dispatchEvent(new Event('input', {bubbles: true}));
      slider.dispatchEvent(new Event('change', {bubbles: true}));
    }

    console.log('[W4P] dragSliderMax: dragged to max' + (maxAttr ? ' (max=' + maxAttr + ')' : ''));
    return true;
  }

  // ── Core betting action: set amount → confirm ─────────────────
  // In BetConstruct, the slider panel is ALREADY VISIBLE when it's
  // your turn and raise/bet is available. Clicking RAISE/BET when
  // the slider is open CONFIRMS the raise at the current value.
  //
  // So the flow is:
  //   1. Check if slider panel is already open (it should be)
  //   2. Click preset OR type amount to set the value
  //   3. Click RAISE/BET to confirm
  //
  // Only click RAISE/BET first if the slider is NOT visible (rare).
  function clickPresetAndConfirm(presetRegex, amount) {
    var raiseBtn = document.querySelector(BTN_SEL.raise) || document.querySelector(BTN_SEL.bet);
    if (!raiseBtn || (raiseBtn.offsetParent === null && raiseBtn.offsetWidth === 0)) {
      console.log('[W4P] clickPresetAndConfirm: no raise/bet button visible');
      return;
    }

    // Check if slider panel is already visible
    var sliderPanel = document.querySelector('sg-poker-betting-slider');
    var sliderVisible = sliderPanel && (sliderPanel.offsetParent !== null || sliderPanel.offsetWidth > 0 || sliderPanel.offsetHeight > 0);
    var rangeSlider = document.querySelector('sg-poker-betting-slider input[type="range"]') || document.querySelector('input[type="range"]');
    var rangeVisible = rangeSlider && (rangeSlider.offsetParent !== null || rangeSlider.offsetWidth > 0);
    var presets = document.querySelectorAll('.limits-buttons-v-p li');

    console.log('[W4P] Panel check: slider-component=' + !!sliderPanel +
                ' visible=' + sliderVisible +
                ' range=' + rangeVisible +
                ' presets=' + presets.length);
    if (presets.length > 0) {
      var labels = [];
      for (var d = 0; d < presets.length; d++) labels.push('"' + (presets[d].textContent || '').trim() + '"');
      console.log('[W4P] Presets: ' + labels.join(', '));
    }

    if (sliderVisible || rangeVisible || presets.length > 0) {
      // Slider panel is already open — set amount FIRST, then confirm
      console.log('[W4P] Step 1: slider already open — setting amount directly');
      setAmountAndConfirm(presetRegex, amount, raiseBtn);
    } else {
      // Slider not visible — click raise/bet to open it, then set amount
      console.log('[W4P] Step 1: slider not open — clicking raise/bet to open');
      raiseBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      setTimeout(function() {
        setAmountAndConfirm(presetRegex, amount, null);
      }, 600);
    }
  }

  // ── Set amount (via preset or typing) then confirm ────────────
  function setAmountAndConfirm(presetRegex, amount, confirmBtnRef) {
    var done = false;

    // A) Try clicking a matching preset button
    if (presetRegex) {
      done = clickPreset(presetRegex);
    }

    // B) Type the amount if no preset matched
    if (!done && amount) {
      done = typeAmount(amount);
    }

    // C) MAX-specific last resort: drag slider to max
    if (!done && presetRegex && /max|all/i.test(presetRegex.source || '')) {
      done = dragSliderMax();
    }

    if (!done) {
      console.log('[W4P] WARNING — could not set bet amount');
    }

    // Confirm: click raise/bet to execute
    setTimeout(function() {
      var confirmBtn = confirmBtnRef || document.querySelector(BTN_SEL.raise) || document.querySelector(BTN_SEL.bet);
      if (confirmBtn && (confirmBtn.offsetParent !== null || confirmBtn.offsetWidth > 0)) {
        confirmBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        console.log('[W4P] Confirmed raise/bet');
      } else {
        console.log('[W4P] WARNING — confirm button not visible');
      }
    }, 500);
  }

  // ── Click a simple action button (fold/check/call/etc) ───────
  function clickSimple(action) {
    var sel = BTN_SEL[action];
    if (!sel) { console.log('[W4P] Unknown action:', action); return false; }
    var btn = document.querySelector(sel);
    if (btn && (btn.offsetParent !== null || btn.offsetWidth > 0)) {
      btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      console.log('[W4P] Clicked native:', action);
      return true;
    }
    console.log('[W4P] Button not visible:', action);
    return false;
  }

  // ── Command handler ──────────────────────────────────────────
  function handleCommand(cmd) {
    var action = (cmd.type || cmd.command || '').toLowerCase();
    console.log('[W4P] CMD:', action, cmd.amount ? 'amt=' + cmd.amount : '');

    // Pre-actions & buy-in
    if (action === 'buyin' || action === 'rebuy_max' || action === 'rebuy_min' || action === 'buyin_max' || action === 'buyin_min') {
      handleBuyin(cmd); return;
    }
    if (action === 'check_fold') { _preAction = 'check_fold'; console.log('[W4P] Pre-action: CHECK/FOLD'); return; }
    if (action === 'check_call') { _preAction = 'check_call'; console.log('[W4P] Pre-action: CHECK/CALL'); return; }
    if (action === 'clear')      { _preAction = null;          console.log('[W4P] Pre-action cleared');    return; }

    // Direct one-click actions
    if (action === 'fold' || action === 'check' || action === 'call' ||
        action === 'cashout' || action === 'show' || action === 'run_it_twice' ||
        action === 'resume_hand' || action === 'back_to_game') {
      clickSimple(action);
      return;
    }

    // ALL-IN: MAX preset → confirm
    if (action === 'allin' || action === 'all-in' || action === 'all_in') {
      var allinBtn = document.querySelector('.control-b-view-p.all_in-c');
      if (allinBtn && (allinBtn.offsetParent !== null || allinBtn.offsetWidth > 0)) {
        allinBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        console.log('[W4P] Clicked native ALL-IN button');
        return;
      }
      clickPresetAndConfirm(/max|all/i);
      return;
    }

    // RAISE with amount
    if (action === 'raise') {
      if (cmd.amount) {
        clickPresetAndConfirm(null, cmd.amount);
      } else {
        var rb = document.querySelector(BTN_SEL.raise);
        if (rb && (rb.offsetParent !== null || rb.offsetWidth > 0)) {
          rb.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
          console.log('[W4P] Clicked raise to open slider');
        }
      }
      return;
    }

    // BET with amount
    if (action === 'bet') {
      if (cmd.amount) {
        clickPresetAndConfirm(null, cmd.amount);
      } else {
        var bb = document.querySelector(BTN_SEL.bet);
        if (bb && (bb.offsetParent !== null || bb.offsetWidth > 0)) {
          bb.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
          console.log('[W4P] Clicked bet to open slider');
        }
      }
      return;
    }

    // POT preset
    if (action === 'pot') {
      clickPresetAndConfirm(/^pot$/i);
      return;
    }

    // MAX preset → confirm
    if (action === 'max' || action === 'raise_max') {
      clickPresetAndConfirm(/max|all/i);
      return;
    }

    // MIN preset → confirm
    if (action === 'min' || action === 'raise_min') {
      clickPresetAndConfirm(/^min$/i);
      return;
    }

    // HALF preset → confirm
    if (action === 'half' || action === '1/2') {
      clickPresetAndConfirm(/1\/2|half|½/i);
      return;
    }

    console.log('[W4P] Unknown command:', action);
  }

  // ── Pre-action executor ──────────────────────────────────────
  function runPreAction(avail) {
    if (!_preAction) return;
    if (_preAction === 'check_fold') {
      if (avail.indexOf('check') !== -1) clickSimple('check');
      else if (avail.indexOf('fold') !== -1) clickSimple('fold');
    } else if (_preAction === 'check_call') {
      if (avail.indexOf('check') !== -1) clickSimple('check');
      else if (avail.indexOf('call') !== -1) clickSimple('call');
    }
    _preAction = null;
  }

  // ── Buy-in handling ──────────────────────────────────────────
  function handleBuyin(cmd) {
    var mode = (cmd.type || '').replace('buyin_', '').replace('rebuy_', '');
    var modal = document.querySelector('sg-buy-in-modal');
    if (modal && modal.offsetParent !== null) {
      doBuyin(modal, mode, cmd.amount);
      return;
    }
    var hero = document.querySelector('.player-mini-container-p.self-player');
    if (hero) {
      hero.click();
      setTimeout(function() {
        var m = document.querySelector('sg-buy-in-modal');
        if (m) doBuyin(m, mode, cmd.amount);
        else console.log('[W4P] Buy-in modal did not appear');
      }, 400);
    } else {
      var buyBtns = document.querySelectorAll('button, [class*="buy"], [class*="rebuy"]');
      for (var i = 0; i < buyBtns.length; i++) {
        var txt = (buyBtns[i].textContent || '').trim().toLowerCase();
        if (/buy.?in|rebuy|top.?up/i.test(txt) && buyBtns[i].offsetParent !== null) {
          buyBtns[i].click();
          setTimeout(function() {
            var m = document.querySelector('sg-buy-in-modal');
            if (m) doBuyin(m, mode, cmd.amount);
          }, 400);
          return;
        }
      }
    }
  }

  function doBuyin(modal, mode, amount) {
    if (mode === 'max') {
      var maxBtn = modal.querySelector('.modal-balance-v li:nth-child(2) .last-v-p button');
      if (maxBtn && maxBtn.offsetParent !== null) {
        maxBtn.click();
        console.log('[W4P] Buy-in MAX clicked');
      }
    } else if (mode === 'min') {
      var minBtn = modal.querySelector('.modal-balance-v li:nth-child(2) .mini-button-view-m:first-child button');
      if (minBtn && minBtn.offsetParent !== null) {
        minBtn.click();
        console.log('[W4P] Buy-in MIN clicked');
      }
    } else if (amount) {
      var inputs = modal.querySelectorAll('input[type="number"], input[type="range"], input[type="text"]');
      for (var i = 0; i < inputs.length; i++) {
        if (inputs[i].offsetParent !== null) {
          var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeSet.call(inputs[i], String(amount));
          inputs[i].dispatchEvent(new Event('input', {bubbles: true}));
          inputs[i].dispatchEvent(new Event('change', {bubbles: true}));
          console.log('[W4P] Buy-in amount set:', amount);
          break;
        }
      }
    }
    setTimeout(function() {
      var submit = modal.querySelector('.modal-button-container button');
      if (submit && submit.offsetParent !== null) {
        submit.click();
        console.log('[W4P] Buy-in confirmed');
      }
    }, 300);
  }

  // ── Command polling loop ─────────────────────────────────────
  function pollCommands() {
    if (!_seatToken) {
      window._w4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 500);
      return;
    }

    fetch(API_BASE + '/commands/pending?token=' + encodeURIComponent(_seatToken))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok && data.command) {
          handleCommand(data.command);
          fetch(API_BASE + '/commands/ack', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: _seatToken, command_id: data.command.id })
          }).catch(function(){});
        }
      })
      .catch(function(){});

    window._w4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 500);
  }

  // ── Auto-untick "Wait for Big Blind" ─────────────────────────
  function untickWaitBB() {
    var cbs = document.querySelectorAll('input[type="checkbox"]');
    for (var i = 0; i < cbs.length; i++) {
      if (cbs[i].checked) {
        var label = cbs[i].parentElement ? cbs[i].parentElement.textContent : '';
        if (/wait.*big\s*blind|big\s*blind/i.test(label)) {
          cbs[i].click();
          console.log('[W4P] Unticked: Wait for Big Blind');
        }
      }
    }
    var toggles = document.querySelectorAll('.check-box-view-p.active, .toggle-switch.active, [class*="wait-bb"].active');
    for (var j = 0; j < toggles.length; j++) {
      var txt = toggles[j].textContent || '';
      if (/wait.*big\s*blind|big\s*blind/i.test(txt)) {
        toggles[j].click();
      }
    }
  }

  // ── Main snapshot loop ───────────────────────────────────────
  function tick() {
    _n++;
    var snap = buildSnapshot();

    if (!snap) {
      _mode = 'NO_TABLE';
      window._w4p_timer = setTimeout(tick, POLL_MS.NO_TABLE);
      return;
    }

    var hero = null;
    for (var i = 0; i < snap.seats.length; i++) {
      if (snap.seats[i].is_hero) { hero = snap.seats[i]; break; }
    }
    var avail = hero ? hero.available_actions : [];
    if (avail.length > 0) _mode = 'HERO_TURN';
    else if (snap.street !== 'PREFLOP') _mode = 'HAND_ACTIVE';
    else _mode = 'IDLE';

    var hash = stateHash(snap);
    var now = Date.now();
    var changed = hash !== _lastHash;
    var heartbeat = (now - _lastSendTime) >= HEARTBEAT_MS;

    if (changed || heartbeat) {
      _lastHash = hash;
      _lastSendTime = now;
      sendSnapshot(snap);

      if (hero) {
        console.log('[W4P] #' + _n + (heartbeat && !changed ? ' (hb)' : '') +
                    ' ' + snap.street + ' pot=R' + snap.pot_zar +
                    ' ' + hero.name + '@seat' + hero.seat_index +
                    ' [' + hero.hole_cards.join(',') + ']' +
                    ' seats=' + snap.seats.length +
                    ' board=' + (snap.board.flop.join('') || '-'));
      }
    }

    if (_preAction && avail.length > 0) {
      runPreAction(avail);
    }

    window._w4p_timer = setTimeout(tick, POLL_MS[_mode] || 1000);
  }

  // ── Start ────────────────────────────────────────────────────
  untickWaitBB();
  window._w4p_bbTimer = setInterval(untickWaitBB, 5000);

  console.log('[W4P] v16.1 native-clicks (slider-first) | session=' + _sessionId);
  console.log('[W4P] Polling: hero=' + POLL_MS.HERO_TURN + 'ms cmd=' + CMD_MS.HERO_TURN + 'ms');
  console.log('[W4P] API: ' + API_BASE + ' | Local engine');
  tick();

  // ── Public API for debugging ─────────────────────────────────
  window._w4p_buildSnapshot = buildSnapshot;
  window._w4pClickSimple = clickSimple;
  window._w4pClickPreset = clickPreset;
  window._w4pActions = getAvailableActions;
  window._w4p_injected = true;
  window._w4p_stop = function() {
    clearTimeout(window._w4p_timer);
    clearTimeout(window._w4p_cmdTimer);
    clearInterval(window._w4p_bbTimer);
    console.log('[W4P] stopped');
  };
})();

// PLOEXT v9.1 - PLO Remote Table Control
// Scrapes PokerBet DOM -> POSTs to 127.0.0.1:4000/api/snapshot
// Polls for commands from remote -> clicks PokerBet buttons

(function() {
  'use strict';

  // Cleanup previous instance
  if (window._n4p_timer) { clearTimeout(window._n4p_timer); window._n4p_timer = null; }
  if (window._n4p_cmdTimer) { clearTimeout(window._n4p_cmdTimer); window._n4p_cmdTimer = null; }

  var API_BASE = 'http://127.0.0.1:4000/api';
  var API_KEY = 'trk_default';

  // Adaptive polling intervals (ms) — fast for live play
  var POLL_MS = { HERO_TURN: 300, HAND_ACTIVE: 400, IDLE: 1000, NO_TABLE: 3000 };
  var CMD_MS  = { HERO_TURN: 100, HAND_ACTIVE: 200, IDLE: 500 };

  var _mode = 'IDLE';
  var _seatToken = null;
  var _preAction = null;   // 'check_fold' | 'check_call' | null
  var _lastHash = null;
  var _lastSendTime = 0;
  var HEARTBEAT_MS = 10000;  // resend every 10s even if unchanged (prevent stale eviction)
  var _n = 0;
  var _sessionId = 'ext_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);

  var RANK_MAP = { 'a':'A', 'k':'K', 'q':'Q', 'j':'J', 't':'T', '10':'T' };

  // ── Card parser ──────────────────────────────────────────────
  function parseCard(cls) {
    if (!cls) return null;
    var m = cls.match(/icon-layer2_([shdc])(10|[akqjt2-9])_p-c-d/i);
    if (!m) return null;
    var suit = m[1].toLowerCase();
    var rank = m[2].toLowerCase();
    rank = RANK_MAP[rank] || rank;
    return rank + suit;  // e.g. "As", "Kh", "Td", "7c"
  }

  // ── Table ID from URL ────────────────────────────────────────
  function getTableId() {
    var url = location.href;
    // Try skillgames iframe URL: /tbl/12345
    var m = url.match(/\/tbl\/(\d+)/);
    if (m) return m[1];
    // Try PokerBet main URL: /poker/28?openGames=28-real
    m = url.match(/\/poker\/(\d+)/);
    if (m) return m[1];
    // Try openGames param: ?openGames=28-real
    m = url.match(/openGames=(\d+)/);
    if (m) return m[1];
    // Try any game/table ID in URL
    m = url.match(/game[_-]?id[=\/](\d+)/i);
    if (m) return m[1];
    // Fallback: if we can see poker DOM elements, use a synthetic ID
    if (document.querySelector('.player-mini-container-p') || document.querySelector('sg-poker-table-seat')) {
      return 'table_' + (url.match(/(\d+)/) || ['', '0'])[1];
    }
    return null;
  }

  // ── Build full snapshot from PokerBet DOM ────────────────────
  function buildSnapshot() {
    var tableId = getTableId();
    if (!tableId) return null;

    var containers = document.querySelectorAll('.player-mini-container-p');
    if (!containers.length) containers = document.querySelectorAll('sg-poker-table-seat');
    if (!containers.length) return null;

    // Table size (6-max, 9-max etc)
    var fullTable = document.querySelector('.full-table-w-p');
    var szMatch = fullTable ? fullTable.className.match(/player-count-(\d+)/) : null;
    var tableSize = szMatch ? parseInt(szMatch[1]) : 6;

    // Dealer position
    var dealerEl = document.querySelector('.dealer-icon-view');
    var dMatch = dealerEl ? dealerEl.className.match(/position-(\d+)/) : null;
    var dealerSeat = dMatch ? parseInt(dMatch[1]) : null;

    // Pot amount
    var potEl = document.querySelector('.pot-w-view-p');
    var potText = potEl ? potEl.innerText : '';
    var pMatch = potText.match(/([\d.,]+)/);
    var potZar = pMatch ? parseFloat(pMatch[1].replace(',', '')) : 0;

    // Board cards (community cards only, skip player cards)
    var allCardEls = document.querySelectorAll('.single-cart-view-p');
    var boardCards = [];
    for (var i = 0; i < allCardEls.length; i++) {
      var el = allCardEls[i];
      if (el.closest('.player-mini-container-p')) continue;
      var c = parseCard(el.className);
      if (c) boardCards.push(c);
    }

    var street = 'PREFLOP';
    if (boardCards.length >= 5) street = 'RIVER';
    else if (boardCards.length >= 4) street = 'TURN';
    else if (boardCards.length >= 3) street = 'FLOP';

    // Seats
    var seats = [];
    var heroName = null;
    for (var i = 0; i < containers.length; i++) {
      var ct = containers[i];
      var isHero = ct.classList.contains('self-player');
      var isSittingOut = ct.classList.contains('seat-out-v');

      var posMatch = ct.className.match(/position-(\d+)/);
      var seatIdx = posMatch ? parseInt(posMatch[1]) : i;

      var nameEl = ct.querySelector('p.single-win-item-sizes');
      var name = nameEl ? nameEl.innerText.trim() : null;
      if (isHero && name) heroName = name;

      var stackEl = ct.querySelector('.player-text-info-p span b');
      var stackText = stackEl ? stackEl.innerText : '';
      var sMatch = stackText.match(/([\d.,]+)/);
      var stackZar = sMatch ? parseFloat(sMatch[1].replace(',', '')) : 0;

      var cardsContainer = ct.querySelector('.carts-container-p');
      var ccMatch = cardsContainer ? cardsContainer.className.match(/cards-count-(\d+)/) : null;
      var cardsCount = ccMatch ? parseInt(ccMatch[1]) : 0;

      // Only extract actual card values for hero (others are face-down)
      var holeCards = [];
      if (isHero) {
        var hcEls = ct.querySelectorAll('.single-cart-view-p');
        for (var j = 0; j < hcEls.length; j++) {
          var hc = parseCard(hcEls[j].className);
          if (hc) holeCards.push(hc);
        }
      }

      var status = 'playing';
      if (isSittingOut) status = 'sitting_out';
      else if (cardsCount === 0 && street !== 'PREFLOP') status = 'folded';

      seats.push({
        seat_index: seatIdx,
        name: name,
        stack_zar: stackZar,
        hole_cards: holeCards,
        cards_count: cardsCount,
        is_hero: isHero,
        is_dealer: seatIdx === dealerSeat,
        status: status
      });
    }

    // Action buttons visible on hero's turn
    var foldBtn = document.querySelector('.control-b-view-p.fold-c');
    var checkBtn = document.querySelector('.control-b-view-p.check-c');
    var callBtn = document.querySelector('.control-b-view-p.call-c');
    var cashoutBtn = document.querySelector('.control-b-view-p.cashout-c');

    return {
      player_id: heroName || 'ploext-player',
      session_id: _sessionId,
      table_id: tableId,
      deal_id: boardCards.slice(0, 3).sort().join('') || 'preflop',
      timestamp_utc: new Date().toISOString(),
      variant: 'plo4-' + tableSize + 'max',
      street: street,
      table_size: tableSize,
      dealer_seat: dealerSeat,
      pot_zar: potZar,
      seats: seats,
      board: {
        flop: boardCards.slice(0, 3),
        turn: boardCards[3] || null,
        river: boardCards[4] || null
      },
      action_buttons: {
        visible: !!(foldBtn || checkBtn || callBtn || cashoutBtn),
        fold: !!foldBtn,
        check: !!checkBtn,
        call: !!callBtn,
        cashout: !!cashoutBtn
      },
      source_key: 'ploext'
    };
  }

  // ── State hash for dedup ─────────────────────────────────────
  function stateHash(snap) {
    return JSON.stringify({
      s: snap.seats.map(function(s) { return (s.name||'') + ':' + s.stack_zar + ':' + s.status + ':' + s.hole_cards.join(''); }),
      b: snap.board, p: snap.pot_zar, st: snap.street, d: snap.dealer_seat, a: snap.action_buttons.visible
    });
  }

  // ── Command execution on PokerBet DOM ────────────────────────
  var BTN_SEL = {
    fold:    '.control-b-view-p.fold-c',
    check:   '.control-b-view-p.check-c',
    call:    '.control-b-view-p.call-c',
    cashout: '.control-b-view-p.cashout-c'
  };

  function clickAction(action) {
    var sel = BTN_SEL[action];
    if (!sel) { console.log('[N4P] Unknown action:', action); return; }
    var btn = document.querySelector(sel);
    if (btn) { btn.click(); console.log('[N4P] Clicked:', action); }
    else { console.log('[N4P] Button not found:', action); }
  }

  function handleCommand(cmd) {
    if (BTN_SEL[cmd.type]) {
      clickAction(cmd.type);
    } else if (cmd.type === 'check_fold') {
      _preAction = 'check_fold';
    } else if (cmd.type === 'check_call') {
      _preAction = 'check_call';
    } else if (cmd.type === 'clear') {
      _preAction = null;
    }
  }

  function runPreAction(buttons) {
    if (!_preAction) return;
    if (_preAction === 'check_fold') {
      if (buttons.check) clickAction('check');
      else if (buttons.fold) clickAction('fold');
    } else if (_preAction === 'check_call') {
      if (buttons.check) clickAction('check');
      else if (buttons.call) clickAction('call');
    }
    _preAction = null;
  }

  // ── Command polling loop ─────────────────────────────────────
  function pollCommands() {
    if (!_seatToken) {
      window._n4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 1000);
      return;
    }
    fetch(API_BASE + '/commands/pending?token=' + encodeURIComponent(_seatToken))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok && data.command) {
          console.log('[N4P] Command:', data.command.type);
          handleCommand(data.command);
          fetch(API_BASE + '/commands/ack', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: _seatToken, command_id: data.command.id })
          });
        }
      })
      .catch(function() { /* silent retry */ })
      .finally(function() {
        window._n4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 1000);
      });
  }

  // ── Main snapshot loop ───────────────────────────────────────
  // NOTE: No slowdown when tab hidden — user is viewing the remote tab,
  // so we MUST keep sending at full speed. DOM is still accessible.
  function tick() {
    _n++;
    var snap = buildSnapshot();

    if (!snap) {
      _mode = 'NO_TABLE';
      window._n4p_timer = setTimeout(tick, POLL_MS.NO_TABLE);
      return;
    }

    // Adaptive polling mode
    if (snap.action_buttons.visible) _mode = 'HERO_TURN';
    else if (snap.street !== 'PREFLOP') _mode = 'HAND_ACTIVE';
    else _mode = 'IDLE';

    // Send on state change OR heartbeat (prevent backend stale eviction)
    var hash = stateHash(snap);
    var now = Date.now();
    var changed = hash !== _lastHash;
    var heartbeat = (now - _lastSendTime) >= HEARTBEAT_MS;

    if (changed || heartbeat) {
      _lastHash = hash;
      _lastSendTime = now;

      fetch(API_BASE + '/snapshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify(snap)
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok && data.seat_token && !_seatToken) {
          _seatToken = data.seat_token;
          console.log('[N4P] Connected! Token:', _seatToken.substr(0, 8) + '...');
          pollCommands();  // Start command polling once connected
        }
      })
      .catch(function(e) { console.log('[N4P] Send error:', e.message); });

      var filled = snap.seats.filter(function(s) { return s.name; }).length;
      console.log('[N4P] #' + _n + (heartbeat && !changed ? ' (heartbeat)' : '') +
                  ' ' + snap.street + ' pot=R' + snap.pot_zar +
                  ' seats=' + filled + '/' + snap.seats.length +
                  ' board=' + (snap.board.flop.join('') || '-'));
    }

    // Fire pre-action if queued and buttons visible
    if (_preAction && snap.action_buttons.visible) {
      runPreAction(snap.action_buttons);
    }

    window._n4p_timer = setTimeout(tick, POLL_MS[_mode] || 2000);
  }

  // ── Start ────────────────────────────────────────────────────
  console.log('[N4P] PLOEXT v9.1 loaded | Remote: 127.0.0.1:4000/remote');
  console.log('[N4P] Session:', _sessionId);
  tick();

  // Expose for debugging
  window._n4p_buildSnapshot = buildSnapshot;
  window._n4p_injected = true;
})();

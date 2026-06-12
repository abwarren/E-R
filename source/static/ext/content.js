// PLO Remote Control - Content Script
// Runs inside poker-web.pokerbet.co.za iframe (all_frames: true)
// Scrapes table DOM, relays via background.js (no CORS issues)

(function() {
  'use strict';

  // Only run inside the poker iframe (18751019 in URL)
  if (!location.href.includes('18751019') && !location.href.includes('skillgames')) {
    return;
  }

  // Only run on table pages (URL contains /tbl/)
  // Wait for table to appear in URL
  let waitCount = 0;
  function waitForTable() {
    if (location.href.includes('/tbl/')) {
      console.log('[PLO-EXT] Table detected, starting scraper');
      init();
    } else if (waitCount < 300) { // Wait up to 5 minutes
      waitCount++;
      setTimeout(waitForTable, 1000);
    }
  }
  waitForTable();

  // Watch for URL changes (SPA navigation)
  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      if (location.href.includes('/tbl/')) {
        console.log('[PLO-EXT] Table navigation detected');
        init();
      }
    }
  }).observe(document, {subtree: true, childList: true});

  let _initialized = false;
  let _sessionId = 'ext_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
  let _lastSampleKey = null;
  let _preAction = null;
  let _tableId = null;
  let _seatNo = null;
  let _n = 0;

  function init() {
    if (_initialized) return;
    _initialized = true;
    console.log('[PLO-EXT] Initializing scraper, session:', _sessionId);
    setInterval(poll, 2000);
  }

  // Listen for commands from background
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'EXECUTE_COMMAND') {
      handleCommand(msg.command);
    } else if (msg.type === 'SEAT_ASSIGNED') {
      _tableId = msg.table_id;
      _seatNo = msg.seat_no;
    }
  });

  // ── DOM SCRAPING (ported from n4p.js v1.1) ──

  function getTableId() {
    var match = location.href.match(/\/tbl\/(\d+)/);
    return match ? match[1] : null;
  }

  function isVisible(el) {
    if (!el) return false;
    if (el.offsetParent === null) return false;
    var style = getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0;
  }

  function getSelfPlayerContainer() {
    var selfMarker = document.querySelector('.player-name-count-v.self-player');
    if (!selfMarker) return null;
    return selfMarker.closest('.player-mini-container-p');
  }

  function getSelfPlayerCards() {
    var selfContainer = getSelfPlayerContainer();
    if (!selfContainer) return [];
    var cards = [];
    var cardElems = selfContainer.querySelectorAll('.cards-view-b-p.animate-show .single-cart-view-p');
    for (var i = 0; i < cardElems.length; i++) {
      var cardMatch = cardElems[i].className.match(/icon-layer2_([shdc])(10|[akqjt2-9])_p-c-d/i);
      if (cardMatch) cards.push(cardMatch[2].toLowerCase() + cardMatch[1].toLowerCase());
    }
    return cards;
  }

  function buildSnapshot() {
    var tableId = getTableId();
    if (!tableId) return null;

    var containers = document.querySelectorAll('.player-mini-container-p');
    if (containers.length === 0) return null;

    var fullTableEl = document.querySelector('.full-table-w-p');
    var tableSizeMatch = fullTableEl ? fullTableEl.className.match(/player-count-(\d+)/) : null;
    var tableSize = tableSizeMatch ? parseInt(tableSizeMatch[1]) : 6;

    var dealerEl = document.querySelector('.dealer-icon-view');
    var dealerMatch = dealerEl ? dealerEl.className.match(/position-(\d+)/) : null;
    var dealerSeat = dealerMatch ? parseInt(dealerMatch[1]) : null;

    var potEl = document.querySelector('.pot-w-view-p');
    var potText = potEl ? potEl.innerText : '';
    var potMatch = potText.match(/([\d.,]+)/);
    var potZar = potMatch ? parseFloat(potMatch[1].replace(',', '')) : null;

    // Board cards (not inside player containers)
    var allCards = document.querySelectorAll('.single-cart-view-p');
    var boardCards = [];
    for (var i = 0; i < allCards.length; i++) {
      var card = allCards[i];
      var isPlayerCard = false;
      var parent = card.parentElement;
      while (parent) {
        if (parent.classList && parent.classList.contains('player-mini-container-p')) { isPlayerCard = true; break; }
        parent = parent.parentElement;
      }
      if (!isPlayerCard) {
        var cm = card.className.match(/icon-layer2_([shdc])(10|[akqjt2-9])_p-c-d/i);
        if (cm) boardCards.push(cm[2].toLowerCase() + cm[1].toLowerCase());
      }
    }

    var street = 'PREFLOP';
    if (boardCards.length >= 3) street = 'FLOP';
    if (boardCards.length >= 4) street = 'TURN';
    if (boardCards.length >= 5) street = 'RIVER';

    var selfContainer = getSelfPlayerContainer();

    var seats = [];
    for (var i = 0; i < containers.length; i++) {
      var cont = containers[i];
      var posMatch = cont.className.match(/position-(\d+)/);
      var seatIndex = posMatch ? parseInt(posMatch[1]) : i;
      var isSelf = (cont === selfContainer);

      var nameEl = cont.querySelector('.player-name-count-v .single-win-item-sizes');
      var name = nameEl ? nameEl.innerText.trim() : null;

      var stackEl = cont.querySelector('.player-text-info-p b');
      var stackText = stackEl ? stackEl.innerText : '0';
      var stackMatch = stackText.match(/([\d.,]+)/);
      var stackZar = stackMatch ? parseFloat(stackMatch[1].replace(',', '')) : 0;

      var holeCards = isSelf ? getSelfPlayerCards() : [];
      var cardsCount = cont.querySelectorAll('.single-cart-view-p').length;
      var status = 'sitting_out';
      if (name && cardsCount > 0) status = 'playing';
      else if (cardsCount === 0) status = 'folded';

      seats.push({
        seat_index: seatIndex, name: name, stack_zar: stackZar,
        hole_cards: holeCards, status: status,
        is_hero: isSelf, is_dealer: seatIndex === dealerSeat
      });
    }

    var foldBtn = document.querySelector('div.control-b-view-p.fold-c');
    var checkBtn = document.querySelector('div.control-b-view-p.check-c');
    var callBtn = document.querySelector('div.control-b-view-p.call-c');
    var raiseBtn = document.querySelector('div.control-b-view-p.raise-c');
    var allinBtn = document.querySelector('div.control-b-view-p.allin-c, div.control-b-view-p.all-in-c');
    var cashoutBtn = document.querySelector('.control-b-view-p.cashout-c');

    return {
      table_id: tableId, variant: 'plo', street: street,
      pot_zar: potZar, dealer_seat: dealerSeat,
      board: { flop: boardCards.slice(0, 3), turn: boardCards[3] || null, river: boardCards[4] || null },
      seats: seats,
      action_buttons: {
        visible: !!(foldBtn || checkBtn || callBtn || raiseBtn || allinBtn),
        fold: isVisible(foldBtn), check: isVisible(checkBtn), call: isVisible(callBtn),
        raise: isVisible(raiseBtn), allin: isVisible(allinBtn), cashout: isVisible(cashoutBtn)
      },
      session_id: _sessionId
    };
  }

  // ── MAIN POLL ──

  function poll() {
    _n++;
    var snap = buildSnapshot();
    if (!snap) return;

    var hero = snap.seats.find(s => s.is_hero);
    if (!hero || !hero.name) return;

    // Deduplicate
    var sampleKey = snap.table_id + ':' + snap.street + ':' + snap.pot_zar + ':' + (hero.hole_cards || []).join(',');
    if (hero.hole_cards.length > 0 && sampleKey !== _lastSampleKey) {
      _lastSampleKey = sampleKey;
      // Send to background for API POST
      chrome.runtime.sendMessage({type: 'POST_SNAPSHOT', data: snap});
      console.log('[PLO-EXT] #' + _n + ' table=' + snap.table_id + ' street=' + snap.street + ' pot=' + snap.pot_zar);
    }

    // Execute pre-action if buttons visible
    if (_preAction && snap.action_buttons.visible) {
      executePreAction(_preAction, snap.action_buttons);
    }
  }

  // ── COMMAND EXECUTION ──

  function handleCommand(cmd) {
    console.log('[PLO-EXT] Command:', cmd.type);
    if (['fold', 'check', 'call', 'allin', 'cashout'].includes(cmd.type)) {
      executeNow(cmd.type);
    } else if (cmd.type === 'raise_max') {
      executeRaiseMax();
    } else if (cmd.type === 'check_fold') {
      _preAction = 'check_fold';
    } else if (cmd.type === 'check_call') {
      _preAction = 'check_call';
    } else if (cmd.type === 'clear_preaction') {
      _preAction = null;
    }
  }

  function executeNow(action) {
    var selectors = {
      fold: 'div.control-b-view-p.fold-c',
      check: 'div.control-b-view-p.check-c',
      call: 'div.control-b-view-p.call-c',
      allin: 'div.control-b-view-p.allin-c, div.control-b-view-p.all-in-c',
      cashout: '.control-b-view-p.cashout-c'
    };
    var btn = document.querySelector(selectors[action]);
    if (btn && isVisible(btn)) {
      btn.click();
      console.log('[PLO-EXT] Clicked:', action);
    }
  }

  function executeRaiseMax() {
    var raiseInput = document.querySelector('input.ng-untouched.ng-pristine.ng-valid:not([type="checkbox"])') ||
                     document.querySelector('input[type="text"]:not([type="checkbox"])');
    var raiseBtn = document.querySelector('div.control-b-view-p.raise-c');
    if (!raiseBtn || !isVisible(raiseBtn)) return;

    if (raiseInput) {
      var stackEl = document.querySelector('.player-mini-container-p.self-player .player-text-info-p b');
      var stackText = stackEl ? stackEl.innerText : '0';
      var stackMatch = stackText.match(/([\d.,]+)/);
      var maxAmount = stackMatch ? stackMatch[1].replace(',', '') : '999999';
      raiseInput.focus(); raiseInput.value = maxAmount;
      raiseInput.dispatchEvent(new Event('input', {bubbles: true}));
      raiseInput.dispatchEvent(new Event('change', {bubbles: true}));
      raiseInput.blur();
      setTimeout(() => { if (isVisible(raiseBtn)) raiseBtn.click(); }, 100);
    } else {
      var allinBtn = document.querySelector('div.control-b-view-p.allin-c, div.control-b-view-p.all-in-c');
      if (allinBtn && isVisible(allinBtn)) allinBtn.click();
    }
  }

  function executePreAction(preAction, buttons) {
    if (preAction === 'check_fold') {
      if (buttons.check) executeNow('check');
      else if (buttons.fold) executeNow('fold');
    } else if (preAction === 'check_call') {
      if (buttons.check) executeNow('check');
      else if (buttons.call) executeNow('call');
    }
    _preAction = null;
  }

  console.log('[PLO-EXT] Content script loaded for:', location.href);
})();

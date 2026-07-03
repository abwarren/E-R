// ╔══════════════════════════════════════════════════════════════════════════════╗
// ║  ⛔ DO NOT REMOVE SEAT STABILITY LAYER (lines ~361-690)                     ║
// ║                                                                            ║
// ║  Commit 74acebe (2026-07-01) removed this layer and regressed:             ║
// ║  - seat_index fell back to loop index i, causing seat collisions           ║
// ║  - multiple seats shared same position → players vanished from UI          ║
// ║  - Fixed by cf328c7 (2026-07-01) — restored v24-bootstrap                  ║
// ║                                                                            ║
// ║  PROTECTED: _seatCache, resolveSeatIndex(), isTableReady(),                ║
// ║  _lastGoodSnapshot, _bootstrapped, collision rejection, swap detection      ║
// ║  See docs/audit-2026-07-01/SEATMAP_REGRESSION_AUDIT.md                     ║
// ║                                                                            ║
// ║  The selector registry (SEL.*, detectRuntime(), validateSelectorRegistry)   ║
// ║  and seat stability layer MUST COEXIST. Neither replaces the other.         ║
// ╚══════════════════════════════════════════════════════════════════════════════╝
//
// W4P Injectable v24-bootstrap+selectors — PLO Remote Table Control (hero-only: .self-player class ONLY, no fallbacks)
// v24: seat stability layer — identity→seat cache, debounce, collision rejection, table readiness gate
//      No more seat_index fallback to loop index. No more seat collisions.
//      Seats persist across polls and hand boundaries. Table must be fully initialized before scraping.
// ADR-013/014: selector registry — runtime detection, SEL.* references, validation gate
// v19: remove .active gate — self-player + visible buttons = available_actions
// v19.1-3: fix MAX flow, diagnostics, getBoundingClientRect consistency
// v20: unified direct fetch — same file works as extension AND standalone (no bridge.js needed)
// v20.1: MAX fix — skip preset clicks (isTrusted=false), use slider.max + setSliderValue + confirmRaise
// v21: Preset-first model — click preset <li>, wait for <i> amount change, THEN click BET/RAISE
//      No openRaiseSlider. No slider input[range] manipulation. No all-in logic.
//      Hard rule: never execute BET/RAISE unless <i> amount changed or was already correct.
// v22: cashout preselect persistence across hand transitions, pre-action persistence, 75ms hyper-poll
// v22-stable-hardened: guards, cooldowns, duplicate command protection, enhanced logging. No behaviour changes.
// Extension runtime: deployed to KasmVNC containers via docker cp
// Rollback: w4p.js.v22-stable.bak in same directory
// Paste into skillgames iframe console, or: fetch('http://127.0.0.1:4000/remote/w4p.js').then(r=>r.text()).then(eval)
// Scrapes ALL seats, sends structured snapshots with button detection, polls commands, clicks buttons
// No chrome.runtime deps — pure fetch-based

(function(){
  'use strict';

  // ── URL Guard: only run on real PokerBet/GoldRush poker game frames ──
  function hasPokerTableProof() {
    try {
      return !!document.querySelector(
        SEL.tableProof
      );
    } catch (e) {
      return false;
    }
  }

  function isPokerScrapeContext() {
    var href = location.href || '';
    var host = location.hostname || '';
    var path = location.pathname || '';

    if (
      host === '127.0.0.1' ||
      host === 'localhost' ||
      host === '127.0.0.1'
    ) {
      return false;
    }

    if (href === 'about:blank' || href.indexOf('about:blank') === 0) return false;

    if (host.indexOf('poker-web.goldrush.co.za') !== -1) {
      return true;
    }

    if (host.indexOf('games.goldrush.co.za') !== -1) {
      if (/\/LaunchGame|\/Inner\/authorization\.php|authorization/i.test(href)) return false;
      return hasPokerTableProof();
    }

    if (host.indexOf('www.goldrush.co.za') !== -1 && path.indexOf('/live-poker') !== -1) {
      return hasPokerTableProof();
    }

    return false;
  }

  function stopW4PTimers() {
    if (window._w4p_timer) { clearTimeout(window._w4p_timer); window._w4p_timer = null; }
    if (window._w4p_cmdTimer) { clearTimeout(window._w4p_cmdTimer); window._w4p_cmdTimer = null; }
    if (window._w4p_bbTimer) { clearInterval(window._w4p_bbTimer); window._w4p_bbTimer = null; }
    if (window._w4p) { clearInterval(window._w4p); window._w4p = null; }
  }

  var _nonPokerStopLogged = false;
  function stopNonPokerScrapeContext(stage) {
    if (isPokerScrapeContext()) return false;
    stopW4PTimers();
    if (!_nonPokerStopLogged) {
      _nonPokerStopLogged = true;
      console.log('[W4P][STOP] non-poker scrape context', {
        href: location.href,
        title: document.title,
        host: location.hostname,
        stage: stage || 'guard'
      });
    }
    return true;
  }

  if (!isPokerScrapeContext()) {
    stopNonPokerScrapeContext('startup');
    return;
  }

  // ── Cleanup prior instances ──────────────────────────────────
  if (window._w4p_timer) { clearTimeout(window._w4p_timer); window._w4p_timer = null; }
  if (window._w4p_cmdTimer) { clearTimeout(window._w4p_cmdTimer); window._w4p_cmdTimer = null; }
  if (window._w4p_bbTimer) { clearInterval(window._w4p_bbTimer); window._w4p_bbTimer = null; }
  if (window._w4p) { clearInterval(window._w4p); window._w4p = null; }
  window._w4p_injected = false;

  // ── Config: Local Only — No external URLs ────────────────────
  var API_BASE = 'http://127.0.0.1:4000/api';
  var API_KEY  = '03622c896cfbeacdfc537e9434f9ddc5';
  var SITE_BASE = 'http://127.0.0.1:4000';

  // ── Runtime Detection — Desktop vs Mobile ──────────────────────
  function detectRuntime() {
    // Mobile: URL path contains /mobile
    if (location.pathname.indexOf('/mobile') !== -1) return 'mobile';
    return 'desktop';
  }

  // ── Selector Registry (ADR-013/ADR-014) ────────────────────────
  // One parser. Multiple selector profiles.
  // Every runtime must expose the same capabilities — only selector strings differ.
  // Mobile selectors populated ONLY from verified runtime DOM capture.

  // Required selectors — every runtime profile must provide these.
  // If any required selector is null/missing, parsing is disabled for that runtime.
  var REQUIRED_SELECTORS = [
    'seatContainer', 'seatContainerAlt',
    'heroClass', 'heroSeatAlt',
    'playerName', 'playerNameAlt',
    'stack', 'stackAlt',
    'boardContainer', 'boardCard',
    'potContainer',
    'dealerIcon',
    'holeCardsContainer',
    'buttons'  // buttons object with fold/check/call/raise/bet sub-keys
  ];

  // Action button schema — every runtime must provide these action names
  var REQUIRED_BUTTONS = ['fold', 'check', 'call', 'raise', 'bet'];

  function validateSelectorRegistry(runtime) {
    var profile = SELECTORS[runtime];
    if (!profile) {
      console.error('[W4P] FATAL: No selector profile for runtime=' + runtime);
      return false;
    }

    var missing = [];
    for (var i = 0; i < REQUIRED_SELECTORS.length; i++) {
      var key = REQUIRED_SELECTORS[i];
      if (profile[key] === null || profile[key] === undefined || profile[key] === '') {
        missing.push(key);
      }
    }

    // Validate button sub-keys
    if (profile.buttons) {
      for (var b = 0; b < REQUIRED_BUTTONS.length; b++) {
        var bk = REQUIRED_BUTTONS[b];
        if (!profile.buttons[bk]) {
          missing.push('buttons.' + bk);
        }
      }
    } else {
      missing.push('buttons');
    }

    if (missing.length > 0) {
      console.warn('[W4P] BLOCKED: Runtime=' + runtime + ' missing selectors: ' + missing.join(', '));
      return false;
    }

    console.log('[W4P] Selector registry valid for runtime=' + runtime +
      ' (' + REQUIRED_SELECTORS.length + ' selectors, ' +
      Object.keys(profile.buttons || {}).length + ' buttons)');
    return true;
  }

  var SELECTORS = {
    desktop: {
      // Seat containers
      seatContainer:    'sg-poker-table-seat',
      seatContainerAlt: '.player-mini-container-p',
      // Hero
      heroClass:        '.self-player',
      heroSeat:         'sg-poker-table-seat.self-player',
      heroSeatAlt:      '.player-mini-container-p.self-player',
      // Player info
      playerName:       'p.single-win-item-sizes',
      playerNameAlt:    '.player-name',
      stack:            '.player-text-info-p span b',
      stackAlt:         '.player-text-info-p b',
      stackAlt2:        '.player-stack',
      // Board
      boardContainer:   'sg-poker-board',
      boardCard:        '.single-cart-view-p',
      // Pot
      potContainer:     '.pot-w-view-p',
      potAlt:           '.pot-amount',
      potAlt2:          '.total-pot',
      // Dealer
      dealerIcon:       '.dealer-icon-view',
      // Hole cards
      holeCardsContainer: '.carts-container-p',
      holeCard:         '.single-cart-view-p',
      // State
      sittingOut:       '.seat-out-v',
      activeTurn:       '.active-turn',
      activeTurnAlt:    '.active-turn',
      // Betting slider
      bettingSlider:    'sg-poker-betting-slider input[type="range"]',
      genericSlider:    'input[type="range"]',
      genericNumber:    'input[type="number"], input[type="text"]',
      // Table proof (frame discovery)
      tableProof:       'sg-poker-table, sg-poker-table-seat, .player-mini-container-p, .control-b-view-p, .pot-w-view-p, .single-cart-view-p',
      // Action buttons
      buttons: {
        fold:          '.control-b-view-p.fold-c',
        check:         '.control-b-view-p.check-c',
        call:          '.control-b-view-p.call-c',
        raise:         '.control-b-view-p.raise-c',
        bet:           '.control-b-view-p.bet-c',
        cashout:       '.control-b-view-p.cash_out-c',
        allin:         '.control-b-view-p.all_in-c',
        show:          '.control-b-view-p.show-c',
        run_it_twice:  '.control-b-view-p.run_it_twice-c',
        resume_hand:   '.control-b-view-p.resume_hand-c',
        back_to_game:  '.control-b-view-p.back_to_game-c'
      }
    },
    mobile: {
      // Populated from verified mobile DOM capture ONLY.
      // Never guessed. Never inferred from desktop.
      // Currently BLOCKED — awaiting live mobile runtime data.
      seatContainer:    null,
      seatContainerAlt: null,
      heroClass:        null,
      heroSeat:         null,
      heroSeatAlt:      null,
      playerName:       null,
      playerNameAlt:    null,
      stack:            null,
      stackAlt:         null,
      stackAlt2:        null,
      boardContainer:   null,
      boardCard:        null,
      potContainer:     null,
      potAlt:           null,
      potAlt2:          null,
      dealerIcon:       null,
      holeCardsContainer: null,
      holeCard:         null,
      sittingOut:       null,
      activeTurn:       null,
      activeTurnAlt:    null,
      bettingSlider:    null,
      genericSlider:    null,
      genericNumber:    null,
      tableProof:       null,
      buttons:          null
    }
  };

  // Runtime selector profile + validation gate
  var RUNTIME = detectRuntime();
  var SEL = SELECTORS[RUNTIME];
  var _registryValid = validateSelectorRegistry(RUNTIME);

  console.log('[W4P] RUNTIME=' + RUNTIME +
    ' | bridge=postMessage' +
    ' | registry=' + (_registryValid ? 'VALID' : 'BLOCKED') +
    ' | selectors=' + (SEL.buttons ? Object.keys(SEL.buttons).length + '-buttons' : 'empty'));
  var API_KEY  = '03622c896cfbeacdfc537e9434f9ddc5';

  // ── Bridge relay: postMessage → bridge.js → background.js → fetch ──
  var _reqId = 0;
  var _callbacks = {};

  // Listen for bridge.js responses (ISOLATED world → MAIN world)
  window.addEventListener('message', function(e) {
    if (!e.data || e.data.channel !== 'W4P_BRIDGE_RESPONSE') return;
    var resp = e.data;
    var cb = _callbacks[resp.reqId];
    if (cb) {
      delete _callbacks[resp.reqId];
      cb(resp.response);
    }
  });

  function bridgeFetch(path, method, body, callback) {
    _reqId++;
    if (callback) _callbacks[_reqId] = callback;
    window.postMessage({
      channel: 'W4P_BRIDGE',
      path: path, method: method, body: body,
      apiKey: API_KEY, rawPath: false, reqId: _reqId
    }, '*');
  }
  function bridgeFetchRaw(path, method, body, callback) {
    _reqId++;
    if (callback) _callbacks[_reqId] = callback;
    window.postMessage({
      channel: 'W4P_BRIDGE',
      path: path, method: method, body: body,
      apiKey: API_KEY, rawPath: true, reqId: _reqId
    }, '*');
  }

  function logFrameDiagnostics(reason) {
    try {
      var bodyText = document.body ? (document.body.innerText || '') : '';
      var all = document.querySelectorAll('*');
      var classCounts = {};
      var candidateSeatElements = 0;
      var cardLikeElementsCount = 0;
      var buttonLikeElementsCount = 0;
      for (var i = 0; i < Math.min(all.length, 500); i++) {
        var el = all[i];
        var tag = el.tagName.toLowerCase();
        var cn = String(el.className || '');
        if (/seat|player|poker|table/i.test(tag + ' ' + cn)) candidateSeatElements++;
        if (/card|cart|single-cart/i.test(tag + ' ' + cn)) cardLikeElementsCount++;
        if (/button|btn|control|action|fold|check|call|raise|bet/i.test(tag + ' ' + cn)) buttonLikeElementsCount++;
        if (cn) {
          var parts = cn.trim().split(/\s+/);
          for (var p = 0; p < parts.length; p++) {
            if (parts[p]) classCounts[parts[p]] = (classCounts[parts[p]] || 0) + 1;
          }
        }
      }
      console.log('[W4P][FRAME-DIAG]', {
        reason: reason,
        currentFrameUrl: location.href.substring(0, 200),
        title: (document.title || '').substring(0, 100),
        bodyTextLength: bodyText.length,
        visibleTextSample: bodyText.replace(/\s+/g, ' ').substring(0, 500),
        candidateSeatElements: candidateSeatElements,
        candidateClassNames: Object.keys(classCounts).sort(function(a, b) { return classCounts[b] - classCounts[a]; }).slice(0, 30),
        cardLikeElementsCount: cardLikeElementsCount,
        buttonLikeElementsCount: buttonLikeElementsCount,
        elemCount: all.length,
        inIframe: window !== window.top
      });
    } catch (e) {
      console.log('[W4P][FRAME-DIAG] error:', e.message);
    }
  }

  // v15: tightened polling — faster detection, faster commands
  var POLL_MS = { HERO_TURN: 300, HAND_ACTIVE: 300, IDLE: 300, NO_TABLE: 2000 };
  var CMD_MS  = { HERO_TURN: 150, HAND_ACTIVE: 150, IDLE: 150 };
  var HEARTBEAT_MS = 8000;
  var CASHOUT_POLL_MS = 75;  // hyper-poll interval when cashout preselected

  var _mode = 'IDLE';
  var _seatToken = null;
  var _handId = null;           // ADR-001: echoed from backend, sent in snapshots
  var _preAction = null;    // 'check_fold' | 'check_call' | null
  var _lastHash = null;
  var _lastSendTime = 0;
  var _n = 0;
  var _sessionId = 'w4p_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
  var _lastButtons = null;
  var _cashoutPre = false;   // when true, hyper-poll for cashout DOM element
  var _cashoutTimer = null;
  var _lastBoardLen = 0;     // track board cards for new hand detection
  var _lastStreet = null;    // track street for pre-action clearing

  // ── Seat stability layer ──────────────────────────────────────
  // ⛔ PROTECTED — DO NOT REMOVE (see file header for audit trail)
  // Identity→seat cache: playerName → stable_seat_index
  // Persists across polls and hand boundaries.
  // Removing this block caused seat collisions (commit 74acebe → cf328c7)
  var _seatCache = {};                   // { playerName: seat_index }
  var _seatLastSeen = {};               // { playerName: timestamp_ms }
  var _pendingCandidates = {};          // { playerName: { seat_index: N, count: M, since: ms } }
  var _collisionsThisPoll = [];         // collision diagnostics
  var _tableReadyState = false;         // all containers present AND have position-N
  var _lastContainerCount = -1;         // for detecting count changes
  var DEBOUNCE_COUNT = 3;              // polls required before accepting new assignment
  var _bootstrapped = false;            // true after first successful snapshot
  var SEAT_STALE_MS = 120000;           // 2 min — forget player if unseen this long
  var _lastGoodSnapshot = null;         // preserved when DOM temporarily lacks containers

  // ── v22-hardened: duplicate command guard + action cooldowns ──
  var _lastCmdId = null;              // last executed command ID — reject duplicates
  var _actionCooldowns = {};          // { 'action_name': timestamp } — per-action cooldown
  var _ACTION_COOLDOWN_MS = 800;      // min ms between same action (prevent double-click)
  var _PRESET_COOLDOWN_MS = 1500;     // min ms between preset executions (preset→verify→execute cycle)
  var _cmdCount = 0;                  // total commands processed this session

  var RANK_MAP = { 'a':'A', 'k':'K', 'q':'Q', 'j':'J', 't':'T', '10':'T' };

  // ── Action button selectors (PokerBet / BetConstruct DOM) ───
  // ── Action button selectors — populated from SEL.buttons (ADR-013) ──
  var BTN_SEL = SEL.buttons || {};

  // ── Detected buttons cache (populated each getAvailableActions call) ──
  var _detectedBtns = {};

  // ── Native click: mousedown → mouseup → click (PokerBet Angular/Zone.js) ──
  function nativeClick(el) {
    if (!el) return false;
    var rect = el.getBoundingClientRect();
    var cx = rect.left + rect.width / 2;
    var cy = rect.top + rect.height / 2;
    var opts = {bubbles: true, cancelable: true, view: window, button: 0, clientX: cx, clientY: cy};
    el.dispatchEvent(new MouseEvent('mousedown', opts));
    el.dispatchEvent(new MouseEvent('mouseup', opts));
    el.dispatchEvent(new MouseEvent('click', opts));
    return true;
  }

  function buildCssPath(el) {
    if (!el) return '';
    var parts = [];
    var cur = el;
    while (cur && cur !== document.body && parts.length < 5) {
      var tag = cur.tagName.toLowerCase();
      if (cur.id) { parts.unshift('#' + cur.id); break; }
      var cls = '';
      if (cur.className && typeof cur.className === 'string') {
        var cc = cur.className.trim().split(/\s+/).filter(function(c) {
          return c && c.indexOf('ng-') !== 0 && c !== 'active' && c !== 'hover';
        }).slice(0, 4);
        if (cc.length) cls = '.' + cc.join('.');
      }
      parts.unshift(tag + cls);
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  }

  function detectSliderPresets() {
    var presetItems = document.querySelectorAll(
      'sg-poker-betting-slider .limits-buttons-v-p li, ' +
      'sg-poker-betting-slider li, .limits-buttons-v-p li, ' +
      '[class*="limit"] li'
    );
    for (var i = 0; i < presetItems.length; i++) {
      var el = presetItems[i];
      var elR = el.getBoundingClientRect(); if (elR.width === 0 && elR.height === 0) continue;
      var txt = (el.textContent || '').trim().toLowerCase();
      var pName = null;
      if (/\bmax\b|all[\s-]*in/i.test(txt)) pName = 'preset_max';
      else if (/\bmin\b/i.test(txt)) pName = 'preset_min';
      else if (/\bpot\b/i.test(txt) && !/half/i.test(txt) && !/1\/2/i.test(txt)) pName = 'preset_pot';
      else if (/half|1\/2/i.test(txt)) pName = 'preset_half';
      if (pName && !_detectedBtns[pName]) {
        var rect = el.getBoundingClientRect();
        _detectedBtns[pName] = {
          el: el, selector: buildCssPath(el),
          text: txt.substring(0, 30),
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2)
        };
      }
    }
  }

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
    if (url.indexOf('skillgames') !== -1 || /187\d{3,}/.test(url) || url.indexOf('live-poker') !== -1) {
      var idm = url.match(/(\d{4,})/);
      return 'pb_' + (idm ? idm[1] : 'sg');
    }
    if (document.querySelector(SEL.seatContainerAlt) || document.querySelector(SEL.seatContainer)) {
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

  // ── DOM Scanner — inventory what elements exist for remote debugging ──
  function domScan() {
    var scan = { url: location.href.substring(0, 120), inIframe: window !== window.top };
    // Check each BTN_SEL selector
    var selHits = {};
    for (var k in BTN_SEL) {
      var el = document.querySelector(BTN_SEL[k]);
      if (el) {
        var r = el.getBoundingClientRect();
        selHits[k] = { found: true, vis: r.width > 0 && r.height > 0, w: Math.round(r.width), h: Math.round(r.height), cls: el.className.substring(0, 60), text: (el.textContent || '').trim().substring(0, 20) };
      }
    }
    scan.btnSelHits = selHits;
    // All elements with "control" in class name
    var ctrls = document.querySelectorAll('[class*="control"]');
    var ctrlDump = [];
    for (var i = 0; i < Math.min(ctrls.length, 10); i++) {
      var ce = ctrls[i]; var cr = ce.getBoundingClientRect();
      ctrlDump.push({ cls: ce.className.substring(0, 60), tag: ce.tagName, text: (ce.textContent || '').trim().substring(0, 20), vis: cr.width > 0 && cr.height > 0 });
    }
    scan.controls = ctrlDump;
    scan.controlCount = ctrls.length;
    // All elements with "fold" "check" "call" "raise" "bet" in class name
    var actionEls = document.querySelectorAll('[class*="fold"], [class*="check"], [class*="call"], [class*="raise"], [class*="bet-"], [class*="action"]');
    var actDump = [];
    for (var j = 0; j < Math.min(actionEls.length, 15); j++) {
      var ae = actionEls[j]; var ar = ae.getBoundingClientRect();
      actDump.push({ cls: ae.className.substring(0, 80), tag: ae.tagName, text: (ae.textContent || '').trim().substring(0, 30), vis: ar.width > 0 && ar.height > 0 });
    }
    scan.actionElements = actDump;
    scan.actionCount = actionEls.length;
    // All buttons on the page
    var allBtns = document.querySelectorAll('button');
    var btnDump = [];
    for (var b = 0; b < Math.min(allBtns.length, 10); b++) {
      var be = allBtns[b]; var br2 = be.getBoundingClientRect();
      btnDump.push({ cls: be.className.substring(0, 60), text: (be.textContent || '').trim().substring(0, 30), vis: br2.width > 0 && br2.height > 0 });
    }
    scan.buttons = btnDump;
    scan.buttonCount = allBtns.length;
    return scan;
  }

  // ── Available actions (hero only — visible buttons = hero's turn) ────
  // ── Action detection: layered, layout-agnostic ──────────────
  // v23-hardened: discovers actions across 4 layers, zero dependency on
  // a single CSS selector family. Survives GoldRush DOM changes.
  
  var ACTION_KEYWORDS = {
    fold:         /(^|\s|\.|-)fold($|\s|\.|-)/i,
    check:        /(^|\s|\.|-)check($|\s|\.|-)/i,
    call:         /(^|\s|\.|-)call($|\s|\.|-)/i,
    raise:        /(^|\s|\.|-)raise($|\s|\.|-)/i,
    bet:          /(^|\s|\.|-)bet($|\s|\.|-)/i,
    cashout:      /cash\s*out|\.cash_out/i,
    allin:        /all\s*in|\.all_in/i,
    show:         /(^|\s|\.|-)show($|\s|\.|-)/i,
    run_it_twice: /run\s*it\s*twice|\.run_it_twice/i,
    resume_hand:  /resume\s*hand|\.resume_hand/i,
    back_to_game: /back\s*to\s*game|\.back_to_game/i
  };

  var _actionDetectionMeta = {
    sourceCounts: { selector: 0, element: 0, text: 0, dataAttr: 0 },
    lastTick: 0
  };

  function _isVisible(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function _normalizeActionName(raw) {
    // Map discovered names to canonical action names
    var lower = (raw || '').trim().toLowerCase().replace(/\s+/g, '_');
    var map = {
      fold: 'fold', check: 'check', call: 'call', raise: 'raise', bet: 'bet',
      cash_out: 'cashout', cashout: 'cashout',
      all_in: 'allin', allin: 'allin',
      show: 'show',
      run_it_twice: 'run_it_twice',
      resume_hand: 'resume_hand',
      back_to_game: 'back_to_game'
    };
    return map[lower] || null;
  }

  function _matchActionText(text) {
    if (!text) return null;
    var clean = text.trim();
    // Quick exact matches first
    var direct = _normalizeActionName(clean);
    if (direct) return direct;
    // Regex matches
    for (var name in ACTION_KEYWORDS) {
      if (ACTION_KEYWORDS[name].test(clean)) return name;
    }
    return null;
  }

  function getAvailableActions() {
    var heroSeat = document.querySelector(SEL.heroSeat) || document.querySelector(SEL.heroSeatAlt);
    if (!heroSeat) { _detectedBtns = {}; return []; }
    _detectedBtns = {};
    var avail = [];
    var seenActions = {};
    var meta = { selector: 0, element: 0, text: 0, dataAttr: 0 };

    function _addAction(name, el, selector, source) {
      if (seenActions[name]) return;
      seenActions[name] = true;
      avail.push(name);
      meta[source] = (meta[source] || 0) + 1;
      _detectedBtns[name] = {
        el: el, selector: selector,
        text: (el.textContent || '').trim().substring(0, 30),
        source: source,
        x: Math.round(el.getBoundingClientRect().x + el.getBoundingClientRect().width / 2),
        y: Math.round(el.getBoundingClientRect().y + el.getBoundingClientRect().height / 2)
      };
    }

    // ── Layer 1: Known BTN_SEL selectors (backwards compat) ──
    for (var name in BTN_SEL) {
      var btn = document.querySelector(BTN_SEL[name]);
      if (_isVisible(btn)) {
        _addAction(name, btn, BTN_SEL[name], 'selector');
      }
    }

    // Also detect slider presets
    detectSliderPresets();

    // ── Layer 2: visible <button> and [role="button"] elements ──
    var btnElements = document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]');
    for (var bi = 0; bi < btnElements.length; bi++) {
      var bel = btnElements[bi];
      if (!_isVisible(bel)) continue;
      var btext = (bel.innerText || bel.value || '').trim();
      if (!btext) continue;
      var baction = _matchActionText(btext);
      if (baction && !seenActions[baction]) {
        _addAction(baction, bel, buildCssPath(bel), 'element');
      }
    }

    // ── Layer 3: visible elements with action text ──
    if (avail.length === 0) {
      var textCandidates = document.querySelectorAll('div, span, a, p, li, .btn, [class*="btn"], [class*="action"], [class*="control"]');
      for (var ti = 0; ti < textCandidates.length; ti++) {
        var tel = textCandidates[ti];
        if (!_isVisible(tel)) continue;
        var ttext = (tel.innerText || tel.textContent || '').trim();
        if (!ttext || ttext.length > 50) continue;
        var taction = _matchActionText(ttext);
        if (taction && !seenActions[taction]) {
          _addAction(taction, tel, buildCssPath(tel), 'text');
        }
      }
    }

    // ── Layer 4: [data-action] attributes ──
    var daElements = document.querySelectorAll('[data-action]');
    for (var di = 0; di < daElements.length; di++) {
      var del = daElements[di];
      if (!_isVisible(del)) continue;
      var dname = _normalizeActionName(del.getAttribute('data-action'));
      if (dname && !seenActions[dname]) {
        _addAction(dname, del, '[data-action="' + del.getAttribute('data-action') + '"]', 'dataAttr');
      }
    }

    // ── Diagnostics (compact, every 10 ticks) ──
    if (_n % 50 === 1 && avail.length > 0) {
      var srcs = [];
      for (var ak in _detectedBtns) {
        srcs.push(ak + '=' + _detectedBtns[ak].source);
      }
      console.log('[W4P] actions=' + avail.length + ' [' + avail.join(',') + ']');
    }

    // Update global meta
    _actionDetectionMeta = {
      sourceCounts: meta,
      lastTick: _n,
      actions: avail.slice()
    };

    return avail;
  }

  // ── ACTION AUDIT: window.__W4P_ACTION_AUDIT() ──────────────
  window.__W4P_ACTION_AUDIT = function() {
    var hero = document.querySelector(SEL.heroClass) || document.querySelector(SEL.heroSeatAlt);
    var heroName = hero ? ((hero.querySelector(SEL.playerName) || hero.querySelector(SEL.playerNameAlt) || {}).innerText || '').trim() : null;
    
    console.log('═══ W4P ACTION AUDIT ═══');
    console.log('heroName:', heroName || 'NONE');
    console.log('heroSeat:', !!hero, hero ? hero.className : '');
    console.log('tick:', _n, 'mode:', _mode);
    console.log('detected actions:', _actionDetectionMeta.actions || []);
    console.log('detection sources:', JSON.stringify(_actionDetectionMeta.sourceCounts));
    console.log('last detection tick:', _actionDetectionMeta.lastTick);
    
    // Full BTN_SEL sweep
    console.log('--- BTN_SEL scan ---');
    for (var name in BTN_SEL) {
      var el = document.querySelector(BTN_SEL[name]);
      console.log('  ' + name + ': ' + BTN_SEL[name] + ' found=' + !!el + ' visible=' + _isVisible(el));
    }
    
    // Visible buttons
    console.log('--- Visible buttons ---');
    var vb = document.querySelectorAll('button, [role="button"]');
    for (var vbi = 0; vbi < vb.length; vbi++) {
      if (_isVisible(vb[vbi])) {
        console.log('  ' + vb[vbi].tagName + ' ' + vb[vbi].className + ' text="' + (vb[vbi].innerText || '').trim().slice(0, 40) + '"');
      }
    }
    
    // All .control-b-view-p elements
    console.log('--- .control-b-view-p ---');
    var cb = document.querySelectorAll('.control-b-view-p');
    console.log('  count:', cb.length);
    for (var cbi = 0; cbi < cb.length; cbi++) {
      console.log('  ' + cb[cbi].className + ' text="' + (cb[cbi].innerText || '').trim().slice(0, 30) + '" visible=' + _isVisible(cb[cbi]));
    }
    
    return {
      heroName: heroName,
      heroSeat: !!hero,
      tick: _n,
      mode: _mode,
      actions: _actionDetectionMeta.actions,
      sources: _actionDetectionMeta.sourceCounts
    };
  };


  // ── Button detection (exact selectors + state for remote) ───
  function detectButtons() {
    var result = { actions: [], presets: [], slider: null };

    // ── FULL SELECTOR VALIDATION (runs every tick) ──
    // Context check: are we in the right document?
    if (_n <= 3 || _n % 30 === 0) {
      var _iframes = document.querySelectorAll('iframe');
      var _iframeInfo = [];
      for (var fi = 0; fi < _iframes.length; fi++) {
        var _if = _iframes[fi];
        _iframeInfo.push({src: (_if.src||'').substring(0, 80), id: _if.id||'', vis: _if.offsetWidth > 0});
      }
      console.log('[W4P][CTX] url=' + location.href.substring(0, 100) +
        ' | doc.title=' + document.title.substring(0, 40) +
        ' | inIframe=' + (window !== window.top) +
        ' | iframes=' + _iframes.length + (_iframeInfo.length > 0 ? ' ' + JSON.stringify(_iframeInfo) : ''));
    }
    var heroSeat = document.querySelector(SEL.heroSeat) || document.querySelector(SEL.heroSeatAlt);
    // heroActive = self-player exists AND visible action buttons present (no .active class needed)
    var _heroActive = false;
    if (heroSeat) {
      var _visSels = ['.control-b-view-p.fold-c', '.control-b-view-p.check-c', '.control-b-view-p.call-c', '.control-b-view-p.raise-c', '.control-b-view-p.bet-c'];
      for (var _vi = 0; _vi < _visSels.length; _vi++) {
        var _vel = document.querySelector(_visSels[_vi]);
        if (_vel) { var _vr = _vel.getBoundingClientRect(); if (_vr.width > 0 && _vr.height > 0) { _heroActive = true; break; } }
      }
    }

    // Build full validation report — ALWAYS, regardless of turn state
    var _validation = [];
    for (var vname in BTN_SEL) {
      var vel = document.querySelector(BTN_SEL[vname]);
      var vr = vel ? vel.getBoundingClientRect() : null;
      _validation.push({
        name: vname,
        sel: BTN_SEL[vname],
        found: !!vel,
        visible: !!vel && vr && vr.width > 0 && vr.height > 0,
        text: vel ? (vel.innerText || '').trim().substring(0, 30) : null,
        className: vel ? vel.className : null,
        disabled: vel ? (vel.disabled || vel.classList.contains('disabled')) : false,
        rect: vr ? {x:Math.round(vr.x),y:Math.round(vr.y),w:Math.round(vr.width),h:Math.round(vr.height)} : null
      });
    }
    // Also count all .control-b-view-p elements (raw DOM truth)
    var _allCtrl = document.querySelectorAll('.control-b-view-p');
    var _ctrlDump = [];
    for (var cci = 0; cci < Math.min(_allCtrl.length, 12); cci++) {
      var _ce = _allCtrl[cci];
      var _cr = _ce.getBoundingClientRect();
      _ctrlDump.push({
        cls: _ce.className,
        text: (_ce.innerText||'').trim().substring(0, 20),
        vis: _cr.width > 0 && _cr.height > 0,
        disabled: _ce.disabled || _ce.classList.contains('disabled')
      });
    }

    // Summary every 50 ticks only (reduces console noise)
    if (_n % 50 === 1) {
      var _foundNames = _validation.filter(function(v){return v.found;}).map(function(v){return v.name+(v.visible?'[V]':'[H]')+(v.disabled?'[D]':'');});
      console.log('[W4P] tick=' + _n + ' hero=' + (heroSeat?'Y':'N') + ' active=' + _heroActive +
        ' | ' + (_foundNames.length > 0 ? _foundNames.join(',') : 'NONE'));
    }

    // Store on window for console inspection: _w4p_lastValidation
    window._w4p_lastValidation = {
      tick: _n, heroSeat: !!heroSeat, heroActive: _heroActive,
      selectors: _validation, rawControls: _ctrlDump
    };

    // No gate on .active — if hero seated but no visible buttons, actions will just be empty

    // 1. Known action buttons — scan BTN_SEL for visible ones
    for (var name in BTN_SEL) {
      if (name === 'allin') continue;
      var el = document.querySelector(BTN_SEL[name]);
      var elr = el ? el.getBoundingClientRect() : null;
      if (el && elr && elr.width > 0 && elr.height > 0) {
        var text = (el.innerText || el.textContent || '').trim();
        var amtMatch = text.match(/([\d,]+\.?\d*)/);
        result.actions.push({
          action: name,
          text: text,
          amount: amtMatch ? parseFloat(amtMatch[1].replace(/,/g, '')) : null,
          selector: BTN_SEL[name]
        });
      }
    }
    // Check native all-in button separately
    var allinEl = document.querySelector(BTN_SEL.allin);
    var allinR = allinEl ? allinEl.getBoundingClientRect() : null;
    if (allinEl && allinR && allinR.width > 0 && allinR.height > 0) {
      var allinText = (allinEl.innerText || allinEl.textContent || '').trim();
      var allinAmt = allinText.match(/([\d,]+\.?\d*)/);
      result.actions.push({
        action: 'allin',
        text: allinText,
        amount: allinAmt ? parseFloat(allinAmt[1].replace(/,/g, '')) : null,
        selector: BTN_SEL.allin
      });
    }

    // 2. Presets (min/half/pot/max) from slider panel
    var PRPAT = { min: /\bmin\b/i, half: /\bhalf\b|1\/2/i, pot: /\bpot\b/i, max: /\bmax\b|all[\s-]?in/i };
    var presetEls = document.querySelectorAll(
      'sg-poker-betting-slider li, .limits-buttons-v-p li, [class*="limit"] li, [class*="preset"] li');
    for (var p = 0; p < presetEls.length; p++) {
      var pel = presetEls[p];
      if (pel.offsetParent === null && pel.offsetWidth === 0) continue;
      var ptext = (pel.innerText || pel.textContent || '').trim();
      if (!ptext) continue;
      var label = 'custom';
      for (var pk in PRPAT) {
        if (PRPAT[pk].test(ptext)) { label = pk; break; }
      }
      var pamtMatch = ptext.match(/([\d,]+\.?\d*)/);
      result.presets.push({
        label: label, text: ptext,
        amount: pamtMatch ? parseFloat(pamtMatch[1].replace(/,/g, '')) : null,
        index: p
      });
    }

    // 3. Slider state (range + text/number input)
    var rangeEl = document.querySelector('sg-poker-betting-slider input[type="range"]') || document.querySelector('input[type="range"]');
    var amtEl = document.querySelector('sg-poker-betting-slider input[type="number"]') || document.querySelector('sg-poker-betting-slider input[type="text"]');
    if (!amtEl) {
      var ins = document.querySelectorAll('input[type="number"], input[type="text"]');
      for (var ii = 0; ii < ins.length; ii++) {
        if ((ins[ii].offsetParent !== null || ins[ii].offsetWidth > 0) && !ins[ii].closest('sg-buy-in-modal')) {
          amtEl = ins[ii]; break;
        }
      }
    }
    if (rangeEl || amtEl) {
      result.slider = {
        visible: (rangeEl && rangeEl.offsetParent !== null) || (amtEl && amtEl.offsetParent !== null),
        current: amtEl ? parseFloat(amtEl.value) || 0 : (rangeEl ? parseFloat(rangeEl.value) || 0 : 0),
        min: rangeEl ? parseFloat(rangeEl.min) || 0 : null,
        max: rangeEl ? parseFloat(rangeEl.max) || 0 : null,
        step: rangeEl ? parseFloat(rangeEl.step) || 1 : null
      };
    }

    // ── DIAGNOSTIC: log every 50 ticks only ──
    if (result.actions.length > 0 && _n % 50 === 1) {
      console.log('[W4P] buttons: ' + result.actions.map(function(a) { return a.action; }).join(','));
    }

    // Pipe diagnostics through API (can't see Chrome console remotely)
    // Only send full scan periodically to keep payload small
    if (_n <= 5 || _n % 30 === 0) {
      result._dom_scan = domScan();
    }
    result._debug = {
      tick: _n,
      heroSeat: !!heroSeat,
      heroActive: _heroActive,
      selectorHits: _foundNames,
      rawControlCount: _allCtrl.length,
      url: location.href.substring(0, 120),
      v: 'v21'
    };

    _lastButtons = result;
    return result;
  }

  // ── Table readiness check — all seat containers present with position classes ──
  function isTableReady() {
    var containers = document.querySelectorAll(SEL.seatContainer);
    if (!containers.length) containers = document.querySelectorAll(SEL.seatContainerAlt);
    if (!containers.length) {
      if (_tableReadyState) {
        console.log('[W4P][SEAT] table readiness lost — ' + _lastContainerCount + '→0 containers');
      }
      _tableReadyState = false;
      _lastContainerCount = 0;
      return false;
    }
    var count = containers.length;
    if (count !== _lastContainerCount) {
      // Container count changed — table not stable yet
      console.log('[W4P][SEAT] container count changed: ' + _lastContainerCount + '→' + count + ' — waiting for stability');
      _lastContainerCount = count;
      _tableReadyState = false;
      return false;
    }
    // All containers must have position-N class
    for (var i = 0; i < containers.length; i++) {
      if (!containers[i].className.match(/position-(\d+)/)) {
        if (_tableReadyState) {
          console.log('[W4P][SEAT] position class missing on container ' + i + ' — freezing');
        }
        _tableReadyState = false;
        return false;
      }
    }
    if (!_tableReadyState) {
      console.log('[W4P][SEAT] table ready — ' + count + ' containers with position classes');
    }
    _tableReadyState = true;
    return true;
  }

  // ── Resolve stable seat index for a player ───────────────────
  // Rules:
  //   1. Known player with cached position → use cached position
  //   2. Known player with NEW position from DOM → debounce (DEBOUNCE_COUNT polls)
  //   3. New player with DOM position → debounce
  //   4. Player/missing position → skip (do NOT invent a seat index)
  //   5. Collision: two players at same seat → reject new, keep previous
  // Returns { seat_index: N, isNew: bool, reason: str }
  function resolveSeatIndex(name, rawPosition, containerEl, swapMap) {
    var now = Date.now();
    var result = { seat_index: null, isNew: false, confidence: 0, reason: '' };

    // No name — anonymous seat, return raw position if available
    if (!name) {
      if (rawPosition !== null) {
        result.seat_index = rawPosition;
        result.reason = 'anonymous-seat';
        result.confidence = 100;
      } else {
        result.reason = 'anonymous-no-position';
      }
      return result;
    }

    // Named player — use seat cache
    _seatLastSeen[name] = now;

    if (_seatCache.hasOwnProperty(name)) {
      var cachedPos = _seatCache[name];

      // If we have a fresh DOM position that differs from cache
      if (rawPosition !== null && rawPosition !== cachedPos) {
        // ── Atomic swap bypass: accept immediately, no debounce ──
        if (swapMap && swapMap.hasOwnProperty(name) && swapMap[name] === rawPosition) {
          // Both sides of swap are accepted atomically — skip collision check
          // (the swap pre-scan already verified the 2-player constraint)
          console.log('[W4P][SEAT][SWAP] ' + name + ': ' + cachedPos + '→' + rawPosition + ' atomic');
          delete _seatCache[name];
          _seatCache[name] = rawPosition;
          delete _pendingCandidates[name];
          result.seat_index = rawPosition;
          result.reason = 'swap-atomically-accepted';
          result.confidence = 100;
          return result;
        }

        // Debounce: require DEBOUNCE_COUNT consecutive polls
        var pc = _pendingCandidates[name];
        if (!pc || pc.seat_index !== rawPosition) {
          // New candidate or different candidate — reset counter
          _pendingCandidates[name] = { seat_index: rawPosition, count: 1, since: now };
          result.seat_index = cachedPos;  // keep old position during debounce
          result.reason = 'pending-new-position';
          result.confidence = 80;
          return result;
        }
        pc.count++;
        if (pc.count >= DEBOUNCE_COUNT) {
          // Candidate confirmed — check for collision
          var existing = null;
          for (var otherName in _seatCache) {
            if (otherName !== name && _seatCache[otherName] === rawPosition) {
              existing = otherName;
              break;
            }
          }
          if (existing) {
            // Collision: DON'T move — keep cached position
            _collisionsThisPoll.push({
              seat: rawPosition,
              player1: existing,
              player2: name,
              action: 'rejected-new-comer',
              reason: 'seat ' + rawPosition + ' occupied by ' + existing
            });
            delete _pendingCandidates[name];
            result.seat_index = cachedPos;
            result.reason = 'collision-rejected';
            result.confidence = 90;
            return result;
          }
          // Accept the move
          console.log('[W4P][SEAT] ' + name + ' moved: ' + cachedPos + '→' + rawPosition + ' (debounced ' + pc.count + ' polls)');
          delete _seatCache[name];
          _seatCache[name] = rawPosition;
          delete _pendingCandidates[name];
          result.seat_index = rawPosition;
          result.isNew = false;  // known player, new position
          result.reason = 'move-confirmed';
          result.confidence = 100;
          return result;
        }
        // Still debouncing
        result.seat_index = cachedPos;
        result.reason = 'debouncing(' + pc.count + '/' + DEBOUNCE_COUNT + ')';
        result.confidence = 85;
        return result;
      }

      // No position or same position — keep cached
      if (rawPosition !== null) {
        // Same position confirmed — reset any pending
        delete _pendingCandidates[name];
      }
      result.seat_index = cachedPos;
      result.reason = 'cached';
      result.confidence = 100;
      return result;
    }

    // New player (not in cache yet)
    if (rawPosition !== null) {
      // Check collision with existing cached player
      var occupant = null;
      for (var on in _seatCache) {
        if (_seatCache[on] === rawPosition) {
          occupant = on;
          break;
        }
      }
      if (occupant) {
        // Collision with an established player — debounce the new one
        var pc2 = _pendingCandidates[name];
        if (!pc2 || pc2.seat_index !== rawPosition) {
          _pendingCandidates[name] = { seat_index: rawPosition, count: 1, since: now };
          _collisionsThisPoll.push({
            seat: rawPosition,
            player1: occupant,
            player2: name,
            action: 'new-player-collision-debouncing',
            reason: 'seat ' + rawPosition + ' occupied by ' + occupant
          });
          result.reason = 'new-player-collision';
          return result;
        }
        // Keep debouncing — don't override the established player
        pc2.count++;
        result.reason = 'new-player-pending(' + pc2.count + '/' + DEBOUNCE_COUNT + ')';
        return result;
      }

      // No collision — debounce the new assignment
      var pc3 = _pendingCandidates[name];

      // ── Bootstrap bypass: accept immediately before first snapshot ──
      if (!_bootstrapped) {
        // First table load — every player is new. Accept rawPosition immediately.
        _seatCache[name] = rawPosition;
        delete _pendingCandidates[name];
        result.seat_index = rawPosition;
        result.isNew = true;
        result.reason = 'bootstrap-immediate';
        result.confidence = 100;
        return result;
      }

      if (!pc3 || pc3.seat_index !== rawPosition) {
        _pendingCandidates[name] = { seat_index: rawPosition, count: 1, since: now };
        result.reason = 'new-player-pending(1/' + DEBOUNCE_COUNT + ')';
        return result;
      }
      pc3.count++;
      if (pc3.count >= DEBOUNCE_COUNT) {
        // Confirm — add to cache
        _seatCache[name] = rawPosition;
        delete _pendingCandidates[name];
        console.log('[W4P][SEAT] new player: ' + name + '→' + rawPosition + ' (debounced ' + pc3.count + ' polls)');
        result.seat_index = rawPosition;
        result.isNew = true;
        result.reason = 'new-player-confirmed';
        result.confidence = 100;
        return result;
      }
      result.reason = 'new-player-pending(' + pc3.count + '/' + DEBOUNCE_COUNT + ')';
      return result;
    }

    // New player with no DOM position — skip
    result.reason = 'new-player-no-position';
    return result;
  }

  // ── Build full snapshot — ALL seats ──────────────────────────
  function buildSnapshot() {
    if (stopNonPokerScrapeContext('buildSnapshot')) return null;

    var tableId = getTableId();
    if (!tableId) {
      if (_n <= 5 || _n % 30 === 0) {
        console.log('[W4P] no tableId');
        logFrameDiagnostics('no_table_id');
      }
      return null;
    }

    // ── Table readiness check ──────────────────────────────────
    isTableReady();
    var containers = document.querySelectorAll(SEL.seatContainer);
    if (!containers.length) containers = document.querySelectorAll(SEL.seatContainerAlt);

    if (!containers.length) {
      // No containers at all — preserve last good snapshot if available
      if (_lastGoodSnapshot) {
        console.log('[W4P][SEAT] no containers — returning preserved snapshot');
        _lastGoodSnapshot.ts = new Date().toISOString();
        return _lastGoodSnapshot;
      }
      if (_n <= 5 || _n % 30 === 0) {
        console.log('[W4P] no seat containers');
        logFrameDiagnostics('no_seat_containers');
      }
      return null;
    }

    // Dealer position
    var dealerEl = document.querySelector(SEL.dealerIcon);
    var dMatch = dealerEl ? dealerEl.className.match(/position-(\d+)/) : null;
    var dealerSeat = dMatch ? parseInt(dMatch[1]) : null;

    // Pot amount
    var potEl = document.querySelector(SEL.potContainer) || document.querySelector(SEL.potAlt) || document.querySelector(SEL.potAlt2);
    var potText = potEl ? (potEl.innerText || potEl.textContent || '') : '';
    var pMatch = potText.match(/([\d.,]+)/);
    var potZar = pMatch ? parseFloat(pMatch[1].replace(',', '')) : 0;

    // Board cards (community cards only)
    var boardCards = [];
    var boardEl = document.querySelector(SEL.boardContainer);
    if (boardEl) {
      var bcEls = boardEl.querySelectorAll(SEL.boardCard);
      for (var i = 0; i < bcEls.length; i++) {
        if (bcEls[i].closest(SEL.seatContainer) || bcEls[i].closest(SEL.seatContainerAlt)) continue;
        var c = parseCard(bcEls[i].className);
        if (c) boardCards.push(c);
      }
    }
    // Fallback ONLY if sg-poker-board doesn't exist (DOM structure changed)
    // Never fallback when boardEl exists — preflop legitimately has 0 cards
    if (!boardEl) {
      var allCardEls = document.querySelectorAll(SEL.boardCard);
      boardCards = [];
      for (var i = 0; i < allCardEls.length; i++) {
        if (allCardEls[i].closest(SEL.seatContainerAlt) || allCardEls[i].closest(SEL.seatContainer)) continue;
        var c2 = parseCard(allCardEls[i].className);
        if (c2) boardCards.push(c2);
      }
    }

    var street = 'PREFLOP';
    if (boardCards.length >= 5) street = 'RIVER';
    else if (boardCards.length >= 4) street = 'TURN';
    else if (boardCards.length >= 3) street = 'FLOP';

    var buttons = detectButtons();
    var avail = buttons.actions.map(function(a) { return a.action; });

    // ── Detect active seat (whose turn to act) from PokerBet DOM ──
    // self-player with visible action buttons = hero's turn (primary signal)
    // .active class is checked as secondary hint only
    var activePlayerName = null;
    for (var ai = 0; ai < containers.length; ai++) {
      var act = containers[ai];
      var isActSelf = act.classList.contains('self-player');
      var hasActClass = act.classList.contains('active') || !!act.querySelector(SEL.activeTurn);
      if (hasActClass || (isActSelf && avail.length > 0)) {
        var anEl = act.querySelector(SEL.playerName) || act.querySelector(SEL.playerNameAlt);
        activePlayerName = anEl ? (anEl.innerText || anEl.textContent || '').trim() : null;
        if (!activePlayerName) activePlayerName = null;
        break;
      }
    }

    // ── Scrape ALL seats (stability-aware) ──────────────────────
    _collisionsThisPoll = [];
    var seats = [];
    var heroName = null;
    var assignedPositions = {};  // position → name for collision detection within this poll

    // ── Pre-scan: detect Alice⇄Bob seat swaps ──────────────────
    // Collect all (name, DOM position) pairs where both are cached
    // and the DOM position differs from cache.
    var candidateMoves = {};  // name → { from: cachedPos, to: rawPosition }
    for (var pi = 0; pi < containers.length; pi++) {
      var pct = containers[pi];
      var pname = (pct.querySelector(SEL.playerName) || pct.querySelector(SEL.playerNameAlt) || {}).innerText;
      pname = pname ? pname.trim() : null;
      if (!pname || !_seatCache.hasOwnProperty(pname)) continue;
      var pmatch = pct.className.match(/position-(\d+)/);
      var ppos = pmatch ? parseInt(pmatch[1]) : null;
      if (ppos === null) continue;
      var pcached = _seatCache[pname];
      if (ppos !== pcached) {
        candidateMoves[pname] = { from: pcached, to: ppos };
      }
    }
    // Detect exact 2-player swap: A→B and B→A, no other pending moves
    var _swapMap = {};  // name → new position (atomically accepted)
    var moveNames = Object.keys(candidateMoves);
    if (moveNames.length === 2) {
      var a = moveNames[0], b = moveNames[1];
      if (candidateMoves[a].to === candidateMoves[b].from &&
          candidateMoves[b].to === candidateMoves[a].from) {
        _swapMap[a] = candidateMoves[a].to;
        _swapMap[b] = candidateMoves[b].to;
        console.log('[W4P][SEAT][SWAP] detected: ' + a + ' ' + candidateMoves[a].from + '⇄' + candidateMoves[b].from + ' ' + b + ' — accepted atomically');
      }
    }

    for (var i = 0; i < containers.length; i++) {
      var ct = containers[i];
      var isHero = ct.classList.contains('self-player') || !!ct.querySelector(SEL.heroClass);

      // ── Raw DOM position — from position-N class ─────────────
      // ⛔ Normal (post-bootstrap): never fallback to i — relied on by collision rejection.
      //    Bootstrap: if container lacks position-N class, use loop index temporarily.
      //    The seat stability layer reassigns positions once the DOM stabilizes.
      var posMatch = ct.className.match(/position-(\\d+)/);
      var rawPosition = posMatch ? parseInt(posMatch[1]) : null;
      if (rawPosition === null && !_bootstrapped) rawPosition = i + 1;

      // Player name
      var nameEl = ct.querySelector(SEL.playerName) || ct.querySelector(SEL.playerNameAlt);
      var name = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : null;
      if (!name || name === '') name = null;

      // ── Resolve stable seat index ──────────────────────────
      var resolution = resolveSeatIndex(name, rawPosition, ct, _swapMap);
      var seatIdx = resolution.seat_index;

      // ── Capture hero name BEFORE seat stability check ─────────
      // ⛔ CRITICAL: hero identity must survive regardless of seat assignment status.
      // If the hero seat is debouncing, we still need heroName for the snapshot.
      // The seat itself may be skipped below, but heroName enables the snapshot.
      if (isHero && name) heroName = name;

      // Skip if no stable position can be determined
      if (seatIdx === null || seatIdx === undefined) continue;
      if (seatIdx < 1 || seatIdx > 9) continue;

      // Within-poll collision check: same position already assigned this poll
      if (name && assignedPositions.hasOwnProperty(seatIdx) && assignedPositions[seatIdx] !== name) {
        _collisionsThisPoll.push({
          seat: seatIdx,
          player1: assignedPositions[seatIdx],
          player2: name,
          action: 'within-poll-collision-skipped',
          reason: 'position ' + seatIdx + ' already assigned to ' + assignedPositions[seatIdx]
        });
        continue;  // skip — don't double-assign
      }
      if (name) {
        assignedPositions[seatIdx] = name;
      }

      // Stack
      var stackEl = ct.querySelector(SEL.stack) || ct.querySelector(SEL.stackAlt) || ct.querySelector(SEL.stackAlt2);
      var stackText = stackEl ? (stackEl.innerText || stackEl.textContent || '') : '';
      var sMatch = stackText.match(/([\d.,]+)/);
      var stackZar = sMatch ? parseFloat(sMatch[1].replace(',', '')) : 0;

      // Hole cards
      var holeCards = [];
      var cardsContainer = ct.querySelector(SEL.holeCardsContainer);
      var hcEls = (cardsContainer || ct).querySelectorAll('.single-cart-view-p');
      for (var j = 0; j < hcEls.length; j++) {
        var hc = parseCard(hcEls[j].className);
        if (hc) holeCards.push(hc);
      }

      // (heroName already captured above — before seat stability check)

      // Status detection
      var sittingOut = ct.classList.contains('seat-out-v') || !!ct.querySelector(SEL.sittingOut);
      var isFolded = ct.classList.contains('folded') || !!ct.querySelector('.folded');
      var isActive = isHero && avail.length > 0;

      var status = 'playing';
      if (sittingOut) status = 'sitting_out';
      else if (isFolded) status = 'folded';
      else if (holeCards.length === 0 && street !== 'PREFLOP') status = 'folded';

      seats.push({
        seat_index:        seatIdx,
        name:              name,
        stack_zar:         stackZar,
        hole_cards:        isHero ? holeCards : [],
        is_hero:           isHero,
        is_self_player:    isHero,
        is_dealer:         seatIdx === dealerSeat,
        status:            status,
        sitting_out:       sittingOut,
        is_active:         isActive,
        available_actions: isHero ? avail : [],
        bet:               getPlayerBet(seatIdx)
      });
    }

    // ── Prune stale cache entries ────────────────────────────────
    var staleCutoff = Date.now() - SEAT_STALE_MS;
    var staleNames = [];
    for (var cn in _seatCache) {
      if ((_seatLastSeen[cn] || 0) < staleCutoff) {
        staleNames.push(cn);
      }
    }
    for (var si = 0; si < staleNames.length; si++) {
      console.log('[W4P][SEAT] pruning stale: ' + staleNames[si] + ' (unseen >' + SEAT_STALE_MS + 'ms)');
      delete _seatCache[staleNames[si]];
      delete _seatLastSeen[staleNames[si]];
      delete _pendingCandidates[staleNames[si]];
    }

    // ── Must have found hero ─────────────────────────────────────
    if (!heroName) {
      if (_n <= 5 || _n % 30 === 0) {
        var seatClasses = [];
        for (var d = 0; d < containers.length; d++) {
          var dct = containers[d];
          var dname = dct.querySelector(SEL.playerName) || dct.querySelector(SEL.playerNameAlt);
          var dnameText = dname ? dname.textContent.trim() : 'EMPTY';
          seatClasses.push(dnameText + ':' + dct.className.replace(/\s+/g, '.'));
        }
        console.log('[W4P] no hero | ' + containers.length + ' seats | ' + seatClasses.join(' | '));
      }
      return null;
    }

    // Hero must have a seat assignment — wait until table is ready
    var heroFound = false;
    for (var hi = 0; hi < seats.length; hi++) {
      if (seats[hi].is_hero) { heroFound = true; break; }
    }
    if (!heroFound) {
      if (_n <= 5) {
        console.log('[W4P][SEAT] hero ' + heroName + ' has no seat assignment yet — waiting for table');
      }
      return null;
    }

    // ── Save as last good snapshot ──────────────────────────────
    var snap = {
      table_id:      tableId,
      bot_id:        heroName,
      session_id:    _sessionId,
      hand_id:       _handId,       // ADR-001: echoed from backend
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
      buttons:       buttons,
      available_actions: avail,
      active_player: activePlayerName,
      ts:            new Date().toISOString(),
      source_key:    'w4p_inject'
    };
    _lastGoodSnapshot = JSON.parse(JSON.stringify(snap));  // deep copy
    _bootstrapped = true;  // bootstrap complete — enable normal debounce from now on
    return snap;
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
      btn: snap.buttons ? snap.buttons.actions.map(function(a) { return a.action + ':' + (a.amount || ''); }).join(',') : '',
      b: snap.board, p: snap.pot_zar, str: snap.street, d: snap.dealer_seat,
      sc: snap.seats.length
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
      if (data.hand_id) {
        _handId = data.hand_id;
      }
    } else {
      console.log('[W4P] API error:', data.error);
    }
  }

  // ── Send hand data to collector (for engine textarea) ────────
  var _lastCollectorPayload = '';
  function sendToCollector(snap) {
    if (!snap || !snap.seats || snap.seats.length === 0) return;
    // Build collector text: hero hand + BOARD: tag
    var hero = null;
    for (var i = 0; i < snap.seats.length; i++) {
      if (snap.seats[i].is_hero && snap.seats[i].hole_cards && snap.seats[i].hole_cards.length > 0) {
        hero = snap.seats[i]; break;
      }
    }
    if (!hero) return;
    var lines = [hero.hole_cards.join('')];
    // Build board string
    var b = snap.board || {};
    var boardCards = [];
    if (Array.isArray(b.flop)) boardCards = boardCards.concat(b.flop);
    if (b.turn) boardCards.push(b.turn);
    if (b.river) boardCards.push(b.river);
    if (boardCards.length >= 3) lines.push('BOARD:' + boardCards.join(''));
    var payload = lines.join('\n');
    // Dedup: only send if changed
    if (payload === _lastCollectorPayload) return;
    _lastCollectorPayload = payload;
    bridgeFetchRaw('/collector/save', 'POST', { text: payload, source: 'w4p' });
  }

  // ── Send snapshot (via bridge → service worker) ──────────────
  function sendSnapshot(snap) {
    bridgeFetch('/snapshot', 'POST', snap, function(resp) {
      if (resp && resp.ok) handleSnapshotResponse(resp.data);
      else { var _ = resp; }
    });
  }

  // ── Set raise slider amount ──────────────────────────────────
  function setRaiseAmount(amount) {
    if (!amount || amount <= 0) return false;
    var slider = document.querySelector('sg-poker-betting-slider input[type="range"]');
    if (!slider) slider = document.querySelector('input[type="range"]');
    if (slider) {
      var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSet.call(slider, String(amount));
      slider.dispatchEvent(new Event('input', {bubbles: true}));
      slider.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
    var inputs = document.querySelectorAll('input[type="number"], input[type="text"]');
    for (var i = 0; i < inputs.length; i++) {
      var iR = inputs[i].getBoundingClientRect();
      if (iR.width > 0 && iR.height > 0 && !inputs[i].closest('sg-buy-in-modal')) {
        var nativeSet2 = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSet2.call(inputs[i], String(amount));
        inputs[i].dispatchEvent(new Event('input', {bubbles: true}));
        inputs[i].dispatchEvent(new Event('change', {bubbles: true}));
        return true;
      }
    }
    return false;
  }

  // ── Click a DOM button by selector ───────────────────────────
  function clickSel(sel) {
    var btn = document.querySelector(sel);
    var br = btn ? btn.getBoundingClientRect() : null;
    if (btn && br && br.width > 0 && br.height > 0) {
      nativeClick(btn);
      return true;
    }
    return false;
  }

  // ── v21: CONFIRMED POKERBET CONTROL MODEL ────────────────────
  // Presets (MAX/POT/MIN/%) select the size → BET/RAISE button text updates → click BET/RAISE executes.
  // BET/RAISE always EXECUTES. It is NOT a slider opener.
  // There is no input[type="range"]. The slider is a custom Angular component.
  // The authoritative amount is in the <i> tag inside the BET/RAISE button.

  // ── Find the BET or RAISE execute button ──
  function findExecuteButton() {
    function _vis(el) { if (!el) return false; var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
    var raiseBtn = document.querySelector(BTN_SEL.raise);
    if (_vis(raiseBtn)) return { el: raiseBtn, type: 'raise', sel: BTN_SEL.raise };
    var betBtn = document.querySelector(BTN_SEL.bet);
    if (_vis(betBtn)) return { el: betBtn, type: 'bet', sel: BTN_SEL.bet };
    return null;
  }

  // ── Read amount from BET/RAISE button's <i> tag ──
  function readButtonAmount(btnEl) {
    if (!btnEl) return null;
    var iTag = btnEl.querySelector('i');
    if (!iTag) return null;
    var text = (iTag.textContent || '').replace(/[^\d.]/g, '');
    var val = parseFloat(text);
    return isNaN(val) ? null : val;
  }

  // ── Find preset <li> elements ──
  function findPresets() {
    return document.querySelectorAll(
      'sg-poker-betting-slider .limits-buttons-v-p li, sg-poker-betting-slider li, ' +
      '.limits-buttons-v-p li, [class*="limit"] li, [class*="preset"] li');
  }

  // ── Click a preset element with full event propagation ──
  function clickPreset(presetEl) {
    // Click the <li> itself
    nativeClick(presetEl);
    // Also click all children — Angular may bind on inner <span>, <a>, etc.
    var kids = presetEl.querySelectorAll('*');
    for (var i = 0; i < kids.length; i++) nativeClick(kids[i]);
  }

  // ── CORE: Click preset → wait for amount change → execute BET/RAISE ──
  // This is the ONLY way to size and execute a raise/bet in PokerBet.
  // Hard rule: never execute unless the <i> amount changed or was already correct.
  function presetThenExecute(presetRegex, actionName) {
    var execBtn = findExecuteButton();
    if (!execBtn) {
      console.log('[W4P][MISS] ' + actionName + ': no BET/RAISE button visible — REFUSED');
      return;
    }

    var amountBefore = readButtonAmount(execBtn.el);
    console.log('[W4P][' + actionName + '] button=' + execBtn.type + ' amount_before=' + amountBefore);

    // Find and click the matching preset
    var presets = findPresets();
    var clicked = false;
    var clickedText = '';
    console.log('[W4P][' + actionName + '] scanning ' + presets.length + ' presets for /' + presetRegex.source + '/');

    for (var i = 0; i < presets.length; i++) {
      var txt = (presets[i].textContent || '').trim();
      if (presetRegex.test(txt)) {
        var pr = presets[i].getBoundingClientRect();
        if (pr.width > 0 && pr.height > 0) {
          clickPreset(presets[i]);
          clicked = true;
          clickedText = txt;
          console.log('[W4P][' + actionName + '] clicked preset: "' + txt + '"');
          break;
        }
      }
    }

    // Fallback for MAX: try last preset if regex didn't match
    if (!clicked && /max/i.test(presetRegex.source) && presets.length > 0) {
      var last = presets[presets.length - 1];
      var lr = last.getBoundingClientRect();
      if (lr.width > 0 && lr.height > 0) {
        clickPreset(last);
        clicked = true;
        clickedText = (last.textContent || '').trim();
        console.log('[W4P][' + actionName + '] clicked last preset (MAX fallback): "' + clickedText + '"');
      }
    }

    if (!clicked) {
      console.log('[W4P][MISS] ' + actionName + ': no matching preset found — REFUSED, no blind click');
      return;
    }

    // Wait for Angular to update the BET/RAISE button amount, then verify and execute
    var checkCount = 0;
    var maxChecks = 10;  // 10 x 100ms = 1 second max wait
    var verifyTimer = setInterval(function() {
      checkCount++;
      var btn = findExecuteButton();
      if (!btn) {
        clearInterval(verifyTimer);
        console.log('[W4P][' + actionName + '] ABORT: BET/RAISE disappeared during wait');
        return;
      }
      var amountAfter = readButtonAmount(btn.el);

      // Execute if amount changed OR if we've checked enough times (preset may set same amount)
      if (amountAfter !== amountBefore || checkCount >= maxChecks) {
        clearInterval(verifyTimer);
        var btnText = (btn.el.textContent || '').trim().substring(0, 40);
        if (amountAfter === amountBefore && checkCount >= maxChecks) {
          // Amount didn't change — preset click may have failed (isTrusted blocked)
          console.log('[W4P][REFUSE] ' + actionName + ': amount unchanged (' +
            amountBefore + ' → ' + amountAfter + '). Preset "' + clickedText + '" may have been blocked.');
          console.log('[W4P][REFUSE] ' + actionName + ': NOT executing — no blind click. Manual action required.');
          return;
        }
        console.log('[W4P][EXEC] ' + actionName + ': amount_before=' + amountBefore + ' amount_after=' + amountAfter +
          ' preset="' + clickedText + '" button="' + btnText + '" — EXECUTING');
        nativeClick(btn.el);
        return;
      }
    }, 100);
  }

  // v21: setSliderValue REMOVED — no input[type="range"] exists in PokerBet.
  // Size is set by clicking preset <li> elements. See presetThenExecute().

  // v21: selectMax/selectMin/selectPot/selectAmount/raiseAmount/executeAllin/confirmRaise ALL REMOVED.
  // All sizing now goes through presetThenExecute(). All execution through findExecuteButton() + nativeClick().

  // ── Click simple action button (fold/check/call/cashout — no sizing needed) ──
  function clickAction(action) {
    var key = action.toLowerCase().replace(/[\s-]/g, '_');
    var sel = BTN_SEL[key];
    if (!sel) { console.log('[W4P] Unknown action:', action); return false; }
    var btn = document.querySelector(sel);
    if (btn && (btn.offsetParent !== null || btn.offsetWidth > 0)) {
      nativeClick(btn);
      console.log('[W4P] Clicked:', action);
      return true;
    }
    console.log('[W4P] Button not visible:', action);
    return false;
  }

  // ── Buy-in handling (v15: faster timeouts) ───────────────────
  function handleBuyin(cmd) {
    var mode = (cmd.type || '').replace('buyin_', '').replace('rebuy_', '');
    // Try sg-buy-in-modal first (if already open)
    var modal = document.querySelector('sg-buy-in-modal');
    if (modal && modal.offsetParent !== null) {
      doBuyin(modal, mode, cmd.amount);
      return;
    }
    // Try clicking hero avatar to open buy-in
    var hero = document.querySelector(SEL.heroSeatAlt);
    if (hero) {
      nativeClick(hero);
      setTimeout(function() {
        var m = document.querySelector('sg-buy-in-modal');
        if (m) doBuyin(m, mode, cmd.amount);
        else console.log('[W4P] Buy-in modal did not appear');
      }, 400);
    } else {
      // Fallback: generic buy-in button search
      var buyBtns = document.querySelectorAll('button, [class*="buy"], [class*="rebuy"]');
      for (var i = 0; i < buyBtns.length; i++) {
        var txt = (buyBtns[i].textContent || '').trim().toLowerCase();
        if (/buy.?in|rebuy|top.?up/i.test(txt) && buyBtns[i].offsetParent !== null) {
          nativeClick(buyBtns[i]);
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
        nativeClick(maxBtn);
        console.log('[W4P] Buy-in MAX clicked');
      }
    } else if (mode === 'min') {
      var minBtn = modal.querySelector('.modal-balance-v li:nth-child(2) .mini-button-view-m:first-child button');
      if (minBtn && minBtn.offsetParent !== null) {
        nativeClick(minBtn);
        console.log('[W4P] Buy-in MIN clicked');
      }
    } else if (amount) {
      // Custom amount — set slider/input
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
    // Confirm
    setTimeout(function() {
      var submit = modal.querySelector('.modal-button-container button');
      if (submit && submit.offsetParent !== null) {
        nativeClick(submit);
        console.log('[W4P] Buy-in confirmed');
      }
    }, 300);
  }

  // ── v22-hardened: cooldown check — returns true if action is on cooldown ──
  function isOnCooldown(action, cooldownMs) {
    var now = Date.now();
    var last = _actionCooldowns[action] || 0;
    if (now - last < cooldownMs) {
      console.log('[W4P][GUARD] COOLDOWN: ' + action + ' blocked (' + (now - last) + 'ms < ' + cooldownMs + 'ms)');
      return true;
    }
    return false;
  }
  function markCooldown(action) {
    _actionCooldowns[action] = Date.now();
  }

  // ── Command handler ──────────────────────────────────────────
  function handleCommand(cmd) {
    var action = (cmd.type || cmd.command || '').toLowerCase();
    _cmdCount++;

    // ── v22-hardened: duplicate command guard ──
    if (cmd.id && cmd.id === _lastCmdId) {
      console.log('[W4P][GUARD] DUPLICATE cmd_id=' + cmd.id + ' action=' + action + ' — IGNORED');
      return;
    }
    if (cmd.id) _lastCmdId = cmd.id;

    console.log('[W4P][CMD-RECV] #' + _cmdCount + ' action=' + action + (cmd.amount ? ' amt=' + cmd.amount : '') + ' id=' + (cmd.id || 'none'));

    // ── Pre-actions & buy-in ──
    if (action === 'buyin' || action === 'rebuy_max' || action === 'rebuy_min' || action === 'buyin_max' || action === 'buyin_min') {
      handleBuyin(cmd); return;
    }
    if (action === 'cashout_preselect' || action === 'cashout_pre') { _cashoutPre = true; console.log('[W4P] CASHOUT preselected — hyper-polling .cash_out-c'); return; }
    if (action === 'cashout_clear' || action === 'clear_cashout') { _cashoutPre = false; console.log('[W4P] CASHOUT preselect cleared'); return; }
    if (action === 'check_fold') { _preAction = 'check_fold'; console.log('[W4P] Pre-action: CHECK/FOLD'); return; }
    if (action === 'check_call') { _preAction = 'check_call'; console.log('[W4P] Pre-action: CHECK/CALL'); return; }
    if (action === 'clear' || action === 'clear_preaction') { _preAction = null; console.log('[W4P] Pre-action cleared'); return; }

    // ── Pure native button clicks — mirror PokerBet exactly ──
    var DIRECT = {
      fold:          '.control-b-view-p.fold-c',
      check:         '.control-b-view-p.check-c',
      call:          '.control-b-view-p.call-c',
      cashout:       '.control-b-view-p.cash_out-c',
      show:          '.control-b-view-p.show-c',
      run_it_twice:  '.control-b-view-p.run_it_twice-c',
      resume_hand:   '.control-b-view-p.resume_hand-c',
      back_to_game:  '.control-b-view-p.back_to_game-c'
    };
    if (DIRECT[action]) {
      if (isOnCooldown(action, _ACTION_COOLDOWN_MS)) return;
      var btn = document.querySelector(DIRECT[action]);
      var btnR = btn ? btn.getBoundingClientRect() : null;
      if (btn && btnR && btnR.width > 0 && btnR.height > 0) {
        nativeClick(btn);
        markCooldown(action);
        console.log('[W4P][EXEC] ' + action + ' — clicked ' + DIRECT[action]);
      } else {
        console.log('[W4P][MISS] ' + action + ' — selector ' + DIRECT[action] + ' not visible');
      }
      return;
    }

    // ── v21 PRESET-BASED SIZING (click preset → wait for <i> update → execute) ──

    // PLO: no all-in action. Legacy allin → MAX preset
    if (action === 'allin' || action === 'all-in' || action === 'all_in') {
      if (isOnCooldown('preset', _PRESET_COOLDOWN_MS)) return;
      console.log('[W4P] PLO: allin remapped to MAX preset');
      markCooldown('preset');
      presetThenExecute(/\bmax\b/i, 'ALLIN→MAX');
      return;
    }

    // RAISE / BET — execute only if no custom amount requested, or displayed amount matches
    if (action === 'raise' || action === 'bet') {
      if (isOnCooldown(action, _ACTION_COOLDOWN_MS)) return;
      var execBtn = findExecuteButton();
      if (!execBtn) {
        console.log('[W4P][MISS] ' + action + ': no visible BET/RAISE button — REFUSED');
        return;
      }
      var displayed = readButtonAmount(execBtn.el);
      if (cmd.amount) {
        // Custom amount requested — only execute if displayed amount already matches
        var requested = parseFloat(cmd.amount);
        if (!isNaN(requested) && displayed !== null && Math.abs(displayed - requested) < 0.01) {
          console.log('[W4P][EXEC] ' + action + ': displayed=' + displayed + ' matches requested=' + requested + ' — EXECUTING');
          nativeClick(execBtn.el);
          markCooldown(action);
        } else {
          console.log('[W4P][REFUSE] ' + action + ': custom amount=' + cmd.amount + ' but displayed=' + displayed + '. BLOCKED — no blind click.');
        }
      } else {
        // No amount: execute at current displayed amount
        console.log('[W4P][EXEC] ' + action + ': executing ' + execBtn.type + ' at displayed amount=' + displayed);
        nativeClick(execBtn.el);
        markCooldown(action);
      }
      return;
    }

    // POT: click POT preset → wait → execute
    if (action === 'pot') { if (isOnCooldown('preset', _PRESET_COOLDOWN_MS)) return; markCooldown('preset'); presetThenExecute(/\bpot\b/i, 'POT'); return; }

    // MAX / RAISE_MAX: click MAX preset → wait → execute
    if (action === 'max' || action === 'raise_max') { if (isOnCooldown('preset', _PRESET_COOLDOWN_MS)) return; markCooldown('preset'); presetThenExecute(/\bmax\b/i, 'MAX'); return; }

    // MIN / RAISE_MIN: click MIN preset → wait → execute
    if (action === 'min' || action === 'raise_min') { if (isOnCooldown('preset', _PRESET_COOLDOWN_MS)) return; markCooldown('preset'); presetThenExecute(/\bmin\b/i, 'MIN'); return; }

    // HALF / 1/2 / 32%: click percentage preset → wait → execute
    if (action === 'half' || action === '1/2') { if (isOnCooldown('preset', _PRESET_COOLDOWN_MS)) return; markCooldown('preset'); presetThenExecute(/1\/2|half|32/i, 'HALF'); return; }

    // CLICK: direct selector click (used by remote with detected selectors)
    if (action === 'click' && cmd.selector) {
      var clickEl = document.querySelector(cmd.selector);
      var clickR = clickEl ? clickEl.getBoundingClientRect() : null;
      if (clickEl && clickR && clickR.width > 0 && clickR.height > 0) {
        nativeClick(clickEl);
        console.log('[W4P] Clicked selector:', cmd.selector);
      } else {
        console.log('[W4P] Selector not found/hidden:', cmd.selector);
      }
      return;
    }

    // CLOSE TABLE: click the close-tab icon in lobby header
    if (action === 'close_table') {
      var ct = document.querySelector('sg-poker-table-tab li.closed-tab-icon-p');
      if (ct) { ct.click(); console.log('[W4P] Clicked close_table'); }
      else { console.log('[W4P] close_table: li.closed-tab-icon-p not found'); }
      return;
    }

    // SIT OUT: click the sit-out toggle in more-actions
    if (action === 'sit_out') {
      var so = document.querySelector('sg-more-actions label:nth-of-type(2) span');
      if (so) { so.click(); console.log('[W4P] Clicked sit_out'); }
      else { console.log('[W4P] sit_out: selector not found'); }
      return;
    }

    // SIT_OUT: click sg-more-actions label[2] span (Sit Out Next Hand toggle)
    if (action === 'sit_out') {
      var xp = '/html/body/sg-app/div/sg-lobby/div/div/sg-poker-app/sg-poker-table/div/sg-more-actions/div/label[2]/span';
      var xr = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      var soEl = xr.singleNodeValue;
      if (soEl) { nativeClick(soEl); console.log('[W4P][EXEC] sit_out — clicked label[2]/span'); }
      else { console.log('[W4P][MISS] sit_out — xpath not found'); }
      return;
    }

    // CLICK_XPATH: generic xpath click
    if (action === 'click_xpath' && cmd.xpath) {
      var xr2 = document.evaluate(cmd.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      var xEl = xr2.singleNodeValue;
      if (xEl) { nativeClick(xEl); console.log('[W4P][EXEC] click_xpath:', cmd.xpath); }
      else { console.log('[W4P][MISS] click_xpath not found:', cmd.xpath); }
      return;
    }

    console.log('[W4P][REFUSE] unknown command: "' + action + '" — no handler, IGNORED');
  }

  // clickPresetAndConfirm — REMOVED in v21. Replaced by presetThenExecute().
  // Stub kept to prevent ReferenceError if anything still calls it.
  function clickPresetAndConfirm(presetRegex) {
    console.log('[W4P] WARNING: clickPresetAndConfirm() DEPRECATED — use presetThenExecute()');
    presetThenExecute(presetRegex, 'LEGACY');
  }

  function runPreAction(avail) {
    if (!_preAction) return;
    var executed = false;
    if (_preAction === 'check_fold') {
      if (avail.indexOf('check') !== -1) { clickAction('check'); executed = true; }
      else if (avail.indexOf('fold') !== -1) { clickAction('fold'); executed = true; }
    } else if (_preAction === 'check_call') {
      if (avail.indexOf('check') !== -1) { clickAction('check'); executed = true; }
      else if (avail.indexOf('call') !== -1) { clickAction('call'); executed = true; }
    }
    if (executed) {
      console.log('[W4P][EXEC] pre-action ' + _preAction + ' — executed, clearing');
    } else {
      console.log('[W4P][MISS] pre-action ' + _preAction + ' — no matching button in avail=[' + avail.join(',') + '], clearing anyway');
    }
    _preAction = null;
  }

  // ── Command polling loop ─────────────────────────────────────
  function pollCommands() {
    if (!_seatToken) {
      window._w4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 500);
      return;
    }

    bridgeFetch('/commands/pending?token=' + encodeURIComponent(_seatToken), 'GET', null, function(resp) {
      if (resp && resp.ok && resp.data && resp.data.ok && resp.data.command) {
        handleCommand(resp.data.command);
        // Acknowledge immediately
        bridgeFetch('/commands/ack', 'POST', { token: _seatToken, command_id: resp.data.command.id });
      }
    });

    window._w4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 500);
  }

  // ── Auto-untick "Wait for Big Blind" ─────────────────────────
  function untickWaitBB() {
    var cbs = document.querySelectorAll('input[type="checkbox"]');
    for (var i = 0; i < cbs.length; i++) {
      if (cbs[i].checked) {
        var label = cbs[i].parentElement ? cbs[i].parentElement.textContent : '';
        if (/wait.*big\s*blind|big\s*blind/i.test(label)) {
          nativeClick(cbs[i]);
          console.log('[W4P] Unticked: Wait for Big Blind');
        }
      }
    }
    var toggles = document.querySelectorAll('.check-box-view-p.active, .toggle-switch.active, [class*="wait-bb"].active');
    for (var j = 0; j < toggles.length; j++) {
      var txt = toggles[j].textContent || '';
      if (/wait.*big\s*blind|big\s*blind/i.test(txt)) {
        nativeClick(toggles[j]);
      }
    }
  }

  // ── Main snapshot loop ───────────────────────────────────────
  function tryCashout() {
    if (!_cashoutPre) return;
    var btn = document.querySelector('.control-b-view-p.cash_out-c');
    var coR = btn ? btn.getBoundingClientRect() : null;
    if (btn && coR && coR.width > 0 && coR.height > 0) {
      if (isOnCooldown('cashout', _ACTION_COOLDOWN_MS)) return;
      nativeClick(btn);
      markCooldown('cashout');
      _cashoutPre = false;
      console.log('[W4P][EXEC] CASHOUT via preselect — .cash_out-c clicked, _cashoutPre cleared');
    }
  }

  function tick() {
    _n++;

    // ── Registry gate: if selectors are invalid, do not parse ──
    if (!_registryValid) {
      if (_n === 1) {
        console.warn('[W4P] BLOCKED: Selector registry invalid for runtime=' + RUNTIME +
          '. Parser disabled. Waiting for registry to be populated.');
      }
      if (_n % 100 === 0) {
        console.log('[W4P] Still blocked — registry check #' + _n);
      }
      window._w4p_timer = setTimeout(tick, POLL_MS.NO_TABLE);
      return;
    }

    if (stopNonPokerScrapeContext('tick')) return;

    var snap = buildSnapshot();

    if (!snap) {
      _mode = 'NO_TABLE';
      window._w4p_timer = setTimeout(tick, POLL_MS.NO_TABLE);
      return;
    }

    // ── Seat stability diagnostics ──────────────────────────────
    var cacheSize = Object.keys(_seatCache).length;
    var pendingCount = Object.keys(_pendingCandidates).length;
    if (_collisionsThisPoll.length > 0) {
      console.log('[W4P][SEAT][COLLISION]', JSON.stringify(_collisionsThisPoll));
    }
    if (_n <= 5 || _n % 10 === 0) {
      console.log('[W4P][SEAT] poll=' + _n +
        ' ready=' + _tableReadyState +
        ' containers=' + snap.seats.length +
        ' cache=' + cacheSize +
        ' pending=' + pendingCount +
        ' collisions=' + _collisionsThisPoll.length +
        ' map=' + JSON.stringify(Object.keys(_seatCache).map(function(k) { return k + '→' + _seatCache[k]; })));
    }
    if (_n <= 5) {
      for (var si = 0; si < snap.seats.length; si++) {
        var ss = snap.seats[si];
        console.log('[W4P][SEAT]  seat ' + ss.seat_index + ': ' + (ss.name || 'EMPTY') +
          ' hero=' + ss.is_hero);
      }
    }

    // Adaptive polling mode
    var hero = null;
    for (var i = 0; i < snap.seats.length; i++) {
      if (snap.seats[i].is_hero) { hero = snap.seats[i]; break; }
    }
    var avail = hero ? hero.available_actions : [];

    // Track board transitions (for pre-action reset only)
    var boardLen = snap.board.flop.length + (snap.board.turn ? 1 : 0) + (snap.board.river ? 1 : 0);
    if (boardLen === 0 && _lastBoardLen > 0) {
      // New hand — clear pre-actions
      _preAction = null;
    }
    // Street transition: clear ALL pre-actions on any street change.
    // Pre-actions (C/F, C/C) are only valid for the current street.
    // Shuffle→Preflop→Flop→Turn→River each clear any prior pre-action.
    if (snap.street && _lastStreet && snap.street !== _lastStreet) {
      console.log('[W4P] Street changed ' + _lastStreet + '→' + snap.street + ' — clearing pre-action');
      _preAction = null;
    }
    _lastBoardLen = boardLen;
    _lastStreet = snap.street;

    // Try cashout BEFORE mode calculation (cashout button may appear at any time)
    tryCashout();

    if (avail.length > 0) _mode = 'HERO_TURN';
    else if (snap.street !== 'PREFLOP') _mode = 'HAND_ACTIVE';
    else _mode = 'IDLE';

    // Send every tick — no dedup, no heartbeat gate
    _lastSendTime = Date.now();
    sendSnapshot(snap);
    sendToCollector(snap);

    // Auto-execute pre-actions when hero's turn and actions available
    if (_preAction && avail.length > 0) {
      runPreAction(avail);
    }

    // Use faster polling when cashout preselected
    var pollMs = _cashoutPre ? CASHOUT_POLL_MS : (POLL_MS[_mode] || 1000);
    window._w4p_timer = setTimeout(tick, pollMs);
  }

  // ── Start ────────────────────────────────────────────────────
  untickWaitBB();
  window._w4p_bbTimer = setInterval(untickWaitBB, 5000);

  var _buildTag = 'v24-bootstrap+selectors';
  var _buildTs  = '2026-07-01T22:00:00Z';
  console.log('[W4P] ═══════════════════════════════════════════════');
  console.log('[W4P] ' + _buildTag + ' | built=' + _buildTs + ' | session=' + _sessionId);
  console.log('[W4P] guards: dup-cmd, cooldown=' + _ACTION_COOLDOWN_MS + 'ms, preset-cd=' + _PRESET_COOLDOWN_MS + 'ms');
  console.log('[W4P] polling: hero=' + POLL_MS.HERO_TURN + 'ms cmd=' + CMD_MS.HERO_TURN + 'ms cashout-hyper=' + CASHOUT_POLL_MS + 'ms');
  console.log('[W4P] API: ' + API_BASE + ' | registry=' + RUNTIME + '/' + (_registryValid ? 'valid' : 'BLOCKED') + ' | bridge=postMessage');
  console.log('[W4P] ═══════════════════════════════════════════════');
  tick();

  // ── Public API for debugging ─────────────────────────────────
  window._w4p_buildSnapshot = buildSnapshot;
  window._w4pClickAction = clickAction;
  window._w4pHandleCommand = handleCommand;
  // v21: selectMax/selectMin/selectPot removed — use presetThenExecute directly
  window._w4pPresetExecute = presetThenExecute;
  window._w4pReadButtonAmount = readButtonAmount;
  window._w4pFindExecuteButton = findExecuteButton;
  window._w4pActions = getAvailableActions;
  window._w4p_detectButtons = detectButtons;
  window._w4p_getDetectedBtns = function() { return _detectedBtns; };
  // STEP 3: Force extraction test — run in console: _w4p_forceActions()
  // This injects fake actions into the NEXT snapshot to prove API→UI chain
  window._w4p_forceActions = function() {
    var origDetect = detectButtons;
    detectButtons = function() {
      var r = origDetect();
      r.actions = [
        {action:'fold', text:'Fold', amount:null, selector:'.control-b-view-p.fold-c'},
        {action:'call', text:'Call 2.00', amount:2.00, selector:'.control-b-view-p.call-c'},
        {action:'raise', text:'Raise', amount:null, selector:'.control-b-view-p.raise-c'}
      ];
      console.log('[W4P][STEP3] FORCED actions: fold,call,raise');
      return r;
    };
    console.log('[W4P][STEP3] Force mode ON — next snapshots will have fold/call/raise');
  };
  window._w4p_injected = true;
  window._w4p_stop = function() {
    clearTimeout(window._w4p_timer);
    clearTimeout(window._w4p_cmdTimer);
    clearInterval(window._w4p_bbTimer);
    if (_cashoutTimer) clearInterval(_cashoutTimer);
    console.log('[W4P] stopped');
  };
})();

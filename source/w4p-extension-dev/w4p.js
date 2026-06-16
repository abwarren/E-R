// ── TEMPORARY DIAGNOSTIC BUILD: FRAME_GUARD_V2 ──
console.log(
  "[W4P_SOURCE_OF_TRUTH]",
  "/home/wa/ConceptPoker/extension",
  Date.now()
);
console.log(
  "[W4P_BUILD]",
  "path=/home/wa/ConceptPoker/extension/w4p.js",
  "build=FRAME_GUARD_V2",
  "ts=" + Date.now()
);
window.__W4P_BUILD_ID = "FRAME_GUARD_V2";

// W4P Injectable v22-stable-hardened - PLO Remote Table Control (hero-only: .self-player class ONLY, no fallbacks)
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

  // ── Frame identity & fingerprint (pure — no side effects) ──
  var _isTop = window === window.top;
  var _frameEl = window.frameElement;
  var _frameId = _frameEl ? (_frameEl.id || '') : '';
  var _frameSrc = _frameEl ? (_frameEl.src || '') : '';
  var _locHref = location.href || '';
  var _timeOrigin = (typeof performance !== 'undefined' && performance.timeOrigin) || '';

  var _host = location.hostname || '';
  var _path = location.pathname || '';
  var _href = _locHref;

  // ── URL Guard: only run on real PokerBet/GoldRush poker game frames ──
  function hasPokerTableProof() {
    try {
      return !!document.querySelector(
        'sg-poker-table, sg-poker-table-seat, .player-mini-container-p, .control-b-view-p, .pot-w-view-p, .single-cart-view-p'
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
      host === '192.168.0.106' ||
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

  function stopObserver() {
    if (_observer) { _observer.disconnect(); _observer = null; }
    if (window._w4p_fallback) { clearInterval(window._w4p_fallback); window._w4p_fallback = null; }
  }

  function stopW4PTimers() {
    if (window._w4p_timer) { clearTimeout(window._w4p_timer); window._w4p_timer = null; }
    if (window._w4p_cmdTimer) { clearTimeout(window._w4p_cmdTimer); window._w4p_cmdTimer = null; }
    if (window._w4p_bbTimer) { clearInterval(window._w4p_bbTimer); window._w4p_bbTimer = null; }
    if (window._w4p) { clearInterval(window._w4p); window._w4p = null; }
    stopObserver();
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

  var _urlTableId = (_locHref.match(/\/tbl\/(\d+)/) || _locHref.match(/openGames=(\d+)/) || _locHref.match(/game[_-]?id[=\/](\d+)/i) || [,''])[1] || '';

  console.log('[W4P_BOOT] frameId=' + (_frameId || 'none') + ' url=' + _locHref.substring(0, 80) + ' ts=' + Date.now());

  // ── Poker app URL detection (used by multiple guards below) ──
  var _isPokerAppUrl =
    /poker-web\.goldrush\.co\.za/i.test(_locHref) ||
    /games\.goldrush\.co\.za\/LaunchGame/i.test(_locHref) ||
    /skillgames/i.test(_locHref) ||
    /\/187\d{3,}/i.test(_locHref);

  // ══════════════════════════════════════════════════════════════
  // FRAME TYPE DETECTION & VALIDATION — no side effects
  // Types identified: top | lobby | detached | preload | unknown | table
  // ══════════════════════════════════════════════════════════════

  // ── Top window — game runs inside iframe, exit immediately ──
  if (_isTop) {
    console.log('[W4P][FRAME_SKIP] top window — game runs inside iframe, exiting');
    return;
  }

  // ── Poker URL bypass: skip all frameElement checks for known poker table URLs ──
  // Cross-origin iframes (e.g. poker-web.goldrush.co.za within goldrush.co.za) have
  // null frameElement. URL identification is more reliable than frameElement.
  if (_isPokerAppUrl) {
    console.log('[W4P][FRAME_BYPASS] poker URL match — all frameElement checks bypassed, url=' + _locHref.substring(0, 120));
  } else {
    // ── Detached iframe — frameElement is null or stale ──
    if (!_frameEl) {
      console.log('[W4P][FRAME_SKIP] detached iframe — no frameElement and not poker app URL, exiting url=' + _locHref.substring(0, 120));
      return;
    }
    // ── Lobby / chat / sidebar frames ──
    if (/lobby|chat|sidebar|topbar|header|footer|nav/i.test(_frameId) || /lobby|chat/i.test(_frameSrc)) {
      console.log('[W4P][FRAME_SKIP] lobby iframe id=' + _frameId + ' src=' + _frameSrc.substring(0, 80));
      return;
    }
    // ── Preload frame (zero-size or hidden) — after lobby check for accurate logging ──
    if (_frameEl.offsetWidth === 0 || _frameEl.offsetHeight === 0) {
      console.log('[W4P][FRAME_SKIP] preload iframe (hidden) id=' + _frameId + ' — zero-size, exiting');
      return;
    }
    // ── Table frame check by ID/src (non-poker URLs only) ──
    var _isTableFrame = (_frameId.indexOf('187') === 0) ||
                        (_frameSrc.indexOf('skillgames') !== -1) ||
                        (_frameSrc.indexOf('187') !== -1);
    if (!_isTableFrame) {
      console.log('[W4P][FRAME_SKIP] unknown frame id=' + _frameId + ' src=' + _frameSrc.substring(0, 80) + ' — not a table iframe');
      return;
    }
  } // end _isPokerAppUrl guard

  // ── Preload: table iframe exists but no seat content yet ─────
  // NOTE: For known poker app URLs, retry up to 30s for Angular to render seats
  if (!document.querySelector('sg-poker-table-seat, .player-mini-container-p')) {
    if (_isPokerAppUrl) {
      console.log('[W4P][FRAME_WAIT] poker URL — waiting up to 30s for seats...');
      var _seatWaitCount = 0;
      (function seatRetry() {
        _seatWaitCount++;
        if (document.querySelector('sg-poker-table-seat, .player-mini-container-p')) {
          console.log('[W4P][FRAME_WAIT] seats appeared after ~' + (_seatWaitCount * 500) + 'ms');
          _initFrame();
        } else if (_seatWaitCount >= 60) {
          console.log('[W4P][FRAME_SKIP] no seats after 30s — giving up');
        } else {
          setTimeout(seatRetry, 500);
        }
      })();
      return;
    }
    console.log('[W4P][FRAME_SKIP] preload iframe (empty) id=' + (_frameId || 'none') + ' url=' + _locHref.substring(0, 80) + ' — no seats yet, exiting');
    return;
  }
  _initFrame(); return; // seats found immediately — start frame

  function _initFrame() {

  // ═  // ══════════════════════════════════════════════════════════════
 // FRAME FINGERPRINT — multi-dimensional, deterministic
  // Components: frameElement.id | location.href (no query/hash) | performance.timeOrigin
  // ══════════════════════════════════════════════════════════════
  var _fpUrl = _locHref.replace(/[?#].*$/, '');  // strip query/hash for stability across hand transitions
  var _fingerprint = _frameId + '|' + _fpUrl + '|' + _urlTableId + '|' + _timeOrigin;
  var _guardKey = 'w4p_v22_' + _fingerprint;

  // ── Per-frame singleton guard ────────────────────────────────
  if (window.__W4P_ALREADY_RUNNING__ === _guardKey) {
    console.log('[W4P][DUPLICATE_BLOCKED] key=' + _guardKey + ' — already running in this frame');
    return;
  }
  window.__W4P_ALREADY_RUNNING__ = _guardKey;

  // ── Top-level coordination (across all frames) ───────────────
  try {
    if (window.top.__W4P_SESSION__ === _guardKey) {
      console.log('[W4P][DUPLICATE_BLOCKED] top-level session key=' + _guardKey + ' — already active, exiting');
      return;
    }
    window.top.__W4P_SESSION__ = _guardKey;
  } catch (_e) {
    // Cross-origin top window — per-frame guard is sufficient
  }

  // ══════════════════════════════════════════════════════════════
  // FRAME LOCKED — confirmed active table iframe
  // Side effects below this line are safe
  // ══════════════════════════════════════════════════════════════
  console.log('[W4P][FRAME_LOCKED] table frame id=' + _frameId + ' src=' + _frameSrc.substring(0, 80) + ' fingerprint=' + _fingerprint.substring(0, 60));

  // ── Cleanup prior instances (safe: frame validated) ──────────
  if (window._w4p_timer) { clearTimeout(window._w4p_timer); window._w4p_timer = null; }
  if (window._w4p_cmdTimer) { clearTimeout(window._w4p_cmdTimer); window._w4p_cmdTimer = null; }
  if (window._w4p_bbTimer) { clearInterval(window._w4p_bbTimer); window._w4p_bbTimer = null; }
  if (window._w4p) { clearInterval(window._w4p); window._w4p = null; }
  window._w4p_injected = false;

  // ── Config ───────────────────────────────────────────────────
  // API_BASE: set via window.__W4P_API_BASE before injection, or defaults:
  //   Local dev:  http://127.0.0.1:4000/api
  //   Production: http://127.0.0.1:4000/api
  var API_BASE = window.__W4P_API_BASE || 'http://127.0.0.1:4000/api';
  var API_KEY  = '03622c896cfbeacdfc537e9434f9ddc5';

  // ── Direct fetch (CORS enabled on Flask — works standalone and in extension) ──
  // Set via window.__W4P_SITE_BASE, defaults to API_BASE root
  var SITE_BASE = window.__W4P_SITE_BASE || (function() {
    var m = API_BASE.match(/^(https?:\/\/[^/]+)/);
    return m ? m[1] : 'http://127.0.0.1:4000';
  })();
  function bridgeFetch(path, method, body, callback) {
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(API_BASE + path, opts)
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP_' + r.status);
        return r.json();
      })
      .then(function(data) { if (callback) callback({ ok: true, data: data }); })
      .catch(function(e) {
        var status = 0;
        if (e.message.indexOf('HTTP_') === 0) status = parseInt(e.message.substring(5), 10);
        if (status) {
          // fetch status captured for callback below
        } else {
          // network error captured for callback below
        }
        if (callback) callback({ ok: false, error: e.message, status: status });
      });
  }
  function bridgeFetchRaw(path, method, body, callback) {
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(SITE_BASE + path, opts)
      .then(function(r) { return r.json(); })
      .then(function(data) { if (callback) callback({ ok: true, data: data }); })
      .catch(function(e) { console.warn('[W4P] fetchRaw error:', path, e.message); if (callback) callback({ ok: false, error: e.message }); });
  }

  // v15: tightened polling — faster detection, faster commands
  var POLL_MS = { HERO_TURN: 300, HAND_ACTIVE: 300, IDLE: 300, NO_TABLE: 2000 };
  var CMD_MS  = { HERO_TURN: 150, HAND_ACTIVE: 150, IDLE: 150 };
  var HEARTBEAT_MS = 8000;
  var CASHOUT_POLL_MS = 75;  // hyper-poll interval when cashout preselected
  var SNAPSHOT_INTERVAL_MS = 1000;   // minimum ms between snapshot POSTs
  var SNAPSHOT_BACKOFF_MS = 10000;   // backoff ms after 429 response

  var _mode = 'IDLE';
  var _seatToken = null;
  var _preAction = null;    // 'check_fold' | 'check_call' | null
  var _lastHash = null;
  var _lastSendTime = 0;
  var _n = 0;
  var _sessionId = 'w4p_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
  var _clientId = localStorage.getItem('w4p_client_id');
  if (!_clientId) {
    _clientId = 'w4pc_' + Date.now() + '_' + Math.random().toString(36).substr(2, 12);
    localStorage.setItem('w4p_client_id', _clientId);
  }
  var _lastButtons = null;
  var _cashoutPre = false;   // when true, hyper-poll for cashout DOM element
  var _cashoutTimer = null;
  var _lastBoardLen = 0;     // track board cards for new hand detection
  function _heroFromUrl() {
    try {
      var url = window.location.href;
      var m = url.match(/tbl\/(\d+)/);
      if (m) return "hero_tbl" + m[1];
      m = url.match(/userid=(-?\d+)/);
      if (m) return "hero_uid" + m[1];
      m = url.match(/hash=([a-f0-9]{4,})/);
      if (m) return "hero_h" + m[1].slice(0, 8);
    } catch(e) {}
    return "hero_auto_" + Date.now().toString(36);
  }
  var _lastHeroName = localStorage.getItem('w4p_hero_name') || null;  // persist hero name across sitting-out / folded states (localStorage survives reloads)
  var _wasHeroTurn = false;  // state-change gate: prevent repeated HERO_TURN activation
  var _snapshotInFlight = false;    // guard: prevent overlapping snapshot POSTs
  var _nextSnapshotAllowedAt = 0;   // throttle: timestamp when next snapshot is allowed
  var _lastSnapshotHash = '';       // dedup: hash of last sent snapshot state

  // ── Phase 2: MutationObserver + zero-alloc snapshot ──
  var _heroSeatIndex = null;        // cached hero seat index — don't re-query every tick
  var _observer = null;             // MutationObserver instance
  var _lastTickTime = 0;            // timestamp of last processTick for fallback interval
  var _tickScheduled = false;       // guard: prevent rAF stacking
  var _pollActive = false;          // poll dedup guard — prevents concurrent sendSnapshot
  var _handEpoch = 0;               // hand epoch — bumps on board change, sent to backend
  var _seqId = 0;                   // monotonic snapshot sequence ID
  var _lastBoardHash = '';          // track board changes to auto-bump epoch
  var _snapshot = {                 // persistent mutable snapshot (zero-alloc — reused each tick)
    seats: [],
    board: null,
    dirty: false
  };

  // ── Cache hero seat index at init, don't re-query every tick ──
  function getHeroIndex() {
    if (_heroSeatIndex !== null) return _heroSeatIndex;
    var containers = document.querySelectorAll('sg-poker-table-seat');
    if (!containers.length) containers = document.querySelectorAll('.player-mini-container-p');
    for (var i = 0; i < containers.length; i++) {
      if (containers[i].classList.contains('self-player')) {
        _heroSeatIndex = i;
        return i;
      }
    }
    _heroSeatIndex = -1;
    return -1;
  }

  // ── Zero-alloc: patch a single seat in the persistent snapshot ──
  function patchSeat(index, changes) {
    if (!_snapshot.seats[index]) {
      _snapshot.seats[index] = {};
    }
    var seat = _snapshot.seats[index];
    for (var key in changes) {
      if (changes.hasOwnProperty(key)) {
        seat[key] = changes[key];
      }
    }
    _snapshot.dirty = true;
  }

  // ── v22-hardened: duplicate command guard + action cooldowns ──
  var _lastCmdId = null;              // last executed command ID — reject duplicates
  var _actionCooldowns = {};          // { 'action_name': timestamp } — per-action cooldown
  var _ACTION_COOLDOWN_MS = 800;      // min ms between same action (prevent double-click)
  var _PRESET_COOLDOWN_MS = 1500;     // min ms between preset executions (preset→verify→execute cycle)
  var _cmdCount = 0;                  // total commands processed this session

  var RANK_MAP = { 'a':'A', 'k':'K', 'q':'Q', 'j':'J', 't':'T', '10':'T' };

  // ── Action button selectors (PokerBet / BetConstruct DOM) ───
  var BTN_SEL = {
    fold:         '.control-b-view-p.fold-c',
    check:        '.control-b-view-p.check-c',
    call:         '.control-b-view-p.call-c',
    raise:        '.control-b-view-p.raise-c',
    bet:          '.control-b-view-p.bet-c',
    cashout:      '.control-b-view-p.cash_out-c',
    allin:        '.control-b-view-p.all_in-c',
    show:         '.control-b-view-p.show-c',
    run_it_twice: '.control-b-view-p.run_it_twice-c',
    resume_hand:  '.control-b-view-p.resume_hand-c',
    back_to_game: '.control-b-view-p.back_to_game-c'
  };

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

  
  // ── Robust card parser: accepts PLO4/PLO5/PLO6/PLO7 hero cards ──
  function cardsFromClass(cls) {
    var out = [];
    if (!cls) return out;

    cls = String(cls);

    function add(rank, suit) {
      if (!rank || !suit) return;

      rank = String(rank).toLowerCase();
      suit = String(suit).toLowerCase();

      rank = RANK_MAP[rank] || rank.toUpperCase();
      suit = suit[0];

      if (!/^[AKQJT2-9]$/.test(rank)) return;
      if (!/^[shdc]$/.test(suit)) return;

      var c = rank + suit;
      if (out.indexOf(c) === -1) out.push(c);
    }

    var m;

    // Main Goldrush/PokerBet class pattern:
    // icon-layer2_dq_p-c-d, icon-layer2_s10_p-c-d, etc.
    var re1 = /icon-layer2_([shdc])(10|[akqjt2-9])_p-c-d/ig;
    while ((m = re1.exec(cls)) !== null) {
      add(m[2], m[1]);
    }

    // Backup: rank then suit, e.g. Qd, card-Qd, q-d
    var re2 = /(?:^|[^a-z0-9])(?:card[-_])?(10|[akqjt2-9])[-_]?([shdc])(?:[^a-z0-9]|$)/ig;
    while ((m = re2.exec(cls)) !== null) {
      add(m[1], m[2]);
    }

    // Backup: suit then rank, e.g. dQ, d-q
    var re3 = /(?:^|[^a-z0-9])([shdc])[-_]?(10|[akqjt2-9])(?:[^a-z0-9]|$)/ig;
    while ((m = re3.exec(cls)) !== null) {
      add(m[2], m[1]);
    }

    return out;
  }

  function parseCard(cls) {
    var cards = cardsFromClass(cls);
    return cards.length ? cards[0] : null;
  }

  // ── Extract ALL visible hero hole cards from the self-player seat ──
  function extractCardsFromSeat(ct) {
    var out = [];
    if (!ct) return out;

    function addCardsFromClass(cls) {
      var cards = cardsFromClass(cls || '');
      for (var i = 0; i < cards.length; i++) {
        if (out.indexOf(cards[i]) === -1) out.push(cards[i]);
        if (out.length >= 7) return;
      }
    }

    // Do not depend on .cards-container-p. Goldrush/PokerBet uses nested card/icon classes.
    var els = ct.querySelectorAll(
      '.single-card-view-p, .single-cart-view-p, ' +
      '[class*="single-card"], [class*="single-cart"], [class*="icon-layer2_"], ' +
      'i, span, div'
    );

    for (var i = 0; i < els.length; i++) {
      var el = els[i];

      if (typeof el.className === 'string') {
        addCardsFromClass(el.className);
      }

      var classAttr = el.getAttribute && el.getAttribute('class');
      if (classAttr) {
        addCardsFromClass(classAttr);
      }

      if (out.length >= 7) break;
    }

    console.log('[W4P][HERO_CARDS_EXTRACT]', out, 'count=' + out.length);
    return out.slice(0, 7);
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
    if (url.indexOf('skillgames') !== -1 || /187\d+/.test(url)) {
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
  function getAvailableActions() {
    var heroSeat = document.querySelector('sg-poker-table-seat.self-player') || document.querySelector('.player-mini-container-p.self-player');
    if (!heroSeat) { _detectedBtns = {}; return []; }
    _detectedBtns = {};
    var avail = [];

    // Primary: scan ALL known selectors (including allin) + cache element refs
    for (var name in BTN_SEL) {
      var btn = document.querySelector(BTN_SEL[name]);
      var rect = btn ? btn.getBoundingClientRect() : null;
      if (btn && rect && rect.width > 0 && rect.height > 0) {
        avail.push(name);
        _detectedBtns[name] = {
          el: btn, selector: BTN_SEL[name],
          text: (btn.textContent || '').trim().substring(0, 30),
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2)
        };
      }
    }

    // Also detect slider presets if slider is open
    detectSliderPresets();

    // Fallback: scan ALL visible control elements by class
    if (avail.length === 0) {
      var actionMap = {fold:'fold', check:'check', call:'call', raise:'raise', bet:'bet',
                       cashout:'cashout', show:'show', allin:'all_in'};
      var candidates = document.querySelectorAll('[class*="fold"], [class*="check"], [class*="call"], [class*="raise"], [class*="bet-c"], [class*="cash_out"], [class*="all_in"]');
      for (var i = 0; i < candidates.length; i++) {
        var el = candidates[i];
        if (el.offsetParent === null && el.offsetWidth === 0) continue;
        var cls = el.className.toLowerCase();
        for (var key in actionMap) {
          var searchTerm = actionMap[key] || key;
          if (cls.indexOf(searchTerm) !== -1 && avail.indexOf(key) === -1) {
            avail.push(key);
            var frect = el.getBoundingClientRect();
            _detectedBtns[key] = {
              el: el, selector: buildCssPath(el),
              text: (el.textContent || '').trim().substring(0, 30),
              x: Math.round(frect.x + frect.width / 2),
              y: Math.round(frect.y + frect.height / 2)
            };
          }
        }
      }
      if (avail.length > 0 && _n <= 5) {
        console.log('[W4P] actions via fallback:', avail.join(','));
      }
    }

    // Log detected buttons on first few ticks for debugging
    if (avail.length > 0 && _n <= 3) {
      var btnList = [];
      for (var bk in _detectedBtns) {
        btnList.push(bk + '=' + _detectedBtns[bk].selector);
      }
      console.log('[W4P] detected buttons: ' + btnList.join(' | '));
    }

    return avail;
  }

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
    var heroSeat = document.querySelector('sg-poker-table-seat.self-player') || document.querySelector('.player-mini-container-p.self-player');
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

    // Log every tick (compact)
    var _foundNames = _validation.filter(function(v){return v.found;}).map(function(v){return v.name+(v.visible?'[V]':'[H]')+(v.disabled?'[D]':'');});
    console.log('[W4P][VALID] hero=' + (heroSeat?'Y':'N') + ' active=' + _heroActive +
      ' | selectors: ' + (_foundNames.length > 0 ? _foundNames.join(',') : 'NONE') +
      ' | .control-b-view-p=' + _allCtrl.length);

    // Full dump every 10 ticks (or when any selector found)
    if (_n % 10 === 1 || _foundNames.length > 0) {
      console.log('[W4P][VALID-FULL]', JSON.stringify({
        tick: _n, heroSeat: !!heroSeat, heroActive: _heroActive,
        heroClasses: heroSeat ? heroSeat.className.substring(0, 100) : null,
        selectors: _validation,
        rawControls: _ctrlDump
      }));
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

    // ── DIAGNOSTIC: log when we actually detect buttons ──
    if (result.actions.length > 0) {
      console.log('[W4P][DIAG] DETECTED BUTTONS:', JSON.stringify(result.actions.map(function(a) { return a.action + '(' + (a.amount || '-') + ')'; })));
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

  // ── Build full snapshot — ALL seats ──────────────────────────
  function buildSnapshot() {
    if (stopNonPokerScrapeContext('buildSnapshot')) return null;

    var tableId = getTableId();
    if (!tableId) {
      if (_n <= 5 || _n % 30 === 0)
        console.log('[W4P] no tableId');
      return null;
    }

    var containers = document.querySelectorAll('sg-poker-table-seat');
    if (!containers.length) containers = document.querySelectorAll('.player-mini-container-p');
    if (!containers.length) {
      if (_n <= 5 || _n % 30 === 0)
        console.log('[W4P] no seat containers');
      return null;
    }

    // Dealer position
    var dealerEl = document.querySelector('.dealer-icon-view');
    var dMatch = dealerEl ? dealerEl.className.match(/position-(\d+)/) : null;
    var dealerSeat = dMatch ? parseInt(dMatch[1]) : null;

    // Pot amount
    var potEl = document.querySelector('.pot-w-view-p') || document.querySelector('.pot-amount') || document.querySelector('.total-pot');
    var potText = potEl ? (potEl.innerText || potEl.textContent || '') : '';
    var pMatch = potText.match(/([\d.,]+)/);
    var potZar = pMatch ? parseFloat(pMatch[1].replace(',', '')) : 0;

    // Board cards (community cards only)
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
    // Fallback ONLY if sg-poker-board doesn't exist (DOM structure changed)
    // Never fallback when boardEl exists — preflop legitimately has 0 cards
    if (!boardEl) {
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

    var buttons = detectButtons();
    var avail = buttons.actions.map(function(a) { return a.action; });

    // ── STEP 2 DIAG: Log detected buttons EVERY tick ──
    console.log('[W4P][DIAG] DETECTED BUTTONS:', JSON.stringify(buttons.actions.map(function(a){return a.action;})));
    console.log('[W4P][DIAG] available_actions:', JSON.stringify(avail));

    // ── Detect active seat (whose turn to act) from PokerBet DOM ──
    // self-player with visible action buttons = hero's turn (primary signal)
    // .active class is checked as secondary hint only
    var activePlayerName = null;
    for (var ai = 0; ai < containers.length; ai++) {
      var act = containers[ai];
      var isActSelf = act.classList.contains('self-player');
      var hasActClass = act.classList.contains('active') || !!act.querySelector('.active-turn');
      if (hasActClass || (isActSelf && avail.length > 0)) {
        var anEl = act.querySelector('p.single-win-item-sizes') || act.querySelector('.player-name');
        activePlayerName = anEl ? (anEl.innerText || anEl.textContent || '').trim() : null;
        if (!activePlayerName) activePlayerName = null;
        break;
      }
    }

    // ── Scrape ALL seats ────────────────────────────────────────
    _snapshot.seats.length = 0;  // zero-alloc: clear persistent array
    var heroName = null;

    for (var i = 0; i < containers.length; i++) {
      var ct = containers[i];
      var isHero = ct.classList.contains('self-player');  // canonical: ONLY reliable hero signal (see line 913 comment)

      var posMatch = ct.className.match(/position-(\d+)/);
      var seatIdx = posMatch ? parseInt(posMatch[1]) : i;

      // Player name
      var nameEl = ct.querySelector('p.single-win-item-sizes') || ct.querySelector('.player-name');
      var name = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : null;
      if (!name || name === '') name = null;

      // Stack
      var stackEl = ct.querySelector('.player-text-info-p span b') || ct.querySelector('.player-text-info-p b') || ct.querySelector('.player-stack');
      var stackText = stackEl ? (stackEl.innerText || stackEl.textContent || '') : '';
      var sMatch = stackText.match(/([\d.,]+)/);
      var stackZar = sMatch ? parseFloat(sMatch[1].replace(',', '')) : 0;

      // Hole cards — use robust extractor (no dependency on .cards-container-p)
      var holeCards = isHero ? extractCardsFromSeat(ct) : [];

      // REMOVED: hole-cards fallback was marking villains as hero during showdown
      // when all players' cards are revealed face-up. The .self-player class is
      // the ONLY reliable hero signal — it's set by the poker client on the
      // player's own seat and never appears on villains even at showdown.

      if (isHero) { heroName = name || _lastHeroName; if (name) { _lastHeroName = name; try { localStorage.setItem('w4p_hero_name', name); } catch(_) {} } }

      // Status detection
      var sittingOut = ct.classList.contains('seat-out-v') || !!ct.querySelector('.seat-out-v');
      var isFolded = ct.classList.contains('folded') || !!ct.querySelector('.folded');
      var isActive = isHero && avail.length > 0;  // visible buttons = hero's turn

      var status = 'playing';
      if (sittingOut) status = 'sitting_out';
      else if (isFolded) status = 'folded';
      else if (holeCards.length === 0 && street !== 'PREFLOP') status = 'folded';

      _snapshot.seats.push({
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

    // Must have found hero
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
      heroName = _heroFromUrl();
      if (heroName) { _lastHeroName = heroName; console.log("[W4P] hero_from_url: " + heroName); }
      else { return null; }
    }

    // ── Zero-alloc: mutate persistent _snapshot object ──
    _snapshot.table_id = tableId;
    _snapshot.bot_id = heroName;
    _snapshot.client_id = _clientId;
    _snapshot.session_id = _sessionId;
    // seats already set above via _snapshot.seats.push()
    if (!_snapshot.board) _snapshot.board = {};
    _snapshot.board.flop = boardCards.slice(0, 3);
    _snapshot.board.turn = boardCards[3] || null;
    _snapshot.board.river = boardCards[4] || null;
    _snapshot.pot_zar = potZar;
    _snapshot.dealer_seat = dealerSeat;
    _snapshot.street = street;
    _snapshot.variant = 'plo';
    _snapshot.buttons = buttons;
    _snapshot.available_actions = avail;
    _snapshot.active_player = activePlayerName;
    _snapshot.ts = new Date().toISOString();
    _snapshot.source_key = 'w4p_inject';
    _snapshot.frame_locked = true;
    _snapshot.frame_url = location.href;
    _snapshot.dirty = true;

    // ── Freshness: auto-bump hand epoch on board change ──
    var boardHash = (boardCards || []).join('');
    if (boardHash && boardHash !== _lastBoardHash) {
      _lastBoardHash = boardHash;
      _handEpoch++;
      console.log('[W4P][EPOCH] Board change detected — hand_epoch=' + _handEpoch);
    }
    // Always increment sequence ID per snapshot
    _seqId++;
    _snapshot.hand_epoch = _handEpoch;
    _snapshot.sequence_id = _seqId;

    return _snapshot;
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
    _pollActive = false;  // Clear poll dedup guard
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
    // ── Guard: in-flight check ──
    if (_snapshotInFlight) {
      _pollActive = false;
      return;
    }

    // ── Guard: minimum interval ──
    var now = Date.now();
    if (now < _nextSnapshotAllowedAt) {
      _pollActive = false;
      return;
    }

    // ── Guard: dedup — skip if state unchanged (forced send every 30s for heartbeat) ──
    var hash = stateHash(snap);
    if (hash !== '' && hash === _lastSnapshotHash && now - _lastSendTime < 30000) {
      _pollActive = false;
      return;
    }

    // ── Guard: reduced frequency when hero has no readable cards and not active ──
    var hero = null;
    for (var i = 0; i < snap.seats.length; i++) {
      if (snap.seats[i].is_hero) { hero = snap.seats[i]; break; }
    }
    var hasCards = hero && hero.hole_cards && hero.hole_cards.length > 0;
    if (!hasCards && !(hero && hero.is_active) && now - _lastSendTime < 10000 && _n > 5) {
      _pollActive = false;
      return;
    }

    _snapshotInFlight = true;
    _lastSnapshotHash = hash;

    bridgeFetch('/snapshot', 'POST', snap, function(resp) {
      _snapshotInFlight = false;
      if (resp && resp.ok) {
        _lastSendTime = Date.now();
        _nextSnapshotAllowedAt = Date.now() + SNAPSHOT_INTERVAL_MS;
        handleSnapshotResponse(resp.data);
      } else {
        _pollActive = false;  // Clear on error too
        if (resp && resp.status === 429) {
          _nextSnapshotAllowedAt = Date.now() + SNAPSHOT_BACKOFF_MS;
          console.log('[W4P][SNAPSHOT] 429 — backoff ' + SNAPSHOT_BACKOFF_MS + 'ms');
        } else {
          _nextSnapshotAllowedAt = Date.now() + SNAPSHOT_INTERVAL_MS;
        }
        //console.log('[W4P] bridge error:', resp ? (resp.error || 'no response') : 'no response');
      }
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
    var hero = document.querySelector('.player-mini-container-p.self-player');
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
      window._w4p_cmdTimer = setTimeout(pollCommands, CMD_MS[_mode] || 500);
    });

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

  // ── Core tick logic (driven by MutationObserver + rAF primary, setTimeout fallback) ──
  function processTick() {
    if (_n === 0) console.log('[W4P][TICK_ENTER] first tick — frame validated, starting loop');
    _n++;
    _lastTickTime = Date.now();
    if (stopNonPokerScrapeContext('tick')) return;

    var snap = buildSnapshot();

    if (!snap) {
      _mode = 'NO_TABLE';
      window._w4p_timer = setTimeout(tick, POLL_MS.NO_TABLE);
      return;
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
      // New hand — clear pre-actions but NOT cashout preselect
      _preAction = null;
    }
    // Street transition: clear check_call pre-action when leaving preflop
    // (C/C ALL PREFLOP is preflop-only; stale pre-action must not fire on flop)
    if (_preAction === 'check_call' && snap.street && snap.street !== 'PREFLOP') {
      console.log('[W4P] Clearing stale check_call pre-action — street=' + snap.street);
      _preAction = null;
    }
    _lastBoardLen = boardLen;

    // Try cashout BEFORE mode calculation (cashout button may appear at any time)
    tryCashout();

    // ── State-change gate: prevent repeated HERO_TURN reactivation ──
    // self-player is a STATE SOURCE, not an event trigger.
    // Only change mode on a genuine state transition, not on every DOM tick.
    var _isHeroTurnNow = avail.length > 0;
    var _modeChanged = false;

    if (_isHeroTurnNow && !_wasHeroTurn) {
      _modeChanged = true;
      if (_n <= 10 || _n % 20 === 0)
        console.log('[W4P][STATE] IDLE/HAND_ACTIVE → HERO_TURN (avail=' + avail.join(',') + ')');
    }
    if (!_isHeroTurnNow && _wasHeroTurn) {
      _modeChanged = true;
      if (_n <= 10 || _n % 20 === 0)
        console.log('[W4P][STATE] HERO_TURN → IDLE/HAND_ACTIVE');
    }
    _wasHeroTurn = _isHeroTurnNow;

    if (avail.length > 0) _mode = 'HERO_TURN';
    else if (snap.street !== 'PREFLOP') _mode = 'HAND_ACTIVE';
    else _mode = 'IDLE';

    // ── Poll dedup guard: prevent concurrent sendSnapshot calls ──
    if (_pollActive) {
      if (_n % 50 === 0) console.log('[W4P][DEDUP] Skipped tick — poll already in flight');
      window._w4p_timer = setTimeout(tick, pollMs);
      return;
    }
    _pollActive = true;
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

  // ── Tick entry point (used by setTimeout fallback — primary driver is MutationObserver) ──
  function tick() {
    processTick();
  }

  // ── MutationObserver: DOM-driven primary tick scheduler ───────
  function scheduleTick() {
    if (_tickScheduled) return;
    _tickScheduled = true;
    requestAnimationFrame(function() {
      _tickScheduled = false;
      processTick();
    });
  }

  function startObserver() {
    if (_observer) return;
    try {
      _observer = new MutationObserver(function() {
        scheduleTick();
      });
      _observer.observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['class', 'style']
      });
      console.log('[W4P][OBSERVER] MutationObserver started — DOM-driven ticks active');
    } catch (e) {
      console.warn('[W4P][OBSERVER] MutationObserver failed — falling back to interval only:', e.message);
      _observer = null;
    }

    // Fallback interval: catch anything the observer misses (500ms safety net)
    window._w4p_fallback = setInterval(function() {
      if (Date.now() - _lastTickTime > 500) {
        scheduleTick();
      }
    }, 500);
  }

  // ── Start ────────────────────────────────────────────────────
  untickWaitBB();
  window._w4p_bbTimer = setInterval(untickWaitBB, 5000);

  var _buildTag = 'v22-stable-hardened+phase2';
  var _buildTs  = '2026-06-12T00:00:00Z';
  console.log('[W4P] ═══════════════════════════════════════════════');
  console.log('[W4P] ' + _buildTag + ' | built=' + _buildTs + ' | session=' + _sessionId);
  console.log('[W4P] guards: dup-cmd, cooldown=' + _ACTION_COOLDOWN_MS + 'ms, preset-cd=' + _PRESET_COOLDOWN_MS + 'ms');
  console.log('[W4P] polling: hero=' + POLL_MS.HERO_TURN + 'ms cmd=' + CMD_MS.HERO_TURN + 'ms cashout-hyper=' + CASHOUT_POLL_MS + 'ms');
  console.log('[W4P] API: ' + API_BASE + ' | rollback: w4p.js.v22-stable.bak');
  console.log('[W4P] Phase 2: MutationObserver + zero-alloc snapshot + heroSeatIndex cache');
  console.log('[W4P] ═══════════════════════════════════════════════');
  tick();
  startObserver();  // Phase 2: primary tick driver (MutationObserver + rAF)

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
    stopObserver();
    console.log('[W4P] stopped');
  };
}
})();

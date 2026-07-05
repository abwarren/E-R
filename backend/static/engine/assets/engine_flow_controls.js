(() => {
  'use strict';

  const VERSION = '2.1.0-engine-bridge';
  const STORAGE_KEY = "engineFlowToggles";
  const BRIDGE_URL = (window.W4P_API && window.W4P_API.LATEST) || (window.location.origin + '/api/latest');

  const defaultState = {
    autoFill: true,
    autoRunFlop: true,
    manualTurnOnly: true,
    clearRiver: true
  };

  const VARIANT_CARDS = { 'plo4': 4, 'plo5': 5, 'plo6': 6, 'plo7': 7 };
  const BOARD_LENGTHS = { 6: 'FLOP', 8: 'TURN', 10: 'RIVER' };
  const RANKS = '23456789TJQKA';
  const SUITS = 'cdhs';
  const FULL_DECK = [];
  for (const r of RANKS) for (const s of SUITS) FULL_DECK.push(r + s);

  let lastStateKey = null;
  let lastSnapshotHash = null;
  let lastHandId = null;
  let isRunning = false;
  const FAST_POLL = 1500;
  const SLOW_POLL = 5000;
  const IDLE_THRESHOLD = 30000;
  let lastDataChange = Date.now();
  let currentInterval = FAST_POLL;
  let pollTimer = null;
  let consecutiveErrors = 0;
  const MAX_CONSECUTIVE_ERRORS = 5;
  const ERROR_BACKOFF_MS = 5000;
  let isPageVisible = !document.hidden;

  function loadState() {
    try {
      return { ...defaultState, ...(JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}) };
    } catch { return { ...defaultState }; }
  }

  function saveState(state) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) { console.error('[AUTO] Failed to save state:', e); }
  }

  function isValidCard(s) {
    return s.length === 2 && RANKS.includes(s[0].toUpperCase()) && SUITS.includes(s[1].toLowerCase());
  }

  function parseCards(line) {
    const cards = [];
    for (let i = 0; i < line.length - 1; i += 2) {
      const c = line.substring(i, i + 2);
      if (isValidCard(c)) cards.push(c);
      else return null;
    }
    return cards;
  }

  function getUnusedCard(forbidden) {
    const set = new Set(forbidden.map(c => c.toLowerCase()));
    for (const card of FULL_DECK) {
      if (!set.has(card.toLowerCase())) return card;
    }
    return null;
  }

  function hasDuplicates(cards) {
    const lower = cards.map(c => c.toLowerCase());
    return new Set(lower).size !== lower.length;
  }

  function getSelectedVariant() {
    const sel = document.querySelector('select');
    return sel ? (sel.value || null) : null;
  }

  function getRequiredCards(variant) {
    if (!variant) return null;
    return VARIANT_CARDS[variant.split('-')[0]] || null;
  }

  function formatTableDataToCanonical(table) {
    if (!table) return '';
    const seats = table.seats || [];
    const board = table.board || {};
    const hands = [];
    for (const seat of seats) {
      const cards = seat.hole_cards;
      if (cards && Array.isArray(cards) && cards.length > 0) {
        const valid = cards.filter(c => c && c.length === 2);
        if (valid.length > 0) hands.push(valid.join(''));
      }
    }
    if (hands.length === 0) return '';
    const flop = (board.flop || []).filter(Boolean).join('');
    const turn = (board.turn || []).filter(Boolean).join('');
    const river = (board.river || []).filter(Boolean).join('');
    const boardStr = flop + turn + river;
    const lines = [...hands];
    if (boardStr) lines.push(boardStr);
    return lines.join('\n');
  }

  function parseSnapshot(text, requiredCards) {
    if (!text) return null;
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    const handLen = requiredCards * 2;
    const hands = [];
    let board = null, boardStreet = null;
    for (const line of lines) {
      const len = line.length;
      if (BOARD_LENGTHS[len] && len !== handLen) {
        const cards = parseCards(line);
        if (cards) { board = line; boardStreet = BOARD_LENGTHS[len]; }
      } else if (len === handLen) {
        const cards = parseCards(line);
        if (cards) hands.push(line);
      } else if (len % 2 === 0 && len >= 4 && len <= 14) {
        const cards = parseCards(line);
        if (cards) hands.push(line);
      }
    }
    return { hands, board, boardStreet };
  }

  function normalizeHands(hands, requiredCards, boardCards, allUsedCards) {
    const normalized = [];
    const usedSet = [...allUsedCards];
    for (const hand of hands) {
      const cards = parseCards(hand);
      if (!cards) continue;
      let result = [...cards];
      if (result.length > requiredCards) result = result.slice(0, requiredCards);
      while (result.length < requiredCards) {
        const dummy = getUnusedCard([...usedSet, ...result]);
        if (!dummy) { console.error('[AUTO] Cannot find unused card for padding'); return null; }
        result.push(dummy);
        usedSet.push(dummy);
      }
      if (result.length !== requiredCards) return null;
      normalized.push(result.map(c => c).join(''));
    }
    return normalized;
  }

  function updateStatus(state) {
    const el = document.getElementById("engine-flow-status");
    if (!el) return;
    el.textContent = `AUTO_FILL=${state.autoFill ? "ON" : "OFF"} | AUTO_FLOP=${state.autoRunFlop ? "ON" : "OFF"} | TURN=${state.manualTurnOnly ? "MANUAL" : "FREE"} | CLEAR_RIVER=${state.clearRiver ? "ON" : "OFF"}`;
  }

  function isEngineTabActive() {
    // Check if this page has the engine textarea (is the engine page)
    return document.querySelector('textarea[rows="14"]') !== null;
  }

  function ensureControls() {
    const existing = document.getElementById("engine-flow-controls");
    if (!isEngineTabActive()) {
      if (existing) existing.style.display = 'none';
      return null;
    }
    if (existing) {
      existing.style.display = '';
      return document.querySelector('textarea[rows="14"]') || null;
    }
    const textarea = document.querySelector('textarea[rows="14"]');
    if (!textarea) return null;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div id="engine-flow-controls" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px;font-size:12px;">
        <label><input type="checkbox" id="toggle-auto-fill"> Auto Fill</label>
        <label><input type="checkbox" id="toggle-auto-flop"> Auto Run Flop</label>
        <label><input type="checkbox" id="toggle-manual-turn"> Manual Turn Only</label>
        <label><input type="checkbox" id="toggle-clear-river"> Clear River</label>
        <span id="engine-flow-status" style="opacity:.8;"></span>
      </div>
    `;
    textarea.parentNode.insertBefore(wrap.firstElementChild, textarea);
    const state = loadState();
    document.getElementById("toggle-auto-fill").checked = state.autoFill;
    document.getElementById("toggle-auto-flop").checked = state.autoRunFlop;
    document.getElementById("toggle-manual-turn").checked = state.manualTurnOnly;
    document.getElementById("toggle-clear-river").checked = state.clearRiver;
    ["toggle-auto-fill", "toggle-auto-flop", "toggle-manual-turn", "toggle-clear-river"].forEach(id => {
      document.getElementById(id).addEventListener("change", () => {
        const newState = {
          autoFill: document.getElementById("toggle-auto-fill").checked,
          autoRunFlop: document.getElementById("toggle-auto-flop").checked,
          manualTurnOnly: document.getElementById("toggle-manual-turn").checked,
          clearRiver: document.getElementById("toggle-clear-river").checked
        };
        saveState(newState);
        updateStatus(newState);
      });
    });
    updateStatus(state);
    return textarea;
  }

  function findRunButton() {
    const buttons = [...document.querySelectorAll("button")];
    return buttons.find(b => /run.*engine/i.test((b.innerText || "").trim()));
  }

  async function maybeAutoRun(text, table_id, hand_id) {
    const state = loadState();
    if (!state.autoRunFlop || isRunning) return;
    const variant = getSelectedVariant();
    if (!variant) { console.log('[AUTO] Skip: no variant selected'); return; }
    const requiredCards = getRequiredCards(variant);
    if (!requiredCards) { console.log('[AUTO] Skip: unknown variant', variant); return; }
    const snapshot = parseSnapshot(text, requiredCards);
    if (!snapshot) return;
    const { hands, board, boardStreet } = snapshot;
    if (boardStreet === 'FLOP') {}
    else if (boardStreet === 'TURN') { if (state.manualTurnOnly) { console.log('[AUTO] Skip: TURN but manualTurnOnly ON'); return; } }
    else if (boardStreet === 'RIVER') { if (state.clearRiver) { console.log('[AUTO] Skip: RIVER but clearRiver ON'); return; } }
    else { console.log('[AUTO] Skip: no valid board (pre-flop)'); return; }
    if (hands.length < 2) { console.log('[AUTO] Skip: only', hands.length, 'hands'); return; }
    // Reset on new hand
    if (hand_id && hand_id !== lastHandId) {
      lastStateKey = null;
      lastHandId = hand_id;
      console.log('[AUTO] New hand detected:', hand_id);
    }
    const stateKey = (table_id || '?') + '|' + (hand_id || '?') + '|' + hands.join('|') + '||' + (board || '') + '||' + boardStreet;
    if (stateKey === lastStateKey) { console.log('[AUTO] Skip: same state'); return; }
    const boardCards = board ? parseCards(board) : [];
    const allUsedCards = [...boardCards];
    for (const h of hands) { const hc = parseCards(h); if (hc) allUsedCards.push(...hc); }
    if (hasDuplicates(allUsedCards)) { console.warn('[AUTO] Skip: duplicate cards'); return; }
    const normalizedHands = normalizeHands(hands, requiredCards, boardCards, allUsedCards);
    if (!normalizedHands) { console.warn('[AUTO] Skip: normalization failed'); return; }
    const payload = [...normalizedHands, board].join('\n');
    lastStateKey = stateKey;
    isRunning = true;
    try {
      console.log('[AUTO] ✓', boardStreet, 'board=' + board, '(' + normalizedHands.length + ' players, variant=' + variant + ')');
      const textarea = document.querySelector('textarea[rows="14"]');
      if (textarea) { setTextareaValue(textarea, payload); }
      const runBtn = findRunButton();
      if (runBtn) { runBtn.click(); console.log('[AUTO] ✓ Engine triggered'); }
      else { console.warn('[AUTO] Run button not found'); }
    } catch (e) { console.error('[AUTO] Engine run failed:', e); }
    finally { setTimeout(() => { isRunning = false; }, 3000); }
  }

  const HAND_LEN_TO_PLO = { 8: 'plo4', 10: 'plo5', 12: 'plo6', 14: 'plo7' };
  const PLO_VARIANTS = { 'plo4': [6, 8, 9], 'plo5': [5, 6, 8, 9], 'plo6': [5, 6, 8], 'plo7': [5, 6] };

  function detectAndSetVariant(text) {
    if (!text) return;
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return;
    const firstLen = lines[0].length;
    const ploType = HAND_LEN_TO_PLO[firstLen];
    if (!ploType) return;
    const handCount = lines.filter(l => l.length === firstLen).length;
    const available = PLO_VARIANTS[ploType];
    if (!available) return;
    let bestMax = available[available.length - 1];
    for (const mx of available) { if (mx >= handCount) { bestMax = mx; break; } }
    const targetVariant = ploType + '-' + bestMax + 'max';
    const sel = document.querySelector('select');
    if (!sel || sel.value === targetVariant) return;
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
    nativeSetter.call(sel, targetVariant);
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    console.log('[AUTO] Variant auto-detected:', targetVariant, '(' + handCount + ' hands, ' + (firstLen/2) + ' cards)');
  }

  function setTextareaValue(textarea, value) {
    if (!textarea) return;
    try {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeSetter.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) { console.error('[AUTO] Failed to set textarea value:', e); }
  }

  async function pollLatest() {
    if (!isPageVisible || !isEngineTabActive()) return;
    try {
      const textarea = ensureControls();
      if (!textarea) return;
      const state = loadState();
      const res = await fetch(BRIDGE_URL, { signal: AbortSignal.timeout(10000) });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (!data.ok || !data.table) return;
      const t = data.table;
      const text = formatTableDataToCanonical(t);
      if (!text || text === lastSnapshotHash) {
        if (t.hand_id && t.hand_id !== lastHandId) {
          // Hand ID changed but cards are identical — force re-fill
          lastSnapshotHash = null;
          lastHandId = t.hand_id;
          lastStateKey = null;
          console.log('[AUTO] Hand ID change detected (same cards):', t.hand_id);
        } else {
          return;
        }
      }
      lastSnapshotHash = text;
      lastDataChange = Date.now();
      consecutiveErrors = 0;
      if (state.autoFill && text) { detectAndSetVariant(text); setTextareaValue(textarea, text); }
      await maybeAutoRun(text, t.table_id, t.hand_id);
      adjustPollSpeed();
    } catch (err) {
      consecutiveErrors++;
      console.error('[AUTO] Poll failed (' + consecutiveErrors + '/' + MAX_CONSECUTIVE_ERRORS + '):', err.message);
      if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        console.error('[AUTO] Too many errors, stopping');
        stopPolling();
        setTimeout(() => { console.log('[AUTO] Attempting recovery...'); consecutiveErrors = 0; startAdaptivePolling(); }, ERROR_BACKOFF_MS);
      }
    }
  }

  function adjustPollSpeed() {
    const timeSinceChange = Date.now() - lastDataChange;
    const shouldBeIdle = timeSinceChange > IDLE_THRESHOLD;
    const targetInterval = shouldBeIdle ? SLOW_POLL : FAST_POLL;
    if (targetInterval !== currentInterval) {
      currentInterval = targetInterval;
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(pollLatest, currentInterval);
      console.log('[AUTO] Poll speed:', shouldBeIdle ? 'IDLE' : 'ACTIVE', '(' + currentInterval + 'ms)');
    }
  }

  function startAdaptivePolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollLatest, currentInterval);
    console.log('[AUTO] Polling started:', currentInterval + 'ms (fast=' + FAST_POLL + 'ms, slow=' + SLOW_POLL + 'ms)');
    pollLatest();
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; console.log('[AUTO] Polling stopped'); }
  }

  function handleVisibilityChange() {
    isPageVisible = !document.hidden;
    if (isPageVisible) { console.log('[AUTO] Page visible - resuming'); lastDataChange = Date.now(); adjustPollSpeed(); pollLatest(); }
    else { console.log('[AUTO] Page hidden - pausing'); }
  }

  var stalePanel = document.getElementById("engine-flow-panel");
  if (stalePanel) { stalePanel.remove(); console.log("[AUTO] Removed stale cached panel"); }

  function init() {
    console.log('[AUTO] Engine Flow Controls v' + VERSION);
    console.log('[AUTO] Bridge endpoint:', BRIDGE_URL);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    const checkInterval = setInterval(() => {
      if (ensureControls()) {
        clearInterval(checkInterval);
        console.log('[AUTO] Controls injected');
        startAdaptivePolling();
        console.log('[AUTO] Variant-aware trigger enabled');
      }
    }, 500);
    setTimeout(() => clearInterval(checkInterval), 30000);
  }

  window.engineFlowControls = {
    version: VERSION,
    pollLatest, maybeAutoRun, adjustPollSpeed,
    start: startAdaptivePolling,
    stop: stopPolling,
    state: () => ({ lastStateKey, lastDataChange: new Date(lastDataChange), currentInterval, isPageVisible, consecutiveErrors })
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

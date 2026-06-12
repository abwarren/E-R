(() => {
  'use strict';

  // ══════════════════════════════════════════════════════════════════════════
  // CONFIGURATION
  // ══════════════════════════════════════════════════════════════════════════

  const VERSION = '2.0.0-variant-aware';
  const STORAGE_KEY = "engineFlowToggles";

  const defaultState = {
    autoFill: true,
    autoRunFlop: true,
    manualTurnOnly: true,
    clearRiver: true
  };

  // Variant → cards per hand
  const VARIANT_CARDS = {
    'plo4': 4, 'plo5': 5, 'plo6': 6, 'plo7': 7
  };

  // Board lengths by street
  const BOARD_LENGTHS = { 6: 'FLOP', 8: 'TURN', 10: 'RIVER' };

  // Full deck for dummy card generation
  const RANKS = '23456789TJQKA';
  const SUITS = 'cdhs';
  const FULL_DECK = [];
  for (const r of RANKS) for (const s of SUITS) FULL_DECK.push(r + s);

  // Runtime state
  let lastStateKey = null;
  let lastSnapshotHash = null;
  let isRunning = false;

  // Adaptive polling
  const FAST_POLL = 1500;
  const SLOW_POLL = 5000;
  const IDLE_THRESHOLD = 30000;
  let lastDataChange = Date.now();
  let currentInterval = FAST_POLL;
  let pollTimer = null;

  // Error recovery
  let consecutiveErrors = 0;
  const MAX_CONSECUTIVE_ERRORS = 5;
  const ERROR_BACKOFF_MS = 5000;

  // Page visibility
  let isPageVisible = !document.hidden;

  // ══════════════════════════════════════════════════════════════════════════
  // STATE MANAGEMENT
  // ══════════════════════════════════════════════════════════════════════════

  function loadState() {
    try {
      return { ...defaultState, ...(JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}) };
    } catch {
      return { ...defaultState };
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      console.error('[AUTO] Failed to save state:', e);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // CARD HELPERS
  // ══════════════════════════════════════════════════════════════════════════

  function isValidCard(s) {
    if (s.length !== 2) return false;
    return RANKS.includes(s[0].toUpperCase()) && SUITS.includes(s[1].toLowerCase());
  }

  function parseCards(line) {
    // Parse "AhKhQdJd" → ["Ah","Kh","Qd","Jd"]
    const cards = [];
    for (let i = 0; i < line.length - 1; i += 2) {
      const c = line.substring(i, i + 2);
      if (isValidCard(c)) cards.push(c);
      else return null; // invalid card found
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

  // ══════════════════════════════════════════════════════════════════════════
  // VARIANT DETECTION
  // ══════════════════════════════════════════════════════════════════════════

  function getSelectedVariant() {
    // Read from the React <select> element in the Engine tab
    const sel = document.querySelector('select');
    if (!sel) return null;
    const val = sel.value; // e.g., "plo5-6max"
    return val || null;
  }

  function getRequiredCards(variant) {
    if (!variant) return null;
    // "plo5-6max" → "plo5" → 5
    const base = variant.split('-')[0]; // "plo5"
    return VARIANT_CARDS[base] || null;
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SNAPSHOT PARSER
  // ══════════════════════════════════════════════════════════════════════════

  function parseSnapshot(text, requiredCards) {
    if (!text) return null;

    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    const handLen = requiredCards * 2; // e.g., PLO5 → 10 chars
    const hands = [];
    let board = null;
    let boardStreet = null;

    for (const line of lines) {
      const len = line.length;

      // Check if this is a board line (6=flop, 8=turn, 10=river)
      if (BOARD_LENGTHS[len] && len !== handLen) {
        // It's a board length AND doesn't match hand length
        const cards = parseCards(line);
        if (cards) {
          board = line;
          boardStreet = BOARD_LENGTHS[len];
        }
      } else if (len === handLen) {
        // Matches expected hand length
        const cards = parseCards(line);
        if (cards) hands.push(line);
      } else if (len % 2 === 0 && len >= 4 && len <= 14) {
        // Some other even-length line — could be a short/long hand
        const cards = parseCards(line);
        if (cards) hands.push(line);
      }
      // else: skip non-card lines
    }

    return { hands, board, boardStreet };
  }

  // ══════════════════════════════════════════════════════════════════════════
  // TABLE JSON PARSER — converts /api/table/latest JSON → hands text
  // ══════════════════════════════════════════════════════════════════════════

  function parseTableToHands(tableData) {
    // tableData is the full API response: { ok, table: { seats, board, ... } }
    if (!tableData || !tableData.ok) return null;

    const table = tableData.table;
    if (!table) return null;

    const seats = table.seats || [];
    const lines = [];

    // Collect hands from all seats with hole_cards (backend already filters face-down to empty)
    for (const seat of seats) {
      const cards = seat.hole_cards || seat.cards || [];
      if (!cards.length) continue;

      // Join cards: ["Ah","Kh","Qd","Jd"] → "AhKhQdJd"
      const line = cards.join('');
      // Validate: must be even-length card string
      if (line.length < 4 || line.length % 2 !== 0) continue;

      lines.push(line);
    }

    // Build board line from board.cards or board.flop + board.turn + board.river
    if (table.board) {
      const boardCards = table.board.cards
        || [].concat(table.board.flop || [], table.board.turn || [], table.board.river || [])
        .filter(Boolean);

      if (boardCards.length > 0) {
        lines.push(boardCards.join(''));
      }
    }

    if (lines.length === 0) return null;

    return {
      text: lines.join('\n'),
      hands: lines.slice(0, -1), // all but last (board)
      board: lines[lines.length - 1], // last line
      boardLength: table.board ? (table.board.cards || [].concat(table.board.flop||[],table.board.turn||[],table.board.river||[]).filter(Boolean)).length : 0
    };
  }

  // ══════════════════════════════════════════════════════════════════════════
  // HAND PADDING / TRIMMING
  // ══════════════════════════════════════════════════════════════════════════

  function normalizeHands(hands, requiredCards, boardCards, allUsedCards) {
    const normalized = [];
    const usedSet = [...allUsedCards];

    for (const hand of hands) {
      const cards = parseCards(hand);
      if (!cards) continue;

      let result = [...cards];

      // Trim if too many cards
      if (result.length > requiredCards) {
        result = result.slice(0, requiredCards);
      }

      // Pad if too few cards
      while (result.length < requiredCards) {
        const dummy = getUnusedCard([...usedSet, ...result]);
        if (!dummy) {
          console.error('[AUTO] Cannot find unused card for padding');
          return null;
        }
        result.push(dummy);
        usedSet.push(dummy);
      }

      if (result.length !== requiredCards) return null;
      normalized.push(result.map(c => c).join(''));
    }

    return normalized;
  }

  // ══════════════════════════════════════════════════════════════════════════
  // UI CONTROLS
  // ══════════════════════════════════════════════════════════════════════════

  function updateStatus(state) {
    const el = document.getElementById("engine-flow-status");
    if (!el) return;
    el.textContent =
      `AUTO_FILL=${state.autoFill ? "ON" : "OFF"} | ` +
      `AUTO_FLOP=${state.autoRunFlop ? "ON" : "OFF"} | ` +
      `TURN=${state.manualTurnOnly ? "MANUAL" : "FREE"} | ` +
      `CLEAR_RIVER=${state.clearRiver ? "ON" : "OFF"}`;
  }

  function isEngineTabActive() {
    const activeTab = document.querySelector('.tab-btn.active');
    return activeTab && /engine/i.test(activeTab.textContent);
  }

  function ensureControls() {
    const existing = document.getElementById("engine-flow-controls");

    // Hide controls when not on Engine tab
    if (!isEngineTabActive()) {
      if (existing) existing.style.display = 'none';
      return null;
    }

    // Show controls if Engine tab is active and they exist
    if (existing) {
      existing.style.display = '';
      const textarea = document.querySelector('textarea[rows="14"]');
      return textarea || null;
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

  // ══════════════════════════════════════════════════════════════════════════
  // SMART TRIGGER
  // ══════════════════════════════════════════════════════════════════════════

  function findRunButton() {
    const buttons = [...document.querySelectorAll("button")];
    return buttons.find(b => /run.*engine/i.test((b.innerText || "").trim()));
  }

  async function maybeAutoRun(text) {
    const state = loadState();
    if (!state.autoRunFlop) return;
    if (isRunning) return;

    // Read selected variant from the UI
    const variant = getSelectedVariant();
    if (!variant) {
      console.log('[AUTO] Skip: no variant selected');
      return;
    }

    const requiredCards = getRequiredCards(variant);
    if (!requiredCards) {
      console.log(`[AUTO] Skip: unknown variant ${variant}`);
      return;
    }

    // Parse the snapshot
    const snapshot = parseSnapshot(text, requiredCards);
    if (!snapshot) return;

    const { hands, board, boardStreet } = snapshot;

    // ── Street-based trigger logic ──

    // FLOP: always auto-trigger
    if (boardStreet === 'FLOP') {
      // ok, proceed
    }
    // TURN: respect manualTurnOnly setting
    else if (boardStreet === 'TURN') {
      if (state.manualTurnOnly) {
        console.log('[AUTO] Skip: TURN detected but manualTurnOnly is ON');
        return;
      }
    }
    // RIVER: respect clearRiver setting
    else if (boardStreet === 'RIVER') {
      if (state.clearRiver) {
        console.log('[AUTO] Skip: RIVER detected, clearRiver is ON');
        return;
      }
    }
    // No board or pre-flop
    else {
      console.log('[AUTO] Skip: no valid board detected (pre-flop or invalid)');
      return;
    }

    // ── Player count validation ──
    if (hands.length < 2) {
      console.log(`[AUTO] Skip: only ${hands.length} hands (need ≥2)`);
      return;
    }

    // ── Anti-spam: unique state key ──
    const stateKey = hands.join('|') + '||' + (board || '') + '||' + boardStreet;
    if (stateKey === lastStateKey) {
      console.log(`[AUTO] Skip: same state already processed`);
      return;
    }

    // ── Validate + normalize hands ──
    const boardCards = board ? parseCards(board) : [];
    const allUsedCards = [...boardCards];
    for (const h of hands) {
      const hc = parseCards(h);
      if (hc) allUsedCards.push(...hc);
    }

    // Check for duplicate cards across all hands + board
    if (hasDuplicates(allUsedCards)) {
      console.warn('[AUTO] Skip: duplicate cards detected in snapshot');
      return;
    }

    // Normalize hand lengths (pad/trim to match variant)
    const normalizedHands = normalizeHands(hands, requiredCards, boardCards, allUsedCards);
    if (!normalizedHands) {
      console.warn('[AUTO] Skip: failed to normalize hands');
      return;
    }

    // ── Build payload and fill textarea ──
    // Payload: normalized hands (one per line) + board on last line
    const payload = [...normalizedHands, board].join('\n');

    lastStateKey = stateKey;
    isRunning = true;

    try {
      console.log(`[AUTO] ✓ ${boardStreet}: board="${board}" (${normalizedHands.length} players, variant=${variant})`);

      // Fill the textarea with the normalized payload
      const textarea = document.querySelector('textarea[rows="14"]');
      if (textarea) {
        setTextareaValue(textarea, payload);
      }

      // Click run — defer by one frame so React 18 batches flush
      // the textarea/variant state before the button reads them.
      requestAnimationFrame(() => {
        const runBtn = findRunButton();
        if (runBtn) {
          runBtn.click();
          console.log('[AUTO] ✓ Engine triggered');
        } else {
          console.warn("[AUTO] Run button not found");
        }
      });
    } catch (e) {
      console.error("[AUTO] Engine run failed:", e);
    } finally {
      setTimeout(() => { isRunning = false; }, 3000);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // VARIANT AUTO-DETECTION
  // ══════════════════════════════════════════════════════════════════════════

  // Hand char length → PLO type
  const HAND_LEN_TO_PLO = { 8: 'plo4', 10: 'plo5', 12: 'plo6', 14: 'plo7' };

  // PLO type → available max-player variants (sorted ascending)
  const PLO_VARIANTS = {
    'plo4': [6, 8, 9],
    'plo5': [5, 6, 8, 9],
    'plo6': [5, 6, 8],
    'plo7': [5, 6],
  };

  function detectAndSetVariant(text) {
    if (!text) return;
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return;

    // Find first hand line (skip board lines: 6/8/10 chars that aren't hand-length)
    // Hands are the majority of lines; detect from first line
    const firstLen = lines[0].length;
    const ploType = HAND_LEN_TO_PLO[firstLen];
    if (!ploType) return;

    // Count hand lines (same length as first line)
    const handCount = lines.filter(l => l.length === firstLen).length;

    // Pick best variant: smallest max that fits handCount, or largest available
    const available = PLO_VARIANTS[ploType];
    if (!available) return;
    let bestMax = available[available.length - 1]; // default to largest
    for (const mx of available) {
      if (mx >= handCount) { bestMax = mx; break; }
    }

    const targetVariant = `${ploType}-${bestMax}max`;
    const sel = document.querySelector('select');
    if (!sel || sel.value === targetVariant) return;

    // Set dropdown via React-compatible method
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLSelectElement.prototype, 'value'
    ).set;
    nativeSetter.call(sel, targetVariant);
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    console.log(`[AUTO] Variant auto-detected: ${targetVariant} (${handCount} hands, ${firstLen/2} cards)`);
  }

  // ══════════════════════════════════════════════════════════════════════════
  // DOM MANIPULATION
  // ══════════════════════════════════════════════════════════════════════════

  function setTextareaValue(textarea, value) {
    if (!textarea) return;
    // Anti-flicker: skip if DOM already holds this value
    if (textarea.value === value) return;
    try {
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        "value"
      ).set;
      nativeSetter.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) {
      console.error('[AUTO] Failed to set textarea value:', e);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // POLLING
  // ══════════════════════════════════════════════════════════════════════════

  async function pollLatest() {
    if (!isPageVisible) return;

    // Only run when Engine tab is active
    if (!isEngineTabActive()) return;

    try {
      const textarea = ensureControls();
      if (!textarea) return;

      const state = loadState();
      const res = await fetch("/api/table/latest", {
        signal: AbortSignal.timeout(10000)
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      if (!data.ok) return;

      // Parse /api/table/latest JSON into hands text format
      const parsed = parseTableToHands(data);
      if (!parsed) return;

      const text = parsed.text;
      if (text === lastSnapshotHash) return;

      lastSnapshotHash = text;
      lastDataChange = Date.now();
      consecutiveErrors = 0;

      if (state.autoFill && text) {
        detectAndSetVariant(text);
        setTextareaValue(textarea, text);
      }

      await maybeAutoRun(text);
      adjustPollSpeed();

    } catch (err) {
      consecutiveErrors++;
      console.error(`[AUTO] Poll failed (${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS}):`, err.message);

      if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        console.error('[AUTO] Too many errors, stopping');
        stopPolling();
        setTimeout(() => {
          console.log('[AUTO] Attempting recovery...');
          consecutiveErrors = 0;
          startAdaptivePolling();
        }, ERROR_BACKOFF_MS);
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ADAPTIVE POLLING
  // ══════════════════════════════════════════════════════════════════════════

  function adjustPollSpeed() {
    const timeSinceChange = Date.now() - lastDataChange;
    const shouldBeIdle = timeSinceChange > IDLE_THRESHOLD;
    const targetInterval = shouldBeIdle ? SLOW_POLL : FAST_POLL;

    if (targetInterval !== currentInterval) {
      currentInterval = targetInterval;
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(pollLatest, currentInterval);
      console.log(`[AUTO] Poll speed: ${shouldBeIdle ? 'IDLE' : 'ACTIVE'} (${currentInterval}ms)`);
    }
  }

  function startAdaptivePolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollLatest, currentInterval);
    console.log(`[AUTO] Polling started: ${currentInterval}ms (fast=${FAST_POLL}ms, slow=${SLOW_POLL}ms)`);
    pollLatest();
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
      console.log('[AUTO] Polling stopped');
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // PAGE VISIBILITY
  // ══════════════════════════════════════════════════════════════════════════

  function handleVisibilityChange() {
    isPageVisible = !document.hidden;
    if (isPageVisible) {
      console.log('[AUTO] Page visible - resuming');
      lastDataChange = Date.now();
      adjustPollSpeed();
      pollLatest();
    } else {
      console.log('[AUTO] Page hidden - pausing');
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // INITIALIZATION
  // ══════════════════════════════════════════════════════════════════════════

  // Remove stale cached floating panel if it exists
  var stalePanel = document.getElementById("engine-flow-panel");
  if (stalePanel) { stalePanel.remove(); console.log("[AUTO] Removed stale cached panel"); }

  function init() {
    console.log(`[AUTO] Engine Flow Controls v${VERSION}`);
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

  // Export API
  window.engineFlowControls = {
    version: VERSION,
    pollLatest,
    maybeAutoRun,
    adjustPollSpeed,
    start: startAdaptivePolling,
    stop: stopPolling,
    state: () => ({
      lastStateKey,
      lastDataChange: new Date(lastDataChange),
      currentInterval,
      isPageVisible,
      consecutiveErrors
    })
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

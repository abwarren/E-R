(() => {
  'use strict';

  // ══════════════════════════════════════════════════════════════════════════
  // CONFIGURATION
  // ══════════════════════════════════════════════════════════════════════════

  const VERSION = '1.0.0-adaptive';
  const STORAGE_KEY = "engineFlowToggles";

  const defaultState = {
    autoFill: true,
    autoRunFlop: true,
    manualTurnOnly: true,
    clearRiver: true
  };

  // Runtime state
  let lastFlop = null;
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
  // PARSERS
  // ══════════════════════════════════════════════════════════════════════════

  function extractFlop(text) {
    if (!text) return null;
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    for (const line of lines) {
      if (line.length === 6) return line;
    }
    return null;
  }

  function extractPlayers(text) {
    if (!text) return [];
    return text
      .split("\n")
      .map(l => l.trim())
      .filter(l => l.length >= 8 && l.length <= 14 && l.length % 2 === 0);
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

  function ensureControls() {
    const textarea = document.querySelector('textarea[rows="14"]');
    if (!textarea) return null;
    if (document.getElementById("engine-flow-controls")) return textarea;

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
    return buttons.find(b => /run|calculate|eval|equity/i.test((b.innerText || "").trim()));
  }

  async function maybeAutoRun(text) {
    const state = loadState();
    if (!state.autoRunFlop) return;
    if (isRunning) return;

    const players = extractPlayers(text);
    const flop = extractFlop(text);

    if (players.length < 6) {
      console.log(`[AUTO] Skip: only ${players.length} players (need ≥6)`);
      return;
    }
    if (!flop) return;
    if (flop === lastFlop) {
      console.log(`[AUTO] Skip: flop "${flop}" already processed`);
      return;
    }

    lastFlop = flop;
    isRunning = true;

    try {
      console.log(`[AUTO] ✓ NEW FLOP: "${flop}" (${players.length} players)`);
      const runBtn = findRunButton();
      if (runBtn) runBtn.click();
      else console.warn("[AUTO] Run button not found");
    } catch (e) {
      console.error("[AUTO] Engine run failed:", e);
    } finally {
      setTimeout(() => { isRunning = false; }, 1000);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // DOM MANIPULATION
  // ══════════════════════════════════════════════════════════════════════════

  function setTextareaValue(textarea, value) {
    if (!textarea) return;
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


  // Tab detection - only operate on ENGINE tab
  function isEngineTabActive() {
    const tabs = document.querySelectorAll("button");
    for (const tab of tabs) {
      const text = (tab.textContent || "").trim().toUpperCase();
      if (text === "ENGINE" || text.startsWith("ENGINE")) {
        const style = window.getComputedStyle(tab);
        // Active tab typically has colored text or border
        const color = style.color;
        // Check if this tab looks "active" (not the default dim color)
        if (color && color !== "rgb(148, 163, 184)" && color !== "rgba(148, 163, 184, 1)") {
          return true;
        }
      }
    }
    // Fallback: check if the ENGINE tab text area is labeled with engine-flow-controls
    return document.getElementById("engine-flow-controls") !== null &&
           document.querySelector("textarea[rows="14"]") !== null;
  }

  // ══════════════════════════════════════════════════════════════════════════
  // POLLING
  // ══════════════════════════════════════════════════════════════════════════

  async function pollLatest() {
    if (!isPageVisible) return;
    if (!isEngineTabActive()) return;

    try {
      const textarea = ensureControls();
      if (!textarea) return;

      const state = loadState();
      const res = await fetch("/api/collector/latest", {
        credentials: "include",
        signal: AbortSignal.timeout(10000)
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      if (!data.ok) return;

      const text = data.raw || "";
      if (text === lastSnapshotHash) return;

      lastSnapshotHash = text;
      lastDataChange = Date.now();
      consecutiveErrors = 0;

      if (state.autoFill && text) {
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

  function init() {
    console.log(`[AUTO] Engine Flow Controls v${VERSION}`);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    const checkInterval = setInterval(() => {
      if (ensureControls()) {
        clearInterval(checkInterval);
        console.log('[AUTO] Controls injected');
        startAdaptivePolling();
        console.log('[AUTO] Smart trigger enabled: auto-run on flop (≥6 players)');
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
      lastFlop,
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

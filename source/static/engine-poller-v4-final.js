(() => {
  let pollMs = 1500;
  let timer = null;

  const STORAGE_KEY = "engineFlowToggles";

  const runtime = {
    lastRawBatch: "",
    lastFlop: null,
    lastRiver: null,
    errorCount: 0
  };

  function isEngineTabActive() {
    var allBtns = document.querySelectorAll("button");
    for (var i = 0; i < allBtns.length; i++) {
      var txt = (allBtns[i].textContent || "").trim().toUpperCase();
      if (txt !== "ENGINE") continue;
      var cls = (allBtns[i].className || "").toLowerCase();
      var ariaSelected = allBtns[i].getAttribute("aria-selected");
      var cs = window.getComputedStyle(allBtns[i]);
      var bc = cs.borderBottomColor || "";
      var hasBorder = bc && bc !== "rgba(0, 0, 0, 0)" && bc !== "transparent";
      var hasActive = cls.indexOf("active") >= 0 || cls.indexOf("selected") >= 0;
      if (hasActive || ariaSelected === "true" || hasBorder) return true;
    }
    var ta = document.querySelector('textarea[rows="14"]');
    return ta && ta.offsetParent !== null;
  }

  function getToggles() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch { return {}; }
  }

  function streetOf(board) {
    if (!board) return "PREFLOP";
    let total = (board.flop || []).length;
    if (board.turn) total += 1;
    if (board.river) total += 1;
    if (total === 3) return "FLOP";
    if (total === 4) return "TURN";
    if (total >= 5) return "RIVER";
    return "PREFLOP";
  }

  function extractFlop(board) {
    if (!board || !board.flop || board.flop.length !== 3) return null;
    return board.flop.slice().sort().join("");
  }

  function clickRunButton() {
    const btn = document.querySelector("button");
    if (btn && btn.textContent.includes("Run")) {
      console.log("[POLLER] AUTO-CLICKING Run button");
      btn.click();
    }
  }

  function setTextareaValue(textarea, value) {
    if (!textarea) return;
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, "value"
    ).set;
    nativeSetter.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function pollLatest() {
    if (!isEngineTabActive()) {
      clearTimeout(timer);
      timer = setTimeout(pollLatest, 3000);
      return;
    }

    const toggles = getToggles();

    try {
      const [tableRes, collectorRes] = await Promise.all([
        fetch("/api/table/latest", { credentials: "include", cache: "no-store" }),
        fetch("/api/collector/latest", { credentials: "include", cache: "no-store" })
      ]);

      if (!tableRes.ok || !collectorRes.ok) {
        runtime.errorCount++;
        console.warn("[POLLER] Fetch error (" + runtime.errorCount + ")");
        return;
      }

      const tableJson = await tableRes.json();
      const collectorJson = await collectorRes.json();

      const table = tableJson?.table;
      const board = table?.board;
      const street = streetOf(board);

      // Build rawBatch from collector response:
      //   collectorJson.raw  = hand lines (newline-separated)
      //   collectorJson.board = board string (e.g. "ThQc8h")
      // Engine textarea expects: hands (one per line), no aggregation needed
      let rawBatch = "";
      if (collectorJson?.ok && collectorJson.raw) {
        rawBatch = collectorJson.raw;
        if (collectorJson.board) {
          rawBatch += "\n" + collectorJson.board;
        }
      }
      // Fallback: try table-level batch fields
      if (!rawBatch) {
        rawBatch = table?.raw_batch || table?.collector_batch || "";
      }

      const hasPlayers = (table?.seats || []).some(s => s?.name);
      const hasCards = board && (board.flop?.length > 0 || board.turn || board.river);
      const isActive = hasPlayers || hasCards;

      const textarea = document.querySelector('textarea[rows="14"]');
      if (textarea && rawBatch && toggles.autoFill) {
        setTextareaValue(textarea, rawBatch);
        console.log("[POLLER] Filled textarea: " + rawBatch.split("\n").length + " lines");
      }

      if (street === "FLOP") {
        const currentFlop = extractFlop(board);
        if (currentFlop && currentFlop !== runtime.lastFlop) {
          console.log("[POLLER] NEW FLOP detected: " + currentFlop);
          runtime.lastFlop = currentFlop;
          if (toggles.autoRunFlop) {
            clickRunButton();
          }
        }
        pollMs = 1000;
      } else if (street === "TURN") {
        pollMs = 1500;
      } else if (street === "RIVER") {
        const currentRiver = board?.river || null;
        if (currentRiver && currentRiver !== runtime.lastRiver) {
          console.log("[POLLER] RIVER detected: " + currentRiver + " - RESETTING");
          runtime.lastRiver = currentRiver;
          runtime.lastFlop = null;
          if (textarea && toggles.clearRiver) {
            setTextareaValue(textarea, "");
          }
        }
        pollMs = 2000;
      } else {
        pollMs = isActive ? 2000 : 4000;
      }

      runtime.errorCount = 0;
      runtime.lastRawBatch = rawBatch;

    } catch (err) {
      runtime.errorCount++;
      console.error("[POLLER] Error (" + runtime.errorCount + "):", err);
      pollMs = Math.min(5000, 1500 + runtime.errorCount * 500);
    } finally {
      clearTimeout(timer);
      timer = setTimeout(pollLatest, pollMs);
    }
  }

  console.log("[POLLER] V5 smart polling started (reads collector raw+board correctly)");
  pollLatest();
})();

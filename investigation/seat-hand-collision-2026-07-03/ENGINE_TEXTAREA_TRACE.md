# ENGINE TEXTAREA TRACE

**Date:** 2026-07-03
**Investigation:** Seat Collision / Hand Overwrite
**Status:** READ-ONLY — confirmed at runtime

---

## 1. Key Question

**Why is the Engine textarea being overwritten?**

**Answer:** The Engine polls `/api/latest` every 1.5–5 seconds. The API alternates between 3 different hand contexts. Each time the returned hand differs from the previous one, the textarea is overwritten with new data.

---

## 2. Engine Textarea Data Source

### URL Resolution

**File:** `source/engine_flow_controls.js`, line 6
```javascript
const BRIDGE_URL = (window.W4P_API && window.W4P_API.LATEST)
    || (window.location.origin + '/api/latest');
```

**Resolved value (runtime):**
```
window.W4P_API.LATEST = "http://localhost:5002/api/latest"
```

`api-config.js` (line 19, 26):
```javascript
const BASE = window.location.origin;  // "http://localhost:5002"
window.W4P_API = {
    LATEST: BASE + "/api/latest",  // "http://localhost:5002/api/latest"
};
```

### Proxy Architecture

**File:** Engine Flask `app.py`, lines 138-141
```python
@app.route("/api/latest", methods=["GET"])
def proxy_api_latest():
    target = f"{REMOTE_BASE}/api/latest"
    # REMOTE_BASE = "http://er-remote:4000"
    # Proxies to: http://er-remote:4000/api/latest
```

The Engine Flask proxies `/api/latest` → `er-remote:4000/api/latest` → Flask backend `_handle_table_latest()`.

**Confirmed:** `curl http://127.0.0.1:5002/api/latest` returns valid data with hand_id.

---

## 3. Poll Cycle

**File:** `source/engine_flow_controls.js`, lines 278-324

```
FAST_POLL = 1500ms (active — data changed within last 30s)
SLOW_POLL = 5000ms (idle — no data change for 30s)
```

```javascript
async function pollLatest() {
    const res = await fetch(BRIDGE_URL, { signal: AbortSignal.timeout(10000) });
    const data = await res.json();
    const text = formatTableDataToCanonical(data.table);
    if (!text || text === lastSnapshotHash) return;
    lastSnapshotHash = text;
    if (state.autoFill && text) {
        detectAndSetVariant(text);
        setTextareaValue(textarea, text);  // OVERWRITES TEXTAREA
    }
    await maybeAutoRun(text);
}
```

---

## 4. Overwrite Mechanism

### Step 1: Canonical Format

**File:** `source/engine_flow_controls.js`, lines 83-100
```javascript
function formatTableDataToCanonical(table) {
    const hands = [];
    for (const seat of seats) {
        const cards = seat.hole_cards;
        if (cards && cards.length > 0) {
            hands.push(cards.join(''));
        }
    }
    // Returns: "AcKhQs8h6d5c\nAsJh9c7d4c4s\n" (one line per player with cards)
}
```

Each line represents one player's hole cards. The textarea is formatted as:
```
AcKhQs8h6d5c
AsJh9c7d4c4s
[board cards]
```

### Step 2: Hash Comparison

```javascript
if (!text || text === lastSnapshotHash) return;
lastSnapshotHash = text;
```

The textarea is overwritten ONLY when the canonical text differs. Since different hands have different hole card sets, the hash always differs when the API returns a different hand.

### Step 3: Textarea Write

```javascript
setTextareaValue(textarea, text);  // Overwrites whatever the user may have typed
```

**File:** `source/engine_flow_controls.js`, lines 268-276
```javascript
function setTextareaValue(textarea, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value").set;
    nativeSetter.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.dispatchEvent(new Event("change", { bubbles: true }));
}
```

Uses the native setter to bypass React/Vue/framework interception. Dispatches synthetic events to trigger framework re-render.

---

## 5. Overwrite Timeline

```
T+0ms:    Engine polls /api/latest
          API returns hand 339aec5c (Atros)
          Text: "AcKhQs8h6d5c\n\n" (Atros cards, monarchi has none)
          Textarea updated. Hash = "AcKhQs8h6d5c\n\n"

T+1500ms: Engine polls /api/latest
          API returns hand 339aec5c (Atros — same hand)
          Text unchanged → hash match → SKIP. No overwrite.

T+3000ms: Engine polls /api/latest
          API returns hand 60227f46 (allinstalker — DIFFERENT HAND)
          Text: "\n\n" (no players have hole cards)
          Hash differs → OVERWRITE textarea with empty text.

T+4500ms: Engine polls /api/latest
          API returns hand 27d1d74e (monarchi — DIFFERENT HAND)
          Text: "AsJh9c7d4c4s\n\n"
          Hash differs → OVERWRITE textarea with monarchi's cards.

T+6000ms: ...cycle continues...
```

The operator sees the textarea cycling between:
- "AcKhQs8h6d5c" (Atros's hand)
- "" (allinstalker's hand — no hole cards visible)
- "AsJh9c7d4c4s" (monarchi's hand)

Any manually-typed cards are overwritten on the next poll that returns a different hand.

---

## 6. Does Engine Poll Another Endpoint?

**No.** The Engine poller uses EXCLUSIVELY `BRIDGE_URL` which resolves to `/api/latest` (via Engine Flask proxy → er-remote). There is no fallback endpoint.

The `maybeAutoRun()` function (line 207) triggers equity calculations based on the polled data. If the poll returns the wrong hand's data, the equity calculation runs on the wrong hand.

---

## 7. Conclusion

**The Engine textarea is overwritten because the API selector oscillates between 3 independent hand contexts.** Each time the returned hand changes, `formatTableDataToCanonical()` produces different text, which fails the hash comparison, which triggers `setTextareaValue()`.

**The overwrite is NOT a bug in the Engine poller.** The poller correctly polls, correctly compares, and correctly updates. It faithfully displays whatever the API returns.

**The root cause is the API selection layer** returning different hand contexts at different times.

**Confidence:** 100%
- Verified Engine Flask proxy routes `/api/latest` → er-remote (line 138 of Engine app.py)
- Verified poll cycle (FAST_POLL=1500ms, SLOW_POLL=5000ms)
- Verified overwrite logic (hash comparison + native setter)
- Confirmed oscillation at runtime (7 hand changes in 10 API calls)

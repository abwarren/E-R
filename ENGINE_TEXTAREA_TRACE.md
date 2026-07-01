# ENGINE_TEXTAREA_TRACE.md — W4P Engine Textarea Investigation

**Date:** 2026-07-01
**Investigator:** Hermes Agent
**Conclusion:** ROOT CAUSE IDENTIFIED — NO CODE CHANGES MADE

---

## 1. Architecture Context

```
GoldRush Poker → Chrome Extension (w4p.js) → POST /api/snapshot → Express (:4000) → Flask (:1080)
                                                                                           ↓
                                                                                    table_state (SSOT)
                                                                                           ↓
                                                                                    GET /api/latest
                                                                                    GET /api/table/latest
                                                                                    GET /api/collector/latest
                                                                                    ↓
                                            ┌───────────────────────────────────────┼─────────────────┐
                                            │                                       │                  │
                                    Remote UI (:4000)                        Engine UI (:5002)
                                    ✅ Working                               ❌ Textarea empty
```

**Two containers:**
- `er-remote` (port 4000): Express proxy + Flask backend — serves `/api/table/latest`, `/api/latest`, Remote UI
- `er-engine` (port 5002): Flask equity engine app — serves React SPA, DOES NOT serve `/api/table/latest`

---

## 2. Phase 1: `/api/table/latest` Endpoint Verification

### Correct endpoint (port 4000) — ✅ WORKS
```
URL: http://localhost:4000/api/table/latest
Response: {"ok":true,"table":{"table_id":"waiting","street":"WAITING","seats":[...9 seats...]}}
```
Returns valid JSON with table state. When a live game runs, seats contain `hole_cards` and board data.

### Engine container endpoint (port 5002) — ❌ 404
```
URL: http://localhost:5002/api/table/latest
Response: 404 Not Found
```
The er-engine Flask app (`/app/app.py`) has **zero routes matching `/api/table/*`**. Grep result: empty.

---

## 3. Phase 2: How Engine Retrieves Data

### Scripts loaded by the Engine page
The Engine page (`engine-index.html` in container) loads:
1. `index-Ddit1nUd.js` — React SPA bundle
2. `engine_flow_controls.js?v=1779696136` — Flow controls + polling v2.0.0

**NOT loaded** (present in container but not referenced by HTML):
- `engine-poller-v4-final.js` — also uses `/api/table/latest` relative URL
- `engine_flow_controls_goldrush.js` — uses `/api/collector/latest` relative URL
- `api-config.js` — NOT EVEN PRESENT in the container at `/app/static/`

### Polling implementation
**File:** `/app/static/engine_flow_controls.js` (v2.0.0-variant-aware)
**Polling method:** `setInterval(pollLatest, currentInterval)` with adaptive speed (1500ms active, 5000ms idle)
**API call:**
```javascript
// Line ~229 (approximate — inside pollLatest() function)
const res = await fetch("/api/table/latest", {
    signal: AbortSignal.timeout(10000)
});
```
Relative URL resolves to `http://localhost:5002/api/table/latest` → **HTTP 404**

---

## 4. Phase 3: Data Flow Trace

### Intended flow:
```
pollLatest() → fetch("/api/table/latest") → parseTableToHands(data) → setTextareaValue(textarea, text)
                                   ↓ if autoFill=true + text non-empty
```

### Actual flow:
```
pollLatest() → fetch("/api/table/latest") → HTTP 404 → throw Error → consecutiveErrors++ 
                                                                        ↓
                                                              [after 5 errors] stopPolling()
                                                                        ↓
                                                              [after 5s] restartPolling() → 404 → ∞ loop
```

### Console evidence (real output):
```
[AUTO] Engine Flow Controls v2.0.0-variant-aware
[AUTO] Controls injected
[AUTO] Polling started: 1500ms (fast=1500ms, slow=5000ms)
[AUTO] Poll failed (1/5): HTTP 404
[AUTO] Poll failed (2/5): HTTP 404
[AUTO] Poll failed (3/5): HTTP 404
[AUTO] Poll failed (4/5): HTTP 404
[AUTO] Poll failed (5/5): HTTP 404
[AUTO] Too many errors, stopping
[AUTO] Polling stopped
[AUTO] Attempting recovery...
[AUTO] Polling started: 1500ms (fast=1500ms, slow=5000ms)
[AUTO] Poll failed (1/5): HTTP 404
... (repeats indefinitely)
```

### Functions that would write the textarea (if data arrived):
1. `pollLatest()` → `setTextareaValue(textarea, text)` — line ~240
2. `maybeAutoRun()` → `setTextareaValue(textarea, payload)` — line ~290
3. `setTextareaValue()` — line ~350 (uses native HTMLTextAreaElement value setter)

**All three are dead code — never reached because the fetch 404s.**

---

## 5. Phase 4: Textarea Verification

**XPath:** `/html/body/div/div/main/div/div[1]/div[2]/div[2]/textarea`
**Query:** `document.querySelector('textarea[rows="14"]')`
**Exists:** ✅ Yes (when Engine tab active)
**Value:** Placeholder text ("AhKhQdJd9s...") — never updated by poller
**Current state:** Empty of live data (only contains default placeholder from React)

---

## 6. Phase 5: All Writers

All textarea writes go through a single function:

| File | Function | Line (approx) | Method |
|------|----------|---------------|--------|
| `/app/static/engine_flow_controls.js` | `setTextareaValue()` | ~350 | Native `HTMLTextAreaElement.value` setter |
| `/app/static/engine_flow_controls.js` | `pollLatest()` | ~240 | Calls `setTextareaValue(textarea, text)` |
| `/app/static/engine_flow_controls.js` | `maybeAutoRun()` | ~290 | Calls `setTextareaValue(textarea, payload)` |

No other file writes to this textarea. The `engine-poller-v4-final.js` has the same pattern but is **not loaded**.

---

## 7. Phase 6: Failure Point Determination

| Hypothesis | Result | Evidence |
|-----------|--------|----------|
| Textarea not found | ❌ FALSE | Exists when Engine tab active |
| Polling never starts | ❌ FALSE | Console shows "Polling started" |
| `/api/table/latest` request fails | ✅ **TRUE** | Console: "HTTP 404" × 300+ occurrences |
| JSON parsing fails | N/A | Never reached — fetch throws before parsing |
| Formatter returns empty | N/A | Never reached |
| Writer never executes | ✅ TRUE | Blocked by HTTP 404 |
| Writer executes but wrong textarea | N/A | Only one textarea on page |
| Writer executes then overwritten | N/A | Never executes |

**Answer: Option 3 — "/api/table/latest request fails" (HTTP 404)**

---

## 8. Root Cause

### Exactly one line of code where valid data stops flowing:

**File:** `/app/static/engine_flow_controls.js`
**Function:** `pollLatest()`
**Line:** The `fetch("/api/table/latest")` call (line ~229)
**Failure:** HTTP 404 — endpoint does not exist on port 5002

### Why:
The Engine page is served from `er-engine` (port 5002). The poller uses a **relative URL** `"/api/table/latest"`, which resolves to `http://localhost:5002/api/table/latest`. The er-engine Flask app does not have this route. The route lives on `er-remote` (port 4000).

The Remote UI works because it is also served from port 4000, so `"/api/table/latest"` correctly resolves to `localhost:4000/api/table/latest`.

### Contributing factors:
1. `api-config.js` exists in source (`backend/static/api-config.js`) but is **not deployed** to the er-engine container
2. Even if deployed, `api-config.js` uses `window.location.origin` as BASE, so it would also resolve to port 5002 — same bug
3. `engine-poller-v4-final.js` is present in the container but **not loaded** by the HTML page (would also 404)
4. `engine_flow_controls_goldrush.js` uses `/api/collector/latest` — same 404 pattern

---

## 9. Proposed Fix (not implemented)

The fix must make the Engine poller call the correct server (port 4000). Options:

**Option A: Hardcode cross-origin URL (simplest)**
```javascript
// In engine_flow_controls.js, change fetch URL:
const res = await fetch("http://localhost:4000/api/table/latest", {
    signal: AbortSignal.timeout(10000)
});
```
Drawback: Fragile, breaks if port changes.

**Option B: Reverse proxy in er-engine Flask**
Add a route in `/app/app.py` that proxies `/api/table/*` to `http://er-remote:4000`. The containers are on the same Docker network so `er-remote:4000` resolves.

**Option C: Deploy `api-config.js` with correct BASE**
Copy `api-config.js` into the container AND set `BASE` to point at port 4000, then update `engine_flow_controls.js` to use `window.W4P_API.TABLE_LATEST`.

**Option D: Serve Engine from er-remote container**
Move the Engine page to be served from port 4000 alongside the Remote UI. Then relative URLs resolve correctly.

**Recommendation:** Option B (reverse proxy) — cleanest, no frontend change needed, already on same Docker network. But wait for user decision.

---

## 10. Regression Guardrails (verified)

- ✅ Remote UI confirmed working (same data pipeline, served from port 4000)
- ✅ `/api/table/latest` on port 4000 returns valid data
- ✅ Extension → Express → Flask → table_state pipeline unaffected
- ✅ No backend code modified
- ✅ Fix restricted to Engine frontend (or nginx/Docker proxy config)

---

## 11. Summary

| Question | Answer |
|----------|--------|
| Exact line where data stops | `engine_flow_controls.js` ~line 229: `fetch("/api/table/latest")` |
| Why | Relative URL resolves to port 5002; endpoint only exists on port 4000 |
| Failure type | HTTP 404 — endpoint not found on the Engine server |
| Writer function | `setTextareaValue()` (line ~350) — never reached |
| Textarea | Exists, empty of live data, contains only React default placeholder |

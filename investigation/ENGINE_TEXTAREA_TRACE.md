# ENGINE_TEXTAREA_TRACE.md
## W4P Engine Textarea — Complete Data Flow Trace

**Date:** 2026-07-03
**Investigation:** READ-ONLY

---

## 1. Engine Endpoint

**File:** `source/engine_flow_controls.js`
**Line 6:**
```javascript
const BRIDGE_URL = (window.W4P_API && window.W4P_API.LATEST) || (window.location.origin + '/api/latest');
```

Default: `/api/latest` on origin (port 5002, Engine Flask). Engine Flask proxies `/api/latest` → REMOTEREMOTE Flask via `/api/table/*` or direct route.

**Resolved endpoint (runtime):** `/api/latest` (no `?bot_id=` parameter)

This means the Engine receives whatever `_select_best_table()` returns — the "best" per-bot entry.

---

## 2. Poll Loop

**File:** `source/engine_flow_controls.js`
**Lines 278-305:** `pollLatest()`

```
pollLatest()
  ↓
fetch(BRIDGE_URL, timeout=10s)
  ↓
parse JSON → data.table
  ↓
formatTableDataToCanonical(data.table)  ← converts to text
  ↓
if (text === lastSnapshotHash) return;  ← hash-based dedup (line 289)
  ↓
setTextareaValue(textarea, text)        ← REPLACE, not append (line 293)
  ↓
maybeAutoRun(text)                      ← optional auto-trigger (line 294)
```

Key characteristics:
- **Poll interval:** 1.5s (active) / 5s (idle), adaptive
- **Dedup:** hash-based comparison of canonical text format. Skips identical calls.
- **Update mode:** FULL REPLACE — `setTextareaValue()` sets textarea.value to new text. No append.
- **No hand_id tracking:** The Engine does not read, store, or compare `hand_id` from API response
- **No hand boundary detection:** The Engine has no concept of "new hand" beyond the text content itself

---

## 3. Textarea Build Logic

**File:** `source/engine_flow_controls.js`
**Lines 268-276:** `setTextareaValue(textarea, value)`

```javascript
function setTextareaValue(textarea, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value").set;
    nativeSetter.call(textarea, value);        // FULL REPLACE
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.dispatchEvent(new Event("change", { bubbles: true }));
}
```

This REPLACES the entire textarea value. It does NOT append. It does NOT partially update. It overwrites everything.

---

## 4. Canonical Text Format

**File:** `source/engine_flow_controls.js`
**Lines 83-103:** `formatTableDataToCanonical(table)`

```javascript
function formatTableDataToCanonical(table) {
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
```

This function:
1. Iterates ALL seats in `table.seats`
2. Extracts `hole_cards` from EVERY seat that has non-empty cards
3. Joins them into lines
4. Appends board cards as the last line

**Critical observation:** There is NO filtering by hand_id. There is NO filtering by is_active or is_hero. ANY seat with hole_cards gets included. If a seat has stale hole_cards from a previous hand, they appear in the textarea.

---

## 5. What `setTextareaValue` Actually Does

The Engine textarea contains whatever `formatTableDataToCanonical()` returns. Since it does full REPLACE (not append), the only way to get overlapping hands is if the single API response contains hole_cards from multiple hands in its `seats` array.

**If the textarea shows overlapping hands, the overlap is ALREADY present in the `/api/latest` response's `seats` array.**

---

## 6. Auto-Run Logic

**File:** `source/engine_flow_controls.js`
**Lines 207-242:** `maybeAutoRun(text)`

The auto-run checks:
1. `autoRunFlop` toggle must be ON
2. Variant must be selected
3. Board must be at FLOP or later
4. At least 2 hands required
5. State must differ from `lastStateKey`
6. No duplicate cards
7. Card normalization must succeed

If all pass, the textarea is set AND the "Run Engine" button is clicked.

Auto-run only triggers when ALL conditions are met. It does not modify the textarea independently — it uses `setTextareaValue()` which the poll loop already called.

---

## 7. What the Engine Does NOT Do

| Capability | Present? | Location |
|-----------|----------|----------|
| Track hand_id | ❌ No | — |
| Clear textarea on new hand | ❌ No | — |
| Append to textarea | ❌ No | Always replaces |
| Detect hand boundary | ❌ No | — |
| Filter seats by hand context | ❌ No | All seats included |
| Use `?bot_id=` parameter | ❌ No | Default endpoint |

# AVAILABLE_ACTIONS_STATIC_TRACE.md

**Date:** 2026-07-03
**Status:** READ-ONLY — static code-path analysis
**Scope:** Trace `available_actions` from Extension to DOM

---

## Critical Finding: Operator-Console Gate is MISSING

The documented operator-console rendering gate (`hasActions`) is NOT present in the current code. The button rendering gate at L869 uses the old hero-gated pattern:

```javascript
// Line 869 — CURRENT code (hero-gated):
var isActive = isHero && acts.length > 0;

// Line 928 — gate for rendering action buttons:
if (isActive) { ...render FOLD/CHECK/CALL/BET/RAISE... }
```

**Both conditions must be true for buttons to render.** This means non-hero seats NEVER get action buttons in the current codebase, regardless of their `available_actions` value.

---

## Propagation Matrix (Static)

| Stage | File | Line | Field Read | Written To | Can Be Dropped? | Condition |
|-------|------|------|-----------|-----------|-----------------|-----------|
| Extension: scrape | w4p.js | 1225 | DOM buttons → `avail[]` | local `avail` | Yes | `BTN_SEL` selectors must match DOM |
| Extension: buildSnapshot | w4p.js | 1367 | `avail[]` | `seats[i].available_actions` | **YES - hero gate** | `isHero ? avail : []` → non-hero = `[]` |
| Extension: POST | w4p.js | 1502-1503 | entire snapshot | POST body | No | bridgeFetch sends full JSON |
| Flask: read payload | app.py | 1237 | `s.get("available_actions")` | `new_seats[sno]` | Yes | Defaults to `[]` if key missing |
| Flask: merge (same bot) | app.py | 1265 | `sdata` | `table["seats"][sno]` | No | Full replacement |
| Flask: merge (diff bot) | app.py | 1250-1261 | NOT read | NOT updated | **YES - cross-bot gate** | Restricted merge skips `available_actions` |
| Flask: global store | app.py | 1288-1289 | `payload.get('available_actions')` | `_bot_actions[bot_id]` | Yes | Only if `bot_id` is truthy |
| Flask: serialize | app.py | 700-703 | `seat_data.get("available_actions")` then `_bot_actions.get(bot_id)` | `seat_data["available_actions"]` | Yes | Fallback to global if seat's own is empty |
| Flask: serialize (stale) | app.py | 713-729 | hardcoded `[]` | `"available_actions": []` | Always empty | Stale/anonymous seats |
| Flask: cleanup eviction | app.py | 944-946 | — | DELETED | **YES - eviction** | `_bot_actions.pop(bot_id)` on SEAT_TTL expiry |
| Remote: fetch | remote-w4p.html | ~752 | API response | `lastTable.seats[]` | No | JSON parse |
| Remote: posSeatMap | remote-w4p.html | 1022 | `seat.name != null` | `posSeatMap[pos]` | Yes | Seats without names excluded |
| Remote: heroIsActive | remote-w4p.html | 1028 | `seat.available_actions` | `heroIsActive` | No | Drives adaptive poll rate |
| Remote: buildSeatBoxHtml | remote-w4p.html | 852 | `seat.available_actions` | local `acts[]` | No | `seat.available_actions \|\| []` |
| Remote: render gate | remote-w4p.html | 869 | `acts.length` | `isActive` | **YES - hero gate** | `isHero && acts.length > 0` |
| Remote: EMG panel | remote-w4p.html | 1110-1118 | `hero.available_actions` | local `acts[]` | Yes | Only for hero (findHero()) |

---

## Detailed Hop-by-Hop Trace

### HOP 1: Extension DOM Scrape → available_actions Array

**File:** `backend/static/ext/w4p.js`
**Function:** `getAvailableActions()` → `buildSnapshot()`

```
Line 1225: var avail = buttons.actions.map(function(a) { return a.action; });
```
The extension scrapes the DOM for visible action buttons using `BTN_SEL` selectors. If buttons are found, `avail` contains action names like `["check", "bet"]`.

```
Line 1367: available_actions: isHero ? avail : [],
```
**GATE:** Only the hero seat gets `available_actions`. All non-hero seats get `[]`. This is by design — the extension is a self-reporting bot that can only see its own action buttons.

**CAN DROP: YES.** If `isHero` is false, `available_actions` is always `[]`.

---

### HOP 2: POST /api/snapshot

**File:** `backend/static/ext/w4p.js`
**Function:** `sendSnapshot()`

```
Line 1502: function sendSnapshot(snap) {
Line 1503:   bridgeFetch('/snapshot', 'POST', snap, ...);
```
The entire snapshot object (including `seats[].available_actions`) is serialized as JSON and POSTed via the postMessage bridge → background.js → fetch().

**CAN DROP: NO.** The data is included in the JSON payload. No filtering occurs at this stage.

---

### HOP 3: Flask post_snapshot() — Payload Parsing

**File:** `backend/app.py`
**Function:** `post_snapshot()`

```
Line 1237: "available_actions": s.get("available_actions", []),  # per-seat actions
```
Reads `available_actions` from the incoming seat data into `new_seats[sno]`. Defaults to `[]` if missing.

**CAN DROP: YES (if key missing from snapshot).** Defaults to `[]`.

---

### HOP 4: Flask post_snapshot() — Merge Into table_state

**File:** `backend/app.py`
**Function:** `post_snapshot()`

Two merge paths:

**Path A — Same bot or no existing bot (Line 1264-1265):**
```
else:
    table["seats"][sno] = sdata
```
Full replacement. `available_actions` from snapshot is preserved.

**Path B — Different bot owns this seat (Line 1250-1261):**
```
if existing_bot and bot_id and existing_bot != bot_id:
    # Restricted merge: only updates stack, status, is_dealer, last_seen, hole_cards
    # Does NOT update: name, is_hero, is_active, available_actions
```
**CAN DROP: YES — cross-bot restricted merge.** If Bot-A sends a snapshot that includes Bot-B's seat, Bot-B's `available_actions` is NOT updated. This is by design — the operator-console architecture requires each bot to own its own action state.

---

### HOP 5: Flask post_snapshot() — Global _bot_actions Store

**File:** `backend/app.py`
**Function:** `post_snapshot()`

```
Line 1288: avail_actions = payload.get('available_actions', [])
Line 1289: _bot_actions[bot_id] = avail_actions
```

A **separate** global store keyed by `bot_id` (not by table+seat). This is updated for every snapshot, regardless of which seat the bot occupies.

**CAN DROP: YES.** The `payload.get('available_actions')` at the top level is `payload.get('available_actions', [])` — this reads from the ROOT of the snapshot JSON, not from seats. If the snapshot doesn't have a top-level `available_actions` field, this is always `[]`.

**KEY RISK:** The snapshot payload structure has `available_actions` inside each seat object, NOT at the top level. So `payload.get('available_actions', [])` at line 1288 would always return `[]` UNLESS the snapshot JSON has a root-level `available_actions` field. Looking at the extension's `buildSnapshot()` output structure, I need to verify whether the snapshot root includes this.

---

### HOP 6: Flask _build_seats_list() — Serialization

**File:** `backend/app.py`
**Function:** `_build_seats_list()`

```
Line 700-703:
    seat_actions = seat_data.get("available_actions", [])
    if not seat_actions:
        seat_actions = _bot_actions.get(bot_id, []) if bot_id else []
    seat_data["available_actions"] = seat_actions
```

Two-tier fallback:
1. Read seat's own `available_actions` from table_state
2. If empty, fall back to `_bot_actions[bot_id]`

**CAN DROP: YES.** If both the seat's own `available_actions` is empty AND `_bot_actions[bot_id]` is empty (or the bot_id doesn't exist in _bot_actions), the output is `[]`.

---

### HOP 7: _build_seats_list() — Stale Seat Eviction

**File:** `backend/app.py`
**Function:** `_build_seats_list()`

```
Line 643-653: is_stale = ... and (now_ts - last_seen) > _STALE_TTL
```
If a non-hero controlled seat hasn't been refreshed within `_STALE_TTL` (5.0s), it's classified as stale. Stale seats hit the `else` branch at line 713-729 which hardcodes:
```
"available_actions": [],
```

**CAN DROP: YES — stale timeout.** Seats unrefreshed for 5s get `available_actions: []`.

---

### HOP 8: Flask _cleanup_loop() — Seat Eviction

**File:** `backend/app.py`
**Function:** `_cleanup_loop()`

```
Line 944-946:
    _bot_actions.pop(evicted_bot, None)
    _bot_buttons.pop(evicted_bot, None)
```
When a seat is fully evicted (SEAT_TTL=30s), the owning bot's `_bot_actions` entry is deleted. The serialization fallback at line 701-702 will then return `[]`.

**CAN DROP: YES — full eviction.** 30s without a snapshot → seat removed entirely.

---

### HOP 9: /api/latest Response

**File:** `backend/app.py`
**Function:** `_handle_table_latest()`

```
Line 1555: if table_age > _TABLE_INACTIVE_TTL:
Line 1561:     'table_id': 'waiting', ...  # all seats empty
```

If no snapshots arrive for `_TABLE_INACTIVE_TTL` (30s), the entire table is replaced with `waiting` state — all 9 seats empty, no `available_actions`.

**CAN DROP: YES — table inactivity timeout.** 30s of no snapshots → entire table destroyed.

---

### HOP 10: Remote UI fetchTable()

**File:** `source/remote-w4p.html`
**Function:** `fetchTable()`

Long-poll: `GET /api/table/latest?timeout=25&last_ts=N`. Parses JSON → `lastTable = data.table`. No filtering of `available_actions`.

**CAN DROP: NO.** Raw JSON parse — whatever the API returns is stored.

---

### HOP 11: Remote UI posSeatMap

**File:** `source/remote-w4p.html`
**Function:** `renderSeats()`

```
Line 1022: if (seat.name != null) { posSeatMap[pos] = seat; }
```
Seats without names are excluded from the grid entirely. If a seat exists in the API but has `name: null`, it won't appear in `posSeatMap` and won't be rendered.

**CAN DROP: YES.** Name-less seats excluded before rendering.

---

### HOP 12: Remote UI heroIsActive Check

**File:** `source/remote-w4p.html`
**Function:** `renderSeats()`

```
Line 1028: if (seat.is_self_player && seat.available_actions && seat.available_actions.length > 0) {
Line 1029:   heroIsActive = true;
Line 1030: }
```
This only sets `heroIsActive` for adaptive polling — does NOT control button rendering directly. It requires BOTH `is_self_player` AND `available_actions.length > 0`.

---

### HOP 13: Remote UI buildSeatBoxHtml() — THE GATE

**File:** `source/remote-w4p.html`
**Function:** `buildSeatBoxHtml()`

```
Line 852: var acts = seat.available_actions || [];
Line 869: var isActive = isHero && acts.length > 0;
Line 928: if (isActive) { ... render action buttons ... }
```

**THE CRITICAL GATE:** Buttons ONLY render when `isActive` is true, which requires:
- `isHero === true` (seat must be the self-player)
- `acts.length > 0` (must have available actions)

Non-hero seats NEVER get buttons, even if they have `available_actions`. The operator-console pattern (`hasActions`) documented in the skill is NOT in the current code.

**CAN DROP: YES — hero gate.** This is the definitive render gate. No non-hero seat gets action buttons.

---

### HOP 14: Remote UI EMG Panel

**File:** `source/remote-w4p.html`
**Function:** `renderEmgPanel()`

```
Line 1110: var hero = findHero();
Line 1118: var acts = hero.available_actions || [];
```
Only renders buttons for the hero seat. Uses `findHero()` which returns the first seat with `is_self_player === true`.

---

## Potential Failure Points (Priority Order)

| # | Hop | What Can Go Wrong | Evidence Needed |
|---|-----|-------------------|-----------------|
| 1 | HOP 1 (L1367) | Hero gate: `isHero` is false → `avail = []` | Extension console: heroName, isHero value |
| 2 | HOP 4 (L1250) | Cross-bot restricted merge: different bot's snapshot skips `available_actions` | Snapshot bot_id vs seat owner |
| 3 | HOP 5 (L1288) | `payload.get('available_actions', [])` at ROOT level — may always be `[]` if snapshot has actions only inside seats | Snapshot JSON structure |
| 4 | HOP 6 (L701) | `_bot_actions` fallback returns empty: stale or bot_id mismatch | _bot_actions contents |
| 5 | HOP 7 (L643) | `_STALE_TTL = 5s` — seat classified as stale before next snapshot arrives | Snapshot interval vs TTL |
| 6 | HOP 8 (L944) | `SEAT_TTL = 30s` — full eviction of seat + `_bot_actions` | Snapshot age |
| 7 | HOP 9 (L1555) | `_TABLE_INACTIVE_TTL = 30s` — entire table → waiting | Health endpoint |
| 8 | HOP 11 (L1022) | `seat.name == null` → seat excluded from grid | API response |
| 9 | **HOP 13 (L869)** | **hero gate: `isHero && acts.length > 0` → non-hero never renders** | **buildSeatBoxHtml input** |

---

## Summary

The `available_actions` pipeline has **two independent gates** that prevent non-hero action rendering:

1. **Extension gate (w4p.js:1367):** The extension only sends `available_actions` for the hero seat. Non-hero seats always get `[]` in the snapshot.

2. **Render gate (remote-w4p.html:869):** Even if a non-hero seat somehow had `available_actions` (e.g., through a second extension instance), the button rendering gate requires `isHero === true`. Non-hero seats NEVER get action buttons.

**This is the designed behavior** for the current single-bot architecture. The operator-console pattern (`hasActions`) from the platform skill documentation was apparently a planned change that is not yet implemented.

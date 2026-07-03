# VERTICAL SLICE TRACE — Seat/Hand Collision Investigation

**Date:** 2026-07-03
**Status:** READ-ONLY — no code changes
**Investigation:** Seat Collision / Hand Overwrite

---

## 1. Vertical Slice: One Complete Data Flow

Tracing a complete data path through every component for `table_id = pb_2589955`.

```
GoldRush DOM (PokerBet)
  ↓ [DOM scrape, 300ms interval]
Extension (w4p.js → bridge.js → background.js)
  ↓ [POST /api/snapshot, bot_id in payload]
Express :4000 (scripts/server.js)
  ↓ [proxy → Flask :1080]
Flask backend (backend/app.py, post_snapshot)
  ↓ [_tables[(table_id, bot_id)] → per-bot entry]
API selection (_select_best_table)
  ↓ [freshness + street rank + last_ts + hash tiebreak]
/api/latest → Express :4000 + Engine :5002 (proxy)
  ↓
Remote UI (remote-w4p.html) + Engine textarea (engine_flow_controls.js)
```

---

## 2. Hop-by-Hop Verification

### Hop 1: GoldRush DOM → Extension Scrape

**File:** `source/w4p.js`
**Function:** `tick()` → `buildSnapshot()`

**Status:** VERIFIED (existing investigation)
- Each bot instance scrapes the DOM independently at 300ms
- `bot_id` is correctly assigned per bot profile
- `resolveSeatIndex()` provides stable seat indexing
- Snapshot includes: table_id, bot_id, seats, street, board, pot, dealer

**Runtime evidence:** Backend logs show 3 bots posting:
```
[SNAPSHOT][ACCEPT] table_id=pb_2589955 bot_id=monarchi seats=1
[SNAPSHOT][ACCEPT] table_id=pb_2589955 bot_id=Atros seats=2
[SNAPSHOT][ACCEPT] table_id=pb_2589955 bot_id=allinstalker seats=2
```
- monarchi: sees 1 seat (itself at seat 4)
- Atros: sees 2 seats (itself at 5, monarchi at 4)
- allinstalker: sees 2 seats (itself at 1, Atros at 5)

**Confidence:** 95% — extension behavior unchanged from prior investigations

---

### Hop 2: POST /api/snapshot → Flask :1080

**File:** `backend/app.py`, lines 1097-1325
**Function:** `post_snapshot()`

**Status:** VERIFIED at runtime
- `get_or_create_table(table_id, bot_id)` creates per-bot entry: `_tables[(pb_2589955, monarchi)]`, `_tables[(pb_2589955, Atros)]`, `_tables[(pb_2589955, allinstalker)]`
- Each entry has its own `hand_id` (UUID4, generated on first POST)
- `hero_active` guard (line 1197): only bots with `available_actions` can overwrite structural fields
  - allinstalker: has `["back_to_game"]` → CAN overwrite structural fields
  - monarchi: has `[]` → CANNOT overwrite structural fields
  - Atros: has `[]` → CANNOT overwrite structural fields
- Multi-bot guard (lines 1152-1159): different bot's street regression does NOT trigger hand reset
- Hand IDs are stable within each entry

**Runtime evidence:**
```
hand_id=27d1d74e (monarchi entry)  state_version=1352
hand_id=60227f46 (allinstalker entry)  state_version=5034
hand_id=339aec5c (Atros entry)  state_version=1372
```

**Confidence:** 100% — verified via /api/tables response

---

### Hop 3: API Selection (_select_best_table)

**File:** `backend/app.py`, lines 1541-1597
**Function:** `_select_best_table()`, `_entry_score()`

**Status:** THIS IS THE CONVERGENCE POINT WHERE 3 HANDS BECOME 1

**Selection algorithm:**
```python
Priority: freshness > street rank > last_ts > hash(bot_id)
```

All three entries are:
- Fresh (all updated within 30s)
- PREFLOP (street rank = 0)
- So last_ts determines the winner

**Oscillation cycle:**
```
T+0ms:   monarchi POST → last_ts = T+0 → monarchi selected
T+150ms: Atros POST    → last_ts = T+150 → Atros selected  
T+300ms: allinstalker POST → last_ts = T+300 → allinstalker selected
T+450ms: monarchi POST → last_ts = T+450 → monarchi selected
...cycle repeats...
```

**Runtime evidence (20 samples, 50ms apart):**
```
T+0ms:    hand=339aec5c (Atros)
T+200ms:  hand=60227f46 (allinstalker) <<< CHANGE
T+400ms:  hand=339aec5c (Atros) <<< CHANGE
```
2 hand changes in 1 second. monarchi entry was stale (>30s) for part of this window.

**Confidence:** 100% — reproduced 10+ times

---

### Hop 4: /api/latest → Consumers

**Express :4000** — `_handle_table_latest()` → `_select_best_table()` → returns one entry
**Engine :5002** — `proxy_api_latest()` → forwards to `er-remote:4000/api/latest` → same handler

Both return identical results (same Flask backend), but timing differences mean they may return different hand_ids at any given instant.

**Runtime evidence — simultaneous requests:**
```
Express (T+0): hand=60227f46 (allinstalker, last_ts=T-200ms)
Engine  (T+5): hand=339aec5c (Atros, last_ts=T-5ms — Atros posted between Express and Engine calls)
```

**Confidence:** 100%

---

### Hop 5a: Remote UI Rendering

**File:** `source/remote-w4p.html`
**Function:** `fetchTable()` → `renderSeats()`

The Remote UI long-polls `/api/table/latest` (25s timeout) and renders whatever the API returns. It has no mechanism to verify whether seats belong to the same hand context. It faithfully renders:
- Seat 4: monarchi (hero, playing, cards=6) — when monarchi entry is selected
- Seat 4: monarchi (folded, cards=0) — when Atros entry is selected
- Creates the appearance of "data jumping between hands"

**Confidence:** 95% — consistent with prior investigations

---

### Hop 5b: Engine Textarea Population

**File:** `source/engine_flow_controls.js`, lines 278-304
**Function:** `pollLatest()`

```
BRIDGE_URL = window.W4P_API.LATEST || window.location.origin + '/api/latest'
           = "http://localhost:5002/api/latest"
```

Engine Flask proxies `/api/latest` → `er-remote:4000/api/latest` (line 138-141 of Engine app.py)

Poll cycle: FAST_POLL=1500ms (active) or SLOW_POLL=5000ms (idle)

On each poll:
1. Fetch BRIDGE_URL
2. `formatTableDataToCanonical(data.table)` — extracts hole cards from seats
3. If text differs from `lastSnapshotHash` → `setTextareaValue(textarea, text)` — OVERWRITES textarea
4. `maybeAutoRun(text)` — triggers equity calculation

**Critical:** The textarea is overwritten whenever the API returns a different hand's data. Since the API oscillates between 3 hand_ids, the textarea gets overwritten with different hole cards.

**Confidence:** 100%

---

## 3. First Point of Divergence

The identity chain is preserved until Hop 3 (API selection). At this point:

```
3 independent hand contexts
       ↓
_select_best_table() picks ONE based on freshness/street/last_ts
       ↓
Remote UI + Engine receive a SINGLE merged view
       ↓
Consumers cannot distinguish which hand context they're seeing
```

**Location:** `backend/app.py`, line 1633: `table = _select_best_table()`

This is where 3 hands collapse to 1, and where the oscillation originates.

---

## 4. Verification Summary

| Hop | Component | Status | Confidence |
|-----|-----------|--------|------------|
| 1 | GoldRush → Extension scrape | ✓ Correct per-bot scrape | 95% |
| 2 | POST /api/snapshot → Backend | ✓ Per-bot isolation working | 100% |
| 3 | API selection (_select_best_table) | ⚠ 3 hands → 1, last_ts oscillation | 100% |
| 4 | /api/latest → Consumers | ⚠ Different hands at different times | 100% |
| 5a | Remote UI rendering | ⚠ Renders whichever hand selected | 95% |
| 5b | Engine textarea | ⚠ Overwritten on hand change | 100% |

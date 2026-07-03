# CURRENT_ARCHITECTURE_REVIEW.md
## W4P Runtime Architecture — Deployed vs Baseline

**Date:** 2026-07-03
**Investigation:** READ-ONLY
**Repository:** /home/wa/projects/poker/E&R

---

## 1. Deployment State

| Property | Value |
|----------|-------|
| Baseline release | `w4p-seat-stability-v1` (tagged) |
| Baseline commit | `94a6cfc` |
| Current HEAD | `172a0ee` |
| Commits since baseline | 8 commits (including 4 runtime fixes) |
| Deployed to container | YES — SHA verified: host `backend/app.py` == container `/app/backend/app.py` == git HEAD |
| Container creation | 2026-07-01 22:46 UTC |
| Flask PID | 138 |
| Flask uptime | ~1596s (at time of investigation) |
| Flask health | healthy, `snapshot_seq=4948` |
| Express PID | 1 (node server-container.js) |

### Deployment Parity

All three SHAs match:
```
Host:    117b7b8b...  backend/app.py
Container: 117b7b8b...  /app/backend/app.py
Git HEAD:  117b7b8b...  backend/app.py
```
✅ Parity gate passed. Container is running HEAD.

---

## 2. Post-Baseline Changes (94a6cfc → 172a0ee)

Four runtime changes deployed to production WITHOUT release tagging or approval process:

### Commit a71c555 — `is_active` fix (required)
- **File:** `backend/app.py` (2 lines added)
- **Change:** Added `is_active` to `new_seats[seat_no]` dict construction (line 1237)
- **Impact:** Extension was computing `is_active=True` but backend was dropping it
- **Verification:** Confirmed deployed and functional

### Commit a58a6ee — Per-bot table isolation (architectural change)
- **File:** `backend/app.py` (+85/-30), `source/remote-w4p.html` (+45)
- **Change:** `_tables` keyed by `(table_id, bot_id)` instead of `table_id` alone
- **Impact:** Each bot gets independent state. API accepts `?bot_id=` param.
- **Added:** `_find_table_for_bot()`, `_dedup_latest_by_table()`, `_table_key()`
- **Modified:** `get_or_create_table()`, all `_tables` lookups across SSE, cleanup, debug

### Commit 5a31670 — Structural field gate (tactical guard)
- **File:** `backend/app.py` (+24/-4)
- **Change:** Structural fields (`street`, `board`, `pot_zar`, `dealer_seat`) only overwritten when incoming bot has `available_actions` (is "active")
- **Gate:** `hero_active = bool(payload.get('available_actions'))`
- **Impact:** Prevents inactive bots' stale views from overwriting active bot's game state

### Commit 172a0ee — API dedup (tactical guard)
- **File:** `backend/app.py` (+14/-4)
- **Change:** `_dedup_latest_by_table()` returns most recent entry per unique `table_id` when no `bot_id` specified
- **Impact:** Prevents `/api/latest` from alternating between different bots' entries

---

## 3. Current Runtime Architecture

```
Extension (allinstalker)        Extension (monarchi)        Extension (Atros)
  ↓ POST /api/snapshot            ↓                           ↓
  bot_id=allinstalker             bot_id=monarchi             bot_id=Atros
  ↓                              ↓                           ↓
Flask :1080
  _tables = {
    ("pb_2589955", "allinstalker"): { street=PREFLOP, ... },
    ("pb_2589955", "monarchi"):      { street=FLOP,    ... },  
    ("pb_2589955", "Atros"):         { street=FLOP,    ... },
  }
  ↓
GET /api/latest (no bot_id)
  → _dedup_latest_by_table()
  → returns max(last_ts) among all entries for pb_2589955
  → whichever bot posted most recently wins
```

**Key change from baseline:** State is now per-bot partitioned. The API layer picks the most recent entry when no `bot_id` is specified.

---

## 4. Component-by-Component Assessment

### Extension (w4p.js)
- **Status:** Unchanged from baseline (one uncommitted modification tracked in git status)
- **Polling:** 300ms per bot, independent timers, no coordination
- **Dedup:** None — "Send every tick — no dedup, no heartbeat gate" (w4p.js:2084)
- **Assessment:** Extension correctly reports what each bot observes. NOT the source of oscillation.

### Backend Merge (app.py)
- **Status:** Significantly modified from baseline
- **Per-bot isolation:** ✅ Working — 3 independent entries for 3 bots
- **Structural field gate:** ⚠️ Partially effective — `back_to_game` actions qualify as "active", defeating the gate
- **Hand reset detection:** ⚠️ Oscillation continues within bot-specific entries
- **Hand ID system:** ✅ Correctly assigns per-bot hand_ids

### API Layer (app.py `_handle_table_latest`)
- **Status:** `_dedup_latest_by_table()` returns most-recent bot entry
- **Oscillation vector:** When bots have different streets, the most-recent entry alternates
- **Assessment:** This is where the flicker reaches the API consumer

### Remote UI (remote-w4p.html)
- **Status:** Modified from baseline (seat stability + bot_id param support)
- **Diff-based rendering:** `json === _lastTableJSON` gate (line 736)
- **Assessment:** Faithfully renders whatever `/api/latest` returns. NOT the source of oscillation.

### Engine (engine_flow_controls.js)
- **Status:** Unchanged from baseline
- **Assessment:** Polls `/api/latest`, receives oscillating data during divergence

---

## 5. Active Bots Observed

From log analysis (33,420 ACCEPT lines on 2026-07-03):

| Bot | Snapshots | Rate | Active % | Typical Actions |
|-----|-----------|------|----------|----------------|
| Atros | 13,124 (39%) | 1.33/s | 39% | check, bet, fold, back_to_game |
| monarchi | 11,382 (34%) | 1.15/s | 44% | check, bet, fold, back_to_game |
| allinstalker | 8,906 (27%) | 0.90/s | 100% | back_to_game (always) |

Additional transient bots: 9HiLikeABOss, realTenEight

---

## 6. Hand ID System Status

The hand_id system (ADR-001 Phase 1) is deployed but the extension has NOT been updated to echo hand_ids. All hand_ids are backend-generated UUIDs, one per `_tables[(table_id, bot_id)]` entry.

Observed at 02:35:18 — three simultaneous "Initial hand" lines:
```
[HAND_ID] Initial hand 60227f46 table=pb_2589955
[HAND_ID] Initial hand 5cc882e9 table=pb_2589955
[HAND_ID] Initial hand 491c9ac7 table=pb_2589955
```

Three different hand_ids for three bot entries on the same table. Confirms per-bot isolation at the storage level.

---

## 7. Known Issues in Current Deployment

1. **`_dedup_latest_by_table()` oscillates between bot entries** — picks most recent regardless of game context
2. **Structural field gate defeated by `back_to_game`** — allinstalker always has this action, always qualifies as "active"
3. **240,407 hand reset log lines** — excessive reset frequency (avg 24/sec across 9,874s)
4. **Multi-bot hand reset guard** has `last_street_bot=None` in all 198 observed cases — suggests `last_street_bot` is never being set
5. **Flask PID lock** caused restart failures (observed: "FATAL: Another instance is running (PID 7)")

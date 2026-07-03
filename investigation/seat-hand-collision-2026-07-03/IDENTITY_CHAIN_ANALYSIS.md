# IDENTITY CHAIN ANALYSIS

**Date:** 2026-07-03
**Investigation:** Seat Collision / Hand Overwrite
**Status:** READ-ONLY — confirmed at runtime

---

## 1. The Identity Chain

The full identity chain from DOM to display:

```
table_id (pb_2589955)
  ↓
hand_id (per-bot UUID4)
  ↓
bot_id (monarchi | Atros | allinstalker)
  ↓
seat_no (1-9)
  ↓
player name (DOM-scraped)
  ↓
hole cards (hero-only, DOM-scraped)
  ↓
Remote UI / Engine display
```

---

## 2. Hop-by-Hop Identity Verification

### Hop 1: table_id

**Source:** Extension parses GoldRush URL
**File:** `source/w4p.js`

**Status:** STABLE. All 3 bots share `table_id = "pb_2589955"` because they are observing tables at `tbl/2589955`.

**Issue:** This is the ROOT of all downstream ambiguity. Three bots observe `tbl/2589955` but each is in a DIFFERENT game instance. GoldRush reuses table numbers across sessions.

**Evidence:** All 3 entries in `/api/tables` have `table_id: "pb_2589955"`.

**Confidence:** 100%

---

### Hop 2: hand_id

**Source:** Backend generates UUID4 on first POST
**File:** `backend/app.py`, line 1190

**Status:** STABLE within each per-bot entry, but 3 DIFFERENT hand_ids exist for the same table_id.

```
Entry (pb_2589955, monarchi):    hand_id = 27d1d74e
Entry (pb_2589955, Atros):       hand_id = 339aec5c
Entry (pb_2589955, allinstalker): hand_id = 60227f46
```

**Issue:** `hand_id` correctly identifies a hand within a bot's stream, but cannot identify when two bots are in DIFFERENT hands at the same logical table.

**File reference:** `backend/app.py`, lines 1189-1191 — hand_id generated on first POST, stable until hand change from SAME bot.

**Confidence:** 100%

---

### Hop 3: bot_id

**Source:** Extension configuration
**File:** `source/w4p.js`

**Status:** STABLE and CORRECT. Each bot correctly identifies itself.

**Evidence from bot registry:**
```
monarchi:     seat 4, last_seen 0.08s ago, state=running
Atros:        seat 5, last_seen 0.25s ago, state=running
allinstalker: seat 1, last_seen 0.95s ago, state=running
```

**Issue:** The backend uses `bot_id` to partition state, but `_select_best_table()` ignores it when choosing which entry to return to consumers.

**Confidence:** 100%

---

### Hop 4: seat_no

**Source:** Extension `resolveSeatIndex()` → `_seatCache`
**File:** `source/w4p.js`

**Status:** STABLE. Seat assignments do not change over time.

**Runtime evidence (20 samples):**
```
monarchi:     always at seat 4 (16 observations)
Atros:        always at seat 5 (20 observations)
allinstalker: always at seat 1 (4 observations)
```

**Issue:** Seat assignments are stable WITHIN each bot's entry, but the same seat may have different state across entries (soft collision).

**Confidence:** 100%

---

### Hop 5: player name

**Source:** DOM scrape of `.player-name` elements
**File:** `source/w4p.js`, `buildSnapshot()`

**Status:** STABLE. Player names are correctly scraped and consistent across entries.

**Evidence:** monarchi is always "monarchi", Atros is always "Atros", allinstalker is always "allinstalker" — no name corruption observed.

**Confidence:** 95% — DOM name disappearance (DEBT-004) not observed during this investigation window

---

### Hop 6: hole cards

**Source:** DOM scrape (hero only), backend `_hero_cards` cache fallback
**File:** `source/w4p.js` → `backend/app.py` lines 1379-1420

**Status:** CORRECT within each entry, but DIFFERENT across entries.

```
monarchi entry: As,Jh,9c,7d,4c,4s  (monarchi is hero)
Atros entry:    Ac,Kh,Qs,8h,6d,5c  (Atros is hero)
allinstalker:   []                  (allinstalker, sitting out)
```

**Issue:** When the API returns a different entry, the consumer sees a different set of hole cards. This creates the "data jumps between hands" symptom.

**Confidence:** 100%

---

### Hop 7: Remote UI / Engine display

**Source:** `/api/latest` → `_select_best_table()`
**File:** `backend/app.py`, line 1633

**Status:** THIS IS WHERE IDENTITY BECOMES AMBIGUOUS.

The API selector collapses 3 independent hand contexts into 1 response. Which hand it picks depends on:
1. Which bot posted most recently (freshness → last_ts)
2. Whether any bot has advanced street (street rank)
3. Deterministic tiebreak (hash)

The consumer receives a coherent response and cannot determine:
- Which hand context this represents
- Whether this is the same hand it saw last time
- Whether the seat state changed because the hand changed or because the SELECTION changed

---

## 3. First Point Where Identity Becomes Ambiguous

```
IDENTITY PRESERVED:
  Extension:     table_id, bot_id, seat_no, player name — all stable and correct
  POST /api/snapshot: bot_id included in payload
  Backend _tables: per-bot entries with stable hand_id

IDENTITY LOST:
  _select_best_table() at backend/app.py:1633
  ↓
  "Which hand is this?" → "The freshest one with the highest street"
  ↓
  Consumer receives data → cannot trace which bot/hand it came from
```

**File:** `backend/app.py`, line 1633
**Function:** `_handle_table_latest()` → `_select_best_table()`
**Line:** `table = _select_best_table()`

This is the FIRST point where the connection between "this data" and "which hand/bot this is" is severed.

---

## 4. Why This Matters

The API response shape does not include `bot_id` (removed by `_table_view` at line 844). The consumer sees:

```json
{
  "ok": true,
  "table": {
    "table_id": "pb_2589955",
    "hand_id": "339aec5c",
    "seats": [...]
  }
}
```

The consumer sees `table_id` and `hand_id` but cannot know:
- Which BOT this data came from
- Whether this is the bot-specific view or a merged view
- Whether `hand_id` changed because the hand changed or because the selector picked a different entry

---

## 5. Conclusion

**Identity is preserved until `_select_best_table()` at `backend/app.py:1633`.**

At this point:
- The API must choose ONE of 3 legitimate hand contexts
- The selection criteria (freshness > street > last_ts > hash) are correct for picking the "best" game state
- But the consumer has no way to know WHICH context was selected
- Two consecutive API calls may return data from two different contexts
- The consumer interprets the data as "the table state changed" when in fact "a different hand was selected"

**Confidence:** 100%
- Verified all hops from DOM to display
- Identified the exact function and line where identity becomes ambiguous
- Confirmed with runtime evidence showing 3 hand_ids cycling through the API

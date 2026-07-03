# ROOT CAUSE REPORT — Seat/Hand Collision Investigation

**Date:** 2026-07-03
**Investigation:** Seat Collision / Hand Overwrite
**Status:** READ-ONLY — investigation complete, NO fixes implemented
**Author:** Hermes Agent (surgical investigation)

---

## Executive Summary

**All four symptoms (Engine textarea overwrite, wrong hand on Remote, seat collisions, data jumping) share ONE root cause:**

The API selector (`_select_best_table` at `backend/app.py:1633`) oscillates between 3 independent hand contexts that share the same `table_id`. Per-bot state isolation works correctly. The hand contexts are not merged — they are SELECTED between at the API boundary.

---

## 1. Answers to Acceptance Criteria

### Q1: Why is the Engine textarea being overwritten?

**Answer:** The Engine polls `/api/latest` every 1.5s. The API alternates between 3 different hand contexts (`27d1d74e`, `339aec5c`, `60227f46`). When the hand changes, `formatTableDataToCanonical()` produces different hole card text, the hash comparison detects the change, and `setTextareaValue()` overwrites the textarea.

**File:** `source/engine_flow_controls.js`, lines 278-304
**Confidence:** 100% — verified through runtime polling traces

### Q2: Why does the Remote occasionally show the wrong hand?

**Answer:** The Remote UI long-polls `/api/table/latest`. The API selector picks whichever bot posted most recently. Since bots post at 300ms intervals, the "selected" hand changes frequently. The Remote shows whichever hand had the highest `last_ts` at the moment of the poll.

**File:** `backend/app.py`, line 1633: `table = _select_best_table()`
**Confidence:** 100% — 7 hand changes observed in 10 sequential API calls

### Q3: Is there a seat collision?

**Answer:** No — within a single table entry. Yes — across entries ("soft collision").

Within each per-bot entry, seat assignments are consistent and non-overlapping. Across entries, the same player appears with conflicting state (e.g., monarchi is hero/playing in one entry, non-hero/folded in another). This is not a data corruption bug — it's a consequence of 3 independent game contexts for the same table_id.

**File:** `backend/app.py`, lines 1249-1266 — seat merge logic
**Confidence:** 100%

### Q4: Is there a hand collision?

**Answer:** Yes — three independent hand contexts exist for `table_id = pb_2589955`. They are correctly isolated in storage but collide at the API selection layer.

The three hands are not merged (per-bot isolation prevents that). But the API can only return ONE, and which one it returns changes with each bot POST.

**Confidence:** 100% — three hand_ids confirmed in `/api/tables` response

### Q5: Is identity lost between the Extension and the UI?

**Answer:** Identity is preserved through the extension scrape, POST pipeline, and per-bot state storage. It is lost at the API selection boundary where 3 hand contexts collapse into 1 response.

**File:** `backend/app.py`, line 1633: `table = _select_best_table()`
**Confidence:** 100%

### Q6: What is the first component where incorrect identity appears?

**Answer:** `_select_best_table()` at `backend/app.py:1633`.

This function resolves N bot entries to 1 API response. The response does not include `bot_id` (removed by `_table_view` at line 844). The consumer receives data but cannot determine which bot/hand context it came from.

---

## 2. Root Cause Analysis

### Not the Root Cause

| Hypothesis | Evidence Against |
|-----------|-----------------|
| Rendering bug in Remote UI | Remote UI correctly renders whatever API returns |
| Engine poller bug | Engine correctly polls and updates; faithfully displays API data |
| Extension seat assignment | Seats are stable; seat assignments don't drift |
| Seat ownership drift | `_seat_bots` correctly maps bots to seats |
| Hand reset oscillation | Multi-bot guard prevents cross-bot hand resets |
| Structural field overwrite | `hero_active` guard prevents inactive bots from overwriting |
| Snapshot interleaving | Per-bot isolation prevents cross-contamination |

### The Actual Root Cause

**The `_select_best_table()` function faces an impossible choice.**

It must select ONE entry from `_tables` to return as "the table state." But `_tables` contains 3 entries for `pb_2589955`, each representing a different bot's perspective of a different game context. There is no single "correct" selection — any choice is wrong for some consumer.

The selection algorithm (freshness > street rank > last_ts > hash) is deterministic and correct for choosing the "best" game state. But it cannot distinguish between:
- "The game state changed (same hand, next street)"  
- "A different bot posted (different hand, same street)"

Both produce a different `last_ts`, and the selector treats them identically.

### The Architecture's Assumption

The architecture assumes:
```
table_id → ONE game context → ONE authoritative view
```

The reality is:
```
table_id → THREE game contexts → THREE independent views
```

The architecture was designed for single-bot operation where this assumption held. Multi-bot operation broke the assumption.

---

## 3. Evidence Summary

### Runtime Evidence

```
3 active bots: monarchi (seat 4), Atros (seat 5), allinstalker (seat 1)
3 hand_ids: 27d1d74e, 339aec5c, 60227f46
All same table_id: pb_2589955
All same street: PREFLOP

API oscillation: 7 hand changes in 10 sequential calls (2-second window)
Average oscillation period: ~500ms
```

### Code Evidence

| File | Line | What Happens |
|------|------|-------------|
| `backend/app.py` | 183 | `_tables = {}` — keyed by `(table_id, bot_id)` |
| `backend/app.py` | 1117 | `get_or_create_table(table_id, bot_id)` — per-bot entry |
| `backend/app.py` | 1190 | `hand_id` generated for each new bot entry |
| `backend/app.py` | 1197-1202 | `hero_active` guard — structural fields protected |
| `backend/app.py` | 1152-1159 | Multi-bot guard — cross-bot hand resets blocked |
| `backend/app.py` | **1633** | **`_select_best_table()` — N entries → 1 response** |
| `backend/app.py` | 844-868 | `_table_view()` — strips `bot_id` from response |
| `backend/app.py` | 1742-1750 | `/api/tables` — returns all entries (3 for pb_2589955) |

---

## 4. Severity Assessment

| Aspect | Severity | Impact |
|--------|----------|--------|
| Engine usability | **HIGH** | Textarea overwritten with wrong hand data; operator cannot trust equity results |
| Remote UI trust | **HIGH** | Hand state appears to jump; operator cannot trust displayed data |
| Data integrity | **LOW** | Per-bot entries are internally correct; no corruption |
| Seat stability | **LOW** | Seat assignments are stable within each entry |
| Scope | Limited | Affects tables with 2+ bots in different game contexts |

---

## 5. Why This Wasn't Caught Earlier

1. The `hero_active` guard (line 1197) and multi-bot guard (line 1152) addressed STRUCTURAL FIELD oscillation but not API SELECTION oscillation.
2. The tests likely ran with a single bot where `_select_best_table()` always returns the only entry.
3. The prior investigation (`MULTI_BOT_MERGE_REPORT.md`) focused on the merge algorithm, not the selection algorithm.

---

## 6. The Selection Problem in Detail

### Current State
```
_tables = {
    (pb_2589955, monarchi):    { hand_id=27d1d74e, last_ts=T+0, street=PREFLOP }
    (pb_2589955, Atros):       { hand_id=339aec5c, last_ts=T+150, street=PREFLOP }
    (pb_2589955, allinstalker): { hand_id=60227f46, last_ts=T+300, street=PREFLOP }
}

_select_best_table() → scores all entries
  All fresh (< 30s)
  All same street (PREFLOP = 0)
  Tiebreaker: last_ts
  → Returns Atros's entry (last_ts=T+150)

Next tick:
  monarchi posts → last_ts=T+350 → now highest
  → Returns monarchi's entry

Next tick:
  allinstalker posts → last_ts=T+400 → now highest
  → Returns allinstalker's entry
```

The selection changes not because any hand changed streets, but because a different bot posted. The consumer sees this as "the hand changed" when in fact "a different bot's hand was selected."

---

## 7. Next Steps

This investigation identifies the root cause. Per the directive, NO fixes are implemented. The PROPOSED CHANGE will describe the surgical fix.

The fix must address: how to present 3 independent hand contexts through an API designed for 1.

Possible approaches (to be evaluated in PROPOSED CHANGE):
- A. Expose `bot_id` in API response so consumers can filter
- B. Add a `?bot_id=` parameter requirement (breaking change for consumers)
- C. Return per-bot data in `/api/latest` (multi-view, breaking change)
- D. Add a `_source_bot` field to the response so consumers at least know which bot's view they're seeing (minimal, non-breaking)
- E. If bots ARE at the same table, merge seats from all entries (requires confirming they share a game context — not yet proven)

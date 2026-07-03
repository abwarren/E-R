# HAND_OVERLAP_REPORT.md
## W4P Engine Textarea — Hand Overlap Root Cause

**Date:** 2026-07-03
**Investigation:** READ-ONLY
**Confidence:** HIGH (code-level confirmation, supported by runtime logs)

---

## 1. Root Cause

**The Engine textarea contains overlapping hands because the backend's hand reset is blocked by a permanently-triggering multi-bot guard (line 1149-1159 of `backend/app.py`), preventing seat data from being cleared at hand boundaries. Old hole_cards survive across hand transitions and are included in the `/api/latest` response's `seats` array.**

The Engine faithfully renders whatever the API provides. The overlap is already present in the API response before it reaches the Engine.

---

## 2. The Mechanism — Step by Step

### Step 1: Hand X Plays Out

During Hand X, a bot observes multiple seats with visible hole cards. These are stored in `_tables[("pb_2589955", bot_id)]["seats"]`.

```
Hand X — FLOP
  seat 1: allinstalker, hole_cards=[]
  seat 3: PlayerX,     hole_cards=["Ah","Kh","Qd","Jd"]
  seat 5: Atros,        hole_cards=["2s","3s"]
  seat 7: PlayerY,      hole_cards=["9c","Tc"]
```

### Step 2: Hand X Ends → Hand Y Begins

The genuine hand transition occurs (RIVER→PREFLOP). `_detect_new_deal()` at line 399-418 correctly detects street regression and returns True. `hand_changed = True`.

### Step 3: Multi-Bot Guard Blocks Reset

At lines 1149-1159, the guard checks:
```
incoming_street_guard = "PREFLOP"
table.get("street")   = "RIVER"
→ incoming != current → first condition TRUE

bot_id = "allinstalker"
table.get("last_street_bot") = None
→ bot_id != None → second condition TRUE

→ BOTH conditions TRUE → guard fires → hand_changed = False
```

The reset block (lines 1161-1188) is SKIPPED. Specifically:
- `table["seats"] = {}` — **NEVER EXECUTES** (line 1167)
- `table["hand_id"]` — **NOT UPDATED** (line 1164)
- `_hero_cards` — **NOT CLEARED** (lines 1170-1173)

### Step 4: Old Seats Survive

The table still has Hand X's seat data:
```
table["seats"] = {
    1: {name="allinstalker", hole_cards=[]            },
    3: {name="PlayerX",      hole_cards=["Ah","Kh",...]},  ← FROM HAND X
    5: {name="Atros",        hole_cards=["2s","3s"]     },  ← FROM HAND X
    7: {name="PlayerY",      hole_cards=["9c","Tc"]     },  ← FROM HAND X
}
```

### Step 5: New Snapshot Arrives — Partial Update

Hand Y's PREFLOP snapshot arrives. It only has 2 visible seats (no other players are seated yet, or their cards aren't visible). The incoming `new_seats` dict has:
```
new_seats = {
    1: {name="allinstalker", hole_cards=[], ...},   ← hero, full replace
    5: {name="Atros",        hole_cards=[], ...},   ← other bot, metadata update
}
```

### Step 6: Merge — Seats NOT in New Snapshot Are Never Cleaned

**File:** `backend/app.py`, lines 1300-1317

The merge loop iterates over `new_seats.items()`:
- `sno=1`: owned by allinstalker → full replace (line 1317) → hole_cards cleared ✓
- `sno=5`: owned by Atros (different bot) → metadata update (line 1302-1313) → hole_cards only updated if `observed_cards` is non-empty (line 1312). New snapshot has empty cards → old cards SURVIVE.

Seats 3 and 7 are NOT in `new_seats` → NEVER PROCESSED → old data with old hole_cards PERSISTS.

### Step 7: Result — Mixed Hands in seats Array

After merge:
```
table["seats"] = {
    1: {name="allinstalker", hole_cards=[]            },  ← Hand Y (cleared)
    3: {name="PlayerX",      hole_cards=["Ah","Kh",...]},  ← Hand X (SURVIVED)
    5: {name="Atros",        hole_cards=["2s","3s"]     },  ← Hand X (SURVIVED)
    7: {name="PlayerY",      hole_cards=["9c","Tc"]     },  ← Hand X (SURVIVED)
}
```

### Step 8: API Returns Mixed Data

`/api/latest` → `_table_view()` → `_build_seats_list(table)` → includes ALL seats → includes stale hole_cards from Hand X.

### Step 9: Engine Renders Mixed Data

`formatTableDataToCanonical(data.table)` iterates ALL seats, extracts ALL hole_cards:
```
AhKhQdJd
2s3s
9cTc
```

The Engine textarea shows cards from BOTH Hand X and Hand Y.

---

## 3. Why the Merge Doesn't Clean Up

The seat merge at line 1300 loops over `new_seats.items()`:

```python
for sno, sdata in new_seats.items():
    ...
```

This only processes seats that EXIST in the incoming snapshot. Seats that exist in `table["seats"]` but NOT in `new_seats` are never iterated, never examined, and never removed.

There is NO garbage collection pass after the merge loop to remove seats that weren't updated. The only cleanup mechanisms are:
1. `table["seats"] = {}` on hand reset (line 1167) — **BLOCKED by guard**
2. `_cleanup_loop()` stale entry eviction (line 981) — only removes entries where all seats are empty AND last_ts > 60s

---

## 4. Is the Overlap Already in `/api/latest`?

**Yes.** The overlap originates in the backend's `_tables` storage. By the time `/api/latest` returns data, the seats array already contains hole_cards from multiple hands. The Engine does not add or mix data — it only displays what the API provides.

Verified by tracing `formatTableDataToCanonical()` (engine_flow_controls.js:83-103): it extracts ALL `hole_cards` from ALL seats. No filtering by hand context.

---

## 5. Is Hand_ID Being Propagated Correctly?

**Partially.** The `hand_id` field EXISTS in the API response and is included in `_table_view()` (line 844). The Engine does NOT read it.

More critically: `hand_id` is generated once per table entry (Initial hand) and NEVER CHANGES because the guard blocks all hand resets. The hand_id for the current allinstalker entry (`60227f46`) has been static for ~1.5 hours.

---

## 6. Is the Engine Using Hand_ID?

**No.** The Engine (`engine_flow_controls.js`) has zero references to `hand_id`. It does not:
- Read `hand_id` from the API response
- Compare `hand_id` to detect hand changes
- Clear the textarea when hand_id changes
- Filter seats by hand context

---

## 7. Is the Textarea Cleared When a New Hand Begins?

**No.** The Engine:
- Has no "clear" logic beyond `setTextareaValue()` which replaces the entire content
- The replacement content is generated from the API response
- If the API response contains stale hole_cards, the replacement still contains them
- No explicit "new hand → clear everything" path exists

---

## 8. First Component Where Data Becomes Mixed

| Component | Mixing Occurred? |
|-----------|-----------------|
| Extension (w4p.js) | No — each snapshot is internally consistent |
| POST /api/snapshot | No — payload is internally consistent |
| Backend hand detection | Yes — `_detect_new_deal()` correctly identifies hand change |
| Backend multi-bot guard | **Yes — BLOCKS the reset, preventing seats from being cleared** |
| Backend seat merge | **Yes — partial update preserves old seats not in new snapshot** |
| /api/latest response | **Yes — merged seats array contains cards from multiple hands** |
| Engine formatTableDataToCanonical | No — faithfully renders what API provides |
| Engine textarea | No — displays what formatTableDataToCanonical returns |

**The first component where data from two different hands becomes mixed is the backend's in-memory `_tables[(table_id, bot_id)]["seats"]` dictionary, at lines 1300-1317, when the merge loop preserves old seats that were not cleared by the blocked hand reset.**

---

## 8. Evidence Chain

```
1. Engine textarea shows overlapping hands
   ↓
2. Engine faithfully renders /api/latest response
   (engine_flow_controls.js:288-293)
   ↓
3. /api/latest returns _select_best_table()
   (backend/app.py:1631-1633)
   ↓
4. _select_best_table() returns the "best" per-bot entry
   (backend/app.py:1578-1604)
   ↓
5. Per-bot entry has stale hole_cards in seats array
   ↓
6. Seats were not cleared on hand change
   ↓
7. Hand reset was blocked by multi-bot guard
   (backend/app.py:1149-1159)
   ↓
8. Guard always fires because last_street_bot is never set
   (backend/app.py — field read at 1154, 1158; never written)
   ↓
9. last_street_bot was introduced in commit 5a31670 but never assigned
   ↓
ROOT CAUSE: The multi-bot hand reset guard has an uninitialized field
            (last_street_bot) that causes it to block ALL hand resets,
            not just interleaved-bot false positives.
```

---

## 9. Confidence

**Confidence: 95%**

- Code-level confirmation: guard path traced (lines 1149-1159), merge path traced (lines 1300-1317), reset path confirmed blocked (lines 1161-1188)
- Runtime evidence: 198 "Skipping reset" logs, all with `last_bot=None`
- Field verification: `last_street_bot` grepped — zero writes in entire codebase
- Engine verification: source read — no hand_id usage, no hand boundary detection

One assumption remains unverified: a live hand transition has not been observed at runtime during this investigation (only one bot active). But the code path is deterministic — when a transition occurs, the guard will block it regardless of runtime conditions.

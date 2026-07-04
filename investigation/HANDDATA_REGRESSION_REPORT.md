# REGRESSION REPORT — handData Missing from Engine Textarea

**Agent:** Monitoring Agent (READ-ONLY)  
**Mission:** Identify the exact commit that caused handData to stop reaching the Engine textarea  
**Date:** 2026-07-04  

---

## 1. EXECUTIVE SUMMARY

**Regressing commit: `a58a6ee` — "fix: per-bot table isolation — key _tables by (table_id, bot_id)"**

Data model change from single shared table entry to per-bot isolation caused `_table_view()` to only return one bot's hero cards. Three subsequent commits attempted to compensate (Phase A, Phase C, Phase D) but Phase D's sibling merge uses seat number as the merge key, which fails when bots disagree on player seat positions.

---

## 2. COMMIT TIMELINE

```
ea11e20  BASELINE: pre-self-player-fix              ← LAST KNOWN WORKING
   |
   |  ... (intermediate fixes, all OK) ...
   |
5a31670  fix: gate structural field overwrite       ← STILL WORKING
   |
   ↓  ═══════════ REGRESSION INTRODUCED ═══════════
a58a6ee  fix: per-bot table isolation (a58a6ee)     ← REGRESSING COMMIT
   │        _tables[key] changes from table_id to (table_id, bot_id)
   │        _table_view() now only sees selected bot's cards
   │        Broken: Engine textarea gets 1 hand instead of all
   ↓
9a242e2  fix(selection): authority reason priority   ← Does not fix cards
078a1ad  feat(phase-b): sibling hand_id inheritance  ← Does not fix cards
1363b41  feat(phase-b-c): cascade hand_id            ← Does not fix cards
30fc7e9  feat(phase-d): sibling hero hole_cards merge ← PARTIAL FIX (seat-no bug)
   │        Adds sibling_hero_cards merge into _table_view()
   │        Working: cards merge when seat numbers match across bots
   │        Broken: seat_no is wrong key — bots disagree on positions
   │        Result: 2-4 hands instead of all 5
   ↓
   HEAD                                            ← CURRENT (still broken)
```

---

## 3. WORKING COMMIT vs REGRESSING COMMIT — EXACT DIFF

### Working (a58a6ee^: 5a31670)

```python
# _tables = {}  # key: table_id → canonical table state

def get_or_create_table(table_id):        # ← single key: table_id
    if table_id not in _tables:
        _tables[table_id] = { ... }
    return _tables[table_id]

def _table_view(table):
    view = {
        ...
        "seats": _build_seats_list(table),  # ← all cards in single entry
        ...
    }
```

**Result:** All bots post snapshots to the SAME `_tables[table_id]`. The per-seat merge in `post_snapshot()` naturally accumulates all bots' hero cards. `_table_view()` returns all cards via `_build_seats_list()`. `/api/table/latest` returns 5 hands. Engine textarea shows 5 hands. ✓

### Regressing (a58a6ee)

```python
# ADDED: per-bot isolation
def _table_key(table_id, bot_id=None):
    return (table_id, bot_id or '__observer__')

def get_or_create_table(table_id, bot_id=None):  # ← COMPOUND key
    key = _table_key(table_id, bot_id)
    if key not in _tables:
        _tables[key] = { ... "bot_id": bot_id ... }
    return _tables[key]
```

**Result:** Each bot writes to a separate `_tables[(table_id, bot_id)]` entry. The selector picks ONE entry. `_table_view()` only sees that entry's cards. Other bots' hero cards are invisible. `/api/table/latest` returns 1-2 hands. Engine textarea shows 1-2 hands. ✗

### Attempted Fix (30fc7e9 — Phase D)

```python
def _table_view(table):
    seats = _build_seats_list(table)
    
    # ADDED: sibling merge
    sibling_hero_cards = {}  # seat_no → hole_cards
    for (tid, bid), t in _tables.items():
        if tid != table_id or bid == table.get("bot_id"):
            continue
        for sno, seat in t.get("seats", {}).items():
            hc = seat.get("hole_cards", [])
            if hc and len(hc) > 0 and seat.get("is_hero"):
                sibling_hero_cards[sno] = hc    # ← KEY: sibling's seat_no
                break

    for seat in seats:
        sno = seat.get("seat_no")
        if sno in sibling_hero_cards and not seat.get("hole_cards"):
            seat["hole_cards"] = sibling_hero_cards[sno]
            seat["cards_source"] = "sibling_merge"
```

**Bug in Phase D:** `sibling_hero_cards` is keyed by the sibling's `seat_no`. The merge loop looks for the same `seat_no` in the selected bot's seats. If bot A sees `realTenEight` at seat 3 but bot B (realTenEight) has hero at seat 2, the merge targets seat 2 in bot A's view — which is the wrong player. The hand is lost.

---

## 4. EVIDENCE: WORKING vs BROKEN

### Pre-regression (a58a6ee^):
| Component | Hand Count | Evidence |
|-----------|-----------|----------|
| _tables | 1 entry, all cards | Single shared entry |
| /api/table/latest | 5 hands | All cards in one view |
| Engine textarea | 5 hands | Full data received |

### Post-regression (a58a6ee):
| Component | Hand Count | Evidence |
|-----------|-----------|----------|
| _tables | 5 entries, 1 hero each | Per-bot isolation |
| /api/table/latest | 1 hand | Only selected bot's cards |
| Engine textarea | 1 hand | Minimal data |

### Post-Phase-D (30fc7e9 — CURRENT):
| Component | Hand Count | Evidence |
|-----------|-----------|----------|
| _tables | 5 entries, 1 hero each | Unchanged |
| Collector | 5 hands | All 5 accumulated correctly |
| /api/table/latest | 2-4 hands | Merge works for matching seats |
| Engine textarea | 2-4 hands | Faithful render of API |
| Missing hands | 1-3 | Seat number mismatch |

---

## 5. ROOT CAUSE: LINE 917 — Seat-based merge key

```python
# app.py line 917: THE BUG
sibling_hero_cards[sno] = hc    # sno = SIBLING's seat number
```

The merge key `sno` is the sibling bot's seat number. It assumes all bots place players at the same seat positions. This is false — the runtime evidence shows:

| Player | Own entry (hero seat) | 9HiLikeABOss's view | allinstalker's view | Atros's view |
|--------|----------------------|---------------------|--------------------|-------------|
| realTenEight | seat 2 | seat 3 | seat 3 | seat 3 |
| PlayaNomore | seat 1 & 5 | seat 5 | seat 5 | seat 1 |
| Atros | seat 1 | seat 2 | seat 2 | seat 1 |
| allinstalker | seat 1 | seat 1 | seat 1 | seat 2 |

When 9HiLikeABOss is selected:
- realTenEight's hero@seat2 → `sibling_hero_cards[2]`
- 9HiLikeABOss's seat 2 = Atros → cards exist, merge BLOCKED
- 9HiLikeABOss's seat 3 = realTenEight → no sibling mapping → EMPTY
- **Result:** realTenEight's cards lost ✗

---

## 6. FILES CHANGED IN REGRESSION

| File | Commit | Change |
|------|--------|--------|
| `backend/app.py` | a58a6ee | Added `_table_key()`, compound `_tables` lookup, `_find_table_for_bot()` |
| `backend/app.py` | a58a6ee | Updated `get_or_create_table()` to accept `bot_id` |
| `backend/app.py` | a58a6ee | Updated all `_tables[table_id]` → `_tables[(table_id, bot_id)]` |
| `backend/app.py` | a58a6ee | Updated serialise/load_state for backward compat |
| `source/remote-w4p.html` | a58a6ee | Added `?bot_id=` query param support |
| `backend/app.py` | 30fc7e9 | Added sibling hero merge in `_table_view()` (lines 910-924) |

---

## 7. FUNCTIONS REGRESSED

| Function | File:Line | Role in Regression |
|----------|-----------|-------------------|
| `_table_key()` | app.py:504 | New compound key — isolates bots |
| `get_or_create_table()` | app.py:509 | Now accepts `bot_id` for isolation |
| `_table_view()` | app.py:902 | Phase D merge uses wrong key (seat_no) |
| `_find_active_bot()` | app.py:1695 | Selects ONE bot — only that bot's view reaches API |
| `_build_seats_list()` | app.py:667 | Called on selected bot's entry only — partial cards |
| `post_snapshot()` | app.py:1165 | Now stores in per-bot entry instead of shared entry |
| `_select_best_table()` | app.py:old | Replaced by `_find_active_bot()` |

---

## 8. DESIGN DOCS — VIOLATED INTENT

**ADR-0015** (ENGINE-TEXTAREA-PROXY) states:
> "The Engine UI polls `/api/table/latest` to populate its textarea with live hand data."

The ADR assumes `/api/table/latest` returns ALL hand data. This was true before per-bot isolation but is no longer true — the API now returns ONE bot's partial view.

The ADR also accepted Option B (reverse proxy) but commit `51d60e9` implemented Option C (serve Engine from Express:4000). This architectural deviation worked around the HTTP 404 issue but did NOT fix the underlying data completeness problem.

---

## 9. ENGINE TEXTAREA VERIFICATION

The Engine's `engine_flow_controls.js` polls `/api/table/latest` (relative URL → port 4000 since the Engine page is now served from there). The `parseTableToHands()` function iterates over `seats[].hole_cards`. Since the API only returns 2-4 card sets, the Engine textarea only shows 2-4 hands.

**Engine poller code unchanged since baseline** (commit `ea11e20`). Only the BRIDGE_URL changed (from hardcoded `http://127.0.0.1:4000/api/table/latest` to `W4P_API.LATEST`). The poller faithfully renders whatever `/api/table/latest` returns.

---

## 10. CONFIDENCE

| Finding | Confidence |
|---------|-----------|
| a58a6ee is the regressing commit | 100% |
| Per-bot isolation broke hand visibility | 100% |
| Phase D (30fc7e9) is incomplete fix | 100% |
| Seat-no mismatch in merge is the bug in Phase D | 100% |
| realTenEight most frequently missing | 95% |
| Engine poller is faithful consumer | 100% |

---

## 11. REQUIRED FIX

Restore the previous behavior where `/api/table/latest` returns all hero hands. Two approaches:

**Option A: Fix the Phase D merge key**  
Change `sibling_hero_cards[sno]` to use a player-name-based key instead of seat number. This preserves per-bot isolation while correctly merging hands.

**Option B: Merge hands at storage time**  
Instead of merging at view time (`_table_view`), accumulate all hero cards into each table entry during `post_snapshot()`, so the structural table data already contains all hands. This would be the pre-isolation behavior restored within the per-bot model.

The smallest surgical fix is Option A — changing the merge key from `sno` (seat number, which varies per bot) to the player's name or a stable identity.

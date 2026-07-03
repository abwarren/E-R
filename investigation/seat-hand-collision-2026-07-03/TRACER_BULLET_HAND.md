# TRACER BULLET HAND — Seat/Hand Collision Investigation

**Date:** 2026-07-03
**Status:** READ-ONLY
**Hand Tracked:** `hand_id=339aec5c` (Atros's perspective)

---

## 1. Hand Profile

| Field | Value |
|-------|-------|
| hand_id | 339aec5c-e800-4a00-9e0c-a3f28e5b6232 |
| table_id | pb_2589955 |
| bot_id | Atros |
| street | PREFLOP |
| pot_zar | 40 |
| dealer_seat | 1 |
| state_version | 1372 |
| board | flop=[], turn=None, river=None |

### Seats Observed

| Seat | Player | Hero | Status | Cards | Stack |
|------|--------|------|--------|-------|-------|
| 4 | monarchi | False | folded | 0 | 61.46 |
| 5 | Atros | True | playing | 6 (AcKhQs8h6d5c) | 59.43 |

---

## 2. Tracer Bullet — Every Hop

### T=0: GoldRush DOM

Atros's Chrome extension instance observes:
- PokerBet URL: `https://poker-web.goldrush.co.za/1875356/#/product/3/3/cash-cat/1/cash/1148/tbl/2589955`
- Table ID derived: `pb_2589955` (parsed from URL: tbl/2589955)
- Bot identity: `Atros` (configured in extension)
- Seat 4: monarchi visible, folded, stack=61.46
- Seat 5: Atros (self), playing, hole cards=[Ac, Kh, Qs, 8h, 6d, 5c]
- No board cards, pot=40 (blinds posted)
- Dealer at seat 1
- Atros has no available_actions (not his turn)
- tick=718

### T+0ms: Extension buildSnapshot()

**File:** `source/w4p.js`, lines 1415-1434

Snapshot payload constructed:
```json
{
  "table_id": "pb_2589955",
  "bot_id": "Atros",
  "hand_id": "339aec5c-...",  // echoed from backend
  "street": "PREFLOP",
  "pot_zar": 40,
  "dealer_seat": 1,
  "board": {"flop": [], "turn": null, "river": null},
  "seats": {
    "4": {"name": "monarchi", "status": "folded", "stack_zar": 61.46, ...},
    "5": {"name": "Atros", "is_hero": true, "hole_cards": ["Ac","Kh","Qs","8h","6d","5c"], ...}
  },
  "available_actions": []
}
```

### T+50ms: POST /api/snapshot → Express → Flask :1080

- Express proxies to Flask :1080
- `post_snapshot()` accepted: `bot_id=Atros, seats=2`
- `_store_lock` acquired
- Table retrieved: `_tables[("pb_2589955", "Atros")]`
- `hero_active = bool(payload.get('available_actions'))` = False
- Structural fields NOT overwritten (hero_active guard)
- Seat 4 (monarchi): different bot → metadata update only
- Seat 5 (Atros): same bot → full replace
- `last_ts` updated to current time

### T+75ms: Hand_id check

- `incoming_hand_id = "339aec5c-..."` matches `current_hand_id`
- `hand_changed = False`
- No reset performed

### T+150ms: API Consumer Reads

#### Engine polls (1500ms cycle)
- `pollLatest()` → `fetch("http://localhost:5002/api/latest")`
- Engine Flask proxies → `er-remote:4000/api/latest`
- `_select_best_table()` called
- At time T+150: if Atros's entry has highest last_ts → hand 339aec5c returned
- `formatTableDataToCanonical(table)` → extracts:
  - Atros: "AcKhQs8h6d5c" (hero, seat 5)
  - monarchi: no cards visible (non-hero)
- If text differs from lastSnapshotHash → textarea overwritten

#### Remote UI long-polls (25s timeout)
- Same handler, same result
- Renders seat grid: seats 4 (monarchi, folded), 5 (Atros, hero, playing)

---

## 3. The Other Hands (Simultaneous)

At the same instant, two other bots are observing DIFFERENT game contexts:

### Hand 27d1d74e (monarchi's perspective)
- monarchi is hero at seat 4, playing, cards=[As,Jh,9c,7d,4c,4s]
- No other players visible
- For monarchi: "The hand I'm playing with AsJh9c..."
- For Atros: monarchi appears as folded

### Hand 60227f46 (allinstalker's perspective)  
- allinstalker is hero at seat 1, sitting_out
- Atros visible at seat 5, sitting_out
- For allinstalker: "I'm waiting to get back in the game"
- For Atros: this is an entirely different table state

**These are THREE different game contexts, not three views of the same table.**

---

## 4. Evidence That These Are Different Hands

1. **Different hole card sets:**
   - monarchi's entry: As,Jh,9c,7d,4c,4s (at seat 4, hero)
   - Atros's entry: Ac,Kh,Qs,8h,6d,5c (at seat 5, hero), monarchi at seat 4 has NO cards
   - allinstalker's entry: no hole cards visible at all

2. **Different game state:**
   - monarchi's entry: pot=40, dealer=2
   - Atros's entry: pot=40, dealer=1  
   - allinstalker's entry: pot=0, dealer=1

3. **Same players with conflicting states:**
   - monarchi: hero/playing (own entry) vs non-hero/folded (Atros's entry)
   - Atros: hero/playing (own entry) vs non-hero/sitting_out (allinstalker's entry)

4. **Different hand_ids:**
   - 3 distinct UUID4 values confirm the backend generated 3 separate hand identifiers

---

## 5. Tracer Bullet Conclusion

The hand tracked (339aec5c, Atros) maintains its identity from extension through backend storage. The identity chain is preserved within Atros's per-bot entry. 

**The problem is NOT within a single hand's pipeline** — it is at the point where the API must choose WHICH hand to present to consumers.

The API selector (`_select_best_table`) faces an impossible choice: 3 legitimate hand contexts exist, but the API can only return one. The selector picks based on freshness (last_ts), which changes with every bot POST. This creates the oscillation.

---

## 6. Timestamp Timeline

```
1783051198.960 — Atros POST → hand 339aec5c v=1148
1783051199.070 — monarchi POST → hand 27d1d74e v=1128  
1783051198.966 — allinstalker POST → hand 60227f46 v=4967
1783051200.271 — monarchi POST → hand 27d1d74e v=1132 [API SELECTED]
1783051219.751 — Atros POST → hand 339aec5c v=1372 [API SELECTED]
1783051275.451 — monarchi POST → hand 27d1d74e v=1381
1783051291.958 — allinstalker POST → hand 60227f46 v=5060
1783051292.493 — Atros POST → hand 339aec5c v=1458 [API SELECTED]
```

The [API SELECTED] entries show which hand the `/api/latest` endpoint would return at that moment — it changes with each bot's POST cycle.

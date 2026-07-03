# SEAT_OWNERSHIP_ANALYSIS.md
## W4P Seat Ownership Analysis — `_seat_bots` and Identity Stability

**Date:** 2026-07-03
**Repository:** /home/wa/projects/poker/E&R

---

## 1. Mapping Architecture

Two bidirectional maps govern seat ownership:

```python
# backend/app.py, lines 186-187
_bot_seats = {}   # key: bot_id → {"table_id": str, "seat_no": int, "last_seen": float}
_seat_bots = {}   # key: (table_id, seat_no) → bot_id
```

### Update Path (lines 466-492)

```python
def update_bot_seat_mapping(bot_id, table_id, seat_no):
    if not bot_id or bot_id == 'unknown-bot':
        return  # Don't track unknown bots

    ts = time.time()

    _bot_seats[bot_id] = {
        "table_id": table_id,
        "seat_no": seat_no,
        "last_seen": ts
    }

    # Remove any previous mapping for this bot on this table
    for (tid, sno), bid in list(_seat_bots.items()):
        if tid == table_id and bid == bot_id:
            del _seat_bots[(tid, sno)]

    seat_key = (table_id, seat_no)
    _seat_bots[seat_key] = bot_id
```

### Trigger Point (lines 1286-1288)

```python
if hero_seat_no is not None:
    if bot_id:
        update_bot_seat_mapping(bot_id, table_id, hero_seat_no)
```

Called ONLY when a hero seat is found in the incoming snapshot. Non-hero seats never trigger mapping updates.

---

## 2. Persistence and Lifespan

### Persistence (lines 875-881)
```python
result["__bot_state__"] = {
    "seat_bots": {f"{tid}:{sno}": bid for (tid, sno), bid in _seat_bots.items()},
    "bot_seats": {
        bid: {"table_id": ..., "seat_no": ..., "last_seen": ...}
        for bid, i in _bot_seats.items()
    }
}
```

### Restoration on startup (lines 891-899)
Mappings are loaded from `state_snapshot.json` on Flask startup.

### Survival across hand resets (line 1138)
```python
# NOTE: _seat_bots is NOT cleared — bot identity persists across hands.
```

### Eviction (lines 938-947)
Seats evicted when `last_seen` exceeds `SEAT_TTL` (30s default). Eviction cleans all associated state including `_seat_bots`.

---

## 3. Does `_seat_bots` Drift Over Time?

### Scenario 1: Same seat, same bot (normal play)
```
Bot ID: monarchi, Seat: 3
Every POST: update_bot_seat_mapping("monarchi", pb_2589955, 3)
  → Removes any old (pb_2589955, *) for monarchi
  → Sets (pb_2589955, 3) = "monarchi"
Result: STABLE. Same bot, same seat.
```

### Scenario 2: Bot changes seat between hands
```
Hand 1: monarchi at seat 3
  _seat_bots[(pb_2589955, 3)] = "monarchi"

Hand 2: monarchi at seat 5 (seat changed in lobby)
  POST arrives:
    → Removes (pb_2589955, 3) for monarchi
    → Sets (pb_2589955, 5) = "monarchi"
  Old entry (pb_2589955, 3) is correctly cleared.
Result: CORRECT DRIFT. Mapping follows the bot.
```

### Scenario 3: Bot reconnects (same table)
```
Before reconnect:
  _seat_bots[(pb_2589955, 3)] = "monarchi"

After reconnect (30s TTL → old entry evicted beforehand):
  _seat_bots[(pb_2589955, 3)] — stale, evicted
  New POST: update_bot_seat_mapping("monarchi", pb_2589955, 3)
    → Sets (pb_2589955, 3) = "monarchi"

If reconnect happens WITHIN 30s:
  old (pb_2589955, 3) = "monarchi" still exists
  New POST from monarchi at seat 3:
    → Removes old (pb_2589955, 3) for monarchi → re-adds (pb_2589955, 3) = "monarchi"
Result: CORRECT. No drift.
```

### Scenario 4: Bot joins different table
```
Old: bot_seats["monarchi"] = {table_id: "pb_2589955", seat_no: 3}
New: bot POSTs to pb_9999999 at seat 2
  update_bot_seat_mapping("monarchi", "pb_9999999", 2)
    → for (tid, sno), bid in _seat_bots:
      if tid == "pb_9999999" and bid == "monarchi":
        — NO match (old entry is pb_2589955, NOT pb_9999999)
    → Sets (pb_9999999, 2) = "monarchi"
⚠️ OLD ENTRY (pb_2589955, 3) = "monarchi" IS NOT REMOVED!
```

**BUG FOUND:** `update_bot_seat_mapping` only removes entries where `tid == table_id AND bid == bot_id`. If a bot moves to a DIFFERENT table, the old table's entry is ORPHANED.

This would only matter if the bot returns to the old table, but it's a leak. The cleanup loop would eventually evict the stale entry after 30s.

### Scenario 5: Bot disconnects and another bot takes that seat
```
Seat 3: monarchi disconnects
  30s TTL → (pb_2589955, 3) evicted → cleaned

New bot "Atros" at seat 3:
  POST arrives → hero_seat_no=3
  update_bot_seat_mapping("Atros", pb_2589955, 3)
    → Sets (pb_2589955, 3) = "Atros"
Result: CORRECT. Old mapping evicted before new one created.
```

---

## 4. Merge Behavior Based on Ownership

The critical merge decision at lines 1249-1266:

```python
existing_bot = _seat_bots.get((table_id, sno))
if existing_bot and bot_id and existing_bot != bot_id:
    # SEAT OWNED BY DIFFERENT BOT — metadata update only
    existing["stack_zar"] = ...
    existing["status"] = ...
    existing["is_dealer"] = ...
    existing["last_seen"] = ...
    # hole_cards updated if present
else:
    # SEAT OWNED BY POSTING BOT (OR UNOWNED) — full replace
    table["seats"][sno] = sdata
```

| Incoming Bot | Seat Owner | Merge Behavior | is_active Preserved? | available_actions Preserved? |
|-------------|-----------|---------------|---------------------|---------------------------|
| monarchi | monarchi | Full replace | From monarchi's data | From monarchi's data |
| Atros | monarchi | Metadata only | ✓ (not touched) | ✓ (not touched) |
| Atros | Atros | Full replace | From Atros's data | From Atros's data |
| Atros | None | Full replace | From Atros's data | From Atros's data |

**Key Insight:** Seat-level `is_active` and `available_actions` are OWNERSHIP-PROTECTED. They only change when the seat's OWNER posts a snapshot. Other bots' observations cannot override them.

---

## 5. Problematic Field: `is_dealer`

Line 1257:
```python
existing["is_dealer"] = sdata.get("is_dealer", existing.get("is_dealer"))
```

The `is_dealer` field is INCLUDED in the metadata update. This means when Bot B (Atros) observes seat 3 (owned by monarchi) and sees monarchi is NOT the dealer, it overwrites monarchi's `is_dealer` to false.

**Result:** The dealer chip can oscillate based on which bot last posted, because:
1. Each bot observes the dealer from the DOM independently
2. Bot A sees seat 3 is dealer → sets `is_dealer=true` on full replace (seat 3 owned by Bot A)
3. Bot B sees seat 5 is dealer (different table perspective) → metadata update on seat 3 sets `is_dealer=false`
4. Bot A posts again → full replace → `is_dealer=true` again

This is a **secondary oscillation vector** distinct from the primary street/board oscillation.

---

## 6. Ownership Drift Risk Assessment

| Scenario | Drift Risk | Mechanism | Duration |
|----------|-----------|-----------|----------|
| Same seat, same bot | NONE | Full re-assignment each POST | N/A |
| Bot changes seat (same table) | NONE | Old mapping removed by bot_id scan | N/A |
| Bot reconnects (same table) | WITHIN 30s: NONE<br/>AFTER 30s: NONE | Eviction clears stale; re-add correct | N/A |
| Bot moves to different table | **ORPHAN LEAK** | Old (tid,sno) not cleaned | 30s (eviction) |
| Other bot takes vacated seat | **RACE CONDITION** | If < 30s since eviction, old mapping blocks | < 30s |
| Hand reset oscillation | NONE | `_seat_bots` survives reset; hero re-asserts | N/A |

---

## 7. Conclusion

**`_seat_bots` drift is NOT the primary cause of the observed flicker.**

The mapping is refreshed on every hero POST. The algorithm correctly handles same-table seat changes and reconnects. The only bug is an orphan leak when a bot moves to a different table (cleaned within 30s).

The primary flicker source remains the unconditional overwrite of structural fields (`street`, `board`, `pot_zar`, `dealer_seat`) at the table level, combined with the hand-reset detection's fragility when two bots are observing different hands.

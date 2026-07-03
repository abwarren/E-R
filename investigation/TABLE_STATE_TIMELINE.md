# TABLE_STATE_TIMELINE.md
## W4P Table State Timeline — Merge-by-Merge Trace

**Date:** 2026-07-03
**Repository:** /home/wa/projects/poker/E&R

---

## 1. State Machine Model

The table state in `_tables["pb_2589955"]` is a single mutable dictionary with these volatile fields:

| Field | Set By | Overwrite Policy | Oscillation Risk |
|-------|--------|-----------------|-----------------|
| `street` | app.py:1148 | Unconditional | **HIGH** |
| `board` | app.py:1150 | Unconditional | **HIGH** |
| `pot_zar` | app.py:1149 | Unconditional | **HIGH** |
| `dealer_seat` | app.py:1152 | Unconditional | **HIGH** |
| `variant` | app.py:1151 | Unconditional | LOW (always "plo") |
| `state_version` | app.py:1268 | Monotonic increment | N/A |
| `last_ts` | app.py:1267 | Unconditional | N/A |
| `hand_key` | app.py:1120 | On hand reset | N/A |
| `seats` | app.py:1123,1249-1266 | Merge or clear | **MEDIUM** |
| `active_player` | app.py:1271-1275 | Conditional | MEDIUM |
| `raw_batch` | app.py:1125,1296 | Clear or sync | LOW |

---

## 2. Timeline — Two-Bot Scenario

**Bots:** `monarchi` (Bot A), `Atros` (Bot B)
**Table:** `pb_2589955`

### Phase 1: Normal Operation — Both Bots Same Hand

```
seq=1   [Bot A] POST /api/snapshot
        bot_id=monarchi  street=PREFLOP  board=[]  pot=0  dealer=5
        hand_key=pb_2589955:implicit
        seats: [Seat3=monarchi(hero, active=false, acts=[]), Seat6=Atros, ...]
        ─────────────────────────────────────────────────
        TABLE STATE after merge:
          street=PREFLOP  board={}  pot=0  dealer=5
          _seat_bots: (pb_2589955,3)=monarchi
          _bot_actions: monarchi=[]
        ─────────────────────────────────────────────────

seq=2   [Bot B] POST /api/snapshot (~150ms later)
        bot_id=Atros  street=PREFLOP  board=[]  pot=0  dealer=5
        hand_key=pb_2589955:implicit
        seats: [Seat3=monarchi, Seat6=Atros(hero, active=false, acts=[]), ...]
        ─────────────────────────────────────────────────
        TABLE STATE after merge:
          street=PREFLOP  board={}  pot=0  dealer=5
          _detect_new_deal: no (same street)
          hand_key collision: pb_2589955:implicit — NO reset
          Seat3 owned by monarchi → metadata update only
          Seat6 → full replace (Atros is new owner)
          _seat_bots: (pb_2589955,3)=monarchi, (pb_2589955,6)=Atros
        ─────────────────────────────────────────────────

seq=3   [Bot A] POST (~300ms)
        street=PREFLOP  board=[]  — same state, no change
        ─────────────────────────────────────────────────
        TABLE: stable. Both bots on PREFLOP of same hand.
        ─────────────────────────────────────────────────
```

**Phase 1 Duration:** Minutes (normal play). State is coherent as long as both bots are synchronized in the same hand at the same street.

### Phase 2: Divergence — Different Hands

```
seq=N   [Bot A] POST — Hand X proceeds to FLOP
        bot_id=monarchi  street=FLOP  board=[2s,3s,4s]  pot=12.50
        4+ cards visible across seats
        hand_key=pb_2589955:cards:4:a1b2c3d4e5f6g7h8  ⬅ NEW HAND KEY
        ─────────────────────────────────────────────────
        TABLE STATE:
          street=FLOP  board={flop:[2s,3s,4s]}  pot=12.50
          hand_key=pb_2589955:cards:4:<hashA>
          seats: [Seat3=monarchi(hero,acts=[fold,call,raise]), Seat6=Atros, ...]
        ─────────────────────────────────────────────────

seq=N+1 [Bot B] POST — Still on PREFLOP of OLD hand!
        bot_id=Atros  street=PREFLOP  board=[]  pot=0
        hand_key=pb_2589955:implicit  ⬅ SAME AS BEFORE
        ⚠ DIFFERENT HAND — Bot B hasn't progressed past PREFLOP
        ─────────────────────────────────────────────────
        _detect_new_deal:
          current_street=FLOP  incoming_street=PREFLOP
          STREET_ORDER: FLOP(2) → PREFLOP(0)  → 0 < 2 → TRUE
          ⚠ HAND RESET TRIGGERED
        ─────────────────────────────────────────────────
        RESET ACTIONS (lines 1117-1146):
          ✓ table["hand_key"] = "pb_2589955:implicit"
          ✓ table["seat_map"] = {}
          ✓ table["seats"] = {}
          ✓ table["next_seat_no"] = 1
          ✓ table["raw_batch"] = None
          ✓ _hero_cards cleared for pb_2589955
          ✓ _coll_accumulated_hands = []
          ✓ command_queue flushed
          ✓ cashout_state flushed
          ✗ _seat_bots NOT cleared (line 1138)
        ─────────────────────────────────────────────────
        POST-RESET TABLE STATE:
          street=PREFLOP  board={}  pot=0  dealer=null
          seats={}  ⬅ EMPTY — Bot A's seat data lost
          hand_key=pb_2589955:implicit
          _seat_bots: (pb_2589955,3)=monarchi, (pb_2589955,6)=Atros  ⬅ SURVIVED
        ─────────────────────────────────────────────────
        SEAT REBUILD: Bot B's seats populate the empty table
          Seat6=Atros(hero, active=false, acts=[])
          Seat3=monarchi (observed by Bot B, name only)
        ─────────────────────────────────────────────────

seq=N+2 [Bot A] POST — STILL on FLOP of Hand X!
        bot_id=monarchi  street=FLOP  board=[2s,3s,4s]  pot=12.50
        hand_key=pb_2589955:cards:4:<hashA>
        ─────────────────────────────────────────────────
        _detect_new_deal:
          current_street=PREFLOP  incoming_street=FLOP
          FLOP(2) > PREFLOP(0) → no regression → NO reset
        ─────────────────────────────────────────────────
        is_first_real check (line 1113-1116):
          hand_key = pb_2589955:cards:4:<hashA>
          current hand_key = pb_2589955:implicit
          → hand_key starts with "pb_2589955:cards:" but current is "implicit"
          → is_first_real = TRUE → ⚠ ANOTHER HAND RESET!
        ─────────────────────────────────────────────────
        RESET AGAIN:
          seats={}, seat_map={}, raw_batch=None, hero_cards cleared
        ─────────────────────────────────────────────────
        POST-RESET:
          street=FLOP  board={flop:[2s,3s,4s]}  pot=12.50
          hand_key=pb_2589955:cards:4:<hashA>
          seats: [Seat3=monarchi(hero,active=true,acts=[fold,call,raise])]
        ─────────────────────────────────────────────────

seq=N+3 [Bot B] POST — STILL PREFLOP of old hand
        street=PREFLOP  board=[]  pot=0
        ─────────────────────────────────────────────────
        _detect_new_deal: FLOP→PREFLOP → regression → HAND RESET
        ─────────────────────────────────────────────────
        ... cycle repeats from N+1 ...
```

### Phase 3: Oscillation (Cyclic)

```
    ┌───────────────────────────────────────────────────────┐
    │                                                       │
    ▼                                                       │
┌─────────┐   Bot A: FLOP    ┌─────────┐   Bot B: PREFLOP │
│ FLOP    │ ──────────────►  │ PREFLOP │ ──────────────►   │
│ board=X │                  │ board=[]│                   │
│ pot=12  │                  │ pot=0   │                   │
└─────────┘                  └─────────┘                   │
    │                            │                         │
    │ Bot A: FLOP                │ Bot B: PREFLOP          │
    │ (hand reset triggers       │ (hand reset triggers    │
    │  because is_first_real)    │  because street regress)│
    │                            │                         │
    └────────────────────────────┘                         │
                                                           │
              CYCLE REPEATS (~600ms period)                │
              Remote UI sees: FLOP ⇄ PREFLOP ⇄ FLOP ...   │
```

---

## 3. Timeline — Inactive Hero Overlay

### Scenario: Bot A is active, Bot B is idle (sitting out)

```
seq=K   [Bot A] POST
        hero=true  is_active=true  available_actions=[fold,call,raise]
        street=FLOP  board=[2s,3s,4s]  pot=12.50
        ────────────────────────────────
        TABLE: street=FLOP, board=set, pot=12.50
        Seat3.monarchi: is_active=true, acts=[fold,call,raise]
        ────────────────────────────────

seq=K+1 [Bot B] POST (~150ms)
        hero=true  is_active=false  available_actions=[]
        street=PREFLOP  board=[]  pot=0  ⬅ DIFFERENT HAND
        ────────────────────────────────
        TABLE: street=PREFLOP, board={}, pot=0  ⬅ OVERWRITTEN
        Seat3.monarchi (owned by monarchi → metadata update):
          is_active preserved (NOT in metadata update list)
          available_actions preserved
        Seat6.Atros: full replace with is_active=false, acts=[]
        ────────────────────────────────

seq=K+2 [Bot A] POST (~150ms)
        street=FLOP  board=[2s,3s,4s]  pot=12.50
        ────────────────────────────────
        TABLE: street=FLOP, board=set, pot=12.50  ⬅ BACK
        ────────────────────────────────
```

**Result:** When Bot B's inactive snapshot carries a different street, the structural fields flash. The seat-level `is_active` and `available_actions` are protected by seat ownership, but the table-level fields are not protected.

---

## 4. Seat Ownership Mapping Trace

### How `_seat_bots` evolves during oscillation:

```
State after seq=N (Bot A FLOP):
  _seat_bots = {
    (pb_2589955, 3) → "monarchi",
    (pb_2589955, 6) → "Atros"
  }

HAND RESET at seq=N+1 (Bot B PREFLOP):
  table["seats"] = {}        ⬅ seats cleared
  _seat_bots NOT cleared     ⬅ mapping survived

Bot B rebuilds seats from its snapshot:
  Seat6=Atros(hero) → update_bot_seat_mapping("Atros", pb_2589955, 6)
    → removes old (pb_2589955, 6) for Atros → re-adds (pb_2589955, 6) → "Atros"
    → removes any other seat owned by Atros on pb_2589955
  Seat3=monarchi → not hero, no mapping update
  ⚠ (pb_2589955, 3) still maps to "monarchi"

HAND RESET at seq=N+2 (Bot A FLOP):
  table["seats"] = {}
  Bot A rebuilds:
    Seat3=monarchi(hero) → update_bot_seat_mapping("monarchi", pb_2589955, 3)
      → removes (pb_2589955, 3) for monarchi → re-adds (pb_2589955, 3) → "monarchi"
```

**Observed:** `_seat_bots` is refreshed each time a bot posts as hero. The mapping remains **consistent** across oscillations — `monarchi` stays at seat 3, `Atros` stays at seat 6. Seat ownership is NOT the flicker source.

---

## 5. `/api/latest` Response Trace

The Remote UI polls `/api/latest` with long-polling (25s timeout, line 725 of remote-w4p.html).

The handler at line 1550 returns:
```python
table = max(_tables.values(), key=lambda t: t['last_ts'])
```

Since there's only `pb_2589955`, this returns the single table entry. The `ts` field was set at line 1267:
```python
table["last_ts"] = ts
```

The Remote UI receives the complete `_table_view(table)` output, which includes:
- `street`, `board`, `pot_zar`, `dealer_seat` — from table-level fields (last writer wins)
- `seats` — from `_build_seats_list(table)` (ownership-protected merge)
- `state_version` — monotonic counter

The Remote UI at line 736 checks:
```javascript
if (json === _lastTableJSON) { schedulePoll(); return; }
```

So if two consecutive states are identical (same street, same board, same seats), no re-render occurs. But during oscillation, every other state is different → re-rendering required.

---

## 6. Summary

| Phase | State | Duration | Stability |
|-------|-------|----------|-----------|
| Phase 1: Same hand, same street | Coherent | Minutes | Stable |
| Phase 2: Hand divergence detected | Oscillating | ~600ms cycles | **Flickering** |
| Phase 3: Steady oscillation | Cyclic | Until hands re-sync | **Flickering** |

The oscillation is triggered when one bot's hand progresses to a different street than another bot's hand. The first trigger causes a state convergence failure that perpetuates as long as the bots are in different hands.

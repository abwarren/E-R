# HAND_IDENTIFICATION_ANALYSIS.md
## What Uniquely Identifies a Poker Hand in the W4P Pipeline?

**Date:** 2026-07-03
**Status:** READ-ONLY investigation

---

## 1. What the Extension Sends

The w4p.js extension builds a snapshot at lines 1415-1434:

```javascript
var snap = {
    table_id:      tableId,          // from URL: pb_2589955
    bot_id:        heroName,         // from .self-player name: "monarchi"
    session_id:    _sessionId,       // UUID generated at script load
    seats:         seats,            // scraped from DOM
    board:         { flop, turn, river },
    pot_zar:       potZar,
    dealer_seat:   dealerSeat,
    street:        street,           // derived from board card count
    variant:       'plo',
    buttons:       buttons,
    available_actions: avail,
    active_player: activePlayerName,
    ts:            new Date().toISOString(),
    source_key:    'w4p_inject'
};
```

**Fields NOT present:**
- `deal_id` — no deal identifier
- `hand_id` — no hand identifier
- `hand_epoch` — no epoch number
- `game_id` — no game identifier
- Any UUID or timestamp from the PokerBet client

**`table_id` derivation** (w4p.js lines 481-500):

```javascript
function getTableId() {
    var url = location.href;
    // Extracts numeric ID from PokerBet URL paths:
    //   /tbl/2589955 → pb_2589955
    //   /poker/2589955 → pb_2589955
    //   openGames=2589955 → pb_2589955
    //   game-id=2589955 → pb_2589955
    //   skillgames domain with 187NNN → pb_187NNN
}
```

The `table_id` is a URL-based identifier, not a poker-hand identifier. Two bots at the same table share the same URL and thus the same `table_id`.

---

## 2. What the Backend Derives

The backend's `make_hand_key()` (app.py lines 376-396) tries three strategies:

### Strategy A: `deal_id` from payload (line 377-379)
```python
deal_id = payload.get('deal_id')
if deal_id:
    return f"{payload.get('table_id')}:deal:{deal_id}"
```
**Status: NEVER USED.** The extension does not send `deal_id`. This code path is dead.

### Strategy B: Card fingerprint hash (lines 384-395)
```python
all_cards = []
for s in seats:
    cards = s.get('hole_cards') or []
    for c in cards:
        if isinstance(c, str) and len(c) == 2:
            all_cards.append(c.lower())
if len(all_cards) >= 4:
    h = hashlib.sha256(','.join(all_cards).encode()).hexdigest()[:16]
    return f"{tid}:cards:{len(all_cards)}:{h}"
```
**Status: WORKS for FLOP/TURN/RIVER but FAILS for PREFLOP.**
At PREFLOP, each bot only sees its own 2 hole cards → `len(all_cards) = 2` → threshold not met → falls through.

### Strategy C: Implicit key (line 396)
```python
return f"{tid}:implicit"
```
**Status: ALWAYS USED at PREFLOP.** This produces the SAME key for ALL bots, making different hands indistinguishable.

### Hand Detection (lines 399-418)

`_detect_new_deal()` uses two signals:
1. **Street regression** — if street goes backwards (FLOP→PREFLOP), treat as new hand
2. **Board clearing** — if board was non-empty and incoming is empty at PREFLOP, treat as new hand

Both are fragile when two bots are interleaving and potentially at different streets.

---

## 3. What the Database Model Has

`db_logger.py` defines a complete `hand_id`-based schema:

- `hand_results` table: `hand_id` PRIMARY KEY, `table_id`, `started_at`, `street_count`, `board_flop`, `board_turn`, `board_river`, `pot_final`, `status`, `winner_*`, `num_players`, `num_showdown`
- `hand_actions` table: `hand_id`, `table_id`, `street`, `action_seq`, `seat_no`, `player_name`, `action`, `amount`, etc.
- Functions: `start_hand(hand_id, table_id, ...)`, `update_hand_street(hand_id, street, ...)`, `end_hand(hand_id, ...)`

**But none of this is wired into the live table state in `app.py`.** The `hand_id` model exists for durable logging but the in-memory `_tables` dict has no `hand_id` key.

---

## 4. What Could Serve as a Hand Identifier

### Option 1: Backend-generated UUID

The backend generates a `hand_id` when it detects a new hand (first PREFLOP after a hand ends, or first snapshot at a new table). This `hand_id` is returned in the snapshot response. The extension stores it and includes it in subsequent POSTs.

**Requirements:**
- Extension modification: store and re-send `hand_id`
- Backend modification: generate and return hand_id
- Works for same-table-same-hand multi-bot: all bots get same hand_id
- Works for different-table collision: different hand_ids

### Option 2: Dealer rotation + board sequence (deterministic)

A stable hand identifier can be derived from:
- `dealer_seat` at start of hand
- Seat composition (which players, in which order)

This is how poker tracking software (PT4, HEM) identifies hands.

**Requirements:**
- No extension changes
- Pure backend derivation
- Works within a single bot's stream
- Requires cross-bot correlation for same-hand detection

### Option 3: Hybrid (URL + heuristic combination)

Combine:
- `table_id` from URL
- Player name set (who's at the table)
- Dealer position
- Board card fingerprint (when available)

This provides progressively stronger identification as the hand progresses.

### Option 4: `hand_epoch` from the `buffer` module

The backend already has a `hand_epoch` counter in `buffer.py` that increments on board changes. The `push_snapshot()` function stamps each buffer frame with the current epoch (line 42):
```python
frame = {
    'data': snapshot_dict,
    'seq': _seq,
    'ts': time.time(),
    'hand_epoch': _hand_epoch,
}
```

But this epoch is NOT returned to the extension in the POST response, so the extension never echoes it back.

---

## 5. The Same-Table vs Different-Table Question

This is the critical unresolved question from the investigation:

**Scenario S1: Same physical table, different seats**
- Bot A (monarchi) sits at Seat 3
- Bot B (Atros) sits at Seat 6
- Both load the same URL: `pokerbet.com/tbl/2589955`
- Both see the SAME board, SAME street, SAME pot, SAME dealer
- Both see DIFFERENT hole cards, DIFFERENT available_actions, DIFFERENT is_active

**Scenario S2: Different physical tables (or different hands at same table)**
- Bot A sees FLOP with board [2s,3s,4s]
- Bot B sees PREFLOP with board []
- This can ONLY happen if they are at different tables or different game instances

**How to determine:**
If runtime logs show oscillating `street` values from two bots with the SAME `table_id`, and the streets genuinely differ (PREFLOP vs FLOP), then Scenario S2 is confirmed — they are at different game contexts.

If runtime logs show the SAME street but different available_actions, then Scenario S1 — same table, different seats.

---

## 6. Recommendation

The current architecture has no stable hand identifier in the snapshot pipeline. The `deal_id` hook exists in `make_hand_key()` but is never populated by the extension.

**For the ADR:** The choice of state isolation strategy depends heavily on whether Scenario S1 or S2 is occurring. Both should be evaluated as design options, with the assumption that:
- The chosen strategy must handle BOTH scenarios
- Runtime verification is needed to determine which scenario is active
- A hand identifier will need to be generated (either backend-side or by modifying the extension)

The `db_logger.py` hand_id infrastructure is a strong precedent — it shows the architecture already acknowledges that hands need unique identifiers. The gap is that the live state model in `_tables` doesn't use them.

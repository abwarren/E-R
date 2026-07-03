# VERTICAL_SLICE_TRACE.md
## W4P — One Hand Through Every Stage

**Date:** 2026-07-03
**Investigation:** READ-ONLY

---

## Vertical Slice: Hand X (pb_2589955, bot=Atros)

This traces a hypothetical hand through every layer, based on code analysis and runtime log evidence from 2026-07-03. The trace is anchored to actual log timestamps (±150ms resolution).

### Stage 1: GoldRush DOM

```
https://poker-web.goldrush.co.za/1875356/#/product/3/3/cash-cat/1/cash/1148/tbl/2589955
```

PokerBet renders 9 seats around a poker table. DOM elements for each seat include:
- `.name-plate` — player name
- `.hand-value` — hole cards (hero only)
- `.action-button` — available actions
- `.stack` — chip amount
- `.dealer-chip` — dealer indicator

### Stage 2: Extension Scrape

**File:** `source/w4p.js`
**Function:** `buildSnapshot()` at lines ~1415-1434

```javascript
var snap = {
    table_id:      "pb_2589955",
    bot_id:        "Atros",
    session_id:    "<uuid>",
    seats:         [...],  // 2-9 seats parsed from DOM
    board:         { flop: [], turn: None, river: None },
    pot_zar:       0,
    dealer_seat:   2,
    street:        "PREFLOP",
    variant:       "plo",
    available_actions: [],
    ...
};
```

Polling interval: 300ms. No dedup. Always sends.

### Stage 3: POST /api/snapshot

```
POST /api/snapshot HTTP/1.1
Host: 127.0.0.1:1080 (via Express :4000)
Content-Type: application/json

{
  "table_id": "pb_2589955",
  "bot_id": "Atros",
  "seats": [
    {"name": "Atros", "seat_no": 3, "is_hero": true, "is_active": false, 
     "hole_cards": [], "available_actions": [], "action_on": false},
    {"name": "monarchi", "seat_no": 5, "is_hero": false, "is_active": false,
     "hole_cards": [], "available_actions": []},
    ...
  ],
  "board": {"flop": [], "turn": null, "river": null},
  "street": "PREFLOP",
  ...
}
```

### Stage 4: Backend — post_snapshot()

**File:** `backend/app.py`
**Function:** `post_snapshot()` at line ~1093

```
1. _store_lock acquired (line 1100)
2. get_or_create_table("pb_2589955", "Atros") → _tables[("pb_2589955", "Atros")]
3. Hand detection (line ~1107):
   - incoming_hand_id = None (extension doesn't send)
   - make_hand_key() → "pb_2589955:implicit" (no cards visible)
   - _detect_new_deal(): incoming=PREFLOP, current=None → no regression → False
   - is_first_real: current hand_key is None → False
   - hand_changed = False
4. hand_id: table.get("hand_id") is None → "Initial hand" (line 1189)
   table["hand_id"] = "339aec5c-..."
5. Structural fields: hero_active = False (available_actions=[]) → NOT overwritten
6. Seat merge (lines 1300-1317):
   - seat 3 (owned by Atros): full replace
   - seat 5 (owned by monarchi): metadata update
7. _store_lock released
8. POST response includes hand_id for extension echo
```

### Stage 5: table_state

After merge, `_tables[("pb_2589955", "Atros")]`:

```python
{
    "table_id": "pb_2589955",
    "bot_id": "Atros",
    "hand_id": "339aec5c-e800-4a00-9e0c-a3f28e5b6232",
    "street": "PREFLOP",
    "board": {"flop": [], "turn": None, "river": None},
    "pot_zar": 0,
    "dealer_seat": 2,
    "seats": {
        3: {"name": "Atros", "is_hero": True, "hole_cards": [], ...},
        5: {"name": "monarchi", "is_hero": False, "hole_cards": [], ...},
    },
    "last_ts": 1783050612.5,
    "state_version": 1,
}
```

### Stage 6: _select_best_table()

**File:** `backend/app.py`, lines 1578-1604

Called by `/api/latest` handler. With 3 per-bot entries:
- `("pb_2589955", "Atros")`: street=PREFLOP, last_ts=T+0
- `("pb_2589955", "monarchi")`: street=PREFLOP, last_ts=T-150
- `("pb_2589955", "allinstalker")`: street=PREFLOP, last_ts=T+100

Selection:
1. All within freshness window (recent)
2. All at PREFLOP (street rank 0)
3. allinstalker has highest last_ts (T+100)
4. Returns allinstalker's entry

### Stage 7: /api/latest Response

```json
{
  "ok": true,
  "table": {
    "table_id": "pb_2589955",
    "hand_id": "60227f46-d4f0-4110-b777-c1c248146db1",
    "street": "PREFLOP",
    "board": {"flop": [], "turn": null, "river": null},
    "pot_zar": 0,
    "dealer_seat": 1,
    "seats": [
      {"seat_no": 1, "name": "allinstalker", "is_hero": true, 
       "hole_cards": [], "available_actions": ["back_to_game"], "is_active": true},
      {"seat_no": 5, "name": "Atros", "is_hero": false,
       "hole_cards": ["Ah","Ac","Js","9c","7h","2d"], ...},
      ...
    ],
    "state_version": 47
  }
}
```

Note: Atros has 6 hole cards visible (their own cards, visible because this is Atros's bot but returned via allinstalker's entry... actually this is from allinstalker's entry where Atros's cards were observed).

### Stage 8: Engine Poll

**File:** `source/engine_flow_controls.js`, line 284

```javascript
const res = await fetch(BRIDGE_URL, { signal: AbortSignal.timeout(10000) });
const data = await res.json();
const text = formatTableDataToCanonical(data.table);
```

### Stage 9: Textarea Update

**File:** `source/engine_flow_controls.js`, lines 83-293

```
formatTableDataToCanonical():
  seat 1: hole_cards=[] → skip
  seat 5: hole_cards=["Ah","Ac","Js","9c","7h","2d"] → "AhAcJs9c7h2d"
  → text = "AhAcJs9c7h2d"

hash check: text != lastSnapshotHash → proceed
setTextareaValue(textarea, "AhAcJs9c7h2d")  ← REPLACES content
```

---

## Key Observations at Each Stage

| Stage | What's Present | Hand Context |
|-------|---------------|-------------|
| DOM | Live poker table, one hand | ✅ Consistent |
| Extension scrape | Parsed DOM, per-bot perspective | ✅ Consistent |
| POST payload | Snapshot with seats, street, board | ✅ Consistent |
| Backend merge | Previous hand's stale seats MERGED IN | ❌ Mixed |
| table_state | Seats from multiple hands in one dict | ❌ Mixed |
| _select_best_table | Picks best bot entry (same hand_id but wrong data) | ❌ Mixed |
| /api/latest | Returns mixed seats array | ❌ Mixed |
| Engine textarea | Renders mixed hole_cards | ❌ Mixed |

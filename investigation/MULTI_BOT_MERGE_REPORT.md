# MULTI_BOT_MERGE_REPORT.md
## W4P Multi-Bot State Oscillation — Root Cause Investigation

**Date:** 2026-07-03
**Status:** READ-ONLY investigation — no code changes
**Repository:** /home/wa/projects/poker/E&R
**Canonical Runtime:** containers `er-remote`, `er-engine`

---

## 1. Executive Summary

The backend treats `table_id` as the sole merge key. Multiple Chrome extensions (one per poker bot/account) post snapshots for the same `table_id = pb_2589955` at 300ms intervals. Each bot observes a **different poker hand**. The backend merges them into **one logical table**, causing structural fields to oscillate between two independent game states.

**Root cause path:** `POST /api/snapshot` → `_tables[table_id]` is a SINGLE shared entry → structural fields overwritten unconditionally → no game-context isolation → "last writer wins" oscillation.

**Conclusion:** The observed flicker originates in the backend merge algorithm. It is NOT a rendering issue. The Remote UI faithfully renders what the backend provides.

---

## 2. Architecture Analysis

### 2.1 Single-Table Model

The backend uses `_tables = {}` keyed by `table_id` (line 183 of `backend/app.py`):

```python
_tables = {}  # key: table_id → canonical table state
```

There is exactly ONE table state object per `table_id`. All bots posting to the same `table_id` write to the same object.

### 2.2 Merge Algorithm (Lines 1097-1301 of app.py)

Each `POST /api/snapshot` call enters the `_store_lock` critical section and executes:

1. **Table creation/retrieval** (line 1101): `table = get_or_create_table(table_id)` — always returns the same object
2. **Hand detection** (line 1107): `new_deal = _detect_new_deal(payload, table)`
3. **Structural field overwrite** (lines 1148-1152): table-level fields set unconditionally
4. **Seat merge** (lines 1249-1266): per-seat ownership-protected merge
5. **Bot mapping update** (lines 1286-1293): `_seat_bots` updated for hero only
6. **SSE push** (line 1325): notifies connected clients

### 2.3 Key Design Decision

The backend was designed when only ONE bot (monarchi) posted for a single table. Multi-bot support was added by reusing the same `_tables[table_id]` key, assuming all bots observe the same hand. They do not.

---

## 3. Critical Code Paths

### 3.1 Structural Field Overwrite (THE PRIMARY DEFECT)

Location: `backend/app.py`, lines 1148-1152

```python
table["street"]      = payload.get("street")
table["pot_zar"]     = payload.get("pot_zar")
table["board"]       = payload.get("board", {"flop": [], "turn": None, "river": None})
table["variant"]     = payload.get("variant", "plo")
table["dealer_seat"] = payload.get("dealer_seat")
```

These fields are set **unconditionally** from every arriving payload. No merge, no conflict resolution, no game-context check. The last bot to post determines `street`, `board`, `pot_zar`, and `dealer_seat` for ALL consumers.

### 3.2 Seat Merge (Lines 1249-1266)

```python
for sno, sdata in new_seats.items():
    existing_bot = _seat_bots.get((table_id, sno))
    if existing_bot and bot_id and existing_bot != bot_id:
        existing = table["seats"].get(sno)
        if existing:
            existing["stack_zar"] = _safe_float(sdata.get("stack_zar"), ...)
            existing["status"] = sdata.get("status", existing.get("status"))
            existing["is_dealer"] = sdata.get("is_dealer", existing.get("is_dealer"))
            existing["last_seen"] = sdata["last_seen"]
            observed_cards = sdata.get("hole_cards", [])
            if observed_cards:
                existing["hole_cards"] = observed_cards
        else:
            table["seats"][sno] = sdata
    else:
        table["seats"][sno] = sdata  # FULL REPLACE
```

When a seat is owned by a DIFFERENT bot, only metadata is updated. When the seat is owned by the posting bot (or unowned), the **entire seat object is replaced**.

**What gets protected:** `name`, `is_hero`, `is_active`, `available_actions` (by exclusion from the metadata update)

**What gets overwritten by other bots:** `stack_zar`, `status`, `is_dealer`, `last_seen`, `hole_cards`

**Critical gap:** `is_dealer` is overwritten by the metadata update (line 1257), meaning the dealer chip can oscillate based on which bot last posted.

### 3.3 Hand Reset Detection (Lines 399-418)

```python
def _detect_new_deal(payload, table):
    incoming_street = payload.get('street', 'PREFLOP')
    current_street = table.get('street', 'PREFLOP')
    STREET_ORDER = ['PREFLOP', 'FLOP', 'TURN', 'RIVER']
    # Signal 1: Street went backwards
    if 0 <= incoming_idx < current_idx:
        return True
    # Signal 2: Board went from non-empty to empty AND street is PREFLOP
    ...
```

When a second bot posts a snapshot from a **different hand**, the street comparison may trigger a false hand reset.

**Scenario:**
1. Bot A (monarchi) finishes Hand X, enters new Hand Y → posts PREFLOP
2. Bot B (Atros) is still on Hand Z at FLOP → posts FLOP
3. If Bot B's FLOP was the last write, current street = FLOP
4. Bot A's PREFLOP arrives → street regression detected → **hand reset triggered**
5. All seats, cards, batch data are cleared
6. Bot B's next FLOP snapshot arrives → FLOP overwrites the now-PREFLOP table

The result: PREFLOP → (hand reset) → FLOP → (hand reset) → PREFLOP → ... cycling at ~600ms period.

### 3.4 Hand Key Collision (Lines 376-396)

```python
def make_hand_key(payload):
    deal_id = payload.get('deal_id')
    if deal_id:
        return f"{tid}:deal:{deal_id}"
    all_cards = []
    for s in seats:
        cards = s.get('hole_cards') or []
        for c in cards:
            if isinstance(c, str) and len(c) == 2:
                all_cards.append(c.lower())
    if len(all_cards) >= 4:
        h = hashlib.sha256(','.join(all_cards).encode()).hexdigest()[:16]
        return f"{tid}:cards:{len(all_cards)}:{h}"
    return f"{tid}:implicit"
```

**During PREFLOP:** No hole cards are visible → `hand_key = "pb_2589955:implicit"` for both bots.

**Result:** Two different hands at PREFLOP produce the same hand key → NO hand reset → seats from two different games merge into one table.

---

## 4. Extension Behavior

### 4.1 Polling Interval (w4p.js, line 360)

```javascript
var POLL_MS = { HERO_TURN: 300, HAND_ACTIVE: 300, IDLE: 300, NO_TABLE: 2000 };
```

Every 300ms, each bot builds a snapshot and POSTs it. With 2 bots, interleaving creates 6+ snapshots per second.

### 4.2 Always Posts (w4p.js, line 2084-2085)

```javascript
// Send every tick — no dedup, no heartbeat gate
sendSnapshot(snap);
```

There is no deduplication gate. Inactive hero snapshots (hero=true, is_active=false, available_actions=[]) are posted every 300ms regardless.

### 4.3 Snapshot Payload (w4p.js, lines 1415-1434)

The payload includes all structural fields: `table_id`, `bot_id`, `seats`, `board`, `pot_zar`, `dealer_seat`, `street`, `available_actions`, `active_player`. Each bot only sees its own hole cards, but all community cards and seat data are observed from the DOM.

---

## 5. `/api/latest` Response (Lines 1550-1599)

The Remote UI polls `/api/latest` (long-poll, 25s timeout). The handler returns:

```python
table = max(_tables.values(), key=lambda t: t['last_ts'])
```

There is only ONE entry for `pb_2589955`, so the latest-writer's state is always returned. The Remote UI has no way to distinguish which bot's perspective it's seeing.

---

## 6. Evidence Matrix

| # | Finding | Code Location | Impact |
|---|---------|-------------|--------|
| 1 | Structural fields overwritten unconditionally | app.py:1148-1152 | Street, board, pot, dealer oscillate |
| 2 | Single _tables entry per table_id | app.py:183, 1101 | All bots share one state object |
| 3 | Hand key collision during PREFLOP | app.py:376-396 | Two hands merged without detection |
| 4 | Street regression triggers full reset | app.py:399-418 | Seats cleared mid-oscillation |
| 5 | 300ms per-bot polling interval | w4p.js:360 | 6+ interleaved writes/sec |
| 6 | No dedup/no heartbeat gate | w4p.js:2084 | Inactive snapshots always posted |
| 7 | is_dealer overwritten by other bots | app.py:1257 | Dealer chip oscillates |
| 8 | `_seat_bots` persists across hand resets | app.py:1138 | Bot identity stable, but wrong context |

---

## 7. Oscillation Timeline (Hypothetical 6-Step Cycle)

```
T=0ms    monarchi POST → PREFLOP, board=[], hand_key=implicit
         ── _tables[pb_2589955] ← PREFLOP, no board ──

T=150ms  Atros POST → PREFLOP, board=[], hand_key=implicit (DIFFERENT HAND)
         ── hand_key collision → NO reset → seats merged ──
         ── table["street"] = PREFLOP (unchanged) ──

T=300ms  monarchi POST → street still PREFLOP
         ── No regression, no reset ──

... Several ticks pass. Both bots on PREFLOP of different hands ...

T=Xms    monarchi POST → FLOP, board=[2s,3s,4s], 4+ cards visible
         ── hand_key changes to pb_2589955:cards:4:<hash> ──
         ── table["street"] = FLOP, table["board"] = flop cards ──

T=X+150ms Atros POST → still PREFLOP, board=[] (different hand still preflop)
         ── street regression: FLOP → PREFLOP → _detect_new_deal returns TRUE ──
         ── FULL HAND RESET: seats cleared, cards cleared, batch cleared ──
         ── table["street"] = PREFLOP, table["board"] = [] ──

T=X+300ms monarchi POST → FLOP again (same hand, monarchi still on FLOP)
         ── hand_key is_real: makes new hand_key ──
         ── is_first_real: True (current is implicit after reset) → ANOTHER RESET ──
         ── table["street"] = FLOP, board = [2s,3s,4s] ──

         ... cycle repeats ...
```

**Result:** Street oscillates between PREFLOP and FLOP every ~300-450ms. The Remote UI flickers between the two states.

---

## 8. Answers to Investigation Questions

### Q: Does each bot represent the same poker hand?
**No.** Multiple bots at the same table observe independent hands. The backend has no mechanism to verify this.

### Q: Are different hands being merged into one table?
**Yes.** The `_tables` map uses only `table_id` as the key. All snapshots for `pb_2589955` merge into one state object.

### Q: Are structural fields overwritten?
**Yes.** `street`, `pot_zar`, `board`, `dealer_seat` are set unconditionally from every snapshot (lines 1148-1152).

### Q: Does "last writer wins" cause oscillation?
**Yes.** With two bots posting at 300ms intervals, the structural fields toggle between whatever each bot observes.

### Q: Does `_seat_bots` drift over time?
**Potentially yes.** `_seat_bots` is NOT cleared on hand reset (line 1138 comment). If a bot changes seat between hands, the old mapping is removed and re-created (lines 486-490 of `update_bot_seat_mapping`), so primary identity is preserved. However, during oscillation where seats are cleared and re-created during every hand reset, the bot re-asserts its seat position on each POST.

### Q: Are inactive snapshots overwriting active snapshots?
**Partially.** Inactive snapshots (hero=true, is_active=false) still carry structural fields (street, board, pot, dealer). These overwrite the active bot's structural state. However, per-seat `is_active` and `available_actions` are protected for seats owned by another bot.

### Q: Is the backend correctly distinguishing separate game contexts?
**No.** The backend uses only `table_id` to distinguish contexts. It has no concept of "which game instance" or "which hand" each bot is observing. The `hand_key` fingerprint can detect hand changes within a single bot's stream, but cannot distinguish whether two bots are in the same hand or different hands.

---

## 9. First Point of State Convergence

The **single point** where two independent game states become one is:

**`backend/app.py`, line 1101:** `table = get_or_create_table(table_id)`

This call returns the SAME mutable dictionary for ALL bots posting to the same `table_id`. From this point forward, every mutation by any bot affects the shared state.

The **specific overwrite** that causes visible oscillation is:

**`backend/app.py`, line 1148:** `table["street"] = payload.get("street")`

This is the first unconditional write that can differ between two bots observing different hands. Combined with `_detect_new_deal` (line 1107-1146), it creates the oscillation cycle.

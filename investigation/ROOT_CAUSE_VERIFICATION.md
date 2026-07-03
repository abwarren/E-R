# ROOT_CAUSE_VERIFICATION.md
## W4P Multi-Bot State Oscillation — Root Cause Verification

**Date:** 2026-07-03
**Investigation Type:** READ-ONLY code analysis
**Conclusion:** Primary architectural cause identified with high confidence. The convergence point is the backend state model. NOT a rendering issue.

---

## 1. Problem Statement

**Observed:** The Remote UI (and Engine) flickers between two different game states for `table_id = pb_2589955` — streets change, board cards appear/disappear, pot amounts jump, dealer chip shifts.

**Hypothesis tested:** The flicker originates from interleaved snapshots from multiple bots being merged into a single table state without game-context isolation.

**Alternative hypothesis considered:** The flicker is a rendering issue in the Remote UI.

---

## 2. Root Cause Identification

### 2.1 Primary Root Cause: Single-Table Merge Without Game Context

**Location:** `backend/app.py`, lines 183 + 1101

```python
_tables = {}   # key: table_id → canonical table state
...
table = get_or_create_table(table_id)   # Returns SAME object for all bots
```

The backend uses `table_id` as the SOLE primary key. All bots posting to `pb_2589955` share one mutable dictionary. There is no secondary key for game instance, hand identity, or bot perspective.

**This is confirmed by:**
1. `_tables` is defined as `{}` keyed by `table_id` (line 183)
2. `get_or_create_table` creates exactly one entry per `table_id` (lines 446-463)
3. `post_snapshot` retrieves this single entry (line 1101)
4. All mutations are performed on this shared object under `_store_lock`

### 2.2 Secondary Root Cause: Unconditional Structural Field Overwrite

**Location:** `backend/app.py`, lines 1148-1152

```python
table["street"]      = payload.get("street")
table["pot_zar"]     = payload.get("pot_zar")
table["board"]       = payload.get("board", {"flop": [], "turn": None, "river": None})
table["variant"]     = payload.get("variant", "plo")
table["dealer_seat"] = payload.get("dealer_seat")
```

These five assignments have **zero guards**. They execute for every snapshot from every bot. There is no:
- Comparison with existing value
- Conflict detection
- Game context validation
- Bot-specific override policy

**This is confirmed by:**
1. No `if` statement before any of these assignments
2. No comparison with `table["street"]` or other current values
3. The lines execute unconditionally after the hand reset block (lines 1117-1146)

### 2.3 Tertiary Root Cause: Fragile Hand Detection

**Location:** `backend/app.py`, lines 399-418 + 1113-1116

Two independent detection mechanisms can trigger hand resets:

1. **Street regression** (lines 399-418): If incoming street is "earlier" than current street, treat as new deal. This misfires when two bots are on different streets of different hands.

2. **`is_first_real`** (lines 1113-1116): If the current hand_key is "implicit" and the incoming hand_key has real cards, treat as new deal. This misfires after a reset-clears the hand_key to "implicit".

**Combined failure mode:** These two detectors create an oscillation cycle where each bot's POST triggers a reset that makes the next bot's POST also trigger a reset. The result is 3+ hand resets per second during divergence.

**This is confirmed by:**
1. Street regression comparison at line 409: `0 <= incoming_idx < current_idx` — no check for bot identity
2. `is_first_real` check at line 1113-1116: only compares hand_key format, not bot context
3. Hand reset at lines 1117-1146: clears all seats, cards, batch data unconditionally

### 2.4 Contributing Factor: 300ms Polling Rate

**Location:** `source/w4p.js`, line 360

```javascript
var POLL_MS = { HERO_TURN: 300, HAND_ACTIVE: 300, IDLE: 300, NO_TABLE: 2000 };
```

Each bot builds and POSTs a complete snapshot every 300ms. With 2 bots, the effective write rate is ~6.67 writes/second on the shared state object. There is no deduplication or heartbeat gating (line 2084: "Send every tick — no dedup, no heartbeat gate").

---

## 3. Evidence Chain

```
┌─────────────────────────────────────────────────────────────────────┐
│ EVIDENCE CHAIN: From symptom to root cause                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ 1. REMOTE UI observes flickering street/board/pot/dealer            │
│    ↓                                                                │
│ 2. Remote UI fetches from /api/latest (line 725, remote-w4p.html)  │
│    ↓                                                                │
│ 3. /api/latest returns max(_tables.values(), key=last_ts)           │
│    (line 1550, app.py)                                              │
│    ↓                                                                │
│ 4. _tables["pb_2589955"] is a SINGLE mutable dict (line 183)        │
│    ↓                                                                │
│ 5. Every POST /api/snapshot writes to this dict (line 1101)         │
│    ↓                                                                │
│ 6. Multiple bots POST to the same table_id (line 1040)              │
│    ↓                                                                │
│ 7. Each bot sends its complete perspective: street, board, pot,     │
│    dealer, seats (w4p.js lines 1415-1434)                           │
│    ↓                                                                │
│ 8. structural fields OVERWRITTEN unconditionally (lines 1148-1152)  │
│    ↓                                                                │
│ 9. Bots can be in DIFFERENT HANDS at DIFFERENT STREETS              │
│    ↓                                                                │
│ 10. DIFFERENT STATES overwrite each other in cycles                 │
│    ↓                                                                │
│ ROOT CAUSE: No game-context isolation in the merge algorithm.       │
│             _tables is indexed by table_id alone.                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Falsification of Alternative Hypothesis

### Alternative: "The flicker is a rendering issue in the Remote UI"

**Evidence against:**
1. Remote UI uses long-polling (25s timeout) and diff-based rendering (lines 725, 736, 820-829)
2. Render is driven by `requestAnimationFrame` batching (line 706)
3. Seat rendering uses hash-based diff: if `json === _lastTableJSON`, no re-render occurs (line 736)
4. The Remote UI has NO state of its own — it only renders what `/api/latest` returns
5. Street label, board cards, pot label are rendered directly from `lastTable.street`, `lastTable.board`, `lastTable.pot_zar` (lines 785-789, 800-801)

**Conclusion:** The Remote UI faithfully renders whatever the backend provides. If the backend provides oscillating data, the UI will oscillate. The flicker is NOT a rendering bug.

### Verification: Remote UI Diff Check

The Remote UI at line 736 does:
```javascript
if (json === _lastTableJSON) { schedulePoll(); return; }
```

If the backend returned the same state twice, the UI would skip rendering. But the backend oscillates between two states (PREFLOP vs FLOP), so the JSON strings differ → re-render every time.

---

## 5. Severity Assessment

| Aspect | Severity | Justification |
|--------|----------|--------------|
| Visual disruption | **HIGH** | Street label, board cards, pot, dealer chip all flicker |
| Data integrity | **HIGH** | Hand resets clear accumulated seat data 3x/sec |
| Engine accuracy | **HIGH** | Engine reads table state; oscillation corrupts equity calcs |
| User trust | **HIGH** | Flickering UI undermines confidence in all platform data |
| Scope | Limited | Only affects tables with 2+ bots in different hands |

---

## 6. Where the Fix Should Be Applied

The root cause resides in the backend merge algorithm. Specifically:

1. **Lines 1148-1152:** These unconditional writes must gain per-bot context awareness
2. **Lines 1117-1146:** The hand reset must consider which bot triggered it and whether the state divergence is real or a timing artifact
3. **Line 183:** `_tables` may need to be indexed by `(table_id, bot_id, hand_key)` or similar composite key

**The fix is NOT in:**
- The Chrome extension (w4p.js) — it correctly reports what it observes
- The Remote UI (remote-w4p.html) — it correctly renders what it receives
- The polling rate — reducing frequency would mask but not fix the underlying race
- The Docker/container setup — this is a pure logic defect

---

## 7. Verification Markers

The following runtime evidence would confirm this analysis (to be gathered when read-only restriction is lifted):

1. **Bot interleaving:** Backend logs show alternating `bot_id=monarchi` / `bot_id=Atros` for same `table_id`
2. **Hand reset frequency:** "Hand reset" log lines appear > 1/sec during flicker periods
3. **Street alternation:** Consecutive logs show `street=PREFLOP` / `street=FLOP` / `street=PREFLOP` for same table
4. **State version churn:** `state_version` increments rapidly (6+/sec) rather than normally (3/sec)
5. **Seat data loss:** `_hero_cards` and `table["seats"]` are repeatedly cleared and rebuilt

---

## 8. Final Determination

**The observed flicker is caused by interleaved snapshots from multiple bots being merged into a single table state without game-context isolation.**

**Confidence:** High. The architectural convergence point and overwrite mechanism are identified with precision. However, one assumption remains unverified:

> **Are Bot A and Bot B observing different logical games, or the same table from different seats?**

Both scenarios produce oscillation through the same convergence point, but they require different long-term solutions:

- **Same table, different seats:** The correct fix is a layered state model (shared table state + per-bot hero state), because the board/pot/street ARE common ground between bots.
- **Different tables, same table_id:** The correct fix is to partition state by a hand identifier, because there is genuinely nothing shared between the bots.

The investigation cannot distinguish these scenarios from code analysis alone — runtime evidence (hand IDs, deal timestamps, table URL comparison) is needed.

**It is NOT a rendering issue.** The Remote UI and Engine correctly display the data they receive from the backend.

**The first point where two independent game states become one** is line 1101 of `backend/app.py`:
```python
table = get_or_create_table(table_id)
```

**The specific overwrite causing visible oscillation** is line 1148:
```python
table["street"] = payload.get("street")
```

Combined with the hand-reset logic at lines 1117-1146, these create a self-perpetuating oscillation cycle with a period of approximately 600ms.

**Next step:** An Architectural Decision Record (ADR) comparing state isolation strategies, informed by the hand identification analysis that follows.

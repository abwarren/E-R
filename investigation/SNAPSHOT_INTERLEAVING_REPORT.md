# SNAPSHOT_INTERLEAVING_REPORT.md
## W4P Snapshot Interleaving — Two-Bot Race Condition Analysis

**Date:** 2026-07-03
**Repository:** /home/wa/projects/poker/E&R

---

## 1. Interleaving Mechanics

### 1.1 Polling Rates

Each Chrome extension runs in its own browser instance with its own `setTimeout(tick, ...)` loop:

```javascript
// w4p.js, line 360
var POLL_MS = { HERO_TURN: 300, HAND_ACTIVE: 300, IDLE: 300, NO_TABLE: 2000 };
```

Each bot posts a snapshot **every 300ms** during active play. There is NO coordination between bots — they run independently.

### 1.2 Average Interleaving Pattern (2 Bots)

```
Time  Bot A                         Bot B
────────────────────────────────────────────────────
0ms   buildSnapshot() → POST                       │
      ───────────────────────► Backend              │
                                  buildSnapshot() → │
150ms                             POST              │
                                  ────────► Backend │
300ms buildSnapshot() → POST                       │
      ───────────────────────► Backend              │
450ms                             buildSnapshot() → │
                                  POST              │
                                  ────────► Backend │
600ms buildSnapshot() → POST                       │
      ───────────────────────► Backend              │
```

**Effective interleaving rate:** One snapshot every ~150ms (6.67 per second).
**Each bot's rate:** One snapshot every 300ms (3.33 per second).

### 1.3 Backend Processing

The backend processes each POST synchronously under `_store_lock` (line 1100):

```python
with _store_lock:
    table = get_or_create_table(table_id)
    # ... all mutations ...
```

Processing is **serialized** — only one snapshot is merged at a time. The 150ms interleaving means each snapshot can fully overwrite the state before the next arrives.

---

## 2. Interleaving Effects by Field

### 2.1 Table-Level Fields (Unconditional Overwrite)

| Field | Oscillation Amplitude | Visible Flicker | Period |
|-------|----------------------|-----------------|--------|
| `street` | PREFLOP ⇄ FLOP | **YES** — street label changes color | ~300ms |
| `board` | [] ⇄ [2s,3s,4s] | **YES** — board cards appear/disappear | ~300ms |
| `pot_zar` | 0 ⇄ 12.50 | **YES** — pot amount changes | ~300ms |
| `dealer_seat` | 3 ⇄ 5 | **YES** — D chip moves | ~300ms |
| `variant` | "plo" ⇄ "plo" | NO (always same) | N/A |

### 2.2 Seat-Level Fields (Ownership-Protected)

| Field | Protected? | Oscillation? | Why |
|-------|-----------|-------------|-----|
| `name` | ✓ (not in metadata update) | No | Only owner can change |
| `is_hero` | ✓ | No | Only owner can change |
| `is_active` | ✓ | No | Only owner can change |
| `available_actions` | ✓ | No | Only owner can change |
| `stack_zar` | ✗ (metadata update) | Yes | Last writer wins |
| `status` | ✗ (metadata update) | Yes | Last writer wins |
| `is_dealer` | ✗ (metadata update) | **Yes** | Last writer wins |
| `hole_cards` | ✗ (conditional) | Maybe | Updated if observed |
| `last_seen` | ✗ (metadata update) | Yes | Always updated |

### 2.3 Combined Effect

The resulting flicker has two distinct visual signatures:

1. **Macro flicker (street/board/pot):** The entire table context oscillates between two game states. This is the most visually jarring — the street label changes color, board cards appear and disappear, pot amount jumps.

2. **Micro flicker (dealer/stack/status):** Even when structural fields are stable, the dealer chip and stack amounts can shift slightly between bots' observations due to timing differences in DOM reading.

---

## 3. Interleaving Race Conditions

### 3.1 The Double Reset Race

The most destructive pattern. Requires:

- Bot A: FLOP (hand X)
- Bot B: PREFLOP (hand Y, different hand)

```
Step 1: Bot B POST (PREFLOP)
  → _detect_new_deal: FLOP→PREFLOP regression → HAND RESET
  → seats cleared, batch cleared, hero_cards cleared
  → hand_key = "implicit"
  → street = PREFLOP

Step 2: Bot A POST (FLOP, ~150ms later)
  → _detect_new_deal: PREFLOP→FLOP forward → NO reset
  → is_first_real check:
      incoming hand_key starts with "pb_2589955:cards:"
      current hand_key is "pb_2589955:implicit"
      → is_first_real = TRUE → HAND RESET AGAIN
  → seats cleared AGAIN
  → hand_key = "pb_2589955:cards:4:<hashA>"
  → street = FLOP

Step 3: Bot B POST (PREFLOP, ~150ms later)
  → _detect_new_deal: FLOP→PREFLOP regression → HAND RESET
  → ... back to Step 1 ...
```

**Result:** A hand reset occurs on **every other snapshot**. Seats are cleared and rebuilt 3+ times per second. No seat data persists for more than one snapshot.

### 3.2 The Inactive Overwrite Race

```
Step 1: Bot A POST (FLOP, active=true, acts=[fold,call,raise])
  → street=FLOP, board set, pot set

Step 2: Bot B POST (PREFLOP, hero=true, is_active=false, acts=[])
  → street=PREFLOP, board={}, pot=0  ← ALL OVERWRITTEN
  → Bot A's active seat state preserved (ownership protection)
  → But table context is now WRONG

Step 3: Bot A POST (FLOP, active=true)
  → street=FLOP, board set, pot set AGAIN
  → RESET if is_first_real triggers
```

**Result:** Active bot's table context is periodically overwritten by inactive bot's stale view. The active bot's seat-level state survives but the table context is destroyed.

### 3.3 The Dealer Chip Race

```
Step 1: Bot A POST (sees dealer=3)
  → Seat3.monarchi: full replace → is_dealer=true
  → Seat5.Atros: metadata update → is_dealer=false

Step 2: Bot B POST (sees dealer=5)
  → Seat3.monarchi (owned by A): metadata update → is_dealer=false  ← OVERWRITTEN
  → Seat5.Atros: full replace → is_dealer=true

Step 3: Back to A
  → Seat3.monarchi: full replace → is_dealer=true
  → Seat5.Atros: metadata update → is_dealer=false
```

**Result:** Dealer chip oscillates between Seat 3 and Seat 5 every ~150ms. Both bots may be correctly observing the table, but slight timing differences in DOM reads cause different dealer detection.

---

## 4. Log Evidence Required for Runtime Verification

To confirm interleaving at runtime, the following log patterns would need to be observed:

### Key Log Lines

```
[SNAPSHOT][ACCEPT] table_id=pb_2589955 bot_id=monarchi seats=N
[SNAPSHOT][ACCEPT] table_id=pb_2589955 bot_id=Atros seats=M
```

The interleaving ratio (monarchi:Atros snapshot count) should be ~1:1 if both bots are actively polling.

### Reset Log Lines

```
[V2] Hand reset: cleared batch/commands/cashout table=pb_2589955
```

If this appears multiple times per second during flicker periods, the double-reset race is confirmed.

### Street Oscillation Log Lines

```
[W4P][SNAPSHOT] ... street=PREFLOP ... bot_id=monarchi
[W4P][SNAPSHOT] ... street=FLOP    ... bot_id=Atros
[W4P][SNAPSHOT] ... street=PREFLOP ... bot_id=monarchi
```

Alternating street values for the same table from different bots confirm the root cause.

---

## 5. Impact Summary

| Effect | Severity | Cause | Duration |
|--------|----------|-------|----------|
| Street label flicker | HIGH | Unconditional street overwrite | Continuous during divergence |
| Board cards appear/disappear | HIGH | Unconditional board overwrite + hand resets | Continuous |
| Pot amount jumping | MEDIUM | Unconditional pot overwrite | Continuous |
| Dealer chip shifting | MEDIUM | is_dealer in metadata update | Continuous |
| Stack amount jitter | LOW | Metadata update on stack_zar | Intermittent |
| Seat data loss | HIGH | Double-reset clears seat data 3x/sec | During divergence |

---

## 6. Verification Checklist

- [ ] grep backend logs for alternating bot_ids on same table_id
- [ ] grep for "Hand reset" frequency — if > 1/sec, double-reset confirmed
- [ ] grep for street alternation: `grep "street=" | sort | uniq -c`
- [ ] Check state_snapshot.json for `_seat_bots` to verify orphan entries
- [ ] Monitor Remote UI with browser console to capture `/api/latest` response oscillation

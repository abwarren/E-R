# SNAPSHOT_TIMELINE.md
## W4P Runtime Timeline — 2026-07-03

**Date:** 2026-07-03
**Data Source:** Docker container logs, 33,420 snapshots, 9,874 seconds

---

## 1. Full-Day Timeline

```
00:00:00 ────────────────────────────────────────────── 02:44:34
│                                                          │
│  Phase 1: Single Bot          Phase 2: Multi-Bot        │Phase 3
│  (allinstalker only)          (Atros + monarchi +        │
│                               allinstalker)              │
│                                                          │
│  1 bot, 1 view, no osc       3 bots, different streets  │↓ idle
│  Stable                       OSCILLATING                │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Phase 1: Single Bot (00:00:00 — ~01:00:00)

**State:** allinstalker only
**Snapshots:** ~1/s
**Street:** PREFLOP (consistent)
**Oscillation:** None

```
00:00:00  allinstalker  POST → PREFLOP (back_to_game)
00:00:01  allinstalker  POST → PREFLOP (back_to_game)
00:00:02  allinstalker  POST → PREFLOP (back_to_game)
...
```

**Why stable:** Single bot = single `_tables` entry = consistent view. No other bot to alternate with.

**Note:** allinstalker always shows `back_to_game` — this bot is in a lobby/waiting state, not actively playing.

---

## 3. Phase 2: Multi-Bot Oscillation (~01:00:00 — 02:30:00)

**State:** Atros, monarchi, allinstalker all posting
**Snapshots:** ~3-8/s (burst interleaving)
**Streets:** PREFLOP (allinstalker), FLOP/TURN/RIVER (Atros, monarchi)
**Oscillation:** Confirmed

### 3.1 Peak Oscillation: 01:35:11-01:35:14

```
01:35:11.000  monarchi     POST → seats=1
01:35:11.050  Atros        POST → seats=2
01:35:11.100  monarchi     POST → seats=1
01:35:11.150  Atros        POST → seats=2
01:35:11.200  monarchi     POST → seats=1
01:35:11.250  Atros        POST → seats=2
01:35:11.300  monarchi     POST → seats=1
01:35:11.350  allinstalker POST → seats=2
01:35:11.400  Atros        POST → seats=2
```

**6+ unique POSTs in the same second.** monarchi and Atros alternate every ~50ms.

### 3.2 Street Oscillation: 00:32:20-00:32:29

```
00:32:20  allinstalker  PREFLOP [back_to_game]   ← lobby state
00:32:21  monarchi      FLOP    [check, bet]      ← in-hand
00:32:21  allinstalker  PREFLOP [back_to_game]    ← lobby state
00:32:22  monarchi      FLOP    [check, bet]      ← in-hand
00:32:22  allinstalker  PREFLOP [back_to_game]    ← lobby state
00:32:23  monarchi      FLOP    [check, bet]      ← in-hand
00:32:23  allinstalker  PREFLOP [back_to_game]    ← lobby state
00:32:24  Atros         FLOP    [check, bet]      ← in-hand
00:32:24  allinstalker  PREFLOP [back_to_game]    ← lobby state
00:32:25  Atros         FLOP    [check, bet]      ← in-hand
00:32:25  allinstalker  PREFLOP [back_to_game]    ← lobby state
...
```

**PREFLOP ↔ FLOP oscillation every ~1 second.**

### 3.3 Full Street Oscillation Spectrum

| Transition | Count |
|-----------|-------|
| PREFLOP → FLOP | 468 |
| FLOP → PREFLOP | 456 |
| PREFLOP → TURN | 429 |
| TURN → PREFLOP | 432 |
| PREFLOP → RIVER | 351 |
| RIVER → PREFLOP | 360 |
| FLOP → TURN | 12 |
| TURN → RIVER | 9 |

**Total: 2,517 street changes.** The vast majority are regressions (later street → PREFLOP), confirming that allinstalker's PREFLOP POSTs are interleaving with Atros/monarchi's later-street POSTs.

---

## 4. Phase 3: Wind-Down (02:30:00 — 02:44:34)

**State:** Bots going idle
**Last ACCEPT:** 02:44:34 (Atros)
**Final state:** allinstalker only (consistent with Phase 1)

---

## 5. Hand Reset Timeline

The 240,407 hand reset log lines cluster around specific periods:

### Burst Period: 02:03:56-02:03:57

```
02:03:56  New hand 665709d9 table=pb_2589955
02:03:56  New hand e83585c0 table=pb_2589955
02:03:56  New hand 271c463a table=pb_2589955
02:03:57  New hand 7b1b16cd table=pb_2589955
```

**4 new hands in 1 second!** Each a different hand_id, each for a different bot entry. These are per-bot hand detections firing independently.

### Guard Active Period: 02:29:31-02:29:43

```
02:29:31  Skipping reset: diff bot behind (bot=allinstalker in=PREFLOP cur=RIVER last_bot=None)
02:29:32  Skipping reset: diff bot behind (bot=allinstalker in=PREFLOP cur=RIVER last_bot=None)
... (repeats every second for 14 seconds)
02:29:43  Skipping reset: diff bot behind (bot=allinstalker in=PREFLOP cur=RIVER last_bot=None)
```

**Guard correctly prevents reset** when allinstalker (PREFLOP) tries to trigger hand reset on Atros/monarchi's RIVER entry.

---

## 6. API Response Timeline (Inferred)

Based on the interleaving pattern and `_dedup_latest_by_table()` behavior:

```
T+0.00s   Atros POST → last_ts=T+0.00
T+0.05s   allinstalker POST → last_ts=T+0.05
T+0.10s   monarchi POST → last_ts=T+0.10
T+0.12s   /api/latest poll → picks monarchi's entry (most recent)
          → returns FLOP, board=[cards], pot=12.50
          
T+0.15s   Atros POST → last_ts=T+0.15
T+0.30s   /api/latest poll → picks Atros's entry (most recent)
          → returns FLOP, board=[cards], pot=12.50
          
T+0.35s   allinstalker POST → last_ts=T+0.35
T+0.45s   /api/latest poll → picks allinstalker's entry (most recent)
          → returns PREFLOP, board=[], pot=0
          
T+0.50s   monarchi POST → last_ts=T+0.50
T+0.60s   /api/latest poll → picks monarchi's entry (most recent)
          → returns FLOP, board=[cards], pot=12.50
```

**RESULT: Remote UI receives PREFLOP→FLOP→PREFLOP→FLOP every ~300ms**

---

## 7. Summary

| Phase | Duration | Bots | Snapshots | Street | Stable? |
|-------|----------|------|-----------|--------|---------|
| Phase 1 | ~60 min | 1 | ~1/s | PREFLOP | ✅ Yes |
| Phase 2 | ~90 min | 2-3 | 3-8/s | PREFLOP↔FLOP↔TURN↔RIVER | ❌ OSCILLATING |
| Phase 3 | ~15 min | 0-1 | <1/s | PREFLOP | ✅ Yes (idle) |

The oscillation is confined to Phase 2 — when 2+ bots are simultaneously posting with different game states. The pattern is clear: each bot has a consistent view of ITS game, but the API alternates between them.

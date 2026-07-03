# TRACER_BULLET_HAND.md
## W4P Tracer Bullet — Single Hand Through Time

**Date:** 2026-07-03
**Investigation:** READ-ONLY

---

## Tracer Bullet: Hand Starting at 02:27:06 UTC

This traces one actual hand through the logs, anchored to timestamped events.

### Timeline

```
02:27:06  [HAND_ID] New hand aebcecd5 table=pb_2589955
          → Hand X begins. Street = PREFLOP (from heuristic detection)

02:27:07  [HAND_ID] Extension reports new hand: aebcecd5 -> 010010d4
          → Extension echo: old hand_id aebcecd5, new incoming hand_id 010010d4
          → hand_changed = True (via extension echo path, no guard check)

02:27:07  [HAND_ID] New hand d301eb00 table=pb_2589955
          → DIFFERENT BOT's hand detection fires. Another hand_id assigned.

02:27:08  [HAND_ID] Extension reports new hand: d301eb00 -> aebcecd5
          → Extension echo cycle continues between bot entries

02:27:08  [HAND_ID] New hand 7c025a7e table=pb_2589955
          → Third bot's hand detection fires

02:27:09  [HAND_ID] New hand 11334703 table=pb_2589955
          → Fourth hand detection in 3 seconds

          *** RAPID HAND CYCLE — 4 new hands in 3 seconds across 2-3 bots ***
```

### Preflop → Flop → Turn → River (all bots same hand)

This SHOULD be a clean progression within a single hand. But the multi-bot interleaving causes false hand detections because each bot's street progression is seen as a "new hand" by other bots' entries.

### Next Hand — Guard Blocks Reset

```
02:29:16  [HAND_ID] Skipping reset: bot=allinstalker in=PREFLOP cur=TURN last_bot=None
02:29:17  [HAND_ID] Skipping reset: bot=allinstalker in=PREFLOP cur=TURN last_bot=None
... (28 consecutive, ~1/sec)
02:29:43  [HAND_ID] Skipping reset: bot=allinstalker in=PREFLOP cur=RIVER last_bot=None
```

allinstalker's PERPETUAL PREFLOP snapshots try to reset Atros/monarchi's active hand entries. The guard correctly blocks these interleaved resets. But the guard uses `last_street_bot=None` which is never set — making it also block legitimate same-bot resets.

### Current State (03:53:36 UTC)

```
03:53:33  [HAND_ID] Initial hand 339aec5c table=pb_2589955   ← Atros entry created
03:53:36  [HAND_ID] Initial hand 27d1d74e table=pb_2589955   ← monarchi entry created
03:53:36  [HAND_ID] Skipping reset: bot=monarchi in=PREFLOP cur=None last_bot=None
```

After container restart (w4p-api-selection-v1 deployed ~03:50), new per-bot entries were created with fresh hand_ids. Atros's entry has `339aec5c`, monarchi's has `27d1d74e`.

### Current Hand State (04:13 UTC)

```
hand_id: 60227f46 (allinstalker entry, unchanged since 02:35:18)
street: PREFLOP
dealer: 1
pot: 0
board: empty
seats: 9 (only allinstalker populated)
```

---

## What We Learn From This Tracer

1. **Hand IDs are generated per entry, not per hand.** Three different hand_ids for the same poker hand because each bot has its own entry.

2. **Hand detection oscillates.** At 02:27, 4 "New hand" events in 3 seconds — each from a different bot's heuristic firing independently.

3. **Extension echo was temporarily active.** The "Extension reports new hand" log lines at 02:27 show the extension WAS echoing hand_ids at that time. But the extension has since been reloaded/lost that code.

4. **Guard blocks legitimate resets.** The guard's `last_street_bot=None` means it can never distinguish interleaved-bot resets from same-bot resets. It blocks everything.

5. **hand_id is static for hours.** `60227f46` has been the hand_id for the allinstalker entry since 02:35:18 — across dozens of real hand transitions. It never changes because the guard blocks every reset.

---

## Hand Transition Trace (hypothetical idealized path)

```
TIME     EVENT                           STREET    CARDS      RESET?
─────────────────────────────────────────────────────────────────────
T+0      Hand X starts                   PREFLOP   none       Initial hand
T+10s    Flop dealt                      FLOP      [2s,3s,4s] No (forward)
T+15s    Turn dealt                      TURN      [+5s]      No (forward)
T+20s    River dealt                     RIVER     [+6s]      No (forward)
T+25s    Hand X ends, Hand Y starts      PREFLOP   none       YES → BLOCKED
T+26s    Hand Y PREFLOP snapshot         PREFLOP   none       Blocked → 
          → seats NOT cleared                          seats with old cards survive
T+27s    Merge: Hand Y seats + Hand X    PREFLOP   MIXED      Blocked
          stale seats
T+30s    API returns mixed seats         PREFLOP   MIXED      —
T+30.5s  Engine renders mixed textarea   PREFLOP   MIXED      —
```

The overlap is introduced at T+25s when the legitimate hand reset is blocked, and becomes visible in the API at T+30s.

# SNAPSHOT_REDUNDANCY_REPORT.md
## W4P Snapshot Redundancy Analysis

**Date:** 2026-07-03
**Investigation:** READ-ONLY

---

## 1. Methodology

Analyzed 50,747 per-seat W4P log entries from 2026-07-03 to identify:
1. Consecutive identical snapshots (same bot, same state)
2. Meaningful vs. redundant updates
3. Classification of why each snapshot was sent

---

## 2. Redundancy Analysis

### 2.1 Consecutive Same-Bot Snapshots

From run-length analysis of 33,420 ACCEPT lines:
- 86% of runs are length 1 (immediate bot switch)
- Mean run length: 1.5 POSTs per bot before switching

With per-bot isolation, consecutive snapshots from the SAME bot are rare during multi-bot periods because the interleaving pattern ensures bots alternate. This means duplicate-detection analysis is less relevant — the issue is conflicting observations, not redundant ones.

### 2.2 Same-State Analysis (00:32:20-00:32:29)

During the oscillation period, each bot consistently reports the SAME state:

```
allinstalker at 00:32:20: street=PREFLOP, avail=[back_to_game]
allinstalker at 00:32:21: street=PREFLOP, avail=[back_to_game]  ← identical
allinstalker at 00:32:22: street=PREFLOP, avail=[back_to_game]  ← identical
allinstalker at 00:32:23: street=PREFLOP, avail=[back_to_game]  ← identical
...

Atros at 00:32:24: street=FLOP, avail=[check, bet]
Atros at 00:32:25: street=FLOP, avail=[check, bet]  ← identical
Atros at 00:32:26: street=FLOP, avail=[check, bet]  ← identical
...
```

Within each bot's stream, consecutive snapshots are IDENTICAL. The bot observes the same game state and sends the same data. From a per-bot perspective, these ARE redundant — the bot hasn't changed state but still POSTs every 300ms.

### 2.3 Classification of POSTs

From the hero seat analysis:

| Bot | Total Hero Entries | Active (has actions) | Active % | Typical State |
|-----|-------------------|---------------------|----------|---------------|
| Atros | 12,670 | 4,912 | 39% | Alternates between active (check/bet/fold) and inactive (idle) |
| monarchi | 11,374 | 5,039 | 44% | Alternates between active and inactive |
| allinstalker | 8,770 | 8,770 | 100% | Always back_to_game |

---

## 3. Redundancy Classification

| Reason | Estimated % | Evidence |
|--------|-------------|----------|
| No change from previous POST (same bot, same state) | ~70%+ | Consecutive same-bot snapshots are identical during stable periods |
| Minor change (timer, stack jitter) | ~15% | Stack amounts fluctuate between scrapes |
| Street change (new hand phase) | ~10% | 2,517 street changes observed |
| Board change (new cards) | ~5% | Typically coincides with street changes |
| Hero action change | ~10% | Active/inactive transitions, new available_actions |

**Note:** Percentages overlap (a single snapshot can have multiple changes).

---

## 4. Why Snapshots Are Sent

From w4p.js:2084-2085:
```javascript
// Send every tick — no dedup, no heartbeat gate
sendSnapshot(snap);
```

The extension ALWAYS sends a snapshot on every tick (300ms). There is:
- ❌ No change detection
- ❌ No deduplication gate
- ❌ No heartbeat vs meaningful-update distinction
- ❌ No backoff for idle periods

The extension was designed during single-bot operation where "always send" was correct — every snapshot was the only source of truth. With multi-bot operation, this design is wasteful but not actually harmful to the backend (which can handle the throughput).

---

## 5. Could Deduplication Fix the Flicker?

**No.** Deduplicating within each bot's stream would reduce backend load but would NOT prevent the API alternation between bot entries.

If allinstalker only POSTs when state changes:
- It would stop POSTing during stable PREFLOP periods
- But Atros and monarchi would continue POSTing with FLOP state
- The API would consistently return FLOP (no more alternation with PREFLOP)
- BUT: when allinstalker's state DOES change (e.g., it joins a new game), it would POST again, potentially creating another alternation

**Deduplication would reduce the frequency of oscillation but would not eliminate it.** The root cause (API selecting between bot entries with different game states) remains regardless of how often each bot POSTs.

---

## 6. Conclusion

**Hypothesis PARTIALLY CONFIRMED: Redundant identical snapshots exist but are not the root cause.**

- ~70%+ of snapshots may be redundant (no state change from previous POST)
- The extension sends every tick without deduplication
- Redundant snapshots increase the alternation frequency but are not the cause of alternation
- Eliminating redundancy would reduce oscillation frequency but not eliminate it
- The API selector logic (`_dedup_latest_by_table()`) is the actual cause — it alternates between bot entries regardless of redundancy

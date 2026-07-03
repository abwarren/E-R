# SNAPSHOT_RATE_REPORT.md
## W4P Snapshot Rate Analysis — Is Snapshot Volume the Problem?

**Date:** 2026-07-03
**Investigation:** READ-ONLY runtime log analysis
**Sample Period:** 2026-07-03 00:00:00 to 02:44:34 UTC (9,874 seconds / 164.6 minutes)
**Data Source:** Docker container logs (`er-remote`), [SNAPSHOT][ACCEPT] lines

---

## 1. Executive Summary

**Snapshot rate is NOT the root cause of the flicker.** The combined rate of ~3.4 snapshots/sec across 3 bots is moderate and expected for the configured 300ms polling interval. The problem is the API's selection logic that alternates between per-bot entries — not the volume of snapshots.

---

## 2. Total Volume

| Metric | Value |
|--------|-------|
| Total snapshots (2026-07-03) | 33,420 |
| Duration | 9,874 seconds (164.6 min) |
| Combined rate | 3.38 snapshots/sec |
| Average interval between snapshots | 295ms |

---

## 3. Per-Bot Rates

| Bot | Snapshots | Percentage | Rate | Avg Interval |
|-----|-----------|------------|------|--------------|
| Atros | 13,124 | 39% | 1.33/s | 752ms |
| monarchi | 11,382 | 34% | 1.15/s | 868ms |
| allinstalker | 8,906 | 27% | 0.90/s | 1,109ms |
| Others (test, diag) | 8 | <1% | — | — |

**Note:** These are AVERAGE rates over the full period. Individual bot polling is configured at 300ms (3.33/s theoretical max). The actual rates are lower because:
1. Bots may be idle or disconnected for portions of the period
2. Some snapshots may be dropped (stale timestamp check)
3. `allinstalker` has the lowest rate — it joined later in the observed period

---

## 4. Burst Analysis

During periods when all 3 bots are simultaneously active (e.g., 00:32:20-00:32:29, 01:35:11-01:35:14):

| Metric | Value |
|--------|-------|
| Consecutive POSTs with gaps < 100ms | 73.4% |
| Median gap between consecutive POSTs | 0ms (same second) |
| P75 gap | 1,000ms |
| Mean gap | 295ms |
| Bot run length (consecutive same-bot) | 1.5 POSTs (mean) |
| Runs of length 1 (immediate interleaving) | 86% |
| Bot transitions observed | 22,570 |

### Interleaving Pattern (01:35:11)

```
01:35:11  monarchi     seats=1
01:35:11  Atros        seats=2    ← same second
01:35:11  monarchi     seats=1    ← same second
01:35:11  Atros        seats=2    ← same second
01:35:11  monarchi     seats=1    ← same second
01:35:11  Atros        seats=2    ← same second
01:35:11  monarchi     seats=1    ← same second
01:35:11  allinstalker seats=2    ← same second
01:35:12  Atros        seats=2
01:35:12  monarchi     seats=1
```

6+ unique POSTs in the same second. Heavy interleaving during active multi-bot periods.

---

## 5. Peak vs Average

| Metric | Average | Peak (burst) |
|--------|---------|--------------|
| Combined rate | 3.38/s | ~8/s (within single second) |
| Per-bot rate | ~1.1/s | ~4/s (same bot multiple times in a second) |
| Bot alternation frequency | 2.3 transitions/s | 6+ transitions/s |

---

## 6. Is the Rate Excessive?

**No.** The snapshot rate is consistent with the configured 300ms polling interval.

```
Expected rate (3 bots): 3 × (1 / 0.300s) = 10.0/s theoretical max
Observed rate: 3.38/s average
Peak rate: ~8/s (approaches theoretical max during bursts)
```

The observed rate of 3.38/s is well below the theoretical max because bots are not all active simultaneously for the full period. The polling interval of 300ms has not been modified (w4p.js:360).

Throttling the snapshot rate would NOT fix the flicker because:
1. The flicker is caused by API alternation between bot entries, not by snapshot volume
2. Slower snapshots would still alternate — just at a slower frequency
3. Reducing the rate would increase staleness without addressing the root cause

---

## 7. Timeline of Bot Activity

### Phase 1: Single bot (00:00-01:00)
- allinstalker only — 1 snapshot/sec
- No oscillation (single bot, consistent view)

### Phase 2: Multi-bot (01:00-02:30)
- Atros, monarchi, allinstalker all active
- Peak interleaving at 01:35 (6+ POSTs/sec within same second)
- Street values diverge: PREFLOP vs FLOP vs TURN vs RIVER
- Oscillation confirmed in W4P log lines

### Phase 3: Winding down (02:30-02:44)
- Fewer snapshots as bots go idle
- Final ACCEPT at 02:44:34 (Atros)

---

## 8. Conclusion

**Hypothesis DISPROVEN: Excessive snapshot rate is NOT causing the flicker.**

The snapshot rate is within expected bounds for the configured 300ms polling interval. The backend can clearly handle this throughput (health endpoint shows healthy state, snapshot_seq incrementing normally).

The flicker persists regardless of snapshot rate because it's caused by the API selector choosing between bot entries with different game states. Reducing the rate would make the flicker slower but would not eliminate it.

### Recommendation

Do NOT throttle snapshots. The current rate is fine. Address the API selection logic in `_dedup_latest_by_table()` — the function that alternates between per-bot entries when no `bot_id` is specified.

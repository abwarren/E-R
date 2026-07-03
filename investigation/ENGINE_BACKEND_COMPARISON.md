# ENGINE_BACKEND_COMPARISON.md
## W4P Engine vs Backend — Divergence Analysis

**Date:** 2026-07-03
**Investigation:** READ-ONLY

---

## 1. Data Flow Comparison

| Stage | Backend State | Engine State | Same? |
|-------|-------------|-------------|-------|
| Snapshots received | 3 bots × 300ms | — | — |
| per-bot entries | 3 independent entries | — | — |
| `_select_best_table()` | Picks best entry by freshness+street+last_ts+hash | — | — |
| `/api/latest` response | Returns selected entry's `_table_view()` | Receives this | ✅ Identical |
| `formatTableDataToCanonical()` | — | Converts response to text | ✅ Faithful |
| `setTextareaValue()` | — | Replaces textarea | ✅ Faithful |
| Textarea content | — | What API provided | ✅ No divergence |

**Finding: The Engine does NOT introduce divergence. It faithfully renders whatever the API returns. If the API returns mixed data, the Engine displays mixed data.**

---

## 2. API Response vs Engine Internal Model

The Engine has NO internal model beyond:
- `lastSnapshotHash` — text-based dedup (line 22)
- `lastStateKey` — auto-run state dedup (line 22)
- `lastDataChange` — poll speed adaptation (line 28)

The Engine does not:
- Cache previous API responses
- Maintain a persistent model of table state
- Accumulate data across polls
- Merge old and new data

Each poll is a complete refresh. The Engine's state after each poll is exactly the API response at that moment.

---

## 3. First Divergence Point

If the API response is consistent (no stale cards), the Engine output is consistent. There is no divergence.

If the API response contains stale hole_cards (due to blocked hand reset), the Engine faithfully includes those stale cards. The "divergence" is between the Engine display and what the CORRECT hand data should be — but the Engine is not the source of the divergence.

---

## 4. Poll Timing

| Component | Frequency | Effect |
|-----------|----------|--------|
| Extension → Backend | 300ms | Frequent writes to per-bot entries |
| Backend `/api/latest` | On-demand (long-poll) | Returns current state immediately |
| Engine poll | 1.5s active / 5s idle | Receives snapshot of best entry |

The Engine polls at 1.5-5s intervals. At 3.4 snapshots/sec from the backend, the Engine sees approximately every 5th-17th snapshot. This is coarse enough that the Engine skips intermediate states but fine enough that any stale data persisting across hand transitions will be visible within 1-2 poll cycles.

---

## 5. Engine Auto-Run vs Manual

The Engine has two modes:
1. **Auto-fill ON:** `setTextareaValue()` + `maybeAutoRun()` on every poll
2. **Auto-fill OFF:** Only `setTextareaValue()` on every poll

In both modes, the textarea is replaced. The difference is whether the "Run Engine" button is automatically clicked. Both modes are equally affected by stale hole_cards because both use the same `formatTableDataToCanonical()` source.

---

## 6. What Would Fix Look Like (Not Implementation)

The fix is NOT in the Engine. The Engine is a faithful consumer. The fix is in the backend at lines 1149-1159:

1. **Set `last_street_bot`** when a snapshot's structural fields are written (near lines 1198-1204). This would make the guard conditional (only block when a DIFFERENT bot's regression attempts to reset).

2. **Or: Remove the guard entirely** — with per-bot isolation (a58a6ee), interleaved bots no longer share state. The guard was designed for the shared `_tables[table_id]` model that no longer exists. Per-bot entries don't need cross-bot reset protection because each bot writes to its own entry.

---

## 7. Component Responsibility Matrix

| Component | Hand Detection | Seat Cleanup | Card Management |
|-----------|---------------|-------------|-----------------|
| Extension | ❌ Not responsible | ❌ Not responsible | ❌ Not responsible |
| Backend | ✅ Responsible (blocked by guard) | ✅ Responsible (blocked by guard) | ✅ Responsible (blocked by guard) |
| Engine | ❌ Not responsible | ❌ Not responsible | ❌ Not responsible |

All three responsibilities reside in the backend. All three are blocked by the same guard.

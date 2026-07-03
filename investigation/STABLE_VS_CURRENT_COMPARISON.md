# STABLE_VS_CURRENT_COMPARISON.md
## W4P Baseline (w4p-seat-stability-v1) vs Deployed (172a0ee)

**Date:** 2026-07-03

---

## 1. Baseline: w4p-seat-stability-v1 (94a6cfc)

### Architecture

```
_tables = {
    "pb_2589955": {
        street, board, pot, dealer, seats, ...
    }
}
```

- Single `_tables[table_id]` entry — ONE mutable dictionary per table
- All bots writing to same `table_id` shared the SAME object
- Structural fields (street, board, pot, dealer) set UNCONDITIONALLY from every POST
- "Last writer wins" semantics

### Why It Was Stable (for single-bot)

With ONE bot posting to `pb_2589955`:
- Only one source of truth
- No interleaved writes
- Each POST updated the same entry with consistent data
- `/api/latest` returned that single entry — always coherent

### Why It Became Unstable (for multi-bot)

When a SECOND bot began posting to the same `table_id`:
- Two independent DOM scrapes, potentially different game states
- Each POST unconditionally overwrote structural fields
- Street oscillation: FLOP → PREFLOP → FLOP → PREFLOP (documented in MULIT_BOT_MERGE_REPORT.md)
- Hand reset detection misfired (street regression detected between bots)
- 3+ hand resets per second during divergence

---

## 2. Current: 172a0ee (HEAD)

### Architecture

```
_tables = {
    ("pb_2589955", "Atros"):        { street=FLOP,    ... },
    ("pb_2589955", "monarchi"):     { street=FLOP,    ... },
    ("pb_2589955", "allinstalker"): { street=PREFLOP, ... },
}
```

- Per-bot isolation: key = `(table_id, bot_id)` (commit a58a6ee)
- Each bot has INDEPENDENT state — no cross-bot overwrite
- Structural fields gated on `hero_active` (commit 5a31670)
- API uses `_dedup_latest_by_table()` to select one entry (commit 172a0ee)

### Why It's More Stable Than Baseline

- ✅ Bots cannot overwrite each other's state within their own entry
- ✅ Hand resets are scoped per-bot (Atros's reset doesn't clear monarchi's data)
- ✅ `_seat_bots` mapping is scoped per-entry
- ✅ Hand IDs correctly reflect per-bot identity

### Why It Still Oscillates

- ❌ `_dedup_latest_by_table()` picks the most recent bot entry
- ❌ Most recent entry changes every ~100-150ms with 3 bots
- ❌ Different bots have different `street` values → API alternates
- ❌ Structural field gate bypassed by `back_to_game` actions

---

## 3. Side-by-Side Comparison

| Aspect | Baseline (94a6cfc) | Current (172a0ee) |
|--------|-------------------|-------------------|
| State model | Single `_tables[table_id]` | `_tables[(table_id, bot_id)]` |
| Cross-bot overwrite | Yes — unconditional | No — per-bot isolation |
| Hand reset scope | Global (all bots affected) | Per-bot (bot-specific) |
| hand_id | None | UUID per entry |
| Structural field guard | None | `hero_active` gate (bypassed) |
| API selector | `max(_tables.values(), key=last_ts)` | `_dedup_latest_by_table()` |
| API `bot_id` param | Not supported | Supported (`?bot_id=Atros`) |
| Single-bot operation | ✅ Works | ✅ Works (backward compatible) |
| Multi-bot oscillation | ❌ Severe (unconditional overwrite) | ⚠️ Reduced but still present (API alternation) |
| Hand reset frequency | ~3/sec during divergence | ~24/sec (per-bot entries) |
| Seat data survival | ❌ Lost on every reset | ✅ Per-bot entries retain seats |
| _seat_bots drift | ✅ Correct | ✅ Correct (per-entry scoping) |

---

## 4. Snapshot Rate Comparison

| Metric | Baseline | Current |
|--------|----------|---------|
| Per-bot polling interval | 300ms | 300ms (unchanged) |
| Total snapshots (all bots) | ~3.3/s (1 bot) | ~3.4/s (3 bots observed) |
| Dedup | None | None (unchanged) |
| Burst interleaving | N/A (single bot) | 73% of gaps < 100ms |
| Mean run length (same bot consecutively) | ∞ (single bot) | 1.5 POSTs |

---

## 5. What Actually Changed Between Releases

The flicker was NOT introduced by `w4p-seat-stability-v1`. That release only changed `source/remote-w4p.html` (4 patches for sitting-out display).

The flicker was introduced by **multi-bot operation beginning** — a second (and third) bot instance started posting to the same `table_id`. The baseline architecture was never designed for this scenario.

The post-baseline commits (a58a6ee, 5a31670, 172a0ee) were attempts to fix the oscillation without rethinking the API selection model. They partially succeeded (per-bot isolation prevents cross-contamination) but the API layer's "pick the latest" semantics fundamentally assume a single coherent game state.

---

## 6. Visual Comparison

### Baseline Oscillation Path
```
Extension A (FLOP) ──→ POST ──→ _tables[pb_2589955].street = FLOP
Extension B (PREFLOP) ──→ POST ──→ _tables[pb_2589955].street = PREFLOP
Extension A ──→ POST ──→ _tables[pb_2589955].street = FLOP
...
API always returns _tables[pb_2589955] → oscillates
```

### Current Oscillation Path
```
Extension A (FLOP) ──→ POST ──→ _tables[(pb_2589955, A)].street = FLOP
Extension B (PREFLOP) ──→ POST ──→ _tables[(pb_2589955, B)].street = PREFLOP
Extension A ──→ POST ──→ _tables[(pb_2589955, A)].street = FLOP
...
API calls _dedup_latest_by_table() → picks most recent entry → oscillates
```

**The per-bot isolation changed WHERE oscillation happens (from merge level to API selection level) but didn't eliminate it.**

---

## 7. Summary

| Question | Answer |
|----------|--------|
| Was the baseline stable? | ✅ Yes, for single-bot operation |
| Why? | Single entry, consistent data, no interleaving |
| What changed? | Multi-bot operation began; post-baseline code deployed |
| Is current better than baseline? | ⚠️ Partially — per-bot isolation is architecturally correct, but the API selector undoes it |
| Does the flicker still occur? | ✅ Yes — confirmed via runtime logs |
| Is the root cause different from baseline? | ✅ Yes — was unconditional overwrite; now is API alternation between bot entries |

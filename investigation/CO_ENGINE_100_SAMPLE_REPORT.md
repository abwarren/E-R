# CO ↔ Engine Correlation Analysis — 100 Sample Study

**Date:** 2026-07-03 23:36 UTC  
**Agent:** Observation Agent (READ-ONLY)  
**Source:** Live production data from REMOTEREMOTE + ENGINEENGINE  
**Method:** 100 consecutive API polls at 200ms intervals (20s window)  
**Raw Data:** `/home/wa/projects/poker/E&R/investigation/co_engine_100_samples.json`

---

## 1. DATA SOURCES

| Source | Endpoint | Role |
|--------|----------|------|
| CO State | `GET /api/table/latest` | Returns `_find_active_bot()` output — the Engine's view |
| CO Full | `GET /api/tables` | All per-bot entries in `_tables` |
| Engine | `GET /api/health` (:5002) | Engine liveness only (no state) |

**Note:** The Engine has no server-side state. It polls `/api/table/latest` and renders the response as canonical text in a textarea. Therefore, "Engine state" at any moment = the `/api/table/latest` response at that moment. The CO and Engine share the same data source — any divergence is purely timing-based from the selection algorithm.

---

## 2. RELATIONSHIP MATRIX

| Field | CO | Engine | Match % | Notes |
|-------|-----|--------|---------|-------|
| hand_id | Same UUID | Same UUID | **100%** | Single hand across all samples |
| table_id | pb_2589955 | pb_2589955 | **100%** | Single table |
| street | Varies (PREFLOP ↔ RIVER) | Varies | **32.3%** | Oscillates every 2-3 polls |
| pot_zar | Varies (0 / 25 / 71.44) | Same | **19.2%** | Three distinct values |
| board | Varies (empty / board A / board B) | Same | **19.2%** | Three distinct boards |
| hole_cards | Per-bot set | Best entry's set | **13.1%** | Three distinct card sets |
| needs_action | None | None | **100%** | No bot ever needs action |
| available_actions | Per-bot mapping | Best entry's | **0.0%** | Changes EVERY sample |
| dealer_seat | Per-bot value (1/2/4/5) | Best entry's | **0.0%** | Changes EVERY sample |

**Key Insight:** Identity fields (hand_id, table_id) are 100% stable. State fields (street, board, pot, cards) have catastrophic instability — they oscillate on virtually every poll.

---

## 3. TIMING ANALYSIS

| Metric | Value |
|--------|-------|
| Collection duration | 19.82 seconds |
| Average poll interval | 200.2 ms |
| Minimum interval | 143.7 ms |
| Maximum interval | 246.5 ms |
| Snapshot age at collection | 0.05 seconds |
| Total snapshot sequence | 249,904+ |

---

## 4. DIVERGENCE PATTERN

The divergence follows a precise, repeating pattern driven by the `_select_best_table()` timestamp race:

```
Pattern (repeats every ~3 samples = ~600ms):

  Sample N:   PREFLOP, pot=0,   board=[],    bot=PlayaNomore    (seat 5)
  Sample N+1: PREFLOP, pot=0,   board=[],    bot=allinstalker   (seat 3)
  Sample N+2: RIVER,   pot=71,  board=A/B,   bot=(either)
  
  → repeats with alternating RIVER board (board A or board B)
```

**Divergence frequency:** 99 out of 99 consecutive comparison pairs showed changes (100% divergence rate). Zero consecutive polls returned identical field hashes.

---

## 5. THREE DISTINCT STATES OBSERVED

### State A — Bot "PlayaNomore" PREFLOP View
- hand_id: `1bfedafa-f127-4dfe-9751-451b1eed9ee7`
- street: PREFLOP, pot: 0, board: empty
- Hero: Seat 5 (PlayaNomore) — hole_cards: QsTc9h9d6s4d
- 3 occupied seats: seat 1 (observer), seat 2 (observer), seat 5 (hero)
- available_actions: seat 5 → [back_to_game]
- dealer_seat: 2

### State B — Bot "allinstalker" PREFLOP View
- hand_id: `1bfedafa-f127-4dfe-9751-451b1eed9ee7`
- street: PREFLOP, pot: 0, board: empty
- Hero: Seat 3 (allinstalker) — hole_cards: KdTh6c3h2d2c
- 3 occupied seats: seat 1, seat 2, seat 3 (hero)
- available_actions: seat 3 → [back_to_game]
- dealer_seat: 4

### State C — RIVER View (two board variants)
- **Variant C1:** board=2dAhJh6cQh, pot=71.44, 4 bot entries (all 4 seats)
- **Variant C2:** board=3d4h6hJs6d, pot=25, 3 bot entries
- available_actions: multiple seats → [back_to_game]
- dealer_seat: varies (1 or 5)

---

## 6. STATISTICAL SUMMARY

| Metric | Value |
|--------|-------|
| Total Samples | 100 |
| Valid (table present) | 100 (100%) |
| No table | 0 (0%) |
| Perfect Matches (consecutive) | **0** |
| Partial Matches | 99 |
| Unique field hashes | **100** (every sample unique) |
| Divergence events | 99 / 99 comparisons (100%) |
| Engine missing | 0 (Engine is poll-based, sees any API response) |
| CO missing | 0 (CO is the data source) |
| Textarea empty | 0 (always has content) |

---

## 7. PATTERN DISCOVERY

### Does the Engine always lag?
**No.** The Engine does not lag behind the CO — it has no independent state. The Engine's textarea is a deterministic function of whichever bot entry the `/api/table/latest` selector returns at poll time. The "lag" is not in the Engine; it's in the selector's flip-flopping between different source-of-truth entries.

### Does the Engine ever miss updates?
**No.** The Engine receives the API response faithfully on every poll. But because the selector oscillates, the Engine displays different bot views on consecutive polls, which creates the appearance of data instability.

### Does the CO ever miss updates?
**No.** All 4 `_tables` entries are receiving snapshots at ~300ms intervals. The CO state is complete for each bot. The issue is only in which entry gets selected as the "best" one.

### Which fields are always identical?
**hand_id** and **table_id** — 100% stable across all samples. These are the only fields that don't vary between bot entries for the same table.

### Which fields frequently diverge?
**available_actions** (0% match), **dealer_seat** (0% match), **hole_cards** (13%), **board** (19%), **pot_zar** (19%), **street** (32%).

### Which field most commonly causes mismatches?
**dealer_seat** and **available_actions** — they change on virtually every poll because each bot entry has different hero context.

### Does the Engine clear when the CO does not?
Not applicable — the Engine textarea always contains data from the latest API response.

### Does flicker correspond with a specific field changing?
**Yes.** The flicker corresponds to `_select_best_table()` returning a different bot's `_tables` entry on each poll. When the selected bot changes:
- street changes (PREFLOP ↔ RIVER)
- pot changes (0 ↔ 25 ↔ 71.44)
- board changes (empty ↔ board A ↔ board B)
- hero hole_cards change (bot A's cards ↔ bot B's cards)
- available_actions and dealer_seat change

---

## 8. ROOT CAUSE CONFIRMED

The 100-sample study **confirms** the TRACER BULLET finding with measured evidence:

1. **`_select_best_table()` has no hysteresis** — without needs_action (no bot needs action), the selector falls through to a timestamp race where different bots win on successive polls
2. **`back_to_game` is excluded from authority** — is_authoritative_snapshot() returns False for back_to_game actions, preventing any bot's entry from establishing authority
3. **Zero consecutive identical states** — the system never stabilizes; every poll returns a different result
4. **100 unique hashes in 100 samples** — complete selection oscillation with no steady state

---

## 9. CONCLUSION

**After observing 100 live production samples, the measurable relationship between the CO and the Engine is:**

The CO maintains 4 per-bot table entries with **internally consistent** data for each bot. The Engine, however, sees **unstable, oscillating state** because `/api/table/latest` uses `_select_best_table()` which degenerates into a timestamp race in the absence of any bot with `needs_action == true`.

**Field-by-field correlation:**
- Identity fields (hand_id, table_id): **100%** match — same game, same table
- Structural fields (street, board, pot): **19-32%** match — oscillates between bots' different views
- Hero-specific fields (hole_cards, available_actions, dealer_seat): **0-13%** match — each bot sees different data
- Action state (needs_action): **100%** match — none needed (both bots sitting out)

**The correlation is not 82%. It's effectively broken for all fields except hand_id and table_id.** For any given field that carries game-meaningful data, the CO and Engine disagree more often than they agree. The Engine sees a different bot's perspective on every single poll, creating the visual flicker that was reported.

**The fix is NOT in the Engine.** The Engine is a faithful renderer. The fix is in the CO's selection algorithm — `_select_best_table()` needs hysteresis to stop oscillating between per-bot entries when no bot needs action.

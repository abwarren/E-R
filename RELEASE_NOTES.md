# RELEASE NOTES — w4p-api-selection-v1

**Date:** 2026-07-03
**Commit:** ed293b9
**ADR:** ADR-002-API-SELECTION-POLICY.md

## Scope of Change

Replaced the API selection policy for `/api/latest` from "last writer wins"
(`_dedup_latest_by_table`) to deterministic best-state selection
(`_select_best_table`).

When multiple bots share the same `table_id`, the API now returns the most
advanced recent game state rather than whichever bot posted most recently.
This eliminates Remote UI oscillation caused by interleaved per-bot entries
at different game stages (lobby vs live hand).

## Selection Algorithm

Priority order (higher wins):

1. Freshness — entry must be recent (< 30s)
2. Street rank — RIVER > TURN > FLOP > PREFLOP
3. last_ts — most recently updated
4. hash(bot_id) — deterministic tiebreak

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| `backend/app.py` | -11/+65 | Replace selector function, add scoring |

No changes to: extension (w4p.js), Remote UI (remote-w4p.html),
Engine (engine_flow_controls.js), Express (server.js),
snapshot format, storage model, or API contract.

## Files Added

| File | Purpose |
|------|---------|
| `scripts/test_api_selection.py` | 14 unit tests for selection algorithm |

## What This Fixes

| Symptom | Resolved? |
|---------|-----------|
| Remote UI street oscillation | ✅ Yes |
| Remote UI board oscillation | ✅ Yes |
| Remote UI pot oscillation | ✅ Yes |
| Remote UI dealer oscillation | ✅ Yes |
| /api/latest alternation between bot entries | ✅ Yes |
| Stale advanced street dominating fresh earlier street | ✅ Yes |

## What This Does NOT Fix

This release fixes the API **selection policy**, not the underlying multi-bot
architecture. The following remain as ADR-001 Phase 2 work:

- Runtime state NOT partitioned by `(table_id, hand_id)`
- Multiple independent hand contexts at the same `table_id` are NOT isolated
- The SQL Event Store hand_id foundation is NOT yet wired

## Classification

**Resolved:** Multi-bot API selection oscillation — replaced "last writer wins"
with deterministic best-state selection.

**Not resolved:** Multi-bot architecture — depends on completing hand_id
partitioning (ADR-001 Phase 2).

## Regression Tests

```
scripts/test_api_selection.py — 14/14 PASS
```

| Scenario | Result |
|----------|--------|
| Single bot | PASS |
| Two bots: PREFLOP vs FLOP | PASS |
| Two bots: FLOP vs TURN | PASS |
| Same street, newer timestamp | PASS |
| Three bots: mixed streets | PASS |
| Stale TURN (45s) vs fresh FLOP (4s) | PASS |
| All entries stale | PASS |
| Empty table | PASS |
| Hero inactive | PASS |
| Board complete on one bot only | PASS |
| Identical timestamps (determinism) | PASS |
| bot_id=None observer entries | PASS |
| Determinism — 10/10 identical results | PASS |
| table_id parameter support | PASS |

## Rollback

```bash
git revert ed293b9
```

## Live Validation

Pending — requires 20-30 minute observation with 2+ bots connected:

- [ ] No Remote UI flicker
- [ ] No Engine textarea overwriting
- [ ] No street oscillation
- [ ] No board oscillation
- [ ] No dealer oscillation
- [ ] No seat collisions
- [ ] No hand collisions

---

# RELEASE NOTES — w4p-seat-stability-v1

**Date:** 2026-07-02
**Commit:** 94a6cfc
**Tag:** w4p-seat-stability-v1

## Scope of Change

Sitting out is a player state, not a seat removal event. The Remote UI grid
represents physical table positions — players must remain visible in their
assigned slot regardless of whether they are sitting out, folded, or active.

Prior to this fix, sitting-out players were excluded from the Remote UI grid
entirely. A player who sat out would vanish from their seat slot, giving the
appearance of an empty seat. When they returned, they reappeared — but the
intermediate state was wrong.

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| `source/remote-w4p.html` | 4 patches | posSeatMap filter, CSS, sitting-out class, seatHash |

No changes to: extension (w4p.js), backend (app.py), API, seat assignment,
snapshot format, or any other file.

## Changes

1. **posSeatMap filter (L1020-1022):** Removed `seat.status !== "sitting_out"`
   exclusion. Filter now only requires `seat.name != null`.

2. **CSS (L192-202):** Added `.seat-box.sitting-out` rule — 45% opacity,
   grey border, no shadow. Adds `.seat-sitting-label` styling.

3. **buildSeatBoxHtml (L874, L895-897):** Conditionally adds `sitting-out` CSS
   class and renders "SITTING OUT" label when `seat.status === 'sitting_out'`.

4. **seatHash (L828):** Includes `seat.status` in the hash string so state
   transitions (playing ↔ sitting_out) trigger re-renders.

## Test Evidence

```
scripts/test_seat_stability.js — 26/26 PASS
```

| Scenario | Result |
|----------|--------|
| CSS: .seat-box.sitting-out rule exists | PASS |
| CSS: sitting-out opacity < 1 | PASS |
| CSS: .seat-sitting-label display:block | PASS |
| posSeatMap: sitting_out filter REMOVED | PASS |
| posSeatMap: includes all named seats | PASS |
| buildSeatBoxHtml: sitting-out class conditional | PASS |
| buildSeatBoxHtml: SITTING OUT label rendered | PASS |
| seatHash: includes seat.status | PASS |
| Scenario 1: Player active → visible in assigned seat | PASS |
| Scenario 2: Player sits out → same seat, greyed out | PASS |
| Scenario 3: Player sits back in → same seat restored | PASS |
| Scenario 4: Another sits out → no other seats move | PASS |
| Scenario 5: Hero sits out → hero stays in same seat | PASS |
| Scenario 6: New hand → seat map unchanged | PASS |
| Scenario 7: Player leaves → seat becomes empty | PASS |
| Scenario 8: seatHash differs for playing vs sitting_out | PASS |

## Regression Analysis

| Vector | Assessment |
|--------|-----------|
| posSeatMap filter | Still filters on `name != null` — nameless seats excluded |
| Empty seats | Unchanged — `name=null` seats still omitted |
| Action buttons | Unchanged — sitting-out logic independent |
| Hero detection | Unchanged — `is_self_player` unaffected |
| Seat ownership tracking | Unchanged — `lastSeatAssign` logic intact |
| C/F, C/C, auto presets | Unchanged — these are hero-only controls |
| Diff-based rendering | Enhanced — `seatHash` now includes status |
| Grid compaction | No shift possible — players never removed from grid |

## Known Limitation

**Live production verification deferred.**

EC2 SSH was unavailable (port 22 timed out) at time of release, preventing
browser-based validation with a live poker table. The test suite provides
26/26 code-level verification. Live verification will be performed when
EC2 is reachable.

See: `LIVE_VALIDATION_REQUIRED.md`

## Ship List

- [x] Code change approved
- [x] 26/26 unit tests pass
- [x] Commit to master
- [x] Push to origin
- [x] Tag w4p-seat-stability-v1
- [ ] Live production verification (EC2 down)
- [ ] Backend name-flicker investigation (separate ticket)

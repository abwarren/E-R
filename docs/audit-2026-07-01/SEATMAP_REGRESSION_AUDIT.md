# SEATMAP REGRESSION AUDIT — 2026-07-01 22:00 UTC

## Summary
Seat-mapping overlap regression diagnosed and fixed.

## Root Cause
Commit `74acebe` ("chore: sync runtime investigation fixes and ADR", 2026-07-01 01:39 UTC)
removed the entire v24 seat stability layer from w4p.js — regressing from v24-bootstrap
back to v23-hardened.

## What Was Removed (~200 lines)
- `_seatCache` — identity→seat cache `{playerName: seat_index}`
- `resolveSeatIndex()` — collision rejection + debounce algorithm
- `isTableReady()` — container position-class validation gate
- `_lastGoodSnapshot` — snapshot preservation during DOM transitions
- Within-poll collision detection via `assignedPositions`
- Swap detection (Alice⇄Bob atomic seat exchange)
- Stale cache pruning (players unseen >2min)
- Hero seat assignment verification (return null if hero has no seat)

## Critical Regression Line
```
v24 (GOOD):  var rawPosition = posMatch ? parseInt(posMatch[1]) : null;
BUG:         var seatIdx = posMatch ? parseInt(posMatch[1]) : i;
```
When `position-N` class is missing from a seat container, the loop index `i`
becomes the seat index — multiple containers get the same seat, causing player
overwrites in the backend.

## Fix Applied
Commit `cf328c7` — restored w4p.js from v24 baseline (9af1015) and applied
selector registry (ADR-013/014) on top:
- Restored full seat stability layer
- Added detectRuntime(), SELECTORS object, SEL.* references
- Added validateSelectorRegistry() + registry gate in tick()
- All hardcoded CSS selectors → SEL.* references
- Build tag: v24-bootstrap+selectors

## Files Changed
- `backend/static/ext/w4p.js` — +740/-36 lines
- `source/w4p.js` — +740/-36 lines
- Both files now identical (2119 lines)

## Verification Needed (blocked: SSH tunnel down)
1. Rebuild Docker image: `docker compose build er-remote && docker compose up -d er-remote`
2. Re-establish SSH tunnel to laptop
3. Reload Chrome extension
4. Observe 3+ full hands — verify single hero resolution
5. Check backend logs for zero `[SEAT_SYNC] collision` entries
6. Verify hero seat stable across polls and hand boundaries

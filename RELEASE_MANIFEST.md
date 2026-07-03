# RELEASE MANIFEST — w4p-seat-stability-v1

**Release:** w4p-seat-stability-v1
**Commit:** 94a6cfc
**Tag:** w4p-seat-stability-v1
**Date:** 2026-07-02
**Status:** CONDITIONAL RELEASE (live validation deferred)

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `source/remote-w4p.html` | posSeatMap filter + CSS + sitting-out class + seatHash | 4 patches |

## Files NOT Changed

- `source/w4p.js` — extension (untouched)
- `backend/app.py` — backend session state (untouched)
- `backend/static/ext/w4p.js` — loaded extension copy (untouched)
- `backend/static/ext/bridge.js` — postMessage relay (untouched)
- `backend/static/ext/background.js` — service worker (untouched)
- `source/engine_flow_controls.js` — engine poller (untouched)
- `scripts/server.js` — Express proxy (untouched)

## Protected Components

These are off-limits unless explicitly targeted:

| Component | Status |
|-----------|--------|
| Seat Assignment | ✓ Protected |
| Seat Cache | ✓ Protected |
| Selector Registry | ✓ Protected |
| Extension | ✓ Protected |
| Snapshot Format | ✓ Protected |
| Backend | ✓ Protected |
| Engine | ✓ Protected |

## Runtime Components Verified

| Component | Status |
|-----------|--------|
| Extension | ✓ Untouched |
| Backend | ✓ Untouched |
| Remote UI | ✓ 26/26 tests |
| Engine | ✓ Untouched |

## Regression Tests

```
scripts/test_seat_stability.js

26 PASS
0 FAIL
0 SKIP
```

## Live Validation

| Criteria | Status |
|----------|--------|
| Hero seated | Not verified |
| Player sits out | Not verified |
| Seat remains fixed | Not verified |
| Greyed-out state displayed | Not verified |
| Player sits back in | Not verified |
| Same seat restored | Not verified |
| No other players move | Not verified |
| Screenshots captured | Not verified |

**Reason:** EC2 SSH unavailable (port 22 timed out to 16.28.18.179).
Infrastructure failure, not code defect.

See: `LIVE_VALIDATION_REQUIRED.md`

## Rollback

```bash
git revert 94a6cfc
```

## Release History

```
v24.0.0 (bootstrap + selector registry)
  ↓
w4p-selector-registry-v1
  ↓
w4p-seat-stability-v1  ← current
  ↓
w4p-engine-proxy-v1    (pending)
  ↓
w4p-mobile-selector-v1 (pending)
```

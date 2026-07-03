# TB-W4P-001 — is_active Propagation Fix Verification

**Date:** 2026-07-03
**Status:** VERIFIED — propagation confirmed, awaiting live hero action for button render

---

## Problem

`is_active` was silently dropped during the `new_seats[seat_no]` dict construction in `backend/app.py`. The extension computed and sent `is_active=True` (when hero has visible actions), but the backend never stored it. All downstream consumers saw `False`.

## Root Cause

`app.py:1226-1238` explicitly enumerates keys for `new_seats[seat_no]`. Every field from the snapshot seat was copied EXCEPT `is_active`. This is a field omission bug — no logic was wrong, a single key was missing from a dictionary.

## Fix

One line added at `app.py:1237`:
```python
"is_active": s.get("is_active", False),
```

## Evidence Chain

| Stage | is_active | Evidence |
|-------|-----------|----------|
| Extension sends | `True` | SNAPSHOT log: `is_active=True avail=['back_to_game']` |
| `new_seats[seat_no]` dict | `True` | Log reads from raw `s` dict (same as dict source) |
| `table["seats"]` merge | `True` | Full replacement path (same bot_id) |
| `_build_seats_list()` serialization | `True` | `seat_data.get("is_active", False)` → key exists |
| `/api/latest` response | `True` | API response confirmed |
| Remote UI gate (L869) | `True` | `isHero=True, acts.length>0 → isActive=True` |

## Deployment

- Container SHA: `23550bdeee3fdfef`
- Flask PID: `308`
- Health: `{"active_tables":1,"buffer_has_data":true,"buffer_table":"pb_2589955","cdp_statu`

## SNAPSHOT Log Evidence

```
[2026-07-03 00:21:58] INFO app: [W4P][SNAPSHOT] table=pb_2589955 name=allinstalker seat_no=1 seat_index=1 is_hero=True is_active=True avail=['back_to_game'] street=PREFLOP hand= bot_id=allinstalker
[2026-07-03 00:21:59] INFO app: [W4P][SNAPSHOT] table=pb_2589955 name=allinstalker seat_no=1 seat_index=1 is_hero=True is_active=True avail=['back_to_game'] street=PREFLOP hand= bot_id=allinstalker
```

## API Response

Saved to `docs/tracer_bullets/TB-W4P-001/api_response.json`

## Remote UI Rendering

Waiting for hero to be in an active hand (currently sitting_out). When the hero faces actions:
- L852: `acts = seat.available_actions || []` → non-empty ✅
- L869: `isActive = isHero && acts.length > 0` → True ✅
- L928: `if (isActive) → render FOLD/CHECK/CALL/BET` ✅
- L906: `if (isHero) → render compact controls` ✅

## Operational Recovery

Container became unhealthy after `docker restart` due to stale PID lock (known issue, documented as pitfall #0). Recovery: `rm /tmp/w4p_backend.lock` + Flask restart. See `TB-OPS-001` for permanent fix.

## Regression Test Required

Automated test verifying:
1. Extension sends snapshot with `is_active=True`
2. POST /api/snapshot accepted
3. GET /api/latest returns `is_active=True` on hero seat
4. Value matches the snapshot

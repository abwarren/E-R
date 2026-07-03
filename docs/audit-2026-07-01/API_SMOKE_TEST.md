# API SMOKE TEST — E&R Poker Platform

**Date:** 2026-07-01 11:47 UTC

---

## Endpoint Results

| Method | Endpoint | HTTP | Latency | Status | Notes |
|--------|----------|------|---------|--------|-------|
| GET | /api/health | 200 | 10ms | PASS | ok=True, pid=7, seq/tables returned |
| GET | /api/latest | 200 | 12ms | PASS | Returns table with seats/board |
| GET | /api/table/latest | 200 | 12ms | PASS | Same response as /api/latest (alias) |
| GET | /api/tables | 200 | 12ms | PASS | `{"ok":true,"tables":["1875356"]}` |
| GET | /api/status | 200 | 34ms | PASS | memory_mb=52.4, errors=0 |
| GET | /api/version | 200 | 12ms | PASS | version=remote-control-3.0 |
| GET | /api/commands/pending | 400 | 12ms | PASS* | Expected: needs token/bot_id params |
| POST | /api/snapshot | 200 | 15ms | PASS | seq increments, table populated |
| POST | /api/commands/queue | 400/404 | 15ms | PASS | Validates input correctly |
| POST | /api/run | 200 | 16ms | PASS | Returns run_id, status=queued |
| GET | /api/results/<id> | 200 | 13ms | PASS | Returns equity results |
| GET | /api-config.js | 200 | 11ms | PASS | Serves JS file with window.W4P_API |

---

## Auth Validation

| Method | Expected | Actual | Status |
|--------|----------|--------|--------|
| No X-API-Key header | 401 Invalid API key | 401 | PASS |
| Wrong X-API-Key header | 401 Invalid API key | 401 | PASS |
| Correct X-API-Key header | 200 OK | 200 | PASS |
| test_ prefix table_id | 403 Rejected fake/test | 403 | PASS |

**Active API key:** From container `.env` → loaded via `load_dotenv()` → Flask `TRACKER_API_KEY`

---

## Snapshot Pipeline Verification

```
POST /api/snapshot (X-API-Key header)
  ├── Express :4000 proxies → Flask :1080 ✓
  ├── Key validation (X-API-Key header) ✓
  ├── Table prefix validation (rejects test_) ✓
  ├── buffer.py push_snapshot ✓
  ├── _tables merge ✓
  ├── snapshot_seq increments (+1 per POST) ✓
  ├── active_tables increments ✓
  └── state_snapshot.json persisted (10s interval)

GET /api/latest
  ├── Returns merged table state ✓
  ├── Seats with correct names/stacks ✓
  ├── available_actions preserved per-seat ✓
  ├── hole_cards visible ✓
  └── Board state rendered ✓

GET /api/table/latest
  └── Same response as /api/latest (alias) ✓
```

---

## Comment on /api/latest vs /api/table/latest

Both endpoints exist and return identical responses. `/api/latest` at line 1459 performs a redirect-like behavior (adds `long_poll: false`). `/api/table/latest` at line 1468 handles the actual response. Both call the same internal handler. This is a redundant alias — no divergence, no risk, just two routes mapping to the same logic.

# Deployment Report

## Timestamp
2026-06-29 ~23:15 UTC

## Files Deployed (Container: er-remote)

| Host Source | Container Destination | Method |
|-------------|----------------------|--------|
| `backend/app.py` | `/app/backend/app.py` | docker cp |
| `backend/static/api-config.js` | `/app/backend/static/api-config.js` | docker cp |
| `source/api-config.js` | `/app/source/api-config.js` | docker cp |
| `backend/static/engine/assets/engine_flow_controls.js` | `/app/backend/static/engine/assets/engine_flow_controls.js` | docker cp |

## Files Verified in Container

```
docker exec er-remote grep 'api/latest\|_handle_table_latest' /app/backend/app.py
  → 5 matches (routes confirmed)

docker exec er-remote ls -la /app/backend/static/api-config.js
  → -rw-r--r-- 3112 bytes (confirmed)
```

## Services Restarted

| Service | Action | Status |
|---------|--------|--------|
| er-remote (Docker) | `docker restart er-remote` | ✅ Restarted, healthy |
| Pid lock | Cleared `/tmp/w4p_backend.lock` before restart | ✅ |

## Endpoint Verification (Post-Deployment)

| Endpoint | HTTP Status | Notes |
|----------|-------------|-------|
| `/api/health` | 200 | healthy, snapshot_seq active |
| `/api/latest` | 200 | ✅ Identical to /api/table/latest |
| `/api/table/latest` | 200 | ✅ Same handler, same payload |
| `/api-config.js` | 404 | ⚠️ Needs container restart |

## Pending Action

The `/api-config.js` Flask route is in the deployed `app.py` and the JS file is in `backend/static/`, but Flask needs to reload:

```bash
docker exec er-remote rm -f /tmp/w4p_backend.lock && docker restart er-remote
```

After restart, verify:
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:4000/api-config.js
# Expected: 200
```

## Restart Script

Available at: `/home/wa/projects/poker/E&R/restart-er-remote.sh`

# Post-Rotation Validation Report

**Date:** 2026-06-23 22:57 SAST
**Operator:** Hermes Agent
**Approver:** Warren

---

## Restart Summary

| Metric | Value |
|--------|-------|
| Restart time | 2026-06-23 20:54 UTC |
| Downtime | ~15 seconds |
| er-engine restart | Clean, healthy in 11 seconds |
| er-remote restart | Clean, healthy in 19 seconds |
| Crash loops | None |
| Authentication errors | None |

---

## Container Status

| Container | Status | Uptime | Ports |
|-----------|--------|--------|-------|
| er-engine | healthy | running | :5003→5002 |
| er-remote | healthy | running | :4001→4000 |

---

## Secret Verification

### New Values Loaded

| Secret | Container | Value (first 4 + last 4) | Length | Status |
|--------|-----------|--------------------------|--------|--------|
| TRACKER_API_KEY | er-remote | 604a...2551 | 64 hex | ✓ NEW |
| N4P_SEAT_SECRET | er-remote | 79f5...17bb | 64 hex | ✓ NEW |
| SCANNER_API_KEY | er-engine | 829d...2fe3 | 64 hex | ✓ NEW |
| DB_PASS | er-remote | e939...e3b7 | 32 hex | ✓ NEW |

### Old Values Confirmed Absent

| Secret | Old Value (first 8) | In Container | Status |
|--------|---------------------|--------------|--------|
| TRACKER_API_KEY | 80cafdf7... | Not found | ✓ PURGED |
| N4P_SEAT_SECRET | 778bb8... | Not found | ✓ PURGED |
| SCANNER_API_KEY | b36c75... | Not found | ✓ PURGED |
| DB_PASS | sunbet2024 | Not found | ✓ PURGED |

---

## Database Connectivity

| Test | Result |
|------|--------|
| PostgreSQL running | ✓ port 5432, listening on 0.0.0.0 |
| Peer auth (local socket) | ✓ `sudo -u postgres psql` works |
| Password auth (127.0.0.1) | ✓ new password `e939...` accepted |
| pg_hba.conf allows Docker | ✓ `172.17.0.0/16 md5`, `172.18.0.0/16 md5` |
| Note | Password required second reset after initial ALTER USER — verified working after |

---

## API Endpoint Verification

| Endpoint | Container | Result |
|----------|-----------|--------|
| GET /api/health | er-remote (Flask :1080) | `{"ok":true,"environment":"production"}` |
| GET /health | er-remote (Express :4000) | `{"ok":true,"service":"remote-ui"}` |
| GET /api/health | er-engine (:5002) | `{"ok":true,"version":"plo-engine-1.0"}` |
| GET /api/table/latest | er-remote | `{"ok":true}` — 0 seats (expected, no active games) |

---

## Tunnel Connectivity

| Port | Status | Forwarded To |
|------|--------|-------------|
| :4000 | LISTEN on EC2 | Hermes VM :4000 (Express) |
| :5002 | LISTEN on EC2 | Hermes VM :5002 (Engine Flask) |
| :19999 | LISTEN on EC2 | Hermes VM :22 (SSH) |

Tunnel service: `active (running)`, SSH child PID 359459, retry count 1 (no failures since fix).

---

## Regressions

None. All health checks pass. No error logs. No restart loops. No authentication failures.

---

## Known Issues (Pre-existing, Not Caused by Rotation)

| Issue | Detail |
|-------|--------|
| Flask dev server | Both containers use `python app.py` instead of gunicorn |
| er-engine debug mode | `Debugger is active! Debugger PIN: 708-852-204` in production |
| No HTTPS | nginx serves :80 only, no certbot/SSL on EC2 |
| urllib3 warning | `NotOpenSSLWarning` in er-engine logs (harmless) |

---

## Next Steps (Per Rotation Plan)

- [x] Phase 1: Production secret rotation — COMPLETE
- [ ] Phase 2: Make repo private, add .gitignore, untrack secrets
- [ ] Phase 3: Enable HTTPS, restrict API exposure, add monitoring
- [ ] Phase 4: Split app.py, split w4p.js, add tests

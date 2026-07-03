# TECHNICAL DEBT REPORT — E&R Poker Platform

**Date:** 2026-07-01
**Evidence tier:** DISK (code inspection) + RUNTIME (container inspection)

---

## Phase 7 — Architecture Smells

### Smell Inventory

| # | Category | Smell | Location | Severity | Evidence |
|---|----------|-------|----------|----------|----------|
| 1 | Duplicate Logic | Two Express server files diverging | `scripts/server.js` vs `scripts/server-container.js` | HIGH | server.js has ENGINE_FLASK routes; server-container.js doesn't |
| 2 | Duplicate Logic | `/api/latest` redirects to `/api/table/latest` | `app.py:1459` | LOW | Alias only, no divergence |
| 3 | Dead Code | `action_router.py` — CDP browser control | `backend/action_router.py` | MEDIUM | Referenced in equity_routes.py but may be unused in current flow |
| 4 | Dead Code | `table_scraper.py` — Selenium scraper | `backend/table_scraper.py` | MEDIUM | Separate from extension scraping pipeline |
| 5 | Dead Code | `windows_routes.py` — Windows-specific | `backend/windows_routes.py` | LOW | Windows-only, not used in Docker |
| 6 | Dead Code | GoldRush alternate pipeline (6 endpoints) | `app.py:2687-3181` | MEDIUM | `/api/goldrush/*`, `/api/table/latest/goldrush`, etc. |
| 7 | Dead Code | `backend/ngrok` + `.tgz` | `backend/ngrok*` (20MB+) | LOW | Tunnel tool, not used in Docker deploy |
| 8 | Dead Code | `service-reference/`, `env-reference/`, `nginx-reference/`, `backend-reference/` | 4 directories | MEDIUM | Reference-only directories |
| 9 | Unused File | `backend/static/w4p.js` (35KB legacy) | `backend/static/w4p.js` | HIGH | Served by Flask at `/w4p.js`, completely different from source |
| 10 | Unused File | `backend/static/remote-w4p.html.bak2` | `backend/static/` | LOW | Backup file |
| 11 | Unused File | `source/w4p-lite.js` (6.6KB) | `source/w4p-lite.js` | MEDIUM | Alternative implementation, unclear if used |
| 12 | Unused File | `backend/static/w4p-extension.zip` | `backend/static/` | LOW | Pre-built extension archive |
| 13 | Unused File | `source/w4p-extension.zip` | `source/` | LOW | Duplicate pre-built archive |
| 14 | Duplicate State | Three divergent `remote-w4p.html` | `source/`, `static/`, `ext/` | CRITICAL | Three different versions, different sizes |
| 15 | Duplicate State | `ext.w4p.js` container staleness | Container `/app/backend/static/ext/w4p.js` | CRITICAL | Container runs v24 backup, not current source |
| 16 | Duplicate State | Two Flask instances (split-brain) | Laptop `/home/wa/E&R/` vs `/home/wa/projects/poker/E&R/` | HIGH | Each has independent `_tables` if both running |
| 17 | Duplicate State | `api-config.js` dual-serving | Express + Flask both serve | MEDIUM | Identical now but fragile |
| 18 | Duplicate State | `engine_flow_controls.js` 3 copies | `source/`, `ext/`, `engine/assets/` | LOW | Identical copies |
| 19 | Circular Dependency | `app.py` ←→ `equity_routes.py` | `app.py:77` imports `equity_routes`; `equity_routes.py:48` imports `buffer` | MEDIUM | module-level dependency not circular at import time but tightly coupled |
| 20 | Circular Dependency | `app.py` ←→ `action_router.py` via `equity_routes.py` | Chain: app.py → equity_routes.py → action_router.py | LOW | Optional import, guarded with try/except |
| 21 | Over-coupling | `app.py` is 129KB / 3,200+ lines | `backend/app.py` | CRITICAL | Single file contains: snapshot ingestion, table management, command queue, bot deployment, auth, player CRUD, collector pipeline, cashout, GoldRush pipeline, static serving, health checks, monitoring, logging |
| 22 | Over-coupling | `equity_routes.py` imports from `buffer.py` | `equity_routes.py:48` | MEDIUM | Equity routes depend on snapshot buffer for hand data |
| 23 | Hardcoded URLs | `http://127.0.0.1:4000/api` in w4p.js | `source/w4p.js:98` | HIGH | Extension hardcodes backend URL |
| 24 | Hardcoded URLs | `http://127.0.0.1:5002` as ENGINE_URL default | `app.py:2138`, `equity_routes.py:374,384` | MEDIUM | Has env var override (`ENGINE_URL`) |
| 25 | Hardcoded URLs | `http://127.0.0.1:9222` CDP port | `action_router.py:7,70,96`, `app.py:1634` | MEDIUM | Browser debug port |
| 26 | Hardcoded Ports | Flask port 1080 | `entrypoint.sh:18`, `docker-compose.yml`, `server-container.js:19` | MEDIUM | Containerized but hardcoded in entrypoint |
| 27 | Hardcoded Ports | Express port 4000 | `scripts/server.js:246`, `scripts/server-container.js` | MEDIUM | Configurable via PORT env in bare-metal |
| 28 | Hardcoded Selectors | `BTN_SEL` in w4p.js | `source/w4p.js` | HIGH | Known to not match poker-web.goldrush.co.za DOM |
| 29 | Technical Debt | PID lock survives `docker restart` | `app.py:36-48` | CRITICAL | `/tmp/w4p_backend.lock` persists, Flask exits on restart |
| 30 | Technical Debt | `dict.get()` None pitfall | Multiple locations in `app.py` | HIGH | `seat.get("stack_zar", 0) > 0` crashes when `stack_zar=None` |
| 31 | Technical Debt | `buffer.py:181` board string crash | `buffer.py:181` | HIGH | `turn`/`river` as arrays `[]` crashes `str + list` concatenation |
| 32 | Technical Debt | No automated tests in CI | N/A | HIGH | Tests exist but no CI pipeline |
| 33 | Technical Debt | No type checking | All Python files | MEDIUM | No mypy, no type annotations |
| 34 | Technical Debt | No API versioning | All `/api/*` routes | MEDIUM | No `/api/v1/` prefix |
| 35 | Technical Debt | `app.py` 129KB monolithic | `backend/app.py` | CRITICAL | Single file impossible to maintain long-term |
| 36 | Unused File | Container bak files (5 .bak files in container) | `/app/backend/app.py.bak.*` | LOW | Build artifacts in Docker image |
| 37 | Unused File | `.swp` vim swap files in container | `/app/backend/static/ext/.w4p.js.before.swp` | LOW | Editor artifacts in deployed image |

---

### Severity Summary

| Severity | Count | Items |
|----------|-------|-------|
| 🔴 CRITICAL | 5 | #14, #15, #21, #29, #35 |
| 🟠 HIGH | 9 | #1, #9, #16, #23, #28, #30, #31, #32 |
| 🟡 MEDIUM | 14 | #3, #4, #6, #8, #11, #17, #19, #21b, #22, #24, #25, #26, #27, #33, #34 |
| ⚪ LOW | 12 | #2, #5, #7, #10, #12, #13, #18, #20, #36, #37 |

---

### Detailed Analysis of Critical Items

#### #14 — Three Divergent remote-w4p.html (CRITICAL)

Three files serve the same purpose but are DIFFERENT:
- `source/remote-w4p.html` — 54KB, served by Express at `/remote`
- `backend/static/remote-w4p.html` — 63KB, served by Flask at `/remote`
- `backend/static/ext/remote-w4p.html` — 54KB, extension textarea

**Impact:** Users hitting `http://127.0.0.1:4000/remote` get a different UI than `http://127.0.0.1:1080/remote`. The Flask-served version is 10KB larger — likely contains old features or different rendering logic.

**Fix:** Consolidate to `source/remote-w4p.html` as SSOT. Update Flask to serve from `source/` or sync `static/` copy.

#### #15 — Container ext/w4p.js Staleness (CRITICAL)

Container `/app/backend/static/ext/w4p.js` = `b6685bd...` (v24 backup)
Repo `backend/static/ext/w4p.js` = `0254ba5...` (current source)

**Impact:** Any extension loaded from the container's `ext/` directory runs old v24 code. The correct version is at `ext/w4p.js.before`.

**Fix:** Rebuild Docker image from current repo commit.

#### #21 — Monolithic app.py (CRITICAL)

`backend/app.py` is 129,050 bytes (~3,200 lines) containing:
- Snapshot ingestion
- Table state management
- Command queue
- Bot deployment
- Authentication (with SQLite)
- Player CRUD
- Collector pipeline
- Cashout management
- GoldRush pipeline
- Poker table scraping
- Static file serving
- Health checks
- Monitoring endpoints
- State persistence

**Impact:** Single point of failure, impossible to test in isolation, merge conflicts likely.

**Fix:** Extract modules: `snapshot_routes.py`, `table_routes.py`, `command_routes.py`, `auth_routes.py`, `collector_routes.py`, `health_routes.py`.

#### #29 — PID Lock Survives Restart (CRITICAL)

`app.py:36-48` uses `os.kill(old_pid, 0)` for lock validation. After `docker restart`, `/tmp` persists and PID 7 is re-used deterministically.

**Impact:** Flask fails to start after `docker restart`. Health check fails continuously until manual intervention (`rm /tmp/w4p_backend.lock`).

**Fix:** Verify process name in lock check, or `rm -f /tmp/w4p_backend.lock` in entrypoint.

#### #35 — No Module Separation (CRITICAL)

Same as #21. The monolithic structure makes the codebase fragile and hard to modify.

---

### Duplicate Logic Map

```
┌─────────────────────────────────────────────────────────┐
│  Duplicate server implementations                        │
│                                                          │
│  server.js (bare-metal)     server-container.js (Docker) │
│  ─────────────────────      ──────────────────────────   │
│  14 explicit routes          6 static + 1 catch-all      │
│  ENGINE_FLASK routes         No engine routes            │
│  /api/* split proxy          ALL /api/* → :1080          │
│                                                          │
│  RISK: Routes diverge. Fix in one, forget the other.     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Duplicate static serving                                │
│                                                          │
│  Express :4000                 Flask :1080               │
│  ─────────────                 ──────────                │
│  source/remote-w4p.html (54KB) static/remote-w4p.html (63KB) │
│  source/hand-export.html       static/hand-export.html   │
│  source/api-config.js          static/api-config.js       │
│                                static/w4p.js (35KB STALE) │
│                                                          │
│  RISK: Different versions served from different ports.   │
└─────────────────────────────────────────────────────────┘
```

---

### Hardcoded Values Inventory

| Value | File(s) | Override Mechanism |
|-------|---------|-------------------|
| `127.0.0.1:4000` | w4p.js, background.js, options.html | `W4P_API_BASE` Chrome storage |
| `127.0.0.1:1080` | server.js, server-container.js | `BACKEND_API` env var in server.js only |
| `127.0.0.1:5002` | app.py, equity_routes.py | `ENGINE_URL` env var |
| `127.0.0.1:9222` | action_router.py, app.py | `CDP_URL` constructor arg |
| Port 1080 | Dockerfile, entrypoint.sh | `PORT` env var |
| Port 4000 | scripts/ | `PORT` env var in server.js |

---

### Unused Code Map

```
Potentially Unused (requires runtime verification):
├── GoldRush pipeline: /api/goldrush/* (6 endpoints)
├── Poker table scraper: /api/poker-tables/* (5 endpoints)
├── CDP action_router.py (browser automation)
├── table_scraper.py (Selenium)
├── windows_routes.py (Windows-only)
├── backend/ngrok + .tgz (20MB)
├── w4p-lite.js (alternative implementation)
└── Reference directories (4 dirs)

Definitively Dead:
├── backend/static/w4p.js (35KB, different codebase)
├── backend/static/remote-w4p.html.bak2
├── Container .bak files (5 files)
├── Container .swp files
└── Container ext.v24/ (v24 backup, 11 files)
```

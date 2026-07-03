# DEPLOYMENT AUDIT — E&R Poker Platform

**Date:** 2026-07-01
**Evidence tier:** DISK (Dockerfile, docker-compose.yml, entrypoint.sh) + RUNTIME (docker inspect, docker exec)

---

## Phase 8 — Complete Deployment Map

### Docker Layout

```
┌──────────────────────────────────────────────────┐
│  er-remote (container)                           │
│  Image built from: Dockerfile (Python 3.12-slim) │
│  Ports: 1080 (Flask), 4000 (Express)             │
│  Uptime: 10 hours                                │
│  Health: healthy                                 │
│                                                   │
│  /app/                                            │
│  ├── backend/          ← COPY backend/            │
│  │   ├── app.py        (Flask main, :1080)       │
│  │   ├── equity_routes.py                        │
│  │   ├── buffer.py                               │
│  │   ├── static/        (Flask-served assets)     │
│  │   │   ├── ext/       (Chrome extension)       │
│  │   │   ├── engine/    (React SPA assets)       │
│  │   │   └── *.html     (static pages)           │
│  │   └── venv/          (Python deps)            │
│  ├── scripts/           ← COPY scripts/          │
│  │   ├── server-container.js (Express, :4000)    │
│  │   └── node_modules/  (Node.js deps)           │
│  ├── source/            ← COPY source/           │
│  │   ├── remote-w4p.html (Express-served)        │
│  │   ├── w4p.js          (Express-served)        │
│  │   ├── api-config.js   (Express-served)        │
│  │   └── assets/         (React build)           │
│  ├── state/             ← Docker volume          │
│  │   └── state_snapshot.json                     │
│  └── logs/              ← Docker volume          │
│                                                   │
│  Entrypoint: /entrypoint.sh                       │
│    1. Start Flask :1080 (background)              │
│    2. Wait for Flask health                       │
│    3. Start Express :4000 (foreground, PID 1)     │
│                                                   │
│  Healthcheck (every 15s):                         │
│    curl http://127.0.0.1:1080/api/health          │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  er-engine (container)                           │
│  Image built from: ../ENGINEENGINE/Dockerfile     │
│  Port: 5002                                      │
│  Uptime: 17 hours                                │
│  Health: healthy                                 │
│                                                   │
│  /app/                                            │
│  ├── app.py            (Flask, :5002)            │
│  ├── result_parser.py                            │
│  ├── engine_cache.py                             │
│  ├── scripts/          (eval7 Monte Carlo)        │
│  │   ├── plo4-*.py                               │
│  │   ├── plo5-*.py                               │
│  │   ├── plo6-*.py                               │
│  │   └── plo7-*.py                               │
│  └── static/           (React SPA + extras)       │
│                                                   │
│  Healthcheck (every 15s):                         │
│    curl http://127.0.0.1:5002/api/health          │
└──────────────────────────────────────────────────┘
```

---

### File Serving Routes

#### Express :4000 (server-container.js)

| URL Path | File Served | Source Directory | Status |
|----------|-------------|-----------------|--------|
| `/` | `remote-w4p.html` | `/app/source/` | ACTIVE |
| `/remote` | `remote-w4p.html` | `/app/source/` | ACTIVE |
| `/hand-export` | `hand-export.html` | `/app/source/` | ACTIVE |
| `/api-config.js` | `api-config.js` | `/app/source/` | ACTIVE |
| `/api/*` | Proxy → Flask :1080 | N/A | ACTIVE |
| `/health` | JSON `{"ok":true}` | Inline | ACTIVE |

#### Flask :1080 (app.py)

| URL Path | File Served | Source Directory | Status |
|----------|-------------|-----------------|--------|
| `/` | `index.html` or `remote.html` | `backend/static/` | ACTIVE |
| `/remote` | `remote-w4p.html` | `backend/static/` | **DIVERGENT** (63KB vs 54KB) |
| `/engine` | `engine-index.html` | `backend/static/` | ACTIVE |
| `/engine/assets/<path>` | React SPA assets | `backend/static/engine/assets/` | ACTIVE |
| `/hand-export` | `hand-export.html` | `backend/static/` | ACTIVE |
| `/w4p.js` | `w4p.js` | `backend/static/` | **STALE** (35KB legacy) |
| `/api-config.js` | `api-config.js` | `backend/static/` | ACTIVE |
| `/n4p.js` | `n4p.js` | `backend/static/` | UNCERTAIN |
| `/remotebutton` | `remotebutton.html` | `backend/static/` | UNCERTAIN |
| `/shell` | `shell-live.html` | `backend/static/` | UNCERTAIN |
| `/login` | `login.html` | `backend/static/` | ACTIVE |
| `/change-password` | `change-password.html` | `backend/static/` | ACTIVE |
| `/player-manager` | `player-manager.html` | `backend/static/` | ACTIVE |

---

### Port Usage

| Port | Protocol | Service | Container | Exposed | Mapped |
|------|----------|---------|-----------|---------|--------|
| 1080 | TCP | Flask backend | er-remote | Dockerfile EXPOSE | Internal only (not published) |
| 4000 | TCP | Express proxy | er-remote | Dockerfile EXPOSE | `4000:4000` (published) |
| 5002 | TCP | Engine equity | er-engine | Not in Dockerfile | `5002:5002` (published) |

---

### Docker Compose

```yaml
services:
  engine (er-engine):
    build: ../ENGINEENGINE
    ports: "5002:5002"
    env: FLASK_ENV, PYTHONUNBUFFERED, SCANNER_API_KEY
    healthcheck: curl :5002/api/health (15s)
    restart: unless-stopped
    network: er-net

  remote (er-remote):
    build: .
    ports: "4000:4000"
    env: FLASK_ENV, PYTHONUNBUFFERED, PORT=1080, ENGINE_URL=http://engine:5002, TRACKER_API_KEY, N4P_SEAT_SECRET
    healthcheck: curl :1080/api/health (15s)
    volumes: remote-state:/app/state, remote-logs:/app/logs
    depends_on: engine (healthy)
    restart: unless-stopped
    network: er-net
```

---

### Dockerfile Copy Map

```
COPY backend/requirements.txt → /app/requirements.txt
RUN pip install
COPY scripts/package.json → /app/scripts/package.json
RUN npm install
COPY backend/  → /app/backend/
COPY scripts/  → /app/scripts/
COPY source/   → /app/source/
RUN mkdir state logs backend/data/...
COPY entrypoint.sh → /entrypoint.sh
```

**Key observation:** The Dockerfile copies `backend/` AND `source/` at BUILD TIME. There is no mechanism for runtime sync. Any changes committed to git after the image was built are NOT reflected in the running container.

---

### Runtime Paths

| Runtime Context | Path | Purpose |
|----------------|------|---------|
| Flask cwd | `/app/backend/` | app.py execution directory |
| Flask STATE_FILE | `/app/state/state_snapshot.json` | Derived from `../state/` relative to cwd |
| Flask static dir | `/app/backend/static/` | Default Flask static folder |
| Flask data dir | `/app/backend/data/` | Collector hands, validated hands |
| Express cwd | `/app/scripts/` | server-container.js execution directory |
| Express SOURCE_DIR | `/app/source/` | Static files served by Express |
| PID lock file | `/tmp/w4p_backend.lock` | Flask singleton lock (SURVIVES RESTART) |
| Docker volume remote-state | `/app/state/` | Persistent table state |
| Docker volume remote-logs | `/app/logs/` | Persistent logs |

---

### Deployment Verification Checklist

| Item | Expected | Actual | Status |
|------|----------|--------|--------|
| Container er-remote running | Yes | Yes (10h) | PASS |
| Container er-engine running | Yes | Yes (17h) | PASS |
| Flask :1080 health | `{"ok":true}` | Healthy per docker | PASS |
| Express :4000 health | `{"ok":true}` | Healthy per ss | PASS |
| Engine :5002 health | Healthy | Healthy per docker | PASS |
| Container ext/w4p.js matches source | `0254ba5...` | `b6685bd...` | **FAIL** |
| Container source/w4p.js matches repo | `0254ba5...` | `0254ba5...` | PASS |
| State volume mounted | Yes | Yes | PASS |
| PID lock file cleaned on restart | Should be | NOT cleaned | **FAIL** |
| Flask :1080 not exposed externally | Internal | Only via Express | PASS |

---

### Runtime Architecture vs Repository Match

| Component | Repo Location | Container Location | Match? |
|-----------|--------------|-------------------|--------|
| Flask app.py | `backend/app.py` | `/app/backend/app.py` | ✓ (MD5 matches) |
| Express server | `scripts/server-container.js` | `/app/scripts/server-container.js` | ✓ (MD5 matches) |
| Remote UI | `source/remote-w4p.html` | `/app/source/remote-w4p.html` | ✓ |
| Extension w4p.js | `backend/static/ext/w4p.js` | `/app/backend/static/ext/w4p.js` | ✗ (STALE) |
| Extension bridge.js | `backend/static/ext/bridge.js` | `/app/backend/static/ext/bridge.js` | ✓ |
| Extension background.js | `backend/static/ext/background.js` | `/app/backend/static/ext/background.js` | ✓ |
| api-config.js | `source/api-config.js` | `/app/source/api-config.js` | ✓ |
| Flask static/w4p.js | `backend/static/w4p.js` | `/app/backend/static/w4p.js` | ✓ (both 35KB legacy) |
| Flask static/remote-w4p.html | `backend/static/remote-w4p.html` | `/app/backend/static/remote-w4p.html` | ✓ (both 63KB) |

---

### Critical Deployment Issues

1. **Container ext/w4p.js STALE** — Running v24 backup, not current source. The correct version is at `/app/backend/static/ext/w4p.js.before`.

2. **PID lock survives restart** — `docker restart er-remote` causes Flask to fail because `/tmp/w4p_backend.lock` persists and PID 7 is re-used. Fix: add `rm -f /tmp/w4p_backend.lock` to entrypoint.

3. **Two divergent remote-w4p.html versions served** — Express serves 54KB version, Flask serves 63KB version.

4. **Flask serves STALE w4p.js** — The `/w4p.js` route serves the 35KB legacy file, not the 69KB current version.

5. **No build-time sync mechanism** — Docker image is built once and never auto-rebuilds. Git commits after build are not reflected.

6. **ext.v24/ backup directory in container** — 11 files of old extension code shipped in production image.

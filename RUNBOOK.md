# PLO Equity Engine — Local RUNBOOK

## Overview

Fully independent local clone of the PLO Equity Engine (ENGINE app) at http://localhost:4002.
No production/EC2 dependencies for normal operation.

## Quick Start

```bash
cd /home/wa/ENGINEENGINE
./scripts/start-local.sh
```

## Architecture

```
Browser (http://localhost:4002)
    |
    v
Express Proxy (:4002)  —  serves static assets, proxies /api/* to Flask
    |
    v
Flask Backend (:5002)  —  auth, engine calculations, SSE streaming, results
```

## Services

| Service | Port | Technology | Start Command |
|---------|------|-----------|--------------|
| Frontend/Proxy | 4002 | Express (Node.js 18) | `node scripts/server.js` |
| Backend | 5002 | Flask (Python 3.12) | `python source/app.py` |

## Local-Only Changes Made

1. **HTML titles** — Changed from EC2 domain to `localhost:4002` in `source/static/index.html` and `source/static/engine-index.html`
2. **JS asset bundles** — Replaced EC2 domain display text with `localhost:4002` in 10 minified JS bundles under `source/static/assets/`
3. **Express proxy** — Created `scripts/server.js` to proxy /api/* to Flask backend on :5002, serve static files
4. **Startup scripts** — `scripts/start-local.sh` launches both Flask and Express
5. **W4P files** — `source/static/w4p.js` retains EC2 references (W4P remote controls, out of scope)

## Dependencies

### Python (venv at `source/venv/`)
- Flask 3.0.0, Flask-SocketIO 5.3.5, Flask-CORS 4.0.0
- eventlet 0.35.2, eval7 0.1.6, colorama 0.4.6

### Node.js (modules at `scripts/node_modules/`)
- express ^5.2.1
- http-proxy-middleware ^2.0.7

## API Endpoints (all local, all served via :4002)

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/health | GET | Health check |
| /api/login | POST | Authentication (admin / PokerPass12345) |
| /api/run | POST | Start engine calculation |
| /api/results/:id | GET | Get calculation results |
| /api/stream/:id | GET | SSE stream for live progress |
| /api/batch/* | POST | Batch/analytics endpoints |

## Login Credentials

- **Username:** admin
- **Password:** PokerPass12345

## Acceptance Test Results

### Route Tests
- http://localhost:4002/ — HTTP 200
- http://localhost:4002/engine/ — HTTP 200
- http://localhost:4002/api/health — Returns JSON `{"ok": true}`

### Backend Tests
- POST /api/login — Success, returns auth token
- POST /api/run — Success, returns job_id
- GET /api/results/:id — Returns calculation results

### Independence Verification
- No runtime API calls to EC2
- No SSE/EventSource URLs pointing to EC2
- No card image URLs pointing to EC2
- All static assets served locally
- Engine calculations run locally

## Project Structure

```
/home/wa/ENGINEENGINE/
  source/              Flask backend + static frontend assets
    app.py             Main Flask application
    ai_guard.py        AI/Claude integration guard
    cache_layer.py     Caching layer
    dirk_tracker.py    Dirk activity tracker
    engine_cache.py    Engine cache
    result_parser.py   Result parsing and formatting
    requirements.txt   Python dependencies
    scripts/           Engine calculation scripts (plo4-*, plo5-*, etc.)
    static/            Frontend HTML, JS, CSS assets
      assets/          Minified React bundles
      engine-index.html  Main engine entry point (at /engine/)
      index.html       Root entry point
      engine_flow_controls.js  Engine flow controls
      w4p.js           W4P remote controls (out of scope)
    venv/              Python virtual environment
  scripts/             Express proxy + start/stop scripts
    server.js          Express proxy server
    start-local.sh     Combined startup script
    stop-local.sh      Combined stop script
    package.json       Node.js dependencies
  nginx-reference/     Reference: EC2 nginx configs
  service-reference/   Reference: EC2 systemd service files
  logs/                Application logs
```

## Production References (Unchanged)

The following directories contain reference copies of EC2 configuration files
for documentation purposes only. They are not used by the local app.

- `nginx-reference/` — Production nginx configs
- `service-reference/` — Production systemd service files
- `env-reference/` — Production environment files

EC2 server was accessed in read-only mode. No EC2 files were modified.

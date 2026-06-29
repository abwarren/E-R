# REMOTEREMOTE — Local Clone of haaats.xyz/remote

## Overview

This repository contains a locally-cloned copy of the remote control UI served at `https://haaats.xyz/remote` from the EC2 instance `ec2-15-240-11-107.af-south-1.compute.amazonaws.com`.

The application is a **fully self-contained HTML/JS/CSS** frontend (one file: `remote-w4p.html`) with inline CSS and JavaScript — no build step required. The local server uses Express with an API proxy to the production backend so all features work.

---

## Architecture

```
Browser ──► http://localhost:4000
                 │
                 ├── / → remote-w4p.html
                 ├── /remote → remote-w4p.html
                 ├── /remote/ → remote-w4p.html
                 ├── /assets/* → ./source/assets/*
                 ├── /w4p-lite.js → ./source/w4p-lite.js
                 ├── /engine.html → ./source/engine.html
                 ├── /index.html → ./source/index.html
                 └── /api/* ──► https://haaats.xyz/api/*
                                  │
                                  └── nginx ──► flask:5003
```

### Key Design Decisions

| Aspect | Decision | Rationale |
|---|---|---|
| Local server | Node.js + Express | Needed routing + proxy — Python http.server can't do this |
| API calls | Proxied to production | The Flask backend runs on EC2 port 5003 (read-only); frontend functions fully via proxy |
| Root route `/` | Serves remote UI | Production redirects `/` → `/engine`, but for local use we map root to the remote page for convenience |
| `/remote` route | Serves same page | Matches nginx `location ~ ^/remote/?$` rule |
| Source files | Byte-identical copies | `diff` confirmed zero modifications to EC2 files |

---

## Source Paths

| Component | EC2 Path | Local Path |
|---|---|---|
| Remote UI | `/opt/plo-engine/static/remote-w4p.html` | `./source/remote-w4p.html` |
| Main Engine UI | `/opt/plo-engine/static/index.html` | `./source/index.html` |
| Engine HTML | `/opt/plo-engine/static/engine.html` | `./source/engine.html` |
| W4P Lite Script | `/opt/plo-engine/static/w4p-lite.js` | `./source/w4p-lite.js` |
| JS Bundle | `/opt/plo-engine/static/assets/index-Cq0zqSC6.js` | `./source/assets/index-Cq0zqSC6.js` |
| CSS Bundle | `/opt/plo-engine/static/assets/index-DgTzSuxS.css` | `./source/assets/index-DgTzSuxS.css` |
| W4P Extension ZIP | `/opt/plo-engine/static/w4p-extension.zip` | `./source/w4p-extension.zip` |
| Backend Flask App | `/opt/plo-equity/backend/app.py` | Not cloned (read-only EC2) |
| Backend Environment | `/opt/plo-equity/.env` | `./env-reference/plo-equity.env` |

---

## Quick Start

### Prerequisites
- Node.js v18+ (v18.19.1 available)
- npm

### Start the Server
```bash
cd /home/wa/REMOTEREMOTE
./scripts/start-local.sh
```

Or manually:
```bash
cd /home/wa/REMOTEREMOTE/scripts
node server.js
```

### Open in Browser
- **http://localhost:4000** — Main page (remote UI)
- **http://localhost:4000/remote** — Also serves the remote UI
- **http://localhost:4000/remote-w4p.html** — Direct file access

### Stop the Server
Press `Ctrl+C` in the terminal where the server is running, or:
```bash
pkill -f 'node server.js'
```

---

## Nginx Config Reference

The `/remote` location block on EC2:
```nginx
location ~ ^/remote/?$ {
    root /opt/plo-engine/static;
    try_files /remote-w4p.html =404;
    add_header Cache-Control "no-cache" always;
}
```

The API proxy routes for the remote control:
```nginx
location /api/table/ {
    proxy_pass http://127.0.0.1:5003/api/table/;
}
location /api/commands/ {
    proxy_pass http://127.0.0.1:5003/api/commands/;
}
location /api/ {
    limit_req zone=api_limit burst=20 nodelay;
    proxy_pass http://127.0.0.1:5003/api/;
}
```

---

## API Behavior

The remote UI makes these API calls (relative via `var API = '/api'`):

| Endpoint | Method | Purpose | Local Behavior |
|---|---|---|---|
| `/api/table/latest` | GET | Fetch current table state | Proxied to production ✅ |
| `/api/commands/queue` | POST | Send poker actions | Proxied to production ✅ |
| `/api/health` | GET | Health check | Proxied to production ✅ |

**All `/api/*` calls** are proxied to `https://haaats.xyz/api/*` via the Express server. This means:
- The remote UI polls the real production backend
- Action commands go to the real production backend
- The UI behaves identically to the production version
- No local backend is required

The proxy forwards these headers (matching nginx config):
- `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`

---

## Backend Reference (Not Cloned)

The Flask backend (`/opt/plo-equity/backend/app.py`) was **not cloned** from EC2 per the read-only requirement. See `./backend-reference/README.md` for details on how to set it up locally if needed in the future.

### Service File (for reference)
`./service-reference/plo-w4p.service`:
```ini
[Unit]
Description=PLO W4P Remote Control Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/plo-equity/backend
EnvironmentFile=/opt/plo-equity/.env
ExecStart=/opt/plo-equity/venv/bin/gunicorn -w 1 --timeout 60 --bind 0.0.0.0:5003 app:app
Restart=on-failure
RestartSec=5
```

---

## Directory Structure

```
/home/wa/REMOTEREMOTE/
├── source/                     # Cloned frontend files (from /opt/plo-engine/static/)
│   ├── remote-w4p.html         # ★ Remote UI entry point (53,686 bytes)
│   ├── index.html              # Engine UI
│   ├── engine.html             # Engine page
│   ├── w4p-lite.js             # Lite script
│   ├── w4p-extension.zip       # Extension
│   └── assets/
│       ├── index-Cq0zqSC6.js   # JS bundle
│       ├── index-DgTzSuxS.css  # CSS bundle
│       └── w4p-extension.zip   # Extension (duplicate)
├── scripts/
│   ├── server.js               # ★ Express server with routing + API proxy
│   ├── start-local.sh          # ★ Startup script
│   ├── package.json
│   └── node_modules/
├── nginx-reference/
│   ├── full-nginx-config.txt   # Full nginx -T output
│   ├── sites-enabled/
│   └── sites-available/
├── service-reference/
│   └── plo-w4p.service
├── env-reference/
│   └── plo-equity.env
├── backend-reference/
│   └── README.md               # Explains why backend wasn't cloned
├── logs/
└── RUNBOOK.md                  # This file
```

---

## Local Changes Made

| Change | File | Reason |
|---|---|---|
| Created Express server | `./scripts/server.js` | Needed for routing (/, /remote) and API proxy |
| Created startup script | `./scripts/start-local.sh` | Convenience script |
| Installed dependencies | `./scripts/package.json`, `./scripts/node_modules/` | Express + http-proxy-middleware |
| Created backend-reference | `./backend-reference/README.md` | Document why backend isn't cloned |
| Updated RUNBOOK.md | `./RUNBOOK.md` | Full documentation of new setup |

**No changes were made to the cloned source files.** All files in `./source/` are byte-identical to the EC2 originals.

---

## Acceptance Tests

### Route Tests
```bash
curl -I http://localhost:4000          # → HTTP 200
curl -I http://localhost:4000/remote   # → HTTP 200
curl -I http://localhost:4000/remote/  # → HTTP 200
```

### API Proxy Tests
```bash
curl http://localhost:4000/api/health        # → 200, {"ok":true,...}
curl http://localhost:4000/api/table/latest  # → 200, table state JSON
```

### Visual Tests
Open http://localhost:4000 and compare to https://haaats.xyz/remote:
- ✅ Same layout (3x3 seat grid, header, controls)
- ✅ Same styling (dark theme, colors)
- ✅ Same controls (Fold, Check, Call, Bet/Raise, Auto C/C, KH, EMG)
- ✅ Same JavaScript behavior (polling, command queue)
- ✅ API calls work (proxied to production)

---

## EC2 Integrity Confirmation

- ✅ EC2 used in read-only mode only
- ✅ No files edited on EC2
- ✅ No nginx reload/restart
- ✅ No services restarted
- ✅ No packages installed
- ✅ No permissions changed
- ✅ Local clone verified byte-identical via `diff`

---

## Known Issues

1. **API calls use production data** — The `/api/*` proxy forwards requests to `haaats.xyz`. If the production API goes down or changes, the local UI will be affected.
2. **No local backend** — The Flask backend was not cloned. It's proxied to production.
3. **EC2 ssh key included** — `LINUXSSHKEY.pem` is in this directory. Keep it secure.
4. **CONTEXT.md** on EC2 (`/home/ubuntu/CONTEXT.md`) documents known bugs: validation gate issue, seat collision bug, config mismatch between nginx-served remote-w4p.html and backend copy.

---

## Multi-Tool Local Development (June 2026)

The PLO app source has been reorganized into independently-operable tools:

### Tool Ports
| Tool | Server | Port | URL |
|------|--------|------|-----|
| Backend API | Flask (REMOTEREMOTE/backend/app.py) | **1080** | http://127.0.0.1:1080/api |
| Remote UI | Express (REMOTEREMOTE/scripts/server.js) | **4000** | http://127.0.0.1:4000/remote |
| Engine UI | Express (ENGINEENGINE/scripts/server-standalone.js) | **4001** | http://127.0.0.1:4001/engine |
| Hand Export | Any server (HTML/JS) | any | /hand-export on any tool |
| Extension | Chrome extension | N/A | w4p-extension.zip or w4p-extension-dev/ |

### Independence Rule
Each tool starts and runs independently. The **only** shared dependency is the Backend API (port 1080):
- Remote UI does not need Engine UI
- Engine UI does not need Remote UI
- Extension does not need Remote UI or Engine UI
- Hand Export works on any server that proxies to the backend

### Quick Start (All Tools)
```bash
# Terminal 1: Backend API
cd /home/wa/REMOTEREMOTE/backend
export TRACKER_API_KEY=03622c896cfbeacdfc537e9434f9ddc5
source venv/bin/activate
python app.py

# Terminal 2: Remote UI
cd /home/wa/REMOTEREMOTE/scripts
node server.js

# Terminal 3: Engine UI
cd /home/wa/ENGINEENGINE/scripts
node server-standalone.js
```

### Health Checks
```bash
# Backend API
curl -s http://127.0.0.1:1080/api/health

# Remote UI (verify serving)
curl -I http://127.0.0.1:4000/remote

# Engine UI
curl -s http://127.0.0.1:4001/health

# API proxy through either tool
curl -s http://127.0.0.1:4000/api/health
curl -s http://127.0.0.1:4001/api/health

# Snapshot (test end-to-end)
curl -s -X POST http://127.0.0.1:1080/api/snapshot \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 03622c896cfbeacdfc537e9434f9ddc5" \
  -d '{"table_id":"test1","dealer_seat":1,"deal_id":"d1","street":"FLOP","pot_zar":1000,"board":{"flop":["Kc","Qc","7d"]},"seats":[{"name":"Hero","seat_index":1,"stack_zar":5000,"hole_cards":["Ah","Kh","Qh","Jh"],"is_hero":true,"status":"active"}],"bot_id":"test-bot"}'

# Verify table state
curl -s http://127.0.0.1:1080/api/table/latest
```

### Dev/Prod API Configuration

| Environment | API_BASE | Where to change |
|-------------|----------|-----------------|
| Local dev | `http://127.0.0.1:1080/api` | Extension: click icon → options |
| Production | `https://haaats.xyz/api` | Extension: click icon → options |
| Hand Export | `var API_BASE = '/api'` | Top of hand-export.html |
| w4p.js | `window.__W4P_API_BASE` | Set before injection |

### New Files Created

| File | Purpose |
|------|---------|
| `CONTEXT.md` | Full developer context document |
| `backend/app.py` (updated) | Added `/hand-export` route |
| `scripts/server.js` (updated) | Added `/hand-export` route |
| `source/hand-export.html` | Standalone hand export renderer |
| `backend/static/hand-export.html` | Backend-served copy |
| `source/w4p-extension-dev/` | Unpacked extension for dev loading |
| `backend/static/w4p-extension.zip` | Updated extension zip |
| `../ENGINEENGINE/scripts/server-standalone.js` | Standalone Engine UI server on 4001 |
| `../ENGINEENGINE/scripts/start-engine-standalone.sh` | Engine UI startup script |

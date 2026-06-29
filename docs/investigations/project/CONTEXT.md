# PLO App Source — Local Development Context

## Overview

Six independent tools sharing one dependency: the Backend API (port 1080).

| Tool | Port | URL | Server |
|------|------|-----|--------|
| Backend API | 1080 | http://127.0.0.1:1080/api | Flask (REMOTEREMOTE/backend/app.py) |
| Remote UI | 4000 | http://127.0.0.1:4000/remote | Express (REMOTEREMOTE/scripts/server.js) |
| Engine UI | 4001 | http://127.0.0.1:4001/engine | Express (ENGINEENGINE/scripts/server-standalone.js) |
| Hand Export | any | /hand-export on any server | HTML/JS standalone page |
| Extension | N/A | Chrome extension | w4p-extension.zip |
| Production | 443 | https://haaats.xyz/* | Nginx → Flask on EC2 |

## Architecture Rule

**Every tool must start, run, and fail independently.**
- No tool depends on the Engine UI being up.
- No tool depends on the Remote UI being up.
- The Backend API is the ONLY shared dependency.
- Port 4000 (Remote UI Express) is not assumed to be alive.

---

## Quick Start

```bash
# 1. Start Backend API (shared dependency)
cd /home/wa/REMOTEREMOTE/backend
export TRACKER_API_KEY=03622c896cfbeacdfc537e9434f9ddc5
source venv/bin/activate
python app.py

# 2. Start Remote UI (separate terminal)
cd /home/wa/REMOTEREMOTE/scripts
node server.js

# 3. Start Engine UI (separate terminal)
cd /home/wa/ENGINEENGINE/scripts
node server-standalone.js

# 4. Load Extension in Chrome
# - Go to chrome://extensions
# - Enable "Developer mode"
# - "Load unpacked" → /home/wa/REMOTEREMOTE/source/w4p-extension-dev/
# - Click extension icon to configure API_BASE
```

---

## Tool Details

### 1. Backend API (port 1080)

**Source:** `/home/wa/REMOTEREMOTE/backend/app.py`
**Start:** `cd /home/wa/REMOTEREMOTE/backend && export TRACKER_API_KEY=03622c896cfbeacdfc537e9434f9ddc5 && source venv/bin/activate && python app.py`
**Health:** `curl http://127.0.0.1:1080/api/health`
**Env:** `.env` file (TRACKER_API_KEY, N4P_SEAT_SECRET, FLASK_ENV)

Endpoints:
- `GET /api/health` — service health
- `GET /api/table/latest` — latest table state + seats + board
- `POST /api/snapshot` — receive snapshot from extension
- `GET /api/commands/pending?token=...` — command polling
- `POST /api/commands/queue` — queue action command
- `POST /api/commands/ack` — acknowledge command
- `GET /api/tables` — list all active tables
- `POST /api/collector/save` — save hand to collector
- `GET /api/collector/latest` — latest collector hands
- `GET /api/hands/recent` — recent hand history
- `GET /api/remote/status` — detailed remote status
- `GET /api/engine/status` — engine connectivity
- `GET /api/status` — detailed status + metrics

Static pages (served by Flask):
- `GET /remote` → remote-w4p.html (Remote UI)
- `GET /hand-export` → hand-export.html (Hand Export Renderer)
- `GET /` → remote.html or index.html (by host)

### 2. Remote UI (port 4000)

**Source:** `/home/wa/REMOTEREMOTE/scripts/server.js`
**Start:** `cd /home/wa/REMOTEREMOTE/scripts && node server.js`
**URL:** http://127.0.0.1:4000/remote or http://127.0.0.1:4000/remote-w4p.html
**Health:** `curl http://127.0.0.1:4000/api/health` (through proxy)

Features:
- W4P Remote Table Control — per-seat button mirror
- Proxies `/api/*` → Backend API (127.0.0.1:1080)
- Serves `remote-w4p.html` from `./source/`
- Emergency fallback panel (EMG button)
- Force test mode for UI validation
- Pre-action toggles (C/F, C/C, CO, KH)
- Global Auto C/C Preflop

### 3. Engine UI (port 4001)

**Source:** `/home/wa/ENGINEENGINE/scripts/server-standalone.js`
**Start:** `cd /home/wa/ENGINEENGINE/scripts && node server-standalone.js`
**URL:** http://127.0.0.1:4001/engine
**Health:** `curl http://127.0.0.1:4001/health`
**Calculator:** http://127.0.0.1:4001/engine/calculator

Features:
- React app for equity engine and table display
- Proxies `/api/*` → Backend API (127.0.0.1:1080)
- Load latest table and render hands
- Manual equity calculations (no auto-run)
- Does NOT depend on Remote UI or Engine Flask backend

### 4. Hand Export Renderer

**Source:** `/home/wa/REMOTEREMOTE/source/hand-export.html`
**Accessible from:**
- http://127.0.0.1:1080/hand-export (via backend)
- http://127.0.0.1:4000/hand-export (via Remote UI)
- Direct file open in browser

Features:
- Fetches `/api/table/latest`
- Extracts hero hole cards and board
- Renders one hand per line, no labels, no spaces
- Copy-to-clipboard button

Output format:
```
AhKhQhJhKcQc7d   (4 hole cards + 3 flop)
AdKdQdJdKcQc7d   (4 hole cards + 3 flop)
```

### 5. Chrome Extension / W4P Bridge

**Files:**
- `/home/wa/REMOTEREMOTE/source/w4p-extension.zip` — packaged extension
- `/home/wa/REMOTEREMOTE/source/w4p-extension-dev/` — unpacked for dev loading

**Config:**
- Default API_BASE: `http://127.0.0.1:1080/api` (local dev)
- Production API_BASE: `https://haaats.xyz/api`
- Click extension icon → options popup → select "Local Dev" or "Production"
- Or set via `window.__W4P_API_BASE` before injection

**Loading:**
1. Open `chrome://extensions`
2. Enable Developer mode
3. "Load unpacked" → select `/home/wa/REMOTEREMOTE/source/w4p-extension-dev/`
4. Click extension icon → configure API_BASE

**Console logging:** Extension logs `[W4P-BG] API_BASE=...` on startup.

### 6. Snapshot Collector

Test independently with curl:
```bash
# Post a snapshot
curl -X POST http://127.0.0.1:1080/api/snapshot \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 03622c896cfbeacdfc537e9434f9ddc5" \
  -d '{"table_id":"test1","dealer_seat":1,"deal_id":"d1","street":"FLOP","pot_zar":1000,"board":{"flop":["Kc","Qc","7d"]},"seats":[{"name":"Hero","seat_index":1,"stack_zar":5000,"hole_cards":["Ah","Kh","Qh","Jh"],"is_hero":true,"status":"active"}],"bot_id":"test-bot"}'

# Verify table state
curl http://127.0.0.1:1080/api/table/latest
```

---

## Dev/Prod Config

### API_BASE values
| Environment | API_BASE |
|-------------|----------|
| Local dev | `http://127.0.0.1:1080/api` |
| Production | `https://haaats.xyz/api` |

### Where to change
| Component | How to switch |
|-----------|---------------|
| Backend | Set `TRACKER_API_KEY` env var (from `.env`) |
| Remote UI (remote-w4p.html) | `var API = '/api'` — auto-routes via Express proxy |
| Hand Export (hand-export.html) | `var API_BASE = '/api'` (top of script) |
| Extension (background.js) | Click extension icon → options popup |
| Extension (w4p.js) | Set `window.__W4P_API_BASE` before injection |
| Production (haaats.xyz) | Nginx routes handled by server config |

---

## Health Check Quick Reference

```bash
# Backend API
curl -s http://127.0.0.1:1080/api/health

# Remote UI (verify it's serving)
curl -I http://127.0.0.1:4000/remote

# Remote UI API proxy
curl -s http://127.0.0.1:4000/api/health

# Engine UI
curl -s http://127.0.0.1:4001/health

# Engine UI API proxy
curl -s http://127.0.0.1:4001/api/health

# Hand Export (any server)
curl -I http://127.0.0.1:1080/hand-export

# Production
curl -s https://haaats.xyz/api/health
```

---

## Important Rules

1. **No hardcoded localhost:4000 assumptions** — always check which port is running.
2. **No stale domain references** — `potlimitomaha.xyz` and `nuts4poker.com` are obsolete.
3. **Before debugging UI**, verify the backend is up first:
   ```bash
   ss -ltnp | grep ':1080'
   curl -I http://127.0.0.1:1080/api/health
   ```
4. **Backend is the shared source of truth** — all table state lives in the Flask app.
5. **Each tool has its own startup path** — they do not start each other.

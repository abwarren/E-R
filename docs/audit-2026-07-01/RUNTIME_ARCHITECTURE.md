# RUNTIME ARCHITECTURE — E&R Poker Platform

**Date:** 2026-07-01
**Evidence tier:** DISK (repo files) + RUNTIME (Docker container inspection)

---

## Phase 2 — Runtime Architecture

### Component Inventory

#### 1. Chrome Extension (PokerScope W4P)
- **Location:** `backend/static/ext/`
- **Runtime:** Browser content script (MAIN + ISOLATED worlds)
- **Entry point:** `w4p.js` (69KB), `bridge.js` (938B), `background.js` (6.5KB)
- **Manifest:** `manifest.json` — `"world": "ISOLATED"` + `"host_permissions": ["http://127.0.0.1:4000/*"]`
- **Trigger sites:** `poker-web.goldrush.co.za/*`, `games.goldrush.co.za/*`, `www.goldrush.co.za/live-poker*`
- **Responsibility:** DOM scraping → snapshot construction → POST to Express :4000
- **Data flow:** `w4p.js` → `bridgeFetch()` → `postMessage` → `bridge.js` → `chrome.runtime.sendMessage` → `background.js` → `fetch()` to `http://127.0.0.1:4000/api/snapshot`

#### 2. Express Frontend Proxy (server-container.js)
- **Location:** `scripts/server-container.js` (4,955 bytes)
- **Runtime:** Node.js, port 4000
- **Entry point:** `node server-container.js`
- **Responsibilities:**
  - Serves static files from `/app/source/`:
    - `/` → `remote-w4p.html`
    - `/remote` → `remote-w4p.html`
    - `/hand-export` → `hand-export.html`
    - `/api-config.js` → `api-config.js`
  - Proxies ALL `/api/*` → Flask backend `http://127.0.0.1:1080`
  - CORS headers for cross-origin extension access
  - Private Network Access (PNA) bridge headers
- **Consumers:** Remote UI browser, Chrome extension, direct API clients

#### 3. Flask Backend (app.py)
- **Location:** `backend/app.py` (129,050 bytes, ~3,200 lines)
- **Runtime:** Python 3.12, port 1080
- **Entry point:** `python app.py` (server-container.js starts it)
- **Responsibilities:**
  - Snapshot ingestion: `POST /api/snapshot`
  - Table state management: `_tables` dict, `_seat_bots`, `_bot_actions`, `_bot_buttons`
  - Command queue: `POST /api/commands/queue`, `GET /api/commands/pending`, `POST /api/commands/ack`
  - Table API: `GET /api/table/<id>`, `GET /api/table/latest`, `GET /api/tables`
  - Health/status: `GET /api/health`, `GET /api/status`, `GET /api/version`
  - Equity delegation: via `equity_routes.py` → engine `:5002`
  - Collector hand pipeline: `POST /collector/save`, `GET /collector/meta`
  - Authentication: login, verify, logout, player CRUD
  - State persistence: `state/state_snapshot.json` (every 10s)
  - Static file serving: `backend/static/` directory
- **Modules loaded:**
  - `buffer.py` — snapshot dedup, board detection, hand epoch management
  - `equity_routes.py` — equity calculation delegation
  - `action_router.py` — CDP-based browser action execution
  - `windows_routes.py` — Windows CDP management
  - `auth_models.py` — user authentication (SQLite)
  - `bot_deployment.py` — bot deployment lifecycle
  - `db_logger.py` — PostgreSQL hand logging
  - `audit_logs.py` — audit trail
  - `table_scraper.py` — poker table scraping

#### 4. Remote UI (remote-w4p.html)
- **Location:** `source/remote-w4p.html` → served by Express
- **Runtime:** Browser (single-file HTML/JS/CSS, no build step)
- **Responsibilities:**
  - Displays merged table state (all seats, all bots)
  - Renders action buttons (operator-console architecture)
  - Sends commands via `POST /api/commands/queue`
  - Polls `GET /api/table/latest` for updates
  - Operator console — not a player mirror

#### 5. Engine (ENGINEENGINE)
- **Location:** Separate repo (`github.com:abwarren/E-R.git`, `engine` branch)
- **Image:** `er-engine` container
- **Runtime:** Python 3.12 Flask, port 5002
- **Responsibilities:**
  - PLO equity calculation via eval7 Monte Carlo scripts
  - Result parsing (`result_parser.py`)
  - React SPA frontend
  - Action decision engine (`/api/decide`)
  - RNG generation (`/api/rng/generate`)
- **Scripts:** `plo4-*.py` through `plo7-*.py` for different max-players × variant combinations

#### 6. Snapshot Pipeline
```
Browser DOM
  → w4p.js buildSnapshot()
    → bridgeFetch() postMessage relay
      → bridge.js → background.js fetch()
        → Express :4000 proxy
          → Flask :1080 POST /api/snapshot
            → buffer.py (dedup, board detection)
              → _tables merge (app.py lines 1200-1310)
                → state_snapshot.json (10s persist)
                  → GET /api/table/latest (API consumers)
```

#### 7. Command Pipeline
```
Remote UI button click
  → POST /api/commands/queue {seat_no, action, amount}
    → Flask :1080 stores in _command_queue
      → Extension polls GET /api/commands/pending
        → Executes via CDP action_router.py
          → POST /api/commands/ack
```

#### 8. API Architecture
- **Flask routes:** ~50+ endpoints (see API_INVENTORY.md)
- **Express routes:** 6 static routes + 1 catch-all `/api/*` proxy
- **Proxy architecture:**
  - `server-container.js` (container): ALL `/api/*` → Flask :1080
  - `server.js` (bare-metal laptop): Selective routing — some → Engine :5002, remainder → Flask :1080

---

## Complete Data-Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       GoldRush Poker Client                      │
│  https://poker-web.goldrush.co.za (Angular, iframe-based)       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Chrome Extension (PokerScope W4P)                        │   │
│  │  backend/static/ext/                                       │   │
│  │                                                            │   │
│  │  ISOLATED world: bridge.js  ──►  postMessage listener     │   │
│  │  MAIN world:     w4p.js     ──►  DOM scraper + snapshot   │   │
│  │  Service Worker: background.js ─►  fetch() relay          │   │
│  │                                                            │   │
│  │  Flow: w4p.js → postMessage → bridge.js → SW → fetch()   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │ fetch('http://127.0.0.1:4000/api/…')│
└───────────────────────────┼─────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│  Express Frontend Proxy  (:4000)                                  │
│  /app/scripts/server-container.js                                 │
│                                                                   │
│  Static:   / → remote-w4p.html  (from /app/source/)              │
│            /remote → remote-w4p.html                              │
│            /hand-export → hand-export.html                        │
│            /api-config.js → api-config.js                         │
│                                                                   │
│  Proxy:    /api/* → http://127.0.0.1:1080/api/*                   │
│  Headers:  CORS + PNA (Access-Control-Allow-Private-Network)     │
└───────────────────────┬───────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────┐
│  Flask Backend  (:1080)                                           │
│  /app/backend/app.py  (129KB, ~3200 lines)                        │
│                                                                   │
│  Routes (selected):                                               │
│    POST /api/snapshot         ─► buffer.py → _tables merge        │
│    GET  /api/table/latest     ─► _build_seats_list()              │
│    GET  /api/table/<id>       ─► table state lookup               │
│    POST /api/commands/queue   ─► _command_queue                   │
│    GET  /api/commands/pending ─► Dequeue for extension             │
│    GET  /api/health           ─► Health check + seq info          │
│                                                                   │
│  State:                                                           │
│    _tables       = {}  # table_id → canonical state               │
│    _command_queue = {} # seat_token → command                     │
│    _seat_bots     = {} # (table_id, seat_no) → bot_id             │
│    _bot_actions   = {} # bot_id → [actions]                       │
│    _bot_buttons   = {} # bot_id → full button detection           │
│                                                                   │
│  Persistence: state/state_snapshot.json (write every 10s)        │
│                                                                   │
│  Static serving (from backend/static/):                           │
│    /w4p.js       → static/w4p.js        (35KB STALE COPY!)       │
│    /api-config.js → static/api-config.js                         │
│    /remote        → static/remote-w4p.html (63KB DIFFERENT!)     │
│    /engine        → static/engine-index.html                      │
└───────────────────────┬───────────────────────────────────────────┘
                        │
                        ▼  (equity routes only)
┌───────────────────────────────────────────────────────────────────┐
│  Engine Backend  (:5002)                                          │
│  Separate container: er-engine                                    │
│  Flask + eval7 Monte Carlo scripts                                │
│                                                                   │
│  Routes:                                                          │
│    POST /api/run              ─► Run equity calculation           │
│    GET  /api/results/<id>     ─► Get calculation results          │
│    GET  /api/stream/equity    ─► SSE equity stream                │
│    POST /api/decide           ─► AI action decision               │
│    POST /api/rng/generate     ─► Random number generation         │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  Remote UI  (Browser)                                              │
│  http://127.0.0.1:4000/remote                                     │
│                                                                   │
│  Polls:    GET  /api/table/latest                                 │
│  Commands: POST /api/commands/queue                               │
│  Display:  Seats + actions (operator console architecture)        │
│  Equity:   POST /api/run → SSE /api/stream/equity                 │
└───────────────────────────────────────────────────────────────────┘
```

---

## Port Map

| Port | Service | Container | Source File | Status |
|------|---------|-----------|-------------|--------|
| 1080 | Flask backend | er-remote | backend/app.py | HEALTHY |
| 4000 | Express proxy | er-remote | scripts/server-container.js | HEALTHY |
| 5002 | Engine equity | er-engine | ENGINEENGINE app.py | HEALTHY |
| 19999 | SSH reverse tunnel | (laptop→VM) | N/A | DOWN |

---

## Runtime Component Dependencies

```
Express :4000 ──depends on──► Flask :1080
Flask :1080  ──depends on──► Engine :5002 (equity routes only)
Flask :1080  ──depends on──► DB (PostgreSQL, optional)
Remote UI    ──depends on──► Express :4000
Chrome Ext   ──depends on──► Express :4000 (or direct Flask :1080)
```

---

## Key Finding: Container File Staleness

The Docker image `er-remote` contains files that were baked in at BUILD TIME and are NOT auto-synced from the git repository:

```
File                       Container Hash    Repo Hash       Status
/app/backend/static/ext/w4p.js  b6685bd...      0254ba5...    STALE (v24 backup!)
/app/source/w4p.js              0254ba5...      0254ba5...    MATCH
/app/backend/static/w4p.js     94b708df...     94b708df...    MATCH (but STALE legacy)
```

**The container's active extension file (`ext/w4p.js`) is the v24 backup, NOT the current source.** The correct version exists at `ext/w4p.js.before` (0254ba5...).

The container must be rebuilt to pick up the current extension files.

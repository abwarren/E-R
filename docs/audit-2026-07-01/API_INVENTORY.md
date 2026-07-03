# API INVENTORY — E&R Poker Platform

**Date:** 2026-07-01
**Source:** `backend/app.py` + `backend/equity_routes.py` + `scripts/server.js` + `scripts/server-container.js`

---

## Phase 5 — Complete Endpoint Enumeration

### Route Sources

Three route registries:
1. **Flask app.py** — 50+ routes (port 1080)
2. **Flask equity_routes.py** — 8 routes (port 1080, registered via `register_equity_routes`)
3. **Express server-container.js** — 6 static routes + 1 catch-all proxy (port 4000)
4. **Express server.js** (bare-metal only) — Adds ENGINE_FLASK-specific routes (not in container)

---

## Flask Backend Routes (app.py, port 1080)

### Core API

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 1 | POST | `/api/snapshot` | push_snapshot → _tables | Chrome extension | **ACTIVE** — primary data ingest | REQUIRED |
| 2 | GET | `/api/table/latest` | _build_seats_list | Remote UI, engine textarea | **ACTIVE** — most-called endpoint | REQUIRED |
| 3 | GET | `/api/table/<table_id>` | table state lookup | Remote UI, API clients | **ACTIVE** | REQUIRED |
| 4 | GET | `/api/latest` | redirect→/api/table/latest | Backward compat | **ACTIVE** (alias) | REDUNDANT (alias) |
| 5 | GET | `/api/tables` | list all table IDs | API clients | **ACTIVE** | REQUIRED |
| 6 | GET | `/api/health` | health + seq/snapshot info | Docker healthcheck, monitoring | **ACTIVE** | REQUIRED |
| 7 | GET | `/api/heartbeat` | lightweight ping | Extension keepalive | **ACTIVE** | REQUIRED |
| 8 | GET | `/api/status` | full system status | Admin | **ACTIVE** | REQUIRED |
| 9 | GET | `/api/version` | version info | Admin | **ACTIVE** | REQUIRED |

### Command Queue

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 10 | POST | `/api/commands/queue` | enqueue command | Remote UI | **ACTIVE** | REQUIRED |
| 11 | GET | `/api/commands/pending` | dequeue command | Chrome extension | **ACTIVE** | REQUIRED |
| 12 | POST | `/api/commands/ack` | acknowledge command | Chrome extension | **ACTIVE** | REQUIRED |
| 13 | POST | `/api/actions/report` | report available actions | Extension | **ACTIVE** | REQUIRED |

### Bot Management

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 14 | GET | `/api/bots` | list deployed bots | Admin | **ACTIVE** | REQUIRED |
| 15 | POST | `/api/bot/deploy` | deploy new bot | Admin | **ACTIVE** | REQUIRED |
| 16 | GET | `/api/bot/status/<deployment_id>` | bot deployment status | Admin | **ACTIVE** | REQUIRED |

### Hand Management

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 17 | GET | `/api/hands/recent` | recent hands | Engine UI | **ACTIVE** | REQUIRED |
| 18 | POST | `/api/hands/clear` | clear hands | Admin | **ACTIVE** | OPTIONAL |

### Collector Pipeline

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 19 | GET | `/collector` | HTML page | Browser | **ACTIVE** | REQUIRED |
| 20 | GET | `/collector/` | same as above | Browser | **ACTIVE** | REDUNDANT (same as #19) |
| 21 | POST | `/collector/save` | save collected hands | Chrome extension | **ACTIVE** | REQUIRED |
| 22 | POST | `/collector/clear` | clear collected hands | Admin | **ACTIVE** | OPTIONAL |
| 23 | GET | `/collector/meta` | collector metadata | Admin | **ACTIVE** | OPTIONAL |
| 24 | GET | `/api/collector/status` | collector status | Admin | **ACTIVE** | OPTIONAL |
| 25 | GET | `/api/collector/latest` | latest collector data | Engine textarea | **ACTIVE** | REQUIRED |

### Cashout

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 26 | POST | `/api/cashout/request` | cashout request | Remote UI | **ACTIVE** | OPTIONAL |
| 27 | GET | `/api/cashout/status` | cashout status | Remote UI | **ACTIVE** | OPTIONAL |

### Auth (Dual routes — API + legacy)

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 28 | POST | `/api/auth/login` | login | Engine UI, Remote UI | **ACTIVE** | REQUIRED |
| 29 | POST | `/api/login` | login (legacy) | Legacy clients | **ACTIVE** | **DUPLICATE** of #28 |
| 30 | GET | `/api/auth/verify` | verify token | Engine UI | **ACTIVE** | REQUIRED |
| 31 | POST | `/api/auth/logout` | logout | Engine UI | **ACTIVE** | REQUIRED |
| 32 | POST | `/api/logout` | logout (legacy) | Legacy clients | **ACTIVE** | **DUPLICATE** of #31 |
| 33 | GET | `/api/auth/me` | current user info | Engine UI | **ACTIVE** | REQUIRED |
| 34 | POST | `/api/auth/change-password` | change password | Web UI | **ACTIVE** | REQUIRED |

### Player Management

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 35 | GET | `/api/players` | list players | Admin UI | **ACTIVE** | REQUIRED |
| 36 | GET | `/api/players/<username>` | get player | Admin UI | **ACTIVE** | REQUIRED |
| 37 | POST | `/api/players` | create player | Admin UI | **ACTIVE** | REQUIRED |
| 38 | PUT | `/api/players/<username>` | update player | Admin UI | **ACTIVE** | REQUIRED |

### GoldRush Integration (alternate pipeline)

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 39 | POST | `/api/goldrush/save` | save GoldRush hands | Alternate client | **UNCERTAIN** | OPTIONAL |
| 40 | GET | `/api/goldrush/latest` | latest GoldRush data | Alternate client | **UNCERTAIN** | OPTIONAL |
| 41 | POST | `/api/collector/save/goldrush` | GoldRush collector save | Alternate client | **UNCERTAIN** | OPTIONAL |
| 42 | GET | `/api/collector/latest/goldrush` | GoldRush collector latest | Alternate client | **UNCERTAIN** | OPTIONAL |
| 43 | GET | `/api/table/latest/goldrush` | GoldRush table latest | Alternate client | **UNCERTAIN** | **DUPLICATE** of `/api/table/latest` |
| 44 | POST | `/api/snapshot/goldrush` | GoldRush snapshot | Alternate client | **UNCERTAIN** | **DUPLICATE** of `/api/snapshot` |

### Poker Table Scraping

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 45 | GET | `/api/poker-tables` | list scraped tables | Admin | **UNCERTAIN** | OPTIONAL |
| 46 | GET | `/api/poker-tables/<int:table_id>` | get scraped table | Admin | **UNCERTAIN** | OPTIONAL |
| 47 | POST | `/api/poker-tables` | create scraped table | Admin | **UNCERTAIN** | OPTIONAL |
| 48 | PUT | `/api/poker-tables/<int:table_id>` | update scraped table | Admin | **UNCERTAIN** | OPTIONAL |
| 49 | DELETE | `/api/poker-tables/<int:table_id>` | delete scraped table | Admin | **UNCERTAIN** | OPTIONAL |
| 50 | POST | `/api/tables/scrape` | trigger scrape | Admin | **UNCERTAIN** | OPTIONAL |
| 51 | GET | `/api/tables/available` | available tables | Admin | **UNCERTAIN** | OPTIONAL |
| 52 | GET | `/api/tables/stats` | table statistics | Admin | **UNCERTAIN** | OPTIONAL |

### Parsing

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 53 | POST | `/api/parse/batch` | batch hand parse | Admin | **UNCERTAIN** | OPTIONAL |

### Status Endpoints (monitoring)

| # | Method | Route | Handler | Caller | Current Usage | Status |
|---|--------|-------|---------|--------|---------------|--------|
| 54 | GET | `/api/remote/status` | remote status | Monitoring | **ACTIVE** | REQUIRED |
| 55 | GET | `/api/engine/status` | engine status | Monitoring | **ACTIVE** | REQUIRED |

### Static Pages (Flask-served)

| # | Method | Route | Handler | Content | Status |
|---|--------|-------|---------|---------|--------|
| 56 | GET | `/` | send_from_directory | `static/index.html` | ACTIVE |
| 57 | GET | `/remote` | send_from_directory | `static/remote-w4p.html` (63KB — LEGACY!) | **DIVERGENT** |
| 58 | GET | `/remote/` | same as /remote | same file | REDUNDANT |
| 59 | GET | `/engine` | send_from_directory | `static/engine-index.html` | ACTIVE |
| 60 | GET | `/engine/` | same as /engine | same file | REDUNDANT |
| 61 | GET | `/engine/assets/<path>` | send_from_directory | `static/engine/assets/` | ACTIVE |
| 62 | GET | `/remotebutton` | send_from_directory | `static/remotebutton.html` | UNCERTAIN |
| 63 | GET | `/shell` | send_from_directory | `static/shell-live.html` | UNCERTAIN |
| 64 | GET | `/hand-export` | send_from_directory | `static/hand-export.html` | ACTIVE |
| 65 | GET | `/n4p.js` | send_from_directory | `static/n4p.js` | UNCERTAIN |
| 66 | GET | `/w4p.js` | send_from_directory | `static/w4p.js` (35KB STALE!) | **STALE** |
| 67 | GET | `/api-config.js` | send_from_directory | `static/api-config.js` | ACTIVE |
| 68 | GET | `/login` | send_from_directory | `static/login.html` | ACTIVE |
| 69 | GET | `/change-password` | send_from_directory | `static/change-password.html` | ACTIVE |
| 70 | GET | `/player-manager` | send_from_directory | `static/player-manager.html` | ACTIVE |

---

## Flask Equity Routes (equity_routes.py, port 1080)

| # | Method | Route | Handler | Caller | Status |
|---|--------|-------|---------|--------|--------|
| 71 | POST | `/api/run` | equity calculation | Remote UI, Engine UI | **ACTIVE** |
| 72 | GET | `/api/run/<run_id>` | run status | Polling clients | **ACTIVE** |
| 73 | GET | `/api/stream/equity` | SSE equity stream | Remote UI | **ACTIVE** |
| 74 | GET | `/api/stream/<run_id>` | SSE run-specific stream | Polling clients | **ACTIVE** |
| 75 | GET | `/api/runs` | list all runs | Admin | **ACTIVE** |
| 76 | GET | `/api/results/<run_id>` | get run results | Remote UI | **ACTIVE** |
| 77 | POST | `/api/rng/generate` | RNG generation | Engine UI | **ACTIVE** |
| 78 | POST | `/api/decide` | AI action decision | Engine UI | **ACTIVE** |

---

## Express Routes (server-container.js, port 4000)

| # | Method | Route | Handler | Content | Status |
|---|--------|-------|---------|---------|--------|
| 79 | GET | `/health` | JSON response | `{"ok":true,"service":"local-bridge"}` | ACTIVE |
| 80 | GET | `/` | sendFile | `source/remote-w4p.html` (54KB) | ACTIVE |
| 81 | GET | `/remote` | sendFile | same file | ACTIVE |
| 82 | GET | `/remote/` | sendFile | same file | REDUNDANT |
| 83 | GET | `/hand-export` | sendFile | `source/hand-export.html` | ACTIVE |
| 84 | GET | `/api-config.js` | sendFile | `source/api-config.js` | ACTIVE |
| 85 | ALL | `/api/*` | proxy → Flask :1080 | ALL Flask API routes | ACTIVE |

---

## Express Routes (server.js — bare-metal laptop only, NOT in container)

Additional routes ONLY on the bare-metal laptop Express:

| # | Method | Route | Handler | Target | Status |
|---|--------|-------|---------|--------|--------|
| 86 | GET | `/engine` | serveEngine | `source/engine.html` | LAPTOP-ONLY |
| 87 | ALL | `/engine/*` | express.static | `ENGINE_STATIC` dir | LAPTOP-ONLY |
| 88 | POST | `/api/rng/generate` | proxy | Engine :5002 | LAPTOP-ONLY |
| 89 | POST | `/api/equity` | proxy | Engine :5002 | LAPTOP-ONLY |
| 90 | GET | `/api/results/latest` | proxy | Engine :5002 | LAPTOP-ONLY |
| 91 | POST | `/api/validate` | proxy | Engine :5002 | LAPTOP-ONLY |
| 92 | POST | `/api/run-batch` | proxy | Engine :5002 | LAPTOP-ONLY |
| 93 | POST | `/api/login` | proxy | Engine :5002 | LAPTOP-ONLY |
| 94 | GET | `/api/auth/verify` | proxy | Engine :5002 | LAPTOP-ONLY |
| 95 | POST | `/api/logout` | proxy | Engine :5002 | LAPTOP-ONLY |
| 96 | POST | `/snapshot` | direct handler | Express itself | LAPTOP-ONLY |
| 97 | GET | `/commands/pending` | proxy | Flask :1080 | LAPTOP-ONLY |
| 98 | POST | `/commands/ack` | proxy | Flask :1080 | LAPTOP-ONLY |
| 99 | POST | `/collector/save` | proxy | Flask :1080 | LAPTOP-ONLY |

---

## Endpoint Summary

### Total Count: 78 endpoints (excluding duplicates)
- **Flask app.py:** 54 unique routes
- **Flask equity_routes.py:** 8 routes
- **Express (container):** 6 static + 1 proxy
- **Express (bare-metal):** 14 additional (laptop-only)

### Duplicate Endpoints (same functionality, different route)

| Pair | Status | Risk |
|------|--------|------|
| `/api/latest` → `/api/table/latest` | REDUNDANT alias | LOW — backward compat |
| `/api/login` ↔ `/api/auth/login` | DUPLICATE | MEDIUM — diverging behavior risk |
| `/api/logout` ↔ `/api/auth/logout` | DUPLICATE | MEDIUM — diverging behavior risk |
| `/api/snapshot` ↔ `/api/snapshot/goldrush` | DUPLICATE | LOW — separate pipeline |
| `/api/table/latest` ↔ `/api/table/latest/goldrush` | DUPLICATE | LOW — separate pipeline |

### Unused/Uncertain Endpoints

| Route | Evidence | Recommendation |
|-------|----------|----------------|
| `/api/goldrush/*` (6 endpoints) | No known active callers | Deprecate if unused |
| `/api/poker-tables/*` (5 endpoints) | SQL-backed scraper, may be unused | Verify usage, consider removing |
| `/api/tables/scrape` | Selenium-based scraping | May conflict with extension pipeline |
| `/api/tables/available` | Table listing | Verify usage |
| `/api/tables/stats` | Statistics | Verify usage |
| `/api/parse/batch` | Batch parser | Verify usage |

### Static Files Served Incorrectly

| Route | Expected | Actual | Risk |
|-------|----------|--------|------|
| Flask `/w4p.js` | Current w4p.js (69KB) | STALE 35KB legacy | HIGH |
| Flask `/remote` | Current remote-w4p.html (54KB) | STALE 63KB version | HIGH |

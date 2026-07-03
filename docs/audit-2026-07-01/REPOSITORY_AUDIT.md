# REPOSITORY AUDIT — E&R Poker Platform

**Date:** 2026-07-01
**Auditor:** Hermes Agent
**Repository:** github.com:abwarren/E-R.git
**Local working copy:** /home/wa/projects/poker/E&R (VM mirror)
**Canonical source-of-truth:** Laptop at /home/wa/projects/poker/E&R
**Evidence tier:** DISK (VM mirror) + RUNTIME (Docker containers on VM)

---

## Phase 0 — Repository Verification

### Repository
```
Repository:  git@github.com:abwarren/E-R.git
Origin:      git@github.com:abwarren/E-R.git (fetch/push)
HEAD branch: master
```

### Branch
```
* master  8280c78 [origin/master] chore: ignore local artifacts and generated files
  fix/w4p-bridge-fetch  5bf8481 [origin/fix/w4p-bridge-fetch] fix: serve /api-config.js via Express
```

### HEAD SHA
```
8280c78e75f9e8419b18bd1bdb5cbb7c37a0adbd
```

### Tracking Branch
```
master → origin/master (up to date)
```

### Working Tree Status
```
Working tree: DIRTY — 10 deleted .bak files staged for removal, 2 untracked directories
  - backend/app.py.bak.* (3 files)
  - backend/equity_routes.py.bak.* (1 file)
  - backend/static/remote-w4p.html.bak (1 file)
  - nginx-reference/sites-enabled/default.bak.* (3 files)
  - scripts/start-local.sh.bak.* (1 file)
  - source/index.html.bak.* (1 file)
Untracked: docs/audit-2026-07-01/, docs/runtime/
```

### Latest Tags
```
v24.0.0
w4p-engineering-standard-v1.0
```

### Commit History (last 20)
```
8280c78 chore: ignore local artifacts and generated files
74acebe chore: sync runtime investigation fixes and ADR
75a5300 chore: archive investigation reports into docs/investigations/
5bf8481 fix: serve /api-config.js via Express before proxy to avoid prefix stripping
848c1f4 feat: frontend API configuration, /api/latest endpoint, environment-independent routing
9af1015 fix(extension): v24 stable seat mapping with bootstrap initialization
c4d2822 diag: add full fetch pipeline tracing to background.js service worker
a5110b4 fix: route bridgeFetch through postMessage relay instead of direct fetch
cd6921b security: untrack secrets and sensitive files
e4c3ad1 Backup: snapshot of current working state — 2026-06-23_0618
d4ce228 chore: .gitignore and production deploy script
1624f3a release: production v1.0 — stable end-to-end pipeline
63b2355 fix: is_active always emitted for every seat in _build_seats_list
1865db1 chore: add tracer.py with --remote-allow-origins=* flag
dca43d7 fix: remove hero-only gating, make pipeline table-relative
8e1406b fix: add diagnostic logging to bridge.js + background.js
c511a88 fix: revert LOCAL_MODE (HTTPS mixed-content blocks it), uncomment bridge error log
8ef7d3f fix: background.js — robust fetch response handling for SW relay
e5ec21d fix: w4p bridge — LOCAL_MODE direct fetch bypass for localhost dev
6a511eb fix: prevent stale collector hands from overriding fresh snapshot seat data
```

### Remote Branches
```
origin/engine               — ENGINEENGINE codebase (separate app)
origin/fix/w4p-bridge-fetch — bridgeFetch postMessage fix branch
origin/master               — primary branch (REMOTEREMOTE)
```

---

## Phase 1 — Repository Structure

### High-Level Directory Map

```
E&R/
├── backend/              # Flask backend (app.py, routes, static assets)
│   ├── app.py            # Main application (129,050 bytes, 3200+ lines)
│   ├── equity_routes.py  # Equity engine delegation routes
│   ├── action_router.py  # CDP-based browser action routing
│   ├── buffer.py         # Snapshot buffer + board detection
│   ├── db_logger.py      # PostgreSQL hand logging
│   ├── auth_models.py    # User authentication
│   ├── bot_deployment.py # Bot deployment management
│   ├── audit_logs.py     # Audit trail logging
│   ├── table_scraper.py  # Poker table scraping
│   ├── windows_routes.py # Windows-specific CDP management
│   ├── static/           # Flask-served static assets
│   │   ├── ext/          # Chrome extension (loaded as unpacked)
│   │   ├── engine/       # Engine static assets (React SPA)
│   │   └── *.html/*.js   # Various HTML pages and standalone JS
│   ├── venv/             # Python virtual environment
│   └── requirements.txt  # Python dependencies
│
├── scripts/              # Node.js Express server + utilities
│   ├── server.js         # Bare-metal Express (laptop, :4000)
│   ├── server-container.js # Container Express (:4000, simplified)
│   ├── tracer.py         # Browser tracer utility
│   ├── start-local.sh    # Local startup script
│   ├── stop-local.sh     # Local shutdown script
│   └── node_modules/     # Node.js dependencies
│
├── source/               # Source-of-truth for browser-side code
│   ├── w4p.js            # Main extension content script (69KB)
│   ├── w4p-lite.js       # Lightweight alternative (6.6KB)
│   ├── bridge.js         # Bridge script (not present — in ext/ only)
│   ├── background.js     # Service worker (not present — in ext/ only)
│   ├── engine_flow_controls.js # Engine textarea controls
│   ├── api-config.js     # Frontend API endpoint configuration
│   ├── remote-w4p.html   # Remote UI (single-file HTML)
│   └── assets/           # React SPA build artifacts
│
├── docs/                 # Documentation
│   ├── adr/              # Architecture Decision Records (1 ADR)
│   ├── investigations/   # Investigation reports (6 categories)
│   └── audit-2026-07-01/ # This audit
│
├── tests/                # Test suite
│   ├── tracer_bullet_e2e.py  # E2E tracer bullet tests
│   ├── pipe_test.sh          # Pipeline test
│   ├── logs/                 # Test logs
│   └── reports/              # Test reports
│
├── state/                # Runtime state persistence
├── data/                 # Collector hand data
├── tools/                # Utility tools
├── logs/                 # Runtime logs
│
├── Dockerfile            # Container image definition
├── docker-compose.yml    # Multi-container orchestration
├── entrypoint.sh         # Container startup script
├── deploy.sh             # Production deployment script
│
├── backend-reference/    # Reference backend files (ARCHIVE)
├── env-reference/        # Reference environment files (ARCHIVE)
├── nginx-reference/      # Reference nginx config (ARCHIVE)
├── service-reference/    # Reference service files (ARCHIVE)
│
├── CONTEXT.md            # Development context documentation
├── RUNBOOK.md            # Operational runbook
├── .gitignore            # Git ignore rules
└── .gitignore.d/         # Additional git ignore rules
```

### Directory Purposes

| Directory | Purpose | Runtime Role | Deployment Role | Dependencies |
|-----------|---------|-------------|-----------------|--------------|
| backend/ | Flask API server | Primary runtime (port 1080) | Copied to Docker `/app/backend/` | Flask, flask-cors, flask-limiter, flask-login, eval7, requests, selenium |
| scripts/ | Express proxy + tools | Frontend proxy (port 4000) | Copied to Docker `/app/scripts/` | express, http-proxy-middleware, Node.js 20 |
| source/ | Browser-side source of truth | Served by Express `/app/source/` | Copied to Docker `/app/source/` | None (static files) |
| docs/ | Documentation | None | Copied to Docker image | None |
| tests/ | Test suite | None | NOT in Docker image | Python stdlib |
| state/ | Persistent state | Mounted as Docker volume `remote-state` | Docker volume | None |
| data/ | Collector hand data | None | NOT active in container | None |
| tools/ | Utility tools | None | NOT in Docker image | Various |

---

## Evidence Tier Summary

| Claim | Evidence Tier | Status |
|-------|--------------|--------|
| Repo on master at 8280c78 | DISK (git log) | CONFIRMED |
| Working tree has deleted .bak files | DISK (git status) | CONFIRMED |
| Docker er-remote running 10h | RUNTIME (docker ps) | CONFIRMED |
| Docker er-engine running 17h | RUNTIME (docker ps) | CONFIRMED |
| Ports 4000/5002 listening on VM | RUNTIME (ss -tlnp) | CONFIRMED |
| Laptop SSH tunnel DOWN | RUNTIME (connection refused) | CONFIRMED |
| Container ext/w4p.js STALE vs source | DISK+RUNTIME (md5sum) | CRITICAL |

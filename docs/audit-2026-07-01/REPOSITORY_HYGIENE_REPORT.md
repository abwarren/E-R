# REPOSITORY HYGIENE REPORT — E&R Poker Platform

**Date:** 2026-07-01

---

## Phase 9 — Documentation Audit

### Documentation Inventory

```
docs/
├── adr/
│   └── ADR-0001-EXTENSION-SOURCE-AUTHORITY.md    ← 1 ADR only
├── investigations/
│   ├── api-latest/          (3 reports)
│   ├── bridge-fetch/        (6 reports)
│   ├── deployment/          (4 reports)
│   ├── plans/               (6 reports)
│   ├── project/             (3 files: CONTEXT.md, PROJECT.md, RUNBOOK.md)
│   ├── security/            (7 reports)
│   └── seat-stability/      (empty)
├── runtime/
│   └── PORT_REGRESSION_ANALYSIS.md
└── audit-2026-07-01/        (this audit)

Root:
├── CONTEXT.md               ← Development context
├── RUNBOOK.md               ← Operational runbook
└── BRIDGE_FETCH_FIX_PLAN.md ← Stale plan at root
BRIDGE_FETCH_TEST_PLAN.md    ← Stale plan at root
```

### Documentation Health Assessment

| Document | Status | Issues |
|----------|--------|--------|
| CONTEXT.md | PARTIALLY STALE | References `/home/wa/REMOTEREMOTE/` (legacy path), port 4001 for Engine UI (should be 5002) |
| RUNBOOK.md | PARTIALLY STALE | References `haaats.xyz` production URL, EC2 instance `ec2-15-240-11-107` (may be stale) |
| ADR-0001 | ACTIVE | Only 1 ADR — severely under-documented architecture decisions |
| BRIDGE_FETCH_FIX_PLAN.md | COMPLETED | Should be in docs/investigations/, not root |
| BRIDGE_FETCH_TEST_PLAN.md | COMPLETED | Should be in docs/investigations/, not root |
| Investigation reports | COMPLETED | Well-organized by topic |
| Deployment docs | MISSING | No DEPLOYMENT.md, no docker-compose documentation |

### Missing Documentation

| Document | Priority | Why Needed |
|----------|----------|------------|
| **ADR-0002: Extension Source Authority** | HIGH | Source/w4p.js vs ext/w4p.js divergence, stale container copies |
| **ADR-0003: Express Proxy Architecture** | HIGH | server.js vs server-container.js split, proxy route decisions |
| **ADR-0004: State Persistence Strategy** | MEDIUM | 10s interval, split-brain risk, state file path |
| **ADR-0005: Collector Pipeline** | MEDIUM | Hand collection, textarea integration |
| **ADR-0006: API Versioning Strategy** | LOW | No version prefix, backward compat |
| **DEPLOYMENT.md** | CRITICAL | Deployment steps, env vars, rebuild procedures |
| **ARCHITECTURE.md** | HIGH | System-level architecture overview (this audit fills gap) |
| **EXTENSION_SETUP.md** | HIGH | How to load/unpack extension, verify version |
| **TESTING.md** | MEDIUM | Test suite documentation, how to run |

### Stale Documentation

| Document | Staleness | Detail |
|----------|-----------|--------|
| CONTEXT.md | Engine port | References port 4001 — should be 5002 |
| CONTEXT.md | Legacy paths | References `/home/wa/REMOTEREMOTE/` — should be `/home/wa/projects/poker/E&R/` |
| RUNBOOK.md | Production URL | References `haaats.xyz` — may no longer be active |
| RUNBOOK.md | EC2 instance | References specific EC2 — may have changed |
| BRIDGE_FETCH_*_PLAN.md | Location | Completed plans at repo root, not in docs/ |

---

## Phase 10 — Engineering Recommendations

### Prioritized Recommendations

#### 🔴 CRITICAL — Fix Immediately

| # | Recommendation | Problem Addressed | Effort |
|---|---------------|-------------------|--------|
| 1 | **Rebuild Docker image** to sync container `ext/w4p.js` with current source | Container runs stale v24 extension code | 30 min |
| 2 | **Fix entrypoint.sh** to `rm -f /tmp/w4p_backend.lock` before starting Flask | PID lock survives restart, Flask fails | 5 min |
| 3 | **Consolidate remote-w4p.html** to single source of truth | Three divergent versions served | 1 hour |
| 4 | **Delete or update backend/static/w4p.js** — served by Flask at `/w4p.js` | 35KB legacy file served in production | 15 min |

#### 🟠 HIGH — Do This Sprint

| # | Recommendation | Problem Addressed | Effort |
|---|---------------|-------------------|--------|
| 5 | **Extract modules from monolithic app.py**: `table_routes.py`, `snapshot_routes.py`, `command_routes.py`, `auth_routes.py`, `collector_routes.py` | 129KB single file, impossible to maintain | 1-2 days |
| 6 | **Fix `dict.get()` None pitfall** — use `(seat.get("stack_zar") or 0)` pattern everywhere | TypeErrors when keys exist-but-None | 2 hours |
| 7 | **Fix buffer.py:181 board string crash** — handle `turn`/`river` as arrays | 500 errors on snapshot POST | 30 min |
| 8 | **Add CI pipeline** — GitHub Actions for tests on push | No automated testing | 2-4 hours |
| 9 | **Write DEPLOYMENT.md** — document deploy steps, env vars, rebuild procedure | No deployment docs | 1 hour |
| 10 | **Add ADR-0002 through ADR-0004** — document key architecture decisions | Only 1 ADR exists | 2 hours |

#### 🟡 MEDIUM — This Month

| # | Recommendation | Problem Addressed | Effort |
|---|---------------|-------------------|--------|
| 11 | **Delete GoldRush alternate pipeline** if unused | 6 endpoints of uncertain usage | 1 hour |
| 12 | **Delete `ext.v24/` backup from container** | 11 files of old code in production image | 15 min |
| 13 | **Move .bak files out of repo** — commit deletions, add to .gitignore | Working tree dirty, stale bak files | 15 min |
| 14 | **Move BRIDGE_FETCH_*_PLAN.md to docs/investigations/** | Stale docs at repo root | 5 min |
| 15 | **Delete `backend/ngrok` + `.tgz` (20MB)** from repo | Unused tunnel binary in source tree | 5 min |
| 16 | **Archive reference directories** (`backend-reference/`, `env-reference/`, `nginx-reference/`, `service-reference/`) | Dead reference code | 30 min |
| 17 | **Unify engine_flow_controls.js copies** — SSOT in `source/`, copy at build time | 3 identical copies | 1 hour |
| 18 | **Document test suite** — TESTING.md with how to run each test | No test documentation | 1 hour |

#### ⚪ LOW — Backlog

| # | Recommendation | Problem Addressed | Effort |
|---|---------------|-------------------|--------|
| 19 | **Add API versioning** (`/api/v1/` prefix) | No versioning strategy | 1 day |
| 20 | **Add type annotations** to Python code | No type safety | Ongoing |
| 21 | **Delete `w4p-lite.js`** if unused | Alternative implementation | 5 min |
| 22 | **Delete .zip archives** from source tree | Pre-built archives in repo | 5 min |
| 23 | **Consolidate api-config.js** to single serving path | Dual-serving risk | 30 min |
| 24 | **Add hardware/OS health endpoint** | No system monitoring | 1 hour |
| 25 | **Document extension setup** — EXTENSION_SETUP.md | No extension docs | 30 min |

---

## Repository Hygiene Scorecard

| Category | Score | Notes |
|----------|-------|-------|
| **Code Organization** | 3/10 | Monolithic 129KB app.py, no module separation |
| **Duplicate Files** | 2/10 | 5 w4p.js copies, 3 divergent remote-w4p.html, stale container |
| **Documentation** | 4/10 | 1 ADR, stale CONTEXT.md, no deployment docs |
| **Testing** | 2/10 | Tests exist but no CI, no docs, broken by ampersand path |
| **Deployment** | 4/10 | Dockerized but stale images, PID lock bug, manual rebuild |
| **State Management** | 5/10 | SSOT identified but split-brain risk, volatile queues |
| **API Design** | 4/10 | 50+ endpoints, duplicate auth routes, no versioning |
| **Dependency Hygiene** | 6/10 | venv + node_modules in repo, requirements tracked |
| **Git Hygiene** | 5/10 | Dirty working tree, .bak files not cleaned, good commit history |
| **Security** | 5/10 | Secrets in .env (gitignored), hardcoded defaults, no rotation docs |

**Overall: 40/100**

---

## Success Criteria Answers

### What is actually deployed?
- **er-remote container:** Docker image built from commit ~e4c3ad1 or similar. Flask :1080 + Express :4000. Extension files are STALE (v24 backup, not current source).
- **er-engine container:** Built from ENGINEENGINE repo. Flask :5002 with eval7 Monte Carlo scripts.

### Which files are authoritative?
- `source/w4p.js` — SSOT for extension content script
- `source/remote-w4p.html` — SSOT for remote UI
- `backend/app.py` — SSOT for Flask backend
- `backend/static/ext/` — SSOT for extension manifest + support files
- All other copies are either build-time copies or stale duplicates.

### Which files are duplicates?
- w4p.js: 5 copies, 1 stale legacy (35KB), 1 stale container (v24)
- remote-w4p.html: 3 copies, ALL DIFFERENT
- engine_flow_controls.js: 3 copies, identical (redundant)
- api-config.js: 2 copies, identical (redundant)

### Which files are obsolete?
- `backend/static/w4p.js` (35KB legacy) — DELETE
- `backend/static/remote-w4p.html` (63KB version) — SYNC or DELETE
- `backend/ngrok*` (20MB) — DELETE
- Reference directories (4 dirs) — ARCHIVE
- Container `ext.v24/` (11 files) — DELETE from production image
- Container .bak and .swp files — DELETE

### Where does every piece of runtime state originate?
- Table/Seat/Board: Browser DOM → w4p.js scraper → POST /api/snapshot → buffer.py → _tables merge
- Commands: Remote UI → POST /api/commands/queue → _command_queue (volatile)
- Equity results: Engine subprocess → result_parser.py → equity_routes.py in-memory (volatile)
- Persistent state: _tables → state_snapshot.json (10s interval)

### Where is unnecessary complexity?
- Monolithic 129KB app.py with 50+ routes in single file
- Two Express server files (server.js vs server-container.js) with diverging routes
- GoldRush alternate pipeline (6 endpoints) of uncertain usage
- CDP-based browser automation (action_router.py, windows_routes.py) alongside extension pipeline
- Selenium scraper (table_scraper.py) alongside extension DOM scraper

### What should the long-term architecture look like?
1. **Modular Flask** — Routes in separate files, registered as Blueprints
2. **Single Express server** — One file, env-var-driven differences for bare-metal vs container
3. **Build pipeline** — Copy `source/` files to deploy targets (ext/, static/) at build time
4. **CI/CD** — GitHub Actions: test on push, build Docker image, deploy
5. **API versioning** — `/api/v1/` prefix, deprecation headers
6. **State layer** — Extract state management from app.py into a `StateManager` class
7. **Single SSOT** — One copy of each browser-side file in `source/`, copied at build time

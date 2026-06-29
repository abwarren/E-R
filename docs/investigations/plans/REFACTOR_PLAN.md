# E&R Poker Platform — Refactoring Plan

**Date:** 2026-06-23
**Author:** Hermes Agent
**Status:** Draft — not yet implemented

---

## Overview

This plan outlines a structured refactoring of the E&R codebase to address the technical debt identified in PROJECT.md. The guiding principle: **surgical refactoring, one module at a time, with tests before and after each change.**

---

## Phase 1: Fix Immediate Issues (0.5 day)

Priority fixes that don't require large-scale refactoring.

### 1.1 Fix PORT Default
**File:** `backend/app.py:2699`
**Change:** `port=int(os.getenv('PORT', '4000'))` → `port=int(os.getenv('PORT', '1080'))`
**Risk:** Minimal — Express already owns :4000, nothing depends on Flask using :4000
**Verification:** `PORT=1080 python app.py` starts without error

### 1.2 Remove Dead Express Proxy Routes
**File:** `scripts/server.js:97-106`
**Change:** Remove ENGINE_FLASK proxy routes (now handled by Flask equity_routes.py)
**Risk:** Low — these routes are dead code
**Verification:** Equity endpoints still work after removal

### 1.3 Add .gitignore Entries
**File:** `.gitignore`
**Add:**
```
*.pem
*.broken.*
*.current_broken.*
backend/data/secret_key
backend/.env
state/state_snapshot.json
logs/*.log
```
**Risk:** None
**Verification:** `git status` shows these files as ignored

### 1.4 Remove Broken Backup Files
**Files:** `ENGINEENGINE/source/app.py.broken.*`, `ENGINEENGINE/source/app.py.current_broken.*`
**Change:** Delete these files (they contain old copies of secrets)
**Risk:** None — these are broken variants
**Verification:** Files gone, app still runs

---

## Phase 2: Split app.py into Modules (2-3 days)

The 3,154-line monolith is the biggest technical debt item. This must be done **carefully** with full test coverage before and after.

### Target Structure

```
backend/
├── app.py                    # ~100 lines: Flask app creation, blueprint registration, startup
├── config.py                 # ~60 lines: environment, constants, defaults
├── auth/
│   ├── __init__.py
│   ├── models.py             # User model (from auth_models.py)
│   ├── routes.py             # Login/logout/verify endpoints (from app.py ~2257-2700)
│   └── decorators.py         # login_required, admin_required
├── snapshot/
│   ├── __init__.py
│   ├── engine.py             # POST /api/snapshot logic (~300 lines from app.py)
│   ├── table_state.py        # _tables, get_or_create_table, _build_seats_list, _table_view
│   ├── deal_detection.py     # make_hand_key, _detect_new_deal, _archive_hand
│   └── persistence.py        # _serialise_state, _load_state, _persist_loop, _cleanup_loop
├── commands/
│   ├── __init__.py
│   ├── routes.py             # /api/commands/pending, queue, ack, actions/report
│   └── tokens.py             # generate_seat_token, seat token validation
├── collector/
│   ├── __init__.py
│   ├── routes.py             # /collector/* endpoints
│   ├── goldrush.py           # GoldRush collector endpoints
│   └── storage.py            # File I/O, batch reading, card extraction
├── equity/
│   ├── __init__.py
│   └── routes.py             # SSE streaming, worker pool (from equity_routes.py)
├── tables/
│   ├── __init__.py
│   └── routes.py             # /api/tables, /api/tables/scrape, /api/tables/stats
├── bots/
│   ├── __init__.py
│   └── routes.py             # /api/bots, /api/bot/deploy, /api/bot/status
├── cashout/
│   ├── __init__.py
│   └── routes.py             # /api/cashout/request, /api/cashout/status
├── windows/
│   ├── __init__.py
│   └── routes.py             # /api/windows/* (from windows_routes.py)
├── services/
│   ├── __init__.py
│   ├── buffer.py             # In-memory ring buffer (already separate)
│   ├── db_logger.py          # PostgreSQL logger (already separate)
│   ├── table_scraper.py      # Lobby scraper (already separate)
│   └── action_router.py      # CDP injection (already separate)
└── static/                    # Unchanged
```

### Migration Strategy

**Step 2.1: Write characterization tests for app.py**
- Record current behavior of all endpoints
- Use pytest + Flask test client
- Capture all JSON responses for known inputs
- These tests define "correct behavior"

**Step 2.2: Extract config.py**
- Move all `os.getenv()` calls into a single config module
- Define dataclass: `class Config: PORT, N4P_SEAT_SECRET, SEAT_TTL, ...`
- Replace all `os.getenv('X', 'Y')` with `config.X`

**Step 2.3: Extract snapshot engine**
- Move `post_snapshot()` and related helpers into `snapshot/engine.py`
- Move `_tables`, `get_or_create_table`, `_build_seats_list`, `_table_view` into `snapshot/table_state.py`
- Move `make_hand_key`, `_detect_new_deal`, `_archive_hand` into `snapshot/deal_detection.py`
- Move `_serialise_state`, `_load_state`, `_persist_loop`, `_cleanup_loop` into `snapshot/persistence.py`
- Register as Flask blueprint: `app.register_blueprint(snapshot_bp, url_prefix='/api')`

**Step 2.4: Extract commands**
- Move command endpoints into `commands/routes.py`
- Move seat token logic into `commands/tokens.py`
- Register blueprint

**Step 2.5: Extract collector**
- Move PokerBet collector into `collector/routes.py`
- Move GoldRush collector into `collector/goldrush.py`
- Move file operations into `collector/storage.py`
- Merge shared logic between PokerBet and GoldRush paths

**Step 2.6: Extract auth**
- Move login/logout/verify into `auth/routes.py`
- User model stays in `auth/models.py` (already separate)
- Register blueprint

**Step 2.7: Extract remaining modules**
- Tables, bots, cashout, windows — one blueprint each
- Each is relatively small (~50-100 lines)

**Step 2.8: New app.py**
```python
from flask import Flask
from config import Config

app = Flask(__name__)
# ... CORS, limiter, login manager setup ...

from snapshot.engine import snapshot_bp
from commands.routes import commands_bp
from collector.routes import collector_bp
from auth.routes import auth_bp
from equity.routes import equity_bp
# ... etc

app.register_blueprint(snapshot_bp)
app.register_blueprint(commands_bp)
# ... etc

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.PORT, debug=False)
```

**Risk:** Medium — large code movement, but behavior-preserving with tests.
**Effort:** 2-3 days

---

## Phase 3: Split w4p.js (2-3 days)

The extension script is ~4,000 lines in a single IIFE. It also has duplicate versions across repos.

### Target Structure

```
ext/
├── adapters/
│   ├── pokerbet.js           # PokerBet-specific selectors, card parsing
│   ├── goldrush.js           # GoldRush-specific selectors, card parsing
│   └── base.js               # Common adapter interface
├── scrapers/
│   ├── seats.js              # Seat scraping: names, stacks, positions
│   ├── cards.js              # Card parsing: hole cards, board
│   ├── actions.js            # Available action button detection
│   └── table.js              # Table ID extraction, context detection
├── executor/
│   ├── commands.js           # Command polling, execution queue
│   ├── clicks.js             # Button clicking: presets, BET, RAISE
│   └── cashout.js            # Cashout flow
├── state/
│   ├── poller.js             # Adaptive polling loop
│   └── session.js            # Session state, config, API_BASE
├── transport/
│   ├── fetch.js              # HTTP fetch wrapper (for standalone)
│   └── bridge.js             # postMessage bridge (for extension)
├── utils/
│   ├── dom.js                # DOM query helpers
│   └── cards.js              # Card rank/suit utilities
└── w4p.js                    # ~50 lines: bootstrap, detect context, wire up adapters
```

### Migration Strategy

**Step 3.1: Extract utility functions**
- Card parsing (`parseCard`, `RANK_MAP`)
- DOM helpers
- These are pure functions, easy to test

**Step 3.2: Extract site adapters**
- PokerBet DOM selectors, table ID detection
- GoldRush DOM selectors, table ID detection
- Base adapter interface: `{ getTableId(), getSeats(), getBoard(), getActions(), getButtons() }`

**Step 3.3: Extract scrapers**
- Seat scraping: names, stacks, seat_index
- Card parsing: CSS class → rank+suit
- Action detection: visible buttons

**Step 3.4: Extract executor**
- Command polling loop
- Button clicking with preset-first model
- Cashout flow

**Step 3.5: Extract state management**
- Mode detection (IDLE, HERO_TURN, HAND_ACTIVE, NO_TABLE)
- Adaptive polling with variable intervals
- Session tracking

**Step 3.6: New w4p.js bootstrap**
```javascript
import { detectSite } from './adapters/base.js';
import { startPoller } from './state/poller.js';

const adapter = detectSite();
if (adapter) {
    stopW4PTimers();  // cleanup prior instances
    startPoller(adapter);
}
```

**Risk:** Medium-High — the scraper is complex and tightly coupled to live DOMs.
**Effort:** 2-3 days

---

## Phase 4: Unify GoldRush + PokerBet (1 day)

### Current State
- `_tables` dict for PokerBet tables
- `_tables_goldrush` dict for GoldRush tables
- Duplicate collector endpoints: `/api/collector/*` vs `/api/collector/*/goldrush`
- Duplicate snapshot endpoints: `/api/snapshot` vs `/api/snapshot/goldrush`

### Target State
- Single `_tables` dict with `platform` field (`pokerbet` | `goldrush`)
- Single collector with subdirectories per platform
- Single snapshot endpoint that detects platform from payload

### Changes
1. Add `platform` field to table state schema
2. Merge `_tables_goldrush` into `_tables` with platform='goldrush'
3. Route `/api/snapshot/goldrush` → same handler with platform override
4. Route `/api/collector/latest/goldrush` → `/api/collector/latest?platform=goldrush`

**Risk:** Low — GoldRush code is small and well-isolated.
**Effort:** 1 day

---

## Phase 5: Configuration Cleanup (0.5 day)

### 5.1 Create config.py with TypedDict
```python
from dataclasses import dataclass
import os

@dataclass
class Config:
    PORT: int = int(os.getenv('PORT', '1080'))
    FLASK_ENV: str = os.getenv('FLASK_ENV', 'production')
    TRACKER_API_KEY: str = os.getenv('TRACKER_API_KEY', '')
    N4P_SEAT_SECRET: str = os.getenv('N4P_SEAT_SECRET', '')
    SEAT_TTL: int = int(os.getenv('N4P_SEAT_TTL', '30'))
    CMD_TTL: int = int(os.getenv('N4P_CMD_TTL', '30'))
    PERSIST_INT: int = int(os.getenv('N4P_PERSIST_INT', '10'))
    STATE_FILE: str = os.getenv('N4P_STATE_FILE', 'state/state_snapshot.json')
    ENGINE_URL: str = os.getenv('ENGINE_URL', 'http://127.0.0.1:5002')
    DB_HOST: str = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT: str = os.getenv('DB_PORT', '5432')
    DB_NAME: str = os.getenv('DB_NAME', 'er_hands')
    DB_USER: str = os.getenv('DB_USER', 'postgres')
    DB_PASS: str = os.getenv('DB_PASS', '')
    COLLECTOR_FILE_MAX_AGE: float = float(os.getenv('COLLECTOR_FILE_MAX_AGE', '60.0'))
    STALE_MAX_AGE: float = float(os.getenv('STALE_MAX_AGE', '5.0'))
    STALE_TTL: float = float(os.getenv('STALE_TTL', '5.0'))
    
    def validate(self):
        """Crash if required secrets are missing."""
        missing = []
        if not self.TRACKER_API_KEY:
            missing.append('TRACKER_API_KEY')
        if not self.N4P_SEAT_SECRET:
            missing.append('N4P_SEAT_SECRET')
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
```

### 5.2 Create .env.example
```
PORT=1080
FLASK_ENV=development
TRACKER_API_KEY=change_me
N4P_SEAT_SECRET=change_me
ENGINE_URL=http://127.0.0.1:5002
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=er_hands
DB_USER=postgres
DB_PASS=change_me
```

### 5.3 Populate .env with Real Values
Extract secrets from current defaults, move to .env.

**Risk:** Low
**Effort:** 0.5 day

---

## Phase 6: Security Remediation (1 day)

Per SECURITY_AUDIT.md findings:

1. Remove `LINUXSSHKEY.pem` from git (BFG or filter-branch)
2. Delete all `*.broken.*` backup files
3. Rotate ANTHROPIC_API_KEY, TRACKER_API_KEY, SCANNER_API_KEY
4. Move all secrets to .env with no defaults
5. Remove PokerBet credentials from `remote.html`
6. Migrate engine auth to bcrypt in database
7. Add rate limiting to login endpoints
8. Remove API keys from client-side JS files

**Risk:** Low (security improvement)
**Effort:** 1 day

---

## Phase 7: Testing Infrastructure (1 day)

### 7.1 Add pytest with Flask Test Client
```python
# tests/conftest.py
import pytest
from app import app as flask_app

@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    return flask_app

@pytest.fixture
def client(app):
    return app.test_client()
```

### 7.2 Core Tests
```python
# tests/test_snapshot.py — validate snapshot ingestion
# tests/test_commands.py — validate command queue/ack cycle
# tests/test_table.py   — validate table state merging
# tests/test_auth.py    — validate login flow
# tests/test_buffer.py  — validate ring buffer FIFO
```

### 7.3 E2E Tracer Bullet
Extend `tests/tracer_bullet_e2e.py` to cover the full pipeline:
1. POST snapshot → verify state
2. POST command → poll pending → verify returned
3. POST ack → verify cleared
4. POST equity run → verify SSE stream

**Risk:** Low (testing only)
**Effort:** 1 day

---

## Effort Summary

| Phase | Description | Effort | Risk |
|-------|-------------|--------|------|
| 1 | Immediate fixes | 0.5 day | Low |
| 2 | Split app.py | 2-3 days | Medium |
| 3 | Split w4p.js | 2-3 days | Medium-High |
| 4 | Unify GoldRush + PokerBet | 1 day | Low |
| 5 | Configuration cleanup | 0.5 day | Low |
| 6 | Security remediation | 1 day | Low |
| 7 | Testing infrastructure | 1 day | Low |
| **Total** | | **8-10 days** | |

---

## Risk Mitigation

1. **Every phase is independently reversible** — blueprints can be unregistered
2. **Tests before refactoring** — characterization tests capture current behavior
3. **One module per PR** — each phase produces a self-contained, reviewable change
4. **No behavior changes in refactoring phases** — only move code, don't change logic
5. **Security fixes are last** — don't mix security changes with refactoring

---

## Files to NOT Touch (High-Risk Areas)

These files are critical to runtime behavior and have no test coverage. Approach with extreme caution:

| File | Reason |
|------|--------|
| `w4p.js` (extension) | Live DOM selectors — changing them silently breaks scraping |
| `app.py` `post_snapshot()` | ~300 lines of hand merge logic with undocumented edge cases |
| `equity_routes.py` worker pool | Serialized execution with threading — easy to deadlock |
| `buffer.py` | Thread-safe deque — subtle concurrency bugs possible |
| `action_router.py` | CDP WebSocket — hard to test without Vivaldi running |

---

## Recommended Execution Order

```
Phase 1 (immediate fixes) → deploy, verify
Phase 5 (config)          → deploy, verify
Phase 7 (tests)           → write characterization tests
Phase 2 (split app.py)    → one blueprint at a time, test between each
Phase 4 (unify platforms)  → after app.py is split
Phase 3 (split w4p.js)    → highest risk, do last
Phase 6 (security)        → after everything else is stable
```

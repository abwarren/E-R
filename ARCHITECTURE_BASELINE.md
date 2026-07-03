# ARCHITECTURE BASELINE — W4P PLO Poker Platform

**Last Updated:** 2026-07-02
**Status:** FROZEN — architectural reference, not implementation instruction

## Runtime Architecture

```
GoldRush / PokerBet (HTTPS)
  │
  ▼
Chrome Extension (w4p.js — content script, ISOLATED world)
  │  DOM scrape → snapshot
  │  postMessage → bridge.js → background.js → fetch() (bypasses PNA)
  ▼
POST /api/snapshot → Flask :1080 (backend/app.py)
  │  table_state in _tables (in-memory, SSOT)
  │  ┌──────────────────────────┬──────────────────────┐
  ▼  ▼                          ▼                      ▼
Remote UI                    Engine                  Event Store
remote-w4p.html              engine_flow_controls    (future, append-only)
(Express :4000)              (Engine :5002)
GET /api/table/latest        GET /api/latest
long-poll (25s timeout)      adaptive poll (1.5s/5s)
```

## Single Source of Truth (SSOT)

| State | SSOT | NOT SSOT |
|-------|------|----------|
| Table state | Flask `_tables` (in-memory) | Remote UI, Engine, SQL |
| Seat assignment | Extension `_seatCache` | Backend `seat_map` (read-only diagnostic) |
| Action buttons | Extension `BTN_SEL` (DOM) | Backend, Remote UI |
| Hero identity | `.self-player` class | URL, `_heroFromUrl()` (removed) |
| Render state | Remote UI `lastTable` | Flask static copies |
| Canonical source | `source/` directory | `backend/static/` (divergent copies) |

## Component Map

| Component | File | Owner | Runtime |
|-----------|------|-------|---------|
| Extension scraper | `source/w4p.js` | Extension | Browser (Chrome/Opera) |
| DOM bridge | `backend/static/ext/bridge.js` | Extension | Browser |
| Service worker | `backend/static/ext/background.js` | Extension | Browser |
| Flask backend | `backend/app.py` | Backend | Docker (:1080) |
| Express bridge | `scripts/server.js` | Backend | Docker (:4000) |
| Remote UI | `source/remote-w4p.html` | Remote UI | Express-served (:4000) |
| Engine poller | `source/engine_flow_controls.js` | Engine | Engine page (:5002) |
| Engine backend | `ENGINEENGINE/source/app.py` | Engine | Docker (:5002) |

## Protection Levels

### 🔴 Level 1 — Engineering Process (Highest)

*May not be modified without explicit, separate approval. Feature approvals do not
include permission to modify process files.*

| File | Purpose |
|------|---------|
| `W4P Project Context & Operating Directive.md` | Governing directive (FROZEN v1.0) |
| `.hermes/skills/*/er-poker-platform/SKILL.md` | Engineering methodology |
| `.hermes/skills/*/engineering-standards/SKILL.md` | Quality standards |
| `PLO/ADRs/ADR-*.md` | Architecture decisions |
| `ARCHITECTURE_BASELINE.md` | This file |
| `PROJECT_BASELINE.md` | Production state reference |
| `RELEASE_MANIFEST.md` | Release process template |

### 🟠 Level 2 — Production Runtime

*May not be modified without explicit approval. Every change must include
a PROPOSED CHANGE block with reason, impact, risk, and rollback plan.*

| Component | Files |
|-----------|-------|
| Extension | `source/w4p.js`, `backend/static/ext/w4p.js`, `bridge.js`, `background.js`, `manifest.json` |
| Backend | `backend/app.py`, `backend/equity_routes.py`, `backend/buffer.py` |
| Remote UI | `source/remote-w4p.html` |
| Engine | `source/engine_flow_controls.js`, `ENGINEENGINE/source/app.py` |
| Express | `scripts/server.js`, `scripts/server-container.js` |
| Docker | `docker-compose.yml`, `Dockerfile` |

### 🟢 Level 3 — Documentation

*May be created and updated without approval, provided no runtime code changes.
Investigation reports, release notes, validation plans.*

| Examples |
|----------|
| `RELEASE_NOTES.md`, `LIVE_VALIDATION_REQUIRED.md` |
| Investigation reports |
| Audit documents |
| Test scripts (no runtime impact) |

## Data Stability Model

### Stable for Session Duration

These are immutable once assigned for the current table session:

| Data | Owner | Rule |
|------|-------|------|
| Seat index (1-9) | Extension `_seatCache` | Never changes |
| Player → seat assignment | Extension `_seatCache` | Player stays in assigned seat |
| Position (BTN, SB, BB, etc.) | Game state | Set at hand start |

### Always Fresh (No Staleness)

These must reflect the latest known value from the most recent snapshot:

| Data | Owner | Rule |
|------|-------|------|
| Stack (ZAR) | Extension scrape → Backend | Every poll updates |
| Hole cards | Extension scrape → Backend | Every poll updates |
| Community cards | Extension scrape → Backend | Every poll updates |
| Pot | Extension scrape → Backend | Every poll updates |
| Dealer button | Extension scrape → Backend | Every poll updates |
| Available actions | Extension `BTN_SEL` → Backend | Every poll updates |
| Street | Derived from board cards | Every poll updates |
| Timer | (future) | Every poll updates |

If no longer valid, update or clear. Never serve old values as current.

### Transient Tolerance

For temporary DOM glitches (missing name, missing container), use a confidence
model rather than immediate clear:

```
Poll 1:  Seat 3 → Bob (ACTIVE)
Poll 2:  DOM temporarily omits Bob's name
         → Keep "Bob" (transient missing, 2s TTL)
Poll 3:  Bob appears again → ACTIVE
```

| State | TTL | Action on Expiry |
|-------|-----|-----------------|
| Transient missing (name=null, was known) | 2 seconds | Mark "Unknown" |
| Unknown (confidence lost) | 30 seconds | Clear seat |
| Confirmed departure (session evidence) | Immediate | Clear seat |
| New session detected | Immediate | Full seat map reset |

**This prevents UI flicker while ensuring genuinely departed players
don't remain forever.**

### Never Acceptable

- Serving data from a snapshot older than the current known-good interval
- Showing a player in a seat where they are no longer seated
- Freezing the DOM on old data when the API returns `waiting`
- Compacting the grid to fill gaps left by departing players

## Extension ↔ Backend ↔ Remote UI Contract

```
Extension (w4p.js)                   Backend (app.py)                Remote UI (remote-w4p.html)
─────────────────                    ────────────────                ───────────────────────────
seat_index: stable position            seat_no: 1-9                    pos: 0-8 (zero-indexed slot)
name: scraped player name              name: sanitized, non-null       rendered if name != null
status: playing|sitting_out|folded     status: passed through          CSS: hero|sitting-out|expanded
is_hero: bool                          is_hero: bool                   is_self_player: bool
is_active: hero && avail.length>0      is_active: passed through       NOT a render gate
available_actions: hero?avail:[]       available_actions: per-seat     hasActions gate (L840)
stack_zar: float                       stack_zar: float                R X.XX displayed
hole_cards: hero?cards:[]              hole_cards: hero cache fallback  rendered if length>0
```

## Data Flow — Snapshot → Render

```
1. Extension tick() @ 300ms
2. DOM scrape → buildSnapshot()
3. resolveSeatIndex() → stable seat_index
4. POST /api/snapshot (postMessage relay)
5. Backend _tables merge (per-bot write protection)
6. GET /api/table/latest?timeout=25&last_ts=N (long-poll)
7. Remote UI fetchTable() → JSON compare → scheduleRender()
8. renderSeats() → posSeatMap from seat_no → buildSeatBoxHtml()
```

## Known Architectural Debt

| ID | Issue | Impact |
|----|-------|--------|
| DEBT-001 | `_TABLE_INACTIVE_TTL = 30s` | 30s of stale data served as live |
| DEBT-002 | `_last_good_view` 5s cache | Marked `stale:true` but UI ignores |
| DEBT-003 | Remote UI frozen DOM on `waiting` | Old board rendered indefinitely |
| DEBT-004 | Backend skips seat when `name=null` | Name flicker → seat disappears |
| DEBT-005 | Two divergent remote-w4p.html copies | Flask serves 63KB, Express serves 54KB |
| DEBT-006 | `engine_flow_controls.js` uses `setInterval` | Can pile up if poll > 1.5s |
| DEBT-007 | Engine container `source/` ≠ deployed `backend/static/` | v2.1.0 regression-in-waiting |

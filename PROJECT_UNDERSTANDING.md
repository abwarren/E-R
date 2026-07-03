# PROJECT UNDERSTANDING — W4P PLO Poker Platform

**Created:** 2026-07-03
**Author:** Hermes Agent (bootstrap pass)
**Status:** READ-ONLY survey — no code changes
**Approval:** Awaiting explicit user approval before any implementation

---

## 1. Architecture Summary

### Runtime Data Flow

```
GoldRush / PokerBet (HTTPS poker client)
  │
  ▼
Chrome Extension (w4p.js — content script, ISOLATED world)
  │  DOM scrape → buildSnapshot()
  │  resolveSeatIndex() → stable seat_index
  │  postMessage → bridge.js → background.js → fetch() (bypasses PNA)
  ▼
POST /api/snapshot → Flask :1080 (backend/app.py)
  │  table_state merged into _tables (in-memory, Single Source of Truth)
  │
  ├── GET /api/table/latest?timeout=25&last_ts=N  →  Remote UI (Express :4000)
  │    remote-w4p.html long-polls, renders seat grid
  │
  ├── GET /api/latest (via Engine Flask proxy)    →  Engine (:5002)
  │    engine_flow_controls.js textarea auto-fill
  │
  └── (Future) Event Store — append-only SQL ledger
```

### Single Source of Truth (SSOT)

| State Domain | SSOT | NOT SSOT |
|-------------|------|----------|
| Table state | Flask `_tables` (in-memory) | Remote UI, Engine, SQL |
| Seat assignment | Extension `_seatCache` | Backend `seat_map` (read-only diagnostic) |
| Action buttons | Extension `BTN_SEL` (DOM) | Backend, Remote UI |
| Hero identity | `.self-player` class | URL, `_heroFromUrl()` (removed) |
| Render state | Remote UI `lastTable` | Flask static copies |

### Identity Invariants (Never Change During a Session)

- Seat Index
- Player → Seat assignment
- Table ID
- Session ID

### Dynamic State (May Change Every Poll)

- Stack, Cards, Pot, Dealer, Street, Actions, Sitting Out, Time Bank

---

## 2. Runtime Ownership

| Component | File | Owner | Responsibility |
|-----------|------|-------|--------------|
| Extension scraper | `source/w4p.js` / `backend/static/ext/w4p.js` | Extension | DOM parsing, seat resolution, player detection, snapshot generation |
| DOM bridge | `backend/static/ext/bridge.js` | Extension | postMessage relay |
| Service worker | `backend/static/ext/background.js` | Extension | fetch() with host_permissions |
| Flask backend | `backend/app.py` | Backend | table_state, snapshot pipeline, API contracts, command queue |
| Express bridge | `scripts/server.js` | Backend | API proxy :4000 → :1080, serves remote-w4p.html |
| Remote UI | `source/remote-w4p.html` | Remote UI | Rendering ONLY — never decides truth |
| Engine poller | `source/engine_flow_controls.js` | Engine | Human interaction, command display |
| Engine backend | `ENGINEENGINE/source/app.py` | Engine | Equity calculations, API proxy |

### The UI Never Owns Truth

```
Remote UI → Displays state only.
Never decides state.
Never assigns seats.
Never resolves conflicts.
Never repairs snapshots.

The Extension owns seat resolution.
The Backend owns the current table state.
```

---

## 3. Repository Structure

| Field | Value |
|-------|-------|
| Repository | `git@github.com:abwarren/E-R.git` |
| Branch | `master` |
| HEAD commit | `94a6cfcf7f250b870fb3e593637c6d1ef4ef0643` |
| HEAD message | `fix(remote): preserve seat positions for sitting-out players` |
| Working tree | Modified: `backend/app.py` (uncommitted), 25 untracked files |
| Tags | `w4p-seat-stability-v1`, `w4p-selector-registry-v1`, `w4p-engineering-standard-v1.0` |
| Local path | `/home/wa/projects/poker/E&R` |

### Runtime Locations

| Component | Location | Port |
|-----------|----------|------|
| Flask backend | `backend/app.py` (Docker: `/app/backend/app.py`) | 1080 |
| Express bridge | `scripts/server.js` (Docker: `/app/scripts/server-container.js`) | 4000 |
| Engine equity | `ENGINEENGINE/source/app.py` (Docker) | 5002 |
| Chrome extension | `backend/static/ext/` (loaded unpacked from host filesystem) | — |
| Remote UI | `source/remote-w4p.html` (Express-served, SSOT) | via :4000 |
| State file | `state/state_snapshot.json` | — |

### Deployed File Map

- **Express :4000 serves:** `source/remote-w4p.html` (54KB, SSOT), `source/assets/`
- **Flask :1080 serves:** `backend/static/` (legacy copies — divergent from source)
- **Browser loads:** `backend/static/ext/w4p.js` from host filesystem (NOT from container)
- **Container `ext/w4p.js`:** Stale backup — zero runtime impact on the extension

---

## 4. Current Production Baseline

| Field | Value |
|-------|-------|
| Release | `w4p-seat-stability-v1` |
| Commit | `94a6cfc` |
| Date | 2026-07-02 |
| Status | CONDITIONAL RELEASE (live validation deferred) |
| Previous | `w4p-selector-registry-v1` |

### What Changed (w4p-seat-stability-v1)

One file: `source/remote-w4p.html` — 4 patches:
1. Removed `seat.status !== "sitting_out"` filter from posSeatMap
2. Added `.seat-box.sitting-out` CSS (45% opacity, greyed, "SITTING OUT" label)
3. buildSeatBoxHtml conditionally adds sitting-out class and label
4. seatHash now includes `seat.status` — triggers re-render on state transitions

### What Was Intentionally NOT Changed

- Extension (`source/w4p.js`, `backend/static/ext/w4p.js`, bridge.js, background.js)
- Backend (`backend/app.py`)
- Snapshot format, API contracts
- Engine (`engine_flow_controls.js`, `ENGINEENGINE/source/app.py`)
- Express (`scripts/server.js`)

### Why

Sitting out is a player state, not a seat removal event. The extension owns seat assignment — the Remote UI renders whatever the extension reports. The fix was a render-layer change only.

---

## 5. Protected Components

### Level 1 — Engineering Process (Highest)

*May not be modified without explicit, separate approval.*

- `W4P Project Context & Operating Directive.md` (FROZEN v1.0)
- `.hermes/skills/*/er-poker-platform/SKILL.md`
- `.hermes/skills/*/engineering-standards/SKILL.md`
- `PLO/ADRs/ADR-*.md`
- `ARCHITECTURE_BASELINE.md`
- `PROJECT_BASELINE.md`
- `RELEASE_MANIFEST.md`

### Level 2 — Production Runtime

*May not be modified without explicit approval + PROPOSED CHANGE block.*

| Component | Files |
|-----------|-------|
| Extension | `source/w4p.js`, `backend/static/ext/w4p.js`, `bridge.js`, `background.js`, `manifest.json` |
| Backend | `backend/app.py`, `backend/equity_routes.py`, `backend/buffer.py` |
| Remote UI | `source/remote-w4p.html` |
| Engine | `source/engine_flow_controls.js`, `ENGINEENGINE/source/app.py` |
| Express | `scripts/server.js`, `scripts/server-container.js` |
| Docker | `docker-compose.yml`, `Dockerfile` |

### Runtime Protection Status

| Subsystem | Status | Default Rule |
|-----------|--------|-------------|
| Seat Assignment | ✓ Protected | Never touch unless explicitly targeted |
| Seat Cache | ✓ Protected | Never touch unless explicitly targeted |
| Selector Registry | ✓ Protected | Never touch unless explicitly targeted |
| Extension scrape | ✓ Protected | Never touch unless explicitly targeted |
| Snapshot Format | ✓ Protected | Never touch unless explicitly targeted |
| Backend table_state | ✓ Protected | Never touch unless explicitly targeted |
| Remote UI rendering | ✓ Protected | Never touch unless explicitly targeted |
| Engine polling | ✓ Protected | Never touch unless explicitly targeted |
| Bridge (postMessage) | ✓ Protected | Never touch unless explicitly targeted |

---

## 6. Seat Stability — Architectural Invariant

### The Rule

```
Seat indices are immutable for a table session.
Player state may change.
Seat assignment may not.

The Remote renders seat state.
The Extension owns seat resolution.
```

### The State Machine

```
EMPTY
  ↓
PLAYER_DETECTED
  ↓
ACTIVE
  ↓
SITTING_OUT
  ↓
ACTIVE
  ↓
UNKNOWN (temporary DOM loss)
  ↓
ACTIVE
  or
  ↓
LEFT_TABLE
  ↓
EMPTY
```

**Notice:** Seat index never changes. Only the state changes.

### Confidence Model

| Level | Condition |
|-------|-----------|
| HIGH | Player visible in DOM |
| MEDIUM | DOM temporarily missing |
| LOW | Seat unresolved |
| NONE | Seat confirmed empty |

### Unknown State Handling

Temporary DOM loss is **UNKNOWN** — not EMPTY. Never destroy state because of temporary uncertainty.

### Transient Tolerance Rules

| State | TTL | Action on Expiry |
|-------|-----|-----------------|
| Transient missing (name=null, was known) | 2 seconds | Mark "Unknown" |
| Unknown (confidence lost) | 30 seconds | Clear seat |
| Confirmed departure (session evidence) | Immediate | Clear seat |
| New session detected | Immediate | Full seat map reset |

**User-proposed refinement (not yet adopted):** Replace the 30-second timer with event-driven clearing — only clear a seat when: new table/session detected, different player positively identified, table reports seat as empty, or manual reset. A timer is a heuristic; a table event is proof.

### Never Acceptable

- Serving data from a snapshot older than the current known-good interval
- Showing a player in a seat where they are no longer seated
- Freezing the DOM on old data when the API returns `waiting`
- Compacting the grid to fill gaps left by departing players

---

## 7. ADR Catalog

| ADR | Title | Decision | Status |
|-----|-------|----------|--------|
| ADR-0001 | Extension Source Authority | `backend/static/ext/` is the single source of truth for the Chrome extension | ACCEPTED |
| ADR-0015 | Engine Textarea Polling — Reverse Proxy Architecture | Engine Flask proxies `/api/table/*` → `er-remote:4000` (Option B) | PROPOSED |
| ADR-011 | BLOCKED is an acceptable engineering outcome | Document missing prerequisites and wait. Never simulate, infer, or implement speculatively. | ACCEPTED |
| ADR-012 | Frame discovery via confidence scoring | Automatically detect poker frame — enumerate accessible frames, score on poker DOM signals, select highest confidence. Never hardcode frame indices. | ACCEPTED |
| ADR-013 | Desktop + Mobile as single product with selector registry | `SELECTORS.desktop` / `SELECTORS.mobile` profiles. Shared parser, platform-specific selectors only. Mobile selectors EMPTY until live DOM capture. | ACCEPTED |
| ADR-014 | Selector registry validation with startup gate | `validateSelectorRegistry()` gates `tick()`. Desktop=VALID, Mobile=BLOCKED until selectors populated. | ACCEPTED |

### Why These Decisions Were Made

**ADR-0001 (Source Authority):** Two divergent extension copies existed — `source/` (untracked, wrong API config) and `backend/static/ext/` (tracked, correct). The decision eliminated ambiguity by naming a single authoritative source. Git authority determines truth.

**ADR-0015 (Engine Proxy):** Poller used relative URL resolving to wrong port. Option A (hardcoded URL) was rejected because it makes the frontend environment-aware. Option C (serve from er-remote) was rejected because it couples independent services. Option B (reverse proxy) was selected — clean separation of concerns, zero frontend changes, no CORS.

**ADR-011 (BLOCKED):** Prevents speculative implementation when prerequisites are unavailable. BLOCKED with documented prerequisites is a valid engineering outcome, not a failure.

**ADR-012 (Frame Discovery):** Hardcoded iframe indices break when the poker client changes its DOM structure. Confidence scoring automatically adapts to any frame layout.

**ADR-013 (Desktop + Mobile):** Shared parser eliminates code duplication. Platform-specific selectors isolate the only thing that differs. Mobile selectors are empty until live DOM capture — prevents speculative mobile selectors from breaking the desktop path.

**ADR-014 (Registry Validation):** Startup gate prevents parsing from running with an incomplete selector set. Reports ALL missing selectors at once instead of failing one at a time.

---

## 8. Technical Debt

| ID | Issue | Impact | Status |
|----|-------|--------|--------|
| DEBT-001 | `_TABLE_INACTIVE_TTL = 30s` | 30s of stale data served as live | Open |
| DEBT-002 | `_last_good_view` 5s cache | Marked `stale:true` but UI ignores | Open |
| DEBT-003 | Remote UI frozen DOM on `waiting` | Old board rendered indefinitely | Open |
| DEBT-004 | Backend skips seat when `name=null` | Name flicker → seat disappears | Open |
| DEBT-005 | Two divergent remote-w4p.html copies | Flask serves 63KB, Express serves 54KB | Open |
| DEBT-006 | `engine_flow_controls.js` uses `setInterval` | Can pile up if poll > 1.5s | Open |
| DEBT-007 | Engine container `source/` ≠ deployed `backend/static/` | v2.1.0 regression-in-waiting (BRIDGE_URL changed to `/api/latest`) | Open |

### Known Limitations

1. Live validation deferred — EC2 SSH unavailable
2. Backend name flicker — transient DOM name loss causes backend to omit seat
3. EC2 UFW blocks 4000/5002 — external browsers can't reach tunnel
4. Express divergence — `server.js` ≠ `server-container.js`
5. Container staleness — `ext/w4p.js` in container is stale (irrelevant — Chrome loads from host)
6. Engine bridge URL regression — source v2.1.0 changed `BRIDGE_URL` to `/api/latest`, Flask proxy only handles `/api/table/*`

---

## 9. Open Investigations

| ID | Subject | Status |
|----|---------|--------|
| TODO-001 | Transient name disappearance — preserve identity when `name=null` | Not started |
| TODO-002 | Stale data elimination — `_TABLE_INACTIVE_TTL` 30s→3s | Proposed |
| TODO-003 | Event Store SQL schema | Design phase |
| LIVE_VALIDATION_REQUIRED | Seat stability production verification | Deferred (EC2 down) |

---

## 10. Release History

```
v24.0.0 (bootstrap + selector registry)
  ↓
w4p-selector-registry-v1
  ↓
w4p-seat-stability-v1  ← current (2026-07-02, CONDITIONAL)
  ↓
w4p-engine-proxy-v1    (pending)
  ↓
w4p-mobile-selector-v1 (pending)
```

---

## 11. Engineering Rules Summary

### SURGICAL MODE (effective 2026-07-02)

- One defect = one change
- PROPOSED CHANGE block required before any edit
- Protected subsystems: seat mapping, snapshot pipeline, hero detection, remote UI, selector registry, runtime bridge
- Regression gate before every commit
- One logical change per commit
- Every change validated end-to-end vertical slice

### Operating Rules (AUTHORITATIVE)

- Flask MUST run on :1080
- Express MUST run on :4000
- Engine MUST run on :5002
- Never use `hero_tbl` fallbacks — `.self-player` class ONLY
- Never derive hero from URL — `_heroFromUrl()` removed
- Extension is table-relative — no global hero anchoring
- `is_active` is authoritative for every seat
- `available_actions` are per-seat from visible buttons
- BLOCKED is acceptable (ADR-011) — never simulate
- Frame discovery via confidence scoring (ADR-012)
- Desktop + Mobile = one product (ADR-013)
- Registry validation at startup (ADR-014)

### Already Proven (DO NOT RE-INVESTIGATE)

16 conclusively-proven truths including: hero detection mechanism, bridgeFetch fix at ea5867e, Flask PID lock behavior, seat stability, frame discovery, selector registry, PNA loopback blocking, and more. See skill for full list.

---

## 12. Maturity Assessment

| Area | Status |
|------|--------|
| Engineering Process | 🟢 10/10 |
| Release Discipline | 🟢 10/10 |
| Regression Protection | 🟢 9.5/10 |
| Runtime Architecture | 🟢 9/10 |
| Documentation | 🟢 10/10 |
| Observability | 🟢 9/10 |
| Source Control Discipline | 🟢 10/10 |

---

## 13. Next Major Milestone

The Event Store (SQL) — a passive, append-only recorder that captures every session, hand, street, action, and balance change without disturbing the live runtime. Provides complete audit trail for replay, analytics, and future AI capabilities.

---

## Approval Status

- [ ] User has reviewed and approved this understanding
- [ ] User has authorized transition to implementation mode

# Unified Engine ↔ Remote Synchronization — Revised Plan v2

**Status:** DRAFT — awaiting approval
**Based on:** Architecture review v1 + 12 revisions from operator review
**Date:** 2026-07-20

---

## Architecture Diagram (Revised)

```
Extension (w4p.js)  ───POST /api/snapshot───┐
                                            ▼
┌────────────────────────────────────────────────────────────┐
│                 Flask Backend (:1080) — SSOT               │
│                                                           │
│  _tables[(tid, bid)]   hand_id UUID    version counter   │
│  Hand Lifecycle FSM    _detect_new_deal()  authority      │
│  _find_active_bot()    command_queue     _PG sync        │
│                                                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │          Event Dispatcher (transport-agnostic)        │ │
│  │                                                       │ │
│  │  dispatch(event) → SSE handler                        │ │
│  │                   → WebSocket handler (future)         │ │
│  │                   → Replay handler (deterministic)     │ │
│  │                   → Test harness (mock consumer)       │ │
│  │                                                       │ │
│  │  Events: table_update | engine_update | hand_event    │ │
│  │          seat_changed | pot_changed | board_changed   │ │
│  │          hand_complete | heartbeat | state_snapshot   │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────┬──────────────────────────────┘
                             │ Event Bus (currently SSE)
                             ▼
┌────────────────────────────────────────────────────────────┐
│              Unified Frontend (single page)                │
│                                                            │
│  Feature flags:                                            │
│    USE_SSE=true            USE_EVENT_BUS=true              │
│    USE_UNIFIED_LAYOUT=true USE_HAND_FSM=true               │
│    USE_VERSIONED_STATE=true                                 │
│                                                            │
│  ┌─────────────┬─────────────┬─────────────┐              │
│  │   HEADER    │  BOARD BAR  │  CONTROLS   │              │
│  ├─────────────┴─────────────┴─────────────┤              │
│  │          3x3 SEAT GRID                  │              │
│  ├───────────────────┬─────────────────────┤              │
│  │  ENGINE PANEL     │  SYNC INSPECTOR     │              │
│  │  (collapsible)    │  (collapsible)       │              │
│  │  hands | equity   │  version | latency   │              │
│  │  auto-run | %     │  snap# | queue      │              │
│  ├───────────────────┴─────────────────────┤              │
│  │  CMD LOG / EVENT LOG                    │              │
│  └─────────────────────────────────────────┘              │
└────────────────────────────────────────────────────────────┘
```

---

## Phase 0 — Architecture Freeze & Baseline (MANDATORY)

Before any code changes, capture the exact pre-migration state.

### 0.1 Create Recovery Snapshots

| Artifact | Command / Action | File Path |
|----------|-----------------|-----------|
| Git tag | `git tag -a v2.0.0-unification-baseline -m "Pre-unification baseline"` | Repo |
| Database | `pg_dump er_hands > .hermes/snapshots/db-pre-unification-$(date +%Y%m%d).sql` | `.hermes/snapshots/` |
| Docker compose | `cp docker-compose.yml .hermes/snapshots/docker-compose-pre-unification.yml` | `.hermes/snapshots/` |
| State file | `cp /app/state/state_snapshot.json .hermes/snapshots/state-pre-unification.json` | `.hermes/snapshots/` |
| Config | `cp .env .hermes/snapshots/env-pre-unification.env` | `.hermes/snapshots/` |
| API schema | `curl -s :1080/api/health | python3 -m json.tool > .hermes/snapshots/api-health-pre-unification.json` | `.hermes/snapshots/` |
| Static assets | `sha256sum backend/static/remote-w4p.html source/remote-w4p.html source/engine_flow_controls.js > .hermes/snapshots/sha256-pre-unification.txt` | `.hermes/snapshots/` |

### 0.2 Baseline Performance Benchmarks

Run these 3 times and record median:

| Metric | How to Measure | Baseline (median) |
|--------|---------------|-------------------|
| Snapshot→Backend latency | `time curl -X POST :1080/api/snapshot -d '{...}'` | ___ms |
| Snapshot→API latency | Poll `/api/table/latest` immediately after POST | ___ms |
| Long-poll wake latency | POST snapshot while long-poll is held open, measure response time | ___ms |
| Engine /api/run latency | POST to `/api/run` with PLO4 hands | ___ms |
| Memory: Flask RSS | `docker stats er-remote --no-stream` | ___MB |
| CPU: Flask % | `docker stats er-remote --no-stream` | ___% |
| Error rate (30min) | `docker logs er-remote 2>&1 | grep -c ERROR` | ___ |

### 0.3 Regression Baseline

Run the existing MVP validation suite and record every pass/fail:

- MVP-1: Active player detection
- MVP-2: Hand capture (all 7 fields)
- MVP-3: Remote rendering
- MVP-4: Engine rendering
- MVP-5: Command execution
- MVP-6: Stability (no oscillation, no flicker)
- REG-001: No selection oscillation
- REG-002: street never null
- REG-003: No stale board when inactive

**Result:** ___/9 pass

### 0.4 Document Current Behaviour (Video)

Record 30s screen capture of the Remote + Engine operating side-by-side during a live hand cycle. Stored at `.hermes/snapshots/baseline-behavior-notes.md`.

### 0.5 Phase 0 Gate

**Do not proceed to Phase A until:**
- [ ] All 9 recovery snapshots created and verified restorable
- [ ] Baseline benchmarks recorded (median of 3)
- [ ] MVP regression suite 9/9 passing
- [ ] Behaviour documented
- [ ] ADR-001, ADR-002, ADR-003 written and committed

---

## Phase A — Event Bus + SSE (Tracer Bullet)

### Feature Flag
- `USE_SSE=true` (default: `false` — long-poll continues as fallback)
- `USE_EVENT_BUS=true` (default: `false`)

### Changes

**backend/app.py:**
1. Create `EventDispatcher` class — transport-agnostic dispatch:
   ```python
   class EventDispatcher:
       def __init__(self):
           self._sse_clients = []  # list of queue.Queue
           self._ws_clients = []   # reserved for future
           self._replay_log = deque(maxlen=10000)  # deterministic replay buffer
       
       def dispatch(self, event_type: str, payload: dict):
           """Push event to ALL registered transports."""
           event = {
               "type": event_type,
               "version": monotonic_version(),
               "ts": time.time(),
               "data": payload,
               "hand_id": payload.get("hand_id"),
           }
           self._replay_log.append(event)
           self._push_sse(event)
           # self._push_ws(event)  # future
       
       def replay(self, hand_id: str) -> list[dict]:
           """Return all events for a given hand_id."""
           return [e for e in self._replay_log if e.get("hand_id") == hand_id]
   ```

2. Add SSE endpoint `/api/events`:
   - Long-lived GET, streams `text/event-stream`
   - Client receives `table_update`, `engine_update`, `hand_event`, `heartbeat`

3. On every `post_snapshot()` → `dispatch("table_update", table_view)`
4. On every equity calc complete → `dispatch("engine_update", equity_results)`
5. On hand lifecycle transition → `dispatch("hand_event", {from, to, hand_id})`
6. Heartbeat every 25s (existing long-poll timeout — keeps SSE alive)

**source/remote-w4p.html:**
1. Add `EventSource` connection to `/api/events`
2. On `table_update` → call existing `render()` pipeline (unchanged)
3. On `engine_update` → populate engine panel
4. On `hand_event` → trigger hand lifecycle display
5. Fallback: if `EventSource` disconnects → resume existing long-poll

**What is NOT changed:**
- `_tables` dict structure (versioned later)
- `_find_active_bot()` logic
- `is_authoritative_snapshot()` logic
- `post_snapshot()` data ingestion
- seat stability, command queue, auto-actions

### Verification
- [ ] SSE connection established (1 connection instead of 2 pollers)
- [ ] Snapshot→display latency < 100ms (vs 50ms-25s long-poll)
- [ ] Long-poll count drops to 0 when SSE is connected
- [ ] Fallback works: kill SSE → long-poll resumes
- [ ] Feature flag OFF restores original behaviour
- [ ] All 6 MVP requirements still pass
- [ ] REG-001, REG-002, REG-003 still pass

### Rollback
- Set `USE_SSE=false` → browser reloads with long-poll
- `git revert <phase-a-commit>` if needed

---

## Phase B — Unified Frontend (Vertical Slice)

### Feature Flag
- `USE_UNIFIED_LAYOUT=true` (default: `false`)
- When `false`: Remote renders at `/remote`, Engine renders at `/engine` (current behaviour)
- When `true`: Remote at `/remote` includes embedded engine panel

### Changes

**source/remote-w4p.html:**
1. Add collapsible engine panel below the seat grid
2. Engine panel shows:
   - Auto-fill toggle, Auto-run flop toggle, Manual turn toggle, Clear river toggle
   - Hands textarea (auto-populated from table data)
   - Equity results table (player name, equity %, hand name)
   - Run Engine button
3. Add Sync Inspector panel (collapsible):
   - Event version counter
   - Snapshot age / sequence number
   - Connection status (SSE/long-poll)
   - Render time (ms)
   - Hand lifecycle state
   - Reconnect count
   - Memory usage (performance.memory)

**source/engine_flow_controls.js:**
1. **NOT deleted.** Deprecated banner added:
   ```
   // ╔══════════════════════════════════════════════════════╗
   // ║  DEPRECATED — v2.0.0                               ║
   // ║  Engine polling migrated to Unified Frontend.       ║
   // ║  This file will be removed after 2 weeks stability  ║
   // ║  monitoring (target: 2026-08-03).                   ║
   // ╚══════════════════════════════════════════════════════╝
   ```
2. Disabled by default when `USE_UNIFIED_LAYOUT=true`
3. `/engine` route still serves the old standalone engine page for fallback

### Verification
- [ ] Engine panel renders below seat grid when flag ON
- [ ] Auto-fill populates hands from table data
- [ ] Auto-run fires on FLOP
- [ ] Manual turn toggle respected (TURN doesn't auto-run)
- [ ] River clear toggle respected
- [ ] Sync Inspector shows live metrics
- [ ] `/engine` still works (old page, deprecated)
- [ ] MVP-1 through MVP-6 pass
- [ ] Regression suite 9/9 pass

### Rollback
- `USE_UNIFIED_LAYOUT=false` → restores split layout
- Engine still works via `/engine` standalone page

---

## Phase C — Versioned State & Idempotent Updates

### Feature Flag
- `USE_VERSIONED_STATE=true` (default: `false`)

### Changes

**backend/app.py:**
1. Add global monotonic version counter (`_global_version = itertools.count()`)
2. Every `post_snapshot()` → `table["_version"] = next(_global_version)`
3. Every `dispatch()` event includes the version
4. State diff generation:
   ```python
   def compute_diff(old_table, new_table):
       """Return only changed fields."""
       diff = {}
       if old_table.get("street") != new_table.get("street"):
           diff["street"] = new_table["street"]
       if old_table.get("pot_zar") != new_table.get("pot_zar"):
           diff["pot_zar"] = new_table["pot_zar"]
       if old_table.get("board") != new_table.get("board"):
           diff["board"] = new_table["board"]
       # Seat-level diffs
       diff["seat_changes"] = []
       for sn, new_seat in new_table.get("seats", {}).items():
           old_seat = old_table.get("seats", {}).get(sn)
           seat_diff = seat_diff(old_seat, new_seat)
           if seat_diff:
               diff["seat_changes"].append({"seat_no": sn, "changes": seat_diff})
       return diff
   ```
5. Events with version < client's last received version are silently dropped (client-side)
6. Idempotent event handling: same version processed twice produces same state

**source/remote-w4p.html:**
1. Track `_lastVersion` (starts at 0)
2. On `table_update` event: if `event.version <= _lastVersion`, ignore
3. Increment `_lastVersion = event.version`
4. If event contains `diff` object (partial), merge into local state
5. If event contains `full` (full table), replace local state

### Benefits
- Stale snapshot cannot overwrite newer state
- Duplicate events (SSE reconnect) don't re-render
- Diff-based payloads are ~90% smaller than full state
- Deterministic ordering

### Verification
- [ ] Version counter increments monotonically
- [ ] Client ignores stale events (version check)
- [ ] Duplicate FLOP event doesn't re-render
- [ ] Diff payloads verified smaller than full state (measure)
- [ ] Full fallback still works when `USE_VERSIONED_STATE=false`

---

## Phase D — Hand Lifecycle State Machine

### Feature Flag
- `USE_HAND_FSM=true` (default: `false`)

### Changes

**backend/app.py:**
1. Define formal state machine:
   ```python
   HAND_STATES = {
       "WAITING":        {"next": {"SEATED", "NEW_HAND"}},
       "SEATED":         {"next": {"NEW_HAND", "WAITING"}},
       "NEW_HAND":       {"next": {"PREFLOP", "WAITING"}},
       "PREFLOP":        {"next": {"FLOP", "WAITING"}},
       "FLOP":           {"next": {"TURN", "RIVER", "WAITING"}},
       "TURN":           {"next": {"RIVER", "WAITING"}},
       "RIVER":          {"next": {"SHOWDOWN", "HAND_COMPLETE", "WAITING"}},
       "SHOWDOWN":       {"next": {"HAND_COMPLETE", "WAITING"}},
       "HAND_COMPLETE":  {"next": {"ARCHIVED", "READY", "NEW_HAND"}},
       "ARCHIVED":       {"next": {"READY", "WAITING"}},
       "READY":          {"next": {"NEW_HAND", "SEATED", "WAITING"}},
   }
   ```
2. Add `table["hand_state"]` field to every table entry
3. Validate every transition in `post_snapshot()`:
   - Invalid transition → log warning, reject, keep current state
   - `is_authoritative_snapshot()` gates the actual transition
4. On `HAND_COMPLETE` → `dispatch("hand_event", {from, to, hand_id})`
5. On `ARCHIVED` → push to `_hand_history`, clear board/pot/cards
6. Expose current state in `/api/table/latest` response: `"hand_lifecycle": "FLOP"`

**source/remote-w4p.html:**
1. Display hand lifecycle state in Sync Inspector and board bar
2. `hand_lifecycle === "HAND_COMPLETE"` triggers display flash (optional)

### Verification
- [ ] All valid transitions produce correct state
- [ ] Invalid transitions (PREFLOP→RIVER) rejected with log
- [ ] HAND_COMPLETE → board clear works
- [ ] HAND_COMPLETE → NEW_HAND works
- [ ] No regressions in existing hand detection (`make_hand_key`, `_detect_new_deal`)
- [ ] MVP-6 stability still passes

---

## Phase E — Observability Dashboard

### Feature Flag
- `USE_OBSERVABILITY=true` (default: `true`)

### Changes

**backend/app.py:**
1. Add in-memory metrics collector (thread-safe counters):
   ```python
   class Metrics:
       def __init__(self):
           self.snapshots_received = 0
           self.snapshots_rejected = 0
           self.events_dispatched = 0
           self.commands_queued = 0
           self.commands_executed = 0
           self.commands_expired = 0
           self.hands_archived = 0
           self.invalid_transitions = 0
           self._latencies = deque(maxlen=100)
       
       def record_latency(self, ms): self._latencies.append(ms)
       def avg_latency(self): return sum(self._latencies)/len(self._latencies) if self._latencies else 0
   ```
2. Add `/api/metrics` endpoint returning all counters
3. Add `/api/events/replay?hand_id=XXX` for deterministic replay
4. Expose in `/api/health`

**Unified Frontend:**
1. Sync Inspector shows live metrics (polled from `/api/metrics` every 5s)
2. Graph: latency over time (last 60 data points)
3. Counter display: snapshots, commands, hands, events/sec
4. Replay button: replay a hand by hand_id → step through events

### Verification
- [ ] Metrics counters increment correctly
- [ ] `/api/metrics` returns valid data
- [ ] Replay produces identical events to original hand
- [ ] Sync Inspector shows live data

---

## Summary of Feature Flags

| Flag | Default | Purpose | Introduced | Removed |
|------|---------|---------|------------|---------|
| `USE_SSE` | `true` (Phase A+) | Enable SSE transport | Phase A | Never |
| `USE_EVENT_BUS` | `true` (Phase A+) | Enable event dispatcher | Phase A | Never |
| `USE_UNIFIED_LAYOUT` | `false` Phase B, `true` after 2wk | Single page layout | Phase B | Phase F |
| `USE_VERSIONED_STATE` | `true` (Phase C+) | Monotonic version + diff | Phase C | Never |
| `USE_HAND_FSM` | `true` (Phase D+) | Formal hand lifecycle | Phase D | Never |
| `USE_OBSERVABILITY` | `true` | Metrics dashboard | Phase D | Never |

**Feature flag implementation:**
```python
# backend/config.py
FEATURE_FLAGS = {
    "USE_SSE": os.getenv("USE_SSE", "true").lower() == "true",
    "USE_EVENT_BUS": os.getenv("USE_EVENT_BUS", "true").lower() == "true",
    "USE_UNIFIED_LAYOUT": os.getenv("USE_UNIFIED_LAYOUT", "false").lower() == "true",
    "USE_VERSIONED_STATE": os.getenv("USE_VERSIONED_STATE", "false").lower() == "true",
    "USE_HAND_FSM": os.getenv("USE_HAND_FSM", "false").lower() == "true",
    "USE_OBSERVABILITY": os.getenv("USE_OBSERVABILITY", "true").lower() == "true",
}
```

---

## File Modification Manifest

### Phase 0 (No code changes)
- `.hermes/snapshots/*` — NEW directory with 9+ snapshot files
- `.hermes/plans/unified-engine-remote-sync-v2.md` — NEW (this file)
- `docs/adr/ADR-001-EVENT-BUS-ARCHITECTURE.md` — NEW
- `docs/adr/ADR-002-UNIFIED-FRONTEND.md` — NEW
- `docs/adr/ADR-003-HAND-LIFECYCLE-FSM.md` — NEW

### Phase A
- `backend/app.py` — MODIFY: +EventDispatcher, +/api/events SSE, +dispatch calls in post_snapshot
- `backend/config.py` — NEW: feature flags
- `source/remote-w4p.html` — MODIFY: +EventSource listener, +fallback logic

### Phase B
- `source/remote-w4p.html` — MODIFY: +engine panel HTML/CSS, +Sync Inspector
- `source/engine_flow_controls.js` — MODIFY: add deprecation banner (NOT deleted)
- `scripts/server.js` — NO CHANGE (both /remote and /engine still served)

### Phase C
- `backend/app.py` — MODIFY: +_global_version, +compute_diff(), +version in events
- `source/remote-w4p.html` — MODIFY: +_lastVersion tracking, +stale event rejection, +diff merge

### Phase D
- `backend/app.py` — MODIFY: +HAND_STATES dict, +transition validation, +hand_state in table entries
- `source/remote-w4p.html` — MODIFY: +hand_lifecycle display

### Phase E
- `backend/app.py` — MODIFY: +Metrics class, +/api/metrics, +/api/events/replay
- `source/remote-w4p.html` — MODIFY: +metrics display in Sync Inspector, +replay UI

---

## Files That Remain Untouched (Complete List)

- `backend/buffer.py` — Internal plumbing, no change
- `backend/action_router.py` — CDP routing, orthogonal
- `backend/bot_deployment.py` — Bot lifecycle, orthogonal
- `backend/auth_models.py` — Auth, orthogonal
- `backend/windows_routes.py` — Windows instances, orthogonal
- `backend/equity_routes.py` — Equity calc, extracted later in Phase D
- `source/w4p.js` — Extension scraper, unchanged
- `source/hand-export.html` — Standalone, unchanged
- `source/api-config.js` — Config, unchanged
- `source/assets/*` — Static assets, unchanged
- `data/hand-collector/*` — Collector, unchanged
- `investigation/*` — Read-only records
- `docs/*` (except ADR files) — Governance docs
- `service-reference/*` — Service files
- `env-reference/*` — Environment examples
- `nginx-reference/*` — Nginx config
- `tests/*` — Tests (will be updated to cover new code)

---

## Rollback Strategy (Per Phase)

| Phase | Trigger | Rollback Action | Time |
|-------|---------|-----------------|------|
| Any | Any regression | `USE_FLAG=false` → restart | 30s |
| A | SSE broken | `USE_SSE=false` → long-poll resumes | 30s |
| B | Layout broken | `USE_UNIFIED_LAYOUT=false` → old layout | 30s |
| C | Version mismatch | `USE_VERSIONED_STATE=false` → full payloads | 30s |
| D | FSM bug | `USE_HAND_FSM=false` → existing heuristics | 30s |
| E | Metrics overhead | `USE_OBSERVABILITY=false` → no metrics | 30s |

**Feature flag file (`backend/config.py`)**: All flags read from `os.getenv` — can be toggled via `docker exec er-remote env USE_SSE=false` without rebuild, or set in `docker-compose.yml` and `docker compose up -d`.

---

## Validation Gate (Every Phase)

Before marking any phase complete:

- [ ] 6 MVP requirements pass
- [ ] REG-001, REG-002, REG-003 pass
- [ ] New feature works with flag ON
- [ ] Old behaviour works with flag OFF
- [ ] No console errors (browser or backend)
- [ ] Deployment parity: `sha256sum` matches between source and container
- [ ] Git commit + tag created
- [ ] `.hermes/snapshots/` updated with post-phase state
- [ ] ADR updated if decisions changed
- [ ] Baseline benchmarks re-run (Phase 0 measurements exist for comparison)

---

## Timeline Estimate

| Phase | Effort | Clock Time |
|-------|--------|------------|
| Phase 0: Baseline | 1 session | ~1 hour |
| Phase A: Event Bus | 1 session | ~2 hours |
| Phase B: Unified UI | 2 sessions | ~4 hours |
| Phase C: Versioned State | 1 session | ~2 hours |
| Phase D: Hand FSM | 1 session | ~2 hours |
| Phase E: Observability | 1 session | ~1 hour |
| **Total** | **7 sessions** | **~12 hours** |

Each phase is a committed milestone — `git tag v2-unification-phase-{letter}`.

---

**Implementation plan complete.**
The following flags/features will be added or modified:

Phase 0 backups at `.hermes/snapshots/`
ADR-001, ADR-002, ADR-003 at `docs/adr/`
Phases A-E with feature flags in `backend/config.py`
All gated by `USE_*` env vars for instant rollback

**Would you like me to proceed with Phase 0?**

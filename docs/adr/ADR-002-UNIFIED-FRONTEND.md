# ADR-002: Unified Frontend — Single Page with Feature Flags

**Status:** ACCEPTED (draft)
**Date:** 2026-07-20
**Driver:** Eliminate duplicate rendering logic, polling, and state ownership between Remote and Engine
**Phase:** Phase B

---

## Context

Currently two separate browser contexts serve the operator:

| Context | Route | Server | Polling | State |
|---------|-------|--------|---------|-------|
| Remote UI | `/remote` | Express :4000 | Long-poll (25s) | `lastTable`, `renderedSeats`, auto-action state |
| Engine tab | `/engine` | Express :4000 (serves ENGINEENGINE static) | setInterval (1.5s/5s) | `lastSnapshotHash`, hand context, auto-run state |
| Debug/logs | Embedded in Remote | None | None | Console only |

Both independently poll the same API, parse the same JSON, and render overlapping information (board, street, pot, hero cards). Every difference between them is a bug.

---

## Decision

Merge Engine functionality into the Remote page as a collapsible panel. Both become one page:

```
/remote (Unified Dashboard)
├── Header (title, connection status, latency)
├── Board Bar (street, board cards, pot, hand lifecycle)
├── Global Controls (AUTO C/C, SELECT ALL C/F, KH, SIT-IN)
├── 3x3 Seat Grid (existing, unchanged)
├── Engine Panel (collapsible, new)
│   ├── Auto-fill/Auto-run/Clear River toggles
│   ├── Hands textarea (auto-populated)
│   ├── Equity results table
│   └── Run Engine button
├── Sync Inspector (collapsible, new)
│   ├── Version counter, snapshot age, latency
│   ├── Hand lifecycle state
│   ├── Event log / command log
│   └── Replay controls
└── CMD LOG (existing, moved)
```

### Feature Flag: `USE_UNIFIED_LAYOUT`

The entire change is gated by a single env var:

- `USE_UNIFIED_LAYOUT=false` (default during Phase B rollout): `/remote` renders the existing Remote UI, `/engine` renders the existing standalone Engine page
- `USE_UNIFIED_LAYOUT=true`: `/remote` renders the unified dashboard with embedded engine panel. `/engine` continues to serve the old standalone page (deprecated but functional)

This means:
1. Deploy Phase B code with flag OFF — nothing changes
2. Toggle ON for one operator — test the unified layout
3. If bugs found, toggle OFF — instant rollback, no redeploy
4. After 2 weeks of stability, change default to `true`

### Old Engine File: Deprecation, Not Deletion

`source/engine_flow_controls.js`:
1. Add deprecation banner header
2. Disable automatic initialization when `USE_UNIFIED_LAYOUT=true`
3. `/engine` still serves the old page with working engine_flow_controls.js
4. Delete the file after 2 weeks of `USE_UNIFIED_LAYOUT=true` with zero issues

### 3-Copy Sync

Every change to `source/remote-w4p.html` must be mirrored to:
- `backend/static/remote-w4p.html` (Flask serves from here)
- `backend/static/ext/remote-w4p.html` (Chrome Extension)

Use deployment parity gate: `sha256sum` comparison after deploy.

---

## Consequences

### Positive
- Single render pipeline — one `render()` call updates both seat grid and engine panel
- One EventSource connection replaces two pollers
- No divergence between Remote and Engine data
- Debug panel in the same page as seat grid — operator sees everything at once
- Feature flag gives instant rollback without redeploy

### Negative
- Single page is more complex than two simple pages (~1,800 lines → ~2,200 lines)
- Operator loses ability to have Remote and Engine in separate windows (possible future: open `/engine` in a new tab for the standalone view)
- Engine equity calculations are now in-page JS, not a separate worker — may block UI rendering during heavy equity calc (mitigation: equity runs on backend via SSE, frontend just displays)

### Tradeoffs
- **Collapsible vs separate tab:** Collapsible is simpler (one EventSource, one render cycle). If operators need dedicated screen real estate, a future enhancement could pop out the engine panel into a separate window communicating via BroadcastChannel.
- **Vanilla JS vs React:** The existing Remote UI is vanilla JS (~1,800 lines). Rewriting in React would add 100KB+ of framework code with zero user-facing benefit. Keep vanilla JS.

---

## Related

- ADR-001: Event Bus Architecture (provides the events this page consumes)
- ADR-003: Hand Lifecycle State Machine (adds lifecycle state to this page's inspector)
- Phase B implementation details in `.hermes/plans/unified-engine-remote-sync-v2.md`

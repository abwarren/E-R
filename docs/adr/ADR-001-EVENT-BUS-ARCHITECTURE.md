# ADR-001: Event Bus Architecture — Transport-Agnostic Event Dispatch

**Status:** ACCEPTED (draft)
**Date:** 2026-07-20
**Driver:** Unify Engine ↔ Remote synchronization via single event stream
**Phase:** Phase A

---

## Context

The W4P platform has two independent consumers (Remote UI and Engine) that both poll the same `/api/table/latest` endpoint at different rates (Remote: long-poll, Engine: 1.5s setInterval). This creates:

- Duplicate HTTP requests (42-52/min during active play)
- Divergent state (each consumer independently decides when data has changed)
- Race conditions (one consumer receives update before the other)
- No deterministic replay capability for debugging

We need a single, authoritative event stream from the backend to all consumers.

---

## Decision

Introduce an **Event Dispatcher** — a transport-agnostic event dispatch layer in the Flask backend. Currently backed by SSE (Server-Sent Events), designed to support WebSocket or any other transport in the future without changing the dispatch interface.

### Architecture

```
post_snapshot() or equity calc complete
        │
        ▼
EventDispatcher.dispatch(event_type, payload)
        │
        ├──→ SSE handler  (current, /api/events)
        ├──→ WS handler   (reserved, future)
        ├──→ Replay log   (deque, max 10,000 events)
        └──→ Test hook    (mock consumer in unit tests)
```

### Event Types

| Event | Producer | Payload | Consumer |
|-------|----------|---------|----------|
| `table_update` | `post_snapshot()` | Full `_table_view()` or diff | Remote UI (seat grid, board, pot) |
| `engine_update` | `equity_run()` | Equity results {hands, equity%, hand_name} | Engine panel |
| `hand_event` | Hand lifecycle transition | {from, to, hand_id, version} | Sync Inspector, state display |
| `seat_changed` | Seat mutation in snapshot | {seat_no, delta fields} | Remote UI (partial render) |
| `pot_changed` | Pot amount changes | {old, new, delta} | Board bar, pot label |
| `board_changed` | Board cards change | {street, new_cards} | Board render |
| `heartbeat` | Timer (every 25s) | {ts, version} | Keep connection alive, health |

### SSE Implementation

- Endpoint: `GET /api/events`
- Content-Type: `text/event-stream`
- Each event: `event: <type>\ndata: <json>\n\n`
- Client: `new EventSource('/api/events')`
- Fallback: if EventSource disconnects → resume long-poll (`GET /api/table/latest?timeout=25`)

### Why Not Raw SSE as the Only Transport

SSE was recommended in the initial review. We're adding an abstraction layer because:

1. **WebSocket may be needed later** — if we need bidirectional communication (e.g., server requests client state)
2. **Deterministic replay** — the event bus logs all events to a replay buffer; neither raw SSE nor WS provides this
3. **Testability** — a mock transport can be injected in unit tests without starting a server
4. **Swap without rewrite** — frontend imports `EventBus.connect()` not `new EventSource()` — change one factory, not every consumer

---

## Consequences

### Positive
- Single connection replaces two pollers → 93% fewer HTTP requests
- Sub-100ms push latency vs 50ms-25s polling latency
- Deterministic event log enables "replay hand" debugging
- Transport swap requires changing one factory function
- Coexists with existing long-poll (graceful degradation)

### Negative
- SSE is unidirectional (server→client). Commands still need REST POST (acceptable — actions are rare, events are frequent)
- SSE has a browser limit of 6 concurrent connections (we'll use 1)
- Requires `EventSource` polyfill for very old browsers (not in scope — modern Chrome/Edge only)
- Event log buffer consumes memory (~10,000 events × ~500 bytes = ~5MB at peak)

### Tradeoffs
- **Log buffer size:** 10,000 events chosen as balance. At 300ms polling = ~3,300 events/hour/bot. Buffer covers ~3 hours of continuous play per bot. If hand disputes require deeper history, increase to 50,000.
- **Full state vs diff:** Initial implementation dispatches full `_table_view()` for correctness. Phase C adds diff-based events for performance.

---

## Related

- ADR-002: Unified Frontend (consumes these events)
- ADR-003: Hand Lifecycle State Machine (produces hand_event)
- Phase A implementation: EventDispatcher class + /api/events endpoint

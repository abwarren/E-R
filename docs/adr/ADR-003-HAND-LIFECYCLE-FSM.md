# ADR-003: Hand Lifecycle State Machine — Explicit State Transitions

**Status:** ACCEPTED (draft)
**Date:** 2026-07-20
**Driver:** Replace implicit hand detection heuristics with a formal, validated state machine
**Phase:** Phase D

---

## Context

The current system infers hand state from snapshots:

- **Hand start:** Detected by `make_hand_key()` fingerprint (sorted cards hash) or `_detect_new_deal()` (street regression + seat constellation change) or `hand_id` echo from extension
- **Street:** Derived from `board.flop.length` → 0=PREFLOP, 3=FLOP, 3+turn=FLOP with partial, 3+turn+river=RIVER
- **Hand end:** Inferred from board clearing or hand_id change. No explicit "hand complete" event
- **Archiving:** Triggered by hand_key change inside `post_snapshot()` — one function does detection, archiving, AND state reset

This implicit approach has caused every regression in the system's history:

| Regression | Root Cause | Fix |
|------------|-----------|-----|
| REG-001: Oscillation | Scoring-based selection inferred authority incorrectly | `_find_active_bot()` by needs_action |
| REG-002: street=null | `back_to_game` excluded from POKER_ACTIONS | Added it to authority set |
| REG-004 (pre-MVP): Seat/hand collision | Hand detection heuristic conflated with seat assignment | Three-layer model (Identity → Authority → Selection) |

Each fix addresses a symptom, not the root problem: **poker state is never explicitly modelled.**

---

## Decision

Replace implicit hand detection with a formal **finite state machine (FSM)** embedded in the backend.

### States

```
WAITING ──→ SEATED ──→ NEW_HAND ──→ PREFLOP ──→ FLOP ──→ TURN ──→ RIVER ──→ SHOWDOWN ──→ HAND_COMPLETE ──→ ARCHIVED ──→ READY
   ↑                                                                                                                            │
   └────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| State | Meaning | Entry Criteria | Exit Criteria |
|-------|---------|---------------|---------------|
| `WAITING` | No table, no data | Startup or all tables inactive | Snapshot received with valid table_id and seats |
| `SEATED` | Bot seated at table, between hands | Snapshot with seats but no hole cards | Hole cards appear AND pot > 0 |
| `NEW_HAND` | Hand detected, transitioning in | hand_id changes OR deal detected | Board cards appear |
| `PREFLOP` | Hole cards dealt, pre-flop betting | Hole cards visible, pot > 0, board empty | board.flop has 3 cards |
| `FLOP` | Three community cards | board.flop has 3 cards | board.turn is set |
| `TURN` | Fourth community card | board.turn is set | board.river is set |
| `RIVER` | Fifth community card | board.river is set | Showdown detected OR board clears |
| `SHOWDOWN` | Cards shown, winner determined | Action buttons disappear, pot awarded | hand_id changes OR 5s timeout |
| `HAND_COMPLETE` | Hand finished, awaiting archive | Pot awarded, no active actions | Archive written |
| `ARCHIVED` | Hand stored to history | _archive_hand() completed | Next hand detected |
| `READY` | Ready for next hand | Bot seated, waiting for new deal | New hand detected |

### Transition Validation

```python
HAND_STATES = {
    "WAITING":        {"next": {"SEATED", "NEW_HAND"}},
    "SEATED":         {"next": {"NEW_HAND", "WAITING"}},
    "NEW_HAND":       {"next": {"PREFLOP", "WAITING", "HAND_COMPLETE"}},
    "PREFLOP":        {"next": {"FLOP", "WAITING", "HAND_COMPLETE"}},
    "FLOP":           {"next": {"TURN", "RIVER", "WAITING", "HAND_COMPLETE"}},
    "TURN":           {"next": {"RIVER", "WAITING", "HAND_COMPLETE"}},
    "RIVER":          {"next": {"SHOWDOWN", "HAND_COMPLETE", "WAITING"}},
    "SHOWDOWN":       {"next": {"HAND_COMPLETE", "WAITING"}},
    "HAND_COMPLETE":  {"next": {"ARCHIVED", "NEW_HAND", "SEATED"}},
    "ARCHIVED":       {"next": {"READY", "WAITING"}},
    "READY":          {"next": {"NEW_HAND", "SEATED", "WAITING"}},
}
```

### Invalid Transition Handling

If `post_snapshot()` produces a transition not in `HAND_STATES[current]["next"]`:

```python
def validate_transition(current_state, next_state, snapshot):
    allowed = HAND_STATES.get(current_state, {}).get("next", set())
    if next_state not in allowed:
        app.logger.warning(
            "[FSM] Invalid transition %s → %s (hand_id=%s, bot=%s)",
            current_state, next_state, snapshot.get("hand_id","?")[:8], bot_id
        )
        metrics.increment("invalid_transitions")
        return current_state  # Stay in current state, don't silently advance
    return next_state
```

### Where Transitions Are Triggered

The FSM is NOT a separate thread. Transitions are computed inside `post_snapshot()` after structural fields are validated by `is_authoritative_snapshot()`:

```
post_snapshot()
  → is_authoritative_snapshot()?  (gate)
  → determine next_state from board, pot, hole_cards
  → validate_transition(current, next)
  → if valid: table["hand_state"] = next
  → if hand_complete: _archive_hand(), dispatch("hand_event", ...)
  → dispatch("table_update", ...) with new hand_state
```

### Feature Flag: `USE_HAND_FSM=true`

- `false` (default): Existing heuristics (`make_hand_key`, `_detect_new_deal`) run unchanged. State field is populated but unused.
- `true`: FSM is authoritative. Invalid transitions are rejected. `hand_state` field exposed in API response.

---

## Consequences

### Positive
- Every hand lifecycle event is explicit and recorded
- Invalid transitions (PREFLOP→RIVER) are caught and logged, not silently accepted
- `hand_state` in API response lets frontend display exact lifecycle position
- `HAND_COMPLETE` triggers deterministic cleanup — no more "board cleared too early" or "stale cards remain"
- Event sourcing integration: every transition becomes a `hand_event` dispatch
- Debugging: review FSM log to answer "what state was this hand in at time X?"

### Negative
- State machine adds ~60 lines of Python to app.py
- Invalid transition rejection means: if the FSM has a gap (a valid poker transition we forgot to encode), it will reject a real hand. Mitigation: logging + manual override via flag toggle
- The state machine must be kept in sync with game rules (e.g., hand can fold on any street → HAND_COMPLETE must be reachable from PREFLOP/FLOP/TURN/RIVER)

### Edge Cases
- **Hand folds on PREFLOP:** PREFLOP → HAND_COMPLETE (valid, encoded)
- **Walk (everyone folds to BB):** PREFLOP → HAND_COMPLETE (valid)
- **Auto-run twice:** RIVER stays RIVER, no transition (dealer runs second river, board.river replaced — no state change needed)
- **Table breaks mid-hand:** Any state → WAITING (valid from all states — connection loss)
- **Bot sits out mid-hand:** PREFLOP → PREFLOP (hand_state unchanged, status changes in seat)
- **Disconnect/reconnect:** Any state → SEATED (reconnection resumes at seat level)

---

## Related

- ADR-001: Event Bus Architecture (hand_event dispatched on every transition)
- ADR-002: Unified Frontend (hand_state displayed in Sync Inspector)
- Phase D implementation details in `.hermes/plans/unified-engine-remote-sync-v2.md`
- Existing `is_authoritative_snapshot()` in `backend/app.py` (gate for all transitions)

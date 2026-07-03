# AVAILABLE_ACTIONS — Ranked Failure Points

**Date:** 2026-07-03
**Status:** STATIC ANALYSIS COMPLETE — awaiting runtime evidence

## Clarification Confirmed

Extension snapshot root at w4p.js:1430:
```
available_actions: avail,
```
Flask reads at app.py:1288:
```
avail_actions = payload.get('available_actions', [])
_bot_actions[bot_id] = avail_actions
```

The root-level field EXISTS. The `_bot_actions` global store IS populated.

---

## Ranked Failure Points (1 = most likely, 9 = least likely)

| Rank | Category | File:Line | Condition | Mechanism | Runtime Evidence Needed |
|------|----------|-----------|-----------|-----------|------------------------|
| 1 | **Bug** | app.py:643-653 | `_STALE_TTL = 5.0s` | Non-hero controlled seat not refreshed within 5s → classified stale → `available_actions: []` in output | `/api/latest` seat `available_actions` vs `last_seen` age |
| 2 | **Bug** | app.py:1555 | `_TABLE_INACTIVE_TTL = 30s` | No snapshot for 30s → entire table → `waiting` → all state destroyed | `/api/health` snapshot_age |
| 3 | **Design** | remote-w4p.html:869 | `isActive = isHero && acts.length > 0` | Non-hero seats never render action buttons — by design (operator-console gate not implemented) | Remote DOM during live hand |
| 4 | **Race** | app.py:1250-1261 | `existing_bot != bot_id` | Cross-bot restricted merge skips `available_actions` — Bot-A's snapshot doesn't update Bot-B's actions | Which bot sent snapshot vs which seat has actions |
| 5 | **Bug** | app.py:924-954 | `SEAT_TTL = 30s` | Full eviction: `_bot_actions.pop(bot_id)` — bot's action state permanently deleted | Cleanup log: `[CLEANUP] evicted N stale seat(s)` |
| 6 | **Design** | w4p.js:1367 | `isHero ? avail : []` | Extension only sends actions for self-player — non-hero seats always `[]` by design | Extension console during live hand |
| 7 | **Race** | app.py:700-703 | `_bot_actions.get(bot_id)` | Fallback to global store — if bot_id mismatches between snapshot and store, returns `[]` | `bot_id` in snapshot vs `_seat_bots` mapping |
| 8 | **Theory** | w4p.js:1225 | `BTN_SEL` selectors | Selectors don't match current DOM → `avail = []` → no actions scraped (proven working in your session) | Extension console `available_actions` |
| 9 | **Theory** | remote-w4p.html:1022 | `seat.name != null` | Seat dropped from posSeatMap entirely → never rendered → buttons irrelevant | `/api/latest` seat `name` field |

---

## Category Definitions

| Category | Meaning |
|----------|---------|
| **Bug** | Code path that can silently drop data without intention |
| **Design** | Intentional gate that may need surgical adjustment |
| **Race** | Timing-dependent — works correctly under specific conditions, fails under others |
| **Theory** | Statically possible but unlikely to be the active cause |

---

## Runtime Trace Trigger

Monitoring these transitions:

```
Current state:
  snapshot_seq:    626231 (stalled)
  active_tables:   0
  table_state:     waiting

On ANY of:
  snapshot_seq     → increment
  active_tables    → ≥ 1
  table_state      → active (table_id ≠ "waiting")

→ Immediately execute full runtime propagation trace
→ Capture Extension → POST → Flask → API → Remote → Engine
→ Populate the Propagation Matrix with real evidence
```

---

## Propagation Matrix (to be filled by runtime trace)

| Stage | Field Exists | Value | Evidence |
|-------|-------------|-------|----------|
| Extension console | ? | ? | — |
| Snapshot JSON | ? | ? | — |
| POST /api/snapshot | ? | ? | — |
| Flask table_state | ? | ? | — |
| /api/latest response | ? | ? | — |
| Remote Network response | ? | ? | — |
| Remote buildSeatBoxHtml | ? | ? | — |
| Remote DOM | ? | ? | — |

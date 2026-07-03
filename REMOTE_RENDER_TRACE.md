# REMOTE_RENDER_TRACE.md

**Date:** 2026-07-03
**Method:** Captured 30 consecutive /api/latest responses, simulated seatHash() and render decision for each seat

---

## Render Decision Trace (samples 1-30)

Format: `sn: seat=X status stack dealer acts → RENDER/SKIP (changed: fields)`

```
sn 4552: S1 playing  R63.50  D=F  acts=[]             → RENDER (initial)
sn 4552: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4553: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4554: S1 sitting  R59.00  D=T  acts=back_to_game   → RENDER (status,stack,dealer,actions)
sn 4555: S1 playing  R63.50  D=F  acts=[]             → RENDER (status,stack,dealer,actions)
sn 4556: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4556: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4557: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4557: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4559: S1 sitting  R59.00  D=T  acts=back_to_game   → RENDER (status,stack,dealer,actions)
sn 4560: S1 playing  R63.50  D=F  acts=[]             → RENDER (status,stack,dealer,actions)
sn 4560: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4561: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4562: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4563: S1 sitting  R59.00  D=T  acts=back_to_game   → RENDER (status,stack,dealer,actions)
sn 4564: S1 playing  R63.50  D=F  acts=[]             → RENDER (status,stack,dealer,actions)
sn 4565: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4565: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4566: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4567: S1 sitting  R59.00  D=T  acts=back_to_game   → RENDER (status,stack,dealer,actions)
sn 4568: S1 playing  R63.50  D=F  acts=[]             → RENDER (status,stack,dealer,actions)
sn 4569: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4569: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4570: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4570: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4572: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4573: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4573: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4574: S1 playing  R63.50  D=F  acts=[]             → SKIP
sn 4574: S1 playing  R63.50  D=F  acts=[]             → SKIP
```

---

## Summary

| Metric | Value |
|--------|-------|
| Total samples | 30 |
| Renders triggered | 8 (27%) |
| Skips (hash match) | 22 (73%) |
| Renders caused by status toggle | 8 (100% of renders) |
| Renders from gameplay changes | 0 |
| Flicker events | 4 (pairs of RENDER in adjacent snapshots) |

---

## Render Reason Breakdown

Every render (8 total) was caused by the same 4-field change:
```
status:       playing ↔ sitting_out
stack_zar:    63.50 ↔ 59.00
is_dealer:    false ↔ true
available_actions: [] ↔ [back_to_game]
```

The `status` field is the first to change. The other three fields cascade from it (the DOM presents a different view of the seat when the sitting-out class is detected).

---

## Instrumented Remote UI

Diagnostic instrumentation added to `remote-w4p.html` (deployed, SHA `f96f6b64`):
- `window.__DIAG` — global state tracker
- `diagState()` — logs render decisions with changed fields
- Periodic POST to `/diag/render` every 10 render cycles
- Active when Remote UI loads at http://localhost:4000/remote

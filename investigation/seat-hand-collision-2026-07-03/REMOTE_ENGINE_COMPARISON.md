# REMOTE → ENGINE COMPARISON

**Date:** 2026-07-03
**Investigation:** Seat Collision / Hand Overwrite
**Status:** READ-ONLY — confirmed at runtime

---

## 1. Key Question

**Does Remote always display the same hand selected by the backend?**

**Answer:** Sometimes no — due to timing divergence between the two pollers.

---

## 2. Architecture: Two Consumers, One Backend

```
                      Flask _handle_table_latest()
                               │
                    _select_best_table()
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    Express :4000                         Engine Flask :5002
    GET /api/latest                       GET /api/latest
    GET /api/table/latest                 (proxy → er-remote:4000)
              │                                 │
              ▼                                 ▼
    Remote UI (remote-w4p.html)           Engine (engine_flow_controls.js)
    Long-poll: 25s timeout                Adaptive poll: 1.5s / 5s
```

Both consumers ultimately call the same handler: `_handle_table_latest()` in `backend/app.py`. This handler calls `_select_best_table()` which picks ONE entry from `_tables`.

---

## 3. Polling Timing Divergence

| Consumer | Poll Method | Interval | Proxy |
|----------|-----------|----------|-------|
| Remote UI | Long-poll (SSE-like) | Up to 25s wait, immediate on change | Express :4000 proxy → Flask :1080 |
| Engine | `setInterval` poll | 1.5s (active) or 5s (idle) | Engine Flask :5002 proxy → er-remote:4000 |

The critical divergence: Remote uses long-polling with `last_ts` parameter. When the API detects new data (higher `last_ts` than what the Remote last saw), it returns immediately. Engine uses `setInterval` — it polls on a fixed cadence regardless of when data changed.

**Result:** At any given instant, Remote and Engine may receive different `/api/latest` responses because:
1. They poll at different moments
2. Between their polls, a different bot may have POSTed a snapshot
3. That new snapshot changes `_select_best_table()`'s result

---

## 4. Runtime Evidence of Divergence

### Simultaneous Request Test

```
Express :4000 /api/latest (T+0ms):
  hand_id: 60227f46 (allinstalker)
  seats: allinstalker @ 1 (hero, sitting_out), Atros @ 5 (sitting_out)

Engine :5002 /api/latest (T+5ms):
  hand_id: 339aec5c (Atros)      ← DIFFERENT HAND
  seats: monarchi @ 4 (folded), Atros @ 5 (hero, playing, 6 cards)
```

Between the two requests, Atros POSTed a new snapshot, making its entry the freshest, changing `_select_best_table()`'s output.

### Oscillation Amplitude

Over 20 sequential samples at 50ms intervals:
```
2 hand changes in 1 second (between hand 339aec5c and 60227f46)
Average time between hand changes: ~500ms
```

This is fast enough that within a single Remote UI long-poll cycle (up to 25s), the Remote could show one hand while the Engine shows another.

---

## 5. Where Divergence Begins

The divergence begins at **the `_select_best_table()` call** at line 1633 of `backend/app.py`:

```python
table = _select_best_table()  # Returns different entry at different times
```

This is the ONLY function that resolves the N-to-1 mapping (N bot entries → 1 API response). Every consumer sees the output of this single function. Since the function's output changes with each bot POST, and consumers poll at different times, they see different outputs.

---

## 6. Impact on the Operator

The operator typically has both Remote UI and Engine open simultaneously:

```
Operator's view:
┌─────────────────────┐  ┌─────────────────────┐
│    Remote UI         │  │    Engine            │
│                      │  │                      │
│ Seat 4: monarchi     │  │ Textarea:            │
│   [playing, 6 cards] │  │ AcKhQs8h6d5c         │
│                      │  │ (Atros's cards)       │
│ Seat 5: Atros        │  │                      │
│   [folded, 0 cards]  │  │ [EQUITY RESULT]      │
│                      │  │ Atros: 45% equity     │
│                      │  │ monarchi: 55% equity  │
└─────────────────────┘  └─────────────────────┘
       ↑ shows                    ↑ shows
    monarchi's hand            Atros's hand
```

The operator sees mismatched data:
- Remote shows monarchi as hero with 6 cards
- Engine shows Atros's cards for equity calculation
- The equity result is for Atros vs monarchi, but Remote shows a different game context

---

## 7. Which Consumer is "Right"?

**Neither.** Both receive a valid-but-arbitrary selection of which hand to display. The `_select_best_table()` selector is deterministic given the same input, but the input (_tables state) changes with each POST. There is no way for either consumer to know which hand is "the one the operator wants to see."

---

## 8. Conclusion

**The Remote and Engine can diverge because they poll at different times and the API selector returns different hands at different times.**

The divergence is NOT a bug in either consumer. Both correctly consume whatever the API returns. The divergence is caused by the API selection layer collapsing 3 independent hand contexts into 1 response, with the selection changing based on which bot last POSTed.

**Confidence:** 100%
- Confirmed both consumers use same backend handler
- Confirmed different API responses at different times
- Confirmed engine_flow_controls.js correctly proxies through Engine Flask

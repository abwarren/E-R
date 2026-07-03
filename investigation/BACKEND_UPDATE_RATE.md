# BACKEND_UPDATE_RATE.md
## W4P Backend Processing Analysis

**Date:** 2026-07-03

---

## 1. Backend Processing Pipeline

```
POST /api/snapshot (Express :4000 → proxy → Flask :1080)
  ↓
post_snapshot() acquires _store_lock
  ↓
get_or_create_table(table_id, bot_id) → per-bot entry
  ↓
Hand detection + structural field merge + seat merge
  ↓
SSE notify → pushes to connected clients
  ↓
POST response → includes hand_id
  ↓
GET /api/latest (Remote UI long-poll, 25s timeout)
  ↓
_handle_table_latest() → _dedup_latest_by_table()
```

---

## 2. Backend Processing Rate

From 33,420 ACCEPT lines across 9,874 seconds:

| Metric | Value |
|--------|-------|
| Total snapshots processed | 33,420 |
| Processing rate | 3.38/s |
| Average processing time per snapshot | Sub-millisecond (in-memory dict operations under lock) |
| `_store_lock` contention | Low — only serialized at 3.4/s |
| SSE pushes | 1 per snapshot (clients notified on every write) |

### Lock Contention Analysis

With `_store_lock` serializing all writes:
- Average time between lock acquisitions: 295ms
- 73.4% of gaps are < 100ms (burst during interleaving)
- Each write is O(seats) operations on an in-memory dict
- No lock contention observed (writes complete well within 100ms window)

**The backend can easily handle the current snapshot rate.** There is no evidence of processing bottleneck.

---

## 3. table_state Updates

With per-bot isolation (a58a6ee), each bot writes to its own entry:

```
_tables = {
    ("pb_2589955", "Atros"):        { state_version=N, last_ts=T1, ... },
    ("pb_2589955", "monarchi"):     { state_version=M, last_ts=T2, ... },
    ("pb_2589955", "allinstalker"): { state_version=K, last_ts=T3, ... },
}
```

| Metric | Value |
|--------|-------|
| Entries updated per snapshot | 1 (per-bot isolation) |
| state_version increments | 1 per snapshot per entry |
| Cross-entry contamination | None (isolated) |
| Hand resets per entry | Variable (depends on bot's hand cycle) |

### Update Breakdown (per snapshot)

1. Table retrieval: `get_or_create_table(table_id, bot_id)` — O(1) dict access
2. Hand detection: `make_hand_key()` + `_detect_new_deal()` — O(seats) for card enumeration
3. Structural field write: O(1) dict assignment (gated)
4. Seat processing: O(seats) to parse and merge each seat
5. SSE notify: O(1) to push to connected clients
6. State persistence: Async write to `state_snapshot.json`

---

## 4. /api/latest Update Rate

From werkzeug access logs during 00:32:20-00:32:29:
```
GET /api/table/latest?timeout=25&last_ts=... 200
GET /api/table/latest?timeout=25&last_ts=... 200
GET /api/table/latest?timeout=25&last_ts=... 200
... (multiple per second during active periods)
```

| Metric | Value |
|--------|-------|
| /api/latest calls during active period | ~1-3/s (varies with Remote UI long-poll resolution) |
| Long-poll timeout | 25 seconds |
| Immediate response on new data | Yes (SSE-style wake on state change) |
| Response shape | Full `_table_view()` output |

The API responds immediately when new data is available (via the long-poll loop checking `table['last_ts'] > last_ts_seen`). Each response reflects whichever bot entry `_dedup_latest_by_table()` selects.

---

## 5. Render Correlation

```
Snapshot received (POST /api/snapshot, ~3.4/s)
  ↓ ~0ms (in-memory dict write)
Backend mutation (_tables entry updated)
  ↓ ~0-25s (long-poll wakeup threshold)
/api/latest response (Remote UI receives new data)
  ↓ ~16ms (requestAnimationFrame)
Render (diff-based, skipped if JSON identical)
```

| Pipe Segment | Latency |
|-------------|---------|
| POST → backend write | < 1ms |
| Backend write → SSE notify | < 1ms |
| SSE notify → Remote UI wakeup | Depends on long-poll cycle (0-25s) |
| Remote UI receive → render | ~16ms (rAF) |
| Render → DOM update | < 16ms |

**Every snapshot causes a backend write.** With per-bot isolation, each write is to a separate entry. The Remote UI receives the most recent entry (via `_dedup_latest_by_table()`).

**Not every backend write causes a Remote UI render.** The diff check at remote-w4p.html:736 (`json === _lastTableJSON`) skips rendering when the JSON is identical. During oscillation, the JSON IS different (different bot entry → different street/board) → re-render every time.

---

## 6. Multi-Bot Interaction Effect

With 3 bots interleaving:

```
Backend writes:
  Atros entry:        ~1.3 writes/s
  monarchi entry:     ~1.2 writes/s
  allinstalker entry: ~0.9 writes/s
  Total:              ~3.4 writes/s

API responses:
  Returns most recent entry among all three
  If Atros at T+0 (FLOP), allinstalker at T+50ms (PREFLOP), monarchi at T+150ms (FLOP):
    T+60ms API call → allinstalker's PREFLOP entry
    T+200ms API call → monarchi's FLOP entry
    PREFLOP → FLOP → PREFLOP → FLOP ... oscillation
```

The interleaving DOES cause the oscillation, but NOT because of the write rate. It causes oscillation because the API selector picks between entries with DIFFERENT game states. Even if each bot posted at 1/s (instead of 3/s), the API would still alternate — just 3x slower.

---

## 7. Conclusion

**Hypothesis DISPROVEN: The backend is NOT overwhelmed by snapshot rate.**

| Question | Answer |
|----------|--------|
| Does the backend process every snapshot? | ✅ Yes |
| Does every snapshot cause a backend mutation? | ✅ Yes (per-bot entry updated) |
| Does every backend mutation cause a render? | ⚠️ Only when the JSON differs from previous render |
| Is the update rate unsustainable? | ❌ No — 3.4/s is easily handled |
| Is interleaving responsible for oscillation? | ⚠️ Partially — interleaving enables alternation, but the API selector is the actual mechanism |

The backend scales correctly with the current snapshot rate. The oscillation is a semantic issue in the API selection logic, not a throughput issue.

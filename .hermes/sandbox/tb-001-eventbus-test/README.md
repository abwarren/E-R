# TB-001: EventBus Sandbox Tracer Bullet

**Status:** 🟢 COMPLETE — QA Approved
**Date:** 2026-07-20
**Evidence:** `evidence/test_output.log`, `evidence/replay-hand-001.json`, `evidence/replay-all.json`, `evidence/metrics.json`

**Objective:** Prove the transport-agnostic EventDispatcher + SSE push
works end-to-end BEFORE modifying any production code.

## Results

| Test | Result |
|------|--------|
| Server health | ✅ |
| SSE connection + heartbeat | ✅ |
| Hand lifecycle: SEATED→PREFLOP→FLOP→TURN→RIVER→PREFLOP | ✅ |
| SSE table_update events received by client | ✅ (6 events) |
| hand_event dispatch on hand transition | ✅ (1 event) |
| Replay log: all events captured | ✅ (17 events) |
| Replay filtering by hand_id | ✅ (9 events for hand-001) |
| Monotonic version counter | ✅ (1→17 strictly increasing) |
| Idempotent duplicate POST | ✅ (no crash) |
| Metrics endpoint live counters | ✅ (events_dispatched=17) |
| **Total** | **32/32 ✅** |

**Stack exercised:**
- API layer: Flask SSE endpoint (`/api/events`)
- Service layer: `EventDispatcher.dispatch()` 
- Projection: monotonic version counter, replay log
- Consumer: Python test client receiving events via SSE
- Event log: deterministic replay buffer

## Evidence Directory
- `server.py` — standalone sandbox server (can run alongside production)
- `test_client.py` — test harness
- `test_output.log` — captured test run
- `qa-signoff.md` — sign-off

## Run
```bash
cd .hermes/sandbox/tb-001-eventbus-test
python3 server.py &
sleep 1
python3 test_client.py
kill %1
```

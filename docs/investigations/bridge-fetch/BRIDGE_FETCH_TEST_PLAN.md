# BRIDGE_FETCH_TEST_PLAN.md

**Date:** 2026-06-24
**Branch:** `fix/w4p-bridge-fetch`
**Backup:** `w4p.js.before` (1586 lines, SHA256 at patch time)
**Status:** READY — execute after patch applied and extension reloaded

---

## Purpose

Verify that replacing direct `fetch()` with `postMessage → bridge.js → background.js`
works end-to-end with no regressions.

---

## Test Sequence

### A. Extension loads

**How to verify:**
1. Go to `chrome://extensions/`
2. Find "PokerScope W4P"
3. Confirm: enabled toggle is ON
4. Click "Details" → confirm "Loaded from: `/home/wa/projects/poker/E&R/backend/static/ext`"
5. Confirm no errors under "Errors" button

**Pass criteria:** Extension is enabled, loaded from correct path, zero errors.

### B. w4p.js injected

**How to verify:**
1. Navigate to GoldRush poker table
2. Press F12 → Console
3. Look for: `[W4P] ══════════════` ... `v23-hardened`

**Pass criteria:** Banner appears. If banner does NOT appear, injection failed.

### C. No console errors

**How to verify:**
1. After table loads, wait 5 seconds
2. Console → Check for any red messages starting with `Uncaught` from w4p.js scope
3. Specifically check: no `POST http://127.0.0.1:4000/api/snapshot net::ERR_FAILED`
4. Specifically check: no `Access to fetch ... blocked by CORS policy`

**Pass criteria:** Zero PNA/CORS fetch errors. Third-party errors (Meta Pixel, TikTok, etc.) are acceptable.

### D. POST /api/snapshot observed

**How to verify (three methods, pick one):**

**Method 1 — Browser Console:**
```
Look for: [W4P_BRIDGE] RX from MAIN: /snapshot POST
Then:     [W4P-BG] FETCH POST http://127.0.0.1:4000/api/snapshot
Then:     [W4P-BG] FETCH response: 200 OK
Then:     [W4P_BRIDGE] SW response: OK
Then:     [W4P] Connected! seat_no=X token=XXXXXXXX...
```

**Method 2 — Browser Network Tab:**
1. Open DevTools → Network tab
2. Filter: `snapshot`
3. Reload the poker table page
4. Look for POST requests to `/api/snapshot` with status 200

**Method 3 — Backend health:**
```bash
curl -s http://127.0.0.1:4000/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'seq={d.get(\"snapshot_seq\",0)} tables={d.get(\"active_tables\",0)} age={d.get(\"snapshot_age_seconds\",\"?\"):.1f}s')"
```
Wait 5 seconds, run again. `seq` should increment between runs.

**Pass criteria:** At least one snapshot reaches Flask (HTTP 200, seq increments).

### E. Flask receives snapshot

**How to verify:**
```bash
curl -s http://127.0.0.1:4000/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('snapshot_seq',0) > 0 and d.get('active_tables',0) > 0 else 'FAIL')"
```

**Pass criteria:** `ok` printed (seq > 0 AND active_tables > 0).

### F. snapshot_seq increments

**How to verify:**
```bash
# Record current seq
SEQ1=$(curl -s http://127.0.0.1:4000/api/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('snapshot_seq',0))")
echo "seq1=$SEQ1"
sleep 10
SEQ2=$(curl -s http://127.0.0.1:4000/api/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('snapshot_seq',0))")
echo "seq2=$SEQ2"
if [ "$SEQ2" -gt "$SEQ1" ]; then echo "PASS: seq incremented $SEQ1 → $SEQ2"; else echo "FAIL: seq did not increment"; fi
```

**Pass criteria:** `SEQ2 > SEQ1`.

### G. /api/table/latest populated

**How to verify:**
```bash
curl -s http://127.0.0.1:4000/api/table/latest | python3 -c "
import sys,json
d=json.load(sys.stdin)
t=d.get('table',{})
seats=t.get('seats',[])
occupied=[s for s in seats if s.get('name')]
print(f'table_id={t.get(\"table_id\",\"?\")} street={t.get(\"street\",\"?\")} occupied={len(occupied)}/{len(seats)}')
if occupied: 
    for s in occupied:
        print(f'  seat {s[\"seat_no\"]}: {s[\"name\"]} hero={s.get(\"is_hero\")} cards={s.get(\"hole_cards\",[])} actions={s.get(\"available_actions\",[])}')
else:
    print('  NO OCCUPIED SEATS')
"
```

**Pass criteria:** At least one seat has a name. Table ID matches the GoldRush table.

### H. Command polling still works

**How to verify:**
```bash
# Queue a command to the hero seat
curl -s -X POST http://127.0.0.1:4000/api/commands/queue \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: 03622c896cfbeacdfc537e9434f9ddc5' \
  -d '{"table_id":"pb_2589954","seat_no":1,"action":"check","amount":0}' | python3 -m json.tool

# Browser console should show:
# [W4P] Received command: check
```

**Pass criteria:** Queue endpoint returns 200. Browser console shows command received.
(Manual test — requires browser console open during test.)

### I. Command ACK still works

**How to verify:**
```bash
# After command is executed, check backend for cleared commands
curl -s http://127.0.0.1:4000/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'pending_cmds={d.get(\"pending_cmds\",0)}')"
```

**Pass criteria:** `pending_cmds` returns to 0 after command is executed and ACKed.
(Manual test — timing-dependent on browser processing the command.)

---

## Rollback Procedure

If any test fails:

```bash
# 1. Restore original
cp /home/wa/projects/poker/E&R/backend/static/ext/w4p.js.before \
   /home/wa/projects/poker/E&R/backend/static/ext/w4p.js

# 2. Reload extension
# chrome://extensions → PokerScope W4P → Reload ↻

# 3. Verify PNA errors return
# Open GoldRush table → F12 → Check for:
# "Access to fetch at 'http://127.0.0.1:4000/api/snapshot' ... blocked by CORS policy"
# This confirms the original behavior is restored.
```

---

## Quick Validation (Single Command)

After extension reloaded and on poker table page:

```bash
# Wait 15 seconds for snapshots to accumulate, then check
sleep 15 && curl -s http://127.0.0.1:4000/api/health | python3 -c "
import sys,json
d=json.load(sys.stdin)
tests={
  'backend_alive': d.get('ok',False),
  'seq_positive': d.get('snapshot_seq',0) > 0,
  'tables_active': d.get('active_tables',0) > 0,
  'buffer_has_data': d.get('buffer_has_data',False),
  'age_recent': d.get('snapshot_age_seconds',999) < 60 or d.get('snapshot_age_seconds') is None
}
for name, passed in tests.items():
    print(f'  {\"PASS\" if passed else \"FAIL\"}  {name}')
all_pass = all(tests.values())
print(f'\\n{\"ALL TESTS PASSED\" if all_pass else \"SOME TESTS FAILED\"}')
print(f'seq={d[\"snapshot_seq\"]} tables={d[\"active_tables\"]} age={d.get(\"snapshot_age_seconds\",\"?\")}')
"
```

**Expected output when working:**
```
  PASS  backend_alive
  PASS  seq_positive
  PASS  tables_active
  PASS  buffer_has_data
  PASS  age_recent

ALL TESTS PASSED
seq=42 tables=1 age=0.5
```

---

## Test Order

1. Apply patch → reload extension
2. Run Test A (extension loads)
3. Navigate to GoldRush table
4. Run Test B (w4p injected)
5. Wait 5 seconds
6. Run Test C (no errors)
7. Run Test D (snapshot observed)
8. If D passes, run Quick Validation
9. Run Test E (Flask receives)
10. Run Test F (seq increments)
11. Run Test G (table populated)
12. (Manual) Run Test H (command polling)
13. (Manual) Run Test I (command ACK)

Tests H and I require browser console interaction and are manual.

**If any test between A-F fails:** Rollback immediately. Do not proceed.
**If A-F passes but G fails:** Investigate table_id mapping. Not a relay issue.
**If H or I fails:** Investigate command polling path separately. Not a relay issue
  (both go through the same bridgeFetch function).

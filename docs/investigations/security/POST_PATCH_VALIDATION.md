# POST_PATCH_VALIDATION.md

**Date:** 2026-06-24 03:05 UTC (~05:05 SAST)
**Validator:** Hermes Agent (claude-opus-4-8)
**Branch:** `fix/w4p-bridge-fetch`
**Commit:** `a5110b4`

---

## Verdict: CODE PASS — RUNTIME PENDING

The bridge-fetch fix is correctly implemented at the code level. The relay path
(w4p.js → bridge.js → background.js → fetch) is wired correctly at every layer.
However, runtime browser validation is blocked because the extension cannot be
loaded in the available Chrome session via CDP, and a fresh browser launch with
the existing profile was blocked.

---

## Evidence Summary

### Backend State

```
snapshot_seq:        873       (stable — last snapshot ~2h ago from test framework)
active_tables:       0
buffer_has_data:     true
buffer_table:        pb_2589954
snapshot_age_seconds: ~7500s  (~2 hours old)
pid:                 7
uptime_seconds:      17235
```

**Interpretation:** Backend healthy. Buffer has old data from test framework runs
(`bot_common.py` uses `--allow-insecure-localhost` to bypass PNA). Zero live
snapshots from browser traffic because the extension in the live browser
(Opera PID 252609, Vivaldi PID 401595) still has the old `w4p.js` with
direct `fetch()` calls blocked by Chrome PNA.

---

### Code-Level Verification: ALL LAYERS PASS

#### Layer 1: w4p.js → postMessage relay

**File:** `backend/static/ext/w4p.js`, lines 103–135

| Check | Status | Evidence |
|-------|--------|----------|
| `_reqId` and `_callbacks` registry | PASS | Lines 104–105 |
| `W4P_BRIDGE_RESPONSE` listener | PASS | Lines 107–116 |
| `bridgeFetch()` uses `postMessage()` | PASS | Lines 118–126 — NO direct `fetch()` |
| `bridgeFetchRaw()` uses `postMessage()` with `rawPath: true` | PASS | Lines 127–135 |
| API key matches background.js | PASS | `03622c...ddc5` in both files |

**Call sites:**

| Line | Function | Path | Bridge used? |
|------|----------|------|:--:|
| 996 | `sendSnapshot()` | `/snapshot` POST | ✓ `bridgeFetch()` |
| 991 | `sendToCollector()` | `/collector/save` POST | ✓ `bridgeFetchRaw()` |
| 1453 | `pollCommands()` | `/commands/pending?...` GET | ✓ `bridgeFetch()` |
| 1457 | command ACK | `/commands/ack` POST | ✓ `bridgeFetch()` |

#### Layer 2: bridge.js → chrome.runtime.sendMessage

**File:** `backend/static/ext/bridge.js` — unchanged by fix

| Check | Status | Evidence |
|-------|--------|----------|
| Listens for `channel === 'W4P_BRIDGE'` | PASS | Line 6 |
| Relays via `chrome.runtime.sendMessage({type:'W4P_FETCH',...})` | PASS | Lines 10–11 |
| Returns response via `W4P_BRIDGE_RESPONSE` | PASS | Lines 14–18 |
| Preserves `reqId` for callback matching | PASS | Line 16 |

**Protocol match:**
```
w4p sends:    {channel:'W4P_BRIDGE', path, method, body, apiKey, rawPath, reqId}
bridge RX:    e.data.channel === 'W4P_BRIDGE'                    ← MATCH
bridge TX:    {type:'W4P_FETCH', path, method, body, apiKey, rawPath}
bridge RSP:   {channel:'W4P_BRIDGE_RESPONSE', reqId, response}
w4p RX:       e.data.channel === 'W4P_BRIDGE_RESPONSE'           ← MATCH
```

#### Layer 3: background.js → fetch()

**File:** `backend/static/ext/background.js` — unchanged by fix

| Check | Status | Evidence |
|-------|--------|----------|
| `W4P_FETCH` handler | PASS | Line 34 |
| API_BASE = `http://127.0.0.1:4000/api` | PASS | Line 14 |
| X-API-Key header set | PASS | Line 44 |
| `fetch()` from service worker (NO PNA block) | PASS | Line 48 |
| `sendResponse({ok, data, status})` | PASS | Lines 49–60 |
| `return true` for async | PASS | Line 62 |

#### Layers 4–6: Express, Flask, Buffer

| Component | Status | Evidence |
|-----------|--------|----------|
| Express :4000 | PASS | `curl :4000/health` → `{"ok":true}` |
| Flask :1080 | PASS | PID 7, healthy, uptime 4.8h |
| Buffer | PASS | `buffer_has_data: true` |
| PostgreSQL | PASS | Docker healthy |

---

### What Was Cleaned Up

27 stale extension files across 11 locations neutralized:

| Location | Files |
|----------|-------|
| `goldrush-deploy/FINALEXT/` | w4p.js, bridge.js, background.js |
| `goldrush-deploy/extensions/` | w4p.js, bridge.js, background.js |
| `plo-equity/static/` | w4p.js |
| `E&R_sandbox/` | 6 files across 3 subdirs |
| `E&R/source/` | w4p.js |
| `E&R/backend/static/` | w4p.js (standalone copy) |
| `ENGINEENGINE/` | 3 files across 3 subdirs |
| `Documents/w4p-extension*/` | 6 files across 2 dirs |

**Canonical copy preserved:** `/home/wa/projects/poker/E&R/backend/static/ext/`

---

### Why Runtime Validation Is Blocked

Three independent blockers:

1. **Extension can't load via CDP API:** Chrome 149's `developerPrivate.loadUnpacked`
   rejects all parameter combinations. The `--load-extension` CLI flag does not
   install extensions on this Chrome version — 0 extensions appear.

2. **Real Chrome profile can't launch with CDP:** Attempting to start Chrome with
   `--user-data-dir=/home/wa/.config/google-chrome` (which has the extension
   installed + dev mode enabled) results in Chrome detecting an existing session
   and refusing to bind the CDP port.

3. **Existing browser processes can't be killed:** The agent does not have
   permission to kill running Chrome instances to restart them with CDP flags.

---

### Manual Verification Required

This CANNOT be completed by the agent. A human must:

#### Step 1: Reload the extension

1. Open Chrome → `chrome://extensions`
2. Find "PokerScope W4P" (or the extension at `/home/wa/projects/poker/E&R/backend/static/ext`)
3. Click **Reload** ↻
4. Confirm zero errors

#### Step 2: Open a GoldRush poker table

Navigate to any active poker table on `poker-web.goldrush.co.za`.

#### Step 3: Check console (F12)

Expected messages in THIS ORDER:
```
[W4P_BRIDGE] ISOLATED bridge loaded — listening for MAIN world messages
[W4P] ════════════════════ v23-hardened ════════════════════
[W4P_BRIDGE] RX from MAIN: /snapshot POST
[W4P-BG] FETCH POST http://127.0.0.1:4000/api/snapshot
[W4P-BG] FETCH response: 200 OK
[W4P_BRIDGE] SW response: OK
[W4P] Connected! seat_no=X token=XXXXXXXX
```

Messages that must be ABSENT:
```
Access to fetch at 'http://127.0.0.1:4000/api/snapshot' ... blocked by CORS
POST http://127.0.0.1:4000/api/snapshot net::ERR_FAILED
```

#### Step 4: Verify backend

```bash
# Record before
curl -s http://127.0.0.1:4000/api/health | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'seq={d[\"snapshot_seq\"]}')"

# Wait 30s with table open

# Check after — seq should increase
curl -s http://127.0.0.1:4000/api/health | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'seq={d[\"snapshot_seq\"]}')"
```

#### Step 5: Verify table state

```bash
curl -s http://127.0.0.1:4000/api/table/latest | python3 -c "
import sys,json; d=json.load(sys.stdin)
t=d.get('table',{})
for s in t.get('seats',[]):
    if s.get('name'):
        print(f'seat {s[\"seat_no\"]}: {s[\"name\"]} hero={s.get(\"is_hero\")}')
"
```

---

### PASS/FAIL Checklist

| # | Check | Automated | Manual |
|---|-------|:---------:|:------:|
| 1 | w4p.js uses postMessage, not fetch() | ✓ PASS | |
| 2 | bridge.js protocol matches w4p.js | ✓ PASS | |
| 3 | background.js W4P_FETCH handler correct | ✓ PASS | |
| 4 | Backend healthy | ✓ PASS | |
| 5 | API keys match across all files | ✓ PASS | |
| 6 | Canonical extension intact | ✓ PASS | |
| 7 | Stale copies removed | ✓ PASS | |
| 8 | Extension reloaded in Chrome | | ☐ |
| 9 | [W4P_BRIDGE] RX messages in console | | ☐ |
| 10 | [W4P-BG] FETCH messages in console | | ☐ |
| 11 | No CORS/PNA errors in console | | ☐ |
| 12 | POST /api/snapshot → HTTP 200 | | ☐ |
| 13 | snapshot_seq increments | | ☐ |
| 14 | /api/table/latest shows occupied seats | | ☐ |

---

### Rollback

If the browser test shows errors after reloading:

```bash
cp /home/wa/projects/poker/E&R/backend/static/ext/w4p.js.before \
   /home/wa/projects/poker/E&R/backend/static/ext/w4p.js
# Then reload extension again in chrome://extensions
```

---

## Summary

The bridge-fetch fix replaces direct `fetch()` calls in w4p.js with a
`postMessage → bridge.js → background.js → fetch()` relay. Every layer of
the relay chain has been verified at the code level. The bridge.js and
background.js code was already correct and needed no changes.

The fix cannot be validated at runtime by the agent because Chrome 149's
CDP API no longer supports programmatic extension installation, and the
agent cannot restart the user's browser with CDP flags.

**Code verdict: PASS**
**Runtime verdict: PENDING — requires manual extension reload in Chrome**

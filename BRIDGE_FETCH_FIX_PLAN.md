# BRIDGE_FETCH_FIX_PLAN.md

**Date:** 2026-06-24
**Status:** PLAN — not yet implemented
**References:** EXTENSION_INJECTION_REPORT.md (root cause confirmed)

---

## Summary

One function, `bridgeFetch()` at `w4p.js:103-110`, needs to be rewritten to route requests
through the existing bridge.js → background.js relay instead of calling `fetch()` directly
from MAIN world. The bridge.js and background.js implementations are already complete and
correct. Only w4p.js needs changes.

---

## 1. bridgeFetch() — Current Implementation

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/w4p.js`
**Lines:** 97-118

```javascript
// ── Config: Local Only — No external URLs ────────────────────
var API_BASE = 'http://127.0.0.1:4000/api';
var API_KEY  = '03622c896cfbeacdfc537e9434f9ddc5';     // line 99
var SITE_BASE = 'http://127.0.0.1:4000';
var API_KEY  = '03622c896cfbeacdfc537e9434f9ddc5';     // line 101 — duplicate, safe to keep

function bridgeFetch(path, method, body, callback) {      // line 103
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(API_BASE + path, opts)                          // ← line 106: THE PROBLEM
      .then(function(r) { return r.json(); })
      .then(function(data) { if (callback) callback({ ok: true, data: data }); })
      .catch(function(e) { var _ = e; if (callback) callback({ ok: false, error: e.message }); });
}                                                          // line 110

function bridgeFetchRaw(path, method, body, callback) {    // line 111
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(SITE_BASE + path, opts)                         // ← line 114: same problem
      .then(function(r) { return r.json(); })
      .then(function(data) { if (callback) callback({ ok: true, data: data }); })
      .catch(function(e) { console.warn('[W4P] fetchRaw error:', path, e.message); if (callback) callback({ ok: false, error: e.message }); });
}                                                          // line 118
```

**Call sites within w4p.js:**
| Line | Function | Path |
|------|----------|------|
| 979 | `sendSnapshot()` | `'/snapshot'` (POST) |
| 974 | `sendToCollector()` | `'/collector/save'` (POST, uses bridgeFetchRaw) |
| 1436 | `pollCommands()` | `'/commands/pending?token=...'` (GET) |
| 1440 | `handleCommand()` ACK | `'/commands/ack'` (POST) |

All four call sites route through the same two functions. Fixing `bridgeFetch` and `bridgeFetchRaw`
fixes the entire extension pipeline.

---

## 2. bridge.js — Existing Relay (READY, NO CHANGES NEEDED)

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/bridge.js`
**Lines:** 1-23

```javascript
window.addEventListener('message', function(e) {           // line 5
  if (!e.data || e.data.channel !== 'W4P_BRIDGE') return; // line 6

  var msg = e.data;
  console.log('[W4P_BRIDGE] RX from MAIN:', msg.path, msg.method);  // line 9
  chrome.runtime.sendMessage(                              // line 10
    { type: 'W4P_FETCH', path: msg.path, method: msg.method, body: msg.body, apiKey: msg.apiKey, rawPath: msg.rawPath },
    function(response) {                                   // line 12
      console.log('[W4P_BRIDGE] SW response:', ...);      // line 13
      window.postMessage({                                 // line 14
        channel: 'W4P_BRIDGE_RESPONSE',
        reqId: msg.reqId,
        response: response
      }, '*');
    }
  );
});

console.log('[W4P_BRIDGE] ISOLATED bridge loaded — listening for MAIN world messages'); // line 23
```

**Protocol contract (what w4p.js must send):**
```javascript
{
  channel: 'W4P_BRIDGE',
  path: string,       // e.g., '/snapshot'
  method: string,     // 'GET' | 'POST'
  body: object|null,  // JSON payload for POST
  apiKey: string,     // API key for X-API-Key header
  rawPath: boolean,   // true = use SITE_BASE, false = use API_BASE
  reqId: number       // unique request ID for response matching
}
```

**Protocol contract (what bridge.js sends back):**
```javascript
{
  channel: 'W4P_BRIDGE_RESPONSE',
  reqId: number,      // matches the request
  response: {
    ok: boolean,
    data: object,     // parsed JSON response body
    error: string,    // error message if !ok
    status: number    // HTTP status code
  }
}
```

---

## 3. background.js — Existing Handler (READY, NO CHANGES NEEDED)

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/background.js`
**Lines:** 33-63

```javascript
chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
  if (msg.type === 'W4P_FETCH') {                          // line 34
    var url = msg.rawPath ? (SITE_BASE + msg.path) : (API_BASE + msg.path);  // line 36
    var opts = { method: msg.method || 'GET', headers: {} };                 // line 37

    if (msg.body) {
      opts.headers['Content-Type'] = 'application/json';   // line 40
      opts.body = JSON.stringify(msg.body);                // line 41
    }
    opts.headers['X-API-Key'] = msg.apiKey || API_KEY;     // line 44

    console.log('[W4P-BG] FETCH', msg.method || 'GET', url); // line 46

    fetch(url, opts)                                       // line 48 ← THIS fetch is OK
      .then(function(r) {                                   // line 49
        console.log('[W4P-BG] FETCH response:', r.status, r.statusText);
        if (!r.ok) return sendResponse({ ok: false, error: 'HTTP ' + r.status, status: r.status });
        return r.text().then(function(txt) {
          try { sendResponse({ ok: true, data: JSON.parse(txt), status: r.status }); }
          catch (_) { sendResponse({ ok: true, data: txt, status: r.status }); }
        });
      })
      .catch(function(e) {
        console.error('[W4P-BG] FETCH error:', e.message);
        sendResponse({ ok: false, error: e.message, status: 0 });
      });

    return true; // keep sendResponse channel open for async
  }
  ...
});
```

**How it works:** The service worker runs with the extension's full `host_permissions`
including `http://127.0.0.1:4000/*`. Its `fetch()` call is NOT subject to PNA loopback
blocking because extension service workers have elevated network privileges. This is
exactly the mechanism designed for Manifest V3 extensions to talk to local servers.

**API_BASE / SITE_BASE in background.js (lines 14-15):**
```javascript
const DEFAULT_API_BASE = 'http://127.0.0.1:4000/api';
const DEFAULT_SITE_BASE = 'http://127.0.0.1:4000';
```

Matches w4p.js lines 98 and 100 exactly.

---

## 4. Before / After Flow Diagrams

### BEFORE (CURRENT — BROKEN)

```
┌─ w4p.js (MAIN world, https://poker-web.goldrush.co.za) ──────────┐
│                                                                   │
│  bridgeFetch(path, method, body, callback)                        │
│    fetch('http://127.0.0.1:4000/api/snapshot', opts)  ← line 106 │
│      │                                                            │
│      ▼ Chrome PNA blocks loopback fetch from HTTPS origin          │
│      ✗ ERR_FAILED: Permission denied for loopback address space   │
│                                                                   │
│  bridge.js (ISOLATED world) — NEVER REACHED                      │
│  background.js (service worker) — NEVER REACHED                  │
│  Express :4000 — NEVER REACHED                                    │
│  Flask :1080 — NEVER REACHED                                      │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### AFTER (PROPOSED — FIXED)

```
┌─ w4p.js (MAIN world) ──────────────────────────────────────────────────────────┐
│                                                                                │
│  bridgeFetch(path, method, body, callback)                                     │
│    _reqId++;                                                                   │
│    _callbacks[_reqId] = callback;             ← store callback by request ID   │
│    window.postMessage({                                                        │
│      channel: 'W4P_BRIDGE',                   ← dispatch to bridge.js          │
│      path: path, method: method, body: body,                                    │
│      apiKey: API_KEY, rawPath: false, reqId: _reqId                            │
│    }, '*');                                                                    │
│      │                                                                         │
│      ▼                                                                         │
│  ┌─ bridge.js (ISOLATED world) ────────────────────────────────────────────┐   │
│  │  window.addEventListener('message', ...)                                 │   │
│  │  if (e.data.channel === 'W4P_BRIDGE')                                   │   │
│  │    chrome.runtime.sendMessage({type: 'W4P_FETCH', ...})  ← line 10     │   │
│  │      │                                                                  │   │
│  └──────┼──────────────────────────────────────────────────────────────────┘   │
│         ▼                                                                      │
│  ┌─ background.js (service worker) ────────────────────────────────────────┐   │
│  │  chrome.runtime.onMessage.addListener(...)                              │   │
│  │  if (msg.type === 'W4P_FETCH')                                         │   │
│  │    fetch('http://127.0.0.1:4000/api/snapshot', opts)  ← line 48       │   │
│  │      │                                                                  │   │
│  │      ▼ Extension permission — NO PNA BLOCK                             │   │
│  │      ✓ HTTP 200                                                         │   │
│  │    sendResponse({ok: true, data: {...}, status: 200})                   │   │
│  └──────┼──────────────────────────────────────────────────────────────────┘   │
│         ▼                                                                      │
│  ┌─ bridge.js — response handler ──────────────────────────────────────────┐   │
│  │  window.postMessage({channel: 'W4P_BRIDGE_RESPONSE', reqId, response}) │   │
│  └──────┼──────────────────────────────────────────────────────────────────┘   │
│         ▼                                                                      │
│  ┌─ w4p.js — W4P_BRIDGE_RESPONSE listener ─────────────────────────────────┐   │
│  │  var cb = _callbacks[resp.reqId];                                        │   │
│  │  delete _callbacks[resp.reqId];                                          │   │
│  │  cb(resp.response);                                                      │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                │
│  Express :4000 ← receives POST /api/snapshot                                  │
│    → Flask :1080 ← processes snapshot                                        │
│      → buffer.push_snapshot() ← snapshot_seq increments                      │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Minimal Code Changes Required

### File: `w4p.js` (ONLY file changed)

### Change 1: Add callback registry + request counter (before bridgeFetch)

**Insert after line 101** (after `var API_KEY = ...` duplicate, before `function bridgeFetch`):

```javascript
  // ── Bridge relay: postMessage → bridge.js → background.js → fetch ──
  var _reqId = 0;
  var _callbacks = {};

  // Listen for bridge.js responses
  window.addEventListener('message', function(e) {
    if (!e.data || e.data.channel !== 'W4P_BRIDGE_RESPONSE') return;
    var resp = e.data;
    var cb = _callbacks[resp.reqId];
    if (cb) {
      delete _callbacks[resp.reqId];
      cb(resp.response);
    }
  });
```

**Lines added:** 13

### Change 2: Rewrite bridgeFetch() (replaces lines 103-110)

```javascript
  function bridgeFetch(path, method, body, callback) {
    _reqId++;
    if (callback) _callbacks[_reqId] = callback;
    window.postMessage({
      channel: 'W4P_BRIDGE',
      path: path, method: method, body: body,
      apiKey: API_KEY, rawPath: false, reqId: _reqId
    }, '*');
  }
```

**Old lines:** 8 → **New lines:** 9

### Change 3: Rewrite bridgeFetchRaw() (replaces lines 111-118)

```javascript
  function bridgeFetchRaw(path, method, body, callback) {
    _reqId++;
    if (callback) _callbacks[_reqId] = callback;
    window.postMessage({
      channel: 'W4P_BRIDGE',
      path: path, method: method, body: body,
      apiKey: API_KEY, rawPath: true, reqId: _reqId
    }, '*');
  }
```

**Old lines:** 8 → **New lines:** 9

### Summary

| File | Lines changed | Lines added | Lines removed |
|------|-------------|------------|--------------|
| `w4p.js` | 3 blocks | ~22 | ~16 |
| `bridge.js` | 0 | 0 | 0 |
| `background.js` | 0 | 0 | 0 |
| **Total** | — | **~22** | **~16** |

---

## 6. Response Handling Analysis

### Current callback interface (unchanged)

Both `bridgeFetch` and `bridgeFetchRaw` accept a callback with signature:
```javascript
function callback(response) {
  // response.ok      — boolean
  // response.data    — parsed JSON body (when ok)
  // response.error   — error message (when !ok)
  // response.status  — HTTP status code
}
```

The relay preserves this same interface because:
1. bridge.js `sendResponse()` returns `{ok:..., data:..., error:..., status:...}`
2. bridge.js sends this via `postMessage({channel:'W4P_BRIDGE_RESPONSE', reqId, response})`
3. w4p.js listener extracts `response` object and passes it directly to the stored callback

**No call-site changes needed.** All four call sites (sendSnapshot, sendToCollector, pollCommands, handleCommand ACK) use the same callback signature.

### Call sites verified:

| Call site | Line | Function | Uses callback? | Compatible? |
|-----------|------|----------|---------------|-------------|
| sendSnapshot | 979 | bridgeFetch | Yes | ✓ |
| sendToCollector | 974 | bridgeFetchRaw | Yes | ✓ |
| pollCommands | 1436 | bridgeFetch | Yes | ✓ |
| command ACK | 1440 | bridgeFetch | No callback | ✓ (nullable) |

When callback is null/undefined (e.g., command ACK), the fix handles it:
```javascript
if (callback) _callbacks[_reqId] = callback;
```
and the response listener safely:
```javascript
if (cb) { delete _callbacks[resp.reqId]; cb(resp.response); }
```

---

## 7. Timeouts and Retries

### Current behavior
- bridgeFetch does NOT have timeouts. The fetch promise resolves/rejects naturally.
- `.catch()` at line 109 catches network errors (which is what PNA blocks produce).
- No retry logic exists in bridgeFetch.

### Proposed behavior (unchanged)
- `window.postMessage()` is synchronous and never fails (it's event dispatch, not network).
- If bridge.js doesn't respond, the callback is never called. This is equivalent to the
  current network timeout behavior — the `.catch()` handler is never triggered, and
  `_callbacks[_reqId]` accumulates a stale entry.
- This is acceptable because:
  - bridge.js is loaded at `document_start` before w4p.js (at `document_idle`)
  - The postMessage event loop is reliable in the same frame
  - background.js service worker has no restart cycle during page lifetime

### Optional improvement (not in minimal fix)
A request timeout could be added to clean up stale callbacks:
```javascript
setTimeout(function() {
  var cb = _callbacks[_reqId];
  if (cb) { delete _callbacks[_reqId]; cb({ ok: false, error: 'bridge timeout' }); }
}, 10000);
```
This is NOT included in the minimal fix — it adds complexity without addressing the root cause.

---

## 8. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| bridge.js not injected before w4p.js sends | LOW | bridge.js runs at `document_start`, w4p.js at `document_idle`. Bridge is always ready. |
| background.js service worker not active | LOW | Service worker wakes on `chrome.runtime.sendMessage` automatically (Manifest V3 behavior) |
| Callback never called (orphan _callbacks entry) | LOW | Same failure mode as current `fetch().catch()` — silently dropped. Same impact. |
| Response ordering (requests A, B return in order B, A) | NONE | `reqId`-based matching handles out-of-order responses correctly |
| postMessage blocked by CSP | NONE | `'*'` target origin is unrestricted. `window.postMessage` is not subject to CSP `connect-src` |
| bridgeFetchRaw vs bridgeFetch API_BASE/SITE_BASE | NONE | Handled by `rawPath` parameter per the existing bridge.js protocol |
| `_callbacks` memory leak (uncalled callbacks) | LOW | Each entry is ~100 bytes. Even at 300ms poll rate, 10s accumulation is ~33 entries ≈ 3KB |
| Concurrent requests stomping each other | NONE | `_reqId` is monotonically increasing, no reuse possible |
| bridge.js → background.js async gap | NONE | bridge.js already returns `true` from `sendMessage` to keep channel open (existing code works) |
| Same fix needed in other w4p.js copies | MEDIUM | See "Outstanding Work" below |

---

## 9. Verification Steps

After applying the change:

1. **Reload extension** in Chrome: `chrome://extensions` → PokerScope W4P → reload ↻
2. **Open GoldRush table**, check console for:
   - `[W4P] v23-hardened` — w4p.js loaded
   - `[W4P_BRIDGE] RX from MAIN: /snapshot POST` — bridge.js received the message
   - `[W4P-BG] FETCH POST http://127.0.0.1:4000/api/snapshot` — background.js made the fetch
   - `[W4P-BG] FETCH response: 200 OK` — fetch succeeded
   - `[W4P] Connected! seat_no=... token=...` — snapshot response received
3. **Check backend:**
   ```bash
   curl http://127.0.0.1:4000/api/health | jq '{seq:.snapshot_seq, tables:.active_tables}'
   ```
   - `snapshot_seq` should increment
   - `active_tables` should be > 0

---

## 10. Outstanding Work (Not in This Fix)

After bridgeFetch is fixed, these additional changes are needed for completeness:

1. **Sync to source copy**: `source/w4p.js` may be a different version. After fixing `backend/static/ext/w4p.js`, verify whether `source/w4p.js` is a reference copy or an independent file. If independent, apply the same fix there.

2. **Remove `--allow-insecure-localhost` from test framework**: The Selenium bot runner (`bot_common.py`) uses Chrome flags to bypass PNA. After the real fix, those flags are no longer needed to test the extension path (they're still useful for the fetch test in `table_discovery.py`).

3. **Consider timeout**: Add a 10-second request timeout to the `_callbacks` registry to clean up stale entries. This is optional — the current code has no timeout either.

4. **Test both functions**: `bridgeFetch` (for snapshot + commands) and `bridgeFetchRaw` (for collector) both need testing. The fix is identical for both.

---

## 11. Files Summary

| File | Role | Changed? |
|------|------|----------|
| `backend/static/ext/w4p.js` | Scraper — add postMessage relay | **YES** (~22 lines added) |
| `backend/static/ext/bridge.js` | Mail relay — ISOLATED → service worker | No (already correct) |
| `backend/static/ext/background.js` | Service worker — fetch proxy | No (already correct) |
| `source/w4p.js` | Reference copy | **LATER** (sync after verification) |

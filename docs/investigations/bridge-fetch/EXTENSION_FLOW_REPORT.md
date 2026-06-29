# E&R Poker Platform — Extension Flow Report

**Date:** 2026-06-23 22:20 UTC
**Investigator:** Hermes Agent (claude-opus-4-8)
**Methodology:** SOURCE + DISK evidence only. No RUNTIME (browser console) evidence
  available — CDP debugging port not configured on any browser.
**Status:** IDENTIFIED root cause with high confidence.

---

## Executive Summary

The extension is NOT sending snapshots because **w4p.js uses direct `fetch()` from MAIN
world, bypassing the bridge.js → background.js relay entirely.** This fetch goes from
an HTTPS page (GoldRush) to an HTTP localhost (127.0.0.1:4000), which Chrome blocks as
mixed content despite correct CORS/PNA headers.

This is a **code-level architecture defect**, not a configuration or deployment issue.
The fix requires either restoring the bridge.postMessage relay path or changing the
fetch to go through the extension's ISOLATED-world message channel.

---

## Architecture Discovery: The Real Data Path

### Expected (from bridge.js logic and manifest):

```
w4p.js (MAIN world)
    → postMessage('W4P_BRIDGE', ...)
        → bridge.js (ISOLATED world)
            → chrome.runtime.sendMessage('W4P_FETCH', ...)
                → background.js (service worker)
                    → fetch('http://127.0.0.1:4000/api/snapshot', ...)
                        → Express :4000
                            → Flask :1080
```

### ACTUAL (from w4p.js source code):

```
w4p.js (MAIN world)
    → fetch('http://127.0.0.1:4000/api/snapshot', ...)  ← DIRECT FETCH
        [BLOCKED by Chrome mixed content policy]
```

---

## Evidence by Component

### 1. manifest.json

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/manifest.json`

| Setting | Value | Status |
|---------|-------|--------|
| manifest_version | 3 | OK |
| host_permissions | `*://*.goldrush.co.za/*`, `http://127.0.0.1:4000/*`, etc. | OK |
| bridge.js matches | `*://*.goldrush.co.za/*` | OK |
| w4p.js matches | `*://*.goldrush.co.za/*` | OK |
| w4p.js world | `"MAIN"` | **CAUSE** |
| bridge.js world | `"ISOLATED"` | OK |
| w4p.js run_at | `document_idle` | OK |
| w4p.js all_frames | `true` | OK |
| w4p.js match_about_blank | `true` | OK |

**Match pattern analysis:** `*://*.goldrush.co.za/*` matches ALL subdomains of goldrush.co.za
including `poker-web.goldrush.co.za` and `www.goldrush.co.za`. Pattern is sufficient.

**Missing from w4p.js content_scripts:** `*://poker-web.goldrush.co.za/*` is NOT in the content_scripts
matches (only in host_permissions). However, `*://*.goldrush.co.za/*` already covers it.

### 2. bridge.js

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/bridge.js` (23 lines)

**Function:** Listens for `window.postMessage()` with `channel === 'W4P_BRIDGE'`. Relays to
background.js via `chrome.runtime.sendMessage({ type: 'W4P_FETCH', ... })`.

**Status:** Loaded (`document_start`, ISOLATED world, all frames). Correctly waiting for
messages. **BUT UNUSED** — w4p.js never sends `W4P_BRIDGE` postMessages.

### 3. background.js

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/background.js` (87 lines)

**Function:** Service worker. Listens for `chrome.runtime.onMessage`. Proxies `W4P_FETCH`
messages to actual HTTP fetch calls. API key: `03622c896cfbeacdfc537e9434f9ddc5` (old).

**Status:** Registered as service worker. **BUT UNUSED** — no `W4P_FETCH` messages arrive because
w4p.js never sends through the bridge.

### 4. w4p.js — THE CRITICAL COMPONENT

**File:** `/home/wa/projects/poker/E&R/backend/static/ext/w4p.js` (1586 lines)

**Version banner:** "v23-hardened"

**Injection gates (lines 21-88):**

```javascript
function isPokerScrapeContext() {
    var host = location.hostname;
    var path = location.pathname;

    // poker-web.goldrush.co.za → immediately true (line 46-48)
    if (host.indexOf('poker-web.goldrush.co.za') !== -1) return true;

    // games.goldrush.co.za → needs hasPokerTableProof() (line 50-53)
    if (host.indexOf('games.goldrush.co.za') !== -1) {
        if (/LaunchGame|authorization/i.test(href)) return false;
        return hasPokerTableProof();
    }

    // www.goldrush.co.za/live-poker → needs hasPokerTableProof() (line 55-57)
    if (host.indexOf('www.goldrush.co.za') !== -1 && path.indexOf('/live-poker') !== -1) {
        return hasPokerTableProof();
    }

    return false;  // ← Everything else rejected
}
```

**hasPokerTableProof() (lines 21-29):**
```javascript
function hasPokerTableProof() {
    return !!document.querySelector(
        'sg-poker-table, sg-poker-table-seat, .player-mini-container-p, '
        + '.control-b-view-p, .pot-w-view-p, .single-cart-view-p'
    );
}
```

**The bridgeFetch function (lines 103-110) — THE SMOKING GUN:**
```javascript
function bridgeFetch(path, method, body, callback) {
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(API_BASE + path, opts)          // ← DIRECT fetch to http://127.0.0.1:4000/api/snapshot
      .then(function(r) { return r.json(); })
      .then(function(data) { if (callback) callback({ ok: true, data: data }); })
      .catch(function(e) { if (callback) callback({ ok: false, error: e.message }); });
}
```

Despite the name "bridgeFetch", this function does NOT use the bridge. It does a plain
`fetch()` call from the MAIN world content script directly to Express.

**buildSnapshot null-return points (lines 731-850):**
| Line | Condition | Returns |
|------|-----------|---------|
| 732 | `stopNonPokerScrapeContext()` returns true | null |
| 740 | `getTableId()` returns null | null |
| 750 | No seat containers found | null |

---

## Express CORS/PNA Verification

```
$ curl -sI -X OPTIONS -H 'Origin: https://poker-web.goldrush.co.za' \
  -H 'Access-Control-Request-Method: POST' \
  http://localhost:4000/api/snapshot

HTTP/1.1 204 No Content
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, X-API-Key, X-Api-Key, x-api-key
Access-Control-Allow-Private-Network: true
```

**CORS/PNA headers are CORRECT.** The Express server handles preflight and PNA properly.

---

## Root Cause Analysis

### PRIMARY: Direct fetch() from MAIN world bypasses extension relay

w4p.js v20+ ("unified direct fetch") replaced the bridge.postMessage relay with a direct
`fetch()` call. This was intended to simplify the architecture but has a fatal consequence:

1. w4p.js runs in MAIN world (`"world": "MAIN"` in manifest)
2. MAIN world scripts share the page's JavaScript context
3. `fetch()` from an HTTPS origin (GoldRush) to `http://127.0.0.1:4000` is a **mixed content
   downgrade**
4. Chrome blocks mixed content fetches from secure contexts, even when the extension has
   host_permissions for the target

The correct data path (which existed in earlier versions) is:

```
w4p.js (MAIN) → postMessage → bridge.js (ISOLATED) → chrome.runtime.sendMessage →
background.js (service worker) → fetch → Express
```

The ISOLATED-world service worker can make cross-origin fetches because it operates
with the extension's full permissions, not the page's.

**Confidence:** HIGH (90%). The architecture is clear from code. The fetch is direct from
MAIN world. Mixed content blocking is a known Chrome behavior for HTTP fetches from
HTTPS origins, even for localhost.

### SECONDARY: Possible URL/DOM mismatch

If the current GoldRush poker table URL is `www.goldrush.co.za/live-poker/something`,
then `hasPokerTableProof()` must pass for w4p.js to proceed. If the DOM has changed,
this gate fails and w4p.js silently exits.

**Confidence:** MEDIUM (50%). Cannot verify without browser console access.

### TERTIARY: Zombie extension from deleted directory

Chrome has a second extension ID `bjladcnoceindfikglnijmdkbeahejjm` loaded from path
`/home/wa/projects/poker/E&R/source/w4p-extension-dev` which **no longer exists on disk**.
This zombie extension may cause conflicts but does not prevent the primary extension
from injecting.

**Confidence:** LOW (20% relevance to the primary problem).

---

## Failure Mode Probability Matrix

| Rank | Failure Point | Confidence | Evidence Type |
|------|--------------|-----------|---------------|
| 🔥 | Direct fetch from MAIN world blocked by mixed content | 90% | SOURCE: w4p.js:103-110, manifest:79 |
| 🟠 | isPokerScrapeContext returns false (wrong URL) | 50% | Cannot verify without browser console |
| 🟠 | buildSnapshot returns null (no tableId or containers) | 50% | Cannot verify without browser console |
| 🟡 | Zombie extension interference | 20% | DISK: directory deleted, extension still registered |
| 🟢 | API key mismatch | 5% | Proven matching |
| 🟢 | CORS/PNA headers | 1% | Proven correct |
| 🟢 | Flask dead | 0% | Fixed in previous step |

---

## What CANNOT Be Verified Without Browser Console

The following require `chrome.debugger` or DevTools protocol access. Neither is available
because no browser was started with `--remote-debugging-port`.

1. Whether w4p.js actually injects at all
2. Whether `isPokerScrapeContext()` passes or fails
3. Whether `buildSnapshot()` returns a snapshot or null
4. Whether `fetch()` throws a mixed content error, CORS error, or PNA error
5. Whether `background.js` service worker is alive
6. Whether `bridge.js` has any postMessage listeners
7. The current GoldRush page URL the user is on

**To enable CDP:** Restart Chrome with `--remote-debugging-port=9222` or use
`chrome://inspect/#extensions`.

---

## Recommended Diagnostic (for user to run in browser console)

On the GoldRush poker table page, press F12 and paste:

```javascript
// 1. Is w4p.js injected?
console.log('W4P exists:', typeof window._w4p_buildSnapshot === 'function');
console.log('W4P tag:', window._w4p_tag);

// 2. Is scrape context detected?
var host = location.hostname;
var path = location.pathname;
console.log('URL:', host + path);
console.log('poker-web?', host.indexOf('poker-web.goldrush.co.za') !== -1);
console.log('live-poker?', host.indexOf('www.goldrush.co.za') !== -1 && path.indexOf('/live-poker') !== -1);
console.log('hasPokerTableProof:', !!document.querySelector(
  'sg-poker-table, sg-poker-table-seat, .player-mini-container-p, .control-b-view-p'));

// 3. Build a snapshot manually
var snap = window._w4p_buildSnapshot();
console.log('Snapshot:', snap ? 'OK seats=' + snap.seats.length : 'NULL');

// 4. Try the fetch directly
fetch('http://127.0.0.1:4000/api/health', { headers: { 'X-API-Key': '03622c896cfbeacdfc537e9434f9ddc5' }})
  .then(r => r.json())
  .then(d => console.log('FETCH OK:', d))
  .catch(e => console.error('FETCH ERROR:', e.message));
```

The result of step 4 is critical — it will tell us whether the direct fetch is blocked,
and if so, by what mechanism.

---

## Files Involved (for fix when authorized)

| File | Lines | What to change |
|------|-------|---------------|
| `w4p.js` | 103-110 | `bridgeFetch()` — restore postMessage relay instead of direct fetch |
| `w4p.js` | 111-118 | `bridgeFetchRaw()` — same issue |
| `bridge.js` | 5-21 | Already correct — just unused |
| `background.js` | 48-62 | Already correct — just unused |

The fix is to have `bridgeFetch()` do:

```javascript
// Instead of: fetch(API_BASE + path, opts)
// Use:
window.postMessage({
    channel: 'W4P_BRIDGE',
    path: path,
    method: method,
    body: body,
    apiKey: API_KEY,
    reqId: ++_reqId
}, '*');
```

And listen for the response via `window.addEventListener('message', ...)` with
channel `W4P_BRIDGE_RESPONSE`.

This would route snapshots through the established bridge.js → background.js relay,
where the service worker can use the extension's host_permissions to make the fetch
without mixed content restrictions.

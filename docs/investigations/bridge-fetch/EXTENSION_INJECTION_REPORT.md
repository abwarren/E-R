# E&R Extension Injection Report

**Date:** 2026-06-24 ~01:15 SAST (2026-06-23 23:15 UTC)
**Source:** Runtime browser console from `poker-web.goldrush.co.za/1875356/.../tbl/2589954`
**Evidence Tier:** RUNTIME — authoritative over SOURCE and DISK
**Methodology:** Cross-reference source code with live console output. No code changes.

---

## STAGE 1: manifest.json — Content Script Matching

### 1.1 content_scripts.matches

**w4p.js match patterns (manifest.json:63-72):**
```
*://*.pokerbet.co.za/*
*://*.goldrush.co.za/*
*://*.goldrushnation.com/*
*://*.skillgames-bc.com/*
*://*.skillgames.com/*
*://*.skillgames.co.za/*
*://*.betconstruct.com/*
```

**bridge.js match patterns (manifest.json:46-53):**
```
*://*.pokerbet.co.za/*
*://*.goldrush.co.za/*
*://*.goldrushnation.com/*
*://*.skillgames-bc.com/*
*://*.skillgames.com/*
*://*.skillgames.co.za/*
*://*.betconstruct.com/*
```

**Actual URL:** `https://poker-web.goldrush.co.za/1875356/#/product/3/3/cash-cat/1/cash/1147/tbl/2589954`

| Pattern | Matches poker-web.goldrush.co.za? |
|---------|-----------------------------------|
| `*://*.goldrush.co.za/*` | YES — `poker-web` is a subdomain of `goldrush.co.za` |
| `*://poker-web.goldrush.co.za/*` | YES — exact match in `host_permissions` |
| `*://*.goldrushnation.com/*` | NO (different domain) |

**VERDICT: PASS** — `*://*.goldrush.co.za/*` covers all subdomains including `poker-web`.

### 1.2 host_permissions

```
*://*.goldrush.co.za/*                   ← present
*://poker-web.goldrush.co.za/*           ← present (explicit)
http://127.0.0.1:4000/*                  ← present
http://127.0.0.1:1080/*                  ← present
http://localhost:1080/*                  ← present
```

**VERDICT: PASS** — All required host permissions are declared.

### 1.3 permissions

```
["storage"]
```

**VERDICT: PASS** — `storage` is sufficient for `chrome.storage.sync` used by background.js.

### 1.4 w4p.js world assignment

```json
"world": "MAIN"
```

**VERDICT: PASS (with consequence)** — w4p.js runs in MAIN world as intended, giving it DOM access. But this is also what makes the direct `fetch()` call subject to PNA loopback blocking. ISOLATED-world scripts can use `chrome.runtime.sendMessage` without PNA restrictions.

---

## STAGE 2: background.js — Service Worker

### 2.1 Startup

Console evidence: **None seen.** No errors from background.js.

Source code check: `background.js:87` logs `[W4P-BG] Service worker loaded.`. No startup exceptions in code.

### 2.2 Listeners registered

`background.js:33` — `chrome.runtime.onMessage.addListener(...)` handles:
- `W4P_FETCH` (lines 34-63): proxies `fetch()` calls with `X-API-Key` header
- `W4P_SET_CONFIG` (lines 66-77): updates `API_BASE` / `SITE_BASE`
- `W4P_GET_CONFIG` (lines 81-84): returns current config

**VERDICT: PASS** — Service worker structure is correct. Listeners are registered.

### 2.3 Are any messages arriving?

Console evidence: **Zero** `[W4P-BG]` log lines in the console output. No `W4P_FETCH` messages are being sent to the service worker, because the message relay chain is never initiated (see Stage 5).

**VERDICT: PASS (code) / UNUSED (runtime)** — The service worker is ready but idle.

---

## STAGE 3: bridge.js — ISOLATED World Relay

### 3.1 Injection confirmed

Console evidence:
```
[W4P_BRIDGE] ISOLATED bridge loaded — listening for MAIN world messages
```

This line appears at `bridge.js:23`:
```javascript
console.log('[W4P_BRIDGE] ISOLATED bridge loaded — listening for MAIN world messages');
```

**VERDICT: PASS** — bridge.js is injected and executed successfully.

### 3.2 Listener registered

`bridge.js:5` — `window.addEventListener('message', ...)` filters for:
```javascript
e.data.channel === 'W4P_BRIDGE'
```

On match (`bridge.js:8-20`):
1. Logs `[W4P_BRIDGE] RX from MAIN: ...`
2. Calls `chrome.runtime.sendMessage({type:'W4P_FETCH', ...})`
3. On response, posts back via `window.postMessage({channel:'W4P_BRIDGE_RESPONSE', ...})`

**VERDICT: PASS** — Listener exists and is correct.

### 3.3 Are any messages arriving?

Console evidence: **Zero** `[W4P_BRIDGE] RX from MAIN:` log lines. The listener is listening but nothing is sending to it. The `W4P_BRIDGE` channel on `window.postMessage` has zero messages.

**VERDICT: PASS (code) / UNUSED (runtime)** — bridge.js is waiting but unreachable.

---

## STAGE 4: w4p.js — MAIN World Scraper

### 4.1 Injection confirmed

Console evidence:
```
[W4P] ═══════════════════════════════════════════════
[W4P] v23-hardened | built=2026-04-26T02:30:00Z | session=w4p_1782256523795_70rjyf
[W4P] guards: dup-cmd, cooldown=800ms, preset-cd=1500ms
[W4P] polling: hero=300ms cmd=150ms cashout-hyper=75ms
[W4P] API: http://127.0.0.1:4000/api | rollback: w4p.js.v22-stable.bak
[W4P] ═══════════════════════════════════════════════
```

`w4p.js` line ~1577 — startup banner. IIFE executed successfully.

**VERDICT: PASS** — w4p.js injected and executed.

### 4.2 URL guard: isPokerScrapeContext()

Source: `w4p.js:46-48`:
```javascript
if (host.indexOf('poker-web.goldrush.co.za') !== -1) {
    return true;
}
```

Console evidence: The `hostname` is `poker-web.goldrush.co.za`. The guard passes unconditionally — no DOM proof needed for this host.

**VERDICT: PASS** — Context detection passed. Script continues past `w4p.js:88`.

### 4.3 DOM scraping: buildSnapshot()

**Seat containers found:**
```
[W4P] no seat containers     ← initial attempt failed, retried
[W4P][FRAME-DIAG] ...
[W4P][CTX] url=.../tbl/2589954 | doc.title=SkillGames | inIframe=true | iframes=0
[W4P][VALID] hero=Y active=false | selectors: NONE | .control-b-view-p=0
```

Then later (after page finished loading):
```
[W4P][VALID] hero=Y active=true | selectors: check[V],bet[V] | .control-b-view-p=2
```

**VERDICT: PASS** — DOM scrapes successfully after page load settles. Hero found, buttons detected.

### 4.4 window._w4p_buildSnapshot

Source: `w4p.js:1552`:
```javascript
window._w4p_buildSnapshot = buildSnapshot;
```

Console evidence: Tick loop calls `buildSnapshot()` via `w4p.js:1486` — it returns a valid snapshot (not null). The snapshot contains `seats`, `hero`, `bot_id`, `available_actions`.

**VERDICT: PASS** — `_w4p_buildSnapshot` exists and returns valid data.

### 4.5 No runtime exceptions

Console evidence: No `Uncaught TypeError`, `Uncaught ReferenceError` from w4p.js scope. The only exceptions are third-party (Angular `openType` destructure, Meta Pixel, TikTok pixel — all external).

**VERDICT: PASS** — w4p.js runs without exceptions.

---

## STAGE 5: Message Flow — Send Path

### 5.1 w4p.js → bridge.js

Source: `w4p.js:103-110`:
```javascript
function bridgeFetch(path, method, body, callback) {
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(API_BASE + path, opts)       // ← DIRECT FETCH, no postMessage
      .then(function(r) { return r.json(); })
      .then(function(data) { if (callback) callback({ ok: true, data: data }); })
      .catch(function(e) { var _ = e; if (callback) callback({ ok: false, error: e.message }); });
}
```

**This is where the pipeline breaks.** The function is named `bridgeFetch` but does NOT use the bridge. It calls `fetch()` directly from the MAIN world.

Console evidence:
```
Access to fetch at 'http://127.0.0.1:4000/api/snapshot'
from origin 'https://poker-web.goldrush.co.za'
has been blocked by CORS policy:
Permission was denied for this request to access the `loopback` address space.

POST http://127.0.0.1:4000/api/snapshot net::ERR_FAILED
```

Stack trace from console:
```
bridgeFetch @ w4p.js:106       ← fetch(API_BASE + path, opts)  BLOCKED
sendSnapshot @ w4p.js:979      ← bridgeFetch('/snapshot', ...)
tick @ w4p.js:1524             ← sendSnapshot(snap)
```

**VERDICT: FAIL** — First failing stage. w4p.js never sends any message to bridge.js.

### 5.2 bridge.js → background.js

**Cannot verify** — Stage 5.1 must pass first. bridge.js never receives a `W4P_BRIDGE` postMessage.

### 5.3 background.js → Flask

**Cannot verify** — Stage 5.1 must pass first. background.js never receives a `W4P_FETCH` message.

---

## What EXISTS but is NEVER USED

The correct relay path is fully implemented in `bridge.js` + `background.js`:

```
w4p.js (MAIN)
  → window.postMessage({channel:'W4P_BRIDGE', ...})     ← MISSING from w4p.js
    → bridge.js (ISOLATED, line 5)
      → chrome.runtime.sendMessage({type:'W4P_FETCH', ...})  ← bridge.js:10
        → background.js (service worker, line 33)
          → fetch(url, opts) with extension permissions      ← background.js:48
            → Express :4000 → Flask :1080
```

But w4p.js v20 replaced this relay with a direct `fetch()` call at line 106. The file header (`w4p.js:3-4`) documents this decision:

> "v20: unified direct fetch — same file works as extension AND standalone (no bridge.js needed)"

The "unified" approach broke the extension path because MAIN-world `fetch()` from an HTTPS origin to `http://127.0.0.1` is blocked by Chrome's Private Network Access (PNA) policy.

---

## Failure Analysis by Stage

```
STAGE 1: manifest.json              PASS  ✓
STAGE 2: background.js              PASS  ✓  (idle, ready)
STAGE 3: bridge.js                  PASS  ✓  (idle, ready)
STAGE 4: w4p.js                     PASS  ✓  (injecting, scraping, polling)
STAGE 5: w4p.js → bridge.js        FAIL  ✗  ← FIRST BREAK
         w4p.js → background.js    FAIL  ✗  ← cascade
         w4p.js → Flask             FAIL  ✗  ← cascade
```

---

## Exact Error Chain

| Layer | File:Line | What Happens | Status |
|-------|-----------|-------------|--------|
| Page load | n/a | `poker-web.goldrush.co.za/1875356/...` loads in iframe | OK |
| Manifest match | `manifest.json:72` | `*://*.goldrush.co.za/*` matches | OK |
| bridge.js inject | `manifest.json:56` | ISOLATED world, `document_start` | OK |
| w4p.js inject | `manifest.json:78` | MAIN world, `document_idle` | OK |
| bridge.js execute | `bridge.js:23` | `[W4P_BRIDGE] ISOLATED bridge loaded` | OK |
| w4p.js execute | `w4p.js:88` | `isPokerScrapeContext()` → true | OK |
| DOM scrape | `w4p.js:731` | `buildSnapshot()` → valid snapshot | OK |
| Tick loop | `w4p.js:1486` | `snap = buildSnapshot()` → not null | OK |
| **Send** | **`w4p.js:106`** | **`fetch('http://127.0.0.1:4000/api/snapshot')`** | **BLOCKED** |
| Chrome PNA | n/a | `Permission denied: loopback address space` | **BLOCKED** |
| Error | n/a | `net::ERR_FAILED` | **FAIL** |
| Catch handler | `w4p.js:109` | `callback({ok:false, error:'Failed to fetch'})` | handled |
| bridge.js | `bridge.js:5` | Never receives `W4P_BRIDGE` | IDLE |
| background.js | `background.js:33` | Never receives `W4P_FETCH` | IDLE |
| Flask :1080 | n/a | Never receives POST /api/snapshot | IDLE |

---

## Cross-Reference: What the Console Proves vs Assumptions

| What we assumed | What's actually happening |
|----------------|--------------------------|
| "Extension not loaded" | Extension IS loaded, all 4 scripts inject |
| "DOM selectors broken" | Selectors WORK — buttons detected, hero found |
| "API key mismatch" | Keys MATCH — `03622c...` in both places |
| "Flask dead" | Flask IS alive (fixed earlier) |
| "Network blocked" | PNA BLOCKS loopback fetch from MAIN world |
| "bridge.js not loaded" | bridge.js IS loaded and listening |

Every component works individually. The failure is at the exact architectural seam where
v20's `fetch()` approach collides with Chrome's PNA loopback restriction.

---

## Confidence

| Stage | Pass/Fail | Confidence | Evidence |
|-------|-----------|-----------|----------|
| manifest.json content_scripts | PASS | 100% | Source match + URL verified in console |
| background.js service worker | PASS | 90% | No errors in console; code structure correct |
| bridge.js injection + listener | PASS | 100% | Console log line `[W4P_BRIDGE] ISOLATED bridge loaded` |
| w4p.js IIFE execution | PASS | 100% | Console banner `[W4P] v23-hardened` |
| isPokerScrapeContext() gate | PASS | 100% | Source code line 46 + console shows context detected |
| buildSnapshot() function | PASS | 100% | Console: seat data, hero, buttons, available_actions |
| w4p.js → bridge.js | **FAIL** | 100% | `w4p.js` has zero `postMessage` or `W4P_BRIDGE` references; `bridgeFetch` uses direct `fetch()` |
| PNA loopback block | **FAIL** | 100% | Console error: `blocked by CORS policy: Permission was denied for this request to access the loopback address space` |
| w4p.js → Flask | **FAIL** | 100% | `snapshot_seq` stays at 1 (from manual test); no traffic |

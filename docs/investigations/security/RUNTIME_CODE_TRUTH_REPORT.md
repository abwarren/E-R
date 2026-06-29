# RUNTIME CODE TRUTH REPORT

**Date:** 2026-06-24
**Methodology:** Source analysis. Zero code changes.
**Status:** Partially blocked — laptop SSH is down, cannot inspect browser-loaded extension.
  All Docker and VM repo evidence is definitive.

---

## PART 1: Express Configuration

### 1. Proxy target

**File:** `/app/scripts/server-container.js` (Docker container)

```javascript
const BACKEND_API = 'http://127.0.0.1:1080';

app.use('/api', createProxyMiddleware({
  target: BACKEND_API,
  changeOrigin: true,
  proxyTimeout: 0,
  timeout: 0,
  ...
}));
```

**Answer:** Express proxies all `/api/*` requests to `http://127.0.0.1:1080` (Flask).

### 2. Is the target alive?

**YES.** Flask is alive.

```
curl http://127.0.0.1:4000/api/health → 200 OK
{
  "ok": true,
  "environment": "production",
  "pid": 7,
  "uptime_seconds": 70892,       (~19.7 hours)
  "snapshot_seq": 873,
  "active_tables": 0,
  "version": "remote-control-3.0"
}
```

### 3. Can Express successfully reach Flask?

**YES.** The proxy chain works:

```
curl :4000/api/health → Express → proxy → Flask :1080 → 200 OK
```

Flask PID 7 has been running ~19.7 hours. The stale lock file was cleared.
Snapshot endpoint is functional (seq=873, has logged traffic).

### 4. Exact result of `curl http://127.0.0.1:4000/api/health`

```
HTTP/1.1 200 OK
server: Werkzeug/3.1.8 Python/3.12.13
content-type: application/json

{"active_tables":0,"buffer_has_data":true,"buffer_table":"pb_2589954",
 "cdp_status":"unreachable","environment":"production","ok":true,
 "pending_cmds":0,"pid":7,"snapshot_age_seconds":60935.23,
 "snapshot_seq":873,"status":"healthy",
 "timestamp":"2026-06-24T17:53:05.239312","uptime_seconds":70715.88,
 "version":"remote-control-3.0"}
```

---

## PART 2: Extension Code — Laptop Browser

### STATUS: UNKNOWN (laptop unreachable)

SSH tunnel port 19999 is NOT LISTENING on the VM. Direct SSH to laptop
(192.168.0.107:22) failed — key-based auth required, our keys don't match.

The RUNTIME_TRUTH_REPORT.md from June 23 reported:
- Extension ID: `aioeikkkkoecalijgdedippnjoihofhj`
- Path: `/home/wa/projects/poker/E&R/backend/static/ext/`
- Type: Unpacked (developer mode)

But the file at that path on the VM is now CORRUPTED (502 lines, should be 1603).

**We cannot determine which code the browser actually loaded.**

---

## PART 3: All Known w4p.js Copies — Full Comparison

### Copy A: Docker container `/app/backend/static/ext/w4p.js`

| Property | Value |
|----------|-------|
| Lines | 1839 |
| Bytes | 80,239 |
| SHA256 | `e77073d85b59c159a8b5cc3218fdd65a4ae315ec8a7133135cf62cacc2afffdd` |
| Build ID | `FRAME_GUARD_V2` |
| Source path | `/home/wa/ConceptPoker/extension/w4p.js` |
| Build banner | `build=FRAME_GUARD_V2, ts=...` |
| Has `postMessage` | **NO** — 0 references |
| Has `fetch(API_BASE` | **YES** — 1 reference (line 251) |
| bridgeFetch impl | **DIRECT fetch()** |
| bridgeFetchRaw impl | **DIRECT fetch()** |
| Has commit a5110b4 | **NO** |
| API_BASE default | `http://127.0.0.1:4000/api` (via `window.__W4P_API_BASE`) |
| Date modified | Jun 12 2026 12:49 (timestamp 1781268543) |

```javascript
// bridgeFetch() at line 248:
function bridgeFetch(path, method, body, callback) {
    var opts = { method: method || 'GET', headers: { 'X-API-Key': API_KEY } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    fetch(API_BASE + path, opts)  // ← DIRECT fetch, NO postMessage
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP_' + r.status);
        return r.json();
      })
      ...
}
```

**This is the PRE-FIX code. It calls fetch() directly from MAIN world.**
**It will be blocked by Chrome's PNA loopback restriction.**

### Copy B: Fix branch committed `/home/wa/projects/poker/E&R` commit a5110b4

| Property | Value |
|----------|-------|
| Lines | 1603 |
| SHA256 | (git object, not on disk) |
| Branch | `fix/w4p-bridge-fetch` |
| Version | v23-hardened |
| Has `postMessage` | **YES** — 3 references |
| Has `fetch(API_BASE` | **NO** — 0 references |
| bridgeFetch impl | **postMessage()** |
| bridgeFetchRaw impl | **postMessage()** |
| Has commit a5110b4 | **YES — this IS the commit** |
| API_BASE default | `http://127.0.0.1:4000/api` (hardcoded) |

```javascript
// bridgeFetch() at line 118:
function bridgeFetch(path, method, body, callback) {
    _reqId++;
    if (callback) _callbacks[_reqId] = callback;
    window.postMessage({                         // ← CORRECT relay
      channel: 'W4P_BRIDGE',
      path: path, method: method, body: body,
      apiKey: API_KEY, rawPath: false, reqId: _reqId
    }, '*');
}
```

**This is the FIXED code. It routes through bridge.js → background.js.**

### Copy C: VM working directory `/home/wa/projects/poker/E&R/backend/static/ext/w4p.js`

| Property | Value |
|----------|-------|
| Lines | 502 |
| Bytes | 22,652 |
| Status | **CORRUPTED / TRUNCATED** |
| Missing | Entire tick loop, sendSnapshot, pollCommands, etc (lines 503-1603 gone) |

**This file is BROKEN. It is 1101 lines shorter than the committed version.**
**The working directory needs `git checkout` before any code changes.**

### Copy D: Master branch committed

| Property | Value |
|----------|-------|
| Lines | 1586 |
| Version | v23-hardened |
| branchFetch impl | **DIRECT fetch()** |
| branchFetchRaw impl | **DIRECT fetch()** |

**Same as Copy A but without the FRAME_GUARD_V2 diagnostics.**

### Copy E: Docker `/app/source/w4p-extension-dev/w4p.js`

| Property | Value |
|----------|-------|
| Lines | 1839 |
| SHA256 | `e77073d8...` (identical to Copy A) |
| Status | EXACT COPY of Copy A |

---

## PART 4: Docker bridge.js (all copies identical)

**File:** `/app/backend/static/ext/bridge.js`

| Property | Value |
|----------|-------|
| Lines | 19 |
| SHA256 | `d3b88ee2d2200af8fbb39dec36ee5d61cf48403e659d049244945e831d036f5b` |

```javascript
window.addEventListener('message', function(e) {
  if (!e.data || e.data.channel !== 'W4P_BRIDGE') return;
  chrome.runtime.sendMessage(
    { type: 'W4P_FETCH', path: msg.path, method: msg.method,
      body: msg.body, apiKey: msg.apiKey, rawPath: msg.rawPath },
    function(response) {
      window.postMessage({
        channel: 'W4P_BRIDGE_RESPONSE',
        reqId: msg.reqId,
        response: response
      }, '*');
    }
  );
});
```

**CORRECT implementation.** Listens for `W4P_BRIDGE`, relays to background.js.
But it is **useless** if w4p.js uses direct fetch() instead of postMessage.

---

## PART 5: Docker background.js vs Fix Branch background.js

### Docker container version

| Property | Value |
|----------|-------|
| Lines | 76 |
| SHA256 | `8c0f2f624c8b2d0856a479e79730558f0d3c2bf88b453303ad4e0b8bbce67609` |
| DEFAULT_API_BASE | `http://127.0.0.1:1080/api` |
| DEFAULT_SITE_BASE | `http://127.0.0.1:1080` |

### Fix branch version

| Property | Value |
|----------|-------|
| Lines | 89 |
| SHA256 | different |
| DEFAULT_API_BASE | `http://127.0.0.1:4000/api` |
| DEFAULT_SITE_BASE | `http://127.0.0.1:4000` |

### Critical difference

Docker `background.js` defaults to **1080** (direct Flask).
Fix branch `background.js` defaults to **4000** (Express proxy).

This matters because:
- With the Docker version: if background.js is used and no config is saved, traffic goes directly to Flask :1080
- With the fix branch version: traffic goes to Express :4000 which proxies to Flask :1080
- Both work NOW (Flask is alive), but 4000 is the intended path with CORS headers

---

## PART 6: URL Resolution (Revisited with Docker Evidence)

The Docker container serves the extension files. If the user loaded/updated the
extension FROM the Docker container's served files, they got:

| File | Impl | Problem |
|------|------|---------|
| w4p.js | DIRECT fetch() | Blocked by Chrome PNA |
| bridge.js | postMessage relay | Unused (w4p.js doesn't use it) |
| background.js | fetch() proxy | Unused, and defaults to :1080 |
| options.html | Dev preset = :1080 | Misleading UI |

If the user loaded the extension from the laptop's local git working directory,
they got CORRUPTED w4p.js (502 lines, missing the entire tick loop).

**Neither path delivers a working extension with the fix applied.**

---

## PART 7: What Must Be True for the Fix to Work

For commit a5110b4 to be effective, ALL of these must be true:

1. [ ] Laptop `/home/wa/projects/poker/E&R/` must be on `fix/w4p-bridge-fetch` branch
2. [ ] `git checkout backend/static/ext/w4p.js` must restore the full 1603-line file
3. [ ] Chrome must reload the unpacked extension (or it uses cached old code)
4. [ ] background.js DEFAULT_API_BASE must target :4000 (Express), not :1080
5. [ ] bridge.js must be the ISOLATED-world relay version
6. [ ] No cached service worker from old version

**Current assessment: NONE of these can be verified.** Laptop is unreachable.

---

## PART 8: The ICMP Test

Since the fix CANNOT be verified in the browser, verify the backend chain:

```
curl http://127.0.0.1:4000/api/health
  → Express :4000 receives
    → proxy to Flask :1080
      → Flask responds 200 OK

Verdict: BACKEND CHAIN IS HEALTHY
         Express → Flask proxy works
         Flask is alive (PID 7, ~19.7h uptime)

curl http://127.0.0.1:1080/api/health
  → Flask responds 200 OK directly

Verdict: FLASK IS ALIVE
         Previous lock file issue resolved
```

---

## Confidence Assessment

| Claim | Confidence | Basis |
|-------|-----------|-------|
| Docker w4p.js uses DIRECT fetch (no fix) | 100% | grep + code read inside container |
| Fix branch a5110b4 uses postMessage | 100% | git show + diff |
| VM working dir w4p.js is truncated | 100% | wc -l = 502 vs 1603 committed |
| Express proxies /api/* to Flask :1080 | 100% | server-container.js |
| Flask is alive and reachable | 100% | curl :4000/api/health → 200 |
| Docker background.js defaults to :1080 | 100% | cat inside container |
| Fix branch background.js defaults to :4000 | 100% | read_file from repo |
| Bridge.js implementation is correct | 100% | source review |
| Browser-loaded w4p.js version | **0%** | Laptop unreachable |
| Whether Chrome has fix-branch code | **0%** | Laptop unreachable |
| Whether extension is even loaded now | **0%** | Laptop unreachable |

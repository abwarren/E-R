# LOAD THIS EXTENSION

## Canonical directory

```
/home/wa/projects/poker/E&R/backend/static/ext/
```

**WARNING:** The working directory is currently corrupted. Run this first:

```
cd /home/wa/projects/poker/E&R
git checkout backend/static/ext/
```

After checkout, load the directory as an unpacked extension in Chrome:
1. Navigate to `chrome://extensions`
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select `/home/wa/projects/poker/E&R/backend/static/ext/`

Then restart the extension or click the reload button.

---

## Authoritative source

| Property | Value |
|----------|-------|
| Git branch | `fix/w4p-bridge-fetch` |
| Commit hash | `a5110b4` |
| Commit message | `fix: route bridgeFetch through postMessage relay instead of direct fetch` |
| Parent | `cd6921b security: untrack secrets and sensitive files` |

---

## File hashes (as committed)

```
w4p.js:
  SHA256: 2d97ca27eba121793bdbd9c664eefb3bf77b57af67bfe122df761f4e62a4b24a
  Lines:  1603

bridge.js:
  SHA256: 30a0a1e9742bf338e09213364ce73f79a8fc515048f9152740ca09cd31d4993c
  Lines:  23

background.js:
  SHA256: daea94a4396609d39babf76c6a836295c569844a11dc0bfd2a31c0231e7dd1c7
  Lines:  89
```

---

## Fix verification

### w4p.js — has bridge relay

```javascript
// 3 W4P_BRIDGE references
// 5 _callbacks references (callback registry)
// 7 _reqId references (request ID counter)
// 3 postMessage calls
// 0 fetch(API_BASE calls

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

### bridge.js — relays ISOLATED → service worker

```javascript
// Listens for W4P_BRIDGE postMessage
// Forwards via chrome.runtime.sendMessage → background.js
// Returns response via W4P_BRIDGE_RESPONSE postMessage
```

### background.js — proxies fetch with extension permissions

```javascript
const DEFAULT_API_BASE = 'http://127.0.0.1:4000/api';
const DEFAULT_SITE_BASE = 'http://127.0.0.1:4000';
// Handles W4P_FETCH: constructs URL from API_BASE + path, fetches
// Handles W4P_SET_CONFIG: updates storage + runtime vars
```

---

## Message flow

```
w4p.js (MAIN world)
  → window.postMessage({channel: 'W4P_BRIDGE', path, rawPath:false})
    → bridge.js (ISOLATED world)
      → chrome.runtime.sendMessage({type:'W4P_FETCH', path, rawPath, ...})
        → background.js (service worker)
          → url = API_BASE + path
          → fetch(url, opts)  ← extension permissions, no PNA block
            → Express :4000
              → proxy → Flask :1080
```

---

## Why every other copy is invalid

### COPY 1: VM working directory `/home/wa/projects/poker/E&R/backend/static/ext/w4p.js`

```
SHA256: fea26f22...
Lines:  502 (should be 1603)
Status: CORRUPTED / TRUNCATED
```

- Missing lines 503-1603: entire tick loop, sendSnapshot, pollCommands,
  handleCommand, handleSnapshotResponse, buildSnapshot, getAvailableActions
- If loaded into Chrome, w4p.js would inject but never send any snapshots
- Even the startup banner wouldn't print fully

### COPY 2: Docker container `/app/backend/static/ext/w4p.js`

```
SHA256: e77073d85b59c159a8b5cc3218fdd65a4ae315ec8a7133135cf62cacc2afffdd
Lines:  1839
Build:  FRAME_GUARD_V2 (diagnostic build)
Source: /home/wa/ConceptPoker/extension
```

- PRE-FIX code — uses DIRECT fetch() from MAIN world
- 0 postMessage references, 1 fetch(API_BASE reference
- bridgeFetch() at line 248:
  ```javascript
  fetch(API_BASE + path, opts)  // ← DIRECT, blocked by PNA
  ```
- Has diagnostic banner FRAME_GUARD_V2 — a temporary build never meant for production
- Dated Jun 12 — older than the fix commit (Jun 24)
- background.js defaults to :1080 (direct Flask), not :4000 (Express)

### COPY 3: Docker `/app/source/w4p-extension-dev/w4p.js`

```
SHA256: e77073d85b59c159a8b5cc3218fdd65a4ae315ec8a7133135cf62cacc2afffdd
Lines:  1839
```

- Identical SHA256 to Copy 2 — exact same FRAME_GUARD_V2 build
- Same pre-fix code, same direct fetch problem
- Vivaldi's Secure Preferences (from RUNTIME_TRUTH_REPORT June 23) showed
  extension ID `bjladcnoceindfikglnijmdkbeahejjm` loaded from this path,
  but the directory was already reported as deleted

### COPY 4: `w4p.js.before` (working dir backup)

```
Lines: 1586
```

- Master branch pre-fix code
- bridgeFetch() uses direct fetch() — no postMessage
- Saved as backup before the fix was applied, but the fix application
  was interrupted, leaving the truncated 502-line file

### COPY 5: Docker background.js defaults to :1080

```
DEFAULT_API_BASE = 'http://127.0.0.1:1080/api'
DEFAULT_SITE_BASE = 'http://127.0.0.1:1080'
```

- Different defaults from fix branch (:1080 vs :4000)
- If bridge.js relay works but this background.js is loaded,
  traffic goes directly to Flask :1080, bypassing Express CORS headers

### COPY 6: Master branch committed

```
Lines: 1586
```

- v23-hardened with direct fetch() — the original pre-fix code
- bridgeFetch calls fetch(API_BASE + path) directly from MAIN world
- This is the code the EXTENSION_INJECTION_REPORT.md proved was broken

---

## Quick integrity check after checkout

```bash
cd /home/wa/projects/poker/E\&R/backend/static/ext/

# Verify you have the fix
grep -c 'postMessage' w4p.js        # must print: 3
grep -c 'fetch(API_BASE' w4p.js     # must print: 0
grep -c 'W4P_BRIDGE' w4p.js         # must print: 3

# Verify line count
wc -l w4p.js                         # must print: 1603

# Verify background.js defaults
grep 'DEFAULT_API_BASE' background.js  # must show: :4000
```

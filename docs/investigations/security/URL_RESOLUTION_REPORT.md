# URL Resolution Report — Extension Network Traffic

**Date:** 2026-06-24
**Methodology:** SOURCE analysis of fix/w4p-bridge-fetch branch (commit a5110b4). 
No code changes. Evidence only.
**Status:** INCOMPLETE — chrome.storage.sync value requires laptop runtime access.

---

## Trace: Options UI → Storage → Runtime Config → Network Request

### Layer 1: Options UI

**File:** `backend/static/ext/options.html`

```javascript
// Line 41 — Dev preset
dev: { apiBase: 'http://127.0.0.1:1080/api', siteBase: 'http://127.0.0.1:1080' }

// Line 42 — Prod preset
prod: { apiBase: 'https://haaats.xyz/api', siteBase: 'https://haaats.xyz' }

// Line 46-47 — Load from storage, fallback to dev preset
chrome.storage.sync.get(['w4p_api_base', 'w4p_site_base'], function(result) {
    document.getElementById('api-base').value = result.w4p_api_base || PRESETS.dev.apiBase;
    document.getElementById('site-base').value = result.w4p_site_base || PRESETS.dev.siteBase;
});

// Line 86 — Save to storage on Save button click
chrome.storage.sync.set({ w4p_api_base: apiBase, w4p_site_base: siteBase });

// Lines 88-94 — Also push W4P_SET_CONFIG message to background.js
chrome.runtime.sendMessage({ type: 'W4P_SET_CONFIG', apiBase, siteBase });
```

**Verdict:** The options page SHOWING `http://127.0.0.1:1080/api` does NOT mean
that value is in chrome.storage.sync. The UI loads `result.w4p_api_base` and falls
back to `PRESETS.dev.apiBase` (1080) when storage is empty. The current display
value is inconclusive without checking chrome.storage.sync directly.

---

### Layer 2: chrome.storage.sync

**Keys used:**

| Key | Purpose | Example value |
|-----|---------|---------------|
| `w4p_api_base` | Base URL prefix for all API calls | `http://127.0.0.1:4000/api` |
| `w4p_site_base` | Base URL for raw-path calls (collector) | `http://127.0.0.1:4000` |

**Current stored value:** UNKNOWN — requires one of:
- Chrome DevTools → Application → Storage → Extension Storage → w4p_api_base
- Or `chrome.storage.sync.get('w4p_api_base', console.log)` in extension console
- Or read Chrome's LevelDB: `~/.config/chromium/Default/Local Extension Settings/<ext_id>/`

**Fallback if storage is empty:** See Layer 3.

---

### Layer 3: background.js — Runtime API_BASE

**File:** `backend/static/ext/background.js`

```javascript
// Line 14-15 — Hardcoded defaults
const DEFAULT_API_BASE = 'http://127.0.0.1:4000/api';
const DEFAULT_SITE_BASE = 'http://127.0.0.1:4000';

// Line 18-19 — Runtime variables (start as defaults)
let API_BASE = DEFAULT_API_BASE;
let SITE_BASE = DEFAULT_SITE_BASE;

// Lines 22-30 — Override from chrome.storage.sync (async, race-prone)
chrome.storage.sync.get(['w4p_api_base', 'w4p_site_base'], function(result) {
    if (result.w4p_api_base) API_BASE = result.w4p_api_base;
    if (result.w4p_site_base) SITE_BASE = result.w4p_site_base;
    console.log('[W4P-BG] API_BASE=' + API_BASE + ' SITE_BASE=' + SITE_BASE);
});

// Lines 66-77 — W4P_SET_CONFIG handler (live updates from options page)
if (msg.type === 'W4P_SET_CONFIG') {
    if (msg.apiBase) { API_BASE = msg.apiBase; chrome.storage.sync.set(...); }
    if (msg.siteBase) { SITE_BASE = msg.siteBase; chrome.storage.sync.set(...); }
}
```

**Race condition:** If a W4P_FETCH message arrives before the async
chrome.storage.sync.get callback fires, `API_BASE` will still be the DEFAULT
(`http://127.0.0.1:4000/api`). The service worker might be more likely to
hit this on first load before storage is read.

---

### Layer 4: background.js — URL Construction

**File:** `backend/static/ext/background.js`, line 36

```javascript
// W4P_FETCH handler
var url = msg.rawPath ? (SITE_BASE + msg.path) : (API_BASE + msg.path);
```

| `rawPath` | URL source | Use case |
|-----------|-----------|----------|
| `false` | `API_BASE + msg.path` | /snapshot, /commands/pending, /commands/ack |
| `true` | `SITE_BASE + msg.path` | /collector/save (no /api prefix) |

**Final fetch at line 48:**
```javascript
fetch(url, opts)
```

This runs in the service worker context. It has full extension host_permissions.
It is NOT subject to page-level CORS or PNA restrictions.

---

### Layer 5: w4p.js — API Call Sites

**File:** `backend/static/ext/w4p.js` (commit a5110b4, 1603 lines)

w4p.js has its own hardcoded `API_BASE` (line 98) and `SITE_BASE` (line 100),
but these are ONLY used for:
1. The startup banner text showing `[W4P] API: http://127.0.0.1:4000/api`
2. No effect on actual network request URLs

All network calls use `bridgeFetch` or `bridgeFetchRaw` which send only the
PATH to bridge.js. The full URL is constructed in background.js (Layer 4).

**API call sites:**

| Call | Path | rawPath | Constructor | Default URL |
|------|------|---------|-------------|-------------|
| sendSnapshot (L996) | `/snapshot` | false | API_BASE + path | `http://127.0.0.1:4000/api/snapshot` |
| pollCommands (L1453) | `/commands/pending?token=...` | false | API_BASE + path | `http://127.0.0.1:4000/api/commands/pending?token=...` |
| command ack (L1457) | `/commands/ack` | false | API_BASE + path | `http://127.0.0.1:4000/api/commands/ack` |
| collector (L991) | `/collector/save` | true | SITE_BASE + path | `http://127.0.0.1:4000/collector/save` |

**No bridgeFetch call sites reference localhost:1080 anywhere in the code.**

---

### Layer 6: bridge.js — Message Relay

**File:** `backend/static/ext/bridge.js`

```javascript
// Line 5 — Receives from w4p.js (MAIN world)
window.addEventListener('message', function(e) {
    if (!e.data || e.data.channel !== 'W4P_BRIDGE') return;

    // Line 10-12 — Forwards ALL fields to background.js
    chrome.runtime.sendMessage({
        type: 'W4P_FETCH',
        path: msg.path,
        method: msg.method,
        body: msg.body,
        apiKey: msg.apiKey,
        rawPath: msg.rawPath    // ← passed through verbatim
    }, function(response) { ... });
});
```

**Verdict:** bridge.js is a transparent relay. It does not modify any URL fields.
All w4p.js fields pass through unmodified to background.js.

---

## Answers to the 7 Questions

### 1. Where API URL is stored?

**chrome.storage.sync** under key `w4p_api_base`.

More precisely:
- **Persistent storage:** `chrome.storage.sync.get('w4p_api_base')`
- **Runtime variable:** `background.js` line 18 — `let API_BASE = DEFAULT_API_BASE`
- **Live update path:** Options UI → chrome.storage.sync.set() + W4P_SET_CONFIG → background.js line 68

### 2. What value is currently stored?

**UNKNOWN** — evidence unavailable.

To determine:
1. On the laptop, open Chrome, go to `chrome://extensions`, find "PokerScope W4P"
2. Click "service worker" to open background.js console
3. Execute: `chrome.storage.sync.get(['w4p_api_base','w4p_site_base'], console.log)`
4. Or check Chrome's LevelDB store on disk

### 3. What file reads it?

**`background.js`**, lines 22-25 (startup load) and lines 66-68 (live W4P_SET_CONFIG update).

### 4. What file performs network requests?

**`background.js`**, line 48 — `fetch(url, opts)` in the W4P_FETCH handler.

w4p.js does NOT perform any network requests (after the fix). It delegates
via postMessage → bridge.js → chrome.runtime.sendMessage → background.js.

### 5. Exact runtime URL used?

Depends on `w4p_api_base` in chrome.storage.sync:

| Storage value | Snapshot URL | Commands URL |
|--------------|-------------|-------------|
| **Not set (default)** | `http://127.0.0.1:4000/api/snapshot` | `http://127.0.0.1:4000/api/commands/pending?token=...` |
| `http://127.0.0.1:1080/api` | `http://127.0.0.1:1080/api/snapshot` | `http://127.0.0.1:1080/api/commands/pending?token=...` |
| `https://haaats.xyz/api` | `https://haaats.xyz/api/snapshot` | `https://haaats.xyz/api/commands/pending?token=...` |

### 6. Fallback URL if storage is empty?

```
DEFAULT_API_BASE = 'http://127.0.0.1:4000/api'
DEFAULT_SITE_BASE = 'http://127.0.0.1:4000'
```

Both hardcoded at `background.js` lines 14-15.

### 7. Where does runtime traffic go?

**DEFAULT: `localhost:4000`** (Express). Unless the user explicitly saved a
different value in the options page.

The options page presets are:
- **Dev preset (unsaved default display):** `http://127.0.0.1:1080/api` — BUT
  this is ONLY a display placeholder. It does NOT affect runtime unless the
  user clicked "Save".
- **Prod preset:** `https://haaats.xyz/api`
- **DEFAULT_API_BASE in background.js:** `http://127.0.0.1:4000/api`

---

## Architecture Diagram

```
                        OPTIONS UI (options.html)
                        Shows placeholder: http://127.0.0.1:1080/api
                        unless user saved a different value
                              │
                              │ Save button: chrome.storage.sync.set()
                              │ + chrome.runtime.sendMessage(W4P_SET_CONFIG)
                              ▼
                   chrome.storage.sync
                   ┌─────────────────────────────────────┐
                   │ w4p_api_base = ???                  │ ← UNKNOWN
                   │ w4p_site_base = ???                 │
                   └─────────────────────────────────────┘
                              │
                              │ background.js line 22:
                              │ chrome.storage.sync.get()
                              │ fallback: DEFAULT_API_BASE
                              ▼
              background.js  (service worker)
              ┌──────────────────────────────────────────┐
              │ let API_BASE = DEFAULT_API_BASE          │
              │        = 'http://127.0.0.1:4000/api'     │
              │ let SITE_BASE = DEFAULT_SITE_BASE        │
              │        = 'http://127.0.0.1:4000'         │
              │                                          │
              │ On W4P_FETCH msg:                        │
              │   url = API_BASE + msg.path              │
              │   fetch(url, opts)     ← ACTUAL REQUEST  │
              └──────────────────────────────────────────┘
                       ▲
                       │ chrome.runtime.sendMessage()
                       │ {type:'W4P_FETCH', path:'/snapshot', rawPath:false}
                       │
              bridge.js  (ISOLATED world)
              ┌──────────────────────────────────────────┐
              │ Transparent relay. Passes ALL w4p.js     │
              │ fields through unmodified:               │
              │   path, method, body, apiKey, rawPath    │
              └──────────────────────────────────────────┘
                       ▲
                       │ window.postMessage()
                       │ {channel:'W4P_BRIDGE', path:'/snapshot', rawPath:false}
                       │
              w4p.js  (MAIN world)
              ┌──────────────────────────────────────────┐
              │ var API_BASE = 'http://127.0.0.1:4000/api'│ ← Banner ONLY
              │                                          │
              │ bridgeFetch('/snapshot', 'POST', snap)   │
              │   → postMessage({path:'/snapshot',       │
              │      rawPath:false})                     │
              │   → PATH ONLY, no host/port              │
              └──────────────────────────────────────────┘
```

---

## Critical Implications

### 1. Default goes to localhost:4000, not 1080

If the user has never clicked "Save" in the options page, the background.js
default (`http://127.0.0.1:4000/api`) is used. The options page showing
`http://127.0.0.1:1080/api` is the DEV PRESET placeholder, not the active
configuration.

### 2. Options page display is misleading

The UI shows `PRESETS.dev.apiBase` as a fallback when storage is empty.
This makes it appear as if 1080 is configured when it may not be stored.

### 3. Express (:4000) proxies /api/* to Flask (:1080)

If traffic goes to :4000, the Express proxy forwards `/api/snapshot` to
`http://127.0.0.1:1080/api/snapshot`. Flask :1080 is currently DEAD inside
the Docker container (stale PID lock). So even with the correct URL,
requests will get ECONNREFUSED.

### 4. If user DID save 1080 as API_BASE

Then traffic goes directly to `http://127.0.0.1:1080/api/snapshot`.
This completely bypasses Express (:4000) and goes straight to the (dead)
Flask process. ECONNREFUSED either way.

### 5. w4p.js hardcoded API_BASE is cosmetic only

Line 98: `var API_BASE = 'http://127.0.0.1:4000/api'` in w4p.js only
affects the startup banner text. It has zero effect on network request URLs
because w4p.js never constructs a full URL — it only sends the path.

---

## What We CANNOT Determine Without Laptop Access

| Question | Why blocked |
|----------|------------|
| Actual chrome.storage.sync value for w4p_api_base | No SSH to laptop (port 19999 connection refused) |
| Whether user ever clicked Save in options | No browser localStorage/LevelDB access |
| Whether background.js actually loads before first fetch | No service worker console access |
| Which version of w4p.js is loaded in Chrome | Unknown if Chrome picked up fix branch or master |
| Whether traffic actually flows | No runtime network logs |

---

## Confidence Assessment

| Claim | Confidence | Basis |
|-------|-----------|-------|
| API_BASE stored in chrome.storage.sync.w4p_api_base | 100% | background.js:22 + options.html:86 |
| Default API_BASE = http://127.0.0.1:4000/api | 100% | background.js:14 |
| bridgeFetch sends only path (not full URL) | 100% | w4p.js:118-126 (fix branch) |
| background.js constructs full URL from API_BASE + path | 100% | background.js:36 |
| Options display of 1080 is not proof of config | 100% | options.html:47 fallback logic |
| Actual value in chrome.storage.sync | 0% | No laptop access |
| Runtime traffic destination | 0% | Depends on unknown storage value |
| Whether Chrome loaded fix branch or master | 0% | No laptop access |

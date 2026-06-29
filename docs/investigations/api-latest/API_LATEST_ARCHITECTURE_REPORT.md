# API_LATEST Architecture Report

## Investigation Summary

### Q1: Does `/api/latest` already exist?

**No.** There is no route `/api/latest` anywhere in the codebase.

The nearest existing endpoint is **`GET /api/table/latest`** (Flask: `app.py` line 1450), which is the primary polling endpoint used by all UIs.

There is also a separate **`GET /api/collector/latest`** (line 2161) and a **`GET /api/hands/recent`** (line 1782).

---

### Q2: Which Flask route serves the nearest equivalent?

**`GET /api/table/latest`** — defined at `backend/app.py:1450`.

```python
@app.route('/api/table/latest', methods=['GET'])
def table_latest():
```

It supports optional long-polling via `?timeout=N&last_ts=N` query parameters. Returns `{'ok': True, 'table': view}` where `view` is built by `_table_view()`.

---

### Q3: What data structure does it return?

`_table_view(table)` at `app.py:822` builds:

```python
{
    "table_id":      str,
    "variant":       str,         # "plo"
    "street":        str,         # "PREFLOP"|"FLOP"|"TURN"|"RIVER"
    "pot_zar":       float,
    "dealer_seat":   int|None,
    "board":         {"flop": [...], "turn": str|None, "river": str|None},
    "state_version": int,         # incremented on each snapshot
    "last_updated":  float,       # timestamp
    "seats":         [...],       # 9-element array from _build_seats_list()
    "collector_batch": str|None,  # raw batch text for engine
}
```

Each seat object:
```python
{
    "seat_no":          int,
    "seat_index":       int,
    "name":             str|None,
    "stack_zar":        float,
    "hole_cards":       [...],
    "status":           str,       # "empty"|"sitting_out"|etc
    "is_dealer":        bool,
    "is_hero":          bool,
    "is_self_player":   bool,
    "available_actions": [...],
    "buttons":          {...},
    "bot_id":           str|None,
    "pending_cmd":      str|None,
}
```

---

### Q4: Which backend function updates the latest hand state?

**`POST /api/snapshot`** at `app.py:1013` is the sole writer to `_tables` (the in-memory store).

Flow:
1. `w4p.js` scrapes DOM → calls `bridgeFetch('/snapshot', 'POST', snap)`
2. `bridge.js` relays to `background.js` (service worker)
3. `background.js` proxies to `http://127.0.0.1:4000/api/snapshot`
4. Express at `:4000` proxies `/api/*` → Flask at `:1080`
5. Flask `post_snapshot()` updates `_tables[table_id]` under `_store_lock`
6. Sets `table["last_ts"]`, increments `table["state_version"]`
7. Calls `sse_notify(_table_view(table))` for SSE push
8. Calls `push_snapshot(payload)` for ring buffer

The canonical state lives in `_tables` dict in Flask memory (with disk persistence every 10s to `state_snapshot.json`).

---

### Q5: Which frontend JavaScript updates the textarea?

There are **three** textareas across the application:

#### A. Engine textarea (`engine-index.html` React SPA)

XPath: `/html/body/div/div/main/div/div[1]/div[2]/div[2]/textarea`

This is the React-built textarea with `rows="14"`. It's populated by:

**`engine_flow_controls.js`** (injected into the React SPA via `<script defer>` at line 15 of `engine-index.html`)

Key code path (`engine_flow_controls.js` line 278-294):
```javascript
async function pollLatest() {
    const textarea = ensureControls();
    const res = await fetch(BRIDGE_URL, ...);  // BRIDGE_URL = 'https://potlimitomaha.xyz/api/table/latest'
    const data = await res.json();
    const text = formatTableDataToCanonical(data.table);
    if (state.autoFill && text) {
        detectAndSetVariant(text);
        setTextareaValue(textarea, text);
    }
}
```

`formatTableDataToCanonical()` (line 83) extracts `hole_cards` from each seat, then appends board cards as a separate line, producing canonical format like:
```
AhKhQhJh
AdKdQdJd
6s7c8d9hTd
```

#### B. Remote UI hand-log textarea (`remote.html` / `index.html`)

Both files are identical (md5: `ca28166...`). The hand-log textarea at `<textarea id="hand-log">` is populated by `updateHandLog()` (line 2488):

```javascript
function updateHandLog() {
    fetch(API_BASE + '/hands/recent?limit=20')
        .then(r => r.json())
        .then(data => {
            textarea.value = data.hands.join('\n');
        });
}
```

This reads from `GET /api/hands/recent` which returns ASCII hand history accumulated by `_archive_hand()` in Flask (called on hand resets).

#### C. Hand Export textarea (`hand-export.html`)

Polls `/api/table/latest` on user click, extracts hands client-side via `extractHands()`.

---

### Q6: Is the textarea currently populated from `/api/latest`?

**Engine textarea**: Populated from `/api/table/latest` (not `/api/latest`). The data flows:

```
w4p.js scraper → POST /api/snapshot → Flask _tables → _table_view()
    → GET /api/table/latest → engine_flow_controls.js → textarea
```

This is **already a pure backend state view**. The backend is the single source of truth.

**But there is a caveat**: `engine_flow_controls.js` uses a **hardcoded external URL**:
```javascript
const BRIDGE_URL = 'https://potlimitomaha.xyz/api/table/latest';
```
This bypasses the Express proxy and hits the remote production server directly — not `localhost`. In local development, this will show production data, not local data.

**Remote UI hand-log textarea**: Populated from `/api/hands/recent`. Also backend-owned state.

---

### Q7: Smallest architectural change to implement `/api/latest`

#### Option A: Add alias route (trivial)

Add a single Flask route that aliases `/api/latest` → same handler as `/api/table/latest`:

```python
@app.route('/api/latest', methods=['GET'])
def api_latest():
    return table_latest()
```

This keeps backward compatibility while providing the shorter URL the user expects.

**Impact**: Zero downstream changes needed. All existing consumers of `/api/table/latest` continue working.

#### Option B: Fix engine_flow_controls BRIDGE_URL (medium)

Change `engine_flow_controls.js` line 6:
```javascript
// Current (hardcoded prod):
const BRIDGE_URL = 'https://potlimitomaha.xyz/api/table/latest';

// Fixed (respects local context):
const BRIDGE_URL = window.location.origin + '/api/table/latest';
```

This makes the engine textarea correctly use local backend state in development, and production backend state in production — instead of always hitting `potlimitomaha.xyz`.

---

## Current Data Flow Diagram

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                      GoldRush Poker                      │
                    └──────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │                    w4p.js (MAIN world)                    │
                    │                                                          │
                    │  sendSnapshot() ─────────────────┐                       │
                    │  sendToCollector() ───┐           │                       │
                    └───────────────────────┼───────────┼───────────────────────┘
                                            │           │
                              POST /collector/save      │
                              (hero hand + board)       │
                                            │           │
                                            ▼           ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │              bridge.js + background.js (SW)               │
                    │         proxies MAIN-world fetches via chrome.runtime     │
                    └──────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │               Express (:4000) — server.js                 │
                    │                                                          │
                    │  /collector/save   → Flask :1080                         │
                    │  /api/*            → Flask :1080                         │
                    └──────────────────────────────────────────────────────────┘
                                            │
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                    ┌──────────────────┐        ┌──────────────────────────┐
                    │ /collector/save  │        │ POST /api/snapshot       │
                    │ → file on disk   │        │ → _tables[table_id]      │
                    │  saved_hands/*.txt│       │ → _archive_hand()        │
                    └──────────────────┘        │ → _hero_cards cache      │
                              │                  │ → _seat_bots mapping     │
                              │                  │ → _bot_buttons cache     │
                              │                  │ → state_version++        │
                              │                  └──────────────────────────┘
                              │                               │
                              ▼                               ▼
                    ┌──────────────────┐        ┌──────────────────────────┐
                    │ GET /api/        │        │ GET /api/table/latest    │
                    │ collector/latest │        │ → _table_view()          │
                    │ → reads file     │        │ → _build_seats_list()    │
                    └──────────────────┘        │ → collector_batch field  │
                                                └──────────────────────────┘
                                                              │
                                     ┌────────────────────────┼─────────────────────────┐
                                     ▼                        ▼                         ▼
                              ┌─────────────┐        ┌──────────────┐         ┌──────────────────┐
                              │ remote-w4p  │        │ engine_flow_ │         │ remote.html      │
                              │ .html       │        │ controls.js  │         │ / index.html     │
                              │             │        │              │         │                  │
                              │ polls       │        │ polls        │         │ hand-log textarea│
                              │ /api/table/ │        │ https://     │         │ calls            │
                              │ latest      │        │ potlimitomaha│         │ /api/hands/recent│
                              │             │        │ .xyz/api/    │         │                  │
                              │ renders     │        │ table/latest │         │                  │
                              │ seat grid   │        │              │         │                  │
                              │             │        │ writes to    │         │                  │
                              │             │        │ React's      │         │                  │
                              │             │        │ textarea     │         │                  │
                              └─────────────┘        └──────────────┘         └──────────────────┘
```

---

## Assessment

### Current Owner of Latest Hand State

The **Flask backend** (`_tables` dict) is already the single source of truth. State is updated exclusively by `POST /api/snapshot` under lock, persisted to disk every 10s, and served read-only by `GET /api/table/latest`.

### Whether the Textarea Is Using Backend State

- **Engine textarea**: YES — data comes from `/api/table/latest` (via `formatTableDataToCanonical`). Already a pure view of backend state.
- **BUT**: uses a hardcoded remote URL, not local Express proxy. This means local dev textarea shows production data.
- **Remote UI hand-log textarea**: YES — data comes from `/api/hands/recent`, which is backend-owned ASCII hand history.

### Whether `/api/latest` Exists

**No.** Needs to be created. Trivial: add a single alias route.

### Backend → Frontend Compliance

The architecture **already follows** the directive's required pattern:

```
GoldRush → w4p.js → POST /api/snapshot → Flask → Update _tables
                                                      │
                                                      ▼
                                            GET /api/table/latest
                                                      │
                                                      ▼
                                              Remote UI / textarea
```

The backend IS the single source of truth. The UIs simply render what `/api/table/latest` returns. No frontend reconstructs poker state itself.

### Identified Issues

1. **`/api/latest` does not exist** — the directive references this endpoint by name but it's not implemented. The existing endpoint is `/api/table/latest`.

2. **`engine_flow_controls.js` hardcodes production URL** (`https://potlimitomaha.xyz/api/table/latest`) instead of using relative URLs. This bypasses the Express proxy and makes the engine textarea show production data in local dev.

3. **Parallel collector pipeline** — `w4p.js` also POSTs to `/collector/save` which writes to disk files. The `/api/collector/latest` endpoint reads these files. This is a secondary data path that bypasses `_tables` — although the engine textarea uses `/api/table/latest` (not `/api/collector/latest`), the collector files feed into the `collector_batch` field of the table view.

4. **`index.html` and `remote.html` are identical** — both are 2834-line duplicate files. The Flask router serves `index.html` on `rc2.` host and `remote.html` otherwise, but both contain identical deployment/bot-management UI code.

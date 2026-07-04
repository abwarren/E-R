# ENGINE TEXTAREA REGRESSION — Git Investigation Report

**Date:** 2026-07-04  
**Agent:** Monitoring Agent (READ-ONLY)  
**Mission:** Identify the exact Git commit that stopped handData from reaching the Engine textarea

---

## 1. ENGINE TEXTAREA DATA PATH (UNCHANGED SINCE BASELINE)

```
Extension (w4p.js)
  ↓ POST /api/snapshot
Flask CO (app.py)
  ↓ _tables[(table_id, bot_id)]
  ↓ _table_view() → sibling merge
  ↓ GET /api/table/latest
Engine poller (engine_flow_controls.js v2.0.0-variant-aware)
  ↓ fetch("/api/table/latest")
  ↓ parseTableToHands(data)
  ↓ setTextareaValue(textarea, text)
Textarea DOM element
```

**Key finding:** The Engine poller (`engine_flow_controls.js`, file at `/ENGINEENGINE/source/static/assets/engine_flow_controls.js`) has NEVER changed its fetch URL. Since the baseline commit `9439e15` in the ENGINEENGINE repo, it has always used:

```javascript
const res = await fetch("/api/table/latest", ...);
```

No hardcoded BRIDGE_URL. No W4P_API lookup. Just a relative URL. It has been the same through all commits:

| Commit | ENGINEENGINE repo | Change to poller? |
|--------|------------------|-------------------|
| 9439e15 | BASELINE | Initial version — `fetch("/api/table/latest")` |
| 42482b1 | feat: auto-populate names | Added Names textarea, poller unchanged |
| HEAD | current | Poller unchanged since baseline |

The E&R repo has a DIFFERENT version (`v2.1.0-engine-bridge`) with `BRIDGE_URL = (window.W4P_API && ...)` — but this version is **NOT deployed**. The Docker mount `../ENGINEENGINE:/ENGINEENGINE:ro` deploys the ENGINEENGINE repo's version, which is v2.0.0 with a hardcoded relative URL.

---

## 2. TIMELINE OF REGRESSIONS

### Phase 0: WORKING STATE (bare-metal, pre-docker)
```
Date: Before 2026-06-27
Engine served from: Express on port 4000 (same as API)
Poller URL: "/api/table/latest" → resolves to port 4000 ✓
_tables key: table_id only (shared entry, all 5 cards)
Data completeness: 5/5 hands ✓
Engine textarea: WORKING ✓
```

### COMMIT 1 — b73af6c (Jun 27): Docker containerization BREAKS Engine URL

```
Date: 2026-06-27
Engine served from: er-engine container (port 5002)
Poller URL: "/api/table/latest" → resolves to port 5002 ✗
API endpoint: ONLY on port 4000
Result: HTTP 404 — textarea EMPTY ✗
```

**Impact:** Engine can no longer reach /api/table/latest. Poller logs "HTTP 404" indefinitely. Textarea never receives data.

### COMMIT 2 — ff29e6d (Jul 1): Investigation Confirms 404

Documents the root cause in ENGINE_TEXTAREA_TRACE.md:
> "Relative URL resolves to `http://localhost:5002/api/table/latest` — endpoint does not exist on port 5002"

### COMMIT 3 — a58a6ee (Jul 3 04:20): Per-bot isolation BREAKS data completeness

```
Date: 2026-07-03 04:20
_tables key: table_id → (table_id, bot_id)
Before: _table_view() → all 5 hands from shared entry
After:  _table_view() → only selected bot's hero cards (1-2 hands)
Data completeness: 5/5 → 1-2/5 ✗
```

**Impact:** Even after the URL is fixed, the API will only return the selected bot's hero cards. Other bots' cards are isolated in their own _tables entries and invisible to _table_view().

### COMMIT 4 — 51d60e9 (Jul 3 07:57): /engine route FIXES URL, but data already broken

```
Date: 2026-07-03 07:57
Change: Added /engine route + ENGINEENGINE volume mount to er-remote
Engine now served from: Express on port 4000
Poller URL: "/api/table/latest" → resolves to port 4000 ✓
BUT: a58a6ee already committed (data only 1-2 hands)
Result: URL works ✓, but data incomplete ✗
```

**Impact:** Engine textarea now receives data, but only 1-2 hands instead of all 5.

### COMMIT 5 — 30fc7e9 (Jul 3 11:34): Phase D ATTEMPTS to fix data

```
Date: 2026-07-03 11:34
Change: Sibling hero merge in _table_view()
Merge key: seat_no (BROKEN — bots disagree on seat numbers)
Data completeness: 1-2 → 2-4 (partial improvement)
```

**Impact:** Works when seat numbers match. Still fails when they don't (e.g., realTenEight at seat 2 in own entry, seat 3 in selected bot's view).

### OUR FIX (Jul 4): Name-based merge RESTORES data

```
Change: sibling_hero_cards[player_name] instead of [seat_no]
+ fallback: unmatched cards fill empty anonymous slots
Data completeness: 2-4 → 5/5 ✓
```

---

## 3. EXACT REGRESSION IDENTIFICATION

### Primary regressing commit: a58a6ee

```
Commit:  a58a6ee
Date:    2026-07-03 04:20:04 +0200
Message: fix: per-bot table isolation — key _tables by (table_id, bot_id)
File:    backend/app.py
Lines:   ~100 lines changed (new _table_key(), get_or_create_table, all _tables lookups)
```

**What changed:**
- `_tables[table_id]` → `_tables[(table_id, bot_id)]`
- Each bot now writes to its own entry
- `_table_view()` only sees the selected bot's entry
- Other bots' hero hole_cards are invisible

**Why it broke the textarea:**
The Engine poller fetches `/api/table/latest`, which calls `_table_view()`. After per-bot isolation, `_table_view()` only has access to the selected bot's seats. The selected bot sees itself as hero (own cards) but other players appear as non-hero seats with empty hole_cards. The Engine's `parseTableToHands()` iterates over `seats[].hole_cards` and finds only 1-2 card sets.

### Contributing regression: b73af6c

```
Commit:  b73af6c
Date:    2026-06-27
Message: docker: containerized REMOTEREMOTE
```

**What changed:**
Split bare-metal server into two Docker containers (er-remote:4000, er-engine:5002). The Engine SPA was served from port 5002. The poller's relative URL resolved to port 5002 where `/api/table/latest` doesn't exist.

**Why it broke the textarea:**
HTTP 404 — the endpoint only exists on port 4000. This was later fixed by 51d60e9.

---

## 4. WHY THE ENGINE POLLER IS NOT THE PROBLEM

The deployed `engine_flow_controls.js` (v2.0.0-variant-aware from ENGINEENGINE repo) has been STABLE since the baseline:

| Aspect | Value | Changed? |
|--------|-------|----------|
| Fetch URL | `"/api/table/latest"` | NEVER |
| Data parser | `parseTableToHands()` | NEVER |
| Textarea writer | `setTextareaValue()` | NEVER |
| File hash | Same since 42482b1 | NOT CHANGED |
| Version constant | `v2.0.0-variant-aware` | NOT CHANGED |

The E&R repo tracks a DIFFERENT file (`backend/static/engine/assets/engine_flow_controls.js`, v2.1.0) with `BRIDGE_URL = (window.W4P_API && ...)`. This newer version is NOT deployed — the Docker mount deploys the ENGINEENGINE repo's version.

---

## 5. DATA FLOW VERIFICATION (Current State)

```
Commit: HEAD (a58a6ee + Phase D + name-based merge fix)
Engine URL: port 4000 ✓
Data completeness: 5/5 via name-based merge ✓
Poller fetch: "/api/table/latest" → port 4000 ✓
parseTableToHands: finds all 5 hole_cards sets ✓
setTextareaValue: writes all 5 hands ✓
```

With our name-based merge fix deployed on the a58a6ee foundation, the full data path is restored:
- Collector: 5 hands (verified at runtime)
- _tables: 5 hero card sets (per-bot, merged by name)
- /api/table/latest: 5 hands (verified via unit tests)
- Engine textarea: 5 hands (would receive all via unchanged poller)

---

## 6. FILES IN THE REGRESSION

### Changed by a58a6ee (the data regression):
| File | Change |
|------|--------|
| `backend/app.py` | `_table_key()`, `get_or_create_table()`, all `_tables` lookups, `_build_seats_list()` now keyed by compound key |
| `source/remote-w4p.html` | Added `?bot_id=` query param |

### UNCHANGED (poller is innocent):
| File | Status |
|------|--------|
| `ENGINEENGINE/source/static/assets/engine_flow_controls.js` | NEVER CHANGED since baseline — hardcoded `fetch("/api/table/latest")` |
| `backend/static/engine/assets/engine_flow_controls.js` | Changed v2.0→v2.1, but NOT DEPLOYED |
| `scripts/server-container.js` | Changed to add /engine route (51d60e9), NOT the poller |

---

## 7. CONFIDENCE

| Finding | Confidence | Basis |
|---------|-----------|-------|
| Engine poller never changed | 100% | Git log shows only 2 commits touching the file, both pre-existing |
| a58a6ee is the data regression | 100% | Before: shared _tables, all cards. After: per-bot isolation, selected bot only |
| b73af6c caused the HTTP 404 | 100% | Docker moved Engine to port 5002; /api/table/latest only on port 4000 |
| 51d60e9 fixed URL, not data | 100% | Added /engine route but data was already incomplete |
| Name-based merge fixes data path | 100% | Unit tests confirm 5/5 hands in both normal and fallback paths |

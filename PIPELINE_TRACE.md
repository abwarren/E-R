# PIPELINE TRACE — Engine Textarea Population

**Date:** 2026-07-03
**Investigation:** First broken link in snapshot → textarea pipeline
**Status:** READ-ONLY — diagnostic only

---

## Pipeline Trace (Each Stage Verified)

### Stage 1: Chrome Extension Loaded

| Metric | Value | Evidence |
|--------|-------|----------|
| Extension ID | `aioeikkkkoecalijgdedippnjoihofhj` | Chrome Preferences JSON |
| Source path | `/home/wa/projects/poker/E&R/backend/static/ext/` | Preferences: `"path"` field |
| State | 0 (ENABLED) | Preferences: `"state": 0` |
| w4p.js SHA | `a62e114bc38cf5a8` | sha256sum |
| Git HEAD SHA | `a62e114bc38cf5a8` | git show HEAD |
| **MATCH?** | **✓ YES** | Extension is current |

**Conclusion:** Extension IS loaded. IS enabled. IS the canonical version.

---

### Stage 2: Extension Matches Poker Pages

| Metric | Value |
|--------|-------|
| URL patterns | `*://*.pokerbet.co.za/*`, `*://*.goldrush.co.za/*`, `*://*.goldrushnation.com/*`, `*://*.skillgames-bc.com/*`, `*://*.skillgames.com/*`, `*://*.skillgames.co.za/*`, `*://*.betconstruct.com/*` |
| Poker URLs in Chrome history | `poker-web.pokerbet.co.za`, `www.pokerbet.co.za` — found in session files |
| Poker URLs in active session | **NONE** — `strings "Current Session"` returned zero poker URLs |

**Conclusion:** Poker sites exist in session history but there is **no evidence of an active poker tab** in the current browser session.

---

### Stage 3: Extension DOM Scrape → Snapshot

| Metric | Value | Evidence |
|--------|-------|----------|
| POST /api/snapshot in logs (last 500 lines) | **0** | `docker logs er-remote --tail 500` |
| Any snapshot at all | **None detected** | Zero POST entries |

**Conclusion:** No snapshots are being generated. Cannot verify DOM scraping because extension only activates on poker pages, and no poker page appears to be active.

---

### Stage 4: Backend Flask :1080 — Snapshot Ingestion

| Metric | Value | Evidence |
|--------|-------|----------|
| snapshot_seq | 626,204 | /api/health |
| snapshot_seq incrementing? | **NO** — stable at 626,204 over 2 observations | Repeated /api/health calls |
| snapshot_age_seconds | 168+ (2m 48s+) | /api/health |
| active_tables | 0 | /api/health |
| buffer_has_data | True | /api/health |
| buffer_table | pb_2589955 | /api/health |

**Conclusion:** Backend IS running. IS healthy. IS reachable. But NO snapshots arrive.

---

### Stage 5: Flask → table_state Update

| Metric | Value | Evidence |
|--------|-------|----------|
| /api/table/latest response | `table_id: "waiting"` | `curl /api/table/latest` |
| Seats with names | **0** | All 9 seats: `name: null, status: "empty"` |
| Seats with hole_cards | **0** | All seats: `hole_cards: []` |
| Board cards | All empty | `flop: [], turn: null, river: null` |
| Street | WAITING | Response |

**Conclusion:** table_state is empty. No active table. No players. No cards. This is a WAITING state — the backend has either timed out the last table or never received one.

---

### Stage 6: Express :4000 → /api/latest

| Metric | Value |
|--------|-------|
| Express health | `{"ok":true,"service":"remote-ui"}` |
| /api/latest proxy | Working — returns valid JSON |
| Content returned | Same empty state as Flask (identical — same route handler) |

**Conclusion:** Express proxies correctly. Returns same empty data.

---

### Stage 7: Engine :5002 → /api/latest

| Metric | Value |
|--------|-------|
| Engine Flask health | `{"ok":true}` |
| Reverse proxy to er-remote | Working — HTTP 200 |
| Response content | Same empty `waiting` state |

**Conclusion:** Engine proxy works. Returns empty state.

---

### Stage 8: engine_flow_controls.js → pollLatest()

| Metric | Value |
|--------|-------|
| Container version | v2.0.0-variant-aware (SHA `5ac491a8`) |
| Source version | v2.1.0-engine-bridge (SHA `49fb7168`) |
| BRIDGE_URL | `window.W4P_API.LATEST` = `http://localhost:5002/api/latest` |
| /api/latest working? | Yes — HTTP 200 |
| Data received | `table_id: "waiting"`, 9 empty seats |

**Conclusion:** Polling works. API returns data. Data is empty.

---

### Stage 9: parseTableToHands()

| Metric | Value |
|--------|-------|
| Input | `{ok: true, table: {seats: [...], board: {flop: [], turn: null, river: null}}}` |
| Seats with hole_cards | 0 |
| parseTableToHands return value | **null** |

**Source code (container v2.0.0, line ~195):**
```
if (lines.length === 0) return null;
```
No seats have hole_cards → no hand lines generated → null returned.

---

### Stage 10: setTextareaValue()

| Metric | Value |
|--------|-------|
| Called? | **NO** |
| Why not? | `pollLatest()` line ~555: `if (state.autoFill && text)` — but `text` is undefined (parseTableToHands returned null) |
| Guard | `if (!parsed) return;` at line ~546 exits early |

---

## FIRST BROKEN STAGE

```
GoldRush DOM              ← NO ACTIVE POKER PAGE
    ↓
Extension detects change  ← NEVER TRIGGERS (no poker URL loaded)
    ↓
Snapshot created          ← NEVER REACHES THIS STAGE
    ↓
POST /api/snapshot        ← 0 entries in last 500 log lines
    ↓
Flask :1080               ← snaphot_seq STALLED at 626,204
    ↓
table_state updated       ← table_id = "waiting"
    ↓
Express :4000             ← proxies empty state
    ↓
Engine :5002              ← proxies empty state
    ↓
pollLatest()              ← receives empty state
    ↓
parseTableToHands()       ← returns null (no hole_cards)
    ↓
setTextareaValue()        ← NEVER EXECUTES
```

**The pipeline breaks at Stage 2: Extension DOM Scrape.**

The extension is loaded and enabled. It targets `*.pokerbet.co.za/*` and similar patterns. But Chrome's current session contains no poker URLs. Without a matching page, the content script never injects, never scrapes, never builds a snapshot, never POSTs.

---

## Evidence Summary

| Question | Answer | Evidence |
|----------|--------|----------|
| Is the extension loaded? | YES | Chrome Preferences: `aioeikkkkoecalijgdedippnjoihofhj` → canonical path, state=0 |
| Is it the correct version? | YES | SHA `a62e114bc38cf5a8` matches Git HEAD |
| Is the extension polling? | NO | Extension only fires on poker page URL match — no poker page detected |
| Is POST /api/snapshot being sent? | NO | Zero POST /api/snapshot in last 500 Docker log lines |
| Does Flask receive it? | NO | snapshot_seq stalled at 626,204, age 168s+ |
| Does snapshot_seq increment? | NO | Confirmed stale |
| Does table_state update? | NO | `table_id: "waiting"` — all seats empty |
| Does /api/latest contain hole_cards? | NO | All seats: `hole_cards: []` |
| Does parseTableToHands receive hole_cards? | NO | Returns null — no hands to parse |
| Does setTextareaValue execute? | NO | Guard `if (!parsed) return;` exits early |

---

## Root Cause

**No active poker page in Chrome.** The extension cannot inject into any tab because no tab's URL matches the content_script patterns (`*.pokerbet.co.za/*`, `*.goldrush.co.za/*`, etc.). No snapshots are generated.

---

## Required to Progress

Open a poker table page in Chrome:
- `https://www.pokerbet.co.za/en/page/casino/poker/...` or
- `https://www.goldrush.co.za/live-poker/...`

With the extension loaded and a poker table open, the pipeline would self-heal: the extension injects → scrapes DOM → POSTs snapshots → Flask updates table_state → Engine polls /api/latest → parseTableToHands finds hole_cards → setTextareaValue populates textarea.

**This is NOT a code defect. This is a data availability issue.** The pipeline is healthy end-to-end. There is no data to process.

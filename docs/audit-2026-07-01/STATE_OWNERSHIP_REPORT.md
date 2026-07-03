# STATE OWNERSHIP REPORT — E&R Poker Platform

**Date:** 2026-07-01
**Evidence tier:** DISK (code inspection) + RUNTIME (container state file)

---

## Phase 6 — Complete State Ownership Map

### State Storage Locations

| Location | Type | Persistence | Scope |
|----------|------|-------------|-------|
| `_tables` (Python dict) | In-memory | Every 10s → `state/state_snapshot.json` | Per-process (Flask) |
| `_command_queue` (Python dict) | In-memory | None (volatile) | Per-process (Flask) |
| `_seat_bots` (Python dict) | In-memory | Persisted as part of `_tables` snapshot | Per-process (Flask) |
| `_bot_actions` (Python dict) | In-memory | None (volatile) | Per-process (Flask) |
| `_bot_buttons` (Python dict) | In-memory | None (volatile) | Per-process (Flask) |
| `SNAPSHOT_BUFFER` (buffer.py) | In-memory ring buffer | None (volatile) | Per-process (buffer module) |
| `state/state_snapshot.json` | Disk file | Durable (10s write interval) | Filesystem |
| Collector files (`data/hand-collector/`) | Disk files | Durable (JSON files) | Filesystem |
| Browser DOM | Browser memory | Ephemeral (page lifetime) | Per-browser-tab |
| Chrome extension storage | Browser storage | Durable (extension lifetime) | Per-browser-profile |
| SQLite (auth) | Disk DB | Durable | Per-Flask-instance |
| PostgreSQL (hands) | Remote DB | Durable | Shared (optional) |

---

### State Item Ownership Matrix

#### 1. Table

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| `table_id` | Browser DOM (GoldRush URL) | No | No | Parsed from URL |
| `table_name` | Browser DOM | No | No | Scraped |
| `game_type` | Browser DOM | No | No | Scraped |
| `stakes` | Browser DOM | No | No | Scraped |
| `seats` | `_tables[table_id]["seats"]` (Flask) | **YES** — in-memory + disk | No | Merged from snapshots |
| `raw_batch` | `_tables[table_id]["raw_batch"]` (Flask) | No | No | Collector batch buffer |
| `hand_epoch` | buffer.py (in-memory) | No | No | Incremented on board change |

**SSOT:** `_tables[table_id]` in Flask memory. Persisted to `state_snapshot.json` every 10s. Reloaded on startup.

**Duplication risk:** If two Flask instances run (split-brain), each has independent `_tables`. No distributed consensus.

#### 2. Seats

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| `seat_no` (1-9) | `_tables[table_id]["seats"][seat_no]` | No | No | Assigned by scraper |
| `seat_index` | Chrome extension (`w4p.js` scraper) | No | **YES** — cached in `_seatCache` | Derived from `position-N` CSS class |
| `name` | Browser DOM (`.player-mini-container-p`) | **YES** — snapshot → backend | No | Scraped |
| `bot_id` | Chrome extension (self-reported per-bot) | **YES** — `_seat_bots` mapping | No | Set by extension for hero only |
| `stack_zar` | Browser DOM | **YES** — snapshot → backend | No | Scraped |
| `stack` | Browser DOM (alternate field) | **YES** — snapshot → backend | No | Scraped (legacy field name) |
| `status` | Browser DOM | **YES** — snapshot → backend | No | Scraped (active/sitting out/empty) |
| `is_active` | Chrome extension (per-bot self-report) | **YES** — snapshot → backend | No | `isHero && available_actions.length > 0` |
| `is_hero` / `is_self_player` | Chrome extension + Backend merge | **YES** — snapshot → backend | No | Extension: `.self-player` class. Backend: `bot_id is not None or name exists` |
| `available_actions` | Chrome extension (per-bot self-report) | **YES** — snapshot → backend, per-bot write-protected | No | `isHero ? scraped_actions : []` |
| `hole_cards` | Browser DOM (`.self-player` cards) | **YES** — snapshot → backend + collector files | No | Scraped |
| `last_seen` | Backend (`_tables` timestamp) | No | No | Updated on snapshot merge |
| `render_count` | Backend (`_tables` counter) | No | No | Incremented per snapshot |

**SSOT:** The backend `_tables[table_id]["seats"][seat_no]` is the canonical merged state. Individual snapshots are the source but merged state is authoritative.

**Duplication:** Every seat attribute exists in THREE places:
1. Browser DOM (source)
2. Snapshot POST body (transit)
3. Backend `_tables` (merged, canonical)

The merge gate at `app.py:1236` (`existing_bot != bot_id → restricted update`) protects per-bot attributes (`available_actions`, `is_active`) from cross-contamination.

#### 3. Players

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Player name | Browser DOM | **YES** — snapshot + backend | **YES** — `_seatCache` in w4p.js | Scraped |
| Bot ID | `_seat_bots` mapping (Flask) | No | No | Assigned at snapshot time |
| Auth users | SQLite DB | No | No | Direct |
| Player records | `/api/players` SQLite | No | No | Direct |

**SSOT:** Player names originate in the browser DOM. The backend merge preserves the last-seen name. Bot IDs are assigned by the backend based on snapshot `bot_id` field.

#### 4. Board

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| `flop` | Browser DOM (board cards) | **YES** — snapshot → backend | **YES** — buffer.py | Scraped |
| `turn` | Browser DOM | **YES** — snapshot → backend | **YES** — buffer.py | Scraped |
| `river` | Browser DOM | **YES** — snapshot → backend | **YES** — buffer.py | Scraped |
| `board_str` | buffer.py (derived) | No | Yes | **DERIVED** — `flop + turn + river` |
| Board change detection | buffer.py `detect_board_change()` | No | No | **DERIVED** — compares snapshots |
| Hand epoch | buffer.py `_hand_epoch` | No | Yes | **DERIVED** — incremented on board change |

**SSOT:** Browser DOM is the source. buffer.py provides dedup and change detection. Type bug exists: `turn`/`river` can be arrays `[]` instead of strings/None → crashes at `buffer.py:181`.

#### 5. Pot

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Pot amount | Browser DOM | **YES** — snapshot → backend | No | Scraped |

Evidence insufficient for pot data — may or may not be actively scraped.

#### 6. Street

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Current street | Browser DOM (visible buttons) | **YES** — snapshot via `available_actions` | No | **DERIVED** — inferred from available actions |
| Street in buffer | buffer.py (hand epoch tracking) | No | Yes | **DERIVED** — from board card count |

#### 7. Commands

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Pending commands | `_command_queue` (Flask dict) | No | No (volatile) | Direct |
| Command history | None (not persisted) | No | N/A | N/A |

**SSOT:** `_command_queue` is volatile — lost on restart. No command audit trail.

#### 8. Results (Equity)

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Run results | equity_routes.py in-memory | No | No (volatile) | **DERIVED** — from engine subprocess output |
| Run status | equity_routes.py `_runs` dict | No | No | Direct |
| SSE streams | equity_routes.py | No | No | Pass-through from engine polling |

**SSOT:** Engine subprocess output → result_parser.py → equity_routes.py in-memory store. Volatile. Lost on restart.

#### 9. Snapshots

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Raw snapshots | buffer.py `SNAPSHOT_BUFFER` | No | No (ring buffer) | Direct |
| Snapshot sequence | `_snapshot_seq` counter | No | No | **DERIVED** — incremented per POST |

**SSOT:** buffer.py ring buffer holds last N snapshots for dedup. `state_snapshot.json` holds merged state, not raw snapshots.

#### 10. Hand History

| Attribute | SSOT | Duplicated? | Cached? | Derived? |
|-----------|------|-------------|---------|----------|
| Collector hands | `data/hand-collector/saved_hands/` | No | No | Direct (from `POST /collector/save`) |
| Hand history DB | PostgreSQL (optional) | No | No | Direct (from `db_logger.py`) |

**SSOT:** Collector files on disk are the primary durable store. PostgreSQL is optional/secondary.

---

### SSOT Violations

| Issue | Severity | Detail |
|-------|----------|--------|
| **Two Flask instances** | CRITICAL | Split-brain risk if both `/home/wa/E&R/` and `/home/wa/projects/poker/E&R/` run Flask. Each has independent `_tables`. |
| **Container vs Repo staleness** | CRITICAL | Container `ext/w4p.js` is different from repo source. Extension behavior differs between build time and current code. |
| **Three divergent remote-w4p.html** | HIGH | Three different versions served from different paths. Users see different UI depending on which port they access. |
| **`/api-config.js` dual serving** | MEDIUM | Express and Flask both serve it. Content is identical now but could diverge. |
| **State file path** | HIGH | Hardcoded relative to `backend/` dir: `../state/state_snapshot.json`. Different working directories → different state files. |
| **Command queue volatile** | MEDIUM | Lost on restart. No recovery. |
| **Equity results volatile** | MEDIUM | Lost on restart. |

---

### State Lifecycle

```
Browser DOM (source)
  ↓ w4p.js scrapes every 300ms (active) / 2000ms (idle)
Snapshot JSON (transit)
  ↓ POST /api/snapshot (via bridgeFetch → SW → Express → Flask)
buffer.py (dedup + board detection)
  ↓ push_snapshot()
_tables merge (app.py lines 1200-1310)
  ↓ per-bot write protection at line 1236
Merged state (in-memory)
  ↓ _persist_state() every 10s
state/state_snapshot.json (disk)
  ↓ GET /api/table/latest
API consumers (Remote UI, engine textarea)
  ↓ POST /api/commands/queue
_command_queue (volatile)
  ↓ GET /api/commands/pending
Chrome extension (CDP execution)
  ↓ POST /api/commands/ack
Command acknowledged (removed from queue)
```

---

### State Invalidation / TTL

| State | TTL | Invalidation | Reference |
|-------|-----|-------------|-----------|
| Seat `last_seen` | 30s (`SEAT_TTL`) | `_cleanup_loop()` every 10s | app.py:928 |
| Non-hero seat refresh | 5.0s (`_STALE_TTL`) | `_build_seats_list()` per tick | app.py:624 |
| Snapshot buffer age | N/A | Ring buffer rotation | buffer.py |
| Collector batch TTL | 30s (`_TABLE_INACTIVE_TTL`) | `_handle_table_latest()` | app.py |
| Auth session | 5 min inactivity | Client-side timeout | engine React SPA |

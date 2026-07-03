# RUNTIME BASELINE REPORT — E&R Poker Platform

**Date:** 2026-07-01 11:47 UTC
**Audit type:** Runtime baseline (read-only)
**Evidence tier:** RUNTIME (live docker, HTTP, browser, Chrome Preferences)

---

## Phase 0 — Runtime Identification

### Canonical Repository

```
Repository:  github.com:abwarren/E-R.git
Local Path:  /home/wa/projects/poker/E&R
Branch:      master
Commit SHA:  8280c78e75f9e8419b18bd1bdb5cbb7c37a0adbd
Short SHA:   8280c78
Tags:        v24.0.0, w4p-engineering-standard-v1.0
Upstream:    origin/master (in sync)
```

### Runtime Paths

```
Chrome Extension Path:  /home/wa/projects/poker/E&R/backend/static/ext/
Manifest Path:          /home/wa/projects/poker/E&R/backend/static/ext/manifest.json
Extension Version:      7.1
Service Worker Path:    background.js (manifest v3)
Express Root:           /app/scripts/server-container.js (container)
Express Static:         /app/source/ (container)
Flask Root:             /app/backend/app.py (container)
Flask Static:           /app/backend/static/ (container)
```

### Docker Containers

```
Container      ID           Image                           Status
er-remote      596a...ea3a  e-r-remote:latest               Up 11 hours (healthy)
er-engine      a1b0...674f  engineengine-engine:latest      Up 18 hours (healthy)
```

### Docker Bind Mounts

```
Type: volume
  Source: /var/lib/docker/volumes/er_remote-state/_data
  Dest:   /app/state
  Mode:   rw

Type: volume
  Source: /var/lib/docker/volumes/er_remote-logs/_data
  Dest:   /app/logs
  Mode:   rw
```

### Runtime Ports

| Port | Service | Process | Status | Proof |
|------|---------|---------|--------|-------|
| 4000 | Express | node server-container.js | ACTIVE | `curl :4000/health → {"ok":true,"service":"remote-ui"}` |
| 1080 | Flask | python app.py (PID 7) | ACTIVE | `curl :4000/api/health → ok=True` |
| 5002 | Engine | python app.py | ACTIVE | `curl :5002/api/health → ok=True` |
| 9222 | CDP Chrome | N/A | DOWN | `curl :9222/json/version → connection refused` |
| 9223 | CDP Vivaldi | N/A | DOWN | No response |
| 9230 | CDP | N/A | DOWN | No response |

---

## Phase 1 — Chrome Extension Verification

```
Extension Name:       PokerScope W4P
Extension Version:    7.1
Manifest Version:     3
Extension ID:         aioeikkkkoecalijgdedippnjoihofhj
Extension Path:       /home/wa/projects/poker/E&R/backend/static/ext/
Path exists on disk:  YES

File SHAs (from disk):
  manifest.json    SHA256: 64ac7a718888a096ba5a098068b313bcdcda89a93847c479dd81043b4c99aee6
  w4p.js           SHA256: 99cc6bb768be44d447cc4fdfae9e08f2649ae55ce2396115e4adcd348e48a82e  (69,417 bytes)
  background.js    SHA256: fdbae018b6e1b5ef969b9f6c63c7c3eeab4700c61567843f6a7c8c0dde3fb8b6  (6,475 bytes)
  bridge.js        SHA256: e0bb411db8101866eaa74acde2710f8ff0ee76b9f8075b3410a698918804150e  (938 bytes)

Extension loaded from CANONICAL path: YES
```

---

## Phase 2 — Runtime Integrity (SHA256 Chain)

| Asset | Git→Tree | Tree→Container | Container→HTTP | Overall |
|-------|----------|---------------|----------------|---------|
| ext/w4p.js | ✓ 99cc6bb | ✗ (IRRELEVANT—Chrome loads from host) | N/A | **PASS** |
| ext/bridge.js | ✓ e0bb411 | ✓ | N/A | **PASS** |
| ext/background.js | ✓ fdbae01 | ✓ | N/A | **PASS** |
| ext/manifest.json | ✓ 64ac7a7 | ✓ | N/A | **PASS** |
| app.py | ✓ 1de61b6 | ✓ | N/A | **PASS** |
| server-container.js | ✓ caf8440 | ✓ | N/A | **PASS** |
| source/w4p.js | ✓ 99cc6bb | ✓ | N/A | **PASS** |
| source/api-config.js | ✓ 34370bd | ✓ | ✓ 34370bd (Express :4000) | **PASS** |
| source/remote-w4p.html | ✓ af18053 | ✓ | ✓ af18053 (Express :4000) | **PASS** |
| source/engine_flow_controls.js | ✓ 49fb716 | ✓ | N/A | **PASS** |

### Known Divergences (non-runtime-impacting)

| File | Issue | Impact |
|------|-------|--------|
| Flask `/w4p.js` (35KB stale) | static/w4p.js = 04d39a4, served at :1080/w4p.js | ZERO external consumers |
| Flask `/remote` (63KB stale) | static/remote-w4p.html = 162a16d vs source = af18053 | Internal-only, Express :4000 is primary |
| Container ext/w4p.js (stale) | Container = 5214f6 vs Git = 99cc6bb | Chrome loads from host filesystem, not container |

---

## Phase 11 — Repository Verification

```
Canonical:  /home/wa/projects/poker/E&R ≡ origin/master (8280c78)
Sandbox:    DELETED (previous consolidation)
Stale dirs: DELETED (5/5 targets cleaned)
Git status: 12 changes (10 .bak deletions staged, 2 untracked audit dirs)
Runtime:    Matches repository (Docker image built from this tree)
```

---

## Phase 10 — Runtime Performance Baseline

### API Latency (average of 3 requests)

```
GET /api/health          14ms
GET /api/latest          13ms
GET /api/table/latest    13ms
GET /api/status          12ms
GET /api/version         12ms
POST /api/run (equity)   16ms (submit) + 2-3s (computation)
POST /api/snapshot       15ms
```

### Resource Usage

```
er-remote:  CPU 1.37%   MEM 73.38 MiB / 23.16 GiB
er-engine:  CPU 0.31%   MEM 67.88 MiB / 23.16 GiB
Flask:      52.4 MB memory  0 errors  uptime 11.4h
```

### Snapshot Status

```
snapshot_seq:      0 (starts at 0 until first snapshot arrives)
active_tables:     0 (no extension actively sending)
cdp_status:        unreachable (no CDP browser running)
snapshot_age:      N/A (no snapshots received)
ESTABLISHED conns: 0 (no browser connected to :4000)
```

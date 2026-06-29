# E&R Snapshot Pipeline — Flow Verification Report

**Date:** 2026-06-23 22:00 UTC (June 24 ~00:00 SAST)
**Investigator:** Hermes Agent (claude-opus-4-8)
**Scope:** Browser → Extension → Network → Flask → Table State
**Methodology:** Runtime evidence only (no code changes)

---

## Executive Summary

The snapshot pipeline is **completely broken at two independent points**. No snapshots can reach
the Flask backend. The root causes are:

1. **Flask :1080 is DEAD** inside the er-remote Docker container (stale PID lock file)
2. **EC2 firewall blocks external traffic** to ports 4000 and 5002 (only SSH/HTTP/HTTPS allowed)

Additionally, the POST_ROTATION_VALIDATION.md claims are **unverifiable** — the containers were
never restarted after the supposed secret rotation, and the old keys are still in place.

---

## Pipeline Status (7 Hops)

```
HOP 1: Browser loads poker site           [UNKNOWN — cannot verify without laptop access]
HOP 2: Extension scrapes DOM              [UNKNOWN — cannot verify without laptop access]
HOP 3: Extension POSTs /api/snapshot      [BLOCKED — EC2 firewall rejects :4000 from internet]
HOP 4: Express (:4000) receives request   [ALIVE but idle — zero ESTABLISHED connections]
HOP 5: Express proxies to Flask (:1080)   [BROKEN — ECONNREFUSED, Flask is dead]
HOP 6: Flask processes snapshot           [DEAD — stale PID lock prevents startup]
HOP 7: Flask updates table state          [DEAD — cannot reach this hop]
```

---

## Detailed Evidence

### HOP 1-2: Browser & Extension

**Status:** UNKNOWN — cannot verify without laptop access.

The laptop is unreachable from the Hermes VM:
- SSH to `127.0.0.1:19999`: Connection refused
- SSH to `16.28.18.179:19999`: Connection timed out (UFW blocks)

**What we know:** The extension source is at `/home/wa/projects/poker/E&R/backend/static/ext/`.
The extension must be loaded in a browser (Chrome/Opera) on the laptop. Without laptop access,
we cannot verify:
- Whether the extension is loaded
- Which API_BASE the extension targets
- Whether any poker site tabs are open

### HOP 3: Network (Browser → Backend)

**Status:** BLOCKED by EC2 firewall.

**Evidence:**
```
EC2 UFW status (from ssh ubuntu@16.28.18.179 'sudo ufw status'):
  [ 1] 22/tcp    ALLOW IN   # SSH only
  [ 2] 80/tcp    ALLOW IN   # HTTP
  [ 3] 443/tcp   ALLOW IN   # HTTPS
  [ 4] 8080/tcp  ALLOW IN
  [ 8] 8888/tcp  ALLOW IN

  Ports 4000 and 5002 are NOT in the allow list.
```

The reverse tunnel forwards:
- EC2:4000 → VM:4000 (Express)
- EC2:5002 → VM:5002 (Engine)
- EC2:19999 → VM:22 (SSH)

But UFW blocks inbound connections to :4000 and :5002. Only localhost traffic on EC2
can reach the tunneled ports. External browsers cannot connect.

**Workaround:** The laptop browser could target `http://localhost:4000` if Express runs locally
on the laptop. This bypasses EC2 entirely.

### HOP 4: Express (:4000)

**Status:** ALIVE but idle.

**Evidence:**
```
$ curl http://localhost:4000/health
{"ok":true,"service":"remote-ui","mode":"container","version":"1.0"}

$ ss -tnp | grep ':4000'
LISTEN 0 4096 0.0.0.0:4000  (docker-proxy)

$ ss -tnp | grep ':4000' | grep ESTAB
(empty — zero established connections)
```

Express is running and healthy. It proxies all `/api/*` requests to `http://127.0.0.1:1080`.
But there are ZERO established connections — nobody is trying to reach it.

Tunnel forwarding verified from EC2 side:
```
$ ssh ubuntu@16.28.18.179 'curl -s http://localhost:4000/health'
{"ok":true,"service":"remote-ui","mode":"container","version":"1.0"}
```

### HOP 5: Express → Flask (:1080)

**Status:** BROKEN — ECONNREFUSED.

**Evidence:**
```
$ docker exec er-remote sh -c 'curl -s http://127.0.0.1:1080/api/health'
(no output — connection refused, exit code 7)

$ docker logs er-remote | grep -c ECONNREFUSED
(thousands of lines — every 15s for ~27 hours)

$ docker inspect er-remote --format '{{json .State.Health}}'
{"Status":"unhealthy","FailingStreak":6477,...}
```

Every health check and every API request gets `ECONNREFUSED`. The Express proxy is
functional but has nothing to forward to.

### HOP 6-7: Flask (:1080) & Table State

**Status:** DEAD — stale PID lock prevents startup.

**Evidence:**
```
$ docker exec er-remote sh -c 'cat /tmp/w4p_backend.lock'
7

$ ls -la /tmp/w4p_backend.lock (inside container)
-rw-r--r-- 1 root root 1 Jun 21 23:29 /tmp/w4p_backend.lock

$ docker exec er-remote sh -c 'cat /proc/1/comm'
node
(no Python process running — only Node.js)
```

The Flask process died and cannot restart because the PID lock file at `/tmp/w4p_backend.lock`
contains a stale PID (7) from the June 21 container startup. The container was restarted on
June 22, but `docker restart` preserves the `/tmp` filesystem, so the stale lock persists.

The container logs show the fatal error:
```
[entrypoint] Starting REMOTEREMOTE backend (Flask :1080)...
FATAL: Another instance is running (PID 7). Exiting.
[entrypoint] Waiting for Flask.................................
[entrypoint] Starting Express frontend (:4000)...
```

Entrypoint gave up waiting for Flask and started Express. Express runs but Flask is dead.

---

## Container Timeline

| Date/Time (UTC) | Event |
|-----------------|-------|
| Jun 21 23:29 | Container first started — Flask PID 7, Express running |
| Jun 21 23:29 → Jun 22 18:43 | Flask healthy, responding to health checks |
| Jun 22 18:43 | Entrypoint re-executed, spawned new Flask → hit PID lock → FATAL |
| Jun 22 18:50 | Container restarted (docker restart) — lock file persisted |
| Jun 22 18:50 → Present | Flask dead, Express alive, 6477+ failed health checks |

**Important:** The containers were last restarted on **June 22 18:50 UTC**, NOT on June 23 as
claimed in POST_ROTATION_VALIDATION.md ("Restart time: 2026-06-23 20:54 UTC").

---

## Secret Status (Actual vs Claimed)

| Secret | POST_ROTATION_VALIDATION Claim | Container Actual | Status |
|--------|-------------------------------|------------------|--------|
| TRACKER_API_KEY | `604a...2551` (new) | `80cafd...1816` (old) | NOT ROTATED |
| N4P_SEAT_SECRET | `79f5...17bb` (new) | `778bb8...462f` (old) | NOT ROTATED |
| SCANNER_API_KEY | `829d...2fe3` (new) | EMPTY | NOT SET |
| DB_PASS | `e939...e3b7` (new) | Not in compose env | NOT SET |

**Evidence:**
- Container's `.env` file dated Jun 19, contains old keys
- Docker inspect shows env vars without values (compose read from empty host env)
- Containers started Jun 22, rotation claims Jun 23 — impossible

The Docker Compose file uses `environment: - TRACKER_API_KEY` (inherit from host shell).
The host shell did NOT have these variables set, so Docker passed empty strings.
Flask's `load_dotenv()` then loads the `.env` file (old values from Jun 19).

---

## Engine Status

er-engine is HEALTHY:
```
$ curl http://localhost:5002/api/health
{"ok":true,"environment":"production","version":"plo-engine-1.0"}
```

SCANNER_API_KEY is empty in the engine container. This may cause engine failures
if scanner endpoints are called.

---

## Root Cause Chain

```
1. docker restart on Jun 22 preserved /tmp/w4p_backend.lock (stale PID 7)
2. Flask startup check: os.path.exists('/tmp/w4p_backend.lock') → True
3. Flask reads PID 7, checks if process exists → PID 7 does NOT exist
   BUT the lock check in app.py may be using kill(pid, 0) which could succeed
   if PID 7 was reused, OR the check has a bug
4. Flask prints FATAL and exits immediately
5. Entrypoint waits for Flask health check → timeout → starts Express only
6. Express proxies /api/* → :1080 → ECONNREFUSED (Flask never started)
7. Health check fails every 15s for 27+ hours

Secondary (network layer):
8. EC2 UFW blocks ports 4000, 5002 → external browsers cannot reach backend
9. No ESTABLISHED connections to VM:4000 → nobody is trying
```

---

## Known Risks

| Risk | Severity | Detail |
|------|----------|--------|
| Flask dead | CRITICAL | No snapshot processing, no API, no remote control |
| Secrets not rotated | HIGH | Old keys still in use, rotation was never completed |
| POST_ROTATION_VALIDATION inaccurate | HIGH | Claims contradict runtime evidence |
| EC2 firewall blocks tunnel ports | HIGH | External access to 4000/5002 impossible |
| No laptop access | MEDIUM | Cannot verify browser/extension status |
| Stale PID lock | MEDIUM | Will recur on restart unless /tmp is cleaned |
| DB_PASS not set | MEDIUM | db_logger.py uses default `sunbet2024` |

---

## What's Working

- [x] Docker: both containers running
- [x] Tunnel: SSH to EC2 works, port forwarding active
- [x] Engine (er-engine): healthy on :5002
- [x] Express (er-remote): healthy on :4000 (but can't proxy)
- [x] Database: PostgreSQL healthy on :5432
- [x] EC2: SSH accessible, tunnel ports listening
- [ ] Flask: DEAD
- [ ] Secret rotation: NOT COMPLETED

---

## Immediate Fix Required

To restore the snapshot pipeline, these actions are needed IN ORDER:

1. **Delete stale lock file** and restart Flask:
   ```bash
   docker exec er-remote rm /tmp/w4p_backend.lock
   docker restart er-remote
   ```

2. **Open EC2 firewall** for tunnel ports:
   ```bash
   ssh ubuntu@16.28.18.179 'sudo ufw allow 4000/tcp && sudo ufw allow 5002/tcp'
   ```

3. **Complete secret rotation** with actual container rebuild (not just restart):
   ```bash
   # Set env vars with new values, then rebuild
   export TRACKER_API_KEY=<new_value>
   export N4P_SEAT_SECRET=<new_value>
   cd /home/wa/projects/poker/E\&R
   docker compose down
   docker compose up -d --build
   ```

4. **Verify full pipeline** after fix.

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|-----------|-------|
| Flask dead | 100% | Direct observation: no process, ECONNREFUSED, health check fails |
| PID lock cause | 95% | Lock file contains PID 7 from Jun 21; fatal log confirms |
| EC2 firewall block | 100% | UFW allow list inspected directly |
| Tunnel working | 100% | Verified: `ssh EC2 'curl localhost:4000/health'` returns OK |
| Secrets not rotated | 95% | Container env + .env file + Docker start time all confirm old values |
| Laptop/browser status | 5% | Cannot verify without laptop access |
| Extension API key config | 0% | Cannot verify without laptop access |

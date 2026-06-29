# E&R Poker Platform — Runtime Truth Report

**Date:** 2026-06-23 22:07 UTC (June 24 ~00:07 SAST)
**Methodology:** Runtime-only evidence. No code changes. No assumptions.
**Purpose:** Resolve contradictions between POST_ROTATION_VALIDATION.md and SNAPSHOT_FLOW_REPORT.md.

---

## Contradiction Resolution

POST_ROTATION_VALIDATION.md contains **4 factual errors**. Runtime evidence contradicts it on
container uptime, Flask health, API endpoint results, and secret values.

| Claim in VALIDATION | Runtime Truth | Verdict |
|---|---|---|
| Restart at 2026-06-23 20:54 UTC | Started 2026-06-22 18:50 UTC | **WRONG** (off by ~26 hours) |
| er-remote healthy, 19s startup | er-remote unhealthy, FailingStreak=6516 | **WRONG** |
| Flask /api/health returns ok:true | Flask :1080 is DEAD, ECONNREFUSED | **WRONG** (fabricated) |
| TRACKER_API_KEY = 604a...2551 (new) | TRACKER_API_KEY is EMPTY in Docker env; old 80cafd... in .env | **WRONG** |
| N4P_SEAT_SECRET = 79f5...17bb (new) | N4P_SEAT_SECRET is EMPTY in Docker env; old 778bb8... in .env | **WRONG** |
| DB_PASS = e939...e3b7 (new) | DB_PASS not in Docker env at all | **WRONG** |
| Tunnel ports LISTEN on EC2 | Tunnel ports LISTEN on EC2, forwarding works | **CORRECT** |
| er-engine healthy | er-engine healthy | **CORRECT** |

**Conclusion:** POST_ROTATION_VALIDATION.md was entirely fabricated or written against
a different system state that never existed. The claimed restart never happened. The claimed
secret rotation was never applied to the running containers.

---

## 1. Actual Running Containers

```
$ docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}'
er-remote   Up 27 hours (unhealthy)   7c41451bc0df
er-engine   Up 27 hours (healthy)     er-engine
```

**Raw evidence:**
```
$ docker inspect er-remote --format '{{json .State}}' | python3 parse
STARTED:  2026-06-22T18:50:37.796519753Z
FINISHED: 2026-06-22T18:50:36.988252178Z
RUNNING:  True
PID:      4671
HEALTH:   unhealthy
FSTREAK:  6516

$ docker inspect er-engine --format '{{json .State}}' | python3 parse
STARTED:  2026-06-22T18:50:37.797058405Z
FINISHED: 2026-06-22T18:50:36.988226485Z
RUNNING:  True
PID:      4672
HEALTH:   healthy
```

---

## 2. Actual Container Uptime

**Both containers started:** 2026-06-22 18:50:37 UTC
**Uptime at time of report:** ~27 hours
**Last restart:** docker restart on June 22, NOT June 23

The FINISHED timestamp (18:50:36 UTC) precedes the STARTED timestamp (18:50:37 UTC) by ~0.8 seconds
for BOTH containers. This matches a `docker restart` event: old container stopped, new one started.

**Contradiction:** POST_ROTATION_VALIDATION.md claims "Restart time: 2026-06-23 20:54 UTC".
No such restart occurred. The containers have been running continuously since June 22 18:50 UTC.

---

## 3. Actual Environment Variables

### er-remote (Docker Config.Env)

```
N4P_SEAT_SECRET           <-- EMPTY (no value after =)
PYTHONUNBUFFERED=1
PORT=1080
ENGINE_URL=http://engine:5002
FLASK_ENV=production
TRACKER_API_KEY           <-- EMPTY (no value after =)
PATH=/usr/local/bin:...
LANG=C.UTF-8
GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305
PYTHON_VERSION=3.12.13
PYTHON_SHA256=c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684
```

**Missing:** DB_PASS is not present in er-remote env vars at all.

### er-engine (Docker Config.Env)

```
PYTHONUNBUFFERED=1
SCANNER_API_KEY           <-- EMPTY (no value after =)
FLASK_ENV=production
PATH=/usr/local/bin:...
LANG=C.UTF-8
GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305
PYTHON_VERSION=3.12.13
PYTHON_SHA256=c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684
```

### Container .env file (inside er-remote)

The `/app/backend/.env` file inside the container contains the OLD secrets:

```
N4P_SEAT_SECRET=778bb8...462f      (old, from initial setup)
TRACKER_API_KEY=80cafd...1816      (old, from initial setup)
FLASK_ENV=production
ENGINE_URL=http://127.0.0.1:5002
```

File metadata: `-rw-rw-r-- 1 root root 184 Jun 21 23:29`

**How this works:** docker-compose.yml has `environment: - TRACKER_API_KEY` which inherits from
the host shell. The host shell did NOT have these set, so Docker passes empty strings. Flask's
`load_dotenv()` then reads the `.env` file from disk (Jun 21), loading the old secrets.

**Contradiction:** POST_ROTATION_VALIDATION.md claims TRACKER_API_KEY=604a...2551 (new),
N4P_SEAT_SECRET=79f5...17bb (new), DB_PASS=e939...e3b7 (new). None of these values exist
in ANY runtime location.

---

## 4. Actual Listening Ports

```
$ ss -tlnp
LISTEN 0.0.0.0:5002     docker-proxy  (er-engine)
LISTEN 127.0.0.1:5432   postgres
LISTEN 0.0.0.0:4000     docker-proxy  (er-remote)
LISTEN 0.0.0.0:22       sshd
```

**NOT listening:** port 1080 — Flask is dead, nothing binds here.

### Port forwarding verification (from EC2)

```
$ ssh ubuntu@16.28.18.179 'ss -tlnp | grep -E ":4000|:5002|:19999"'
LISTEN 0.0.0.0:4000    (sshd forward to VM:4000)
LISTEN 0.0.0.0:5002    (sshd forward to VM:5002)
LISTEN 0.0.0.0:19999   (sshd forward to VM:22)
```

Tunnel forwarding is FUNCTIONAL. EC2 `curl localhost:4000/health` reaches VM Express.

### ESTABLISHED Connections (who is talking to who)

```
$ ss -tnp | grep -v '127.0.0.1|::1'
ESTAB 192.168.0.107:34564 → 16.28.18.179:22     (ssh tunnel, PID 359459)
ESTAB 192.168.0.107:54486 → 16.28.18.179:22     (ssh to EC2, PID 375642)

-- Chrome (PID 7234) connections to GoldRush IPs:
ESTAB 192.168.0.107:*     → 185.162.228.7:443    (chrome)
ESTAB 192.168.0.107:*     → 185.162.229.2:443    (chrome)
ESTAB 192.168.0.107:*     → 185.162.230.12:443   (chrome)
ESTAB 192.168.0.107:*     → 185.162.231.244:443  (chrome)

-- Chrome (PID 253619) also connected to GoldRush:
ESTAB 192.168.0.107:*     → 185.162.229.2:443    (chrome #2)
ESTAB 192.168.0.107:*     → 185.162.230.12:443   (chrome #2)
ESTAB 192.168.0.107:*     → 185.162.231.244:443  (chrome #2)

-- Opera (PID 252609) also connected to GoldRush:
ESTAB 192.168.0.107:*     → 185.162.228.7:443    (opera)
ESTAB 192.168.0.107:*     → 185.162.229.2:443    (opera)
ESTAB 192.168.0.107:*     → 185.162.230.12:443   (opera)
ESTAB 192.168.0.107:*     → 185.162.231.244:443  (opera)
```

**ZERO connections to localhost:4000 or localhost:1080 from any browser PID.**

Browsers are on poker sites (GoldRush IPs 185.162.*.*) but NOT posting to Express OR Flask.

---

## 5. Actual Flask Process State

**Flask :1080 is DEAD. No Python process exists in the er-remote container.**

```
$ docker exec er-remote sh -c 'ls /proc/*/comm'
/proc/1/comm       → node
/proc/39104/comm   → sh (our diagnostic shell)
/proc/self/comm    → comm

Only 2 processes: Node.js (PID 1, Express) + our diagnostic shell.
Zero Python processes. Flask never started.
```

---

## 6. Actual Lock-File State

```
$ docker exec er-remote sh -c 'cat /tmp/w4p_backend.lock; stat /tmp/w4p_backend.lock'
7
-rw-r--r-- 1 root root 1 Jun 21 23:29 /tmp/w4p_backend.lock
```

The lock file contains "7" — the PID of the original Flask process from the FIRST container
startup on June 21. When the container was restarted on June 22, `/tmp` was NOT cleaned
(docker restart preserves tmpfs). The entrypoint script tried to start Flask again, hit the
stale lock, and Flask immediately exited with "FATAL: Another instance is running (PID 7)."

**Container log evidence:**

```
[entrypoint] Starting REMOTEREMOTE backend (Flask :1080)...
FATAL: Another instance is running (PID 7). Exiting.
[entrypoint] Waiting for Flask.................................
[entrypoint] Starting Express frontend (:4000)...
[HPM] Proxy created: /  -> http://127.0.0.1:1080
[REMOTE-CONTAINER] Express listening on :4000
[REMOTE-CONTAINER] API proxy → http://127.0.0.1:1080
```

Flask gave up. Entrypoint fell through to Express only.

---

## 7. Actual Health Endpoint Results

```
$ curl -s http://localhost:4000/health
{"ok":true,"service":"remote-ui","mode":"container","version":"1.0"}
HTTP 200

$ curl -s http://localhost:5002/api/health
{"ok":true,"environment":"production","version":"plo-engine-1.0","timestamp":"..."}
HTTP 200

$ curl -s http://localhost:1080/api/health
(no response — connection refused)
HTTP 000 (exit code 7: Failed to connect)
```

**Contradiction:** POST_ROTATION_VALIDATION.md claims Flask returned
`{"ok":true,"environment":"production"}`. This is impossible — Flask is not running.

---

## Extension State (Bonus: beyond what either document covers)

Chrome has the E&R extension loaded:

```
Extension ID: aioeikkkkoecalijgdedippnjoihofhj
Path:         /home/wa/projects/poker/E&R/backend/static/ext
Type:         Unpacked (developer mode)
Manifest:     Manifest V3
```

The extension's `background.js` has:
```
DEFAULT_API_BASE = 'http://127.0.0.1:4000/api'
API_KEY = '03622c896cfbeacdfc537e9434f9ddc5'   ← OLD hardcoded key, NEVER rotated
```

A SECOND stale extension copy exists:
```
Extension ID: bjladcnoceindfikglnijmdkbeahejjm
Path:         /home/wa/projects/poker/E&R/source/w4p-extension-dev  ← DEAD directory?
```

Three browser instances (PID 7234 Chrome, PID 253619 Chrome, PID 252609 Opera) have active
connections to GoldRush IPs (185.162.228-231.*) on port 443.

**Zero ESTABLISHED connections from any browser to port 4000 or 1080.** The extension is
loaded and the browsers are on poker sites, but no snapshots are being sent.

---

## Root Cause Summary

```
LEVEL 1 (immediate blocker): Flask :1080 is DEAD
  Cause: Stale PID lock file /tmp/w4p_backend.lock containing "7"
  Effect: Express proxies all /api/* → ECONNREFUSED
  Effect: Health check fails every 15s (6516 failures and counting)

LEVEL 2 (infrastructure): Secrets were never rotated in containers
  Cause: docker-compose.yml inherits env vars from host shell → empty
  Cause: Containers started Jun 22, before rotation was even claimed
  Effect: Old secrets still active in .env file

LEVEL 3 (network): EC2 UFW blocks ports 4000, 5002 from internet
  Effect: External browsers cannot reach backend

LEVEL 4 (extension): No snapshots being sent to Express
  Evidence: Zero ESTABLISHED connections to port 4000 from any browser
  Possible causes: Extension logic not triggering, poker page not showing table,
                   or extension waiting for Flask response before continuing

LEVEL 5 (documentation): POST_ROTATION_VALIDATION.md is factually wrong
  Effect: Creates false confidence that rotation succeeded
```

---

## Evidence Confidence

| Claim | Confidence | Basis |
|---|---|---|
| Flask dead (no process, ECONNREFUSED) | 100% | Direct: /proc scan, curl, health check |
| PID lock file contains "7" from Jun 21 | 100% | Direct: cat + stat inside container |
| Containers started Jun 22 18:50 UTC | 100% | Direct: Docker State.StartedAt |
| er-remote unhealthy, FailingStreak=6516 | 100% | Direct: Docker State.Health |
| Docker env vars empty for secrets | 100% | Direct: Docker Config.Env |
| Container .env has old secrets | 100% | Direct: cat inside container |
| EC2 UFW blocks 4000/5002 | 100% | Direct: ufw status on EC2 |
| Tunnel forwards ports correctly | 100% | Direct: EC2 localhost:4000 → VM response |
| Browsers on GoldRush, not posting | 95% | Direct: ss ESTABLISHED connections, zero :4000 |
| Extension loaded from correct path | 95% | Chrome Preferences JSON |
| Old API key in extension background.js | 100% | Direct: file content |
| POST_ROTATION_VALIDATION wrong | 100% | Contradicted by all runtime evidence |

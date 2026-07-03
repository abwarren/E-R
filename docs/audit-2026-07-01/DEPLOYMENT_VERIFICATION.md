# DEPLOYMENT VERIFICATION — E&R Poker Platform

**Date:** 2026-07-01 11:47 UTC

---

## Deployment Map

```
GitHub: abwarren/E-R.git @ 8280c78 (master)
    ↓ git clone / git pull
Local VM: /home/wa/projects/poker/E&R
    ↓ docker build (Dockerfile)
Docker Image: e-r-remote:latest
    ↓ docker compose up -d
Container: er-remote (:4000, :1080)
    ├── Express (server-container.js) :4000
    └── Flask (app.py) :1080

Container: er-engine (:5002)
    └── Flask (app.py) + eval7 scripts
```

---

## Container-File Verification

| File | Repo SHA256[:12] | Container SHA256[:12] | Match |
|------|------------------|----------------------|-------|
| backend/app.py | 1de61b644c06 | 1de61b644c06 | ✓ |
| scripts/server-container.js | caf84408889c | caf84408889c | ✓ |
| source/w4p.js | 99cc6bb768be | 99cc6bb768be | ✓ |
| source/remote-w4p.html | af180531d13f | af180531d13f | ✓ |
| source/api-config.js | 34370bdba32e | 34370bdba32e | ✓ |
| source/engine_flow_controls.js | 49fb71688ff4 | 49fb71688ff4 | ✓ |
| backend/static/ext/bridge.js | e0bb411db810 | e0bb411db810 | ✓ |
| backend/static/ext/background.js | fdbae018b6e1 | fdbae018b6e1 | ✓ |
| backend/static/ext/manifest.json | 64ac7a718888 | 64ac7a718888 | ✓ |
| backend/static/ext/w4p.js | 99cc6bb768be | 5214f6aa0597 | ✗ STALE (IRRELEVANT) |

**Note on ext/w4p.js container staleness:** Chrome loads the extension from the HOST filesystem (`/home/wa/projects/poker/E&R/backend/static/ext/`), NOT from the container. The container copy of ext/ has zero runtime consumers. This is a build artifact only.

---

## HTTP-Served File Verification

| URL | Server | File | SHA256[:12] | Match Repo? |
|-----|--------|------|-------------|-------------|
| :4000/remote | Express | source/remote-w4p.html | af180531d13f | ✓ |
| :4000/api-config.js | Express | source/api-config.js | 34370bdba32e | ✓ |
| :1080/remote | Flask | static/remote-w4p.html | 162a16d2de83 | ✗ DIVERGENT |
| :1080/w4p.js | Flask | static/w4p.js | 04d39a49eaca | ✗ STALE LEGACY |
| :1080/api-config.js | Flask | static/api-config.js | 34370bdba32e | ✓ |

---

## Docker Health Checks

```
er-remote:  HEALTHCHECK CMD curl -f http://127.0.0.1:1080/api/health
            Status: healthy (11 hours)
            Last check: passed

er-engine:  HEALTHCHECK CMD curl -f http://127.0.0.1:5002/api/health
            Status: healthy (18 hours)
            Last check: passed
```

---

## Known Deployment Issues

| Issue | Severity | Detail |
|-------|----------|--------|
| PID lock survives restart | HIGH | `/tmp/w4p_backend.lock` persists on `docker restart`, Flask exits |
| Container ext/w4p.js stale | LOW | Not used at runtime (Chrome loads from host) |
| Flask serves divergent remote-w4p.html | MEDIUM | 63KB vs 54KB, internal-only access |
| Flask serves stale /w4p.js | MEDIUM | 35KB legacy, zero external consumers |
| TRACKER_API_KEY bare in docker-compose | MEDIUM | Docker Config.Env shows empty string |

---

## Start/Stop Verification

```
Startup: docker compose up -d → er-engine starts first → er-remote waits for healthy → starts
Process: entrypoint.sh → flask :1080 & → wait for health → exec node server-container.js :4000
Health: Docker healthcheck hits Flask :1080 every 15s
Restart: docker restart er-remote → PID lock may block Flask (see known issue)
```

---

## Production Access

```
External: NOT exposed (VM has no public ports configured for 4000/5002)
Internal: 127.0.0.1:4000 (Express), 127.0.0.1:1080 (Flask), 127.0.0.1:5002 (Engine)
Tunnel:   SSH reverse tunnel to laptop (port 19999) — currently DOWN
```

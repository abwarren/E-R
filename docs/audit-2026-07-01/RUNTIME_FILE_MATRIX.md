# RUNTIME FILE MATRIX — E&R Poker Platform

**Date:** 2026-07-01 11:47 UTC

---

## Complete Provenance Chain

Every runtime-critical file traced through 4 hops:

```
Git HEAD → Working Tree → Docker Container → HTTP Response → Browser
```

---

### Extension Files (Chrome loads from host filesystem)

| File | Git HEAD | Working Tree | Container | Chrome Loaded | Status |
|------|----------|-------------|-----------|---------------|--------|
| w4p.js | 99cc6bb7 | 99cc6bb7 ✓ | 5214f6 (IRRELEVANT) | 99cc6bb7 ✓ | PASS |
| bridge.js | e0bb411d | e0bb411d ✓ | e0bb411d ✓ | e0bb411d ✓ | PASS |
| background.js | fdbae018 | fdbae018 ✓ | fdbae018 ✓ | fdbae018 ✓ | PASS |
| manifest.json | 64ac7a71 | 64ac7a71 ✓ | 64ac7a71 ✓ | 64ac7a71 ✓ | PASS |

**Note:** Container ext/w4p.js is STALE (5214f6 — old v24 backup). But Chrome loads from HOST FILESYSTEM path `/home/wa/projects/poker/E&R/backend/static/ext/`, NOT from the container. Docker COPY of ext/ has zero runtime consumers. The stale container copy is a build artifact with NO runtime impact.

---

### Express-Served Files (via container /app/source/)

| File | Git HEAD | Working Tree | Container | HTTP Response | Status |
|------|----------|-------------|-----------|---------------|--------|
| api-config.js | 34370bdb | 34370bdb ✓ | 34370bdb ✓ | 34370bdb ✓ | PASS |
| remote-w4p.html | af180531 | af180531 ✓ | af180531 ✓ | af180531 ✓ | PASS |
| engine_flow_controls.js | 49fb7168 | 49fb7168 ✓ | 49fb7168 ✓ | N/A | PASS |

---

### Flask-Served Files (via container /app/backend/static/)

| File | Git HEAD | Working Tree | Container | HTTP Response | Status |
|------|----------|-------------|-----------|---------------|--------|
| api-config.js | 34370bdb | 34370bdb ✓ | 34370bdb ✓ | 34370bdb ✓ | PASS |
| remote-w4p.html | 162a16d2 | 162a16d2 ✓ | 162a16d2 ✓ | 162a16d2 ✓ | DIVERGENT |
| w4p.js | 04d39a49 | 04d39a49 ✓ | 04d39a49 ✓ | 04d39a49 ✓ | STALE LEGACY |

---

### Backend Source Files

| File | Git HEAD | Working Tree | Container | Status |
|------|----------|-------------|-----------|--------|
| app.py | 1de61b64 | 1de61b64 ✓ | 1de61b64 ✓ | PASS |
| server-container.js | caf84408 | caf84408 ✓ | caf84408 ✓ | PASS |
| server.js (bare-metal) | 15c04c9b | 15c04c9b ✓ | caf84408 (different — correct) | PASS |

---

### Files with Provenance Issues

| File | Issue | Consumer | Impact | Priority |
|------|-------|----------|--------|----------|
| static/w4p.js (35KB) | STALE — different codebase from ext/w4p.js (69KB) | Flask :1080/w4p.js | ZERO external consumers | LOW |
| static/remote-w4p.html (63KB) | DIVERGENT from source/ (54KB) | Flask :1080/remote | Internal-only access | MEDIUM |
| ext/w4p.js (container) | STALE v24 copy | None | Chrome loads from host, not container | LOW |

---

## File Count Summary

| Category | Files | Status |
|----------|-------|--------|
| Extension files | 4 (w4p, bridge, bg, manifest) | PASS — all match Git HEAD |
| Express-served | 3 (api-config, remote, engine_flow) | PASS — all match Git HEAD |
| Flask-served (current) | 1 (api-config) | PASS |
| Flask-served (stale) | 2 (w4p.js, remote-w4p.html) | KNOWN DIVERGENCE |
| Backend source | 3 (app.py, server.js, server-container.js) | PASS |
| **Total** | **13** | **10 PASS, 2 STALE, 1 CONTAINER STALE** |

---

## No Missing Files

All files listed in the Phase 3 requirements are present:
- ✓ backend/static/ext/w4p.js
- ✓ backend/static/ext/background.js  
- ✓ backend/static/ext/bridge.js
- ✓ backend/static/ext/manifest.json
- ✓ backend/app.py
- ✓ scripts/server.js
- ✓ scripts/server-container.js
- ✓ backend/static/api-config.js
- ✓ backend/static/ext/engine_flow_controls.js
- ✓ backend/static/engine/assets/engine_flow_controls.js
- ✓ source/remote-w4p.html
- ✓ source/engine_flow_controls.js

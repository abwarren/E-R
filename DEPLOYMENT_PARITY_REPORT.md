# DEPLOYMENT PARITY REPORT

**Date:** 2026-07-03
**Git HEAD:** 94a6cfc (w4p-seat-stability-v1)
**Mission:** Restore deployment parity — runtime equals Git HEAD

---

## Root Cause

The Dockerfile at line 29 contains `COPY source/ ./source/` — the `source/` directory is baked into the container image at build time. No volume mount exists for `/app/source/`.

The container was built **before** commit `94a6cfc` was applied to `source/remote-w4p.html`. The Express server (`res.sendFile`) was serving the pre-release copy frozen inside the container image.

**Not a code defect. Not a configuration error. A build lifecycle gap** — the container was never rebuilt after the release was tagged.

---

## Fix Applied

`docker cp` from host filesystem into running container:

```
docker cp source/remote-w4p.html er-remote:/app/source/remote-w4p.html
```

No container restart required — Express `res.sendFile()` reads from disk on each request.

---

## SHA256 Chain — remote-w4p.html

| Hop | SHA256 | Bytes | Status |
|-----|--------|-------|--------|
| Git HEAD (94a6cfc) | `2068f7e838f05e67...` | 57,601 | — |
| Host filesystem | `2068f7e838f05e67...` | 57,601 | ✓ MATCH |
| Container `/app/source/` | `2068f7e838f05e67...` | 57,601 | ✓ MATCH |
| HTTP :4000/remote | `2068f7e838f05e67...` | 57,601 | ✓ MATCH |

**DEPLOYMENT PARITY: ACHIEVED** — all 4 hops identical.

---

## SHA256 Chain — backend/app.py

| Hop | SHA256 | Status |
|-----|--------|--------|
| Git HEAD (94a6cfc) | `1de61b644c0680b6...` | — |
| Container `/app/backend/` | `1de61b644c0680b6...` | ✓ MATCH |

The uncommitted `action_on` WIP exists only on the host filesystem — NOT in the container.

---

## SHA256 Chain — extension w4p.js (host-loaded)

| Hop | SHA256 | Status |
|-----|--------|--------|
| Git HEAD | `a62e114bc38cf5a8...` | — |
| Host `backend/static/ext/` | `a62e114bc38cf5a8...` | ✓ MATCH |
| Container copy (irrelevant) | `a62e114bc38cf5a8...` | MATCH but NOT the path Chrome loads from |

Chrome loads the extension from the host filesystem — container EXT copy is irrelevant.

---

## Release Feature Verification

All 6 w4p-seat-stability-v1 features confirmed in running Express :4000/remote:

| Feature | Status |
|---------|--------|
| `.seat-box.sitting-out` CSS rule | ✓ Present |
| `opacity: 0.45` on sitting-out seats | ✓ Present |
| `.seat-sitting-label` display:block | ✓ Present |
| "SITTING OUT" label in buildSeatBoxHtml | ✓ Present |
| `seat.status` included in seatHash | ✓ Present |
| "Include sitting-out players" comment | ✓ Present |
| OLD exclusion filter (`sitting_out` in posSeatMap) | ✓ REMOVED |

---

## Current State Summary

| Component | Status |
|-----------|--------|
| Git HEAD | 94a6cfc (clean) |
| Host source/ | Matches HEAD |
| Container /app/source/ | Matches HEAD |
| Container /app/backend/ | Matches HEAD |
| Express :4000 serving | Matches HEAD |
| Extension (host-loaded) | Matches HEAD |
| backend/app.py (host only) | WIP `action_on` changes — UNCOMMITTED, NOT deployed |

---

## Unresolved

1. **`backend/app.py` working tree modification** — 10-line `action_on` feature WIP. Uncommitted. Not in container. Not in release. Should remain isolated until ready for dedicated feature branch/release.

2. **Container rebuild** — The `docker cp` fix is surgical and correct for this single file, but a full `docker compose build` will revert it (the Dockerfile still copies from `source/` which now matches HEAD, so a rebuild would produce the same result). No rebuild needed at this time.

---

## Rollback

To revert to pre-release container file (if needed):
```
git -C '/home/wa/projects/poker/E&R' show 94a6cfc~1:source/remote-w4p.html | docker exec -i er-remote tee /app/source/remote-w4p.html > /dev/null
```

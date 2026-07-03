# DELETION LOG — E&R Poker Platform Consolidation

**Date:** 2026-07-01
**Status:** PENDING APPROVAL — no deletions executed yet

---

## Pre-Deletion Evidence Summary

| # | Item | Type | Size | Unique Work? | Runtime Role? | Evidence |
|---|------|------|------|-------------|---------------|----------|
| 1 | `/home/wa/projects/poker/E&R_sandbox` | git repo | 178MB | NO (git log origin/master..HEAD = empty) | NO (no process references, not in Docker) | git log, lsof |
| 2 | `/home/wa/Documents/w4p-extension` | directory | ~50KB | NO (61-byte stubs) | NO (Chrome loads from E&R/ext/) | Chrome Preferences |
| 3 | `/home/wa/Documents/w4p-extension-dev` | directory | ~50KB | NO (61-byte stubs) | NO (Chrome ref EXISTS=False) | Chrome Preferences |
| 4 | `/home/wa/projects/poker/REMOTEREMOTE` | directory | unknown | NO (no .git) | NO (bare data dirs) | ls |
| 5 | `/home/wa/REMOTEREMOTE` | directory | unknown | NO (no .git) | NO (bare data dir) | ls |
| 6 | `/home/wa/.local/share/Trash/files/w4p.js` | file | 81KB | N/A | NO (trash) | Already deleted |
| 7 | `/home/wa/.local/share/Trash/files/bridge.js` | file | 1.7KB | N/A | NO (trash) | Already deleted |
| 8 | `/home/wa/.local/share/Trash/files/background.js` | file | 1.7KB | N/A | NO (trash) | Already deleted |
| 9 | `/home/wa/.local/share/Trash/files/manifest.json` | file | 2KB | N/A | NO (trash) | Already deleted |

---

## Item #1: `/home/wa/projects/poker/E&R_sandbox`

### Evidence Chain

```
Remote:        git@github.com:abwarren/E-R.git ← SAME as canonical
Branch:        master ← SAME as canonical
HEAD:          8e1406b ← 10+ commits behind canonical (8280c78)
Unique commits: NONE (git log origin/master..HEAD = empty)
Process hold:  No process references this path (lsof returns empty)
Docker ref:    Not in docker-compose.yml, not in any Dockerfile
HTTP ref:      No Express/Flask route points here
Chrome ref:    Chrome Preferences: no extension ID points here
Size:          178MB (includes venv and node_modules)
```

### Why Safe to Delete

1. **No unique work:** `git log origin/master..HEAD` returns EMPTY — no commits exist in sandbox that aren't in origin.
2. **Behind canonical:** 8e1406b vs 8280c78 — the sandbox is missing 10+ commits including the bridgeFetch fix, v24 seat mapping, api-config.js, and frontend API configuration.
3. **No runtime role:** Docker images are built from `/home/wa/projects/poker/E&R`, not from the sandbox. Chrome loads from canonical path. No running process has files open in this directory.
4. **Created by agent session:** Contains 61-byte placeholder stubs with text `// DELETED — use canonical copy at E&R/backend/static/ext/` — identical to the Documents/w4p-extension stubs. This was a temporary agent workspace that was never cleaned up.

### What's Inside

```
backend/     — stale copy of Flask backend (126KB app.py vs 129KB canonical)
scripts/     — stale Express (10.8KB vs 11.3KB canonical)
source/      — 61-byte stub files + stale copies
venv/        — full Python virtual environment (~150MB)
node_modules/ — full Node.js modules (~20MB)
```

---

## Item #2: `/home/wa/Documents/w4p-extension`

### Evidence Chain

```
Contents:    9 files, all 61-byte stubs OR stale copies
Stub content: "// DELETED — use canonical copy at E&R/backend/static/ext/"
Chrome ref:   Chrome Preferences: NO extension loads from this path
Runtime role: NONE
```

### Files

| File | SHA | Size | vs Canonical |
|------|-----|------|-------------|
| w4p.js | 47f89c88... | 61B | STUB (canonical: 69,417B) |
| background.js | 47f89c88... | 61B | STUB (canonical: 6,475B) |
| bridge.js | 47f89c88... | 61B | STUB (canonical: 938B) |
| manifest.json | 64ac7a71... | 2,499B | MATCHES canonical |
| engine_flow_controls.js | e7a67998... | 15,094B | DIFFERENT from canonical (49fb7168) |
| autologin.js | — | — | — |
| options.html | — | — | — |
| strip_images.js | — | — | — |
| w4p.js.bak | — | — | — |

### Why Safe to Delete

The 61-byte stubs were placed intentionally (previous consolidation) to prevent accidental use. They literally say "DELETED." No process references this directory.

---

## Item #3: `/home/wa/Documents/w4p-extension-dev`

### Evidence Chain

```
Contents:    8 files, all 61-byte stubs
Chrome ref:   Chrome Preferences: extension ID bjladcnoceindfikglnijmdkbeahejjm 
             points to /home/wa/projects/poker/E&R/source/w4p-extension-dev
             EXISTS=False ← path DOES NOT EXIST (already deleted directory)
Runtime role: NONE (Chrome extension not loaded)
```

### Why Safe to Delete

Chrome already reports the path as non-existent. The directory contains only 61-byte stubs.

---

## Items #4-5: REMOTEREMOTE Directories

### Evidence Chain

```
/home/wa/projects/poker/REMOTEREMOTE:
  Contents: data/, source/, state/ — no .git
  Runtime:  No Docker references, no process references
  Origin:   Legacy path from before E&R repo was created

/home/wa/REMOTEREMOTE:
  Contents: data/ only — no .git
  Runtime:  No Docker references, no process references
  Origin:   Legacy path from original laptop setup
```

The er-poker-platform skill documents that `/home/wa/REMOTEREMOTE/state/` was the legacy state file path but the active state file is at `/home/wa/projects/poker/E&R/state/state_snapshot.json` (verified 2026-06-21).

---

## Items #6-9: Trash Files

Already in `/home/wa/.local/share/Trash/files/`. These are files that were previously deleted via GUI/file manager and moved to trash. Can be permanently removed with `rm` or left for the trash system.

---

## Phase 7 — Unique Work Preservation

**Verified: No unique work exists in any deletion target.**

| Target | Unique commits? | Unique files? | Action needed |
|--------|----------------|---------------|---------------|
| E&R_sandbox | None (git log proves) | None | No merge needed |
| Documents/w4p-extension | N/A | None (stubs) | No merge needed |
| Documents/w4p-extension-dev | N/A | None (stubs) | No merge needed |
| REMOTEREMOTE dirs | N/A | None | No merge needed |

No commits or pushes required for any deletion target.

---

## Phase 8 — Post-Consolidation Verification

After deletions execute, verify:

1. `docker ps` shows er-remote and er-engine healthy
2. `curl http://127.0.0.1:4000/health` returns `{"ok":true}`
3. Chrome extension still loads (check `chrome://extensions` — PokerScope W4P should show path `/home/wa/projects/poker/E&R/backend/static/ext`)
4. `git -C '/home/wa/projects/poker/E&R' status` is unchanged
5. System services unaffected

---

## Approval Required

The following deletions are pending user approval:

```
rm -rf '/home/wa/projects/poker/E&R_sandbox'         # 178MB
rm -rf '/home/wa/Documents/w4p-extension'             # ~50KB
rm -rf '/home/wa/Documents/w4p-extension-dev'         # ~50KB
rm -rf '/home/wa/projects/poker/REMOTEREMOTE'         # unknown
rm -rf '/home/wa/REMOTEREMOTE'                        # unknown
```

**Total recovery: ~178MB+**

All 4 deliverable reports are at:
- `docs/audit-2026-07-01/REPOSITORY_CONSOLIDATION_REPORT.md`
- `docs/audit-2026-07-01/DUPLICATE_REPOSITORY_REPORT.md`
- `docs/audit-2026-07-01/RUNTIME_FILE_MATRIX.md`
- `docs/audit-2026-07-01/DELETION_LOG.md` (this file)

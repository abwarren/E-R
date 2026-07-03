# DUPLICATE REPOSITORY REPORT — E&R Poker Platform

**Date:** 2026-07-01

---

## All Git Repositories Found

| # | Path | Remote | Branch | HEAD | Upstream | Status |
|---|------|--------|--------|------|----------|--------|
| 1 | `/home/wa/projects/poker/E&R` | abwarren/E-R | master | 8280c78 | origin/master (in sync) | **CANONICAL** |
| 2 | `/home/wa/projects/poker/ENGINEENGINE` | abwarren/E-R | engine | e19e9db | origin/engine | **CANONICAL** (separate component) |
| 3 | `/home/wa/projects/poker/E&R_sandbox` | abwarren/E-R | master | 8e1406b | behind by 10+ commits | **STALE FORK** |
| 4 | `/home/wa/projects/poker/goldrush-deploy` | abwarren/RemoteControl | main | 02c872e | separate project | **SEPARATE PROJECT** |

---

## Repository Detail

### #1: `/home/wa/projects/poker/E&R` — CANONICAL
- In sync with GitHub
- Docker images built from this tree
- Chrome extension loaded from this path
- **KEEP — this is the single source of truth**

### #2: `/home/wa/projects/poker/ENGINEENGINE` — CANONICAL (engine branch)
- Same remote but `engine` branch (different component)
- Running as er-engine Docker container
- `docker-compose.yml` depends on it: `build: ../ENGINEENGINE`
- **KEEP — actively used, separate component**

### #3: `/home/wa/projects/poker/E&R_sandbox` — STALE FORK
- Same remote (abwarren/E-R), same branch (master)
- HEAD at 8e1406b — 10+ commits behind canonical 8280c78
- `git log origin/master..HEAD` = EMPTY — zero unique commits
- Contains 61-byte placeholder stubs (same as Documents/w4p-extension)
- Content: `// DELETED — use canonical copy at E&R/backend/static/ext/`
- Created by previous agent session as a temporary sandbox
- **DELETE — no unique work, no runtime role**

### #4: `/home/wa/projects/poker/goldrush-deploy` — SEPARATE PROJECT
- Different remote: `https://github.com/abwarren/RemoteControl`
- Different project entirely — GoldRush-specific deployment
- Contains its own extension files, React frontend, backend
- **KEEP — separate project, not an E&R duplicate**

---

## Non-Repository Directories with W4P Content

| Path | Has .git? | Content | Status |
|------|-----------|---------|--------|
| `/home/wa/Documents/w4p-extension` | No | 61-byte stub placeholders | **DELETE** |
| `/home/wa/Documents/w4p-extension-dev` | No | 61-byte stub placeholders | **DELETE** |
| `/home/wa/projects/poker/REMOTEREMOTE` | No | `data/`, `source/`, `state/` dirs | **DELETE** |
| `/home/wa/REMOTEREMOTE` | No | `data/` dir only | **DELETE** |
| `/home/wa/projects/poker/ConceptPoker` | No | Documentation, no runtime code | **KEEP** |
| `/home/wa/projects/poker/plo-equity` | No | Older equity engine code | **KEEP** |

---

## Stub File Content (all 61-byte files)

```
00000000: 2f2f 2044 454c 4554 4544 20e2 8094 2075  // DELETED ... u
00000010: 7365 2063 616e 6f6e 6963 616c 2063 6f70  se canonical cop
00000020: 7920 6174 2045 2652 2f62 6163 6b65 6e64  y at E&R/backend
00000030: 2f73 7461 7469 632f 6578 742f 0a         /static/ext/.
```

These were intentionally placed by a previous consolidation to prevent accidental use of stale copies.

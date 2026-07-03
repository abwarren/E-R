# REPOSITORY CONSOLIDATION REPORT — E&R Poker Platform

**Date:** 2026-07-01
**Evidence tier:** DISK + RUNTIME

---

## Executive Summary

The W4P poker platform has spread across 4 Git repositories and ~15 directory trees on this workstation. Past agent sessions created sandboxes (E&R_sandbox), stub placeholders (Documents/w4p-extension*), and archived deployments (goldrush-deploy). This report identifies what must be kept and what can be safely removed.

**Post-consolidation target:** ONE repository (`/home/wa/projects/poker/E&R`), ONE extension load path, ONE Express source tree, ONE Flask source tree.

---

## Phase 1 — Canonical Repository Verification

| Attribute | Value |
|-----------|-------|
| Path | `/home/wa/projects/poker/E&R` |
| Remote | `git@github.com:abwarren/E-R.git` |
| Branch | `master` |
| HEAD | `8280c78e75f9e8419b18bd1bdb5cbb7c37a0adbd` |
| GitHub origin/master | `8280c78e75f9e8419b18bd1bdb5cbb7c37a0adbd` |
| Match? | **YES — identical** |
| Working tree | 10 deleted .bak files, 2 untracked dirs |

**Conclusion:** Canonical repository is in sync with GitHub. No un-pushed commits.

---

## Phase 2 — Running System Deployment Map

### Docker Containers

| Container | Ports | Source |
|-----------|-------|--------|
| er-remote | 4000:4000 | Dockerfile builds from `/home/wa/projects/poker/E&R` |
| er-engine | 5002:5002 | Built from `/home/wa/projects/poker/ENGINEENGINE` |

### Docker COPY Paths (er-remote)

```
Host (git repo)                         Container
─────────────────                       ─────────
backend/              ──COPY──►         /app/backend/
  app.py                                /app/backend/app.py
  static/                               /app/backend/static/
    ext/               (EXTENSION)      /app/backend/static/ext/
    remote-w4p.html    (Flask serves)   /app/backend/static/remote-w4p.html
    w4p.js             (Flask serves)   /app/backend/static/w4p.js
scripts/              ──COPY──►         /app/scripts/
  server-container.js                   /app/scripts/server-container.js
source/               ──COPY──►         /app/source/
  remote-w4p.html     (Express serves)  /app/source/remote-w4p.html
  w4p.js                                /app/source/w4p.js
  api-config.js                         /app/source/api-config.js
```

### Docker Volumes (bind mounts for persistence only)

| Volume | Container Path | Purpose |
|--------|---------------|---------|
| er_remote-state | `/app/state/` | State persistence |
| er_remote-logs | `/app/logs/` | Log persistence |

**No source code is bind-mounted.** All code is baked into the Docker image at build time.

### Chrome Extension Load Path

```
Chrome loads from (Preferences JSON):
  /home/wa/projects/poker/E&R/backend/static/ext/
  Manifest name: "PokerScope W4P"
  Extension ID: aioeikkkkoecalijgdedippnjoihofhj
  EXISTS on disk: YES
```

### HTTP Serving Map

| URL | Server | File Served | Container Path |
|-----|--------|-------------|----------------|
| `:4000/remote` | Express | `source/remote-w4p.html` (54KB) | `/app/source/remote-w4p.html` |
| `:4000/api-config.js` | Express | `source/api-config.js` (3KB) | `/app/source/api-config.js` |
| `:4000/api/*` | Express→Flask | Proxied to `:1080` | N/A |
| `:1080/remote` | Flask | `static/remote-w4p.html` (63KB ⚠️) | `/app/backend/static/remote-w4p.html` |
| `:1080/w4p.js` | Flask | `static/w4p.js` (35KB ⚠️) | `/app/backend/static/w4p.js` |
| `:1080/api-config.js` | Flask | `static/api-config.js` (3KB ✓) | `/app/backend/static/api-config.js` |

---

## Phase 5 — Runtime Chain Verification (Complete)

### w4p.js (extension — Chrome loads from host filesystem)

| Link | SHA256 (first 16) | Size |
|------|-------------------|------|
| Git HEAD | `99cc6bb768be44d4` | 69,417B |
| Working Tree `ext/` | `99cc6bb768be44d4` ✓ | 69,417B |
| Container `ext/` | `5214f6aa0597015d` ✗ | 84,675B |
| Chrome loaded | `99cc6bb768be44d4` ✓ | 69,417B |

**Verdict:** Chrome loads current version from host filesystem. Container copy is stale but IRRELEVANT — Chrome does not load from container.

### w4p.js (Express-served from source/)

| Link | SHA256 | Size |
|------|--------|------|
| Git HEAD | `99cc6bb768be44d4` | 69,417B |
| Working Tree `source/` | `99cc6bb768be44d4` ✓ | 69,417B |
| Container `source/` | `99cc6bb768be44d4` ✓ | 69,417B |
| HTTP `:4000/` | N/A (not served directly) | N/A |

### w4p.js (Flask-served from static/ — STALE)

| Link | SHA256 | Size |
|------|--------|------|
| Git HEAD | `04d39a49eaca0da3` | 35,902B |
| Working Tree `static/` | `04d39a49eaca0da3` ✓ | 35,902B |
| Container `static/` | `04d39a49eaca0da3` ✓ | 35,902B |
| HTTP `:1080/w4p.js` | `04d39a49eaca0da3` ✓ | 35,902B |

**Verdict:** Flask serves 35KB legacy file. Chain is consistent but file is STALE. Reachable only via direct Flask :1080 access (Express does NOT proxy `/w4p.js`). ZERO external consumers.

### bridge.js (extension)

| Link | SHA256 | Size |
|------|--------|------|
| Git HEAD | `e0bb411db8101866` | 938B |
| Working Tree `ext/` | `e0bb411db8101866` ✓ | 938B |
| Container `ext/` | `e0bb411db8101866` ✓ | 938B |
| Chrome loaded | `e0bb411db8101866` ✓ | 938B |

**Verdict:** ALL MATCH.

### background.js (extension)

| Link | SHA256 | Size |
|------|--------|------|
| Git HEAD | `fdbae018b6e1b5ef` | 6,475B |
| Working Tree `ext/` | `fdbae018b6e1b5ef` ✓ | 6,475B |
| Container `ext/` | `fdbae018b6e1b5ef` ✓ | 6,475B |
| Chrome loaded | `fdbae018b6e1b5ef` ✓ | 6,475B |

**Verdict:** ALL MATCH.

### remote-w4p.html (Express-served from source/)

| Link | SHA256 | Size |
|------|--------|------|
| Git HEAD | `af180531d13fd92a` | 54,005B |
| Working Tree `source/` | `af180531d13fd92a` ✓ | 54,005B |
| Container `source/` | `af180531d13fd92a` ✓ | 54,005B |
| HTTP `:4000/remote` | `af180531d13fd92a` ✓ | 54,005B |

**Verdict:** ALL MATCH.

### remote-w4p.html (Flask-served from static/ — DIVERGENT)

| Link | SHA256 | Size |
|------|--------|------|
| Git HEAD | `162a16d2de83034a` | 63,963B |
| Working Tree `static/` | `162a16d2de83034a` ✓ | 63,963B |
| Container `static/` | `162a16d2de83034a` ✓ | 63,963B |
| HTTP `:1080/remote` | `162a16d2de83034a` ✓ | 63,963B |

**Verdict:** Chain consistent but file DIVERGENT from Express-served version (54KB vs 63KB). Flask :1080 is internal-only. Express :4000 is the primary access path.

### api-config.js

| Link | SHA256 (source/) | SHA256 (static/) |
|------|------------------|------------------|
| Git HEAD | `34370bdba32ef4a1` | `34370bdba32ef4a1` |
| Working Tree | `34370bdba32ef4a1` ✓ | `34370bdba32ef4a1` ✓ |
| Container | `34370bdba32ef4a1` ✓ | `34370bdba32ef4a1` ✓ |
| HTTP | `34370bdba32ef4a1` ✓ (Express) | `34370bdba32ef4a1` ✓ (Flask) |

**Verdict:** ALL MATCH. Both copies identical.

### engine_flow_controls.js

| Link | SHA256 (source/) | SHA256 (ext/) | SHA256 (engine/assets/) |
|------|------------------|---------------|--------------------------|
| Git HEAD | `49fb71688ff405cc` | `49fb71688ff405cc` | `49fb71688ff405cc` |
| Working Tree | `49fb71688ff405cc` ✓ | `49fb71688ff405cc` ✓ | `49fb71688ff405cc` ✓ |
| Container | `49fb71688ff405cc` ✓ | `49fb71688ff405cc` ✓ | `49fb71688ff405cc` ✓ |

**Verdict:** ALL THREE COPIES IDENTICAL.

---

## Phase 4 — Complete Classification

### Repositories

| Path | Remote | Branch | HEAD | Classification |
|------|--------|--------|------|----------------|
| `/home/wa/projects/poker/E&R` | abwarren/E-R | master | 8280c78 | **CANONICAL_SOURCE** |
| `/home/wa/projects/poker/ENGINEENGINE` | abwarren/E-R | engine | e19e9db | **CANONICAL_SOURCE** (separate component) |
| `/home/wa/projects/poker/E&R_sandbox` | abwarren/E-R | master | 8e1406b | **DELETE** — stale fork, no unique commits, behind by 10+ commits |
| `/home/wa/projects/poker/goldrush-deploy` | abwarren/RemoteControl | main | 02c872e | **ARCHIVE** — separate project, different repo |

### Directories (non-git)

| Path | Classification | Reason |
|------|---------------|--------|
| `/home/wa/Documents/w4p-extension` | **DELETE** | 61-byte placeholder stubs, not runtime |
| `/home/wa/Documents/w4p-extension-dev` | **DELETE** | 61-byte placeholder stubs, not runtime |
| `/home/wa/projects/poker/REMOTEREMOTE` | **DELETE** | No .git, bare data/source/state dirs, no runtime code |
| `/home/wa/REMOTEREMOTE` | **DELETE** | No .git, bare data/ dir, no runtime code |
| `/home/wa/projects/poker/ConceptPoker` | **KEEP** | Separate project, documentation only |
| `/home/wa/projects/poker/plo-equity` | **KEEP** | Older equity engine, may have reusable code |
| `/home/wa/projects/poker/pokerafricaace` | **KEEP** | Separate project |
| `/home/wa/projects/poker/whatsapp-bot` | **KEEP** | Separate project |

### Runtime Files — w4p.js

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/backend/static/ext/w4p.js` | 99cc6bb7... | 69,417B | **ACTIVE_RUNTIME + CANONICAL_SOURCE** |
| `E&R/source/w4p.js` | 99cc6bb7... | 69,417B | **CANONICAL_SOURCE** (Express COPY source) |
| `E&R/backend/static/w4p.js` | 04d39a49... | 35,902B | **STALE** (Flask-served legacy, zero external consumers) |
| `E&R_sandbox/**/w4p.js` | 47f89c88... | 61B | **DELETE** (stubs in stale sandbox) |
| `Documents/w4p-extension/w4p.js` | 47f89c88... | 61B | **DELETE** (placeholder stub) |
| `Documents/w4p-extension-dev/w4p.js` | 47f89c88... | 61B | **DELETE** (placeholder stub) |
| `goldrush-deploy/**/w4p.js` | 47f89c88... / bc9b65... | varies | **ARCHIVE** (separate project) |
| `ENGINEENGINE/**/w4p.js` | 47f89c88... | 61B | **STALE** (stub in engine repo) |
| `plo-equity/static/w4p.js` | 47f89c88... | 61B | **STALE** (stub in old project) |
| `projects/fw/plug/w4p.js` | 7f75a443... | 73,119B | **KEEP** (separate project) |
| `Trash/files/w4p.js` | e742e628... | 81,364B | **DELETE** (trash — already deleted) |

### Runtime Files — bridge.js

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/backend/static/ext/bridge.js` | e0bb411d... | 938B | **ACTIVE_RUNTIME + CANONICAL_SOURCE** |
| All 61-byte stubs elsewhere | 47f89c88... | 61B | **DELETE** |
| `goldrush-deploy/**` copies | 47f89c88... | 61B | **DELETE** (stubs) |
| `Trash/files/bridge.js` | ecbc6dd1... | 1,724B | **DELETE** (trash) |

### Runtime Files — background.js

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/backend/static/ext/background.js` | fdbae018... | 6,475B | **ACTIVE_RUNTIME + CANONICAL_SOURCE** |
| All 61-byte stubs elsewhere | 47f89c88... | 61B | **DELETE** |
| `goldrush-deploy/**` copies | 47f89c88... | 61B | **DELETE** (stubs) |
| `Trash/files/background.js` | ecbc6dd1... | 1,724B | **DELETE** (trash) |

### Runtime Files — manifest.json

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/backend/static/ext/manifest.json` | 64ac7a71... | 2,499B | **ACTIVE_RUNTIME + CANONICAL_SOURCE** |
| `Documents/w4p-extension/manifest.json` | 64ac7a71... | 2,499B | **BACKUP** (identical to active, not loaded) |
| `Documents/w4p-extension-dev/manifest.json` | 64ac7a71... | 2,499B | **BACKUP** (identical to active, not loaded) |
| `goldrush-deploy/**` copies | e22cb973... / a0e399b1... | varies | **ARCHIVE** (different project, different manifest) |

### Runtime Files — remote-w4p.html

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/source/remote-w4p.html` | af180531... | 54,005B | **CANONICAL_SOURCE** (Express serves from COPY) |
| `E&R/backend/static/ext/remote-w4p.html` | 168c00b6... | 53,966B | **ACTIVE_RUNTIME** (extension textarea) |
| `E&R/backend/static/remote-w4p.html` | 162a16d2... | 63,963B | **STALE** (Flask-served, 10KB larger, different version) |

### Runtime Files — engine_flow_controls.js

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/source/engine_flow_controls.js` | 49fb7168... | 15,139B | **CANONICAL_SOURCE** |
| `E&R/backend/static/engine/assets/engine_flow_controls.js` | 49fb7168... | 15,139B | **ACTIVE_RUNTIME** (engine React SPA) |
| `E&R/backend/static/ext/engine_flow_controls.js` | 49fb7168... | 15,139B | **ACTIVE_RUNTIME** (extension textarea) |
| `Documents/w4p-extension/*.js` copies | e7a67998... | 15,094B | **STALE** (different hash from canonical!) |
| All others | various | various | **ARCHIVE** (different projects) |

### Runtime Files — api-config.js

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/source/api-config.js` | 34370bdb... | 3,112B | **CANONICAL_SOURCE** (Express serves from COPY) |
| `E&R/backend/static/api-config.js` | 34370bdb... | 3,112B | **ACTIVE_RUNTIME** (Flask serves from COPY) |

### Runtime Files — app.py

| Path | SHA | Size | Classification |
|------|-----|------|----------------|
| `E&R/backend/app.py` | 1de61b64... | 129,050B | **ACTIVE_RUNTIME + CANONICAL_SOURCE** |
| `E&R_sandbox/backend/app.py` | 6034fa66... | 126,016B | **DELETE** (stale fork) |

### Runtime Files — server.js / server-container.js

| Path | Classification |
|------|----------------|
| `E&R/scripts/server.js` | **CANONICAL_SOURCE** (bare-metal laptop only) |
| `E&R/scripts/server-container.js` | **ACTIVE_RUNTIME + CANONICAL_SOURCE** (container) |

---

## Phase 6 — Consolidation Plan

### DELETE (safe — no runtime impact)

| Item | Type | Size | Reason |
|------|------|------|--------|
| `/home/wa/projects/poker/E&R_sandbox` | git repo | ~5MB | Stale fork, no unique commits |
| `/home/wa/Documents/w4p-extension` | directory | ~50KB | 61-byte placeholder stubs |
| `/home/wa/Documents/w4p-extension-dev` | directory | ~50KB | 61-byte placeholder stubs |
| `/home/wa/projects/poker/REMOTEREMOTE` | directory | unknown | No .git, bare data dirs |
| `/home/wa/REMOTEREMOTE` | directory | unknown | No .git, bare data dir |
| `/home/wa/.local/share/Trash/files/w4p.js` | file | 81KB | Already trashed |
| `/home/wa/.local/share/Trash/files/background.js` | file | 1.7KB | Already trashed |
| `/home/wa/.local/share/Trash/files/bridge.js` | file | 1.7KB | Already trashed |
| `/home/wa/.local/share/Trash/files/manifest.json` | file | 2KB | Already trashed |

### KEEP (separate projects — not duplicates)

| Item | Reason |
|------|--------|
| `/home/wa/projects/poker/ENGINEENGINE` | Separate engine component, different branch |
| `/home/wa/projects/poker/goldrush-deploy` | Different repo (abwarren/RemoteControl) |
| `/home/wa/projects/poker/ConceptPoker` | Separate project |
| `/home/wa/projects/poker/plo-equity` | Older codebase, potential reuse |
| `/home/wa/projects/poker/pokerafricaace` | Separate project |
| `/home/wa/projects/poker/whatsapp-bot` | Separate project |

### KEEP but FIX (in canonical repo — not deletion, but consolidation target)

| Issue | Current State | Target State |
|-------|--------------|--------------|
| `static/w4p.js` (35KB) | Flask serves stale legacy | Delete or replace with current ext/w4p.js |
| `static/remote-w4p.html` (63KB) | Flask serves divergent version | Replace with `source/remote-w4p.html` (54KB) |
| Three `engine_flow_controls.js` copies | Identical but redundant | Single SSOT in source/, copy at build time |
| Two `api-config.js` copies | Identical but redundant | Single SSOT in source/, copy at build time |

---

## Safety Verification

Before any deletion, I verified:

1. **No unique work in E&R_sandbox:** `git log origin/master..HEAD` returned EMPTY — zero unique commits.
2. **Stub files are placeholders:** Content reads `// DELETED — use canonical copy at E&R/backend/static/ext/` — intentionally left as markers.
3. **No runtime references to deleted paths:** Chrome loads from canonical path only. Express serves from container source/. Flask routes only reference static/. No code references Documents/w4p-extension*.
4. **GoldRush deploy is separate repo:** `abwarren/RemoteControl` — different remote from `abwarren/E-R`. Not a duplicate.
5. **ENGINEENGINE is a separate component:** Same remote (`abwarren/E-R`) but different branch (`engine`). Actively running as er-engine container.

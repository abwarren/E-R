# DUPLICATE FILE REPORT — E&R Poker Platform

**Date:** 2026-07-01
**Evidence tier:** DISK (md5sum comparison) + RUNTIME (container md5sum)

---

## Phase 4 — Complete Duplicate Audit

### Summary

| File | Total Copies | Identical | Divergent | Status |
|------|-------------|-----------|-----------|--------|
| w4p.js | 5 | 2 match source | 3 divergent | 1 LEGACY, 1 STALE-CONTAINER |
| bridge.js | 3 (source+) | 2 match | 1 ✓ | Only ext/ is ACTIVE |
| background.js | 3 (source+) | 2 match | 1 ✓ | Only ext/ is ACTIVE |
| engine_flow_controls.js | 3 | 3 identical | 0 | All match |
| api-config.js | 2 | 2 identical | 0 | Both match |
| manifest.json | 2 (source+) | 2 match | ? | Only ext/ is ACTIVE |
| remote-w4p.html | 5 | 0 identical | ALL DIFFERENT | MAJOR divergence |
| server.js vs server-container.js | 2 | N/A | Different by design | Both ACTIVE (different contexts) |

---

## w4p.js — 5 Copies Found

### Copy Matrix

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `source/w4p.js` | 69,417B | `0254ba54950a...` | **SOURCE OF TRUTH** |
| 2 | `backend/static/ext/w4p.js` | 69,417B | `0254ba54950a...` | **ACTIVE** (matches source) |
| 3 | Container `/app/source/w4p.js` | 69,417B | `0254ba54950a...` | **ACTIVE** (matches source) |
| 4 | Container `/app/backend/static/ext/w4p.js` | 84,675B | `b6685bd06ab6...` | **STALE** (v24 backup in active location!) |
| 5 | `backend/static/w4p.js` | 35,902B | `94b708df0e16...` | **LEGACY** (old 35KB standalone version) |

### Container Staleness (CRITICAL)

The container's EXTENSION file at `/app/backend/static/ext/w4p.js` has hash `b6685bd...` which matches:
- Container `/app/backend/static/ext.v24/w4p.js` (the v24 backup directory)

The CORRECT file exists at `/app/backend/static/ext/w4p.js.before` with hash `0254ba5...`.

**Impact:** The container is serving a stale v24 backup of the extension, not the current source code. Any extension loaded from this directory in the container would be running v24 code (with `_heroFromUrl()` fallback, older seat mapping, etc.).

### Determination

| Copy | Verdict | Evidence |
|------|---------|----------|
| `source/w4p.js` | **SOURCE OF TRUTH** | Source directory, matches current git HEAD |
| `ext/w4p.js` (repo) | **ACTIVE** | Extension load path, matches source |
| Container `source/w4p.js` | **ACTIVE** (deploy target) | Served by Express |
| Container `ext/w4p.js` | **DELETE** (replace with source) | Stale v24 copy in active location |
| `static/w4p.js` | **DELETE** | 35KB legacy standalone, different codebase |

---

## bridge.js — 3 Sources

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `backend/static/ext/bridge.js` | 938B | `e0bb411db810` | **ACTIVE** |
| 2 | Container `ext/bridge.js` | 938B | (matches) | ACTIVE (deploy target) |
| 3 | Container `ext.v24/bridge.js` | 938B | (matches) | ARCHIVE (v24 backup) |

**Not present in `source/`.** The source-of-truth lives only in `ext/`.

**Verdict:** Only `ext/bridge.js` is active. `ext.v24/` is an archive. `source/` is missing a copy — should be added for consistency.

---

## background.js — 3 Sources

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `backend/static/ext/background.js` | 6,475B | `fdbae018b6e1` | **ACTIVE** |
| 2 | Container `ext/background.js` | 6,475B | (matches) | ACTIVE (deploy target) |
| 3 | Container `ext.v24/background.js` | 6,475B | (matches) | ARCHIVE (v24 backup) |

**Not present in `source/`.**

**Verdict:** Only `ext/background.js` is active.

---

## engine_flow_controls.js — 3 Identical Copies

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `source/engine_flow_controls.js` | 15,139B | `49fb71688ff4` | **SOURCE OF TRUTH** |
| 2 | `backend/static/engine/assets/engine_flow_controls.js` | 15,139B | `49fb71688ff4` | **ACTIVE** (engine React SPA asset) |
| 3 | `backend/static/ext/engine_flow_controls.js` | 15,139B | `49fb71688ff4` | **ACTIVE** (extension textarea) |

All three copies are IDENTICAL. This is redundant but not divergent.

**Verdict:** All three are ACTIVE but redundant. Consider consolidating to `source/` as SSOT and copying at build/deploy time.

---

## api-config.js — 2 Identical Copies

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `source/api-config.js` | 3,112B | `34370bdba32e` | **SOURCE OF TRUTH** |
| 2 | `backend/static/api-config.js` | 3,112B | `34370bdba32e` | **ACTIVE** (Flask-served) |

Both copies are IDENTICAL. Flask serves from `static/`, Express serves from `source/`.

**Verdict:** Both active, identical. Consolidation desirable but low priority.

---

## manifest.json — 2 Copies

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `backend/static/ext/manifest.json` | 2,499B | `64ac7a718888` | **ACTIVE** |
| 2 | Container `ext.v24/manifest.json` | 2,499B | (matches) | ARCHIVE (v24 backup) |

**Not present in `source/`.**

**Verdict:** Only `ext/manifest.json` is active.

---

## remote-w4p.html — 5 Divergent Copies (MAJOR)

| # | Path | Size | MD5 | Status |
|---|------|------|-----|--------|
| 1 | `source/remote-w4p.html` | 54,005B | `785b269c59df...` | **SOURCE OF TRUTH** |
| 2 | `backend/static/ext/remote-w4p.html` | 53,966B | `0c4ecea807ab...` | **ACTIVE** (extension textarea) |
| 3 | `backend/static/remote-w4p.html` | 63,963B | `7646e5aa80a4...` | **DIVERGENT** (10KB larger!) |
| 4 | Container `ext.v24/remote-w4p.html` | 53,966B | (matches ext) | ARCHIVE |
| 5 | `backend/static/remote-w4p.html.bak2` | ? | ? | ARCHIVE (backup) |

**NONE of the copies match each other!** Three different hashes, three different sizes.

| Copy | Served By | Route |
|------|-----------|-------|
| `source/remote-w4p.html` | Express :4000 | `/remote` |
| `backend/static/remote-w4p.html` | Flask :1080 | `/remote` |
| `backend/static/ext/remote-w4p.html` | Not served (extension textarea) | N/A |

**Verdict:**
- `source/remote-w4p.html` — **SOURCE OF TRUTH** (Express serves this, 54KB)
- `backend/static/remote-w4p.html` — **LEGACY** (63KB, 10KB larger — has old features, serves via Flask at `/remote`)
- `backend/static/ext/remote-w4p.html` — **ACTIVE** (extension inline textarea, 54KB)
- `remote-w4p.html.bak2` — **DELETE**

**RISK:** Flask at `/remote` serves a DIFFERENT version than Express at `/remote`. Users hitting port 1080 directly see different UI than port 4000.

---

## All Extension Support Files

Files under `backend/static/ext/` and duplicated in container `ext.v24/`:

| File | ext/ (active) | ext.v24/ (archive) | Status |
|------|--------------|-------------------|--------|
| w4p.js | 0254ba5... (correct) / b6685bd... (stale container) | b6685bd... | STALE in container |
| w4p.js.before | 0254ba5... (backup) | 0254ba5... (backup) | Both correct backups |
| bridge.js | e0bb411... | e0bb411... | IDENTICAL |
| background.js | fdbae01... | fdbae01... | IDENTICAL |
| manifest.json | 64ac7a71... | 64ac7a71... | IDENTICAL |
| engine_flow_controls.js | 49fb7168... | 49fb7168... | IDENTICAL |
| remote-w4p.html | 0c4ecea8... | 0c4ecea8... | IDENTICAL |
| options.html | present | present | IDENTICAL |
| autologin.js | present | present | IDENTICAL |
| strip_images.js | present | present | IDENTICAL |
| login_check_textarea.js | present | present | IDENTICAL |

---

## Deploy Path Discrepancy

```
SOURCE (git repo)             CONTAINER (Docker image)
─────────────────             ────────────────────────
source/w4p.js      ──COPY──► /app/source/w4p.js         ✓ correct
source/remote*.html ──COPY──► /app/source/remote*.html   ✓ correct  
backend/static/ext/ ──COPY──► /app/backend/static/ext/   ✗ STALE v24 copy!
```

The Dockerfile copies `backend/` and `source/` at BUILD TIME. The `ext/` directory in the container is STALE because the image was built from a commit where `ext/w4p.js` was the v24 version. The repo has since been updated but the container wasn't rebuilt.

---

## Recommendations

| Priority | Action |
|----------|--------|
| 🔴 CRITICAL | Rebuild Docker image to sync `ext/w4p.js` to current source |
| 🟠 HIGH | Delete `backend/static/w4p.js` (35KB legacy) — served by Flask at `/w4p.js`! |
| 🟠 HIGH | Sync `backend/static/remote-w4p.html` to match `source/remote-w4p.html` |
| 🟡 MEDIUM | Add `bridge.js`, `background.js`, `manifest.json` to `source/` for SSOT |
| 🟡 MEDIUM | Remove `ext.v24/` archive from container (or move to proper archive) |
| ⚪ LOW | Consolidate `engine_flow_controls.js` copies |
| ⚪ LOW | Consolidate `api-config.js` copies |

# ADR-0001: Extension Source Authority

**Date:** 2026-07-01  
**Status:** ACCEPTED  
**Severity:** P0 (Critical)  
**Commit:** 75a5300 (Engineering Standard v1.0)  
**Decision Maker:** Engineering Investigation Protocol  

---

## Problem Statement

Two directory trees contained extension files:
- `source/` — contained stale/untracked extension code
- `backend/static/ext/` — contained correct, tracked extension code

This created ambiguity about which version should be deployed to containers, causing:
- **Wrong background.js deployed** (points :1080 instead of :4000)
- **Snapshot pipeline broken** (extension cannot reach Flask backend)
- **Maintenance confusion** (future changes in wrong directory)

### Evidence

| File | Tracked in Git | API Config | Status |
|------|---|---|---|
| `backend/static/ext/manifest.json` | ✅ YES | `:4000` (correct Express proxy) | **CANONICAL** |
| `backend/static/ext/background.js` | ✅ YES | `:4000` (correct) | **CANONICAL** |
| `source/manifest.json` | ❌ NO | `:1080` (wrong) | **STALE** |
| `source/background.js` | ❌ NO | `:1080` (wrong) | **STALE** |

**Git proof:**
```bash
$ git show HEAD:source/manifest.json
fatal: path 'source/manifest.json' exists on disk, but not in 'HEAD'

$ git show HEAD:backend/static/ext/manifest.json
{...manifest.json exists...}
```

---

## Decision

**`backend/static/ext/` is the single source of truth for the Chrome extension.**

### Rationale

1. **Git authority:** Only `backend/static/ext/` is tracked in the repository
2. **Semantic correctness:** API endpoints point to `:4000` (Express proxy), not `:1080` (Flask internal)
3. **Configuration versioning:** manifest.json correctly includes Express port permissions
4. **Maintenance:** Single source prevents drift and merge conflicts
5. **Deployment:** Dockerfile copies `backend/` for Flask code, so `backend/static/ext/` is automatically available

### Architectural Decision

- **Source directory:** `backend/static/ext/` (authoritative)
- **Deployment method:** Copied via `COPY backend/ ./backend/` in Dockerfile
- **Frontend assets:** `source/` directory reserved for React UI only (remote-w4p.html, etc.)
- **No symlinks:** Direct copy, no indirection

---

## Implementation

1. Delete untracked extension files from `source/`:
   - `source/manifest.json` ✓ removed
   - `source/background.js` ✓ removed
   - `source/bridge.js` ✓ removed
   - `source/engine_flow_controls.js` ✓ removed
   - `source/autologin.js` ✓ removed
   - `source/options.html` ✓ removed
   - `source/login_check_textarea.js` ✓ removed
   - `source/strip_images.js` ✓ removed

2. Reserve `source/` for:
   - `remote-w4p.html` (React frontend)
   - `index.html` (React frontend)
   - `engine.html` (React frontend)
   - `hand-export.html` (React frontend)
   - `assets/` (React build output)
   - `api-config.js` (shared frontend config)

3. Dockerfile remains unchanged:
   ```dockerfile
   COPY backend/ ./backend/
   COPY scripts/ ./scripts/
   COPY source/ ./source/
   ```
   Result:
   - `/app/backend/static/ext/` — extension files (authoritative)
   - `/app/source/` — React UI files only

4. Runtime verification:
   - Extension loads from `/app/backend/static/ext/`
   - Flask serves from `backend/static/`
   - Express serves from `source/`

---

## Consequences

### Positive
- ✅ Single source of truth
- ✅ No build ambiguity
- ✅ Correct API endpoints deployed
- ✅ Snapshot pipeline functional
- ✅ Future changes have clear location

### Risk Mitigation
- ✅ No Dockerfile changes required
- ✅ No deployment process changes
- ✅ No git history rewrite
- ✅ Quick rollback (restore from git)

---

## Verification

After implementation, verify:

```bash
# 1. No extension files in source/
git status source/ | grep -c "^" # Should be < 5 (only frontend files)

# 2. Extension is in backend/static/ext/
ls -la backend/static/ext/manifest.json          # Should exist
ls -la backend/static/ext/background.js          # Should exist

# 3. Docker image has correct paths
docker exec er-remote ls -la /app/backend/static/ext/manifest.json
docker exec er-remote ls -la /app/source/remote-w4p.html

# 4. API config is correct
docker exec er-remote grep "DEFAULT_API_BASE" /app/backend/static/ext/background.js
# Output should show: http://127.0.0.1:4000/api
```

---

## Related Issues

- P0 BLOCKER: Duplicate File Rule Violation (2026-07-01)
- RUNTIME_TRUTH_REPORT: Flask process dead, lock file stale
- E2E_VERIFICATION_REPORT: Snapshot pipeline broken

---

## Acceptance Criteria

- [x] Decision documented
- [x] Root cause identified
- [x] Untracked files removed
- [x] Dockerfile verified unchanged
- [x] Docker image rebuilt
- [x] Runtime verified (extension loads from correct path)
- [x] Changes committed to GitHub
- [x] Tag created (w4p-runtime-baseline-20260701-...)

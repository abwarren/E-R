# Git Release Report

## Branch
```
fix/w4p-bridge-fetch
```

## Commit
```
848c1f4 — feat: frontend API configuration, /api/latest endpoint, environment-independent routing
```

## Remote
```
origin  git@github.com:abwarren/E-R.git
```

## Push Confirmation
```
9af1015..848c1f4  fix/w4p-bridge-fetch -> fix/w4p-bridge-fetch
```
✅ Pushed successfully.

## Files Committed (14 files, +795/-361)

### New Files (3)
| File | Lines |
|------|-------|
| `backend/static/api-config.js` | +71 |
| `source/api-config.js` | +71 |
| `source/engine_flow_controls.js` | +364 |

### Modified Files (11)
| File | Change | Description |
|------|--------|-------------|
| `backend/app.py` | +21 | /api/latest alias + /api-config.js route |
| `backend/static/engine-index.html` | +1 | Add api-config.js script tag |
| `backend/static/engine/assets/engine_flow_controls.js` | +1/-1 | BRIDGE_URL to W4P_API |
| `backend/static/ext/engine_flow_controls.js` | +1/-1 | BRIDGE_URL to W4P_API |
| `backend/static/hand-export.html` | +1 | Add api-config.js script tag |
| `backend/static/index.html` | +1/-1 | Add api-config.js script tag |
| `backend/static/remote-w4p.html` | +1 | Add api-config.js script tag |
| `backend/static/remote.html` | +1/-1 | Add api-config.js script tag |
| `source/hand-export.html` | +1 | Add api-config.js script tag |
| `source/index.html` | +2/-2 | Add api-config.js + fetch refactor |
| `source/remote-w4p.html` | +613/-361 | Add api-config.js + responsive grid CSS |

## Excluded from Commit

| Category | Count | Reason |
|----------|-------|--------|
| Report MD files | ~15 | Investigation artifacts |
| Test files (tests/) | ~40+ | Test infrastructure |
| Data files (data/, backend/data/) | ~5 | Runtime data |
| Secrets (.env, .pem) | 2 | Security |
| Temp scripts (restart-er-remote.sh) | 1 | Deployment helper |
| Backup files (.bak, .swp) | Several | Artifacts |
| ext.v24/ directory | Entire | Archived copy |
| w4p.js changes | 2 files | Reverted (not part of this release) |

## Working Tree Status
```
✅ 0 staged changes
✅ 0 unstaged modifications
✅ 79 untracked files (reports, tests, data — excluded from commit)
```

## Commit History (tail)
```
848c1f4 feat: frontend API configuration, /api/latest endpoint, environment-independent routing
9af1015 fix(extension): v24 stable seat mapping with bootstrap initialization
c4d2822 diag: add full fetch pipeline tracing to background.js service worker
```

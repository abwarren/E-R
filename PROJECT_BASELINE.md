# PROJECT BASELINE — W4P PLO Poker Platform

**Last Updated:** 2026-07-03
**Current Status:** CONDITIONAL RELEASE (w4p-api-selection-v1, live validation pending)

## Repository

| Field | Value |
|-------|-------|
| Repository | `github.com:abwarren/E-R` |
| Branch | `master` |
| Local path | `/home/wa/projects/poker/E&R` |

## Current Production State

| Field | Value |
|-------|-------|
| Latest release | `w4p-api-selection-v1` |
| Latest commit | `ed293b9` |
| Previous release | `w4p-seat-stability-v1` (`94a6cfc`) |

## Release History

```
w4p-selector-registry-v1
  ↓
w4p-seat-stability-v1 (94a6cfc)
  ↓
w4p-api-selection-v1 (ed293b9)
  ↓
w4p-architecture-baseline-v1  ← current (investigation freeze, zero code changes)
  ↓ (planned)
Phase A: Fix authority (is_authoritative_snapshot)
  ↓ (planned)
Phase B: Complete hand_id propagation
  ↓ (planned)
Phase C: Partition state by (table_id, hand_id)
```

## Runtime Locations

| Component | Location | Port |
|-----------|----------|------|
| Flask backend | `backend/app.py` (Docker: `/app/backend/app.py`) | 1080 |
| Express bridge | `scripts/server.js` (Docker: `/app/scripts/server-container.js`) | 4000 |
| Engine equity | `ENGINEENGINE/source/app.py` (Docker) | 5002 |
| Chrome extension | `backend/static/ext/` (loaded unpacked from host filesystem) | — |
| Remote UI | `source/remote-w4p.html` (Express-served, SSOT) | via :4000 |
| State file | `state/state_snapshot.json` | — |
| Extension source | `source/w4p.js` (reference copy) | — |
| Extension loaded | `backend/static/ext/w4p.js` (browser loads this) | — |
| Engine poller | `source/engine_flow_controls.js` | — |

## Open Investigations

| ID | Subject | Status |
|----|---------|--------|
| Seat-Hand-Collision | Multi-bot state oscillation (15 reports, root causes identified) | **COMPLETE** — see `investigation/seat-hand-collision-2026-07-03/` |
| ADR-001 Phase 1 | hand_id echo from extension | Design complete; extension-side implementation pending |
| ADR-001 Phase 2 | Partition runtime state by (table_id, hand_id) | Design complete; implementation pending |
| TODO-001 | Transient name disappearance — preserve identity when `name=null` | Not started |
| TODO-003 | Event Store SQL schema | Design phase |

## Protection Levels

### 🔴 Level 1 — Engineering Process (Highest)

*May not be modified without explicit, separate approval. Feature approvals
do NOT include permission to modify process files. These files define how
engineers work — changing them requires a dedicated approval distinct from
any code change approval.*

| File | Purpose |
|------|---------|
| `W4P Project Context & Operating Directive.md` | Governing directive (FROZEN v1.0) |
| `.hermes/skills/*/er-poker-platform/SKILL.md` | Engineering methodology |
| `.hermes/skills/*/engineering-standards/SKILL.md` | Quality standards |
| `PLO/ADRs/ADR-*.md` | Architecture decisions |
| `ARCHITECTURE_BASELINE.md` | Architectural reference |
| `PROJECT_BASELINE.md` | This file |
| `RELEASE_MANIFEST.md` | Release process template |
| `RUNTIME_OWNERSHIP.md` | Canonical field ownership — who creates/modifies/consumes every runtime field |
| `investigation/seat-hand-collision-2026-07-03/AUTHORITY_MODEL.md` | Authority model — `is_authoritative_snapshot()` specification |

### 🟠 Level 2 — Production Runtime

*May not be modified without explicit approval. Every change must include
a PROPOSED CHANGE block with reason, files affected, impact, risk, and rollback.*

| Component | Files |
|-----------|-------|
| Extension | `source/w4p.js`, `backend/static/ext/w4p.js`, `bridge.js`, `background.js`, `manifest.json` |
| Backend | `backend/app.py`, `backend/equity_routes.py`, `backend/buffer.py` |
| Remote UI | `source/remote-w4p.html` |
| Engine | `source/engine_flow_controls.js`, `ENGINEENGINE/source/app.py` |
| Express | `scripts/server.js`, `scripts/server-container.js` |
| Docker | `docker-compose.yml`, `Dockerfile` |

### 🟢 Level 3 — Documentation

*May be created and updated without approval, provided no runtime code
changes. Investigation reports, release notes, validation plans, test scripts.*

| Examples |
|----------|
| `RELEASE_NOTES.md`, `LIVE_VALIDATION_REQUIRED.md` |
| Investigation reports, audit documents |
| Test scripts (no runtime impact) |

## Protected Runtime Components

These are off-limits unless explicitly targeted by the current task:

| Component | Status | Owner |
|-----------|--------|-------|
| Seat Assignment | ✓ Protected | Extension |
| Seat Cache | ✓ Protected | Extension |
| Selector Registry | ✓ Protected | Extension |
| Extension scrape | ✓ Protected | Extension |
| Snapshot Format | ✓ Protected | Extension → Backend |
| Backend table_state | ✓ Protected | Backend |
| Remote UI rendering | ✓ Protected | Remote UI |
| Engine polling | ✓ Protected | Engine |
| Bridge (postMessage) | ✓ Protected | Extension → Express |

## Protected Process Files

These may NOT be modified without explicit user request:

| File | Purpose |
|------|---------|
| `W4P Project Context & Operating Directive.md` | Governing directive (FROZEN v1.0) |
| `.hermes/skills/software-development/er-poker-platform/SKILL.md` | Engineering methodology |
| `.hermes/skills/software-development/engineering-standards/SKILL.md` | Quality standards |
| `PLO/ADRs/ADR-*.md` | Architecture decisions |
| `RELEASE_MANIFEST.md` | Release process template |

Feature work must not change process documentation.

### Engineering Rule: Single Field Ownership

*No runtime field may have more than one authoritative owner.*

Every field MUST answer:
- Who creates it?
- Who may modify it?
- Who consumes it?
- Under what conditions may it change?

If the answer is not in `RUNTIME_OWNERSHIP.md`, the change is not ready for implementation.

`is_authoritative_snapshot()` is the ONLY function that determines structural field authority.
No code anywhere else may contain `if available_actions:` or `if hero_active:` to decide
structural ownership. Everything calls `is_authoritative_snapshot()` or consumes the
result already computed by the backend.

### Engineering Rule: Ralph Loop (Implementation & QA Cycle)

The Ralph Loop is the mandatory, evidence-driven implementation and verification cycle for all runtime changes.

**Workflow:**

```
Stage 1: Architecture Approved
  ↓
Stage 2: Implementation
  ↓
Stage 3: Independent QA
  ↓
QA Verdict ── PASS ──→ Release Candidate
  │                        ↓
  │                    Deployment
  │                        ↓
  │                    Live Validation
  │                        ↓
  │                    Rollback Verified
  │                        ↓
  │                    Release Freeze
  │
  └── FAIL ──→ Evidence Package
                   • Runtime logs
                   • Screenshots
                   • Diff
                   • Exact file/function/line
                   • Root cause
                   • Proposed correction
                     ↓
               Implementation Engineer
                     ↓
               Fix ONLY approved issues
                     ↓
               Full QA Re-run (all tests, not only affected tests)
                     ↓
               QA Verdict (loop restarts)
```

**Permanent Rules:**

1. QA decisions are evidence-based, never opinion-based.
2. Every FAIL includes: reproduction steps, runtime evidence, expected vs actual behavior, exact source location, severity.
3. Every FAIL triggers a full regression suite, not just the affected tests.
4. The implementation engineer cannot override QA.
5. QA cannot implement production fixes.
6. No partial PASS. No conditional PASS. No "ship now, fix later."
7. Every release must satisfy all runtime invariants (I1–I4).
8. Every release must have a documented rollback.
9. Rollback must be verified before release freeze.
10. Live runtime validation is required before release closure.

**Exit Condition:**

The Ralph Loop terminates only when all three are true:

- QA Verdict = PASS
- Live Validation = PASS
- Rollback Verified = PASS

Otherwise the loop repeats.

Future directives may simply say: "Follow the Ralph Loop."

### Implementation Roadmap

```
Phase A: Fix authority (is_authoritative_snapshot)  ← NEXT
  ↓  Live validation
Phase B: Complete hand_id propagation (ADR-001 Phase 1)
  ↓  Live validation
Phase C: Partition state by (table_id, hand_id) (ADR-001 Phase 2)
```

Each phase is its own tagged release with rollback capability.
Phases are sequential — never parallel.

## Current Known Limitations

1. **Live validation deferred** — all releases require live observation with EC2/remote browser
2. **Multi-bot architecture not complete** — state not yet partitioned by `(table_id, hand_id)`; ADR-001 Phase 2 pending
3. **EC2 UFW blocks 4000/5002** — external browsers can't reach tunnel through EC2
4. **Express divergence** — `server.js` ≠ `server-container.js` (per-route vs flat proxy)
5. **Container staleness** — `ext/w4p.js` in container is stale backup (irrelevant — Chrome loads from host)
6. **Engine bridge URL regression** — v2.1.0 changed `BRIDGE_URL` from `/api/table/latest` to `/api/latest`, Flask proxy doesn't handle `/api/latest`

## Open Investigations

| ID | Subject | Status |
|----|---------|--------|
| ADR-001 Phase 2 | Partition runtime state by (table_id, hand_id) | Design complete; implementation pending |
| ADR-002 Live Validation | Multi-bot API selection — production observation | Deferred (EC2 down) |
| TODO-001 | Transient name disappearance — preserve identity when `name=null` | Not started |
| TODO-003 | Event Store SQL schema | Design phase |

## ADR Catalog

| ADR | Title | Date |
|-----|-------|------|
| ADR-001 | Multi-Bot State Isolation (hand_id generation + partitioning) | 2026-07-03 |
| ADR-002 | API Selection Policy for Multi-Bot Tables | 2026-07-03 |
| ADR-011 | BLOCKED is an acceptable engineering outcome | 2026-07-01 |
| ADR-012 | Frame discovery via confidence scoring | 2026-07-01 |
| ADR-013 | Desktop + Mobile as single product with selector registry | 2026-07-01 |
| ADR-014 | Selector registry validation with startup gate | 2026-07-01 |

## Incident Postmortems

See `er-poker-platform` skill — contains 5 postmortems covering:
- `hero_tbl2589954` synthetic name (2026-06-21)
- No seat containers (2026-06-21)
- v22 banner on v23 code (2026-06-21)
- `available_actions=[]` on all snapshots (2026-06-21)
- Flask :1080 dead for 27 hours — stale PID lock (2026-06-23)
- bridgeFetch regression via chore commit 74acebe (2026-07-01)

# Autonomous Engineering Roadmap

W4P's engineering pipeline evolves from manual debugging to autonomous verification.

Do not automate prematurely. Each phase must be **stable** before the next begins.

---

## Architecture

```
                         Runtime
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
   Observation DB      Event Store       Metrics DB
         │                  │                  │
         └──────────────────┼──────────────────┘
                            │
                    Correlation Engine
                            │
                    Confidence Engine
                            │
                      Rules Engine
                            │
                  Root Cause Analyzer
                            │
                 Suggested Patch Generator
                            │
                       Verification
                            │
                      QA Validator
                            │
                     GitHub Workflow
```

Three independent stores, each with a single responsibility:

| Store | Responsibility | Current Status |
|---|---|---|
| Observation DB | Raw runtime facts with provenance | Phase 1 — Being built |
| Event Store | Immutable event log for replay | Planned |
| Metrics DB | Aggregated statistics and trends | Future |

The pipeline flows top to bottom. Each stage consumes the output of the previous stage. No stage skips ahead.

---

## Phase 1 — Observe

**Status: In Progress**

```
Extension
    │
    ▼
Backend
    │
    ▼
API
    │
    ▼
UI
    │
    ▼
Observation DB
```

**What it does:** Records runtime facts. No decisions. No analysis. No conclusions.

**Input:** Live runtime (Extension → Flask → API → Remote UI → Engine UI).

**Output:** Raw observations in `analysis_runtime.db` with sequencing, provenance, and per-field source tracking.

**Rules:**
- No modification of runtime code or state
- No diagnosis of anomalies
- Facts only — values, timestamps, sources
- Every observation carries provenance (layer, component, git_sha, container, build)

**Deliverables:**
- `analysis_runtime.db` — Observation database
- `docs/runtime/ENTITY_DICTIONARY.md` — Entity definitions
- `RUNTIME_OBSERVATION_MISSION.md` — Observation methodology

**Success:** Every observable field from every layer is recorded with provenance and sequencing.

---

## Phase 2 — Correlate

**Status: Planned**

```
Observation DB
    │
    ▼
Correlation Engine
    │
    ▼
Confidence Scores
    │
    ▼
Stable Relationships
```

**What it does:** Builds measured relationships between entities using only observed data.

**Input:** Observation DB.

**Output:** Correlation table with confidence scores, observation counts, and contradiction counts.

**Example output:**

| Relationship | Confidence | Observations | Contradictions |
|---|---|---|---|
| Seat 3 ↔ allinstalker | 99.98% | 12,487 | 2 |
| Hero ↔ Seat 3 | 100% | 12,487 | 0 |
| Engine hand ↔ Seat 3 | 92% | 9,847 | 831 |

**Rules:**
- No assumed relationships — data-driven only
- Every correlation includes confidence, first/last observed, evidence sources, and contradiction count
- Contradictions logged as anomalies, not errors
- Confidence recalculated as new data arrives

**Deliverables:**
- Correlation engine (script or module)
- `PLAYER_CORRELATION_REPORT.md`
- `SEAT_IDENTITY_REPORT.md`
- `REMOTE_ENGINE_MAPPING.md`

**Success:** Every entity pair has a measured confidence score. Primary keys are identified.

---

## Phase 3 — Detect

**Status: Planned**

```
Runtime
    │
    ▼
Rules Engine
    │
    ▼
Anomaly Detection
    │
    ▼
Alert
```

**What it does:** Discovers anomalies without human prompting. Compares observed values against expected rules.

**Input:** Live runtime observations + correlation model.

**Output:** Anomaly incidents with automatic alerts.

**Example rule:**

```yaml
rule:
  name: MissingFieldPropagation
  description: >
    A field present in the Extension snapshot should be present
    in the API response. If it is missing, the backend merge
    dropped it.
  condition:
    extension.is_active == true
    api.is_active == false
  severity: high
  action: create_incident
```

```yaml
rule:
  name: HoleCardVisibilityConflict
  description: >
    Hole cards should be visible when the hero is active in a hand.
    If the hero is active but hole cards are null, something dropped
    the data between backend and Engine UI.
  condition:
    hero_active == true
    hole_cards == null
    street == "Preflop"
  severity: critical
  action: create_incident
```

```yaml
rule:
  name: StackDiscontinuity
  description: >
    A player's stack should change only by the amount of their action
    or by chips won at showdown. Any other change is a data error or
    an unobserved event.
  condition:
    abs(current_stack - previous_stack) not in [0, bet_amount, win_amount]
  severity: medium
  action: create_incident
```

**Rules:**
- Rules are versioned and stored with the codebase
- Rules can reference any field from any layer
- False positives are recorded and used to refine rules
- Alerts include full provenance for the anomalous values

**Deliverables:**
- Rules engine
- Rule definition format and storage
- Anomaly alert system
- `docs/runtime/RULES_CATALOG.md`

**Success:** Anomalies are detected within one snapshot of occurrence. No human monitoring required.

---

## Phase 4 — Diagnose

**Status: Planned**

```
Observation
    │
    ▼
Locate Transition Point
    │
    ▼
Determine First Mutation
    │
    ▼
Confidence Score
    │
    ▼
Suggested Fix
```

**What it does:** Given an anomaly, traces the data back through the pipeline to find where the value first diverged from expected.

**Input:** Anomaly incident + observation history + correlation model.

**Output:** Root cause analysis with confidence score and suggested fix location.

**Example:**

```
Anomaly: is_active = false at API layer but true at Extension layer

Trace:
  Extension (w4p.js)     → is_active = true   ✓
  Backend merge (app.py)  → is_active = false  ✗  ← FIRST MUTATION
  API response            → is_active = false  (inherited)
  Remote UI               → is_active = false  (inherited)

Root Cause: backend/app.py merge logic omitted is_active when
            constructing new_seats dictionary.

Confidence: 94%

Fix Location: backend/app.py, merge_snapshot() function
Suggested Fix: Copy is_active field into new_seats during merge
```

**Rules:**
- Always trace from observed anomaly backward to source
- Each layer in the trace is verified by provenance
- Confidence score required for every diagnosis
- Diagnosis is a suggestion, not a command — human review required

**Deliverables:**
- Root cause analyzer
- Trace visualization
- Suggested fix generator
- `docs/runtime/DIAGNOSIS_LOG.md` template

**Success:** Root cause identified with >90% confidence in under 60 seconds for common anomaly types.

---

## Phase 5 — Verify

**Status: Planned**

```
Patch
    │
    ▼
Tests
    │
    ▼
Replay
    │
    ▼
Live Verification
    │
    ▼
Regression Tests
```

**What it does:** Applies a proposed fix and verifies it against historical data and live runtime before human review.

**Input:** Suggested fix + observation replay data + test suite.

**Output:** Verification report — pass/fail with evidence.

**Verification sequence:**

1. **Unit tests** — Does the fix pass existing tests?
2. **Replay** — Re-run historical snapshots through the patched code. Does the anomaly disappear? Do any new anomalies appear?
3. **Live verification** — Deploy to a staging instance. Observe for N minutes. Compare against baseline.
4. **Regression** — Run the full test suite. Any regressions?

**Rules:**
- Fix never reaches human review without passing all four verification stages
- Replay must use real historical observations, not synthetic data
- Regression detection compares field-by-field, not just test pass/fail
- Verification report is immutable — created once, never edited

**Deliverables:**
- Verification engine
- Replay infrastructure (feed historical observations through patched code)
- Automated regression detection
- `VERIFICATION_REPORT.md` template

**Success:** 100% of fixes verified before human review. Zero regressions reach production.

---

## Phase 6 — QA

**Status: Planned**

```
┌─────────────────────────────────┐
│          QA Validator           │
├─────────────────────────────────┤
│ Did the fix work?               │
│ Did anything regress?           │
│ Is documentation updated?       │
│ Are tests passing?              │
│ Is the evidence sufficient?     │
│ Is the confidence acceptable?   │
│ Does this match the ADR?        │
└─────────────────────────────────┘
```

**What it does:** Automated QA gate. Validates that every requirement is met before a PR is created.

**Input:** Verification report + fix + test results + observation data.

**Output:** QA checklist with pass/fail per criterion. If any criterion fails, the PR is blocked.

**QA checklist:**

| Criterion | Evidence Required |
|---|---|
| Fix resolves the anomaly | Replay shows anomaly absent after patch |
| No regressions introduced | Full test suite passes; field-by-field comparison clean |
| Documentation updated | `CHANGELOG.md`, ADR if architectural, inline docs if API |
| Tests cover the fix | New test for the specific bug scenario |
| Evidence is sufficient | Observation count meets minimum threshold for confidence |
| Confidence is acceptable | Root cause confidence >90% |
| Architectural compliance | Change does not violate existing ADRs |

**Rules:**
- QA is a gate, not an advisor — if it fails, the pipeline stops
- Every criterion must be met; partial passes are failures
- QA report is immutable and attached to the PR
- If QA rejects, it must state exactly which criterion failed and why

**Deliverables:**
- QA validator
- `QA_CHECKLIST.md` template
- `docs/engineering/QA_STANDARDS.md`

**Success:** Every PR includes a complete QA report. No unreviewed changes reach the PR stage.

---

## Phase 7 — Merge

**Status: Planned**

```
Commit
    │
    ▼
Push
    │
    ▼
PR
    │
    ▼
QA Report
    │
    ▼
Human Review
    │
    ▼
Merge
```

**What it does:** Packages a verified, QA-approved fix into a PR for human review and merge.

**Input:** Verified fix + QA report + verification evidence.

**Output:** GitHub PR with full evidence package.

**PR contents:**
- Code change (minimal diff)
- Root cause analysis
- Verification report
- QA checklist (all passed)
- Replay evidence summary
- Regression test results

**Rules:**
- Human always makes the final merge decision
- PR must include all evidence — no "trust me" merges
- If human rejects, the pipeline records the reason for future learning
- Merged PRs become the new baseline for future verification

**Deliverables:**
- PR generation workflow
- Evidence package template
- Merge criteria document

**Success:** Human reviewers spend time on judgment, not verification. PRs are decision-ready on arrival.

---

## Phase 8 — Continuous Learning

**Status: Future**

**What it does:** The pipeline improves itself over time.

- Rejected PRs refine rules and confidence thresholds
- False positives tune anomaly detection sensitivity
- Successful root cause analyses improve the diagnosis model
- New entity relationships discovered during correlation become permanent
- QA criteria evolve as the codebase matures

This phase never ends. It is the feedback loop that makes every other phase smarter.

---

## Permanent Agent Roles

Each phase maps to a dedicated agent role. No agent does everything.

| Role | Phase | Responsibility |
|---|---|---|
| **Observer** | 1 | Records facts. No analysis. No conclusions. |
| **Correlator** | 2 | Builds relationships. Measures confidence. |
| **Analyzer** | 3-4 | Detects anomalies. Diagnoses root causes. |
| **Architect** | N/A | Designs solutions. Writes ADRs. Reviews structural changes. |
| **Developer** | 4-5 | Generates fixes. Writes code. |
| **Verifier** | 5 | Runs tests. Replays history. Detects regressions. |
| **QA** | 6 | Validates fixes. Checks documentation. Gates the PR. |
| **Documentation** | All | Maintains docs. Updates changelogs. Keeps the dictionary current. |
| **Release Manager** | 7 | Packages PRs. Creates evidence bundles. Manages the merge queue. |

**Principles:**
- One agent, one responsibility
- Agents communicate through artifacts (documents, databases, reports), not through prompts
- Any agent can be replaced without affecting others
- The pipeline is the coordinator, not any single agent

---

## End State

```
Developer writes code
         │
         ▼
  Runtime monitors itself
         │
         ▼
  Observations stored with provenance
         │
         ▼
  AI correlates events across layers
         │
         ▼
  Regression detected automatically
         │
         ▼
  AI proposes fix with root cause
         │
         ▼
  Replay verifies against historical data
         │
         ▼
  QA reviews evidence against all criteria
         │
         ▼
  PR created with full evidence package
         │
         ▼
  Human reviews and approves
         │
         ▼
  Merged
```

The human is not removed. They are **moved to the point where judgment is most valuable** — the architectural decision, the design choice, the final approval. Everything before that is evidence-gathering. Everything after that is execution.

---

## Current Status

**Phase 1 — Observe:** In progress.

- `RUNTIME_OBSERVATION_MISSION.md` — methodology defined
- `docs/runtime/ENTITY_DICTIONARY.md` — entities defined
- `analysis_runtime.db` — schema defined
- Provenance model — defined
- Sequencing model — defined

**Next step:** Execute the observation mission. Populate the database with live runtime data. Then move to Phase 2.

---

## Principles

1. **Never automate what you don't understand.** Each phase must be stable before the next begins.
2. **Facts before conclusions.** Observation precedes correlation. Correlation precedes diagnosis.
3. **Evidence over authority.** Every claim is backed by observations. Confidence scores, not opinions.
4. **Provenance is mandatory.** Every value carries its origin. No data without a source.
5. **The human judges. The pipeline proves.** The pipeline gathers evidence. The human makes the decision.
6. **One agent, one responsibility.** Split work across specialized agents. No monoliths.
7. **Artifacts over prompts.** Agents communicate through documents, databases, and reports — not through shared context windows.

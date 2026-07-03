# Runtime Observation Mission (READ-ONLY)

## Context

This project is **W4P**, a live poker observation platform.

### Current Runtime Architecture

```
GoldRush Poker
       │
       ▼
Chrome Extension (DOM parser)
       │
       ▼
POST /api/snapshot
       │
       ▼
Flask table_state (Single Source of Truth)
       │
       ├──► Remote UI (table visualization)
       │
       └──► Engine UI (hand analysis / action interface)
```

The **Remote UI** and **Engine** both consume the same backend data but present different views of it.

- **Remote UI**: A table visualization showing the poker table layout — seats, player names, stacks, community cards, and action indicators. It mirrors what a spectator would see at the table.
- **Engine UI**: A hand analysis and action interface. It displays hole cards, available actions, pot odds, and strategic information relevant to decision-making. It represents the perspective of a player (the hero) with access to their private hole cards.

Both UIs draw from a single Flask backend that maintains `table_state` as the single source of truth, which itself is populated by a Chrome Extension scraping the GoldRush Poker client DOM and POSTing snapshots to `/api/snapshot`.

---

## Mission

Observe the live runtime to understand how data relates across the system.

**This is not an implementation task.**

- Do **not** modify code.
- Do **not** alter the runtime.
- Do **not** commit.
- Do **not** push.

---

## Goal

Determine whether information displayed in the **Engine** can be **deterministically mapped** back to the corresponding player shown in the **Remote UI**.

---

## Observation Sources

Observe **only**:

1. Extension snapshots (raw DOM data before it reaches the backend)
2. Flask `table_state` (the in-memory or persisted state object)
3. `/api/latest` endpoint responses
4. Remote UI state (what the Remote UI renders)
5. Engine UI state (what the Engine UI renders)

---

## Event Sequencing

Every observation **must** be sequenced so events can be replayed in the exact order they occurred.

```
sequence:
  snapshot_seq:   <monotonic integer, unique per snapshot>
  hand_epoch:     <monotonic integer, resets to 0 at start of each hand>
  timestamp:      <ISO 8601 with timezone>
  table_id:       <stable table identifier>
```

- **`snapshot_seq`** — Global ordering. Never resets. The master timeline.
- **`hand_epoch`** — Intra-hand ordering. Resets to 0 when a new hand begins. Allows comparing snapshots within the same hand without needing absolute sequence numbers.
- **`timestamp`** — Wall-clock time of capture. For correlating with external logs.
- **`table_id`** — Which table produced this observation. Required because the platform may observe multiple tables.

Together these four fields allow an observer to replay events exactly as they occurred, group snapshots by hand, and correlate across tables.

---

## Provenance

Every observed value **must** record where it came from. This makes debugging across versions possible.

```
source:
  layer:      <extension | flask | api | remote_ui | engine_ui>
  component:  <w4p.js | app.py | remote.js | engine.js>
  git_sha:    <full commit hash of the running code>
  container:  <backend | remote | engine | extension>
  build:      <runtime | debug | release>
```

- **`layer`** — Which architectural layer produced the value.
- **`component`** — Which specific file or module.
- **`git_sha`** — The commit the code was built from. Critical when comparing observations across deployments.
- **`container`** — Which container or process generated the data.
- **`build`** — Build variant. A `debug` build may behave differently than `release`.

Provenance is recorded **per value**, not per snapshot. Two fields in the same snapshot may come from different layers. For example, `hole_cards` may originate from `engine_ui` while `player_name` originates from `remote_ui`.

---

## Local Observation Database

Create a completely separate SQLite database:

**`analysis_runtime.db`**

This database:

- Must **never** be read by the runtime
- Must **never** modify runtime behaviour
- Is **disposable**
- Exists **only** for analysis

### Schema — Snapshots Table

Every row is one point-in-time observation of the runtime state.

| Field | Type | Description |
|---|---|---|
| `snapshot_seq` | INTEGER | Monotonic global sequence number |
| `hand_epoch` | INTEGER | Monotonic intra-hand counter, resets to 0 per hand |
| `timestamp` | TEXT | ISO 8601 with timezone |
| `table_id` | TEXT | Stable table identifier |
| `hand_id` | TEXT | Hand identifier (if available from runtime, null otherwise) |
| `street` | TEXT | Preflop / Flop / Turn / River / Showdown |
| `board` | TEXT | Community cards (JSON array of card strings) |
| `pot` | REAL | Total pot size |
| `dealer` | INTEGER | Dealer seat index |
| `hero_seat` | INTEGER | Which seat is the hero |
| `hero_active` | INTEGER | 1 if hero is active in the hand, 0 otherwise |
| `available_actions` | TEXT | JSON array: e.g. `["fold","check","bet"]` |
| `players_json` | TEXT | Full player array as JSON — seats, stacks, names, status per player |
| `hole_cards` | TEXT | Hero's private cards when visible (JSON array, null when not) |
| `provenance` | TEXT | JSON object: `{"layer":"...","component":"...","git_sha":"...","container":"...","build":"..."}` for the snapshot as a whole |

### Schema — Observations Table

For per-field provenance when individual values within a snapshot come from different sources.

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-increment PK |
| `snapshot_seq` | INTEGER | FK to snapshots table |
| `field_name` | TEXT | Which field this observation covers (e.g. `hole_cards`, `player_name`) |
| `field_value` | TEXT | The observed value (JSON-encoded if complex) |
| `layer` | TEXT | extension / flask / api / remote_ui / engine_ui |
| `component` | TEXT | Specific file or module |
| `git_sha` | TEXT | Commit hash of running code |
| `container` | TEXT | Which container/process |
| `build` | TEXT | runtime / debug / release |

### Schema — Correlations Table

For every attempted mapping between entities.

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-increment PK |
| `relationship` | TEXT | Human-readable description of the mapping |
| `confidence` | REAL | 0.0 to 1.0 |
| `first_observed` | TEXT | ISO 8601 of first confirming observation |
| `last_observed` | TEXT | ISO 8601 of most recent confirming observation |
| `observation_count` | INTEGER | Number of snapshots confirming this relationship |
| `contradiction_count` | INTEGER | Number of snapshots contradicting this relationship |
| `evidence_sources` | TEXT | JSON array of layers that confirmed it: `["remote_ui","engine_ui"]` |
| `evidence_fields` | TEXT | Which specific fields were used to establish the mapping |
| `git_sha_range` | TEXT | Commit range this correlation was observed under: `"23550bde..a1b2c3d4"` |
| `notes` | TEXT | Any caveats or conditions |

### Schema — Anomalies Table

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-increment PK |
| `snapshot_seq` | INTEGER | Snapshot where the anomaly was observed |
| `timestamp` | TEXT | ISO 8601 |
| `hand_epoch` | INTEGER | Intra-hand position |
| `table_id` | TEXT | Which table |
| `anomaly_type` | TEXT | Short category label |
| `observed` | TEXT | What was observed (verbatim field values) |
| `expected` | TEXT | What would have been expected under normal conditions |
| `frequency` | TEXT | e.g. "3 times in 287 snapshots" |
| `source_layer` | TEXT | Which layer the anomalous value came from |
| `source_component` | TEXT | Which component |
| `git_sha` | TEXT | Commit hash at time of anomaly |
| `conclusion` | TEXT | Must be "No conclusion drawn" unless independently verified |

---

## Correlation Model

Attempt to build relationships:

```
Seat
  ↓
Player Name
  ↓
Hero
  ↓
Hole Cards
  ↓
Engine Hand
  ↓
Remote Seat
```

**Do not assume relationships.** Every relationship must be backed by observations.

---

## Confidence Model

Every mapping **must** include:

| Attribute | Description |
|---|---|
| `confidence` | 0.0 to 1.0 (or percentage) |
| `first_observed` | Timestamp of first confirming observation |
| `last_observed` | Timestamp of most recent confirming observation |
| `observation_count` | Number of snapshots confirming the relationship |
| `contradiction_count` | Number of snapshots contradicting |
| `evidence_sources` | Which layers/provenance confirmed it |
| `git_sha_range` | Code versions this was observed under |

Example:

| Relationship | Confidence | Observations | Contradictions |
|---|---|---|---|
| Seat 3 ↔ allinstalker | 100% | 247 | 0 |
| Hero ↔ Seat 3 | 100% | 247 | 0 |
| Engine hand ↔ Seat 3 | 92% | 188 | 16 |

---

## Poker Entity Model

All entities are defined in `docs/runtime/ENTITY_DICTIONARY.md`. Reference that document — do not redefine terms here.

Key entities: Session, Table, Hand, Street, Board, Pot, Seat, Player, Stack, Bot, Action, Cash-out, Snapshot, Observation, Correlation, Anomaly, Command.

---

## Record Anomalies

If observations contradict expectations, **record them without diagnosing them**.

Example:

> **Observation:** `snapshot_seq = 626239`
>
> **Provenance:** `layer=api`, `component=app.py`, `git_sha=23550bde`
>
> `available_actions = ["check","bet"]`
>
> `is_active = false`
>
> **Frequency:** Observed 3 times in 287 snapshots.
>
> **Conclusion:** No conclusion drawn.

**Do not speculate about causes.**

---

## Determine Stable Identifiers

Assess the stability of each field across hands and sessions. Rank each as:

- **Stable** — Never changes for a given entity
- **Mostly Stable** — Rarely changes, changes are predictable
- **Volatile** — Changes frequently, unpredictable
- **Unknown** — Not enough data to assess

Fields to assess:

- `seat_index`
- `player_name`
- `hero_flag`
- `stack`
- `available_actions`
- `hole_cards`
- `board`
- `dealer`
- `street`
- `hand_id`
- `table_id`
- `pot`

Record results with provenance so stability can be re-evaluated across code versions.

---

## Deliverables

Produce **six** documents under `docs/runtime/`:

### 1. RUNTIME_OBSERVATION_REPORT.md

Raw observations. A log of every snapshot examined, fields recorded, and any anomalies noticed. This is the evidence base. Structured as a chronological log with `snapshot_seq` as the primary index. Every entry includes sequencing and provenance.

### 2. PLAYER_CORRELATION_REPORT.md

How players relate to seats, the hero, and each other across hands.
- Player name stability across sessions
- Player ↔ seat mapping stability
- Hero identification reliability
- Stack-to-player association accuracy

### 3. SEAT_IDENTITY_REPORT.md

Whether seat indices are stable identifiers.
- Does seat 3 always mean the same position?
- Does seat numbering change between hands?
- Does the dealer button shift affect seat identity?
- Remote seat numbering vs Engine seat numbering

### 4. REMOTE_ENGINE_MAPPING.md

The core question: can Engine data be mapped to Remote seats and players?
- Engine hand → Remote seat path analysis
- Remote seat → player name → hole cards → Engine display path analysis
- Confidence levels for each mapping direction
- Ambiguities and unresolved cases

### 5. POKER_ENTITY_MODEL.md

The entity-relationship model derived from observations.
- Entity definitions with stable attributes
- Relationship cardinalities
- Lifecycle of each entity
- Which entities can serve as foreign keys
- Recommended primary keys for the future Event Store

### 6. OBSERVED_ANOMALIES.md

Every anomaly recorded, with no diagnosis. Organized by anomaly type. Includes:
- Snapshot reference with sequencing
- Provenance of the anomalous value
- What was observed
- What was expected
- Frequency
- No conclusion drawn unless independently verified

### Prerequisite: ENTITY_DICTIONARY.md

Exists at `docs/runtime/ENTITY_DICTIONARY.md`. All other documents reference this for entity definitions.

---

## Success Criteria

By the end of the observation period we should be able to answer:

1. **Can Engine hands be mapped to Remote seats?** — With what confidence? Through what path?
2. **Can hole cards be deterministically assigned to players?** — Always? Sometimes? Under what conditions?
3. **Which identifiers are stable enough to become SQL primary keys?** — For players, seats, hands, sessions.
4. **Which relationships require additional metadata?** — What's missing that would make the mapping perfect?
5. **What should the future Event Store persist?** — Schema recommendations based on observed reality, not assumptions.

---

## Success

The objective is **understanding**, not implementation.

At the end of the investigation we should know **exactly** how Remote, Engine, and the underlying runtime relate to one another, without having modified a single line of production code.

---

## Long-Term Vision

This observation methodology is designed to scale beyond the current mission.

```
Extension
    │
    ▼
Observation
    │
    ▼
Event Store
    │
    ▼
Analytics
    │
    ▼
Replay ──► AI ──► Regression Testing
```

The same structure — observe, store, correlate, measure confidence, detect anomalies, form conclusions — applies to any subsystem being instrumented, whether ECU communication, cloud synchronization, or hardware telemetry.

This document is a **project standard**, not a one-off mission.

# ADR-001: Multi-Bot State Isolation

**Status:** Proposed
**Date:** 2026-07-03
**Author:** Hermes Agent (investigation phase)
**Supersedes:** None

---

## Context

The W4P backend uses a single in-memory dictionary `_tables` keyed by `table_id` to store all table state. When multiple Chrome extensions (one per poker bot/account) POST snapshots for the same `table_id`, they share a single mutable state object. Structural fields (`street`, `board`, `pot_zar`, `dealer_seat`) are overwritten unconditionally by the last writer.

The investigation (see `investigation/ROOT_CAUSE_VERIFICATION.md`) identified this as the primary architectural cause of UI flicker. The investigation also identified a critical unresolved question:

> **Are the bots at the same physical table (sharing a board/street/pot) or at different game instances that happen to have the same `table_id`?**

The architecture must handle both scenarios. The chosen strategy must not assume either is the only case.

Additionally, the `db_logger.py` module already has a `hand_id`-based data model (`hand_results`, `hand_actions` tables). This precedent suggests that hand-level identity is the correct unit of state ownership, but it is not yet wired into the live state model.

---

## Problem Statement

How should the backend isolate state when multiple bots post snapshots for the same `table_id`?

### Constraints

1. **No regression of single-bot operation.** The single-bot case (current primary use) must continue to work identically.
2. **The Remote UI must not require changes.** It consumes `/api/latest` and expects one coherent table view.
3. **The Engine must not require changes.** It reads table state for equity calculations.
4. **Future SQL Event Store compatibility.** The chosen model should map naturally to relational schema.
5. **Minimal extension changes.** Modifying the Chrome extension is high-cost (extension store update, browser reload, multiple instances).

### What's at stake

If merge logic is changed without defining the correct ownership model first, subtle bugs will propagate to the Remote UI, Engine, and future Event Store. The previous investigation already proved that rendering is not the problem — the state model is.

---

## Options Considered

### Option A: State keyed by `(table_id, bot_id)`

Each bot gets its own independent table state entry. No shared state between bots.

```
_tables = {
    ("pb_2589955", "monarchi"): { street, board, pot, seats, ... },
    ("pb_2589955", "Atros"):    { street, board, pot, seats, ... },
}
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness — same table, different seats | **WRONG.** Board, street, pot, and dealer are duplicated. If one bot's DOM scrape misses a board card, the states diverge with no reconciliation. |
| Correctness — different tables, same table_id | **CORRECT.** Each bot's view is isolated. No cross-contamination. |
| Regression risk | **HIGH.** `/api/latest` returns one table. Which bot's perspective does it return? The UI/Engine would need to know which bot to query. |
| Remote API impact | **BREAKING.** `/api/latest` must now accept a `bot_id` parameter or return a merged view. |
| Engine impact | **BREAKING.** Engine reads from `/api/table/latest`. Needs to know which bot's view. |
| SQL Event Store compatibility | **POOR.** Two separate rows for the same physical hand. Violates normalization. |
| Extension changes | None required. `bot_id` is already in the payload. |

**Verdict:** Rejected. Destroys shared table context for same-table multi-bot scenarios. Breaks the Remote UI and Engine APIs.

---

### Option B: State keyed by `(table_id, hand_id)`

State is partitioned by hand identifier. All bots in the same hand share one state object.

```
_tables = {
    ("pb_2589955", "hand_abc123"): { street, board, pot, seats, ... },
    ("pb_2589955", "hand_def456"): { street, board, pot, seats, ... },
}
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness — same table, different seats | **CORRECT.** All bots in the same hand share state. |
| Correctness — different tables, same table_id | **CORRECT.** Different hands get different state objects. |
| Regression risk | **MEDIUM.** Single-bot case works if hand_id is stable. |
| Remote API impact | **LOW.** `/api/latest` returns the most recent hand. Same interface. |
| Engine impact | **LOW.** Same interface. May need hand_id for historical queries. |
| SQL Event Store compatibility | **EXCELLENT.** Maps directly to `hand_results.hand_id`. |
| Extension changes | **POTENTIALLY REQUIRED.** The extension does not currently send a `hand_id`. The backend would need to generate one and the extension would need to echo it back. |

**Critical dependency: hand_id generation.**

The extension currently sends NO hand identifier (see `HAND_IDENTIFICATION_ANALYSIS.md`). The `deal_id` hook in `make_hand_key()` is dead code. Options for generating a hand_id:

1. **Backend generates UUID on first PREFLOP snapshot, returns in response, extension echoes in subsequent POSTs.** Requires extension modification (add `hand_id` to `bridgeFetch` response handler and `buildSnapshot`).
2. **Backend derives hand_id from deterministic fingerprint** (dealer seat + player composition + table_id). No extension changes needed. But fragile — if a player sits out and re-joins, the fingerprint may change.
3. **Hybrid:** Backend generates UUID, stores in `_tables` response, but also accepts a client-supplied `deal_id` if the PokerBet DOM ever exposes one.

**Verdict:** Best long-term solution but requires solving the hand_id generation problem. The cleanest approach is Option B with backend-generated UUID + extension echo (Variant B1).

---

### Option C: State keyed by `(table_id, perspective)` — Layered Model

A single table entry with two layers:
- **Shared layer:** `street`, `board`, `pot_zar`, `dealer_seat` — common to all observers
- **Per-bot layer:** `hole_cards`, `available_actions`, `is_active`, `is_hero` — hero-specific

```
_tables["pb_2589955"] = {
    "shared": {
        "street": "FLOP",
        "board": {"flop": [...], "turn": None, "river": None},
        "pot_zar": 12.50,
        "dealer_seat": 5,
    },
    "heroes": {
        "monarchi": {
            "seat_no": 3,
            "hole_cards": ["Ah", "Kh"],
            "available_actions": ["fold", "call", "raise"],
            "is_active": True,
            "stack_zar": 100.00,
        },
        "Atros": {
            "seat_no": 6,
            "hole_cards": ["2d", "3d"],
            "available_actions": [],
            "is_active": False,
            "stack_zar": 50.00,
        },
    },
    "seats": [...]  // merged view from all hero perspectives
}
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness — same table, different seats | **CORRECT.** Shared layer reflects the common board/pot/street. Each hero sees their own cards and actions. |
| Correctness — different tables, same table_id | **WRONG.** If bots are at different physical tables, the shared layer oscillates just like today. The layered model assumes a common table context that doesn't exist. |
| Regression risk | **LOW.** Single-bot case: shared layer = bot's view, heroes = one entry. Identical to current behavior. |
| Remote API impact | **MEDIUM.** `/api/latest` response structure changes slightly. The Remote UI would need to query per-hero seat data differently. |
| Engine impact | **LOW.** Engine reads board/pot/street from shared layer. Seat-level data comes from per-hero layer. |
| SQL Event Store compatibility | **GOOD.** `hand_results` stores shared layer. `hand_actions` stores per-bot data. |
| Extension changes | None required. Structural fields and per-bot data are already in the payload. |

**Verdict:** Correct for same-table multi-bot but incorrect for different-table collision. This option ASSUMES the bots are at the same table. If they are not, the flicker persists in the shared layer.

---

### Option D: Option B + Option C (Hybrid — Hand-Partitioned Layered Model)

Combine the layered model from Option C with hand-based partitioning from Option B.

```
_tables = {
    ("pb_2589955", "hand_abc123"): {
        "shared": { street, board, pot, dealer },
        "heroes": { "monarchi": {...}, "Atros": {...} },
        "seats": [...]
    },
    ("pb_2589955", "hand_def456"): {
        "shared": { street, board, pot, dealer },
        "heroes": { "monarchi": {...} },
        "seats": [...]
    },
}
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness — same table, different seats | **CORRECT.** Same hand → same partition → shared layer + per-hero data. |
| Correctness — different tables, same table_id | **CORRECT.** Different hands → different partitions → no cross-contamination. |
| Regression risk | **MEDIUM.** Single-bot case works trivially. More state objects to manage. |
| Remote API impact | **MANAGEABLE.** `/api/latest` returns the most recent hand's merged view. `/api/tables` lists all active hands. |
| Engine impact | **MANAGEABLE.** Engine queries by `(table_id, hand_id)` or just gets latest. |
| SQL Event Store compatibility | **EXCELLENT.** Matches `hand_results.hand_id` + `hand_actions` schema exactly. |
| Extension changes | **POTENTIALLY REQUIRED.** Same hand_id dependency as Option B. |

**Verdict:** The most architecturally correct solution. Handles both scenarios. Maps to existing DB schema. The cost is the hand_id generation problem (same as Option B).

---

### Option E: Conflict Detection Only (Conservative)

Don't change the merge model. Instead, detect when two bots disagree on a structural field and:
1. Log the conflict
2. Apply a heuristic (e.g., prefer the value from the bot with the most complete board)
3. Do NOT clear seat data on hand reset unless ALL bots agree it's a new hand

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness — same table, different seats | **ADEQUATE.** If bots agree on board/street (they should at same table), conflicts are rare. Falls back to last-writer-wins when they don't disagree. |
| Correctness — different tables, same table_id | **POOR.** Heuristics break down with genuinely conflicting data. A tiebreaker can't invent truth. |
| Regression risk | **LOWEST.** Minimal code changes. Same data model. |
| Remote API impact | None. |
| Engine impact | None. |
| SQL Event Store compatibility | **NEUTRAL.** No change. |
| Extension changes | None. |

**Verdict:** Reduces flicker but doesn't fix the root cause. Acceptable as a tactical mitigation, unacceptable as a strategic solution.

---

## Decision

**Recommendation: Option D — Hand-Partitioned Layered Model** with the following phased implementation:

### Phase 1: Hand Identification (prerequisite)

Before any state model change, establish a stable hand identifier:

1. **Backend generates a `hand_id` (UUID4)** when it detects a new hand (first PREFLOP snapshot after table creation, or street regression with board clearing).
2. **Return `hand_id` in the POST /api/snapshot response.** The extension's `handleSnapshotResponse` stores it.
3. **Extension echoes `hand_id` in subsequent POSTs.** Added to the `snap` object in `buildSnapshot()`.
4. **Fallback:** If the extension doesn't echo a hand_id (old extension version), the backend uses `make_hand_key()` as a best-effort fallback. This maintains backward compatibility.

### Phase 2: Partition state by `(table_id, hand_id)`

1. Change `_tables` key from `table_id` to `(table_id, hand_id)`.
2. Route incoming snapshots to the correct partition based on `hand_id` (from extension) or derived `hand_key` (fallback).
3. `/api/latest` returns the most recently updated partition. Add optional `?hand_id=` parameter.
4. `/api/tables` lists all active partitions, grouped by `table_id`.

### Phase 3: Layer shared vs. per-hero state

1. Within each partition, separate the shared layer from per-hero data.
2. The merge algorithm updates the shared layer only when the board/street is more advanced (progressive merge, not last-writer-wins).
3. Per-hero data is isolated by `bot_id` and never overwritten by another bot.

### Phase 4: Cleanup

1. Remove the `_last_good_view` cache (no longer needed — the hand partition prevents flicker at source).
2. Wire `hand_id` into `db_logger.start_hand()` calls.
3. Remove dead code: `deal_id` path in `make_hand_key()` that's never populated.

---

## Consequences

### Positive

- **Flicker eliminated at root cause.** No oscillation regardless of bot count or game state divergence.
- **Correct for both scenarios.** Same-table multi-seat and different-table collision both handled.
- **Maps to existing DB schema.** `db_logger.py` already models `hand_id` → `hand_results` + `hand_actions`.
- **Backward compatible.** Single-bot operation unchanged. Old extensions work via fallback hand_key.
- **Future-proof.** The SQL Event Store can directly consume the partitioned state.
- **Cleaner separation of concerns.** Shared table context vs. per-hero private state is explicitly modeled.

### Negative

- **Extension modification required** (Phase 1). Requires extension store update, browser reload across all bot instances.
- **Increased state complexity.** Multiple partitions per table_id, two-layer state model. More code to maintain.
- **Transition period risk.** Old extensions (without hand_id echo) use fallback hand_key which has the same PREFLOP collision problem. Acceptable risk: during transition, behavior is no worse than today.
- **`/api/latest` semantics change.** Currently returns "the latest table." After change, returns "the latest hand." The Remote UI and Engine must be verified against this semantic difference.
- **Hand boundary detection remains heuristic.** The backend still determines "new hand" from street regression + board clearing. A mis-detection creates a spurious partition. Low-frequency issue compared to the current oscillation.

### Neutral

- **Memory usage increases.** Each hand creates a new partition. With 20-hand FIFO history in `_hand_history`, memory is bounded. Old partitions naturally expire when all bots post to a newer hand.
- **`_seat_bots` persistence semantics change.** Currently persists across hand resets. With partitions, bot-to-seat mapping is scoped within a hand. On new hand, mapping is re-discovered from the first hero POST.

---

## Alternatives Considered but Rejected

| Option | Why Rejected |
|--------|-------------|
| Option A: bot_id partitioning | Destroys shared table context. Breaks UI/Engine APIs. |
| Option C: layered model only | Wrong for different-table collision. Assumes shared context. |
| Option E: conflict detection | Treats symptom, not cause. Acceptable as mitigation, not solution. |
| Reduce polling frequency | Masks the race condition, doesn't fix it. Architecture stays broken. |
| Don't merge — show one bot at a time | Defeats the purpose of multi-bot observation. |

---

## Open Questions

1. **Runtime verification needed:** Are bots at the same physical table or different tables? The answer determines whether Option C alone would suffice or Option D is required. The ADR recommends Option D regardless, but the urgency of Phase 3 (layered model) depends on this answer.

2. **Hand boundary detection robustness:** Can the current `_detect_new_deal()` logic (street regression + board clearing) reliably detect hand boundaries when multiple bots are contributing? A spurious hand partition is far less destructive than the current oscillation (it creates a new partition rather than clearing the old one), but accuracy matters for the SQL Event Store.

3. **Extension deployment timeline:** How quickly can a modified extension be deployed to all bot instances? Phase 1's hand_id echo is a hard dependency for the cleanest implementation. The fallback hand_key reduces urgency but is imperfect.

4. **`/api/latest` consumer audit:** Which components beyond the Remote UI and Engine consume `/api/latest`? The response shape changes minimally (adds `hand_id`), but any hardcoded assumptions about the structure need verification.

# ADR-002: API Selection Policy for Multi-Bot Tables

**Status:** Proposed
**Date:** 2026-07-03
**Author:** Hermes Agent (investigation phase)
**Supersedes:** None (new ADR)
**Depends on:** ADR-001 (hand_id generation — Phase 1 deployed, extension echo pending)

---

## Context

### Current State

The W4P backend now stores per-bot state via `_tables[(table_id, bot_id)]` (deployed in commit `a58a6ee`). Each bot's entry is internally stable. However, the API endpoint `/api/latest` — consumed by the Remote UI and Engine — must return a SINGLE table view. The current selector `_dedup_latest_by_table()` picks the entry with the highest `last_ts` across all bots for the same `table_id`. When bots observe different game states (different streets, boards, pots), this selector alternates between bot entries, causing visible oscillation in the Remote UI.

The investigation (`FLICKER_ROOT_CAUSE.md`) confirmed:
- Per-bot entries are internally coherent — no cross-contamination
- The oscillation originates at the API selection boundary
- Snapshot rate is NOT the problem
- The structural field gate is bypassed by `back_to_game` actions

### What Changed

The baseline architecture (`w4p-seat-stability-v1`, commit `94a6cfc`) was single-bot: one `_tables[table_id]` entry, one consistent view. `/api/latest` had an unambiguous semantic: "return the latest state for the table."

With multi-bot operation and per-bot isolation, there are now N legitimate "latest" states for the same `table_id`. The API's original semantic is underspecified for this new reality.

### Consumers of `/api/latest`

| Consumer | How It Uses the Response | Bot-Aware? |
|----------|-------------------------|------------|
| Remote UI (`remote-w4p.html`) | Renders seat grid, street label, board, pot, dealer, actions | No — renders whatever the API returns |
| Engine (`engine_flow_controls.js`) | Populates textarea for equity calculation | No — processes whatever the API returns |
| Internal (SSE, status, debug) | Pushes state changes to connected clients | No — all consumers see the same response |

None of these consumers currently pass a `bot_id` parameter, though the API now supports `?bot_id=` (added in `a58a6ee`).

### Observed Bot Profiles

From runtime analysis (33,420 snapshots, 9,874 seconds):

| Bot | State | Typical Actions |
|-----|-------|----------------|
| Atros | Alternates between playing and idle | check, bet, fold, call, back_to_game |
| monarchi | Alternates between playing and idle | check, bet, fold, call, back_to_game |
| allinstalker | Always in lobby/waiting | back_to_game (always) |

allinstalker is perpetually in a non-playing state — `back_to_game` is a lobby-rejoin button, not a poker action. This bot's `available_actions` are always non-empty, which defeats the `hero_active` gate in commit `5a31670`.

---

## Problem Statement

What should `/api/latest` return when multiple bots have per-bot entries for the same `table_id`, and those entries contain different game-state observations (street, board, pot, dealer)?

### Constraints

1. **No regression of single-bot operation.** Default behavior when only one bot exists must be identical to today.
2. **The Remote UI must not require changes.** It consumes a single table view and expects the current response shape.
3. **The Engine must not require changes.** It reads table state from the same endpoint.
4. **The selection must be deterministic.** Given the same set of bot entries with the same data, the API must return the same result. No oscillation.
5. **The selection must be correct for the consumer.** The Remote UI displays a single poker table — the consumer expects to see the state of a poker game, not an arbitrary bot's lobby screen.
6. **Future SQL Event Store compatibility.** The chosen policy should not complicate per-hand state partitioning (ADR-001).

### What's at stake

The Remote UI is the primary human-facing interface for the platform. If it flickers between game states, the operator cannot trust the data. The engine's equity calculations depend on accurate street/board/pot state. The wrong selection policy produces wrong equity results.

---

## Options Considered

### Option A: Multi-Criteria Scoring with Freshness Window ("best game state")

**Policy:** Score each candidate entry against multiple criteria in priority order. A candidate must be recent (within freshness window) to be considered. Among candidates, prefer highest street rank, then most recently updated, then deterministic tiebreak.

```
FRESHNESS_WINDOW = 30  # seconds — must have been updated within this window
STREET_RANK = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}

def _select_best_table(table_id=None):
    """Return the best entry for the given table_id.
    
    Selection algorithm (priority order):
    1. Candidate must be recent (last_ts within FRESHNESS_WINDOW)
    2. Highest street rank wins (RIVER > TURN > FLOP > PREFLOP)
    3. If streets equal, most recently updated wins (highest last_ts)
    4. If still tied, deterministic ordering (alphabetical by bot_id)
    
    If no recent candidates exist, fall back to most recently updated
    entry (any age) to avoid returning nothing.
    """
    now = time.time()
    
    if table_id:
        entries = [(t, bid) for (tid, bid), t in _tables.items() if tid == table_id]
    else:
        # Select per table, return overall best
        best_per_table = {}
        for (tid, bid), t in _tables.items():
            rank = _entry_score(t, now)
            if tid not in best_per_table or rank > _entry_score(best_per_table[tid][0], now):
                best_per_table[tid] = (t, bid)
        entries = [(t, bid) for t, bid in best_per_table.values()]
    
    if not entries:
        return None
    
    # Prefer recent entries
    recent = [(t, bid) for t, bid in entries
              if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW]
    
    if not recent:
        # No recent entries — fall back to most recently updated (any age)
        recent = entries
    
    recent.sort(key=lambda x: _entry_score(x[0], now), reverse=True)
    return recent[0][0]

def _entry_score(t, now):
    """Sort key: (is_recent, street_rank, last_ts, -bot_id). Higher = better.
    
    is_recent: 1 if within freshness window, 0 otherwise
    This ensures recent entries always sort above stale ones, regardless of street.
    """
    is_recent = 1 if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW else 0
    street_rank = STREET_RANK.get(t.get("street", "PREFLOP"), 0)
    last_ts = t.get("last_ts", 0)
    bot_id = t.get("bot_id", "")
    return (is_recent, street_rank, last_ts, -hash(bot_id) % 1000000)
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Stale-advanced-street scenario | **SOLVED.** Bot B: TURN at age 45s vs Bot A: FLOP at age 4s → B fails freshness check → A wins. Old TURN cannot dominate fresh FLOP. |
| Correctness — bots on same hand | **CORRECT.** All recent bots share the same street. `last_ts` picks the freshest. |
| Correctness — different game contexts | **MOSTLY CORRECT.** Lobby bot (PREFLOP, always fresh) still loses to playing bots (FLOP+, also fresh). Two bots in different hands both past PREFLOP both pass freshness → still picks higher street. This edge case requires ADR-001 Phase 2. |
| Determinism | **YES.** Scoring is total order: freshness > street > last_ts > hash(bot_id). |
| allinstalker scenario | **SOLVED.** allinstalker (PREFLOP, recent) vs Atros (FLOP, recent) → Atros wins on street rank. |
| Regression risk | **LOW.** Single-bot: one entry always passes freshness → selected. |
| Empty freshness window | **FALLBACK.** If ALL entries are stale (system-wide outage), falls back to most recent by last_ts. Never returns empty when data exists. |

**Verdict:** Accepted. Multi-criteria scoring prevents stale advanced streets from dominating fresh earlier streets. The freshness window is the safety valve that street-rank-only selection lacks. Still requires no consumer changes.

---

### Option B: Return the Entry from the Most-Active Bot ("most engaged")

**Policy:** Among all entries, return the one whose hero has the most poker-relevant `available_actions` (excluding `back_to_game`).

```python
GAME_ACTIONS = {"fold", "check", "call", "bet", "raise", "all_in"}

def select_most_active(table_id):
    entries = [t for (tid, _bid), t in _tables.items() if tid == table_id]
    best = None
    best_score = -1
    for t in entries:
        # Find the hero seat
        hero = next((s for s in t.get("seats", {}).values() if s.get("is_hero")), None)
        if not hero:
            continue
        actions = set(hero.get("available_actions", []))
        score = len(actions & GAME_ACTIONS)  # count of poker-relevant actions
        if score > best_score:
            best_score = score
            best = t
    return best or max(entries, key=lambda t: t["last_ts"])
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness | **GOOD for same-hand.** The bot with the most poker options is the one whose turn it is. **POOR for different-hand.** A bot with "fold, call, raise" in Hand X beats a bot with "check" in Hand Y — but Hand Y may be the one the operator cares about. |
| Determinism | **NO.** Multiple bots can have the same action count. Falls through to non-deterministic tiebreaker. |
| allinstalker scenario | **SOLVED.** `back_to_game` is excluded from `GAME_ACTIONS` → score=0 → never selected over a bot with real poker actions. |
| Complexity | **HIGHER than A.** Requires iterating seats to find hero, computing action sets. |
| Edge case: all bots idle | All score 0 → falls through to `last_ts` → same as current behavior. |

**Verdict:** Over-engineered. Option A achieves the same practical result (lobby bot excluded, playing bot preferred) with simpler logic. Action-based scoring adds complexity without proportional benefit.

---

### Option C: Merge Shared State, Return One View ("canonical merge")

**Policy:** The API constructs a merged view: take the most advanced street/board/pot from the entry with the highest street rank (as Option A), but populate per-seat data from ALL bot entries.

```
┌─────────────────────────────────────────────────────────┐
│ MERGED VIEW                                             │
│                                                         │
│ Shared (from best entry):                               │
│   street = max(street across entries)                    │
│   board  = board from that entry                        │
│   pot    = pot from that entry                          │
│   dealer = dealer from that entry                       │
│                                                         │
│ Per-seat (merged from all entries):                     │
│   Seat 1: allinstalker (hero data from allinstalker)    │
│   Seat 5: Atros (hero data from Atros)                  │
│   Seat 5: monarchi (hero data from monarchi)             │
│   ...other observed seats...                            │
└─────────────────────────────────────────────────────────┘
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness — same hand | **BEST.** All bots' hero data visible in one view. Shared state reflects the actual game. |
| Correctness — different hands | **WORST.** Merges seats from different game contexts into one view. A seat at FLOP in Hand X merged with a seat at PREFLOP in Hand Y → incoherent view. |
| Determinism | **YES.** Street-based priority is deterministic. |
| Regression risk | **HIGH.** Response shape changes if multiple hero entries exist for the same seat_no. The Remote UI currently expects one entry per seat. |
| Remote UI impact | **BREAKING.** May need to handle multiple hero entries per seat position. |
| Complexity | **HIGHEST.** Merge logic is subtle, edge cases are many. |

**Verdict:** Architecturally aspirational but premature. Requires hand_id partitioning (ADR-001 Phase 2) to know which seats belong to the same game context. Without that, it merges apples and oranges.

---

### Option D: Return All Bot Perspectives ("multi-view API")

**Policy:** `/api/latest` returns an array of per-bot views. The Remote UI selects or displays all.

```json
{
  "ok": true,
  "tables": {
    "pb_2589955": [
      {"bot_id": "Atros", "street": "FLOP", ...},
      {"bot_id": "monarchi", "street": "FLOP", ...},
      {"bot_id": "allinstalker", "street": "PREFLOP", ...}
    ]
  }
}
```

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness | **CORRECT.** No information lost. Consumer has full data. |
| Regression risk | **HIGH.** Response shape changes fundamentally. |
| Remote UI impact | **BREAKING.** Must be rewritten to handle multi-view. |
| Engine impact | **BREAKING.** Must select which view to use for equity. |

**Verdict:** Rejected. Violates constraint #2 (Remote UI must not require changes). This is a valid long-term direction (the Remote UI could show a bot selector dropdown) but not appropriate as a tactical fix for the current oscillation.

---

### Option E: Require `bot_id` Parameter ("explicit selection")

**Policy:** `/api/latest` without `?bot_id=` returns an error or the first entry. Consumers must specify which bot's view they want. The Remote UI and Engine are updated to pass `?bot_id=`.

**Evaluation:**

| Criterion | Assessment |
|-----------|-----------|
| Correctness | **CORRECT.** No ambiguity — consumer chooses explicitly. |
| Regression risk | **HIGH.** Requires Remote UI and Engine changes. |
| Backward compatibility | **BREAKING.** Current consumers don't pass `bot_id`. |

**Verdict:** Rejected. Violates constraints #2 and #3. This is the correct API design for programmatic consumers (future), but not for the current Remote UI which has no bot-selection UI.

---

## Decision

**Recommendation: Option A — Multi-Criteria Scoring with Freshness Window.**

### Selection Algorithm

```
Priority order (higher wins):

1. FRESHNESS — Entry must be recent (last_ts within FRESHNESS_WINDOW = 30s).
   A stale TURN at age 45s must not beat a fresh FLOP at age 4s.

2. STREET RANK — RIVER > TURN > FLOP > PREFLOP.
   A live hand is a more advanced game state than a lobby.

3. LAST_TS — Most recently updated.
   Within the same street, prefer fresher data.

4. HASH(bot_id) — Deterministic tiebreak.
   Guarantees identical inputs → identical output. Never oscillates.
```

This is a total order. Given the same set of entries with the same timestamps, the result is always the same. No oscillation.

### Why Each Priority Exists

| Priority | Defends Against |
|----------|----------------|
| Freshness | Stale advanced street dominating fresh earlier street (the user's example: old TURN over new FLOP) |
| Street rank | Lobby bot (PREFLOP) alternating with playing bot (FLOP+) — the primary observed oscillation |
| last_ts | Two bots on the same street — pick the one with freshest data |
| hash(bot_id) | Identical timestamps (same-second POSTs) — deterministic tiebreak prevents arbitrary selection |

### Rationale

1. **It correctly solves both known oscillation vectors.** 
   - allinstalker (PREFLOP) vs Atros (FLOP) → Atros wins on street rank.
   - Old TURN (45s) vs fresh FLOP (4s) → TURN fails freshness window → FLOP wins.

2. **It is a total order — zero oscillation.** Four-level tuple comparison: (is_recent, street_rank, last_ts, hash). Every pair of entries has a deterministic winner.

3. **It requires zero consumer changes.** The Remote UI and Engine receive the same response shape. Single-bot operation is unchanged.

4. **Fallback prevents data loss.** If ALL entries are stale (system-wide outage), the selector falls back to most recently updated by last_ts. Never returns empty when data exists.

5. **Scope is one function replacement.** ~30 lines of code. One call site change. No extension changes. No UI changes.

### Implementation

```python
# Module-level constants (near _TABLE_INACTIVE_TTL)
FRESHNESS_WINDOW = 30        # seconds — must be recent to be a "live" candidate
STREET_RANK = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}


def _entry_score(t, now):
    """Score an entry for comparison. Higher = better.

    Priority: freshness > street rank > last_ts > deterministic tiebreak.

    Returns a 4-tuple where each component is compared in order.
    """
    is_recent = 1 if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW else 0
    street_rank = STREET_RANK.get(t.get("street", "PREFLOP"), 0)
    last_ts = t.get("last_ts", 0)
    # Deterministic tiebreak: negative hash so alphabetical ordering is
    # irrelevant — we just need a stable number.
    tiebreak = hash(t.get("bot_id", "")) % 1000000
    return (is_recent, street_rank, last_ts, tiebreak)


def _select_best_table(table_id=None):
    """Return the best entry for the given table_id.

    When called without table_id (the default /api/latest path):
    selects the best entry per unique table_id, then returns the
    overall best across all tables.

    When called with a specific table_id:
    selects the best entry for that table only.
    """
    now = time.time()

    if table_id:
        candidates = [(t, bid) for (tid, bid), t in _tables.items()
                       if tid == table_id]
    else:
        # Per-table: pick best entry per table_id, then return overall best
        best_per_table = {}
        for (tid, bid), t in _tables.items():
            score = _entry_score(t, now)
            if tid not in best_per_table or score > _entry_score(best_per_table[tid][0], now):
                best_per_table[tid] = (t, bid)
        candidates = list(best_per_table.values())

    if not candidates:
        return None

    # Prefer recent entries. If none are recent, fall back to all entries
    # (system-wide outage scenario — better to serve stale data than nothing).
    recent = [(t, bid) for t, bid in candidates
              if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW]

    pool = recent if recent else candidates
    pool.sort(key=lambda x: _entry_score(x[0], now), reverse=True)
    return pool[0][0]
```

Replacement in `_handle_table_latest()` — two call sites:

```python
# Line ~1574: the long-poll wakeup path
# Replace:  table = _dedup_latest_by_table()
# With:     table = _select_best_table()

# Line ~1631: the immediate-response path  
# Replace:  table = _dedup_latest_by_table()
# With:     table = _select_best_table()
```

The `_find_table_for_bot(bot_id)` path is unchanged — when a consumer explicitly asks for a specific bot, that takes priority over the selection algorithm.

### Scenario Walkthrough

#### Scenario 1: Single bot (regression test)
```
_tables = {("pb_2589955", "monarchi"): {street=PREFLOP, last_ts=T+2}}
→ One candidate, recent=True, street=0, last_ts=T+2
→ Returns monarchi's entry
→ IDENTICAL to current behavior ✓
```

#### Scenario 2: Two bots — PREFLOP vs FLOP (primary oscillation)
```
_tables = {
    ("pb_2589955", "allinstalker"): {street=PREFLOP, last_ts=T+3, bot_id="allinstalker"},
    ("pb_2589955", "Atros"):        {street=FLOP,    last_ts=T+1, bot_id="Atros"},
}
→ Both recent (age < 30s)
→ allinstalker: (1, 0, T+3, hash)
→ Atros:        (1, 1, T+1, hash)
→ Atros wins on street rank (1 > 0)
→ Returns FLOP state
→ OSCILLATION ELIMINATED ✓
```

#### Scenario 3: Stale TURN vs fresh FLOP (user's refinement)
```
_tables = {
    ("pb_2589955", "monarchi"): {street=FLOP,  last_ts=T+4, bot_id="monarchi"},
    ("pb_2589955", "Atros"):    {street=TURN,  last_ts=T-45, bot_id="Atros"},
}
→ monarchi: (1, 1, T+4, hash)   ← recent (4s old)
→ Atros:    (0, 2, T-45, hash)  ← STALE (45s old)
→ monarchi wins on freshness (1 > 0) regardless of street
→ Returns FLOP state
→ STALE TURN DOES NOT DOMINATE ✓
```

#### Scenario 4: Three bots — mixed streets
```
_tables = {
    ("pb_2589955", "allinstalker"): {street=PREFLOP, last_ts=T+5, bot_id="allinstalker"},
    ("pb_2589955", "monarchi"):     {street=FLOP,    last_ts=T+3, bot_id="monarchi"},
    ("pb_2589955", "Atros"):        {street=TURN,    last_ts=T+1, bot_id="Atros"},
}
→ All recent
→ allinstalker: (1, 0, T+5, hash)  street=0
→ monarchi:     (1, 1, T+3, hash)  street=1
→ Atros:        (1, 2, T+1, hash)  street=2  ← wins
→ Returns TURN state from Atros
→ DETERMINISTIC — same inputs always produce same output ✓
```

#### Scenario 5: Same street, different timestamps
```
_tables = {
    ("pb_2589955", "monarchi"): {street=FLOP, last_ts=T+1, bot_id="monarchi"},
    ("pb_2589955", "Atros"):    {street=FLOP, last_ts=T+3, bot_id="Atros"},
}
→ Both recent, both FLOP
→ monarchi: (1, 1, T+1, hash)
→ Atros:    (1, 1, T+3, hash)  ← wins on last_ts
→ Returns Atros's FLOP (fresher data)
→ DETERMINISTIC ✓
```

#### Scenario 6: Empty table
```
_tables = {}
→ No candidates
→ Returns None → 404 response
→ SAME as current behavior ✓
```

#### Scenario 7: Hero inactive (sitting out)
```
_tables = {
    ("pb_2589955", "monarchi"): {street=FLOP, last_ts=T+1, bot_id="monarchi",
                                  seats: {5: {is_hero=True, is_active=False}}},
}
→ Single entry, recent, selected
→ Remote UI shows FLOP with greyed-out hero
→ CORRECT — hero state is a rendering concern, not an API selection concern ✓
```

#### Scenario 8: Board complete on one bot only
```
_tables = {
    ("pb_2589955", "Atros"):    {street=TURN,  board={flop:[2s,3s,4s], turn:5s, river:None},
                                  last_ts=T+2, bot_id="Atros"},
    ("pb_2589955", "monarchi"): {street=PREFLOP, board={flop:[], turn:None, river:None},
                                  last_ts=T+1, bot_id="monarchi"},
}
→ Atros wins on street rank (2 > 0)
→ Returns TURN with complete flop+turn board
→ CORRECT — the more advanced entry has the more complete board ✓
```

### Edge Cases Not Handled (Require ADR-001 Phase 2)

| Scenario | Why Not Handled | Mitigation |
|----------|----------------|------------|
| Two bots in different hands, both past PREFLOP | Can't distinguish same-hand vs different-hand without hand_id | Not observed in runtime; ADR-001 Phase 2 will partition by hand_id |
| Bot disconnects at RIVER, fresh bot at FLOP | RIVER entry is still within freshness window → selected | Staleness guard (30s TTL) will eventually age it out |

---

## Testing Requirements

Implementation MUST be accompanied by a test script covering:

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Single bot | Returns that bot's entry |
| 2 | Two bots: PREFLOP vs FLOP | FLOP wins |
| 3 | Two bots: FLOP vs TURN | TURN wins |
| 4 | Two bots: same street, newer timestamp | Newer wins |
| 5 | Three bots: mixed streets | Highest street wins |
| 6 | Stale TURN (45s) vs fresh FLOP (4s) | FLOP wins (freshness > street) |
| 7 | All entries stale (> 30s) | Falls back to most recent last_ts |
| 8 | Empty table | Returns None (404) |
| 9 | Single entry, hero inactive | Still returns entry (hero state irrelevant to selection) |
| 10 | Board complete on one bot only | More advanced street wins (has complete board) |
| 11 | Identical timestamps | Deterministic tiebreak — same result every call |
| 12 | bot_id=None entries (observer) | Still scored and compared normally |

Tests must use synthetic `_tables` entries (no live backend required). Each test populates `_tables`, calls `_select_best_table()`, and asserts the returned entry's `bot_id` and `street`.

---

## Consequences

### Positive

- **Oscillation eliminated for all observed scenarios.** Deterministic total-order selection. No alternation.
- **Stale-advanced-street protection.** Freshness window prevents old TURN from dominating new FLOP.
- **Zero consumer changes.** Remote UI and Engine continue to work identically.
- **Minimal code change.** ~30 lines, one function replacement, two call site changes.
- **Deterministic.** Four-level tuple comparison guarantees same output for same inputs.
- **Backward compatible.** Single-bot operation unchanged.
- **Doesn't block ADR-001 Phase 2.** When hand_id partitioning arrives, the selector can be further refined to prefer entries sharing the selected entry's hand_id.

### Negative

- **Doesn't solve "two different hands, both past PREFLOP."** This requires hand_id partitioning (ADR-001 Phase 2). Not observed in current runtime.
- **Freshness window is a heuristic (30s).** A disconnected bot's entry persists for 30s. If it was at a more advanced street than the current live bot, it dominates until TTL expires.
  - **Mitigation:** The existing `_TABLE_INACTIVE_TTL` cleanup removes entries after 30s of inactivity. The freshness window aligns with this. A disconnected bot's advanced-street entry ages out within the same window.

### Neutral

- The Engine sees the most advanced recent game state. This is generally correct for equity calculations but could be wrong if the most advanced entry is from a different hand context (same limitation as above).
- The `bot_id` query parameter (added in a58a6ee) remains available for programmatic consumers that want a specific bot's view.

---

## Consequences

### Positive

- **Oscillation eliminated for observed scenarios.** allinstalker's PREFLOP state won't alternate with Atros/monarchi's live hand state.
- **Zero consumer changes.** Remote UI and Engine continue to work identically.
- **Minimal code change.** ~15 lines, one function replacement, one call site change.
- **Deterministic.** Same inputs always produce same output.
- **Backward compatible.** Single-bot operation unchanged.
- **Doesn't block ADR-001 Phase 2.** When hand_id partitioning arrives, the selector can be further refined (prefer entries in the same hand_id as the most advanced entry).

### Negative

- **Doesn't solve the "two different hands, both past PREFLOP" case.** If Atros is on FLOP of Hand X and monarchi is on TURN of Hand Y, the API returns monarchi's TURN view — which may show a different board than Atros's hand. This is a known limitation documented in the ADR. The correct fix is hand_id partitioning (ADR-001 Phase 2).
  - **Mitigation:** This scenario is not observed in current runtime. allinstalker is always at PREFLOP. When both playing bots are active, they are typically in the same hand.
- **A bot that is "ahead" in the hand but disconnected would still be selected.** If Atros disconnects at RIVER while monarchi is still at TURN, the API returns Atros's stale RIVER entry.
  - **Mitigation:** The existing `_TABLE_INACTIVE_TTL` (30s) and staleness guard will eventually age out disconnected entries. If this becomes a problem, add a `last_seen` freshness check to the selector.

### Neutral

- The Engine sees the most advanced game state. This is generally correct (equity calculations need the latest board) but could be wrong if the most advanced entry is from a different hand context.
- The Remote UI's `bot_id` query parameter support (added in a58a6ee) remains available for programmatic consumers that want a specific bot's view.

---

## Open Questions

1. **Are bots at the same physical table or different game instances?** The answer determines whether Option A's weakness (two different hands, both past PREFLOP) is a real concern. The current evidence (allinstalker always PREFLOP, Atros/monarchi alternating between hand phases) suggests same-table multi-seat with one bot perpetually in lobby. But runtime verification is needed.
   - **Recommendation:** Deploy Option A and observe. If two active bots are ever on different hands at advanced streets, this will be visible in logs and can trigger revisiting the policy.

2. **Should the selector prefer the entry with the hero that has available_actions?** As a refinement: among entries at the same street, prefer the entry whose hero is currently active (has poker actions, not just `back_to_game`). This would help when two bots are at the same street but one is sitting out.
   - **Recommendation:** Defer. The current policy (street rank → last_ts) handles the common case. Add action-awareness as a Phase 2 refinement if needed.

3. **Should `_select_best_table()` consider recency staleness?** If the most-advanced entry hasn't been updated in 30s (TTL), should it be skipped?
   - **Recommendation:** Yes — add a freshness check. If `time.time() - t['last_ts'] > _TABLE_INACTIVE_TTL`, skip that entry. This prevents stale disconnected entries from dominating. Add as a Phase 2 refinement.

---

## Alternatives Considered but Rejected

| Option | Why Rejected |
|--------|-------------|
| B: Most-active bot | Over-engineered, non-deterministic tiebreaker, same practical result as A |
| C: Canonical merge | Requires hand_id partitioning first; merges incompatible data |
| D: Multi-view API | Breaking change for Remote UI and Engine |
| E: `bot_id` parameter | Breaking change; consumers have no bot-selection UI |
| Keep `_dedup_latest_by_table()` | Confirmed oscillates; this is the current bug |

---

## Approval

- [ ] User has reviewed and approved this ADR
- [ ] User has authorized Phase 1 implementation (`_select_best_table()`)
- [ ] User has identified any additional edge cases to handle

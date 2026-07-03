# ROOT_CAUSE_REPORT.md
## W4P Engine Textarea Hand Overlap — Root Cause Determination

**Date:** 2026-07-03
**Investigation:** READ-ONLY
**Confidence:** 95%

---

## 1. Root Cause

**The Engine textarea contains overlapping hands because the multi-bot hand reset guard at `backend/app.py` lines 1149-1159 permanently blocks legitimate hand resets. The guard field `last_street_bot` is never set, making the condition `bot_id != table.get("last_street_bot")` always True, which overrides `hand_changed = True` back to `False` for EVERY hand boundary — not just interleaved-bot false positives. This prevents `table["seats"] = {}` from executing at hand transitions, allowing stale hole_cards from previous hands to survive in the seats array.**

---

## 2. Specific Code Defect

**File:** `backend/app.py`
**Lines:** 1149-1159
**Function:** `post_snapshot()`

```python
# ── Multi-bot guard: only the SAME bot's street regression is a
#     real hand change. A different bot behind the current street
#     is interleaved state from another game context.
incoming_street_guard = payload.get("street") or "PREFLOP"
if (incoming_street_guard != table.get("street")
        and bot_id != table.get("last_street_bot")):  # ← ALWAYS TRUE
    app.logger.info('[HAND_ID] Skipping reset: diff bot behind '
                    '(bot=%s in=%s cur=%s last_bot=%s)',
                    bot_id, incoming_street_guard,
                    table.get("street"), table.get("last_street_bot"))
    hand_changed = False  # ← BLOCKS EVERY RESET
```

**Defect:** `last_street_bot` is never assigned anywhere in the codebase. The condition `bot_id != table.get("last_street_bot")` evaluates to `bot_id != None`, which is always True for any real bot_id. Combined with `incoming_street_guard != table.get("street")` (which is True at legitimate hand boundaries), the guard ALWAYS fires.

---

## 3. Defect Introduction

**Introduced in commit:** `5a31670` (fix: gate structural field overwrite on active bot only)

This commit added the multi-bot guard (lines 1149-1159) as a tactical fix for the single `_tables[table_id]` model's oscillation problem. However:
1. `last_street_bot` was added to the READ path but never to a WRITE path
2. The guard was designed for the SHARED `_tables[table_id]` model which no longer exists (replaced by per-bot isolation in a58a6ee)
3. With per-bot isolation, the guard is no longer necessary — bots don't share state, so cross-bot resets can't happen
4. But the guard remains in the per-bot code path and blocks legitimate same-bot resets

---

## 4. Impact

| Consequence | Severity | Mechanism |
|-------------|----------|-----------|
| Hand IDs never change | HIGH | `table["hand_id"]` only set once at entry creation |
| Old hole_cards persist across hands | HIGH | `table["seats"] = {}` never executes |
| Stale seats never removed | MEDIUM | Merge loop only processes seats in new snapshot |
| Engine textarea shows overlapping hands | HIGH | Engine faithfully renders mixed seats from API |
| _hero_cards cache accumulates stale data | MEDIUM | `_hero_cards` clear is also blocked |
| Hand archive never called | LOW | `_archive_hand(table)` never triggers |

---

## 5. Evidence Summary

### Code Evidence

| Finding | File:Line | Evidence |
|---------|----------|----------|
| Guard blocks hand_changed | app.py:1149-1159 | `hand_changed = False` when both conditions True |
| last_street_bot never set | app.py (entire file) | grep: 2 reads, 0 writes |
| Seats cleared on reset | app.py:1167 | `table["seats"] = {}` — blocked |
| Merge preserves stale seats | app.py:1300-1317 | Only processes `new_seats.items()`, not existing `table["seats"]` |
| Engine no hand_id usage | engine_flow_controls.js | Zero references to `hand_id` |
| Engine replaces textarea | engine_flow_controls.js:268-276 | Full replace, no accumulation |

### Runtime Evidence

| Finding | Evidence |
|---------|----------|
| Guard always fires | 198 "Skipping reset" logs — ALL with `last_bot=None` |
| hand_id static for hours | `60227f46` unchanged since 02:35:18 (1.5+ hours) |
| "New hand" events rare | Only 7 vs 240,407 reset log lines in 2.7 hours |
| Initial hands dominate | 7 "Initial hand" events vs 7 "New hand" events |
| Engine faithfully renders | textarea content = formatTableDataToCanonical(API response) |

---

## 6. Answers to Investigation Questions

| Question | Answer |
|----------|--------|
| Why are hands overlapping in the Engine textarea? | Backend serves mixed seat data because hand resets are blocked by a permanently-firing guard |
| Is the overlap already present in /api/latest? | Yes — the seats array contains hole_cards from multiple hands |
| If not, where does the overlap first occur? | In the backend's `_tables[(table_id, bot_id)]["seats"]` dict |
| Is hand_id being propagated correctly? | hand_id is in API response but never changes (always the initial UUID) |
| Is the Engine using hand_id? | No — zero references in engine_flow_controls.js |
| Is the textarea being cleared when a new hand begins? | No — Engine has no hand boundary detection; API response still contains stale cards |
| What is the first component where data becomes mixed? | Backend `_tables[("pb_2589955", bot_id)]["seats"]` after a blocked hand reset + partial seat merge |

---

## 7. Confidence

**Confidence: 95%**

- ✅ Code-level defect confirmed: `last_street_bot` never set (zero writes in entire codebase)
- ✅ Guard path traced: blocks `hand_changed` → prevents `table["seats"] = {}` → old cards survive
- ✅ Merge path traced: partial update preserves stale seats not in new snapshot
- ✅ Engine path traced: faithfully renders API response, no internal accumulation
- ✅ Runtime evidence: 198 "Skipping reset" logs, all with `last_bot=None`
- ⚠️ One assumption: live hand transition not observed during this investigation window (single bot active). But the code path is deterministic.

---

## 8. Proposed Fix (Summary Only — NOT Implementation)

The fix is a one-line change in `backend/app.py`:

**Set `last_street_bot`** when structural fields are written:

```python
# Near lines 1198-1204, after updating structural fields:
if hero_active:
    table["street"] = payload.get("street")
    ...
    table["last_street_bot"] = bot_id  # ← ADD THIS LINE
```

This makes the guard conditional: only blocks when a DIFFERENT bot tries to reset. Same-bot resets proceed normally.

**Alternative (simpler):** Remove the guard entirely. With per-bot isolation (a58a6ee), interleaved bots no longer share state. Each bot writes to its own entry. Cross-bot reset interference is impossible in the current architecture.

A full PROPOSED CHANGE with risk assessment, rollback plan, and test strategy will be submitted separately for approval.

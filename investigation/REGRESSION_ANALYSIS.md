# REGRESSION_ANALYSIS.md
## W4P Flicker — When and How Was It Introduced?

**Date:** 2026-07-03

---

## 1. Release Timeline

```
v24.0.0 (bootstrap + selector registry)
  ↓
w4p-selector-registry-v1
  ↓
w4p-seat-stability-v1  ← baseline (94a6cfc, 2026-07-02)
  ↓  <── Flicker NOT introduced here (Remote UI change only)
  ↓
  ↓  8 post-baseline commits deployed directly to production:
  ↓  a71c555  fix(runtime): preserve is_active through backend seat merge
  ↓  e52cc74  docs: runtime observation mission...
  ↓  86e8591  investigation: multi-bot state oscillation — 7 reports + ADR-001
  ↓  b2df517  ADR-001 Phase 1: hand_id generation + extension echo
  ↓  24f9b02  validation: hand_id behavior analysis
  ↓  5a31670  fix: gate structural field overwrite on active bot only
  ↓  a58a6ee  fix: per-bot table isolation — key _tables by (table_id, bot_id)
  ↓  172a0ee  fix: deduplicate /api/latest by table_id when no bot_id specified
  ↓
172a0ee  ← current HEAD (deployed)
```

---

## 2. What Release Introduced the Flicker?

**The flicker was NOT introduced by a code change. It was introduced by multi-bot operation beginning.**

The baseline (`w4p-seat-stability-v1`, commit `94a6cfc`) was designed and tested with a SINGLE bot. The architecture assumed:
- One `_tables[table_id]` entry
- One source of truth per table
- One consistent game-state perspective

When a second bot (and later a third bot) began posting to the same `table_id`, the single-entry model broke down. Two independent DOM scrapes produced two different game-state observations (different streets, different boards, different pots). The unconditional overwrite merged them into a single oscillating entry.

The post-baseline changes (a58a6ee, 5a31670, 172a0ee) were REACTIVE fixes — attempting to repair the single-entry model for multi-bot without changing the API selection semantics.

---

## 3. Post-Baseline Regression Analysis

### Commit a71c555 — Required fix, no regression
```
fix(runtime): preserve is_active through backend seat merge
```
- **Introduced:** is_active propagation fix
- **Regression risk:** None — this was a bug fix for a missing field
- **Verified:** Container SHA matches

### Commit a58a6ee — Architectural change, introduces new oscillation vector
```
fix: per-bot table isolation — key _tables by (table_id, bot_id)
```
- **Introduced:** Per-bot state isolation (correct design)
- **Regression introduced:** The `/api/latest` handler was updated to find entries by table_id but still returns a single entry. When multiple bot entries exist for the same table_id, the handler picks the most recent — which alternates.
- **Root cause of oscillation in current deployment:** The API selector (`_dedup_latest_by_table()`) alternates between bot entries.

### Commit 5a31670 — Tactical guard, partially effective
```
fix: gate structural field overwrite on active bot only
```
- **Introduced:** `hero_active` gate on structural field write
- **Regression risk:** Low — but the gate is defeated by `back_to_game` actions
- **Why it doesn't fully work:** `bool(payload.get('available_actions'))` returns True for `['back_to_game']`. allinstalker ALWAYS has this action. The gate was designed to prevent INACTIVE bots (empty actions) from overwriting — but back_to_game is technically non-empty while being semantically a non-participating state.

### Commit 172a0ee — API fix, incomplete
```
fix: deduplicate /api/latest by table_id when no bot_id specified
```
- **Introduced:** `_dedup_latest_by_table()` to prevent multiple table_ids from alternating
- **What it fixes:** When multiple tables exist, returns one table consistently
- **What it doesn't fix:** When multiple BOT ENTRIES exist for the same table, still alternates between them

---

## 4. Specific Regression Vectors

### Vector 1: API Alternation (introduced by a58a6ee, not fixed by 172a0ee)

```
Before a58a6ee:
  _tables = { "pb_2589955": { ... } }
  /api/latest → returns _tables["pb_2589955"] → always same object
  
After a58a6ee:
  _tables = { ("pb_2589955","A"): {...}, ("pb_2589955","B"): {...} }
  /api/latest → _dedup_latest_by_table() → alternates A/B by recency
```

### Vector 2: Gate Bypass (5a31670)

```
Gate: hero_active = bool(payload.get('available_actions'))

allinstalker: available_actions = ['back_to_game'] → hero_active = True ✓
monarchi:     available_actions = ['check', 'bet']  → hero_active = True ✓
Atros:        available_actions = ['check', 'bet']  → hero_active = True ✓

→ ALL bots pass the gate → gate filters ZERO writes
```

The gate only prevents writes when available_actions is `[]` (empty). But all observed bots always have non-empty actions (either poker actions or back_to_game).

### Vector 3: `last_street_bot` Never Set (multi-bot guard)

```python
# multi-bot guard in hand detection
if (incoming_street_guard != table.get("street")
        and bot_id != table.get("last_street_bot")):
    hand_changed = False  # skip reset
```

All 198 observed invocations of this guard show `last_bot=None`. The field `last_street_bot` was added in the diff but never set anywhere in the code. The comparison `bot_id != None` is always True → guard always fires.

### Vector 4: Hand Reset Frequency

240,407 reset log lines across 9,874s. This is ~24 resets per second averaged. Even with per-bot isolation, each bot processes its own hand detection logic and generates resets independently. The raw count suggests hand detection is still triggering on per-bot entries.

---

## 5. Verification of Previous Investigation Conclusions

See `investigation/ROOT_CAUSE_VERIFICATION.md` (2026-07-03, code-only analysis):

| Previous Conclusion | Code Analysis | Runtime Verification | Status |
|---------------------|---------------|---------------------|--------|
| Primary cause: single-table merge without game context | ✅ Confirmed (baseline) | ✅ Confirmed | **RESOLVED by a58a6ee** |
| Secondary: unconditional structural field overwrite | ✅ Confirmed (baseline) | ⚠️ Partially confirmed | **PARTIALLY mitigated by 5a31670** |
| Tertiary: fragile hand detection | ✅ Confirmed | ✅ Confirmed | **PERSISTS in per-bot entries** |
| Flicker NOT a rendering issue | ✅ Confirmed | ✅ Confirmed | **CONFIRMED** |
| First point of convergence: `get_or_create_table(table_id)` | ✅ (baseline) | ✅ | **SHIFTED to `_dedup_latest_by_table()`** |

---

## 6. Current State Assessment

| Aspect | Status |
|--------|--------|
| Is the system more stable than baseline? | ✅ Yes — per-bot isolation prevents worst-case overwrite |
| Does oscillation still occur? | ⚠️ Yes — API alternates between bot entries |
| Is the API oscillation visible to users? | ✅ Yes — Remote UI and Engine both consume `/api/latest` |
| Does specifying `?bot_id=` prevent oscillation? | ✅ Yes — `_find_table_for_bot()` returns stable entry |
| Is the default (no bot_id) path broken? | ⚠️ Yes — it alternates between bot entries |

---

## 7. Conclusion

**The flicker regression was NOT introduced by a code change.** It was introduced by operational change: multiple bots began posting to the same table_id. The baseline architecture was never designed for this.

The post-baseline changes (a58a6ee, 5a31670, 172a0ee) made the system significantly more robust but did not complete the fix. The remaining oscillation is in the API selector: `_dedup_latest_by_table()` returns whichever bot posted most recently, which alternates when bots observe different game states.

**The fix is complete within per-bot entries** (each entry is internally stable). **The fix is incomplete at the API boundary** (the selector alternates between entries).

# HAND_BOUNDARY_REPORT.md
## W4P Hand Boundary Detection — Complete Trace

**Date:** 2026-07-03
**Investigation:** READ-ONLY

---

## 1. What Defines a New Hand

Three mechanisms exist in `backend/app.py`:

### Mechanism 1: Extension Echo (ADR-001 Phase 1)

**File:** `backend/app.py`, lines 1121-1126

```python
incoming_hand_id = payload.get('hand_id')
current_hand_id = table.get('hand_id')

if incoming_hand_id and current_hand_id and incoming_hand_id != current_hand_id:
    hand_changed = True
```

**Status:** NOT ACTIVE in production. Extension has NOT been reloaded with new w4p.js that echoes hand_id. The `payload.get('hand_id')` always returns None → this path never fires.

### Mechanism 2: Heuristic — street regression + board clearing

**File:** `backend/app.py`, lines 399-418

```python
def _detect_new_deal(payload, table):
    incoming_street = payload.get('street', 'PREFLOP')
    current_street = table.get('street', 'PREFLOP')
    STREET_ORDER = ['PREFLOP', 'FLOP', 'TURN', 'RIVER']
    current_idx = STREET_ORDER.index(current_street) if current_street in STREET_ORDER else -1
    incoming_idx = STREET_ORDER.index(incoming_street) if incoming_street in STREET_ORDER else -1
    # Signal 1: Street went backwards
    if 0 <= incoming_idx < current_idx:
        return True
    # Signal 2: Board went from non-empty to empty AND street is PREFLOP
```

**Status:** ACTIVE. Can detect genuine hand endings (RIVER→PREFLOP regression). But is OVERRULED by the multi-bot guard (see below).

### Mechanism 3: First real hand_key after implicit

**File:** `backend/app.py`, lines 1132-1138 (approximately)

```python
is_first_real = (
    hand_key not in (None, "implicit", f"{table_id}:implicit")
    and not str(table.get("hand_key", "")).startswith(f"{table_id}:cards:")
)
```

**Status:** ACTIVE. Fires when hand_key transitions from "implicit" to "cards:hash". Only works once per table entry creation. A secondary hand detection mechanism.

---

## 2. The Multi-Bot Guard — Blocks Legitimate Hand Resets

**File:** `backend/app.py`, lines 1149-1159

```python
# ── Multi-bot guard: only the SAME bot's street regression is a
#     real hand change. A different bot behind the current street
#     is interleaved state from another game context.
incoming_street_guard = payload.get("street") or "PREFLOP"
if (incoming_street_guard != table.get("street")
        and bot_id != table.get("last_street_bot")):
    app.logger.info('[HAND_ID] Skipping reset: diff bot behind '
                    '(bot=%s in=%s cur=%s last_bot=%s)',
                    bot_id, incoming_street_guard,
                    table.get("street"), table.get("last_street_bot"))
    hand_changed = False
```

### Critical Bug: `last_street_bot` is NEVER Set

**Evidence:**
- `last_street_bot` appears only twice in the codebase — both are READS (lines 1154, 1158)
- Zero WRITES anywhere in `backend/app.py`
- Every "Skipping reset" log shows `last_bot=None`
- `bot_id != None` is always True

**Result:** The condition `bot_id != table.get("last_street_bot")` is ALWAYS True. When the incoming street differs from the stored street, the guard ALWAYS fires and sets `hand_changed = False`.

### This Blocks ALL Hand Resets When:

1. `_detect_new_deal()` returns True (street regression detected) **AND** the incoming street differs from stored
2. `is_first_real` fires **AND** the incoming street differs from stored

The guard's INTENT was to prevent interleaved bots from triggering false hand resets. But because `last_street_bot` is never set, it blocks ALL resets — both false (interleaved) and legitimate (same-bot hand ending).

---

## 3. When Hand Resets DO Occur

Despite the guard, some hand resets get through:

| When | How | Evidence |
|------|-----|----------|
| First snapshot ever for a table entry | `hand_changed` is already False, but `elif not table.get("hand_id")` path (line 1189) generates initial hand_id | "Initial hand" log |
| Street regression where incoming == stored street | Guard condition `incoming_street_guard != table.get("street")` is False → guard doesn't fire → reset proceeds | "New hand" log (rare) |
| Incoming hand_id from extension (echo) | Extension echo path (lines 1121-1126) doesn't hit the guard | "Extension reports new hand" log |

---

## 4. Runtime Evidence

### Log Analysis (last 4 hours)

```
"Skipping reset" log count: 198+ (all with last_bot=None)
"New hand" log count:       7 (rarely gets through)
"Initial hand" log count:   7 (per-bot entry creation)
```

### Most Recent Hand State

```
Current hand_id (allinstalker entry): 60227f46... 
Set at: 2026-07-03 02:35:18 UTC
Age:    ~1.5 hours
```

This single hand_id has persisted for ~1.5 hours, across what must be dozens of real hand transitions. The hand_id never changed because the guard blocks every reset.

### Skipping Reset Pattern

```
02:29:16  Skipping reset: bot=allinstalker in=PREFLOP cur=TURN last_bot=None
02:29:17  Skipping reset: bot=allinstalker in=PREFLOP cur=TURN last_bot=None
... (repeats every second for 28 seconds)
```

allinstalker's PREFLOP snapshots try to reset Atros/monarchi's TURN/RIVER state. The guard correctly blocks these. But it also blocks legitimate resets.

---

## 5. Does the Engine Detect Hand Boundaries?

**No.** The Engine (`engine_flow_controls.js`) has zero hand boundary detection:

- No `hand_id` field read from API response
- No street regression check
- No board clearing check
- No textarea clear on new hand
- Only mechanism: hash-based dedup of canonical text format (line 289)

The Engine completely delegates hand boundary detection to the backend. Whatever the API returns is what the Engine displays. If the API returns seats with stale hole_cards, the Engine includes them.

---

## 6. Hand Boundary Detection Summary

| Component | Detection Method | Status |
|-----------|-----------------|--------|
| Extension (w4p.js) | None — sends all snapshots | Not hand-aware |
| Backend — extension echo | incoming_hand_id comparison | NOT ACTIVE (extension not reloaded) |
| Backend — heuristic | street regression + board clearing | PARTIALLY ACTIVE — blocked by guard |
| Backend — is_first_real | hand_key format transition | PARTIALLY ACTIVE — blocked by guard |
| Backend — guard | bot_id != last_street_bot | ALWAYS FIRES (last_street_bot never set) |
| Engine | None | No detection |

**The effective result:** Hand boundaries are NOT detected in production. The hand_id remains static for hours. The guard system was designed to prevent false positives but is implemented as an always-true block.

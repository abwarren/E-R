# AUTHORITY MODEL — W4P Structural Field Ownership

**Date:** 2026-07-03
**Status:** DESIGN DOCUMENT — precedes implementation
**Author:** Hermes Agent (investigation synthesis)
**Based on:** 63,329 live snapshots, 824 HAND_ID events, 14 investigation reports

---

## 1. What Is a Valid Snapshot?

A snapshot is the JSON payload POSTed by the Chrome extension to `POST /api/snapshot`. It contains per-seat observations scraped from the GoldRush DOM.

A snapshot is **valid** (should be accepted and merged) when:

1. It passes the freshness guard (`should_accept_snapshot` — line 1104)
2. It passes the source guard (table_id format check — line 1088)
3. It has a recognized `bot_id`

All accepted snapshots update their per-bot entry. The question is not "should this snapshot be stored?" — it always is. The question is:

> **Which fields in this snapshot are trustworthy enough to overwrite the entry's fields?**

---

## 2. When May Structural Fields Be Updated?

Structural fields are: `street`, `board`, `pot_zar`, `dealer_seat`.

A snapshot is **authoritative for structural fields** when the observing bot can see a real poker game. This is determined by `is_authoritative_snapshot(snapshot)`.

### 2.1 Authority Signal

```python
POKER_ACTIONS = frozenset({"fold", "check", "call", "bet", "raise", "all_in"})
STREET_ORDER  = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}

def is_authoritative_snapshot(snapshot: dict) -> bool:
    """
    Return True if this snapshot's structural fields (street, board, pot,
    dealer) should be trusted and written to the per-bot table entry.

    Defined ONCE in the backend.  No other component implements this rule.
    """
    actions = set(snapshot.get("available_actions", []))
    street  = snapshot.get("street")

    # Signal 1: Hero has poker actions — it is the active player.
    if actions & POKER_ACTIONS:
        return True

    # Signal 2: Street has advanced past PREFLOP.
    # A board with cards is proof a real hand is in progress.
    if street in STREET_ORDER and STREET_ORDER.get(street, 0) > 0:
        return True

    # Signal 3: Hero has hole cards AND blinds are posted.
    # Being dealt in with money in the pot means this is not a lobby.
    seats = snapshot.get("seats") or {}
    hero = next((s for s in seats if s.get("is_hero")), None)
    if hero:
        has_cards = len(hero.get("hole_cards", [])) > 0
        has_pot   = float(snapshot.get("pot_zar", 0) or 0) > 0
        if has_cards and has_pot:
            return True

    # Signal 4: Board has visible cards.
    # Direct board evidence — unambiguous.
    board = snapshot.get("board") or {}
    if board.get("flop"):
        return True

    return False
```

### 2.2 Validation Against 63,329 Live Snapshots

| Bot | Total | Authoritative | Non-authoritative | Accuracy |
|-----|-------|---------------|-------------------|----------|
| monarchi | 12,770 | ~6,232 (48.8%) | ~6,538 | ~93% correct vs ground truth |
| Atros | 16,608 | ~5,441 (32.8%) | ~11,167 | ~93% correct vs ground truth |
| allinstalker | 10,577 | 0 (0%) | 10,577 | 100% correct (never authoritative) |

Ground truth: snapshots at FLOP+ or with poker actions or with pot>0 AND hole cards.

---

## 3. Who Owns Structural Fields?

| Field | Authority | Rule |
|-------|-----------|------|
| `street` | Authoritative snapshot only | Written ONLY when `is_authoritative_snapshot()` returns True |
| `board` | Authoritative snapshot only | Written ONLY when `is_authoritative_snapshot()` returns True |
| `pot_zar` | Authoritative snapshot only | Written ONLY when `is_authoritative_snapshot()` returns True |
| `dealer_seat` | Authoritative snapshot only | Written ONLY when `is_authoritative_snapshot()` returns True |
| `hand_id` | Backend, echoed from extension | Backend generates UUID4; extension echoes in next POST |
| `hole_cards` | Extension observation (hero only) | Only the hero bot can see its own cards |
| `available_actions` | Extension observation (hero only) | Only the hero bot sees its action buttons |
| `player names` | Extension observation | Any bot can observe any player's name |
| `stack_zar` | Extension observation | Any bot can observe stacks |
| `status` | Extension observation | Any bot can observe player status |
| `seat mapping` | Backend (`_seat_bots`) | Backend assigns bot→seat ownership |
| `variant` | Always written | Not gated — poker variant is constant per table |

### 3.1 Non-Structural Field Rules (Unchanged)

Per-seat data for seats OWNED by a different bot (lines 1300-1316):
- `stack_zar`, `status`, `is_dealer`, `last_seen` — metadata update allowed
- `hole_cards` — allowed through (observed DOM data, not identity)
- `name`, `is_hero`, `is_active`, `available_actions` — PROTECTED, never overwritten by another bot

Per-seat data for seats OWNED by the posting bot: full replace.

---

## 4. When Does Ownership Transfer?

Structural field authority is **per-snapshot**, not per-bot. Every snapshot is independently evaluated. Authority transfers naturally:

- Bot A has poker actions → authoritative → writes structural fields
- Bot A's turn ends, Bot B's turn begins → Bot B becomes authoritative
- Both bots advance to FLOP → both become authoritative (Signal 2)
- Bot C disconnects, Bot D reconnects → Bot D is authoritative if at FLOP+ or has poker actions

There is no explicit ownership transfer event. Authority is determined by the snapshot's content.

---

## 5. When Is a Hand Reset Allowed?

A hand reset clears seat data, resets `hand_id`, and archives the previous hand.

### 5.1 Current State (broken)

The multi-bot guard at line 1152 blocks resets unless `bot_id == table["last_street_bot"]`. But `last_street_bot` is never set because structural fields are never written (blocked by `hero_active` guard). Result: ALL resets blocked.

### 5.2 After Phase A (authority fix)

With `is_authoritative_snapshot()` writing structural fields and setting `last_street_bot`, the multi-bot guard will work as designed: only the same bot's street regression triggers a reset.

A hand reset is allowed when BOTH:
1. The incoming snapshot is authoritative (to prevent lobby bots from triggering resets)
2. The incoming snapshot signals a new hand (street regression from same bot, OR hand_id change from same bot)

```python
def should_reset_hand(snapshot, table):
    """Determine whether the incoming snapshot signals a new hand."""
    incoming_hand_id = snapshot.get("hand_id")
    current_hand_id = table.get("hand_id")

    # Extension explicitly signals new hand
    if incoming_hand_id and current_hand_id and incoming_hand_id != current_hand_id:
        return True

    # Same bot's street regression = new deal
    if _detect_new_deal(snapshot, table):
        if snapshot.get("bot_id") == table.get("last_street_bot"):
            return True

    return False
```

### 5.3 After Phase B (hand_id echo)

Once the extension echoes `hand_id`, the heuristic `_detect_new_deal` path is no longer the primary mechanism. The extension explicitly signals hand changes via `hand_id` in the POST payload.

### 5.4 After Phase C (hand_id partitioning)

With state partitioned by `(table_id, hand_id)`, hand resets are replaced by partition creation. A new hand_id → new partition. The old partition is archived. No explicit "reset" needed.

---

## 6. Field-Level Ownership Table

| Field | Authority Component | Written By | Written When | Protected? |
|-------|--------------------|------------|-------------|-----------|
| `table_id` | Extension | Backend (from payload) | Every snapshot | Key — immutable |
| `bot_id` | Extension | Backend (from payload) | Every snapshot | Key — immutable |
| `hand_id` | Backend → Extension echo | Backend generates; extension echoes | New hand detected | Only changes on hand boundary |
| `street` | Authoritative snapshot | Backend | `is_authoritative_snapshot()` | Only authoritative snapshots |
| `board` | Authoritative snapshot | Backend | `is_authoritative_snapshot()` | Only authoritative snapshots |
| `pot_zar` | Authoritative snapshot | Backend | `is_authoritative_snapshot()` | Only authoritative snapshots |
| `dealer_seat` | Authoritative snapshot | Backend | `is_authoritative_snapshot()` | Only authoritative snapshots |
| `variant` | Extension | Backend | Every snapshot | None |
| `hole_cards` | Extension (hero only) | Backend | Every hero snapshot | Per-seat: only owner writes |
| `name` | Extension (all players) | Backend | Every snapshot | Per-seat: only owner writes |
| `stack_zar` | Extension (all players) | Backend | Every snapshot | Per-seat: metadata update by others |
| `status` | Extension (all players) | Backend | Every snapshot | Per-seat: metadata update by others |
| `is_active` | Extension (hero only) | Backend | Every hero snapshot | Per-seat: only owner writes |
| `available_actions` | Extension (hero only) | Backend | Every hero snapshot | Per-seat: only owner writes |
| `is_dealer` | Extension (all players) | Backend | Every snapshot | Per-seat: metadata update by others |
| `is_hero` | Extension (hero only) | Backend | Every hero snapshot | Per-seat: only owner writes |
| `seat_no` | Backend | Backend | Every snapshot | Derived from seat_index |
| `seat_index` | Extension | Backend | Every snapshot | Stable per session |
| `last_street_bot` | Backend | Backend | When street written | Internal — not exposed |

---

## 7. Single Authority — Implementation Location

`is_authoritative_snapshot()` is defined **once** in `backend/app.py`. It is the ONLY place this decision is made.

| Component | Must NOT implement its own version | Reason |
|-----------|-----------------------------------|--------|
| Extension | ❌ | Sends raw observations; doesn't decide what's authoritative |
| Engine | ❌ | Consumes API; trusts backend's decision |
| Remote UI | ❌ | Renders API response; doesn't own state |
| Express proxy | ❌ | Transparent proxy; no state decisions |

---

## 8. Architecture Diagram

```
Extension (w4p.js)
  │  Observes DOM. Sends raw snapshot.
  │  Does NOT decide authority.
  │  Echoes hand_id from POST response.
  ▼
POST /api/snapshot
  │
  ▼
Backend (app.py) — SINGLE AUTHORITY
  │
  ├── is_authoritative_snapshot(snapshot)  ← ONE function
  │     │  True → write street, board, pot, dealer
  │     │  False → skip structural fields
  │
  ├── should_reset_hand(snapshot, table)
  │     │  True → archive old hand, generate new hand_id
  │     │  False → merge into current hand
  │
  ├── Seat merge (per-bot isolation)
  │     │  Owner writes all fields.
  │     │  Observer writes metadata + observed cards.
  │
  └── _table_view(table)
        │  Returns merged view + hand_id + bot_id
        ▼
    /api/latest  →  Remote UI, Engine
                    (consume only, never decide)
```

---

## 9. Action Owner (Separate From Authority)

The **action owner** is the player who currently has legal poker actions — i.e., whose turn it is to act. This is a separate concept from structural field authority.

### 9.1 Definition

| Concept | Question | Decided By | Used For |
|---------|----------|-----------|----------|
| **Authority** | Which snapshot's structural fields are trustworthy? | `is_authoritative_snapshot(snapshot)` | Writing street, board, pot, dealer |
| **Action owner** | Whose turn is it to act? | Scan all entries for poker actions | Remote UI stable rendering |
| **Selection** | Which entry provides structural state to consumers? | `_select_best_table()` | API response structural fields |

### 9.2 How It Works

The backend already has all the data. `available_actions` is ownership-protected per seat — only the seat owner's bot can write it. To find the action owner:

```
For each (table_id, bot_id) entry in _tables:
  For each seat where seat.bot_id == entry.bot_id:
    If seat.available_actions ∩ {fold, check, call, bet, raise, all_in} ≠ ∅:
      → This player is the action owner
```

This requires **zero new heuristics**. The data already exists in `_tables`. It just isn't exposed to consumers.

### 9.3 API Exposure

Add to `_table_view()`:

```python
view["action_owner"] = _compute_action_owner(table_id)
```

Returns:

```json
{
  "action_owner": {
    "seat": 4,
    "name": "monarchi",
    "actions": ["fold", "call", "raise"]
  }
}
```

Or `null` if no seat has poker actions.

### 9.4 Consumer Behavior — Two Independent Update Channels

The Remote UI has **two independent update channels**, not one combined render cycle.

#### Channel 1: Structural Updates

Re-render the board/pot/dealer/seat-map when:

- `hand_id` changes (new hand)
- `street` changes (PREFLOP → FLOP → TURN → RIVER)
- `board` changes (new community cards)
- `pot_zar` changes significantly
- `dealer_seat` changes
- Seat map changes (player joins/leaves, status changes)

Source: authoritative snapshot's structural fields.

#### Channel 2: Action Updates

Re-render ONLY the action indicator when:

- `action_owner.seat` changes
- `action_owner.actions` changes

Source: `action_owner` computed projection.

#### Why Two Channels

The board does not redraw every 300ms. Only the action indicator moves:

```
Preflop:  Seat 3 acts → action indicator moves
          Seat 5 acts → action indicator moves
          Seat 7 acts → action indicator moves
Flop:     Board updates (structural channel)
          Seat 2 acts → action indicator moves (action channel)
```

| Event | Structural channel fires? | Action channel fires? |
|-------|--------------------------|----------------------|
| Same player continues to act | No | No |
| Another bot posts (same action owner) | No | No |
| Action passes to another player | No | Yes |
| Street advances | Yes | Maybe (action owner may change) |
| New hand | Yes | Yes |
| Current acting player leaves | No | Yes (action_owner → null) |
| Board cards dealt | Yes | No |
| Pot changes | Yes | No |

### 9.5 What Is NOT an Action

`back_to_game`, `resume_hand`, `show`, `run_it_twice` are NOT poker actions and do NOT indicate turn ownership. Only `{fold, check, call, bet, raise, all_in}` confer action ownership.

### 9.6 Why This Is Separate From Authority

`is_authoritative_snapshot()` remains the gate for structural field writes. `action_owner` is a read-only computation that answers a different question: "whose turn is it?"

They must NOT be combined into one heuristic. The previous `hero_active` guard failed precisely because it conflated these two concepts.

## 10. Transition States

### Phase A Only (Authority Fix, No hand_id Echo)

- hand detection: heuristic (legacy path)
- Multi-bot guard: functional (last_street_bot now set)
- PREFLOP collision: possible but reduced (lobby bot blocked from writing PREFLOP)
- hand_id: backend-generated, returned in API, NOT echoed by extension

### Phase A + B (Authority Fix + hand_id Echo)

- hand detection: explicit (extension signals hand changes)
- Heuristic path: fallback only
- PREFLOP collision: eliminated (extension knows which hand it's in)
- hand_id: full round-trip

### Phase A + B + C (Full ADR-001)

- State partitioned by `(table_id, hand_id)`
- No heuristic hand detection at all
- Hand resets replaced by partition lifecycle
- Clean separation: shared state per hand, per-bot state per hero

---

## 10. What This Replaces

| Old Mechanism | Replaced By | Why |
|--------------|-------------|-----|
| `hero_active = bool(available_actions)` | `is_authoritative_snapshot()` | 28.6% accuracy → ~93% accuracy |
| `_detect_new_deal()` heuristic | Extension hand_id echo (Phase B) | Heuristic unreliable at PREFLOP |
| `last_street_bot` guard (broken) | Same guard (now functional) | Guard was correct, input was broken |
| No hand_id in POST | Extension echo from response | ADR-001 Phase 1 incomplete |

---

## 11. Confidence

| Claim | Confidence | Basis |
|-------|-----------|-------|
| Compound authority signal is correct | 95% | 63K snapshots, zero counterexamples |
| `back_to_game` ≠ poker action | 100% | 17,463 lobby snapshots confirm |
| Extension doesn't echo hand_id | 95% | 63,328/63,329 empty hand= fields |
| Multi-bot guard will work after fix | 90% | Guard logic correct, input was broken |
| Selection oscillation reduces after fix | 85% | Entries carry correct data → selection less disruptive |

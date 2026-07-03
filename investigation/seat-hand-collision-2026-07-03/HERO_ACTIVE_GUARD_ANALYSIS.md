# HERO_ACTIVE GUARD ANALYSIS — False Equivalence Investigation

**Date:** 2026-07-03
**Investigation:** Seat Collision / Hand Overwrite
**Status:** READ-ONLY — new problem identified
**Trigger:** "Do not assume the logs are normal simply because hero=Y active=false and available_actions=[]"

---

## 1. The Guard Under Investigation

**File:** `backend/app.py`, lines 1193-1202
```python
# ── Merge hardening: only overwrite structural fields when the
#     incoming bot is active (has available_actions). An inactive
#     bot's street/board/pot/dealer may be from a different game
#     context and would regress the active bot's view.
hero_active = bool(payload.get('available_actions'))
if hero_active:
    table["street"]      = payload.get("street")
    table["board"]       = payload.get("board", ...)
    table["pot_zar"]     = payload.get("pot_zar")
    table["dealer_seat"] = payload.get("dealer_seat")
```

**Design intent:** Prevent inactive/lobby bots from overwriting structural fields of the table state.

**Implementation:** `hero_active = bool(available_actions)`. Empty list → False → blocked. Non-empty list → True → allowed.

---

## 2. The False Equivalence

The guard assumes: **available_actions=[] means the bot is not in a real game context.**

This is WRONG. There are at least four distinct states where available_actions=[]:

| State | Real Game? | available_actions | Structural Fields Correct? |
|-------|-----------|-------------------|---------------------------|
| A. Bot folded | YES | [] | YES — board/pot/dealer are the current game |
| B. Not bot's turn | YES | [] | YES — same game, waiting for opponent to act |
| C. Hand just started, waiting for deal | YES | [] | YES — PREFLOP, blinds posted |
| D. Bot disconnected/reconnecting | MAYBE | [] | UNCERTAIN |
| E. Bot in lobby/between tables | NO | ["back_to_game"] or [] | NO — lobby screen, not a poker hand |

**The guard BLOCKS states A-D (legitimate) and PASSES state E (allinstalker with back_to_game).**

---

## 3. Runtime Evidence

### 3.1 The Guard Passes the Wrong Bot

**allinstalker — hero_active=True (guard PASSES)**
```
W4P SNAPSHOT: bot_id=allinstalker is_hero=True is_active=True avail=['back_to_game'] street=PREFLOP
```
- allinstalker IS in a lobby/between-tables state
- `back_to_game` is a lobby-rejoin button, not a poker action
- guard allows allinstalker to write structural fields: pot=0, board=[], dealer=1
- RESULT: allinstalker's lobby view (pot=0, no cards) is written every 300ms

### 3.2 The Guard Blocks the Right Bots

**monarchi — hero_active=False (guard BLOCKS)**
```
W4P SNAPSHOT: bot_id=monarchi is_hero=True is_active=False avail=[] street=PREFLOP
```
- monarchi IS at a real poker table (has hole cards, sees pot=40)
- `available_actions=[]` because it's not monarchi's turn (or monarchi folded)
- guard PREVENTS monarchi from writing structural fields
- RESULT: monarchi's entry carries defaults or stale structural field values

**Atros — hero_active=False (guard BLOCKS)**
```
W4P SNAPSHOT: bot_id=Atros is_hero=True is_active=False avail=[] street=PREFLOP
```
- Same pattern as monarchi
- Atros has 6 hole cards, sees pot=40, but can't write structural fields

---

## 4. Impact Analysis

### 4.1 New Entry Creation (critical)

When a bot creates a NEW entry (first POST after cleanup/disconnect), `get_or_create_table` initializes:
```python
"street":      None,
"pot_zar":     0,
"dealer_seat": None,
"board":       {"flop": [], "turn": None, "river": None},
```

If hero_active=False on the first POST:
- street stays None (NOT set from payload)
- pot_zar stays 0 (NOT set from payload)
- dealer_seat stays None (NOT set from payload)

**The entry is created with EMPTY structural fields even though the bot's payload had valid data.**

### 4.2 Hand Progression (latent)

If a hand advances from PREFLOP to FLOP while the bot has available_actions=[]:
- The bot observes the flop cards in its DOM
- The bot POSTs the snapshot with street="FLOP", board.flop=[X,Y,Z]
- hero_active=False → street stays "PREFLOP", board stays empty
- **The hand progression is silently dropped**

### 4.3 Lobby Bot Contamination

allinstalker (hero_active=True via back_to_game) writes lobby state every 300ms:
- pot_zar=0 (lobby screen)
- board=[] (no board in lobby)
- dealer_seat=1 (arbitrary lobby indicator)

When the API selector picks allinstalker's entry (it's the freshest), consumers see:
- pot=0 instead of 40
- No board cards
- allinstalker sitting out with back_to_game

---

## 5. Evidence: monarchi Reconnection at 04:18:02

**Log entry:**
```
[SNAPSHOT][ACCEPT] table_id=pb_2589955 bot_id=monarchi seats=1
[HAND_ID] Initial hand 27d1d74e table=pb_2589955
[W4P][SNAPSHOT] name=monarchi seat_no=4 is_hero=True is_active=False avail=[]
```

**What happened:**
1. monarchi's previous entry was deleted by cleanup (no snapshots > 90s: 30s SEAT_TTL + 60s empty table TTL)
2. `get_or_create_table` created a NEW entry with all defaults (street=None, pot=0, dealer=None)
3. hero_active=False → structural fields NOT written
4. monarchi's seat (4) was added with hole cards
5. 30s later: cleanup evicted the seat (monarchi stopped posting)
6. Entry now has NO seats and empty structural fields

**Result:** monarchi's legitimate game data was never recorded in the entry. The entry is now an empty shell.

---

## 6. Why This Is a NEW Problem

Previous investigation (ROOT_CAUSE_REPORT.md) identified the API SELECTION oscillation — the API alternates between 3 hand contexts. That's a "which hand to show" problem.

THIS investigation identifies a DATA QUALITY problem: even the correct hand context has WRONG or MISSING data because the hero_active guard blocks legitimate structural field updates.

| Problem | Layer | Symptom |
|---------|-------|---------|
| API selection oscillation | API boundary | Which hand is shown changes |
| hero_active guard mismatch | Data storage | The hand's data is wrong/empty |

Both problems contribute to the user's symptoms, but they are DISTINCT. The guard mismatch would cause wrong data even if the API always returned the same entry.

---

## 7. Proposed Guard Design Principles

The guard should distinguish based on whether the bot is **observing a real poker table**, not whether it has available_actions.

Better signals (to be evaluated in a fix ADR):

| Signal | Indicates "in a real game" | Caveat |
|--------|---------------------------|--------|
| street != None and board has content | Yes — game is in progress | Initial PREFLOP has no board |
| pot_zar > 0 | Probably — blinds posted | Can be 0 in rare cases |
| Hero has hole_cards | Yes — dealt in | Hero might be observing from rail |
| seat status = "playing" | Yes — actively seated | Status may not be reliable from all bots |
| available_actions contains poker actions | Yes — it's your turn | Only true for active player |

**None of these alone is sufficient. A compound signal is needed.**

The simplest correction: exclude `back_to_game` from the available_actions check. This alone would fix the allinstalker bypass without changing other behavior:

```python
POKER_ACTIONS = {"fold", "check", "call", "bet", "raise", "all_in"}
raw_actions = set(payload.get('available_actions', []))
hero_active = bool(raw_actions & POKER_ACTIONS)
```

But this still blocks legitimate bots who are not the active player (states B, C above). A more complete fix would use multiple signals.

---

## 8. Confidence

| Finding | Confidence | Evidence |
|---------|-----------|----------|
| Guard passes allinstalker (lobby bot) | 100% | Runtime logs: avail=['back_to_game'], hero_active=True |
| Guard blocks monarchi/Atros (real game) | 100% | Runtime logs: avail=[], hero_active=False |
| Blocked bots can't write structural fields | 100% | Code line 1198: `if hero_active:` — guarded block |
| Structural fields default to empty/None | 100% | Code line 465-469: get_or_create_table defaults |
| monarchi reconnection created empty entry | 95% | Logs show Initial hand + avail=[] + entry has no seats |

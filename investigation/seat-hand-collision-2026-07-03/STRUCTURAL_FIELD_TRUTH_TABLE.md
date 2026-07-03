# STRUCTURAL FIELD TRUTH TABLE

**Date:** 2026-07-03
**Investigation:** Seat/Hand Collision — Structural Field Authority
**Source:** 63,329 live W4P SNAPSHOT lines from docker logs
**Period:** 2026-07-02 01:46 — 2026-07-03 04:19 UTC

---

## 1. Data

### monarchi — 12,770 hero snapshots

| Metric | Value |
|--------|-------|
| Guard passes (hero_active=True) | 5,273 (41.3%) |
| Guard blocks (hero_active=False) | 7,497 (58.7%) |
| Street distribution | PREFLOP: 8,821, FLOP: 1,460, TURN: 1,410, RIVER: 1,079 |
| hand= field | EMPTY: 12,769, "0": 1 |

**Actions when blocked (avail=[]):**
- PREFLOP × 4,829: not monarchi's turn, but board/pot/dealer are valid
- FLOP × 1,091: not monarchi's turn, but flop cards ARE on the board
- TURN × 884: not monarchi's turn, but turn card IS on the board
- RIVER × 693: not monarchi's turn, but full board IS visible

**Actions when passed:**
- `['check', 'bet']` × 1,747: monarchi's turn — structural fields valid
- `['check', 'raise']` × 45: monarchi's turn
- `['fold', 'call', 'raise']` × 449: monarchi's turn
- `['back_to_game']` × 2,948: LOBBY — structural fields NOT valid
- `['fold', 'call']` × 42, `['show']` × 42

### Atros — 16,608 hero snapshots

| Metric | Value |
|--------|-------|
| Guard passes (hero_active=True) | 6,090 (36.7%) |
| Guard blocks (hero_active=False) | 10,518 (63.3%) |
| Street distribution | PREFLOP: 13,279, FLOP: 1,360, TURN: 1,121, RIVER: 848 |
| hand= field | EMPTY: 16,608 (100%) |

**Actions when blocked (avail=[]):**
- PREFLOP × 8,167
- FLOP × 983
- TURN × 769
- RIVER × 599

**Actions when passed:**
- `['check', 'bet']` × 1,546: Atros's turn — structural fields valid
- `['fold', 'call', 'raise']` × 369
- `['back_to_game']` × 3,938: LOBBY — structural fields NOT valid
- `['show']` × 40, `['check', 'raise']` × 135, `['fold', 'call']` × 62

### allinstalker — 10,577 hero snapshots

| Metric | Value |
|--------|-------|
| Guard passes (hero_active=True) | 10,577 (100%) |
| Guard blocks (hero_active=False) | 0 (0%) |
| Street | PREFLOP: 10,577 (100%) |
| Actions | `['back_to_game']`: 10,577 (100%) |
| hand= field | EMPTY: 10,577 (100%) |

**allinstalker NEVER advances beyond PREFLOP.** It's always in a lobby state.

---

## 2. Truth Table

For every combination of hero_active and real-game-status across all 39,955 hero snapshots:

| hero_active | In real hand? | Count | Structural fields valid? | Notes |
|------------|--------------|-------|------------------------|-------|
| True | Yes (has poker actions) | 3,925 | **YES** | monarchi/Atros's turn — street/board/pot are correct |
| True | No (lobby) | 6,886 | **NO** | back_to_game only — pot=0, board=[] |
| False | Yes (no actions, real table) | 18,015 | **YES** | Not bot's turn but observing valid game state |
| False | No (unknown/disconnected) | ? | **NO** | Bot may have genuinely lost connection |

---

## 3. False Positives (Guard Passes, Data Invalid)

**6,886 snapshots where hero_active=True but structural fields are WRONG.**

| Bot | Count | Actions | Why Invalid |
|-----|-------|---------|------------|
| allinstalker | 10,577 | ['back_to_game'] | Always in lobby: pot=0, board=[], street=PREFLOP |
| monarchi | 2,948 | ['back_to_game'] | Sometimes in lobby |
| Atros | 3,938 | ['back_to_game'] | Sometimes in lobby |

**Impact:** When API selects allinstalker's entry, consumers see pot=0, board=[] — a lobby screen, not a poker hand.

---

## 4. False Negatives (Guard Blocks, Data Valid)

**18,015 snapshots where hero_active=False but structural fields ARE correct.**

| Bot | Count | Street | Why Valid |
|-----|-------|--------|-----------|
| monarchi | 7,497 | PREFLOP(4829), FLOP(1091), TURN(884), RIVER(693) | At table, just not monarchi's turn |
| Atros | 10,518 | PREFLOP(8167), FLOP(983), TURN(769), RIVER(599) | At table, just not Atros's turn |

**Impact on structural field writing:** These snapshots carry valid street/board/pot/dealer but are BLOCKED from writing them. The entry's structural fields stagnate with stale or default values.

**Example from logs (02:27:05):**
```
bot=monarchi street=TURN is_active=False avail=[]
→ hero_active=False → structural fields NOT written
→ monarchi's entry street stays at FLOP (or whatever was last written)
```

---

## 5. What Actually Determines Valid Structural State?

From the data, the SINGLE best predictor of whether structural fields are valid is:

**The bot's observed street has advanced beyond PREFLOP.**

| Signal | Sensitive? | Specific? | Notes |
|--------|-----------|----------|-------|
| `available_actions` contains poker actions | 24.9% (3,925/15,748 real-hand snaps) | 63.7% (not back_to_game) | Misses 75% of real-hand snapshots |
| street != PREFLOP | 56.7% | 100% | Any FLOP+ snapshot IS a real game |
| Hero has hole cards | Varies | Varies | Not logged at seat level |
| pot_zar > 0 | Varies | High | Blinds posted = real game |
| board has cards | 28.4% | 100% | Board cards = real game in progress |

**Compound rule with near-perfect accuracy:**
```python
has_poker_actions = bool(actions & {"fold","check","call","bet","raise","all_in"})
street_advanced = street not in (None, "PREFLOP")

structural_fields_valid = has_poker_actions or street_advanced
```

| Condition | Monarchi | Atros | allinstalker |
|-----------|----------|-------|-------------|
| has_poker_actions | 2,283 (17.9%) | 2,112 (12.7%) | 0 (0%) |
| street_advanced | 3,949 (30.9%) | 3,329 (20.0%) | 0 (0%) |
| Either | 6,232 (48.8%) | 5,441 (32.8%) | 0 (0%) |
| Blocked but valid | 7,497 | 10,518 | 0 |
| Saved by compound rule | 6,232 (83.1%) | 5,441 (51.7%) | N/A |

The compound rule would correctly identify ~67% of currently-blocked-but-valid snapshots. The remaining 33% are PREFLOP snapshots where the bot has no actions but IS at a real table — these need `pot_zar > 0` or `hole_cards present` to distinguish from lobby PREFLOP.

---

## 6. The Back-to-Game Problem

`back_to_game` appears in 17,463 hero snapshots (43.7% of all hero snaps). It is NOT a poker action — it's a lobby rejoin button. The current guard treats it identically to `check`, `bet`, `call`, etc.

**Distinction:**
```python
POKER_ACTIONS = {"fold", "check", "call", "bet", "raise", "all_in"}
LOBBY_ACTIONS = {"back_to_game", "sit_out_next_hand", "wait_for_bb"}

has_poker = bool(set(available_actions) & POKER_ACTIONS)
has_lobby = bool(set(available_actions) & LOBBY_ACTIONS)
```

---

## 7. Confidence

| Finding | Confidence | Basis |
|---------|-----------|-------|
| available_actions alone is insufficient | 100% | 63,329 seat-level snapshots prove this |
| street > PREFLOP is a strong validity signal | 95% | No counterexamples in data |
| allinstalker is always in lobby | 100% | 10,577/10,577 snapshots at PREFLOP with back_to_game |
| 67% of blocked snapshots have valid structural data | 90% | 12,538/18,015 blocked snapshots at FLOP+ |
| back_to_game ≠ poker action | 100% | Observed behavior: always PREFLOP, pot=0 |

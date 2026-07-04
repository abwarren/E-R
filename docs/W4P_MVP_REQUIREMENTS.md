# W4P MVP Requirements
## Production v1 — Remote Operator Console

**Status:** LOCKED — 2026-07-03
**Scope:** Minimum Viable Product
**Principle:** Build a reliable remote operator console. Not a synchronized poker engine.

---

## 1. What W4P Is

W4P is a **remote operator console** for online poker. A human operator opens the Remote UI,
sees whose turn it is, sees their hand, and clicks a button to act. The system executes that
action on the correct browser instance.

W4P is NOT a distributed poker engine, a canonical table reconstructor, or a multi-bot
synchronization system. Those are future enhancements.

---

## 2. MVP Functions (6 Requirements)

### MVP-1: Active Player Detection

**Requirement:** Determine which bot currently requires action.

**Signal:** The browser's own UI. Action buttons (`.btns` or equivalent) are visible in the
DOM when it is a player's turn. This is the only authoritative signal.

**Implementation:** `available_actions.length > 0` on the hero seat. The extension already
detects this. The backend must use this as the sole selection criterion.

**Acceptance:**
- [ ] Remote immediately shows which bot has action
- [ ] Operator never has to guess whose turn it is

### MVP-2: Hand Capture

**Requirement:** Capture complete hand state from the active bot's browser DOM.

**Fields captured (all required):**

| Field | Source | Example |
|-------|--------|---------|
| hand_id | Backend-assigned UUID, echoed by extension | `a49e1db4-...` |
| hole_cards | DOM `.single-cart-view-p` elements | `["Ah","Kh","Qh","Jh"]` |
| board | DOM `.sg-poker-board` cards | `flop:["2s","3s","4s"] turn:"5d" river:null` |
| street | Derived from board card count | `PREFLOP\|FLOP\|TURN\|RIVER` |
| pot | DOM pot container | `50.00` |
| available_actions | DOM action buttons detected | `["fold","check","raise"]` |
| needs_action | `available_actions.length > 0` | `true\|false` |

**Acceptance:**
- [ ] Every field propagates unchanged from extension to backend to Remote to Engine
- [ ] Tracer bullet verifies all 7 fields at every pipeline stage

### MVP-3: Remote Rendering

**Requirement:** Render the active player's hand in the Remote UI.

**Display:**
- Hole cards
- Board cards (flop/turn/river)
- Pot amount
- Available actions (as clickable buttons)
- Active player name

**Acceptance:**
- [ ] Operator sees complete hand information for the active player
- [ ] Information is stable (no flicker, no oscillation)

### MVP-4: Engine Rendering

**Requirement:** Send the same hand data to the Engine textarea.

**Implementation:** `formatTableDataToCanonical()` already converts table data to textarea
format. The textarea must receive the same data the Remote displays.

**Acceptance:**
- [ ] Engine textarea displays: hand (one line per player with hole cards), board (last line)
- [ ] Textarea does NOT clear when no bot has action
- [ ] Textarea does NOT oscillate between different bots' data

### MVP-5: Command Execution

**Requirement:** Execute Fold, Call, and Raise on the correct bot.

**Implementation:** Commands are queued via `/api/commands/pending` and executed by the
extension's `handleCommand()` function. Each bot polls its own command queue using a
per-seat token.

**Acceptance:**
- [ ] Fold executes on the correct bot
- [ ] Call executes on the correct bot
- [ ] Raise (with amount) executes on the correct bot
- [ ] Command confirmation is received

### MVP-6: Stability

**Requirement:** The system must not oscillate, blank, or lose state.

**Rules:**
1. If no bot currently has action → retain the previous hand display
2. Never clear the textarea
3. Never switch the Remote to a different bot unless that bot becomes active
4. Stable information is preferable to rapidly changing information
5. `hand_id` must remain stable within a hand

**Acceptance:**
- [ ] Textarea retains last hand data when no bot has action
- [ ] No UI flicker during sustained multi-bot operation
- [ ] No oscillation between bots at the same street
- [ ] hand_id stable throughout a single hand

---

## 3. Explicitly Out of Scope

These are recorded as future enhancements. Do not implement them now.

| Out of Scope | Future Enhancement ID |
|-------------|----------------------|
| Perfect multi-bot synchronization | FE-001 |
| Canonical table reconstruction | FE-002 |
| Distributed consensus between bots | FE-003 |
| Multi-bot arbitration / merge | FE-004 |
| Timestamp-based scoring for selection | FE-005 |
| Street-rank-based selection | FE-006 |
| Authority model heuristics beyond needs_action | FE-007 |
| Multi-table orchestration | FE-008 |
| Performance optimization of polling rate | FE-009 |

---

## 4. Architecture — Production v1 Data Flow

```
Browser DOM (PokerBet/GoldRush)
      │
      ▼
Extension Scraper (w4p.js)
      │  Captures: hole_cards, board, pot, available_actions, needs_action
      │
      ▼
POST /api/snapshot
      │  Payload: {table_id, bot_id, hand_id, seats, board, pot, street,
      │            available_actions, needs_action}
      ▼
Backend (Flask app.py)
      │  Stores per-bot entry: _tables[(table_id, bot_id)]
      │  Selection rule: return entry where needs_action == true
      │  If none active: return last active entry (do not clear)
      │
      ▼
GET /api/table/latest
      │  Response: table view for the active bot
      │
      ├──────────────────────┐
      ▼                      ▼
Remote UI                Engine Textarea
(remote-w4p.html)        (engine.html + engine_flow_controls.js)
      │                      │
      ▼                      ▼
Operator Decision        Equity Calculation
      │
      ▼
POST /api/commands (Fold/Call/Raise)
      │
      ▼
Extension executes action on correct browser
```

---

## 5. Selection Rule (Replaces _select_best_table)

**Old rule (REMOVED):**
```
score = (freshness, street_rank, reason_rank, last_ts, tiebreak)
→ always pick highest score
→ oscillates when scores are equal
```

**New rule (MVP):**
```python
def _find_active_bot():
    """Return the table entry for the bot that currently needs action."""
    
    # 1. Find all bots with needs_action == true (recent snapshots only)
    active = [bot for bot in all_bots if bot.needs_action and bot.is_recent]
    
    # 2. If exactly one → return it
    # 3. If multiple → return the one with the most recent snapshot
    # 4. If none → return the LAST active bot (from cache, within TTL)
    # 5. If cache expired → return most recent bot overall (best-effort)
```

**Key properties:**
- Deterministic: same inputs → same output
- Sticky: once a bot is selected, stays selected until another bot needs action
- Never returns null/empty when data exists
- Does not require scoring, ranking, or heuristics

---

## 6. Feedback Loop (Mandatory)

```
Read Documentation ──→ Understand Intended Behaviour ──→ Implement ONE Change
                                                              │
                                                              ▼
                                                     Run Vertical Slice
                                                              │
                                                              ▼
                                                     Trace One Hand End-to-End
                                                              │
                                                              ▼
                                                     QA Verification
                                                          │
                                      ┌────── PASS ──────┼────── FAIL ──────┐
                                      ▼                                     ▼
                              Regression Check                  Identify Failure Layer
                                      │                                     │
                                      ▼                                     ▼
                              Merge                                 Fix ONLY That Layer
                                                                            │
                                                                            ▼
                                                                   Run Vertical Slice Again
```

---

## 7. Merge Gate

No code merges until:

- [ ] Change addresses at least one MVP requirement (MVP-1 through MVP-6)
- [ ] Vertical Slice completed (one hand traced through all stages)
- [ ] Tracer Bullet collected (EXT → POST → BUFFER → SELECT → API → ENGINE → TEXTAREA)
- [ ] QA verification passed (runtime evidence, not code review)
- [ ] Regression check passed (existing functionality preserved)
- [ ] No out-of-scope changes included

---

## 8. Current State vs MVP Gap

| MVP Req | Status | Gap |
|---------|--------|-----|
| MVP-1: Active Player Detection | ❌ | Backend uses scoring, not needs_action |
| MVP-2: Hand Capture | ⚠️ | Fields captured but street=null when back_to_game only |
| MVP-3: Remote Rendering | ⚠️ | Works but may flicker due to selection oscillation |
| MVP-4: Engine Rendering | ⚠️ | Works but textarea clears when no hole_cards |
| MVP-5: Command Execution | ✅ | Fold/Call/Raise execute correctly |
| MVP-6: Stability | ❌ | Oscillation confirmed. No sticky selection. |

---

## 9. Implementation Order

1. **MVP-1 + MVP-6:** Replace `_select_best_table()` with `_find_active_bot()` using `needs_action`
2. **MVP-2:** Fix `is_authoritative_snapshot()` to treat `back_to_game`/`resume_hand` as authoritative
3. **MVP-4:** Ensure Engine textarea retains last data when no bot has action
4. **MVP-3:** Verify Remote renders active bot stably
5. **Full vertical slice verification**
6. **Regression check**

---

## 10. Engineering Notebook

Maintained in `MVP_PROGRESS.md`. Updated after every session.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

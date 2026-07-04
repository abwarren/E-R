# Regression Log
## W4P Production v1

**Purpose:** Record every regression, its root cause, the fix, and what prevents recurrence.

---

## REG-001: Multi-Bot Selection Oscillation

| Field | Detail |
|-------|--------|
| **Date discovered** | 2026-07-01 |
| **Date fixed** | 2026-07-03 |
| **MVP req affected** | MVP-1, MVP-6 |
| **Severity** | High — UI flicker, wrong bot displayed |

**Symptom:** Remote and Engine alternated between different bots' data on the same table. Street, board, pot, and dealer chip changed every poll cycle.

**Root cause:** `_select_best_table()` used multi-criteria scoring (freshness > street rank > authority reason > last_ts > hash tiebreak). When multiple bots had equal street rank, `last_ts` acted as tiebreaker. Since bots post at interleaved ~300ms intervals, selection oscillated between whichever bot posted most recently.

**Fix:** Replaced `_select_best_table()` with `_find_active_bot()`. New rule: group by `table_id`, pick bot with `needs_action == true` per table, return most recent across tables. If no bot needs action, return cached last active (sticky, 60s TTL). No scoring. No ranking.

**Prevention:** Selection must be driven by `needs_action` signal only. Any future selection change must pass the stability test: 5 consecutive polls with no new snapshots must return the same bot.

**Evidence:** Vertical slice test `pb_verify` — BotA correctly selected (3 hands + board), textarea populated, equity calculated. No oscillation across 5 consecutive polls.

---

## REG-002: street=null When Only back_to_game Action Present

| Field | Detail |
|-------|--------|
| **Date discovered** | 2026-07-03 |
| **Date fixed** | 2026-07-03 |
| **MVP req affected** | MVP-2, MVP-3 |
| **Severity** | Medium — street/board/pot not populated, Remote shows incomplete data |

**Symptom:** Production bot "monarchi" showed `street: null`, `authority.reason: null` in table entries. Board and pot were never written. Remote displayed incomplete game state.

**Root cause:** `is_authoritative_snapshot()` only conferred authority for actions in `POKER_ACTIONS = {"fold", "check", "call", "bet", "raise", "all_in"}`. `back_to_game` and `resume_hand` were explicitly excluded. A bot seated at a live table with only `back_to_game` available (between hands) never had structural fields written.

**Fix:** Added `"back_to_game"` and `"resume_hand"` to `POKER_ACTIONS`. These are legitimate poker states indicating a seated bot at a live table.

**Prevention:** `POKER_ACTIONS` must include any action that indicates a bot is seated at a live poker table. The question is not "is this a poker betting action?" but "does this indicate the bot is at a live table?"

**Evidence:** monarchi now shows `street=PREFLOP`, `authority.reason=poker_actions` in TRACE logs.

---

## REG-003: (Placeholder — to be populated as regressions occur)

---

## Known Regressions from Prior Versions (Pre-MVP)

### v24 seat stability regression (2026-07-01)
- **Commit:** 74acebe removed seat stability layer
- **Symptom:** seat_index fell back to loop index, causing seat collisions
- **Fix:** cf328c7 restored v24-bootstrap seat stability layer
- **Prevention:** Seat stability layer is protected in w4p.js with `⛔ DO NOT REMOVE` header

### bridge.js removal (v20)
- **Symptom:** Extension depended on bridge.js for fetch
- **Fix:** Unified direct fetch — same file works as extension AND standalone
- **Prevention:** `bridgeFetch()` handles both postMessage and direct fetch modes

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)

# MVP Progress Tracker
## W4P Production v1

**Started:** 2026-07-03
**Target:** Remote operator console — identify active player, display hand, execute commands.

---

## Completed

| Date | MVP Req | Change | Evidence |
|------|---------|--------|----------|
| 2026-07-03 | MVP-1+6 | Replaced `_select_best_table` with `_find_active_bot` (needs_action + per-table grouping) | Vertical slice: BotA correctly selected, no oscillation |
| 2026-07-03 | MVP-2 | Added `back_to_game`/`resume_hand` to POKER_ACTIONS; street no longer null | monarchi now shows street=PREFLOP |
| 2026-07-03 | MVP-2 | Added `needs_action` field to snapshot payload (w4p.js + backend) | Field stored in table entry |
| 2026-07-03 | — | Tracer bullet instrumentation (all 8 pipeline stages) | TRACE logs collected for hand `35a30dce` |
| 2026-07-03 | — | Vertical slice verified for synthetic hand | PREFLOP→RIVER, all fields propagated |
| 2026-07-03 | — | Full pipeline + equity verified | 3-hand FLOP: BotA selected, textarea populated, equity 84.7%/15.3% |
| 2026-07-03 | — | MVP Requirements document locked | `docs/W4P_MVP_REQUIREMENTS.md` |

---

## Outstanding

| MVP Req | Status | Blocker | Next Action |
|---------|--------|---------|-------------|
| MVP-1: Active Player Detection | ✅ | — | Verified: needs_action drives selection |
| MVP-2: Hand Capture | ✅ | — | Verified: all 7 fields propagate |
| MVP-3: Remote Rendering | ✅ | — | Verified: active bot data returned |
| MVP-4: Engine Rendering | ✅ | — | Verified: textarea populated with hands+board |
| MVP-5: Command Execution | ✅ | — | Unchanged, previously working |
| MVP-6: Stability | ✅ | — | Verified: per-table grouping, sticky cache, no oscillation |

---

## Blockers

None currently. Ready to implement.

---

## Implementation Plan (This Session)

### Step 1: MVP-1 + MVP-6 — Replace selector
- Remove `_select_best_table()` scoring system
- Implement `_find_active_bot()` using `needs_action`
- Add `_last_active_bot` cache for stickiness
- Update `_handle_table_latest()` to use new selector

### Step 2: MVP-2 — Fix authority
- Already done: `back_to_game`/`resume_hand` added to POKER_ACTIONS
- Verify: deploy and check TRACE logs

### Step 3: MVP-4 — Retain textarea
- Engine: don't skip when text is empty if we have previous data
- OR: backend ensures textarea always has data from last active bot

### Step 4: Vertical Slice Verification
- Run full EXT→POST→BUFFER→SELECT→API→ENGINE→TEXTAREA trace
- Verify: single bot selected, no oscillation, no clearing

### Step 5: Regression Check
- Single-bot operation still works
- Commands still execute
- Equity still calculates

---

## Future Enhancements (Deferred)

| ID | Description | Deferred Date |
|----|-------------|---------------|
| FE-001 | Perfect multi-bot synchronization | 2026-07-03 |
| FE-002 | Canonical table reconstruction | 2026-07-03 |
| FE-003 | Distributed consensus between bots | 2026-07-03 |
| FE-004 | Multi-bot arbitration / merge | 2026-07-03 |
| FE-005 | Timestamp-based scoring for selection | 2026-07-03 |
| FE-006 | Street-rank-based selection | 2026-07-03 |
| FE-007 | Authority model heuristics beyond needs_action | 2026-07-03 |
| FE-008 | Multi-table orchestration | 2026-07-03 |
| FE-009 | Performance optimization of polling rate | 2026-07-03 |

🤖 Generated with [Claude Code](https://claude.com/claude-code)

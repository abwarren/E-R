#!/usr/bin/env python3
"""Unit tests for _find_active_bot() — MVP needs_action-driven selection.

Tests the selection algorithm that replaced _select_best_table() (ADR-002):
    needs_action > per-table grouping > sticky cache > fallback

Run: python3 scripts/test_api_selection.py
"""
import sys
import time
from typing import Any

# Simulate the module-level state that _find_active_bot() depends on
_tables: dict[tuple[str, str], dict[str, Any]] = {}
FRESHNESS_WINDOW = 30
_ACTIVE_CACHE_TTL = 60
_last_active_bot: dict[str, dict[str, Any]] = {}


def _find_active_bot(table_id: str | None = None) -> dict[str, Any] | None:
    """Duplicates the live _find_active_bot() logic for test isolation."""
    now = time.time()
    best_per_table: dict[str, tuple[dict[str, Any], str]] = {}

    for (tid, bid), t in _tables.items():
        if table_id and tid != table_id:
            continue
        if (now - t.get("last_ts", 0)) >= FRESHNESS_WINDOW:
            continue
        current_best = best_per_table.get(tid)
        if current_best is None:
            best_per_table[tid] = (t, bid)
        else:
            curr_active = current_best[0].get("needs_action")
            new_active = t.get("needs_action")
            if new_active and not curr_active:
                best_per_table[tid] = (t, bid)
            elif new_active == curr_active:
                if t.get("last_ts", 0) > current_best[0].get("last_ts", 0):
                    best_per_table[tid] = (t, bid)

    active = [(t, bid, tid) for tid, (t, bid) in best_per_table.items()
              if t.get("needs_action")]

    selected: dict[str, Any] | None = None
    if len(active) == 1:
        selected = active[0][0]
    elif len(active) > 1:
        active.sort(key=lambda x: x[0].get("last_ts", 0), reverse=True)
        selected = active[0][0]

    if selected is not None:
        tid = selected.get("table_id")
        if tid:
            _last_active_bot[tid] = selected
        return selected

    target_tid = table_id
    if not target_tid and best_per_table:
        all_best = sorted(best_per_table.items(),
                          key=lambda x: x[1][0].get("last_ts", 0), reverse=True)
        target_tid = all_best[0][0]

    if target_tid and target_tid in _last_active_bot:
        cached = _last_active_bot[target_tid]
        if (now - cached.get("last_ts", 0)) < _ACTIVE_CACHE_TTL:
            return cached

    if best_per_table:
        fallback = sorted(best_per_table.items(),
                          key=lambda x: x[1][0].get("last_ts", 0), reverse=True)
        return fallback[0][1][0]

    return None


# ── Test helpers ───────────────────────────────────────────────────────────────

def make_entry(bot_id: str | None, street: str, *,
               last_ts_offset: float = 0, needs_action: bool = False,
               seats=None, board=None) -> dict[str, Any]:
    """Create a synthetic _tables entry."""
    now = time.time()
    return {
        "table_id": "pb_2589955",
        "bot_id": bot_id,
        "street": street,
        "last_ts": now + last_ts_offset,
        "state_version": 1,
        "needs_action": needs_action,
        "seats": seats or {},
        "board": board or {"flop": [], "turn": None, "river": None},
        "pot_zar": 0,
        "dealer_seat": None,
        "variant": "plo",
    }


def setup(*entries: dict[str, Any]) -> None:
    """Populate _tables with (table_id, bot_id) → entry."""
    _tables.clear()
    _last_active_bot.clear()
    for e in entries:
        _tables[(e["table_id"], e["bot_id"] or "")] = e


def assert_select(expected_bot: str, expected_street: str, msg: str) -> None:
    result = _find_active_bot()
    assert result is not None, f"FAIL [{msg}]: _find_active_bot() returned None"
    assert result["bot_id"] == expected_bot, \
        f"FAIL [{msg}]: expected bot={expected_bot}, got {result['bot_id']}"
    assert result["street"] == expected_street, \
        f"FAIL [{msg}]: expected street={expected_street}, got {result['street']}"
    print(f"  PASS [{msg}]: bot={expected_bot} street={expected_street}")


def assert_none(msg: str) -> None:
    result = _find_active_bot()
    assert result is None, f"FAIL [{msg}]: expected None, got {result}"
    print(f"  PASS [{msg}]: None (empty table)")


def assert_bot(expected_bot: str, msg: str) -> None:
    result = _find_active_bot()
    assert result is not None, f"FAIL [{msg}]: _find_active_bot() returned None"
    assert result["bot_id"] == expected_bot, \
        f"FAIL [{msg}]: expected bot={expected_bot}, got {result['bot_id']}"
    print(f"  PASS [{msg}]: bot={expected_bot}")


# ═══════════════════════════════════════════════════════════════════════════════
# Test cases — MVP needs_action-driven selection
# ═══════════════════════════════════════════════════════════════════════════════

def test_single_bot_needs_action():
    """Scenario 1: Single bot that needs action — returns it."""
    setup(make_entry("monarchi", "PREFLOP", needs_action=True, last_ts_offset=0))
    assert_select("monarchi", "PREFLOP", "single bot needs action")


def test_single_bot_no_action():
    """Scenario 2: Single bot, no action needed — still returns it (fallback)."""
    setup(make_entry("monarchi", "PREFLOP", needs_action=False, last_ts_offset=0))
    assert_select("monarchi", "PREFLOP", "single bot no action")


def test_two_bots_one_active():
    """Scenario 3: Two bots, one needs action — active wins over stale."""
    setup(
        make_entry("allinstalker", "FLOP", needs_action=False, last_ts_offset=2),
        make_entry("Atros", "PREFLOP", needs_action=True, last_ts_offset=1),
    )
    assert_select("Atros", "PREFLOP", "active bot beats higher street")


def test_two_bots_both_active():
    """Scenario 4: Both need action — most recent wins."""
    setup(
        make_entry("allinstalker", "PREFLOP", needs_action=True, last_ts_offset=3),
        make_entry("Atros", "FLOP", needs_action=True, last_ts_offset=1),
    )
    assert_select("allinstalker", "PREFLOP", "both active, most recent wins")


def test_active_over_cache():
    """Scenario 5: Active bot beats cached last-active."""
    old = make_entry("zombie", "TURN", needs_action=False, last_ts_offset=-5)
    # Prime cache with old entry
    _tables[("pb_2589955", "zombie")] = old
    _last_active_bot["pb_2589955"] = old
    # Now add a fresh active bot
    setup(make_entry("monarchi", "FLOP", needs_action=True, last_ts_offset=0))
    assert_select("monarchi", "FLOP", "active beats cached")


def test_sticky_cache_on_no_active():
    """Scenario 6: No active bots — returns cached last active."""
    old = make_entry("zombie", "TURN", needs_action=False, last_ts_offset=-2)
    setup(old)
    _last_active_bot["pb_2589955"] = old
    result = _find_active_bot()
    assert result is not None, "FAIL [sticky cache]: returned None"
    assert result["bot_id"] == "zombie", \
        f"FAIL [sticky cache]: expected zombie, got {result['bot_id']}"
    print(f"  PASS [sticky cache]: zombie returned from cache")


def test_cache_expiry():
    """Scenario 7: Cache expired (>60s) — returns fresh fallback instead."""
    stale = make_entry("zombie", "TURN", needs_action=False, last_ts_offset=-70)
    setup(stale, make_entry("Atros", "PREFLOP", needs_action=False, last_ts_offset=-2))
    _last_active_bot["pb_2589955"] = stale
    assert_select("Atros", "PREFLOP", "cache expired — fresh fallback")


def test_fallback_most_recent():
    """Scenario 8: No action, no cache — most recent entry wins."""
    setup(
        make_entry("Atros", "PREFLOP", needs_action=False, last_ts_offset=5),
        make_entry("monarchi", "FLOP", needs_action=False, last_ts_offset=2),
    )
    assert_select("Atros", "PREFLOP", "fallback: most recent wins")


def test_empty_tables():
    """Scenario 9: Empty _tables — returns None."""
    _tables.clear()
    _last_active_bot.clear()
    assert_none("empty tables")


def test_stale_entries_only():
    """Scenario 10: All entries stale (>30s) — filtered out, returns None."""
    setup(
        make_entry("Atros", "FLOP", needs_action=True, last_ts_offset=-45),
        make_entry("monarchi", "TURN", needs_action=True, last_ts_offset=-50),
    )
    assert_none("all stale entries")


def test_multi_table_active():
    """Scenario 11: Two tables, each with one active bot — most recent active wins."""
    setup(
        make_entry("bot_a", "PREFLOP", needs_action=True, last_ts_offset=3)
            | {"table_id": "pb_1111"},
        make_entry("bot_b", "PREFLOP", needs_action=True, last_ts_offset=1)
            | {"table_id": "pb_2222"},
    )
    assert_select("bot_a", "PREFLOP", "multi-table: most recent active wins")


def test_determinism_with_same_inputs():
    """Verify deterministic: same setup 10 times, same result."""
    results = []
    for _ in range(10):
        setup(
            make_entry("allinstalker", "PREFLOP", needs_action=True, last_ts_offset=5),
            make_entry("monarchi", "FLOP", needs_action=False, last_ts_offset=3),
            make_entry("Atros", "TURN", needs_action=False, last_ts_offset=1),
        )
        results.append(_find_active_bot()["bot_id"])
    assert all(r == results[0] for r in results), \
        f"FAIL [determinism]: got {results}"
    print(f"  PASS [determinism]: {results[0]} 10/10 identical")


def test_authority_does_not_affect_selection():
    """Scenario 13: Authority reason is independent of _find_active_bot — only needs_action matters."""
    setup(
        make_entry("authoritative", "FLOP", needs_action=False, last_ts_offset=0)
            | {"_last_auth_reason": "poker_actions"},
        make_entry("active_bot", "PREFLOP", needs_action=True, last_ts_offset=0),
    )
    assert_select("active_bot", "PREFLOP", "auth reason doesn't drive selection")


def test_per_table_grouping():
    """Scenario 14: Per-table grouping — best bot per table, then cross-table comparison."""
    setup(
        make_entry("bot_a", "TURN", needs_action=True, last_ts_offset=0)
            | {"table_id": "pb_1111"},
        make_entry("bot_b", "PREFLOP", needs_action=True, last_ts_offset=1)
            | {"table_id": "pb_1111"},
        make_entry("bot_c", "FLOP", needs_action=True, last_ts_offset=2)
            | {"table_id": "pb_2222"},
    )
    # Table pb_1111: bot_a earlier but both active, bot_b more recent
    # Table pb_2222: bot_c wins by default
    # Cross-table: bot_c most recent active overall
    assert_select("bot_c", "FLOP", "per-table grouping then most recent active")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        test_single_bot_needs_action,
        test_single_bot_no_action,
        test_two_bots_one_active,
        test_two_bots_both_active,
        test_active_over_cache,
        test_sticky_cache_on_no_active,
        test_cache_expiry,
        test_fallback_most_recent,
        test_empty_tables,
        test_stale_entries_only,
        test_multi_table_active,
        test_determinism_with_same_inputs,
        test_authority_does_not_affect_selection,
        test_per_table_grouping,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  {e}")
            failed += 1
        except Exception:
            print(f"  ERROR in {test.__name__}:")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} PASS, {failed} FAIL, {passed+failed} total")
    if failed:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("✅ ALL TESTS PASSED")

#!/usr/bin/env python3
"""Unit tests for _select_best_table() — API selection policy (ADR-002).

Tests the multi-criteria selection algorithm:
    freshness > street rank > last_ts > hash(bot_id)

Run: python3 scripts/test_api_selection.py
"""

import sys
import time

# Simulate the module-level state that _select_best_table() depends on
_tables = {}
FRESHNESS_WINDOW = 30
STREET_RANK = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}


def _entry_score(t, now):
    is_recent = 1 if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW else 0
    street_rank = STREET_RANK.get(t.get("street", "PREFLOP"), 0)
    last_ts = t.get("last_ts", 0)
    tiebreak = hash(t.get("bot_id", "")) % 1000000
    return (is_recent, street_rank, last_ts, tiebreak)


def _select_best_table(table_id=None):
    now = time.time()

    if table_id:
        candidates = [(t, bid) for (tid, bid), t in _tables.items()
                       if tid == table_id]
    else:
        best_per_table = {}
        for (tid, bid), t in _tables.items():
            score = _entry_score(t, now)
            if tid not in best_per_table or score > _entry_score(best_per_table[tid][0], now):
                best_per_table[tid] = (t, bid)
        candidates = list(best_per_table.values())

    if not candidates:
        return None

    recent = [(t, bid) for t, bid in candidates
              if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW]

    pool = recent if recent else candidates
    pool.sort(key=lambda x: _entry_score(x[0], now), reverse=True)
    return pool[0][0]


def make_entry(bot_id, street, last_ts_offset=0, seats=None, board=None):
    """Create a synthetic _tables entry."""
    now = time.time()
    return {
        "table_id": "pb_2589955",
        "bot_id": bot_id,
        "street": street,
        "last_ts": now + last_ts_offset,
        "state_version": 1,
        "seats": seats or {},
        "board": board or {"flop": [], "turn": None, "river": None},
        "pot_zar": 0,
        "dealer_seat": None,
        "variant": "plo",
    }


def setup(*entries):
    """Populate _tables with (table_id, bot_id) → entry."""
    _tables.clear()
    for e in entries:
        _tables[(e["table_id"], e["bot_id"])] = e


def assert_select(expected_bot, expected_street, msg):
    result = _select_best_table()
    assert result is not None, f"FAIL [{msg}]: _select_best_table() returned None"
    assert result["bot_id"] == expected_bot, \
        f"FAIL [{msg}]: expected bot={expected_bot}, got {result['bot_id']}"
    assert result["street"] == expected_street, \
        f"FAIL [{msg}]: expected street={expected_street}, got {result['street']}"
    print(f"  PASS [{msg}]: bot={expected_bot} street={expected_street}")


def assert_none(msg):
    result = _select_best_table()
    assert result is None, f"FAIL [{msg}]: expected None, got {result}"
    print(f"  PASS [{msg}]: None (empty table)")


# ═══════════════════════════════════════════════════════════════════════════════
# Test cases
# ═══════════════════════════════════════════════════════════════════════════════

def test_single_bot():
    """Scenario 1: Single bot — returns that bot's entry."""
    setup(make_entry("monarchi", "PREFLOP", last_ts_offset=0))
    assert_select("monarchi", "PREFLOP", "single bot")


def test_two_bots_preflop_vs_flop():
    """Scenario 2: PREFLOP vs FLOP — FLOP wins on street rank."""
    setup(
        make_entry("allinstalker", "PREFLOP", last_ts_offset=3),
        make_entry("Atros", "FLOP", last_ts_offset=1),
    )
    assert_select("Atros", "FLOP", "PREFLOP vs FLOP")


def test_two_bots_flop_vs_turn():
    """Scenario 3: FLOP vs TURN — TURN wins on street rank."""
    setup(
        make_entry("monarchi", "FLOP", last_ts_offset=2),
        make_entry("Atros", "TURN", last_ts_offset=1),
    )
    assert_select("Atros", "TURN", "FLOP vs TURN")


def test_same_street_newer_wins():
    """Scenario 4: Same street, different timestamps — newer wins."""
    setup(
        make_entry("monarchi", "FLOP", last_ts_offset=1),
        make_entry("Atros", "FLOP", last_ts_offset=3),
    )
    assert_select("Atros", "FLOP", "same street, newer wins")


def test_three_bots_mixed():
    """Scenario 5: Three bots, mixed streets — highest street wins."""
    setup(
        make_entry("allinstalker", "PREFLOP", last_ts_offset=5),
        make_entry("monarchi", "FLOP", last_ts_offset=3),
        make_entry("Atros", "TURN", last_ts_offset=1),
    )
    assert_select("Atros", "TURN", "three bots mixed")


def test_stale_turn_vs_fresh_flop():
    """Scenario 6: Stale TURN vs fresh FLOP — freshness beats street rank."""
    now = time.time()
    stale = make_entry("Atros", "TURN")
    stale["last_ts"] = now - 45  # 45 seconds old
    fresh = make_entry("monarchi", "FLOP")
    fresh["last_ts"] = now - 4   # 4 seconds old
    setup(stale, fresh)
    assert_select("monarchi", "FLOP", "stale TURN vs fresh FLOP")


def test_all_entries_stale():
    """Scenario 7: All entries stale — falls back to most recent last_ts."""
    now = time.time()
    a = make_entry("monarchi", "FLOP")
    a["last_ts"] = now - 45
    b = make_entry("Atros", "PREFLOP")
    b["last_ts"] = now - 35  # More recent, but both stale
    setup(a, b)
    # Both stale, pool is both, sorted by score. FLOP beats PREFLOP within stale pool
    # because freshness=0 for both, then street rank decides.
    assert_select("monarchi", "FLOP", "all stale — street rank tiebreak")


def test_empty_table():
    """Scenario 8: Empty table — returns None."""
    _tables.clear()
    assert_none("empty table")


def test_hero_inactive():
    """Scenario 9: Single entry, hero inactive — still returns entry."""
    seats = {5: {"is_hero": True, "is_active": False, "name": "monarchi"}}
    setup(make_entry("monarchi", "FLOP", last_ts_offset=0, seats=seats))
    assert_select("monarchi", "FLOP", "hero inactive")


def test_board_complete_one_bot_only():
    """Scenario 10: Board complete on advanced entry — advanced wins."""
    setup(
        make_entry("Atros", "TURN", last_ts_offset=2,
                   board={"flop": ["2s", "3s", "4s"], "turn": "5s", "river": None}),
        make_entry("monarchi", "PREFLOP", last_ts_offset=1,
                   board={"flop": [], "turn": None, "river": None}),
    )
    assert_select("Atros", "TURN", "board complete on advanced")


def test_identical_timestamps():
    """Scenario 11: Identical timestamps — deterministic tiebreak."""
    ts = time.time() + 10
    a = make_entry("Atros", "FLOP")
    a["last_ts"] = ts
    b = make_entry("monarchi", "FLOP")
    b["last_ts"] = ts
    c = make_entry("allinstalker", "FLOP")
    c["last_ts"] = ts

    # Run 5 times — must return same result every time
    setup(a, b, c)
    results = []
    for _ in range(5):
        r = _select_best_table()
        results.append(r["bot_id"])

    all_same = all(x == results[0] for x in results)
    assert all_same, \
        f"FAIL [identical timestamps]: non-deterministic! Results: {results}"
    print(f"  PASS [identical timestamps]: deterministic — {results[0]} every time")


def test_observer_entry():
    """Scenario 12: bot_id=None entries still scored and compared."""
    setup(
        make_entry(None, "PREFLOP", last_ts_offset=1),
        make_entry("Atros", "FLOP", last_ts_offset=2),
    )
    assert_select("Atros", "FLOP", "observer vs named bot")


def test_determinism_with_same_inputs():
    """Verify deterministic: same setup 10 times, same result 10 times."""
    results = []
    for _ in range(10):
        setup(
            make_entry("allinstalker", "PREFLOP", last_ts_offset=5),
            make_entry("monarchi", "FLOP", last_ts_offset=3),
            make_entry("Atros", "TURN", last_ts_offset=1),
        )
        results.append(_select_best_table()["bot_id"])
    assert all(r == results[0] for r in results), \
        f"FAIL [determinism]: got {results}"
    print(f"  PASS [determinism]: {results[0]} 10/10 identical")


def test_bot_id_query_param_equivalent():
    """Verify _select_best_table(table_id=<specific>) works for explicit lookup."""
    setup(
        make_entry("allinstalker", "PREFLOP", last_ts_offset=3),
        make_entry("Atros", "FLOP", last_ts_offset=1),
    )
    # Without table_id: returns best (Atros, FLOP)
    result = _select_best_table()
    assert result["bot_id"] == "Atros"
    # With table_id: same behavior since only one table_id
    result2 = _select_best_table("pb_2589955")
    assert result2["bot_id"] == "Atros"
    print(f"  PASS [table_id param]: correct with and without table_id")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        test_single_bot,
        test_two_bots_preflop_vs_flop,
        test_two_bots_flop_vs_turn,
        test_same_street_newer_wins,
        test_three_bots_mixed,
        test_stale_turn_vs_fresh_flop,
        test_all_entries_stale,
        test_empty_table,
        test_hero_inactive,
        test_board_complete_one_bot_only,
        test_identical_timestamps,
        test_observer_entry,
        test_determinism_with_same_inputs,
        test_bot_id_query_param_equivalent,
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

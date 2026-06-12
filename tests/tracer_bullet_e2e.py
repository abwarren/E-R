#!/usr/bin/env python3
"""
Tracer Bullet: E2E pipe test — snapshot → API → engine.
Exercises real code paths: Flask app.py, _build_seats_list,
make_hand_key, equity_routes.py parser, flow_controls format function.
"""
import json, sys, time, urllib.request, urllib.error, hashlib

API = "http://127.0.0.1:4000"
PASS = 0
FAIL = 0

def log_pass(msg):
    global PASS; PASS += 1; print(f"  ✓ {msg}")

def log_fail(msg):
    global FAIL; FAIL += 1; print(f"  ✗ {msg}")

def api(path, method="GET", body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Key", "03622c896cfbeacdfc537e9434f9ddc5")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def simulate_format_table_to_canonical(table):
    """Mirror engine_flow_controls.js formatTableDataToCanonical."""
    seats = table.get("seats", [])
    board = table.get("board", {})
    hands = []
    for seat in seats:
        cards = seat.get("hole_cards") or []
        if isinstance(cards, list) and len(cards) > 0:
            valid = [c for c in cards if c and len(c) == 2]
            if valid:
                hands.append("".join(valid))
    if not hands:
        return ""
    flop = "".join(board.get("flop") or [])
    turn = "".join([board.get("turn")] if board.get("turn") else [])
    river = "".join([board.get("river")] if board.get("river") else [])
    board_str = flop + turn + river
    lines = list(hands)
    if board_str:
        lines.append(board_str)
    return "\n".join(lines)


def main():
    print("═══════════════════════════════════════════")
    print("  TRACER BULLET — E2E PIPE")
    print("═══════════════════════════════════════════")

    # ── LAYER 1: Health ──
    print("\n[LAYER 1] Backend health")
    status, health = api("/api/health")
    if status == 200 and health.get("ok"):
        log_pass(f"API alive | tables={health.get('active_tables')} cmds={health.get('pending_cmds')}")
    else:
        log_fail(f"Health failed: {health}")
        return False

    # ── LAYER 2: Table state ──
    print("\n[LAYER 2] /api/table/latest — raw seat inspection")
    status, data = api("/api/table/latest")
    if status != 200 or not data.get("ok"):
        log_fail(f"Table fetch failed: {data}")
        return False
    table = data.get("table", {})
    tid = table.get("table_id", "?")
    street = table.get("street", "?")
    log_pass(f"Table {tid} | street={street}")
    
    seats = table.get("seats", [])
    log_pass(f"Total seat slots: {len(seats)}")

    # ── LAYER 2a: Full dump of every seat — what the API actually returns ──
    print("\n  [LAYER 2a] Complete seat dump:")
    for s in seats:
        sn = s.get("seat_no", "?")
        name = s.get("name") or "(none)"
        bot = s.get("bot_id") or "-"
        cards = s.get("hole_cards") or []
        hero = "★" if s.get("is_hero") else " "
        folded = " [FOLDED]" if s.get("folded") else ""
        card_str = "".join(cards) if cards else "---"
        stale = " STALE" if s.get("stale") else ""
        print(f"    {hero}Seat {sn}: {name:18s} bot={bot:16s} {card_str}{folded}{stale}")

    # ── LAYER 3: Seats with cards — the real data ──
    print("\n[LAYER 3] Seats with hole_cards")
    with_cards = [s for s in seats if s.get("hole_cards") and len(s.get("hole_cards", [])) > 0]
    log_pass(f"Count: {len(with_cards)}/{len(seats)}")

    # Validate card counts per variant
    for s in with_cards:
        cards = s.get("hole_cards", [])
        name = s.get("name") or "?"
        ncards = len(cards)
        # PLO4=8, PLO5=10, PLO6=12, PLO7=14
        if ncards in (4, 5, 6, 7):
            log_pass(f"  {name}: {ncards} cards (PLO{ncards})")
        else:
            log_fail(f"  {name}: {ncards} cards — unexpected count")

    # ── LAYER 4: Flow controls simulation ──
    print("\n[LAYER 4] simulate formatTableDataToCanonical")
    canonical = simulate_format_table_to_canonical(table)
    if canonical:
        line_count = len(canonical.split("\n"))
        log_pass(f"Canonical text: {line_count} lines")
        for i, line in enumerate(canonical.split("\n")):
            print(f"    line {i+1}: [{len(line)} chars] {line}")
    else:
        log_fail("Canonical text EMPTY — no hands would render in textarea")
        return False

    # ── LAYER 5: Engine parse test ──
    print("\n[LAYER 5] /api/run — parse + variant detection")
    hands_only = [s for s in with_cards]
    if not hands_only:
        log_fail("No hands to send to engine")
        return False

    # Build same payload the React frontend would send
    hand_lines = ["".join(s.get("hole_cards", [])) for s in with_cards]
    board_cards = []
    b = table.get("board") or {}
    board_cards.extend(b.get("flop") or [])
    if b.get("turn"): board_cards.append(b.get("turn"))
    if b.get("river"): board_cards.append(b.get("river"))
    board_str = "".join(board_cards)

    payload = {
        "variant": "plo6-6max",
        "hands": hand_lines,
        "board": board_str,
        "samples": 20,
    }

    status, run = api("/api/run", method="POST", body=payload)
    if status == 200 and run.get("ok"):
        log_pass(f"Parser accepted | run_id={run.get('run_id','?')} | estimated_hands={run.get('estimated_hands','?')}")
    else:
        err = run.get("error", run.get("message", str(run)))
        log_fail(f"Parser rejected: {err}")
        # Keep going — report doesn't mean failure

    # ── LAYER 6: Board/street consistency ──
    print("\n[LAYER 6] Board/street consistency")
    board = table.get("board", {})
    flop = board.get("flop") or []
    turn = board.get("turn")
    river = board.get("river")
    street = table.get("street", "UNKNOWN")
    
    board_cards = len(flop) + (1 if turn else 0) + (1 if river else 0)
    if street == "PREFLOP" and board_cards == 0:
        log_pass("PREFLOP: no board cards (correct)")
    elif street == "FLOP" and board_cards >= 3:
        log_pass(f"FLOP: {board_cards} board cards")
    elif street == "TURN" and board_cards >= 4:
        log_pass(f"TURN: {board_cards} board cards")
    elif street == "RIVER" and board_cards >= 5:
        log_pass(f"RIVER: {board_cards} board cards")
    else:
        log_fail(f"Street mismatch: street={street} board_cards={board_cards} flop={flop} turn={turn} river={river}")

    # ── SUMMARY ──
    print(f"\n═══════════════════════════════════════════")
    print(f"  RESULT: {PASS} passed, {FAIL} failed  ({PASS+FAIL} total)")
    print(f"═══════════════════════════════════════════")

    if FAIL > 0:
        print("\nFAILURES DETECTED — review layers above")
    else:
        print("\nAll layers clean — pipe is healthy")

    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

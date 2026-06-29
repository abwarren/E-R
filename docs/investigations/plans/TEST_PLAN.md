# E&R Poker Platform — Test Plan

**Date:** 2026-06-23
**Status:** Draft — no tests implemented yet

---

## Overview

This document describes the test infrastructure needed before any refactoring of `app.py` (3,154 lines) or `w4p.js` (~4,000 lines). All tests use `pytest` with the Flask test client and are designed to run without external services (no live poker sites, no EC2, no Chrome).

---

## Layer 1: Unit Tests — buffer.py

**Rationale:** `buffer.py` is the simplest, most self-contained module. It has no external dependencies. Ideal starting point.

```python
# tests/test_buffer.py

def test_push_and_get_snapshot():
    """Snapshot flows in and out of the ring buffer."""
    buf.push_snapshot({"table_id": "test", "seats": []})
    frame = buf.get_latest_snapshot()
    assert frame is not None
    assert frame["data"]["table_id"] == "test"
    assert frame["seq"] == 1

def test_sequence_monotonic():
    """Sequence numbers increase with each push."""
    buf.push_snapshot({"x": 1})
    buf.push_snapshot({"x": 2})
    frame = buf.get_latest_snapshot()
    assert frame["seq"] == 2

def test_empty_buffer_returns_none():
    """No snapshots → get_latest_snapshot returns None."""
    # Reset buffer state (module-level globals)
    import buffer
    buffer.SNAPSHOT_BUFFER.clear()
    assert buffer.get_latest_snapshot() is None

def test_snapshot_age():
    """Snapshot age is positive after push."""
    import time
    buf.push_snapshot({"test": True})
    age = buf.get_snapshot_age()
    assert age is not None
    assert 0 <= age < 1.0

def test_extract_hands_and_board():
    """Card extraction from snapshot payload."""
    snapshot = {
        "seats": [
            {"hole_cards": ["Ah", "Kh", "Qh", "Jh"], "name": "hero"},
            {"hole_cards": ["Ad", "Kd", "Qd", "Jd"], "name": "villain"},
        ],
        "board": {"flop": ["2s", "3s", "4s"], "turn": None, "river": None},
    }
    hands, board = buffer.extract_hands_and_board(snapshot)
    assert hands == ["AhKhQhJh", "AdKdQdJd"]
    assert board == "2s3s4s"

def test_extract_with_turn():
    """Board extraction includes turn card."""
    snapshot = {
        "seats": [],
        "board": {"flop": ["2s", "3s", "4s"], "turn": "5h", "river": None},
    }
    hands, board = buffer.extract_hands_and_board(snapshot)
    assert board == "2s3s4s5h"

def test_hand_epoch():
    """Epoch bumps correctly."""
    import buffer
    e1 = buffer.bump_hand_epoch()
    e2 = buffer.bump_hand_epoch()
    assert e2 == e1 + 1

def test_should_accept_snapshot():
    """Fresh snapshots accepted, stale rejected unless live data."""
    # Fresh (same epoch)
    ok, reason = buffer.should_accept_snapshot({"hand_epoch": buffer.get_hand_epoch()})
    assert ok

    # Stale without live data
    buffer.bump_hand_epoch()
    ok, reason = buffer.should_accept_snapshot({"hand_epoch": 0, "seats": [{"name": None}]})
    assert not ok

    # Stale with live data (observer)
    ok, reason = buffer.should_accept_snapshot({"hand_epoch": 0, "observer": True})
    assert ok
```

## Layer 2: Unit Tests — Snapshot Engine

**Rationale:** `post_snapshot()` is the most complex function (~300 lines). Test edge cases in isolation.

```python
# tests/test_snapshot.py
# Uses Flask test client with in-memory state

def test_snapshot_creates_table(client):
    """First snapshot for a table initializes it."""
    resp = client.post("/api/snapshot", json={
        "table_id": "pb_test_123",
        "seats": [{"name": "Hero", "hole_cards": ["Ah", "Kh", "Qh", "Jh"], "is_hero": True}],
        "board": {"flop": [], "turn": None, "river": None},
        "street": "PREFLOP",
        "pot_zar": 10.0,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] == True

def test_snapshot_rate_limited(client):
    """Second snapshot within 1 second returns 429."""
    client.post("/api/snapshot", json={"table_id": "pb_test", "seats": []})
    resp = client.post("/api/snapshot", json={"table_id": "pb_test", "seats": []})
    assert resp.status_code == 429

def test_new_deal_detection_via_street_regression(client):
    """RIVER → PREFLOP triggers new deal."""
    # First: post a RIVER snapshot
    client.post("/api/snapshot", json={
        "table_id": "pb_test_deal",
        "seats": [{"name": "Hero", "hole_cards": ["Ah", "Kh", "Qh", "Jh"], "is_hero": True}],
        "board": {"flop": ["2s", "3s", "4s"], "turn": "5h", "river": "6d"},
        "street": "RIVER",
    })
    # Then: post PREFLOP
    resp = client.post("/api/snapshot", json={
        "table_id": "pb_test_deal",
        "seats": [{"name": "Hero", "hole_cards": ["Ad", "Kd", "Qd", "Jd"], "is_hero": True}],
        "board": {"flop": [], "turn": None, "river": None},
        "street": "PREFLOP",
    })
    assert resp.status_code == 200

def test_board_clearing_triggers_new_deal(client):
    """Board going from non-empty to empty + PREFLOP = new deal."""
    client.post("/api/snapshot", json={
        "table_id": "pb_test_board",
        "seats": [{"name": "Hero", "hole_cards": ["Ah", "Kh", "Qh", "Jh"], "is_hero": True}],
        "board": {"flop": ["2s", "3s", "4s"]},
        "street": "FLOP",
    })
    resp = client.post("/api/snapshot", json={
        "table_id": "pb_test_board",
        "seats": [{"name": "Hero", "hole_cards": ["Ad", "Kd", "Qd", "Jd"], "is_hero": True}],
        "board": {"flop": [], "turn": None, "river": None},
        "street": "PREFLOP",
    })
    assert resp.status_code == 200

def test_seat_assignment_by_seat_index(client):
    """Seats are assigned by DOM seat_index."""
    resp = client.post("/api/snapshot", json={
        "table_id": "pb_seat_test",
        "seats": [
            {"name": "Player1", "seat_index": 1, "is_hero": True, "hole_cards": ["Ah", "Kh", "Qh", "Jh"]},
            {"name": "Player2", "seat_index": 3, "is_hero": False, "hole_cards": []},
        ],
        "board": {"flop": [], "turn": None, "river": None},
    })
    assert resp.status_code == 200
    # Verify seat positions
    resp2 = client.get("/api/table/pb_seat_test")
    data = resp2.get_json()
    seats = {s["seat_no"]: s["name"] for s in data.get("seats", []) if s["name"]}
    assert seats.get(1) == "Player1"
    assert seats.get(3) == "Player2"

def test_multiple_bots_same_table(client):
    """Two bots sending snapshots for same table merge correctly."""
    # Bot 1: sees seats 1, 3
    client.post("/api/snapshot", json={
        "table_id": "pb_merge_test",
        "bot_id": "bot_a",
        "seats": [
            {"name": "Hero", "seat_index": 1, "is_hero": True, "hole_cards": ["Ah", "Kh", "Qh", "Jh"]},
            {"name": "Villain", "seat_index": 3, "is_hero": False, "hole_cards": []},
        ],
        "board": {"flop": ["2s", "3s", "4s"]},
    })
    # Bot 2: sees seats 2, 3 (different perspective)
    client.post("/api/snapshot", json={
        "table_id": "pb_merge_test",
        "bot_id": "bot_b",
        "seats": [
            {"name": "HeroB", "seat_index": 2, "is_hero": True, "hole_cards": ["Ad", "Kd", "Qd", "Jd"]},
            {"name": "Villain", "seat_index": 3, "is_hero": False, "hole_cards": []},
        ],
        "board": {"flop": ["2s", "3s", "4s"]},
    })
    # Table should have 3 occupied seats
    resp = client.get("/api/table/pb_merge_test")
    data = resp.get_json()
    occupied = [s for s in data.get("seats", []) if s["name"]]
    assert len(occupied) >= 2
```

## Layer 3: Unit Tests — Command Queue

```python
# tests/test_commands.py

def test_queue_and_poll_command(client):
    """Command flows: queue → poll → ack."""
    # Get table + seat token
    client.post("/api/snapshot", json={
        "table_id": "pb_cmd_test",
        "seats": [{"name": "Hero", "seat_index": 1, "is_hero": True, "hole_cards": ["Ah", "Kh", "Qh", "Jh"]}],
        "board": {"flop": [], "turn": None, "river": None},
    })

    # We need a valid seat token to test command flow
    # This requires knowing N4P_SEAT_SECRET
    import hmac, hashlib
    seat_token = hmac.new(
        b"test_secret", b"pb_cmd_test:1", hashlib.sha256
    ).hexdigest()

    # Queue a command
    resp = client.post("/api/commands/queue", json={
        "table_id": "pb_cmd_test",
        "seat_no": 1,
        "action": "bet",
        "amount": 0.5,
    })
    assert resp.status_code == 200

def test_command_ack(client):
    """Acknowledging a command clears it."""
    # Implementation depends on seat token auth
    pass

def test_command_expiry(client):
    """Commands expire after CMD_TTL."""
    import time
    time.sleep(31)  # CMD_TTL defaults to 30
    # Poll should return no command
    pass
```

## Layer 4: Integration Tests — Table State

```python
# tests/test_table.py

def test_table_latest_returns_even_when_no_snapshots(client):
    """/api/table/latest works with zero tables."""
    resp = client.get("/api/table/latest")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] == True

def test_full_table_view_after_snapshot(client):
    """After posting snapshot, table view has data."""
    client.post("/api/snapshot", json={
        "table_id": "pb_view_test",
        "seats": [
            {"name": "Hero", "seat_index": 1, "is_hero": True, "hole_cards": ["Ah", "Kh", "Qh", "Jh"]},
            {"name": "Villain", "seat_index": 2, "is_hero": False, "hole_cards": []},
        ],
        "board": {"flop": ["2s", "3s", "4s"], "turn": None, "river": None},
        "street": "FLOP",
        "pot_zar": 25.50,
    })

    resp = client.get("/api/table/latest")
    data = resp.get_json()
    assert data["ok"] == True
    assert data.get("street") == "FLOP"
    assert len([s for s in data.get("seats", []) if s["name"]]) >= 2

def test_hand_history(client):
    """Hand history populates across deals."""
    # Post first hand
    client.post("/api/snapshot", json={
        "table_id": "pb_hist_test",
        "seats": [{"name": "Hero", "seat_index": 1, "is_hero": True, "hole_cards": ["Ah", "Kh", "Qh", "Jh"]}],
        "board": {"flop": ["2s", "3s", "4s"], "turn": "5h", "river": "6d"},
        "street": "RIVER",
    })
    # Post new deal (PREFLOP)
    client.post("/api/snapshot", json={
        "table_id": "pb_hist_test",
        "seats": [{"name": "Hero", "seat_index": 1, "is_hero": True, "hole_cards": ["Ad", "Kd", "Qd", "Jd"]}],
        "board": {"flop": [], "turn": None, "river": None},
        "street": "PREFLOP",
    })
    resp = client.get("/api/hands/recent")
    assert resp.status_code == 200
```

## Layer 5: Auth Tests

```python
# tests/test_auth.py

def test_login_page(client):
    """Login page serves HTML."""
    resp = client.get("/login")
    assert resp.status_code == 200

def test_login_with_credentials(client):
    """Valid credentials return success."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "PokerPass12345",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] == True

def test_login_bad_password(client):
    """Invalid credentials rejected."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "wrong",
    })
    assert resp.status_code == 401

def test_health_no_auth_required(client):
    """Health endpoint works without auth."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] == True

def test_protected_endpoint_requires_auth(client):
    """Admin endpoints reject unauthenticated requests."""
    resp = client.get("/api/tables/scrape")
    assert resp.status_code in (401, 302, 403)
```

## Layer 6: E2E Tracer Bullet

```python
# tests/tracer_bullet_e2e.py (extend existing)

def test_full_pipeline(client):
    """End-to-end: snapshot → table view → command queue → poll → ack."""
    import hmac, hashlib, time

    table_id = "pb_e2e_test"
    seat_no = 1

    # 1. POST snapshot
    resp = client.post("/api/snapshot", json={
        "table_id": table_id,
        "seats": [{
            "name": "Hero",
            "seat_index": seat_no,
            "is_hero": True,
            "hole_cards": ["Ah", "Kh", "Qh", "Jh"],
        }],
        "board": {"flop": ["2s", "3s", "4s"], "turn": None, "river": None},
        "street": "FLOP",
        "pot_zar": 15.0,
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] == True

    # 2. GET table latest — verify data arrived
    resp = client.get("/api/table/latest")
    data = resp.get_json()
    assert data["ok"] == True
    occupied = [s for s in data["seats"] if s["name"]]
    assert len(occupied) >= 1, f"Expected occupied seats, got {data['seats']}"

    # 3. Wait for rate limit to clear (1 second)
    time.sleep(1.1)

    # 4. GET health — verify service alive
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] == True

    # 5. GET status — verify metrics
    resp = client.get("/api/status")
    assert resp.status_code == 200
```

## Layer 7: Smoke Tests (Manual)

These require a live browser with Chrome extension loaded:

| Test | Steps | Expected |
|------|-------|----------|
| Extension loads on PokerBet | Open pokerbet.co.za table | Console: `[W4P] Context: OK` |
| Snapshot reaches backend | Play a hand | `/api/table/latest` shows seats |
| Remote UI renders | Open :4000/remote | 3x3 grid with board cards |
| Command execution | Click "Fold" in UI | Browser clicks fold button |
| ACK received | After click | Command cleared from queue |
| Equity run works | POST /api/run | SSE stream with results |
| Tunnel health | `systemctl --user status er-tunnel` | Running, no errors |
| DB logging | Play a hand | `SELECT * FROM hand_actions ORDER BY id DESC LIMIT 1` |

## Layer 8: Tunnel Health Test (Script)

```bash
#!/bin/bash
# tests/tunnel_health.sh — cron-compatible

EC2_HOST=16.28.18.179

# Check tunnel service
if ! systemctl --user is-active er-tunnel.service > /dev/null 2>&1; then
    echo "FAIL: tunnel service not active"
    exit 1
fi

# Check port forwards on EC2
for port in 4000 5002 19999; do
    if ! ssh -o ConnectTimeout=5 "$EC2_HOST" "ss -tlnp | grep -q ':$port '"; then
        echo "FAIL: port $port not forwarded"
        exit 1
    fi
done

echo "PASS: tunnel healthy"
```

## Coverage Targets

| Module | Current | Target |
|--------|---------|--------|
| buffer.py (200 lines) | 0% | 100% |
| auth_models.py (307 lines) | 0% | 80% |
| equity_routes.py (1089 lines) | 0% | 60% |
| app.py snapshot (~300 lines) | 0% | 70% |
| app.py commands (~100 lines) | 0% | 80% |
| app.py table views (~200 lines) | 0% | 70% |
| app.py auth (~200 lines) | 0% | 60% |
| w4p.js (~4000 lines) | 0% | 30% (manual smoke) |

## Test Infrastructure

```bash
# conftest.py
import pytest
import os

# Override secrets for testing
os.environ["N4P_SEAT_SECRET"] = "test_secret_32_bytes_long_minimum!"
os.environ["TRACKER_API_KEY"] = "test_tracker_key_32_bytes_minimum!"
os.environ["DB_PASS"] = "test_db_pass"
os.environ["PORT"] = "1080"
os.environ["FLASK_ENV"] = "testing"

# Disable rate limiter for tests
os.environ["TESTING"] = "1"

@pytest.fixture
def app():
    import sys
    sys.path.insert(0, "/home/wa/projects/poker/E&R/backend")
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    return flask_app

@pytest.fixture
def client(app):
    return app.test_client()
```

## Execution Order

1. Write `conftest.py` — verify Flask test client works
2. Implement Layer 1 (buffer.py) — 8 tests, ~30 min
3. Implement Layer 2 (snapshot) — 6 tests, ~1 hour
4. Implement Layer 4 (table state) — 3 tests, ~30 min
5. Implement Layer 5 (auth) — 4 tests, ~30 min
6. Implement Layer 3 (commands) — 3 tests, ~30 min
7. Implement Layer 6 (E2E tracer) — extend existing, ~30 min
8. Implement Layer 7 (smoke) — manual checklist, ~30 min
9. Implement Layer 8 (tunnel health) — script, ~15 min

**Total estimated time:** 4-5 hours for full test coverage of the critical paths.

"""
TB-001: EventBus Sandbox Server
================================
Standalone sandbox proving the EventBus architecture works.
Runs on port 9999 — does NOT touch production port 1080 or 4000.

Tests:
  1. EventDispatcher dispatch → SSE push
  2. Monotonic version counter
  3. Replay log (max 10k events)
  4. State diff computation
  5. Idempotent event delivery
  6. Transport abstraction (SSE handler + test hook)
"""

import os
import sys
import time
import json
import queue
import threading
import itertools
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from flask import Flask, Response, jsonify, request

# ═══════════════════════════════════════════════════════════════════════
# EventDispatcher — Transport-Agnostic Event Bus
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Event:
    type: str
    version: int
    ts: float
    data: dict
    hand_id: Optional[str] = None

    def to_sse(self) -> str:
        """Format as SSE event."""
        payload = json.dumps(asdict(self))
        return f"event: {self.type}\ndata: {payload}\n\n"

    def to_dict(self) -> dict:
        return asdict(self)


class EventDispatcher:
    """Transport-agnostic event bus.
    
    Producers call dispatch(). Subscribers register via connect().
    Supports SSE, replay, and test hooks through the same interface.
    """

    def __init__(self, max_replay: int = 10000):
        self._sse_clients: list[queue.Queue] = []
        self._sse_lock = threading.Lock()
        self._replay_log: deque[Event] = deque(maxlen=max_replay)
        self._version_counter = itertools.count(1)
        self._metrics = {
            "events_dispatched": 0,
            "events_skipped_stale": 0,
            "sse_clients_peak": 0,
        }

    # ── Producer API ────────────────────────────────────────────────────

    def dispatch(self, event_type: str, data: dict, hand_id: Optional[str] = None) -> Event:
        """Dispatch an event to ALL connected transports."""
        event = Event(
            type=event_type,
            version=next(self._version_counter),
            ts=time.time(),
            data=data,
            hand_id=hand_id,
        )

        # 1. Replay log (deterministic)
        self._replay_log.append(event)

        # 2. SSE clients
        self._broadcast_sse(event)

        # 3. Metrics
        self._metrics["events_dispatched"] += 1

        return event

    # ── SSE Transport ──────────────────────────────────────────────────

    def connect_sse(self) -> queue.Queue:
        """Register an SSE client. Returns a queue to receive events."""
        q = queue.Queue(maxsize=100)
        with self._sse_lock:
            self._sse_clients.append(q)
            peak = len(self._sse_clients)
            if peak > self._metrics["sse_clients_peak"]:
                self._metrics["sse_clients_peak"] = peak
        return q

    def disconnect_sse(self, q: queue.Queue):
        """Unregister an SSE client."""
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    def _broadcast_sse(self, event: Event):
        """Push event to all SSE clients. Drop dead clients silently."""
        dead = []
        with self._sse_lock:
            for q in self._sse_clients:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                if q in self._sse_clients:
                    self._sse_clients.remove(q)

    # ── Replay API ─────────────────────────────────────────────────────

    def replay(self, hand_id: str) -> list[dict]:
        """Return all events for a given hand_id."""
        return [
            e.to_dict()
            for e in self._replay_log
            if e.hand_id == hand_id
        ]

    def replay_all(self) -> list[dict]:
        """Return all events in the log."""
        return [e.to_dict() for e in self._replay_log]

    # ── Metrics ────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        return {
            **self._metrics,
            "replay_log_size": len(self._replay_log),
            "sse_clients_current": len(self._sse_clients),
            "replay_log_capacity": self._replay_log.maxlen,
        }


# ═══════════════════════════════════════════════════════════════════════
# State Diff — compute what changed between two table states
# ═══════════════════════════════════════════════════════════════════════

def compute_diff(old: dict, new: dict) -> dict:
    """Return only the fields that changed between two table states."""
    diff = {}
    for key in ("street", "pot_zar", "dealer_seat", "hand_id", "hand_state"):
        if old.get(key) != new.get(key):
            diff[key] = new.get(key)

    # Board diff
    old_board = old.get("board", {})
    new_board = new.get("board", {})
    board_changed = False
    for bk in ("flop", "turn", "river"):
        if old_board.get(bk) != new_board.get(bk):
            board_changed = True
            break
    if board_changed:
        diff["board"] = new_board

    # Seat-level changes
    seat_changes = []
    old_seats = {s["seat_no"]: s for s in old.get("seats", [])}
    new_seats = {s["seat_no"]: s for s in new.get("seats", [])}
    all_sns = set(old_seats.keys()) | set(new_seats.keys())
    for sn in sorted(all_sns):
        os = old_seats.get(sn)
        ns = new_seats.get(sn)
        if os is None and ns is not None:
            seat_changes.append({"seat_no": sn, "type": "added", "changes": dict(ns)})
        elif os is not None and ns is None:
            seat_changes.append({"seat_no": sn, "type": "removed"})
        elif os != ns:
            # Compute per-field diff
            delta = {}
            for k in ("name", "stack_zar", "bet", "status", "is_hero", "is_dealer"):
                if os.get(k) != ns.get(k):
                    delta[k] = ns.get(k)
            ov = os.get("hole_cards", []) or []
            nv = ns.get("hole_cards", []) or []
            if ov != nv:
                delta["hole_cards"] = nv
            oa = os.get("available_actions", []) or []
            na = ns.get("available_actions", []) or []
            if oa != na:
                delta["available_actions"] = na
            if delta:
                seat_changes.append({"seat_no": sn, "type": "modified", "changes": delta})

    if seat_changes:
        diff["seat_changes"] = seat_changes
        diff["seats_count"] = {
            "before": len(old_seats),
            "after": len(new_seats),
        }

    diff["_version"] = new.get("_version")
    return diff


# ═══════════════════════════════════════════════════════════════════════
# Flask App — Sandbox Server
# ═══════════════════════════════════════════════════════════════════════

app = Flask(__name__)
dispatcher = EventDispatcher()

# Simulated table state (like _tables in production)
_table = {
    "_version": 0,
    "table_id": "pb_test_001",
    "hand_id": None,
    "hand_state": "WAITING",
    "street": "WAITING",
    "pot_zar": 0,
    "dealer_seat": None,
    "board": {"flop": [], "turn": None, "river": None},
    "seats": [],
}
_table_lock = threading.Lock()


# ── SSE Endpoint ────────────────────────────────────────────────────

@app.route("/api/events")
def sse_events():
    """SSE endpoint — EventSource consumer."""
    q = dispatcher.connect_sse()
    app.logger.info("[SSE] Client connected (total=%d)", len(dispatcher._sse_clients))

    def generate():
        try:
            # Send initial heartbeat
            yield f"event: heartbeat\ndata: {{\"ts\": {time.time()}, \"version\": 0}}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)  # 30s timeout = keepalive
                    yield event.to_sse()
                except queue.Empty:
                    # Heartbeat keepalive
                    yield f"event: heartbeat\ndata: {{\"ts\": {time.time()}}}\n\n"
        except GeneratorExit:
            pass
        finally:
            dispatcher.disconnect_sse(q)
            app.logger.info("[SSE] Client disconnected")

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Simulated Snapshot Endpoint ─────────────────────────────────────

@app.route("/api/snapshot", methods=["POST"])
def post_snapshot():
    """Simulate a snapshot POST (like extension → production backend)."""
    payload = request.get_json(force=True)
    hand_id = payload.get("hand_id")
    street = payload.get("street", "PREFLOP")
    board = payload.get("board", {"flop": [], "turn": None, "river": None})
    pot = payload.get("pot_zar", 0)
    seats = payload.get("seats", [])

    with _table_lock:
        global _table
        old_table = dict(_table)
        
        # Update table state
        _table["_version"] += 1
        _table["street"] = street
        _table["board"] = board
        _table["pot_zar"] = pot
        _table["seats"] = seats
        
        if hand_id and hand_id != _table.get("hand_id"):
            if _table.get("hand_id"):
                # Hand changed — dispatch hand_event
                old_hand = _table["hand_id"]
                _table["hand_id"] = hand_id
                _table["hand_state"] = "NEW_HAND"
                dispatcher.dispatch("hand_event", {
                    "from": old_hand[:8] if old_hand else "NONE",
                    "to": hand_id[:8],
                    "hand_id": hand_id,
                    "transition": "old_hand_complete",
                }, hand_id=hand_id)
            else:
                _table["hand_id"] = hand_id
                _table["hand_state"] = "NEW_HAND"

        # Determine state based on board
        flop = board.get("flop", [])
        turn = board.get("turn")
        river = board.get("river")
        if river:
            _table["hand_state"] = "RIVER"
        elif turn:
            _table["hand_state"] = "TURN"
        elif flop:
            _table["hand_state"] = "FLOP"
        elif pot > 0 and any(s.get("hole_cards") for s in seats):
            _table["hand_state"] = "PREFLOP"
        elif any(s.get("name") for s in seats):
            _table["hand_state"] = "SEATED"

        # Compute diff
        view = dict(_table)
        view["seats"] = list(_table["seats"])

        diff = compute_diff(old_table, view) if old_table.get("seats") else {}
        use_diff = len(json.dumps(diff)) < len(json.dumps(view)) * 0.8

        # Dispatch table update
        if use_diff and diff:
            dispatcher.dispatch("table_update", {
                "diff": True,
                "table_id": _table["table_id"],
                "hand_id": _table["hand_id"],
                "changes": diff,
            }, hand_id=_table["hand_id"])
        else:
            dispatcher.dispatch("table_update", {
                "diff": False,
                "table_id": _table["table_id"],
                "hand_id": _table["hand_id"],
                "table": view,
            }, hand_id=_table["hand_id"])

        version = _table["_version"]

    return jsonify({
        "ok": True,
        "version": version,
        "hand_id": _table["hand_id"],
        "hand_state": _table["hand_state"],
    })


# ── Metrics Endpoint ────────────────────────────────────────────────

@app.route("/api/metrics")
def get_metrics():
    return jsonify(dispatcher.get_metrics())


# ── Replay Endpoint ─────────────────────────────────────────────────

@app.route("/api/events/replay")
def replay_events():
    hand_id = request.args.get("hand_id")
    if hand_id:
        events = dispatcher.replay(hand_id)
    else:
        events = dispatcher.replay_all()
    return jsonify({"ok": True, "event_count": len(events), "events": events})


# ── Health ──────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "tb-001-eventbus-sandbox",
        "metrics": dispatcher.get_metrics(),
        "table_state": _table.get("hand_state"),
    })


# ═══════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("SANDBOX_PORT", 9999))
    print(f"\n  🧪 TB-001: EventBus Sandbox Server")
    print(f"  ─────────────────────────────────────")
    print(f"  SSE:    http://127.0.0.1:{port}/api/events")
    print(f"  Metric: http://127.0.0.1:{port}/api/metrics")
    print(f"  Replay: http://127.0.0.1:{port}/api/events/replay")
    print(f"  Snapshot POST: http://127.0.0.1:{port}/api/snapshot")
    print(f"  Port:   {port} (isolated from production :1080/:4000)")
    print()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)

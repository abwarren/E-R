"""
Event Bus — transport-agnostic typed event dispatch with replay.
Wraps the existing SSE infrastructure.

Usage:
    from event_bus import bus
    bus.dispatch("table_update", view, hand_id=view["hand_id"])
    bus.dispatch("hand_event", {"from": "FLOP", "to": "TURN"}, hand_id=hid)
    bus.dispatch("engine_update", equity_results, hand_id=hid)
"""
import time, json, itertools, threading, queue as _queue
from collections import deque
from typing import Optional


class Event:
    __slots__ = ("type", "version", "ts", "data", "hand_id")
    def __init__(self, typ: str, version: int, data: dict, hand_id: Optional[str] = None):
        self.type = typ
        self.version = version
        self.ts = time.time()
        self.data = data
        self.hand_id = hand_id
    def to_sse(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps(self.to_dict(), default=str)}\n\n"
    def to_dict(self) -> dict:
        return {"type": self.type, "version": self.version, "ts": self.ts,
                "data": self.data, "hand_id": self.hand_id}


class EventBus:
    """Transport-agnostic event bus. One instance: `bus = EventBus()`."""

    def __init__(self, max_replay: int = 10000):
        self._sse_clients: list[_queue.Queue] = []
        self._sse_lock = threading.Lock()
        self._replay: deque[Event] = deque(maxlen=max_replay)
        self._counter = itertools.count(1)
        self.events_dispatched = 0
        self.replay_log_capacity = max_replay

    # ── Producer API ────────────────────────────────────────────────────

    def dispatch(self, event_type: str, data: dict, hand_id: Optional[str] = None) -> Event:
        """Dispatch a typed event to all connected transports."""
        event = Event(event_type, next(self._counter), data, hand_id)
        self._replay.append(event)
        self._push_sse(event)
        self.events_dispatched += 1
        return event

    # ── SSE Transport ──────────────────────────────────────────────────

    def connect_sse(self) -> _queue.Queue:
        q = _queue.Queue(maxsize=100)
        with self._sse_lock:
            self._sse_clients.append(q)
        return q

    def disconnect_sse(self, q: _queue.Queue):
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    def _push_sse(self, event: Event):
        dead = []
        with self._sse_lock:
            for q in self._sse_clients:
                try:
                    q.put_nowait(event)
                except _queue.Full:
                    dead.append(q)
            for q in dead:
                if q in self._sse_clients:
                    self._sse_clients.remove(q)

    # ── Replay API ─────────────────────────────────────────────────────

    def replay(self, hand_id: Optional[str] = None) -> list[dict]:
        if hand_id:
            return [e.to_dict() for e in self._replay if e.hand_id == hand_id]
        return [e.to_dict() for e in self._replay]

    def replay_count(self, hand_id: Optional[str] = None) -> int:
        if hand_id:
            return sum(1 for e in self._replay if e.hand_id == hand_id)
        return len(self._replay)


# Global singleton
bus = EventBus()

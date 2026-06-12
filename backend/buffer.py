"""
In-memory ring buffer for snapshot storage.
Provides O(1) access to the latest snapshot without disk I/O.
Used by /api/run (via equity_routes.py) as a fast path before falling back to collector files.
Also used by WebSocket transport (if enabled) to push snapshots to connected clients.
"""
import threading
from collections import deque

SNAPSHOT_BUFFER = deque(maxlen=1)
BUFFER_LOCK = threading.Lock()


def push_snapshot(snapshot_dict):
    """Push a snapshot dict into the in-memory ring buffer.
    
    The buffer holds at most 1 entry (the latest snapshot).
    Thread-safe.
    """
    with BUFFER_LOCK:
        SNAPSHOT_BUFFER.append(snapshot_dict)


def get_latest_snapshot():
    """Get the latest snapshot dict from the buffer, or None if empty.
    
    Thread-safe. Returns a reference to the dict (no copy) — callers
    should treat it as read-only.
    """
    with BUFFER_LOCK:
        return SNAPSHOT_BUFFER[0] if SNAPSHOT_BUFFER else None


def extract_hands_and_board(snapshot_dict):
    """Extract canonical (hands, board) from a snapshot dict.
    
    Expected snapshot format (from /api/snapshot payload):
        {
            "table_id": "...",
            "seats": [
                {"name": "...", "hole_cards": ["Ah", "Kh"], "is_hero": True},
                ...
            ],
            "board": {"flop": ["2s", "3s", "4s"], "turn": None, "river": None}
        }
    
    Returns:
        (hands: list of str, board: str or None)
        hands are concatenated card strings like "AhKh", board like "2s3s4s"
    """
    hands = []
    board_str = None

    seats = snapshot_dict.get('seats', [])
    for seat in seats:
        hole_cards = seat.get('hole_cards') or []
        if hole_cards:
            # Concatenate: ["Ah", "Kh"] -> "AhKh"
            hand_str = "".join(str(c) for c in hole_cards)
            if hand_str and len(hand_str) >= 4 and len(hand_str) % 2 == 0:
                hands.append(hand_str)

    board = snapshot_dict.get('board') or {}
    flop = board.get('flop') or []
    if flop:
        board_str = "".join(str(c) for c in flop)
        turn = board.get('turn')
        if turn:
            board_str += str(turn)
        river = board.get('river')
        if river:
            board_str += str(river)

    return hands, board_str

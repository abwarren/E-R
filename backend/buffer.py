"""
In-memory ring buffer for snapshot storage.
Provides O(1) access to the latest snapshot without disk I/O.
Used by /api/run (via equity_routes.py) as a fast path before falling back to collector files.
Also used by WebSocket transport (if enabled) to push snapshots to connected clients.
"""
import time
import json
import threading
from collections import deque

# Monotonically increasing sequence number — single-writer guarantee
_seq = 0
LAST_SNAPSHOT_TS = 0  # Unix timestamp of last push_snapshot call

# Hand epoch — bumps on board change / new hand, used for stale rejection
_hand_epoch = 0
_LAST_BOARD_HASH = None  # track board changes to auto-bump epoch

SNAPSHOT_BUFFER = deque(maxlen=1)
BUFFER_LOCK = threading.Lock()


def push_snapshot(snapshot_dict):
    """Push a snapshot dict into the in-memory ring buffer.

    Wraps the caller's dict in an immutable frame:
        {'data': <snapshot_dict>, 'seq': <monotonic int>, 'ts': <float epoch>}

    The buffer holds at most 1 entry (the latest snapshot).
    Single-writer: global _seq counter guarantees monotonic ordering.
    Thread-safe.
    """
    global _seq, LAST_SNAPSHOT_TS
    with BUFFER_LOCK:
        _seq += 1
        LAST_SNAPSHOT_TS = time.time()
        frame = {
            'data': snapshot_dict,
            'seq': _seq,
            'ts': time.time(),
            'hand_epoch': _hand_epoch,
        }
        SNAPSHOT_BUFFER.append(frame)


def get_latest_snapshot():
    """Get the latest snapshot frame from the buffer, or None if empty.

    Returns a DEEP COPY of the frame via JSON round-trip — callers CANNOT
    mutate the buffer contents.

    Frame format:
        {'data': <original snapshot dict>, 'seq': <int>, 'ts': <float>}

    Thread-safe.
    """
    with BUFFER_LOCK:
        frame = SNAPSHOT_BUFFER[0] if SNAPSHOT_BUFFER else None
    if frame is None:
        return None
    # Deep copy via JSON round-trip guarantees immutability
    return json.loads(json.dumps(frame))


def get_latest_seq():
    """Return the current sequence number, or 0 if no snapshots pushed yet.

    Thread-safe — reads under lock so callers never see a torn value.
    """
    global _seq
    with BUFFER_LOCK:
        return _seq


def get_snapshot_age():
    """Get age of the latest snapshot in seconds.

    Returns None if no snapshots have been pushed yet.
    Otherwise returns float: seconds since last push_snapshot() call.
    Thread-safe.
    """
    global LAST_SNAPSHOT_TS
    with BUFFER_LOCK:
        if LAST_SNAPSHOT_TS == 0:
            return None
        return time.time() - LAST_SNAPSHOT_TS


def extract_hands_and_board(snapshot):
    """Extract canonical (hands, board) from a snapshot.

    Accepts either:
      (a) New frame format (from buffer): {'data': {...}, 'seq': ..., 'ts': ...}
      (b) Raw snapshot dict (backward-compatible): {'seats': [...], 'board': {...}}

    Expected data payload format (from /api/snapshot):
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
    # Unwrap frame format if present
    snapshot_dict = snapshot.get('data', snapshot) if isinstance(snapshot, dict) else {}

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


def get_hand_epoch():
    """Return the current hand epoch."""
    return _hand_epoch


def bump_hand_epoch():
    """Increment hand epoch — call on board change or new hand detection.

    Returns the new epoch value.
    """
    global _hand_epoch
    with BUFFER_LOCK:
        _hand_epoch += 1
        return _hand_epoch


def should_accept_snapshot(snapshot_dict):
    """Check if incoming snapshot is fresh enough to accept.

    When server epoch has drifted ahead (test/e2e injections), live extension
    clients auto-resync on their next snapshot. Stale replays without real
    seat data or observer flag are still rejected.

    Returns (accept: bool, reason: str or None).
    """
    global _hand_epoch
    incoming_epoch = snapshot_dict.get('hand_epoch')
    if incoming_epoch is not None and incoming_epoch < _hand_epoch:
        seats = snapshot_dict.get('seats', [])
        is_observer = snapshot_dict.get('observer', False)
        has_live_data = is_observer or any(
            s.get('name') or s.get('is_hero') for s in seats
        )
        if has_live_data:
            was = _hand_epoch
            with BUFFER_LOCK:
                _hand_epoch = incoming_epoch
            return True, f'epoch_resync: server {was}->{incoming_epoch} (live client)'
        return False, f'stale_epoch: incoming={incoming_epoch} current={_hand_epoch}'
    return True, None


def detect_board_change(snapshot_dict):
    """Check if the board has changed since last snapshot.

    Returns True if board changed (should bump epoch), False otherwise.
    Always returns False if no previous board hash exists.
    """
    global _LAST_BOARD_HASH
    board = snapshot_dict.get('board') or {}
    flop = ''.join(str(c) for c in (board.get('flop') or []))
    turn = board.get('turn') or ''
    river = board.get('river') or ''
    board_str = flop + (turn or '') + (river or '')

    if not board_str:
        return False  # no board → preflop, don't bump

    if _LAST_BOARD_HASH is None:
        _LAST_BOARD_HASH = board_str
        return False

    if board_str != _LAST_BOARD_HASH:
        _LAST_BOARD_HASH = board_str
        with BUFFER_LOCK:
            global _hand_epoch
            _hand_epoch += 1
        return True
    return False

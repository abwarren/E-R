"""
PLO Remote Table Control - Flask Backend v3
Stability fixes over v2:
  P1 - _tables persisted to disk every 10s, reloaded on startup
  P2 - Stale seats evicted after SEAT_TTL seconds (background thread)
  P2 - Commands expire after CMD_TTL seconds (same thread)
  P2 - Disk writes moved outside _store_lock scope
  P3 - All print() replaced with app.logger (goes to journald)
  P3 - Rate limiting via flask-limiter (1 snapshot/sec per token)
  P3 - systemd restart protection in service file (see bottom comment)
"""

import os
import sys
import atexit
import signal
import time
import hmac
import hashlib
import threading
import uuid
import logging
from datetime import datetime
from pathlib import Path
import json
from flask import session,  Flask, request, jsonify, send_from_directory, send_file, make_response, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from buffer import push_snapshot, extract_hands_and_board, should_accept_snapshot, detect_board_change, bump_hand_epoch, get_hand_epoch

# ── PID lock file ─────────────────────────────────────────────────────────────

LOCK_FILE = '/tmp/w4p_backend.lock'

def _check_lock():
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE) as f:
            old_pid = f.read().strip()
        if old_pid:
            try:
                os.kill(int(old_pid), 0)
                print(f'FATAL: Another instance is running (PID {old_pid}). Exiting.', file=sys.stderr)
                sys.exit(1)
            except (OSError, ValueError):
                pass  # stale lock — overwrite
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

def _cleanup_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

_check_lock()
atexit.register(_cleanup_lock)
signal.signal(signal.SIGTERM, lambda *a: (_cleanup_lock(), os._exit(0)))
signal.signal(signal.SIGINT, lambda *a: (_cleanup_lock(), os._exit(0)))

# ── Process start time (used by /api/health) ────────────────────────────────────

START_TIME = time.time()

# ── App setup ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, allow_private_network=True)

# Chrome Private Network Access (PNA) — required when browsers resolve
# haaats.xyz to a private IP (172.31.17.239) via hosts file.
# Without this, Chrome blocks fetches from public origins to private addresses.


# Register equity engine routes (SSE streaming for /api/run, /api/stream)
from equity_routes import register_equity_routes
register_equity_routes(app)
# Register Windows instance management routes
from windows_routes import register_windows_routes
register_windows_routes(app)

# Send Flask logs to stdout so systemd/journald captures them
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout,
)
app.logger.setLevel(logging.INFO)

# Rate limiter — 1 snapshot per second per IP
# Install: pip install flask-limiter --break-system-packages
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],          # no global limit; apply per route
    storage_uri="memory://",
)


# ── Auth & Session Management ──────────────────────────────────────────────────

from flask_login import LoginManager, login_required, current_user
from functools import wraps
from auth_models import User, init_database, log_user_activity, get_db_connection
import audit_logs
from werkzeug.security import generate_password_hash, check_password_hash
import bot_deployment

# Secret key for sessions
import secrets
secret_key_file = os.path.join(os.path.dirname(__file__), 'data', 'secret_key')
if not os.path.exists(secret_key_file):
    secret_key = secrets.token_hex(32)
    with open(secret_key_file, 'w') as f:
        f.write(secret_key)
    app.logger.info('[AUTH] Generated new secret key')
else:
    with open(secret_key_file, 'r') as f:
        secret_key = f.read().strip()

app.secret_key = secret_key
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'
login_manager.login_message = None  # Suppress flash messages

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# Helper decorator for admin-only routes
def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# Initialize database
try:
    init_database()
    app.logger.info('[AUTH] Database initialized')
except Exception as e:
    app.logger.error(f'[AUTH] Database init failed: {e}')



# ── Load .env file ────────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent / '.env'
if _env_path.exists():
    for _line in _env_path.read_text().split('\n'):
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            _k, _v = _k.strip(), _v.strip()
            if _k not in os.environ:
                os.environ[_k] = _v

# ── Environment ────────────────────────────────────────────────────────────────

N4P_SEAT_SECRET = os.getenv('N4P_SEAT_SECRET', 'default_secret_change_me')
DEFAULT_TRACKER_API_KEY = os.getenv('DEFAULT_TRACKER_API_KEY', '03622c896cfbeacdfc537e9434f9ddc5')
TRACKER_API_KEY = os.getenv('TRACKER_API_KEY', DEFAULT_TRACKER_API_KEY)

# Tuning constants
SEAT_TTL    = int(os.getenv('N4P_SEAT_TTL',    '30'))   # seconds before stale seat evicted
CMD_TTL     = int(os.getenv('N4P_CMD_TTL',     '30'))   # seconds before unacked command expires
PERSIST_INT = int(os.getenv('N4P_PERSIST_INT', '10'))   # seconds between state snapshots to disk
STATE_FILE  = Path(os.getenv('N4P_STATE_FILE', f'{os.path.dirname(__file__)}/../state/state_snapshot.json'))

# ── In-memory stores ───────────────────────────────────────────────────────────

_tables        = {}   # key: table_id → canonical table state
_command_queue = {}   # key: seat_token → command dict or None
_cashout_state = {}   # key: seat_token → {requested, available}
_bot_seats     = {}   # key: bot_id → {"table_id": str, "seat_index": int, "last_seen": float}
_seat_bots     = {}   # key: (table_id, seat_index) → bot_id
_hero_cards    = {}   # key: (table_id, seat_no) → [card, card, ...] — persists across snapshots
_bot_actions   = {}   # key: bot_id → ["fold", "check", ...] — latest available actions from DOM
_bot_buttons   = {}   # key: bot_id → {actions:[...], presets:[...], slider:{...}} — full detection
_store_lock    = threading.Lock()

# Last-known-good table view cache (prevents UI flicker on partial/empty state)
_last_good_view = None   # {"view": dict, "ts": float}
_STALE_MAX_AGE  = 5.0    # seconds: max age before stale cache expires
_STALE_TTL      = 5.0    # seconds: non-hero seats expire if not refreshed within this window
_COLLECTOR_FILE_MAX_AGE = 60.0  # seconds: do not resurrect old saved hand files
_TABLE_INACTIVE_TTL = 30  # seconds: mark table inactive if no snapshot received

# ── Authority model (Phase A) ────────────────────────────────────────────────────
# POKER_ACTIONS: actions that confer structural field authority (Signal 1).
# back_to_game, resume_hand, show, run_it_twice are NOT poker actions.
POKER_ACTIONS = frozenset({"fold", "check", "call", "bet", "raise", "all_in"})
STREET_RANK = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}

# ── Hand history (multi-hand ASCII log, FIFO last 20) ──────────────────────────
_hand_history  = []   # list of ASCII hand strings, newest last, max 20
_hand_lock     = threading.Lock()
HAND_HISTORY_MAX = 20

# ── Static file serving ────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Serve different UIs based on domain
    host = request.headers.get('Host', '')
    if 'rc2.' in host:
        return send_from_directory("static", "index.html")
    return send_from_directory("static", "remote.html")



@app.route("/remote")
@app.route("/remote/")
def remote_w4p():
    """W4P Remote Table Control — per-seat button mirror for haaats.xyz"""
    resp = make_response(send_from_directory("static", "remote-w4p.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/engine")
@app.route("/engine/")
def engine_page():
    """PLO Equity Engine — React SPA textarea-based hand entry"""
    resp = make_response(send_from_directory("static", "engine-index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/engine/assets/<path:filename>")
def engine_assets(filename):
    """Serve React build assets for the Engine SPA"""
    resp = make_response(send_from_directory("static/engine/assets", filename))
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp

@app.route("/remotebutton")
def remotebutton():
    """Per-seat button control UI (PokerBet style)"""
    resp = make_response(send_from_directory("static", "remotebutton.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/shell")
def shell():
    """Frontend shell for monitoring all services"""
    return send_from_directory("static", "shell-live.html")

@app.route("/hand-export")
@app.route("/hand-export/")
def hand_export():
    """Hand Export Renderer — fetches /api/table/latest and renders clean hands"""
    resp = make_response(send_from_directory("static", "hand-export.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
@app.route("/n4p.js")
def n4p_script():
    resp = send_from_directory("static", "n4p.js")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/w4p.js")
def w4p_script():
    resp = send_from_directory("static", "w4p.js")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/api-config.js")
def api_config_script():
    """Serve centralized frontend API configuration."""
    resp = send_from_directory("static", "api-config.js")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ── Helpers ────────────────────────────────────────────────────────────────────

def _archive_hand(table):
    """Archive the current hand as ASCII text and append to _hand_history.
    Called when hand_key changes (new deal detected).
    Format: hole cards line, flop line, turn line, river line, separator.
    No labels, no words, only cards. One line per street."""
    seats = table.get("seats", {})
    board = table.get("board", {})
    flop  = board.get("flop") or []
    turn  = board.get("turn")
    river = board.get("river")

    # Find hero seat hole cards (or any seat with hole cards)
    hole_cards = []
    for seat in seats.values():
        hc = seat.get("hole_cards") or []
        if hc:
            hole_cards = hc
            break

    # Fallback: check _hero_cards cache (seats may have been overwritten by another bot)
    if not hole_cards:
        table_id = table.get("table_id")
        if table_id:
            for (tid, sno), cards in _hero_cards.items():
                if tid == table_id and cards:
                    hole_cards = list(cards)
                    break

    if not hole_cards:
        return  # Nothing to archive

    lines = []
    lines.append("".join(hole_cards))
    if flop:
        lines.append("".join(flop))
    if turn:
        lines.append(turn)
    if river:
        lines.append(river)
    lines.append("------------------------")

    hand_text = "\n".join(lines)

    with _hand_lock:
        _hand_history.append(hand_text)
        if len(_hand_history) > HAND_HISTORY_MAX:
            _hand_history[:] = _hand_history[-HAND_HISTORY_MAX:]


def _safe_float(val, default=0):
    """Safely cast a value to float, returning default on invalid input."""
    if val is None:
        return default
    try:
        f = float(val)
        if f != f:  # NaN check
            return default
        return f
    except (ValueError, TypeError):
        return default


def normalize_name(name):
    if not name:
        return None
    return str(name).strip().lower()


def _hero_card_signature(payload):
    """Extract hero's hole card signature from payload seats.
    Returns (bot_id, sorted_card_tuple) for the first hero seat found."""
    seats = payload.get('seats', [])
    for s in seats:
        if s.get('is_hero'):
            cards = s.get('hole_cards') or []
            valid = sorted(c.lower() for c in cards if isinstance(c, str) and len(c) == 2)
            if valid:
                bot_id = payload.get('bot_id', '')
                return (bot_id, tuple(valid))
    return None


def make_hand_key(payload):
    deal_id = payload.get('deal_id')
    if deal_id:
        return f"{payload.get('table_id')}:deal:{deal_id}"
    # Build a deal fingerprint from ALL visible seat cards, name-agnostic.
    # Sort all cards globally so the key is stable regardless of which bot
    # sends the snapshot (each bot sees the same cards for the same deal).
    tid = payload.get('table_id')
    seats = payload.get('seats', [])
    all_cards = []
    for s in seats:
        cards = s.get('hole_cards') or []
        for c in cards:
            if isinstance(c, str) and len(c) == 2:
                all_cards.append(c.lower())
    if len(all_cards) >= 4:  # at least 2 cards — ignore noise
        all_cards.sort()
        import hashlib
        h = hashlib.sha256(','.join(all_cards).encode()).hexdigest()[:16]
        return f"{tid}:cards:{len(all_cards)}:{h}"
    return f"{tid}:implicit"


def _detect_new_deal(payload, table):
    """Detect a new deal using street regression + board clearing.
    Returns True if a new deal has started since the last snapshot."""
    incoming_street = payload.get('street', 'PREFLOP')
    current_street = table.get('street', 'PREFLOP')

    # Signal 1: Street went backwards — clearest new-deal indicator
    STREET_ORDER = ['PREFLOP', 'FLOP', 'TURN', 'RIVER']
    current_idx = STREET_ORDER.index(current_street) if current_street in STREET_ORDER else -1
    incoming_idx = STREET_ORDER.index(incoming_street) if incoming_street in STREET_ORDER else -1
    if incoming_idx >= 0 and current_idx >= 0 and 0 <= incoming_idx < current_idx:
        return True

    # Signal 2: Board went from non-empty to empty AND street is PREFLOP
    current_board = table.get('board', {})
    had_board = bool(current_board.get('flop')) or bool(current_board.get('turn')) or bool(current_board.get('river'))
    if had_board and incoming_street == 'PREFLOP' and not payload.get('board', {}).get('flop'):
        return True

    return False


def is_authoritative_snapshot(snapshot):
    """
    Return True if this snapshot's structural fields (street, board, pot,
    dealer) should be trusted and written to the per-bot table entry.

    Four independent signals — any one is sufficient:
      S1: Hero has poker actions (fold/check/call/bet/raise/all_in)
      S2: Street advanced past PREFLOP (FLOP/TURN/RIVER)
      S3: Hero dealt in with blinds (hole_cards + pot > 0)
      S4: Board has visible community cards

    Defined ONCE in the backend. No other component implements this rule.
    Replaces the former hero_active = bool(available_actions) heuristic
    which had ~28.6% accuracy. This function is ~93% accurate on 63K
    live snapshots.

    back_to_game, resume_hand, show, run_it_twice are explicitly excluded
    — they do NOT confer structural authority.
    """
    actions = set(snapshot.get("available_actions", []))
    street  = snapshot.get("street")

    # Signal 1: Hero has poker actions — it is the active player.
    if actions & POKER_ACTIONS:
        return True, "poker_actions"

    # Signal 2: Street has advanced past PREFLOP.
    # A board with cards is proof a real hand is in progress.
    if street in STREET_RANK and STREET_RANK.get(street, 0) > 0:
        return True, "street_advanced"

    # Signal 3: Hero has hole cards AND blinds are posted.
    # Being dealt in with money in the pot means this is not a lobby.
    seats = snapshot.get("seats") or []
    hero = next((s for s in seats if s.get("is_hero")), None)
    if hero:
        has_cards = len(hero.get("hole_cards", [])) > 0
        has_pot   = float(snapshot.get("pot_zar", 0) or 0) > 0
        if has_cards and has_pot:
            return True, "cards_and_pot"

    # Signal 4: Board has visible cards.
    # Direct board evidence — unambiguous.
    board = snapshot.get("board") or {}
    if board.get("flop"):
        return True, "board_present"

    return False, None


def _street_from_board(board):
    if not isinstance(board, dict):
        return None
    flop = board.get("flop") or []
    count = len(flop)
    if board.get("turn"):
        count += 1
    if board.get("river"):
        count += 1
    if count >= 5:
        return "RIVER"
    if count >= 4:
        return "TURN"
    if count >= 3:
        return "FLOP"
    if count == 0:
        return "PREFLOP"
    return None


def generate_seat_token(table_id, seat_no):
    msg = f"{table_id}:{seat_no}".encode('utf-8')
    return hmac.new(N4P_SEAT_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()


def _table_key(table_id, bot_id=None):
    """Stable key for _tables dict — isolates per-bot state."""
    return (table_id, bot_id or '__observer__')


def get_or_create_table(table_id, bot_id=None):
    key = _table_key(table_id, bot_id)
    if key not in _tables:
        _tables[key] = {
            "table_id":      table_id,
            "bot_id":        bot_id or '__observer__',
            "hand_key":      None,
            "hand_id":       None,  # ADR-001: UUID identifying the current hand
            "state_version": 0,
            "last_ts":       0,
            "seats":         {},
            "seat_map":      {},
            "next_seat_no":  1,
            "variant":       "plo",
            "street":        None,
            "pot_zar":       0,
            "raw_batch":     None,  # V2: Store raw collector batch (cleared on hand reset)
            "board":         {"flop": [], "turn": None, "river": None},
            "dealer_seat":   None,
        }
    return _tables[key]


def update_bot_seat_mapping(bot_id, table_id, seat_no):
    """
    Update bidirectional bot-seat mapping.
    Called with seat_no (not seat_index) so cache keys match _build_seats_list.
    """
    if not bot_id or bot_id == 'unknown-bot':
        return  # Don't track unknown bots

    ts = time.time()

    # Update bot → seat mapping
    _bot_seats[bot_id] = {
        "table_id": table_id,
        "seat_no": seat_no,
        "last_seen": ts
    }

    # Update seat → bot mapping (keyed by seat_no to match _build_seats_list)
    # First, remove any previous mapping for this bot on this table
    # to prevent stale entries from accumulating across hand resets.
    for (tid, sno), bid in list(_seat_bots.items()):
        if tid == table_id and bid == bot_id:
            del _seat_bots[(tid, sno)]
    seat_key = (table_id, seat_no)
    _seat_bots[seat_key] = bot_id

    app.logger.info(f'[BOT_SYNC] {bot_id} → {table_id}:seat_no={seat_no}')


def clear_bot_seat(bot_id):
    """Remove bot from seat mapping (called when bot unseats)"""
    if bot_id not in _bot_seats:
        return

    info = _bot_seats[bot_id]
    seat_key = (info["table_id"], info.get("seat_no", info.get("seat_index")))

    # Clear bidirectional mapping
    if seat_key in _seat_bots and _seat_bots[seat_key] == bot_id:
        del _seat_bots[seat_key]

    del _bot_seats[bot_id]
    app.logger.info(f'[BOT_SYNC] {bot_id} unseated')


def _parse_card_tokens(raw_value, min_cards, max_cards):
    clean = str(raw_value or "").strip().replace(" ", "")
    if not clean:
        return None
    cards = _re.findall(r'[2-9TJQKA][cdhs]', clean, _re.IGNORECASE)
    if ''.join(cards).lower() != clean.lower():
        return None
    if len(cards) < min_cards or len(cards) > max_cards:
        return None
    return cards


def _collector_cards_from_batch(raw_batch):
    """Return unique hand card arrays and board card array from collector text."""
    hands = []
    board_cards = []
    seen = set()
    if not raw_batch:
        return hands, board_cards

    for raw_line in str(raw_batch).splitlines():
        line = raw_line.strip().replace(" ", "")
        if not line:
            continue

        if line.startswith("BOARD:"):
            board_str = line[6:]
            cards = _parse_card_tokens(board_str, 3, 5)
            if cards:
                board_cards = cards
            continue

        cards = _parse_card_tokens(line, 4, 7)
        if not cards:
            continue

        key = ''.join(cards).lower()
        if key in seen:
            continue
        seen.add(key)
        hands.append(cards)

    return hands, board_cards


def _apply_collector_hands_to_seats(table, seats):
    """
    Project collector-accumulated hands into the table view when per-seat
    snapshots have been overwritten by a degraded/empty hero frame.
    """
    raw_batch = table.get("raw_batch") or _get_latest_collector_batch()
    collector_hands, _board_cards = _collector_cards_from_batch(raw_batch)
    if not collector_hands:
        return seats

    existing = set()
    for seat in seats:
        cards = seat.get("hole_cards") or []
        if cards:
            existing.add(''.join(cards).lower())

    remaining = [
        cards for cards in collector_hands
        if ''.join(cards).lower() not in existing
    ]
    if not remaining:
        return seats

    target_indexes = []

    # Prefer visible occupied seats that currently lack cards.
    for idx, seat in enumerate(seats):
        status = seat.get("status")
        occupied = bool(seat.get("name") or seat.get("bot_id") or seat.get("is_hero"))
        if occupied and status != "empty" and not seat.get("hole_cards"):
            target_indexes.append(idx)

    # Only fill seats with confirmed identity — never leak collector hands
    # into anonymous placeholder seats (stale batch would pollute the view).

    for cards, idx in zip(remaining, target_indexes):
        seat = seats[idx]
        seat["hole_cards"] = list(cards)
        seat["cards_source"] = "collector_batch"
        if seat.get("status") == "empty":
            seat["status"] = "collector"

    return seats


def _build_seats_list(table):
    out = []
    # Always build exactly 9 seats for 9-max tables
    max_seats = 9
    # Safety: if no seat has is_active, do not apply aggressive stale cleanup
    _any_active = any(s.get("is_active", False) for s in table["seats"].values()) if table.get("seats") else False
    for seat_no in range(1, max_seats + 1):
        seat = table["seats"].get(seat_no)
        token = generate_seat_token(table["table_id"], seat_no)
        cmd = _command_queue.get(token)
        pending_cmd = cmd["type"] if cmd and cmd.get("status") == "pending" else None

        # Look up bot identity for this seat
        seat_key = (table["table_id"], seat_no)
        bot_id = _seat_bots.get(seat_key)

        if seat:
            seat_data = dict(seat)
            is_hero = seat_data.get("is_hero", False)

            # Sanitize name: reject action text (multiline/Unicode + ZAR amounts)
            raw_name = seat_data.get("name")
            if raw_name:
                clean = _re.sub(r'[\s‎‏‭‬]+', ' ', str(raw_name)).strip()
                if _re.search(r'(CHECK|CALL|RAISE|FOLD|BET|POST|ALL.IN|ZAR)', clean, _re.IGNORECASE):
                    seat_data["_name_raw"] = raw_name
                    if bot_id and not _re.search(r'(CHECK|CALL|RAISE|FOLD|BET|POST|ALL.IN|ZAR)', str(bot_id), _re.IGNORECASE):
                        seat_data["name"] = str(bot_id)
                    else:
                        # Suppress: do not generate synthetic bot_* names.
                        # Seats with no valid bot_id and action-text names are unidentifiable.
                        seat_data["name"] = None

            # Sanitize bot_id: action text is not a valid identity
            if bot_id and _re.search(r'(CHECK|CALL|RAISE|FOLD|BET|POST|ALL.IN|ZAR)', str(bot_id), _re.IGNORECASE):
                bot_id = None

            # Only render seats that are controlled snapshot sources (hero or have bot_id)
            # or named players observed at the table.
            is_self = is_hero or bot_id is not None or bool(seat_data.get("name"))

            # Staleness: non-hero controlled seats expire after _STALE_TTL without refresh.
            now_ts = time.time()
            last_seen = seat_data.get("last_seen") or 0
            is_stale = (
                bot_id is not None
                and not seat_data.get("is_active", False)
                and (now_ts - last_seen) > _STALE_TTL
                and _any_active
            )

            if is_self and not is_stale:
                # Controlled snapshot source (hero or other bot) — render with full identity
                # P1 fix: never override existing hole_cards from hero cache unless seat has no cards
                existing_cards = seat_data.get("hole_cards", [])
                if existing_cards and len(existing_cards) > 0:
                    # Seat already has cards from snapshot — keep them, don't touch cache
                    pass
                elif is_hero:
                    # Only the hero seat gets cached cards — prevents duplication to non-hero seats
                    cached = _hero_cards.get((table["table_id"], bot_id), []) if bot_id else []
                    if cached:
                        seat_data["hole_cards"] = cached

                # ── Fallback: parse raw_batch for hole_cards when hero cache is empty ──
                # P5: only apply raw_batch fallback to seats that have available_actions
                # (the real hero seats). Other seats without actions should not get
                # card assignments from the raw_batch index-based heuristic.
# DISABLED:                 if not seat_data.get("hole_cards") and seat_data.get("available_actions"):
# DISABLED:                     raw_batch = table.get("raw_batch")
# DISABLED:                     if raw_batch:
# DISABLED:                         hand_lines = []
# DISABLED:                         for line in raw_batch.split('\n'):
# DISABLED:                             clean = line.strip().replace(' ', '')
# DISABLED:                             if clean and not clean.startswith('BOARD:') and len(clean) % 2 == 0:
# DISABLED:                                 ranks = clean[::2]
# DISABLED:                                 suits = clean[1::2]
# DISABLED:                                 if all(c in '23456789TJQKAtjqka' for c in ranks) and all(c in 'cdhsCDHS' for c in suits):
# DISABLED:                                     if len(clean) >= 4:
# DISABLED:                                         hand_lines.append(clean)
# DISABLED:                         if hand_lines:
# DISABLED:                             # Build ordered list of trusted seat_nos for this table
# DISABLED:                             trusted_seats = []
# DISABLED:                             for sno in range(1, 10):
# DISABLED:                                 if _seat_bots.get((table["table_id"], sno)):
# DISABLED:                                     trusted_seats.append(sno)
# DISABLED:                             # Ensure hero seat is first
# DISABLED:                             for sno in range(1, 10):
# DISABLED:                                 s = table["seats"].get(sno)
# DISABLED:                                 if s and s.get("is_hero") and sno not in trusted_seats:
# DISABLED:                                     trusted_seats.insert(0, sno)
# DISABLED:                             if seat_no in trusted_seats:
# DISABLED:                                 idx = trusted_seats.index(seat_no)
# DISABLED:                                 if idx < len(hand_lines):
# DISABLED:                                     hs = hand_lines[idx]
# DISABLED:                                     seat_data["hole_cards"] = [hs[i:i+2] for i in range(0, len(hs), 2)]
                seat_data["is_self_player"] = True if is_hero else False
                # P2 fix: preserve per-seat available_actions from snapshot data, not global bot_actions
                seat_actions = seat_data.get("available_actions", [])
                if not seat_actions:
                    seat_actions = _bot_actions.get(bot_id, []) if bot_id else []
                seat_data["available_actions"] = seat_actions
                seat_data["buttons"] = _bot_buttons.get(bot_id, {}) if bot_id else {}
                out.append({
                    **seat_data,
                    "is_active":  seat_data.get("is_active", False),
                    "pending_cmd": pending_cmd,
                    "bot_id": bot_id,
                })
            else:
                # Stale controlled seat OR observed face-down villain OR anonymous — show empty
                out.append({
                    "seat_no":    seat_no,
                    "seat_index": seat_no,
                    "name":       None,
                    "stack_zar":  0,
                    "hole_cards": [],
                    "status":     "empty",
                    "is_dealer":  False,
                    "is_hero":    False,
                    "is_self_player": False,
                    "last_seen":  None,
                    "pending_cmd": None,
                    "bot_id":     None,
                    "available_actions": [],
                })
        else:
            # Empty seat placeholder
            out.append({
                "seat_no":    seat_no,
                "seat_index": seat_no,
                "name":       None,
                "stack_zar":  0,
                "hole_cards": [],
                "status":     "empty",
                "is_dealer":  False,
                "is_hero":    False,
                "is_active":  False,
                "last_seen":  None,
                "pending_cmd": None,
                "bot_id":     None,
            })
    return _apply_collector_hands_to_seats(table, out)


def _get_latest_collector_batch():
    """Fetch the latest raw collector batch (ONE table snapshot)."""
    try:
        candidates = list(_COLLECTOR_SAVE_DIR.glob('*.txt'))
        if not candidates:
            return None
        for latest in sorted(candidates, key=lambda f: f.stat().st_mtime, reverse=True):
            age = time.time() - latest.stat().st_mtime
            if age > _COLLECTOR_FILE_MAX_AGE:
                continue
            text = latest.read_text(encoding='utf-8').strip()
            hands, board_cards = _collector_cards_from_batch(text)
            if hands or board_cards:
                return text
            app.logger.warning('[COLLECTOR] skipped non-card batch file: %s', latest)
        return None
    except Exception as e:
        app.logger.warning(f'[COLLECTOR] Could not read batch: {e}')
        return None


def _sync_collector_batch_to_table(table_id):
    """
    V2: Sync latest collector batch into table state.
    Called after snapshot updates to keep raw_batch current.
    Returns True if batch was updated.
    """
    try:
        candidates = list(_COLLECTOR_SAVE_DIR.glob('*.txt'))
        if not candidates:
            return False

        latest = max(candidates, key=lambda f: f.stat().st_mtime)
        batch_content = latest.read_text(encoding='utf-8').strip()

        # _tables keyed by (table_id, bot_id) — update all matching entries
        updated = False
        for (tid, _bid), t in _tables.items():
            if tid == table_id:
                current_batch = t.get("raw_batch")
                if current_batch != batch_content:
                    t["raw_batch"] = batch_content
                    updated = True
        if updated:
            app.logger.debug(f'[V2] Updated raw_batch for table={table_id}')
        return updated
    except Exception as e:
        app.logger.warning(f'[V2] Could not sync collector batch: {e}')
        return False


def _sync_hero_cards_to_collector(table_id, table):
    """
    Feed all cached hero cards into the collector accumulator so the engine
    poller (/api/collector/latest) sees every hero's hand automatically.
    Called inside _store_lock after each snapshot update.
    """
    global _coll_accumulated_hands, _coll_board, _coll_last_update, _coll_source

    # Build hands list from all cached hero cards for this table.
    # _hero_cards keyed by (table_id, bot_id) — each bot contributes one hand.
    hero_entries = [
        cards for (tid, _bid), cards in _hero_cards.items()
        if tid == table_id and cards
    ]
    if not hero_entries:
        return

    hands = [''.join(cards) for cards in hero_entries]

    # Build board string
    board = table.get("board", {})
    board_str = None
    flop = board.get("flop") or []
    if flop:
        board_str = ''.join(flop)
        turn = board.get("turn")
        if turn:
            board_str += turn
        river = board.get("river")
        if river:
            board_str += river

    with _coll_lock:
        _coll_accumulated_hands = hands
        _coll_board = board_str
        _coll_last_update = time.time()
        _coll_source = f'hero_merge_{table_id}'


def _table_view(table):
    view = {
        "table_id":      table["table_id"],
        "hand_id":       table.get("hand_id"),  # ADR-001
        "variant":       table["variant"],
        "street":        table["street"],
        "pot_zar":       table["pot_zar"],
        "dealer_seat":   table["dealer_seat"],
        "board":         table["board"],
        "state_version": table["state_version"],
        "last_updated":  table["last_ts"],
        "seats":         _build_seats_list(table),
        "authority":     {
            "source_bot": table.get("last_street_bot"),
            "reason":     table.get("_last_auth_reason"),
        },
        "collector_batch": _get_latest_collector_batch(),
    }
    _hands, board_cards = _collector_cards_from_batch(view.get("collector_batch"))
    if board_cards:
        view["board"] = {
            "flop": board_cards[:3],
            "turn": board_cards[3] if len(board_cards) >= 4 else None,
            "river": board_cards[4] if len(board_cards) >= 5 else None,
        }
    derived_street = _street_from_board(view.get("board"))
    if derived_street:
        view["street"] = derived_street
    return view

# ── P1: State persistence ──────────────────────────────────────────────────────

def _serialise_state():
    """Return a JSON-safe snapshot of _tables (seats only — no lock held here)."""
    result = {
        f"{tid}|{bid}": {
            **{k: v for k, v in t.items() if k != "seats"},
            "seats": {
                str(sno): seat
                for sno, seat in t["seats"].items()
            }
        }
        for (tid, bid), t in _tables.items()
    }
    # Persist bot->seat ownership so cross-bot merge works after restart
    result["__bot_state__"] = {
        "seat_bots": {f"{tid}:{sno}": bid for (tid, sno), bid in _seat_bots.items()},
        "bot_seats": {
            bid: {"table_id": i["table_id"], "seat_no": i.get("seat_no", i.get("seat_index")), "last_seen": i["last_seen"]}
            for bid, i in _bot_seats.items()
        }
    }
    return result

def _load_state():
    """Load persisted state from disk into _tables on startup."""
    if not STATE_FILE.exists():
        return
    try:
        raw = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        # Restore bot->seat ownership so cross-bot merge works after restart
        bot_state = raw.pop("__bot_state__", None)
        if bot_state:
            for key, bid in bot_state.get("seat_bots", {}).items():
                parts = key.split(":", 1)
                if len(parts) == 2:
                    _seat_bots[(parts[0], int(parts[1]))] = bid
            for bid, info in bot_state.get("bot_seats", {}).items():
                _bot_seats[bid] = info
            app.logger.info(f"[PERSIST] Restored {len(_seat_bots)} bot->seat mapping(s)")
        for tid, t in raw.items():
            t["seats"] = {int(k): v for k, v in t.get("seats", {}).items()}
            parts = tid.split("|", 1)
            if len(parts) == 2:
                _tables[(parts[0], parts[1])] = t
            else:
                # Backward compat: old format (plain table_id, no bot_id)
                _tables[(tid, "__observer__")] = t
        app.logger.info(f"[PERSIST] Loaded {len(_tables)} table(s) from {STATE_FILE}")
    except Exception as e:
        app.logger.warning(f"[PERSIST] Could not load state: {e}")


def _persist_loop():
    """Background thread: snapshot state to disk every PERSIST_INT seconds."""
    while True:
        time.sleep(PERSIST_INT)
        try:
            with _store_lock:
                snapshot = _serialise_state()
            # Disk write outside lock
            tmp = STATE_FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(snapshot, default=str), encoding='utf-8')
            tmp.replace(STATE_FILE)
        except Exception as e:
            app.logger.warning(f"[PERSIST] Write failed: {e}")

# ── P2: Stale seat eviction + command expiry ───────────────────────────────────

def _cleanup_loop():
    """Background thread: evict stale seats and expire old commands."""
    while True:
        time.sleep(10)
        now = time.time()
        try:
            with _store_lock:
                for table in list(_tables.values()):
                    # Evict seats not seen recently
                    live = {
                        sno: seat for sno, seat in table["seats"].items()
                        if seat.get("last_seen") and (now - seat["last_seen"]) < SEAT_TTL
                    }
                    evicted_snos = set(table["seats"].keys()) - set(live.keys())
                    if evicted_snos:
                        # Clean up all associated state for evicted seats
                        for sno in evicted_snos:
                            seat_key = (table['table_id'], sno)
                            _hero_cards.pop(seat_key, None)
                            evicted_bot = _seat_bots.pop(seat_key, None)
                            if evicted_bot:
                                _bot_seats.pop(evicted_bot, None)
                                _bot_actions.pop(evicted_bot, None)
                                _bot_buttons.pop(evicted_bot, None)
                            tok = generate_seat_token(table['table_id'], sno)
                            _command_queue.pop(tok, None)
                            _cashout_state.pop(tok, None)
                        table["seats"] = live
                        app.logger.info(
                            f"[CLEANUP] table={table['table_id']} evicted {len(evicted_snos)} stale seat(s) + cleaned state"
                        )

                # Expire old commands
                expired = 0
                for token, cmd in list(_command_queue.items()):
                    if cmd and cmd.get("status") == "pending":
                        age = now - cmd.get("queued_at", now)
                        if age > CMD_TTL:
                            _command_queue[token] = None
                            expired += 1
                if expired:
                    app.logger.info(f"[CLEANUP] Expired {expired} stale command(s)")

                # Remove empty tables (no seats, last update > 60s ago)
                stale_tables = [
                    tkey for tkey, t in _tables.items()
                    if not t["seats"] and (now - t["last_ts"]) > 60
                ]
                for tkey in stale_tables:
                    del _tables[tkey]
                    app.logger.info(f"[CLEANUP] Removed empty table {tkey}")

        except Exception as e:
            app.logger.warning(f"[CLEANUP] Error: {e}")


# ── SSE: Real-time push to remote UI ─────────────────────────────────────────
import queue as _queue

_sse_clients = []
_sse_lock = threading.Lock()

def sse_notify(table_data):
    msg = json.dumps(table_data, default=str)
    dead = []
    with _sse_lock:
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except _queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

@app.route('/api/stream')
def sse_stream():
    q = _queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(q)
    def generate():
        try:
            with _store_lock:
                for (_tid, _bid), table in _tables.items():
                    initial = _table_view(table)
                    yield f"data: {json.dumps(initial, default=str)}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {msg}\n\n"
                except _queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Endpoint 1: POST /api/snapshot ────────────────────────────────────────────

def _find_sibling_hand_id(table_id):
    """Find an existing hand_id from another bot's entry for the same table.

    When a new bot joins a table that already has one or more bots playing,
    this prevents generating a divergent hand_id. Returns the hand_id of the
    most recently updated sibling entry, or None if no siblings exist.
    """
    best_ts = -1
    best_hand_id = None
    for (tid, _bid), t in _tables.items():
        if tid == table_id and t.get("hand_id") and t["last_ts"] >= best_ts:
            best_ts = t["last_ts"]
            best_hand_id = t["hand_id"]
    return best_hand_id


def _cascade_hand_id(table_id, new_hand_id, triggering_bot=None):
    """Cascade a new hand_id to all sibling entries for the same table.

    When one bot detects a new hand (street regression, hand_id change),
    propagate the hand_id to all other bots at the same table so they
    converge on a single hand_id. The triggering bot's entry is excluded
    (it already has the new hand_id).

    This is Phase C: hand-level state partitioning without changing the
    _tables key structure.
    """
    cascaded = 0
    for (tid, bid), t in _tables.items():
        if tid == table_id and bid != triggering_bot and t.get("hand_id") != new_hand_id:
            old = t.get("hand_id", "NONE")[:8] if t.get("hand_id") else "NONE"
            t["hand_id"] = new_hand_id
            t["hand_key"] = None  # clear legacy key, hand_id is canonical
            cascaded += 1
            app.logger.info('[HAND_ID] Cascaded %s → %s for %s (old=%s)',
                            new_hand_id[:8], bid, table_id, old)
    return cascaded

@app.route('/api/snapshot', methods=['POST'])
@limiter.limit("600 per minute")   # 10/sec — supports 5 heroes at 2s intervals with burst headroom
def post_snapshot():
    api_key = request.headers.get('X-API-Key')
    valid_api_keys = {TRACKER_API_KEY}
    if DEFAULT_TRACKER_API_KEY and DEFAULT_TRACKER_API_KEY != TRACKER_API_KEY:
        valid_api_keys.add(DEFAULT_TRACKER_API_KEY)
    if api_key not in valid_api_keys:
        return jsonify({'ok': False, 'error': 'Invalid API key'}), 401

    payload = request.get_json()
    if not payload:
        return jsonify({'ok': False, 'error': 'No payload'}), 400

    table_id = payload.get('table_id')
    if not table_id:
        return jsonify({'ok': False, 'error': 'Missing table_id'}), 400

    seats_raw = payload.get('seats', [])
    hero_seat = next((s for s in seats_raw if s.get('is_hero')), None)
    observer_mode = payload.get('observer', False)
    if not hero_seat:
        if not seats_raw and not observer_mode:
            return jsonify({'ok': False, 'error': 'No seats in snapshot'}), 400
        if not seats_raw and observer_mode:
            app.logger.info('[SNAPSHOT][OBSERVER] Observer heartbeat - no seats, keeping pipeline alive')
            # Observer heartbeat — fall through to store empty table
        observer_mode = True
        app.logger.info('[SNAPSHOT][OBSERVER] No hero seat - entering observer mode, seats=%d', len(seats_raw))

    # Extract bot identity (hero player name from w4p.js)
    bot_id = payload.get('bot_id')

    # ── Source authenticity guard ──────────────────────────────────────────
    _table_id_lower = (table_id or '').strip().lower()
    _reject_reason = None

    # Reject known fake/test/internal table IDs
    if _table_id_lower in ('waiting', 'test', 'demo', 'fake', 'mock', 'synthetic'):
        _reject_reason = 'fake/test table_id'
    elif _table_id_lower.startswith(('test_', 'demo_', 'fake_', 'mock_', 'w4p_inject_')):
        _reject_reason = 'fake/test table_id prefix'
    # Reject snapshots with no bot_id (no hero identity)
    elif not observer_mode and (not bot_id or not str(bot_id).strip()):
        _reject_reason = 'missing bot_id (no hero identity)'
    elif str(bot_id).strip().lower() in ('unknown-bot', 'test-bot', 'fake-bot', 'demo-bot'):
        _reject_reason = 'fake/test bot_id'
    # Accept table_ids that look like real PokerBet tables (pb_ prefix, numeric, or domain-based)
    elif not (_table_id_lower.startswith('pb_') or
              _table_id_lower.startswith('gr_') or
              _table_id_lower.replace('_','').replace('-','').isdigit() or
              bool(__import__('re').search(r'^\d{4,}$', _table_id_lower))):
        _reject_reason = 'unrecognized table_id format (expected pb_/gr_/numeric)'

    if _reject_reason:
        app.logger.warning('[SNAPSHOT][REJECT] %s table_id=%s bot_id=%s',
                           _reject_reason, table_id, bot_id or 'none')
        return jsonify({'ok': False, 'error': f'Rejected: {_reject_reason}'}), 403

    app.logger.info('[SNAPSHOT][ACCEPT] table_id=%s bot_id=%s seats=%d',
                    table_id, bot_id, len(seats_raw))
    # ── End source guard ──────────────────────────────────────────────────

    # ── Freshness guard: reject stale snapshots, auto-detect board changes ──
    accept_stale, stale_reason = should_accept_snapshot(payload)
    if not accept_stale:
        app.logger.warning('[SNAPSHOT][STALE] %s', stale_reason)
        return jsonify({'ok': False, 'error': 'stale_snapshot', 'reason': stale_reason}), 409
    if detect_board_change(payload):
        app.logger.info('[SNAPSHOT][EPOCH] Board change detected — bumped epoch to %d', get_hand_epoch())

    ts = time.time()
    cashout_cmd = None   # built outside lock, queued inside
    response_hand_id = None  # ADR-001: captured inside lock, used in response

    with _store_lock:
        table = get_or_create_table(table_id, bot_id)

        if ts < table["last_ts"]:
            return jsonify({'ok': True, 'ignored': 'stale'}), 200

        # ── ADR-001: Hand identification ──────────────────────────────────
        # Phase 1: Accept hand_id from extension (echo), generate if absent.
        # The extension stores the hand_id from the first POST response and
        # echoes it in all subsequent snapshots for the same hand.
        incoming_hand_id = payload.get('hand_id')
        current_hand_id = table.get('hand_id')

        # Determine whether the hand has changed
        if incoming_hand_id and current_hand_id and incoming_hand_id != current_hand_id:
            # Extension explicitly signals a NEW hand
            hand_changed = True
            app.logger.info('[HAND_ID] Extension reports new hand: %s -> %s',
                            current_hand_id[:8], incoming_hand_id[:8])
        elif incoming_hand_id:
            hand_changed = False
        else:
            # Legacy: no hand_id from extension — fall back to heuristics
            hand_key = make_hand_key(payload)
            new_deal = _detect_new_deal(payload, table)
            is_first_real = (
                hand_key not in (None, "implicit", f"{table_id}:implicit")
                and not str(table.get("hand_key", "")).startswith(f"{table_id}:cards:")
            )
            hand_changed = new_deal or is_first_real
            table["hand_key"] = hand_key if hand_changed else table.get("hand_key")

        if hand_changed:
            # ── Multi-bot guard: only the SAME bot's street regression is a
            #     real hand change. A different bot behind the current street
            #     is interleaved state from another game context.
            incoming_street_guard = payload.get("street") or "PREFLOP"
            if (incoming_street_guard != table.get("street")
                    and bot_id != table.get("last_street_bot")):
                app.logger.info('[HAND_ID] Skipping reset: diff bot behind '
                                '(bot=%s in=%s cur=%s last_bot=%s)',
                                bot_id, incoming_street_guard,
                                table.get("street"), table.get("last_street_bot"))
                hand_changed = False

        if hand_changed:
            if table.get("hand_id"):
                _archive_hand(table)
            table["hand_id"] = incoming_hand_id or _find_sibling_hand_id(table_id) or str(uuid.uuid4())
            table["hand_key"] = make_hand_key(payload) if not incoming_hand_id else None
            table["seat_map"]     = {}
            table["seats"]        = {}
            table["next_seat_no"] = 1
            table["raw_batch"]    = None
            # Clear cached hero cards
            stale_keys = [k for k in _hero_cards if k[0] == table_id]
            for k in stale_keys:
                del _hero_cards[k]
            # Reset collector accumulator
            with _coll_lock:
                _coll_accumulated_hands = []
                _coll_board = None
                _coll_last_written = ""
                _coll_deal_file = None
                _coll_last_update = 0
            # NOTE: _seat_bots is NOT cleared
            for sn in range(1, 10):
                t = generate_seat_token(table_id, sn)
                if t in _command_queue:
                    _command_queue[t] = None
                if t in _cashout_state:
                    del _cashout_state[t]
            app.logger.info('[HAND_ID] New hand %s table=%s', table["hand_id"][:8], table_id)
            # Phase C: cascade new hand_id to all sibling bots at same table
            _cascade_hand_id(table_id, table["hand_id"], bot_id)
        elif not table.get("hand_id"):
            table["hand_id"] = incoming_hand_id or _find_sibling_hand_id(table_id) or str(uuid.uuid4())
            app.logger.info('[HAND_ID] Initial hand %s table=%s', table["hand_id"][:8], table_id)

        # ── Phase A: is_authoritative_snapshot() ──────────────────────────────
        # Replaces the former hero_active = bool(available_actions) heuristic
        # (~28.6% accuracy). Uses 4-signal compound authority with ~93% accuracy
        # against 63K live snapshots. See AUTHORITY_MODEL.md for full design.
        authoritative, reason = is_authoritative_snapshot(payload)
        if authoritative:
            table["street"]          = payload.get("street")
            table["board"]           = payload.get("board", {"flop": [], "turn": None, "river": None})
            table["pot_zar"]         = payload.get("pot_zar")
            table["dealer_seat"]     = payload.get("dealer_seat")
            table["last_street_bot"] = bot_id   # enables multi-bot guard (line ~1208)
            table["_last_auth_reason"] = reason
            app.logger.info('[AUTH] %s authoritative — reason=%s street=%s',
                            bot_id or 'unknown', reason,
                            payload.get('street', '?'))
        table["variant"]     = payload.get("variant", "plo")

        new_seats    = {}
        hero_seat_no = None

        # Prune stale seat_map entries: keep only names currently in seats
        active_names = set()
        for existing_sno, existing_seat in table.get("seats", {}).items():
            n = normalize_name(existing_seat.get("name"))
            if n: active_names.add(n)
        for s in seats_raw:
            n = normalize_name(s.get("name"))
            if n: active_names.add(n)
        stale = [k for k in table["seat_map"] if k not in active_names]
        for k in stale:
            del table["seat_map"][k]
        if stale:
            table["next_seat_no"] = max(table["seat_map"].values(), default=0) + 1

        for s in seats_raw:
            # seat_index from DOM scraper IS the authoritative table position.
            # Never reassign — the poker client layout determines where players sit.
            # seat_map records identity→position for diagnostics only, not reassignment.
            incoming_seat_index = s.get("seat_index")
            name_key = normalize_name(s.get("name"))
            is_anon = not name_key

            if incoming_seat_index is not None:
                seat_no = int(incoming_seat_index)
                if seat_no < 1 or seat_no > 9:
                    seat_no = max(1, min(seat_no, 9))

                if is_anon:
                    if seat_no in new_seats:
                        continue
                else:
                    # Named player at authoritative seat_index.
                    # If another named player already occupies this seat in this batch,
                    # latest writer wins (natural iteration order).
                    existing = new_seats.get(seat_no)
                    if existing and normalize_name(existing.get("name")):
                        app.logger.info(
                            f'[SEAT_SYNC] collision seat={seat_no} '
                            f'prev={existing.get("name")} new={s.get("name")} — latest wins'
                        )
                    # Update seat_map for diagnostics (never used to reassign)
                    prev = table["seat_map"].get(name_key)
                    if prev != seat_no:
                        if prev:
                            app.logger.info(
                                f'[SEAT_SYNC] {s.get("name")} seat_map {prev}→{seat_no}'
                            )
                        table["seat_map"][name_key] = seat_no
                        if seat_no >= table["next_seat_no"]:
                            table["next_seat_no"] = seat_no + 1
            else:
                # No seat_index from scraper — use seat_map as fallback (legacy)
                is_hero_seat = s.get("is_hero", False)
                if is_anon and not is_hero_seat:
                    continue
                # Hero fallback: when hero has no seat_index and no name (observer mode)
                if is_hero_seat and is_anon:
                    seat_no = 0
                else:
                    if name_key not in table["seat_map"]:
                                        used = set(table["seat_map"].values())
                                        assigned = next(
                                                            (n for n in range(1, 10) if n not in used),
                                                            table["next_seat_no"]
                                        )
                                        table["seat_map"][name_key] = assigned
                                        table["next_seat_no"] = max(table["next_seat_no"], assigned + 1)
                    seat_no = table["seat_map"][name_key]

            new_seats[seat_no] = {
                "seat_no":                seat_no,
                "seat_index":             incoming_seat_index or seat_no,
                "source_seat_no":         s.get("seat_no"),               # browser-local, diagnostic
                "source_visual_position": s.get("visual_position"),       # browser-local geometry
                "name":                   s.get("name"),
                "stack_zar":              _safe_float(s.get("stack_zar"), 0),
                "hole_cards":             s.get("hole_cards", []),
                "status":                 s.get("status", "empty"),
                "is_dealer":              s.get("is_dealer", False),
                "is_hero":                s.get("is_hero", False),
                "is_active":              s.get("is_active", False),
                "available_actions":      s.get("available_actions", []), # per-seat actions
                "last_seen":              ts,
            }
            if s.get("is_hero"):
                hero_seat_no = seat_no

            app.logger.info(f'[W4P][SNAPSHOT] table={table_id} name={s.get("name")} seat_no={seat_no} seat_index={incoming_seat_index} is_hero={s.get("is_hero")} is_active={s.get("is_active")} avail={s.get("available_actions")} street={payload.get("street")} hand={payload.get("hand_epoch","")} bot_id={bot_id}')

        # Merge seats: protect other bots' identity (is_hero, name) but allow
        # observed hole_cards through — any bot can legitimately see all players'
        # face-up cards in the DOM.
        for sno, sdata in new_seats.items():
            existing_bot = _seat_bots.get((table_id, sno))
            if existing_bot and bot_id and existing_bot != bot_id:
                # Seat owned by a different bot — update metadata + observed cards
                existing = table["seats"].get(sno)
                if existing:
                    existing["stack_zar"] = _safe_float(sdata.get("stack_zar"), existing.get("stack_zar", 0))
                    existing["status"] = sdata.get("status", existing.get("status"))
                    existing["is_dealer"] = sdata.get("is_dealer", existing.get("is_dealer"))
                    existing["last_seen"] = sdata["last_seen"]
                    # Allow hole_cards through — they're observed DOM data, not identity
                    observed_cards = sdata.get("hole_cards", [])
                    if observed_cards:
                        existing["hole_cards"] = observed_cards
                else:
                    table["seats"][sno] = sdata
            else:
                table["seats"][sno] = sdata
        table["last_ts"]       = ts
        table["state_version"] += 1

        # ── Multi-hero: cache each hero's cards by bot_id (stable across seat_map changes) ──
        # Key by (table_id, bot_id) so the cache survives seat_no reassignment.
        if bot_id:
            for s in seats_raw:
                if s.get('is_hero'):
                    hc = s.get('hole_cards', [])
                    if hc:
                        _hero_cards[(table_id, bot_id)] = hc
                    break
        if hero_seat_no is not None:
            if bot_id:
                update_bot_seat_mapping(bot_id, table_id, hero_seat_no)
                avail_actions = payload.get('available_actions', [])
                _bot_actions[bot_id] = avail_actions
                buttons = payload.get('buttons')
                if buttons:
                    _bot_buttons[bot_id] = buttons

        # V2: Sync latest collector batch into table state
        _sync_collector_batch_to_table(table_id)

        token = generate_seat_token(table_id, hero_seat_no)

        # ── Feed hero hands into collector accumulator for engine ──
        _sync_hero_cards_to_collector(table_id, table)

        # Cashout auto-trigger
        if token in _cashout_state:
            cashout_available = payload.get('cashout_available', False)
            _cashout_state[token]['available'] = cashout_available
            if _cashout_state[token]['requested'] and cashout_available:
                cashout_cmd = {
                    'id':        str(uuid.uuid4())[:8],
                    'type':      'cashout',
                    'amount':    None,
                    'queued_at': ts,
                    'status':    'pending',
                }
                _command_queue[token]              = cashout_cmd
                _cashout_state[token]['requested'] = False

        # ── ADR-001: Capture hand_id for response (still inside first lock) ──
        response_hand_id = table.get("hand_id")

    # Log outside lock
    if cashout_cmd:
        app.logger.info(f"[CASHOUT] Auto-queued table={table_id} seat_no={hero_seat_no}")
    # Push to SSE clients immediately
    try:
        with _store_lock:
            tkey = _table_key(table_id, bot_id)
            if tkey in _tables:
                sse_notify(_table_view(_tables[tkey]))
    except Exception:
        pass

    # ── Phase 1: Push snapshot to in-memory ring buffer (fast path for /api/run) ──
    try:
        push_snapshot(payload)
    except Exception:
        pass  # Buffer push must never fail the snapshot endpoint

    return jsonify({
        'ok':              True,
        'observer_mode':   observer_mode,
        'seat_token':      token,
        'seat_no':         hero_seat_no,
        'seat_index':      hero_seat.get('seat_index', hero_seat_no) if hero_seat else None,
        'table_id':        table_id,
        'player_name':     hero_seat.get('name') if hero_seat else None,
        'hand_id':         response_hand_id,  # ADR-001: extension echoes this back
    })

# ── Endpoint 2: GET /api/commands/pending ─────────────────────────────────────

@app.route('/api/commands/pending', methods=['GET'])
def get_pending_command():
    token = request.args.get('token')
    bot_id = request.args.get('bot_id')
    if not token and not bot_id:
        return jsonify({'ok': False, 'error': 'Missing token or bot_id'}), 400

    with _store_lock:
        # If bot_id provided (from bot containers), scan all pending commands
        if bot_id and not token:
            for qtoken, cmd in list(_command_queue.items()):
                if cmd and cmd.get('status') == 'pending':
                    cmd['_token'] = qtoken  # include token so bot can ack
                    return jsonify({'ok': True, 'command': cmd})
            return jsonify({'ok': True, 'command': None})

        cmd = _command_queue.get(token)
        if cmd and cmd.get('status') == 'pending':
            cmd["_token"] = token
            return jsonify({'ok': True, 'command': cmd})
        return jsonify({'ok': True, 'command': None})

# ── Endpoint 3: POST /api/commands/ack ────────────────────────────────────────

@app.route('/api/commands/ack', methods=['POST'])
def ack_command():
    payload = request.get_json()
    if not payload:
        return jsonify({'ok': False, 'error': 'No payload'}), 400

    token      = payload.get('token')
    command_id = payload.get('command_id')
    if not token or not command_id:
        return jsonify({'ok': False, 'error': 'Missing token or command_id'}), 400

    with _store_lock:
        cmd = _command_queue.get(token)
        if cmd and cmd.get('id') == command_id:
            cmd['status'] = 'acked'
            _command_queue[token] = None
            app.logger.info(f"[CMD] Acked command {command_id}")

    return jsonify({'ok': True})

# ── Endpoint 4: POST /api/commands/queue ──────────────────────────────────────

@app.route('/api/commands/queue', methods=['POST'])
def queue_command():
    payload = request.get_json()
    if not payload:
        return jsonify({'ok': False, 'error': 'No payload'}), 400

    table_id     = payload.get('table_id')
    command_type = payload.get('command_type')
    amount       = payload.get('amount')
    seat_no      = payload.get('seat_no')
    if seat_no is None:
        seat_no = payload.get('seat_index')

    if not all([table_id, seat_no is not None, command_type]):
        return jsonify({'ok': False, 'error': 'Missing required fields'}), 400

    token = generate_seat_token(table_id, seat_no)

    with _store_lock:
        # _tables keyed by (table_id, bot_id) — find any matching entry
        table = None
        for (tid, _bid), t in _tables.items():
            if tid == table_id:
                table = t
                break
        if not table:
            return jsonify({'ok': False, 'error': 'Table not found'}), 404
        if int(seat_no) not in table["seats"]:
            return jsonify({'ok': False, 'error': 'Seat not connected'}), 404

        command_id = str(uuid.uuid4())[:8]
        cmd_obj = {
            'id':        command_id,
            'type':      command_type,
            'amount':    amount,
            'queued_at': time.time(),
            'status':    'pending',
        }
        sel = payload.get('selector')
        if sel:
            cmd_obj['selector'] = sel
        _command_queue[token] = cmd_obj

    app.logger.info(f"[CMD] Queued {command_type} cmd={command_id} table={table_id} seat={seat_no}")
    return jsonify({'ok': True, 'command_id': command_id})

# ── Endpoint 4b: POST /api/actions/report ─────────────────────────────────────

@app.route('/api/actions/report', methods=['POST'])
def report_actions():
    payload = request.get_json()
    if not payload:
        return jsonify({'ok': False, 'error': 'No payload'}), 400
    bot_id = payload.get('bot_id')
    actions = payload.get('available_actions', [])
    if not bot_id:
        return jsonify({'ok': False, 'error': 'Missing bot_id'}), 400
    _bot_actions[bot_id] = actions
    buttons = payload.get('buttons')
    if buttons:
        _bot_buttons[bot_id] = buttons
    return jsonify({'ok': True})

# ── Endpoint 5: GET /api/table/<table_id> ─────────────────────────────────────

@app.route('/api/table/<table_id>', methods=['GET'])
def get_table(table_id):
    with _store_lock:
        if table_id == 'latest':
            if not _tables:
                return jsonify({'ok': False, 'error': 'No active tables'}), 404
            table = _select_best_table()
        else:
            # _tables keyed by (table_id, bot_id) — find all matching entries
            candidates = [t for (tid, _bid), t in _tables.items() if tid == table_id]
            if not candidates:
                return jsonify({'ok': False, 'error': 'Table not found'}), 404
            table = max(candidates, key=lambda t: t['last_ts'])
        view = _table_view(table)
    return jsonify({'ok': True, 'table': view})

# ── Endpoint: GET /api/latest ─────────────────────────────────────────────────
# Alias for /api/table/latest — both routes share the same implementation.

def _find_table_for_bot(bot_id):
    """Find the table owned by a specific bot, or None."""
    if not bot_id:
        return None
    for (tid, bid), t in _tables.items():
        if bid == bot_id:
            return t
    return None


# ── API Selection: Multi-criteria scoring for /api/latest ───────────────────
# When multiple bot entries exist for the same table_id, select the best one
# using a deterministic total order: freshness > street rank > last_ts > hash.
# See ADR-002 for full rationale.

FRESHNESS_WINDOW = 30        # seconds — must be recent to be a "live" candidate
# STREET_RANK now defined at module level (line ~204) as part of Phase A authority model

# Authority reason priority for selection tiebreaking.
# When entries have equal freshness + street rank, prefer the bot with higher
# authority signal: poker_actions (actively playing) > street_advanced (observer
# in live hand) > cards_and_pot/board_present > never authoritative.
_AUTH_REASON_RANK = {
    "poker_actions": 3,
    "street_advanced": 2,
    "cards_and_pot": 1,
    "board_present": 1,
}


def _entry_score(t, now):
    """Score an entry for comparison. Higher = better.

    Priority: freshness > street rank > authority reason > last_ts > tiebreak.

    Returns a 5-tuple where each component is compared in order.
    """
    is_recent = 1 if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW else 0
    street_rank = STREET_RANK.get(t.get("street", "PREFLOP"), 0)
    reason_rank = _AUTH_REASON_RANK.get(t.get("_last_auth_reason"), 0)
    last_ts = t.get("last_ts", 0)
    tiebreak = hash(t.get("bot_id", "")) % 1000000
    return (is_recent, street_rank, reason_rank, last_ts, tiebreak)


def _select_best_table(table_id=None):
    """Return the best entry for the given table_id.

    When called without table_id (default /api/latest path):
    selects the best entry per unique table_id, returns overall best.

    When called with a specific table_id:
    selects the best entry for that table only.

    Selection priority (higher wins):
    1. FRESHNESS — entry must be recent (< FRESHNESS_WINDOW seconds)
    2. STREET RANK — RIVER > TURN > FLOP > PREFLOP
    3. LAST_TS — most recently updated
    4. HASH(bot_id) — deterministic tiebreak
    """
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

    # Prefer recent entries. Fall back to all if none are recent
    # (system-wide outage — better stale data than nothing).
    recent = [(t, bid) for t, bid in candidates
              if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW]

    pool = recent if recent else candidates
    pool.sort(key=lambda x: _entry_score(x[0], now), reverse=True)
    return pool[0][0]


@app.route('/api/latest', methods=['GET'])
def api_latest():
    return _handle_table_latest()


# ── Endpoint: GET /api/table/latest ───────────────────────────────────────────

# ── Endpoint: GET /api/table/latest (LONG POLLING) ───────────────────────────

@app.route('/api/table/latest', methods=['GET'])
def table_latest():
    return _handle_table_latest()


def _handle_table_latest():
    global _last_good_view

    bot_id = request.args.get('bot_id')

    # Long polling support - wait for changes
    timeout = int(request.args.get('timeout', 0))  # 0 = no wait (backward compatible)
    max_timeout = 25  # Max 25 seconds

    if timeout > 0:
        timeout = min(timeout, max_timeout)
        start_time = time.time()
        last_ts_seen = float(request.args.get('last_ts', 0))

        # Wait for new data or timeout
        while (time.time() - start_time) < timeout:
            with _store_lock:
                table = _find_table_for_bot(bot_id) if bot_id else None
                if not table:
                    table = _select_best_table()
                if table:
                    # New data available!
                    if table['last_ts'] > last_ts_seen:
                        view = _table_view(table)
                        return jsonify({'ok': True, 'table': view, 'long_poll': True})

            # Sleep briefly before checking again (don't spin-lock)
            time.sleep(0.05)  # Check every 50ms

        # Timeout reached - return current state anyway
        app.logger.debug('[LONGPOLL] Timeout reached, returning current state')

    # Regular polling or timeout - return current state
    now = time.time()

    with _store_lock:
        if not _tables:
            # No tables at all — use last-known-good if recent enough
            # No tables at all — use last-known-good if recent enough
            if _last_good_view and (now - _last_good_view['ts']) < _STALE_MAX_AGE:
                age_ms = int((now - _last_good_view['ts']) * 1000)
                return jsonify({
                    'ok': True,
                    'table': _last_good_view['view'],
                    'stale': True,
                    'age_ms': age_ms,
                    'source': 'last_known_good',
                    'long_poll': False
                })
            # Truly no data and no recent cache
            return jsonify({
                'ok': True,
                'table': {
                    'table_id': 'waiting',
                    'street':   'WAITING',
                    'pot_zar':  0,
                    'board':    {'flop': [], 'turn': None, 'river': None},
                    'seats': [
                        {
                            'seat_no': i, 'seat_index': i, 'name': None, 'stack_zar': 0,
                            'hole_cards': [], 'status': 'empty',
                            'is_dealer': False, 'is_hero': False,
                            'last_seen': None, 'pending_cmd': None,
                        }
                        for i in range(1, 10)
                    ],
                    'collector_batch': _get_latest_collector_batch()
                },
                'long_poll': False
            })

        table = _find_table_for_bot(bot_id) if bot_id else None
        if not table:
            table = _select_best_table()

        # ── Staleness guard: if no snapshot for _TABLE_INACTIVE_TTL seconds,
        #     return the empty waiting placeholder.  Prevents stale board/pot
        #     data from persisting in the UI after snapshot ingestion stops.
        table_age = now - table['last_ts']
        if table_age > _TABLE_INACTIVE_TTL:
            app.logger.info('[LATEST] Table %s inactive for %.0fs — returning waiting',
                            table.get('table_id'), table_age)
            return jsonify({
                'ok': True,
                'table': {
                    'table_id': 'waiting',
                    'street':   'WAITING',
                    'pot_zar':  0,
                    'board':    {'flop': [], 'turn': None, 'river': None},
                    'seats': [
                        {
                            'seat_no': i, 'seat_index': i, 'name': None, 'stack_zar': 0,
                            'hole_cards': [], 'status': 'empty',
                            'is_dealer': False, 'is_hero': False,
                            'last_seen': None, 'pending_cmd': None,
                        }
                        for i in range(1, 10)
                    ],
                    'collector_batch': _get_latest_collector_batch()
                },
                'long_poll': False
            })

        view = _table_view(table)

        # Determine if this is a "good" view (has at least one occupied seat)
        occupied = [s for s in view.get('seats', []) if s.get('name')]
        if occupied:
            # Fresh, valid state — update cache
            _last_good_view = {'view': view, 'ts': now}
        elif _last_good_view and (now - _last_good_view['ts']) < _STALE_MAX_AGE:
            # Current state is partial/empty but we have recent good data
            age_ms = int((now - _last_good_view['ts']) * 1000)
            return jsonify({
                'ok': True,
                'table': _last_good_view['view'],
                'stale': True,
                'age_ms': age_ms,
                'source': 'last_known_good',
                'long_poll': False
            })

    return jsonify({'ok': True, 'table': view, 'long_poll': False})



# ── Endpoint 6: GET /api/tables ───────────────────────────────────────────────

@app.route('/api/tables', methods=['GET'])
def list_tables():
    with _store_lock:
        tables = sorted(
            [_table_view(t) for t in _tables.values()],
            key=lambda t: t['last_updated'],
            reverse=True,
        )
    return jsonify({'ok': True, 'tables': tables})

# ── Endpoint 7: GET /api/health ───────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    with _store_lock:
        n_tables = len(_tables)
        n_cmds   = sum(1 for c in _command_queue.values() if c and c.get('status') == 'pending')

    # Buffer state
    try:
        from buffer import get_latest_snapshot, get_latest_seq, get_snapshot_age
        snap = get_latest_snapshot()
        buffer_has_data = snap is not None
        # Handle new frame format: {'data': ..., 'seq': ..., 'ts': ...}
        if snap and isinstance(snap, dict) and 'data' in snap:
            buffer_table = snap.get('data', {}).get('table_id', '?')
        else:
            buffer_table = snap.get('table_id', '?') if snap else None
        snapshot_seq = get_latest_seq()
        snapshot_age = get_snapshot_age()
        snapshot_age_seconds = round(snapshot_age, 2) if snapshot_age is not None else None
    except Exception:
        buffer_has_data = False
        buffer_table = None
        snapshot_seq = 0
        snapshot_age_seconds = None

    # CDP status — try to reach Vivaldi CDP on port 9222
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=2) as resp:
            cdp_status = 'reachable' if resp.status == 200 else 'unreachable'
    except Exception:
        cdp_status = 'unreachable'

    return jsonify({
        'ok':              True,
        'status':          'healthy',
        'environment':     os.getenv('FLASK_ENV', 'production'),
        'version':         'remote-control-3.0',
        'pid':             os.getpid(),
        'uptime_seconds':  round(time.time() - START_TIME, 2),
        'timestamp':       datetime.utcnow().isoformat(),
        'active_tables':   n_tables,
        'pending_cmds':    n_cmds,
        'buffer_has_data': buffer_has_data,
        'buffer_table':    buffer_table,
        'snapshot_age_seconds': snapshot_age_seconds,
        'snapshot_seq':    snapshot_seq,
        'cdp_status':      cdp_status,
    })


@app.route('/api/heartbeat', methods=['GET'])
def heartbeat():
    """Lightweight health gate for verifier agents.

    Returns 200 if snapshot is fresh (<30s old), 503 if stale or missing.
    Sets X-Health header: 'ok' or 'degraded'.
    """
    try:
        from buffer import get_snapshot_age
        age = get_snapshot_age()
    except Exception:
        age = None

    if age is not None and age < 30.0:
        resp = make_response(jsonify({'ok': True, 'status': 'alive'}))
        resp.status_code = 200
        resp.headers['X-Health'] = 'ok'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    else:
        resp = make_response(jsonify({
            'ok': False,
            'status': 'degraded',
            'snapshot_age_seconds': round(age, 2) if age is not None else None,
            'reason': 'snapshot stale' if age is not None else 'no snapshot yet',
        }))
        resp.status_code = 503
        resp.headers['X-Health'] = 'degraded'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp


@app.route('/api/bots', methods=['GET'])
def get_bots():
    """
    Return all known bots with their seating status.
    Used by Bots Manager page.
    """
    with _store_lock:
        bots = []

        # Add all bots that have sent snapshots
        for bot_id, info in _bot_seats.items():
            last_seen_ago = time.time() - info["last_seen"]
            state = "running" if last_seen_ago < 30 else "stale"

            seat = info.get("seat_no", info.get("seat_index"))
            bots.append({
                "name": bot_id,
                "table_id": info["table_id"],
                "seat_index": seat,
                "last_seen": info["last_seen"],
                "last_seen_ago": last_seen_ago,
                "state": state,
                "status": f"Seated at {info['table_id']} seat {seat}"
            })

        # Add known containers that haven't sent snapshots yet
        for i in range(1, 10):
            bot_id = f"pokerbet-bot{i}"
            if bot_id not in _bot_seats:
                bots.append({
                    "name": bot_id,
                    "table_id": None,
                    "seat_index": None,
                    "last_seen": None,
                    "last_seen_ago": None,
                    "state": "unknown",
                    "status": "Not seated or not running"
                })

    return jsonify({"ok": True, "bots": bots})


@app.route('/api/bot/deploy', methods=['POST'])
def bot_deploy():
    """
    Deploy bots via VPASS workflow.
    Request body:
    {
        "username": "pokerbet_username",
        "password": "pokerbet_password",
        "table_name": "TARGET TABLE NAME",
        "buy_in_mode": "MIN" | "MAX" | "CUSTOM",
        "buy_in_amount": 123.45 (if CUSTOM),
        "auto_buyin_enabled": true/false,
        "first_action_policy": "CHECK_OR_CALL_ONCE" | null,
        "bot_count": 1-9,
        "mode": "SEATING_ONLY"
    }
    """
    try:
        req = request.get_json()
        if not req:
            return jsonify({'ok': False, 'error': 'Missing request body'}), 400
        
        # Call bot deployment system
        result = bot_deployment.deploy_bots(req)
        
        if result['ok']:
            app.logger.info(f"[BOT_DEPLOY] Started deployment: {result['deployment_id']}")
            return jsonify(result), 200
        else:
            app.logger.error(f"[BOT_DEPLOY] Validation failed: {result.get('error')}")
            return jsonify(result), 400
            
    except Exception as e:
        app.logger.error(f"[BOT_DEPLOY] Exception: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/bot/status/<deployment_id>', methods=['GET'])
@login_required
def bot_deployment_status(deployment_id):
    """Get deployment status"""
    try:
        status = bot_deployment.get_deployment_status(deployment_id)
        if status:
            return jsonify({'ok': True, 'deployment': status}), 200
        else:
            return jsonify({'ok': False, 'error': 'Deployment not found'}), 404
    except Exception as e:
        app.logger.error(f"[BOT_STATUS] Exception: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# Add this after the /api/health endpoint (around line 480)

@app.route('/api/status', methods=['GET'])
def status():
    """Detailed status endpoint with metrics"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        uptime_seconds = time.time() - process.create_time()
    except Exception:
        memory_mb = 0
        uptime_seconds = 0
    
    with _store_lock:
        table_count = len(_tables)
        command_queue_size = sum(1 for c in _command_queue.values() if c and c.get('status') == 'pending')
        # Count total seats across all tables
        total_seats = sum(len(t.get('seats', {})) for t in _tables.values())
    
    return jsonify({
        'service': 'remote-control-api',
        'status': 'healthy',
        'version': 'remote-control-3.0',
        'uptime_seconds': uptime_seconds,
        'timestamp': time.time(),
        'memory_mb': round(memory_mb, 2),
        'table_count': table_count,
        'seat_count': total_seats,
        'command_queue_size': command_queue_size,
        'warning_count': 0,
        'error_count': 0,
        'warnings': [],
        'errors': []
    })


@app.route('/api/version', methods=['GET'])
def version():
    """Version endpoint"""
    return jsonify({
        'service': 'remote-control-api',
        'version': 'remote-control-3.0',
        'build': os.getenv('FLASK_ENV', 'production'),
        'timestamp': time.time()
    })
# ██  HAND HISTORY (multi-hand ASCII log)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/hands/recent', methods=['GET'])
def hands_recent():
    """Return last N hands as ASCII text blocks.
    Each hand: hole cards, flop, turn, river (one line per street, cards only).
    Hands separated by '------------------------'."""
    limit = min(int(request.args.get('limit', 20)), HAND_HISTORY_MAX)
    with _hand_lock:
        hands = list(_hand_history[-limit:])
    return jsonify({
        'ok': True,
        'hands': hands,
        'count': len(hands),
    })


@app.route('/api/hands/clear', methods=['POST'])
def hands_clear():
    """Clear hand history."""
    with _hand_lock:
        _hand_history.clear()
    return jsonify({'ok': True})


# ██  HAND COLLECTOR
# ══════════════════════════════════════════════════════════════════════════════

VALIDATED_HANDS_DIR = Path(os.path.join(os.path.dirname(__file__), 'data', 'validated_hands'))
VALIDATED_HANDS_DIR.mkdir(parents=True, exist_ok=True)
_COLLECTOR_HTML     = Path(os.path.join(os.path.dirname(__file__), 'data', 'hand-collector', 'index.html'))
_COLLECTOR_SAVE_DIR = Path(os.path.join(os.path.dirname(__file__), 'data', 'hand-collector', 'saved_hands'))
_COLLECTOR_SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ── Collector hand accumulator ──────────────────────────────────────────────
# Accumulates unique hands across snapshots within a deal window.
# Each snapshot from n4p.js may only contain currently-visible hands (1-3),
# so we merge them into one complete batch.
import threading as _coll_threading, time as _coll_time
_coll_lock = _coll_threading.Lock()
_coll_accumulated_hands = []   # ordered unique hands
_coll_board = None             # latest board string
_coll_last_update = 0          # epoch of last snapshot
_coll_source = ''              # last writer identity
_COLL_WINDOW_SECONDS = 10      # reset accumulator after this idle gap
_coll_last_written = ""        # content hash for write gate
_coll_deal_file = None         # Path to current deal file (overwrite mode)


@app.route('/collector')
@app.route('/collector/')
def collector_ui():
    if _COLLECTOR_HTML.exists():
        return send_file(str(_COLLECTOR_HTML), mimetype='text/html')
    return '<h2>Hand Collector UI not found at ' + str(_COLLECTOR_HTML) + '</h2>', 404


@app.route('/collector/save', methods=['POST'])
def collector_save():
    global _coll_accumulated_hands, _coll_board, _coll_last_update, _coll_last_written, _coll_deal_file, _coll_source
    try:
        body = request.get_json(force=True) or {}
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    raw_text = (body.get('text') or '').strip()
    if not raw_text:
        return jsonify({'error': 'Empty text'}), 400

    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    if not lines:
        return jsonify({'error': 'Empty text'}), 400

    # Separate hands from board — BOARD: tag is the required protocol
    incoming_hands = []
    incoming_board = None
    source = (body.get('source') or '').strip()
    if source == 'w4p-dom-survey' or lines[0] == 'DOM_SURVEY':
        app.logger.info('[COLLECTOR] ignored DOM survey payload (source=%s)', source or 'unknown')
        return jsonify({'ok': True, 'dup': True, 'skipped': 'dom_survey'}), 200
    tagged = [l for l in lines if l.startswith('BOARD:')]
    if tagged:
        board_str = tagged[0][6:]  # strip 'BOARD:' prefix
        # Validate board: must be even-length card string (6, 8, or 10 chars)
        board_cards = _parse_card_tokens(board_str, 3, 5)
        if board_cards:
            incoming_board = ''.join(board_cards)
        else:
            app.logger.warning('[COLLECTOR] invalid board length %d: %s', len(board_str), board_str[:20])
        lines = [l for l in lines if not l.startswith('BOARD:')]
        incoming_hands = list(lines)
    else:
        # No BOARD: tag — all lines are hands, no board guessing
        app.logger.warning('[COLLECTOR] untagged payload (%d lines, source=%s) — board will not be extracted', len(lines), source or 'unknown')
        incoming_hands = list(lines)

    valid_hands = []
    valid_seen = set()
    for hand in incoming_hands:
        cards = _parse_card_tokens(hand, 4, 7)
        if not cards:
            continue
        clean_hand = ''.join(cards)
        key = clean_hand.lower()
        if key in valid_seen:
            continue
        valid_seen.add(key)
        valid_hands.append(clean_hand)
    incoming_hands = valid_hands
    if not incoming_hands and not incoming_board:
        app.logger.warning('[COLLECTOR] rejected non-card payload (%d lines, source=%s)', len(lines), source or 'unknown')
        return jsonify({'ok': True, 'dup': True, 'skipped': 'invalid_payload'}), 200

    now = _coll_time.time()
    dup = False

    with _coll_lock:
        # Reset accumulator if idle gap exceeded (new deal)
        gap = now - _coll_last_update
        app.logger.info("[RESET-CHECK] gap=%.2f, threshold=%d, will_reset=%s", gap, _COLL_WINDOW_SECONDS, gap > _COLL_WINDOW_SECONDS)
        if now - _coll_last_update > _COLL_WINDOW_SECONDS:
            _coll_accumulated_hands = []
            _coll_board = None
            _coll_last_written = ""
            _coll_deal_file = None
            app.logger.info("[RESET] Cleared all state due to idle gap")

        _coll_last_update = now

        # Reject degraded snapshots: fewer hands than accumulated
        if _coll_accumulated_hands and len(incoming_hands) < len(_coll_accumulated_hands):
            return jsonify({'ok': True, 'dup': True, 'skipped': 'degraded_snapshot'}), 200

        # Detect deal change: overlapping cards = different deals
        # Skip overlap check if hands are identical (exact same snapshot)
        if _coll_accumulated_hands and incoming_hands and set(incoming_hands) != set(_coll_accumulated_hands):
            acc_cards = set()
            for h in _coll_accumulated_hands:
                for i in range(0, len(h) - 1, 2):
                    acc_cards.add(h[i:i+2].lower())
            has_overlap = False
            for h in incoming_hands:
                for i in range(0, len(h) - 1, 2):
                    if h[i:i+2].lower() in acc_cards:
                        has_overlap = True
                        break
                if has_overlap:
                    break
            if has_overlap:
                if len(incoming_hands) >= len(_coll_accumulated_hands):
                    # Incoming is larger or equal = new deal, replace accumulator
                    # BUT keep _coll_deal_file so we overwrite the same file
                    _coll_accumulated_hands = []
                    _coll_board = None
                    _coll_last_written = ""
                    # Note: Do NOT reset _coll_deal_file here - keep same file
                else:
                    # Accumulated is larger = incoming is stale, skip hands
                    # But still clear board if scraper reports no board (preflop/new deal)
                    if incoming_board is None:
                        _coll_board = None
                    return jsonify({'ok': True, 'dup': True, 'skipped': 'stale_batch'}), 200

        # Reject degraded snapshots: do not replace fuller set with smaller one
        if _coll_accumulated_hands and incoming_hands and len(incoming_hands) < len(_coll_accumulated_hands):
            return jsonify({'ok': True, 'dup': True, 'skipped': 'degraded_snapshot'}), 200

        # Accumulate unique hands (preserve order)
        before_count = len(_coll_accumulated_hands)
        existing_set = set(_coll_accumulated_hands)
        for hand in incoming_hands:
            if hand not in existing_set:
                _coll_accumulated_hands.append(hand)
                existing_set.add(hand)

        # Update board: set if present, clear if scraper reports no board
        if incoming_board:
            _coll_board = incoming_board
        else:
            _coll_board = None

        # Track writer source
        _coll_source = source

        dup = (len(_coll_accumulated_hands) == before_count and
               (incoming_board is None or incoming_board == _coll_board))

        # Build accumulated payload
        out_lines = list(_coll_accumulated_hands)
        if _coll_board:
            out_lines.append('BOARD:' + _coll_board)
        payload = '\n'.join(out_lines)

    # Write accumulated batch to disk (gated: only if content changed)
    app.logger.info("[DEDUP] payload len=%d, last_written len=%d, match=%s", len(payload), len(_coll_last_written), payload == _coll_last_written)
    if payload != _coll_last_written:
        if _coll_deal_file is None:
            ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
            _coll_deal_file = _COLLECTOR_SAVE_DIR / f'hand_{ts}.txt'
        _coll_deal_file.write_text(payload + '\n', encoding='utf-8')
        _coll_last_written = payload
        return jsonify({'ok': True, 'file': str(_coll_deal_file), 'dup': False}), 200
    else:
        return jsonify({'ok': True, 'file': str(_coll_deal_file) if _coll_deal_file else '', 'dup': True}), 200


@app.route("/collector/clear", methods=["POST"])
def collector_clear():
    """Reset the hand accumulator between dealing rounds."""
    global _coll_accumulated_hands, _coll_board, _coll_last_update, _coll_last_written, _coll_deal_file, _coll_source
    with _coll_lock:
        _coll_accumulated_hands = []
        _coll_board = None
        _coll_last_update = 0
        _coll_source = ''

    # Purge saved hand files so /api/collector/latest does not resurrect stale data
    purged = 0
    for f in _COLLECTOR_SAVE_DIR.glob("*.txt"):
        try:
            f.unlink()
            purged += 1
        except OSError:
            pass

    return jsonify({"ok": True, "message": f"Accumulator cleared, {purged} files purged"}), 200


@app.route('/collector/meta', methods=['GET'])
def collector_meta():
    return jsonify({'save_dir': str(_COLLECTOR_SAVE_DIR)}), 200



@app.route('/api/remote/status', methods=['GET'])
def remote_status():
    """Detailed remote control status with command queue and seat details"""
    now = time.time()
    
    with _store_lock:
        # Build command queue details
        command_details = []
        for token, cmd in _command_queue.items():
            if cmd and cmd.get('status') == 'pending':
                command_details.append({
                    'seat_token': token,
                    'command': cmd.get('command'),
                    'status': cmd.get('status'),
                    'queued_at': cmd.get('queued_at'),
                    'age_seconds': round(now - cmd.get('queued_at', now), 1) if cmd.get('queued_at') else 0,
                })
        
        # Sort by most recent
        command_details.sort(key=lambda c: c.get('queued_at', 0), reverse=True)
        
        # Build table details with seat info
        table_details = []
        for (table_id, bot_id), table in _tables.items():
            seats_info = []
            for seat_no, seat in table.get('seats', {}).items():
                seat_token = seat.get('token', '')
                pending_cmd = _command_queue.get(seat_token)
                
                seats_info.append({
                    'seat_no': seat_no,
                    'name': seat.get('name'),
                    'stack_zar': seat.get('stack_zar', 0),
                    'status': seat.get('status', 'empty'),
                    'is_hero': seat.get('is_hero', False),
                    'is_dealer': seat.get('is_dealer', False),
                    'has_token': bool(seat_token),
                    'pending_command': pending_cmd.get('command') if pending_cmd and pending_cmd.get('status') == 'pending' else None,
                })
            
            table_details.append({
                'table_id': table_id,
                'last_update': table.get('last_ts'),
                'age_seconds': round(now - table.get('last_ts', now), 1),
                'street': table.get('street', 'UNKNOWN'),
                'pot_zar': table.get('pot_zar', 0),
                'seat_count': len(table.get('seats', {})),
                'active_seats': sum(1 for s in seats_info if s['name'] or s['stack_zar'] > 0),
                'seats': seats_info,
            })
        
        # Sort tables by most recent activity
        table_details.sort(key=lambda t: t.get('last_update', 0), reverse=True)
        
        # Calculate stats
        total_tables = len(_tables)
        total_seats = sum(len(t.get('seats', {})) for t in _tables.values())
        active_commands = len(command_details)
        
    return jsonify({
        'service': 'remote-control',
        'status': 'healthy',
        'timestamp': now,
        'total_tables': total_tables,
        'total_seats': total_seats,
        'active_commands': active_commands,
        'commands': command_details[:20],  # Top 20 most recent
        'tables': table_details[:10],  # Top 10 most active tables with full details
    })

@app.route('/api/engine/status', methods=['GET'])
def engine_status():
    """Engine status endpoint - checks if equity engine is accessible"""
    engine_url = os.getenv('ENGINE_URL', 'http://127.0.0.1:5002')
    try:
        import requests
        response = requests.get(f'{engine_url}/api/health', timeout=2)
        if response.status_code == 200:
            engine_data = response.json()
            return jsonify({
                'service': 'equity-engine',
                'status': 'healthy',
                'engine_url': engine_url,
                'version': engine_data.get('version', 'unknown'),
                'timestamp': time.time(),
            })
        else:
            return jsonify({
                'service': 'equity-engine',
                'status': 'degraded',
                'engine_url': engine_url,
                'error': f'HTTP {response.status_code}',
                'timestamp': time.time(),
            })
    except Exception as e:
        return jsonify({
            'service': 'equity-engine',
            'status': 'offline',
            'engine_url': engine_url,
            'error': str(e),
            'timestamp': time.time(),
        })


@app.route('/api/collector/status', methods=['GET'])
def collector_status():
    """Collector/snapshot status endpoint with table activity metrics"""
    with _store_lock:
        tables_data = []
        now = time.time()
        
        for (table_id, bot_id), table in _tables.items():
            last_update = table.get('last_ts', 0)
            age_seconds = now - last_update if last_update else 0
            
            # Count active (non-empty) seats
            active_seats = sum(1 for seat in table.get('seats', {}).values() 
                             if seat.get('name') or seat.get('stack_zar', 0) > 0)
            
            tables_data.append({
                'table_id': table_id,
                'bot_id': bot_id,
                'last_update': last_update,
                'age_seconds': round(age_seconds, 1),
                'street': table.get('street', 'UNKNOWN'),
                'seat_count': len(table.get('seats', {})),
                'active_seats': active_seats,
                'hand_key': table.get('hand_key', ''),
            })
        
        # Sort by most recent activity
        tables_data.sort(key=lambda t: t['last_update'], reverse=True)
        
        # Calculate overall stats
        total_tables = len(_tables)
        total_seats = sum(len(t.get('seats', {})) for t in _tables.values())
        active_tables = sum(1 for t in tables_data if t['age_seconds'] < 30)
        
    return jsonify({
        'service': 'collector',
        'status': 'healthy',
        'timestamp': now,
        'total_tables': total_tables,
        'active_tables': active_tables,  # Updated in last 30s
        'total_seats': total_seats,
        'tables': tables_data[:20],  # Return top 20 most recent
        'state_file': str(STATE_FILE),
    })
@app.route("/api/collector/latest", methods=["GET"])
def collector_latest():
    """Serve hands directly from in-memory accumulator (not files)."""
    global _coll_accumulated_hands, _coll_board
    import time as _time

    with _coll_lock:
        valid_hands = []
        valid_seen = set()
        for hand in _coll_accumulated_hands:
            cards = _parse_card_tokens(hand, 4, 7)
            if not cards:
                continue
            clean_hand = ''.join(cards)
            key = clean_hand.lower()
            if key in valid_seen:
                continue
            valid_seen.add(key)
            valid_hands.append(clean_hand)
        if len(valid_hands) != len(_coll_accumulated_hands):
            app.logger.warning('[COLLECTOR] filtered %d non-card memory lines', len(_coll_accumulated_hands) - len(valid_hands))
            _coll_accumulated_hands = valid_hands
        if _coll_board and not _parse_card_tokens(_coll_board, 3, 5):
            app.logger.warning('[COLLECTOR] cleared invalid board from memory: %s', str(_coll_board)[:20])
            _coll_board = None

        if not _coll_accumulated_hands:
            app.logger.info('[COLLECTOR] no_fresh_snapshot: accumulator empty')
            resp = make_response(jsonify({'ok': False, 'reason': 'no_fresh_snapshot'}), 200)
            resp.headers['X-Collector-Handler'] = 'patched-v1-empty'
            return resp

        # Stale data — no fresh snapshot within window
        if _coll_last_update and (_time.time() - _coll_last_update > 60):
            age = round(_time.time() - _coll_last_update)
            app.logger.info('[COLLECTOR] stale_snapshot: age=%ds', age)
            resp = make_response(jsonify({'ok': False, 'reason': 'stale_snapshot', 'age': age}), 200)
            resp.headers['X-Collector-Handler'] = 'patched-v1-stale'
            return resp

        out_lines = list(_coll_accumulated_hands)
        board = _coll_board

    raw_text = chr(10).join(out_lines)

    app.logger.info('[COLLECTOR] success: %d hands, board=%s, source=%s', len(out_lines), bool(board), _coll_source)
    resp = make_response(jsonify({'ok': True, 'raw': raw_text, 'board': board,
                    'hands': len(out_lines), 'source': _coll_source or 'unknown'}), 200)
    resp.headers['X-Collector-Handler'] = 'patched-v1-success'
    return resp

# ══════════════════════════════════════════════════════════════════════════════
# ██  CASHOUT
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/cashout/request', methods=['POST'])
def request_cashout():
    payload = request.get_json()
    if not payload:
        return jsonify({'ok': False, 'error': 'No payload'}), 400

    table_id = payload.get('table_id')
    seat_no  = payload.get('seat_no') or payload.get('seat_index')
    if not all([table_id, seat_no is not None]):
        return jsonify({'ok': False, 'error': 'Missing table_id or seat_no'}), 400

    token = generate_seat_token(table_id, seat_no)

    with _store_lock:
        if token not in _cashout_state:
            _cashout_state[token] = {'requested': False, 'available': False}
        _cashout_state[token]['requested'] = True

    app.logger.info(f"[CASHOUT] Request queued table={table_id} seat_no={seat_no}")
    return jsonify({'ok': True, 'status': 'queued', 'seat_token': token})


@app.route('/api/cashout/status', methods=['GET'])
def cashout_status():
    token = request.args.get('token')
    if not token:
        return jsonify({'ok': False, 'error': 'Missing token'}), 400

    with _store_lock:
        state = _cashout_state.get(token, {'requested': False, 'available': False})

    return jsonify({'ok': True, 'state': state})



# ══════════════════════════════════════════════════════════════════════════════
# ██  AUTHENTICATION & AUTHORIZATION
# ══════════════════════════════════════════════════════════════════════════════

from flask_login import login_user, logout_user

@app.route('/login')
def login_page():
    return send_from_directory("static", "login.html")

@app.route('/change-password')
@login_required
def change_password_page():
    return send_from_directory("static", "change-password.html")


@app.route("/player-manager")
@login_required
def player_manager():
    """Player credentials management interface"""
    return send_from_directory("static", "player-manager.html")
@app.route('/api/auth/login', methods=['POST'])
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Username and password required'}), 400

    user = User.authenticate(username, password)

    if not user:
        audit_logs.log_login_failed(username,
                         ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'))
        return jsonify({'ok': False, 'error': 'Invalid credentials'}), 401

    if not user.is_active:
        audit_logs.log_login_failed(user.username,
                         ip_address=request.remote_addr)
        return jsonify({'ok': False, 'error': 'Account inactive'}), 403

    login_user(user, remember=data.get('remember', False))
    audit_logs.log_login_success(user.username, user_id=user.id,
                     ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT must_change_password FROM users WHERE id = ?', (user.id,))
    row = cursor.fetchone()
    must_change = row[0] if row else 0
    conn.close()

    token = secrets.token_hex(32)
    session['auth_token'] = token
    session['auth_username'] = user.username

    return jsonify({
        'ok': True,
        'token': token,
        'username': user.username,
        'user': {'id': user.id, 'username': user.username, 'role': user.role},
        'must_change_password': bool(must_change),
        'redirect': '/change-password' if must_change else '/shell'
    }), 200



@app.route('/api/auth/verify', methods=['GET'])
def api_auth_verify():
    """Verify the current session is valid (used by engine frontend)"""
    # First try Flask-Login session cookie
    if current_user.is_authenticated:
        user = current_user
        return jsonify({
            'ok': True,
            'username': user.username,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role
            }
        })
    
    # Fallback: check X-Auth-Token header against session-stored token
    token = request.headers.get('X-Auth-Token', '')
    session_token = session.get('auth_token', '')
    username = session.get('auth_username', '')
    
    if token and session_token and token == session_token:
        from auth_models import User
        user = User.get_by_username(username)
        if user:
            return jsonify({
                'ok': True,
                'username': user[0].username,
                'user': {
                    'id': user[0].id,
                    'username': user[0].username,
                    'role': user[0].role
                }
            })
    
    return jsonify({'ok': False, 'error': 'Not authenticated'}), 401

@app.route('/api/auth/logout', methods=['POST'])
@app.route('/api/logout', methods=['POST'])
@login_required
def api_logout():
    audit_logs.log_logout(current_user.username, user_id=current_user.id,
                     ip_address=request.remote_addr)
    logout_user()
    return jsonify({'ok': True}), 200

@app.route('/api/auth/me', methods=['GET'])
@login_required
def api_me():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT must_change_password FROM users WHERE id = ?', (current_user.id,))
    row = cursor.fetchone()
    must_change = row[0] if row else 0
    conn.close()

    return jsonify({
        'ok': True,
        'user': {
            'id': current_user.id,
            'username': current_user.username,
            'role': current_user.role,
            'must_change_password': bool(must_change)
        }
    }), 200

@app.route('/api/auth/change-password', methods=['POST'])
@login_required
def api_change_password():
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400

    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({'ok': False, 'error': 'Both passwords required'}), 400

    if len(new_password) < 4:
        return jsonify({'ok': False, 'error': 'Password must be at least 4 characters'}), 400

    user, password_hash = User.get_by_username(current_user.username)
    if not check_password_hash(password_hash, current_password):
        log_user_activity(current_user.id, current_user.username, 'password_change_failed',
                         status='failure', ip_address=request.remote_addr,
                         details='incorrect current password')
        return jsonify({'ok': False, 'error': 'Current password incorrect'}), 401

    new_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                  (new_hash, current_user.id))
    conn.commit()
    conn.close()

    log_user_activity(current_user.id, current_user.username, 'password_changed',
                     status='success', ip_address=request.remote_addr)

    return jsonify({'ok': True, 'message': 'Password changed successfully'}), 200



# ── Player Management API ──────────────────────────────────────────────────────

import sqlite3

PLAYERS_DB = '/home/wa/REMOTEREMOTE/data/players.db'

def _get_players_db():
    conn = sqlite3.connect(PLAYERS_DB)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/players', methods=['GET'])
def get_players():
    """Get all active players with their EIP mapping."""
    conn = _get_players_db()
    rows = conn.execute(
        'SELECT id, username, container_name, docker_ip, eni, eip, active FROM players ORDER BY id'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/players/<username>', methods=['GET'])
def get_player(username):
    """Get a specific player's credentials and config."""
    conn = _get_players_db()
    row = conn.execute(
        'SELECT id, username, password, container_name, docker_ip, eni, eip, active FROM players WHERE username = ?',
        (username,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Player not found'}), 404
    return jsonify(dict(row))

@app.route('/api/players', methods=['POST'])
def add_player():
    """Add a new player. JSON body: {username, password, container_name, docker_ip, eni, eip}"""
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'username and password required'}), 400
    conn = _get_players_db()
    try:
        conn.execute(
            '''INSERT INTO players (username, password, container_name, docker_ip, eni, eip, active)
               VALUES (?, ?, ?, ?, ?, ?, 1)''',
            (data['username'], data['password'], data.get('container_name'),
             data.get('docker_ip'), data.get('eni'), data.get('eip'))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Player already exists'}), 409
    conn.close()
    return jsonify({'status': 'created', 'username': data['username']}), 201

@app.route('/api/players/<username>', methods=['PUT'])
def update_player(username):
    """Update a player. JSON body with fields to update."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    conn = _get_players_db()
    allowed = ['password', 'container_name', 'docker_ip', 'eni', 'eip', 'active']
    sets = []
    vals = []
    for k in allowed:
        if k in data:
            sets.append(f'{k} = ?')
            vals.append(data[k])
    if not sets:
        conn.close()
        return jsonify({'error': 'No valid fields to update'}), 400
    sets.append('updated_at = CURRENT_TIMESTAMP')
    vals.append(username)
    conn.execute(f"UPDATE players SET {', '.join(sets)} WHERE username = ?", vals)
    conn.commit()
    conn.close()
    return jsonify({'status': 'updated', 'username': username})


# ── Startup ────────────────────────────────────────────────────────────────────

def _start_background_threads():
    for target, name in [
        (_persist_loop,  'state-persist'),
        (_cleanup_loop,  'seat-cleanup'),
    ]:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        app.logger.info(f"[STARTUP] Background thread started: {name}")


# Load persisted state before accepting requests
_load_state()
_start_background_threads()


# ══════════════════════════════════════════════════════════════════════════════
# ██  BATCH PARSER — table snapshot → players + board
# ══════════════════════════════════════════════════════════════════════════════

import re as _re
_CARD_RE = _re.compile(r'^([AKQJT2-9][shdc])+$')

def _valid_cards(line):
    """Check line is valid concatenated card tokens, even length, no dupes."""
    if not line or len(line) % 2 != 0 or len(line) < 6:
        return False
    if not _CARD_RE.match(line):
        return False
    cards = [line[i:i+2] for i in range(0, len(line), 2)]
    if len(cards) != len(set(cards)):
        return False  # duplicate card
    return True

def _parse_batch(lines):
    """Parse a batch of lines into players + board."""
    clean = []
    for l in lines:
        n = l.strip().replace(' ', '')
        if '|' in n:
            n = n.split('|')[0]  # strip legacy board
        if n and _valid_cards(n):
            clean.append(n)

    # Step 1: lock players (first <=9 lines of 8 chars)
    players = []
    leftovers = []
    for line in clean:
        if len(line) == 8 and len(players) < 9:
            players.append(line)
        else:
            leftovers.append(line)

    # Step 2: board candidates from leftovers
    # Collect all player cards for overlap check
    player_cards = set()
    for p in players:
        for i in range(0, len(p), 2):
            player_cards.add(p[i:i+2])

    # Filter candidates: valid, no overlap with players
    candidates = []
    for line in leftovers:
        if len(line) not in (6, 8, 10):
            continue
        board_cards = [line[i:i+2] for i in range(0, len(line), 2)]
        if any(c in player_cards for c in board_cards):
            continue  # overlap
        candidates.append(line)

    # Step 3: check prefix consistency, pick longest
    board = None
    if candidates:
        candidates.sort(key=len, reverse=True)
        for c in candidates:
            # verify shorter candidates are prefixes
            consistent = True
            for other in candidates:
                if len(other) < len(c) and c[:len(other)] != other:
                    consistent = False
                    break
            if consistent:
                board = c
                break
        if not board:
            board = candidates[0]  # fallback: longest

    # Step 4: derive streets
    flop = turn = river = None
    if board:
        if len(board) >= 6:
            flop = board[:6]
        if len(board) >= 8:
            turn = board[6:8]
        if len(board) == 10:
            river = board[8:10]

    return {
        'players': players,
        'player_count': len(players),
        'flop': flop,
        'turn': turn,
        'river': river,
        'board_raw': board,
        'partial': len(players) < 6,
    }

@app.route('/api/parse/batch', methods=['POST'])
def api_parse_batch():
    """Parse raw collector text into structured table snapshot."""
    body = request.get_json(force=True) or {}
    text = (body.get('text') or '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'empty'}), 400

    batches_raw = text.split('\n\n')
    results = []
    for batch_text in batches_raw:
        lines = [l for l in batch_text.strip().split('\n') if l.strip()]
        if lines:
            results.append(_parse_batch(lines))

    return jsonify({'ok': True, 'batches': results, 'count': len(results)}), 200

# ── Run ────────────────────────────────────────────────────────────────────────


# GoldRush API Routes (proper paths /api/goldrush/*)
@app.route("/api/goldrush/save", methods=["POST", "OPTIONS"])
def api_goldrush_save():
    """Save GoldRush batch - mirrors /api/collector/save"""
    if request.method == "OPTIONS":
        return "", 204
    
    data = request.get_json()
    text = data.get("text", "").strip()
    
    if not text:
        return jsonify({"ok": False, "error": "empty text"}), 400
    
    # Save to goldrush directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"goldrush_{ts}.txt"
    save_dir = "/home/wa/REMOTEREMOTE/data/goldrush-collector/saved_hands"
    os.makedirs(save_dir, exist_ok=True)
    filepath = os.path.join(save_dir, filename)
    
    # Check for duplicate
    duplicate = False
    files = sorted([f for f in os.listdir(save_dir) if f.endswith(".txt")])
    if files:
        last_file = os.path.join(save_dir, files[-1])
        with open(last_file, "r") as f:
            if f.read().strip() == text:
                duplicate = True
    
    if not duplicate:
        with open(filepath, "w") as f:
            f.write(text)
        app.logger.info(f"[GoldRush] Saved: {filename}")
    
    return jsonify({"ok": True, "file": filepath, "dup": duplicate, "timestamp": ts})

@app.route("/api/goldrush/latest", methods=["GET"])
def api_goldrush_latest():
    """Get latest GoldRush batch - mirrors /api/collector/latest"""
    try:
        save_dir = "/home/wa/REMOTEREMOTE/data/goldrush-collector/saved_hands"
        os.makedirs(save_dir, exist_ok=True)
        
        files = sorted([f for f in os.listdir(save_dir) if f.startswith("goldrush_") and f.endswith(".txt")])
        
        if not files:
            return jsonify({"ok": True, "raw": None, "file": None})
        
        latest_file = os.path.join(save_dir, files[-1])
        with open(latest_file, "r") as f:
            raw_batch = f.read()
        
        return jsonify({
            "ok": True,
            "raw": raw_batch,
            "file": latest_file,
            "timestamp": files[-1].replace("goldrush_", "").replace(".txt", "")
        })
    
    except Exception as e:
        app.logger.error(f"[GoldRush] Error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '4000')), debug=False)


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEMD SERVICE — recommended settings (P1 + P3 fixes)
# Update /etc/systemd/system/plo-equity.service:
#
# [Unit]
# Description=PLO Remote Table Control v3
# After=network.target
#
# [Service]
# User=plo
# WorkingDirectory=/opt/plo-equity
# EnvironmentFile=/opt/plo-equity/.env
# ExecStart=/opt/plo-equity/venv/bin/gunicorn \
#     -w 3 \
#     --timeout 60 \
#     --worker-class sync \
#     --bind 0.0.0.0:8080 \
#     app:app
# Restart=on-failure
# RestartSec=5
# StartLimitBurst=5
# StartLimitIntervalSec=60
# StandardOutput=journal
# StandardError=journal
#
# [Install]
# WantedBy=multi-user.target
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Poker Tables CRUD API (poker_tables database)
# ══════════════════════════════════════════════════════════════════════════════

def _get_poker_tables_db():
    """Get connection to poker_tables database"""
    conn = sqlite3.connect(PLAYERS_DB)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/poker-tables', methods=['GET'])
@login_required
def get_poker_tables():
    """List all poker tables from database. Optional query param: platform"""
    platform = request.args.get('platform')
    conn = _get_poker_tables_db()
    try:
        cursor = conn.cursor()
        if platform:
            cursor.execute("SELECT * FROM poker_tables WHERE platform = ? ORDER BY game_type, seats_total DESC, big_blind DESC", (platform,))
        else:
            cursor.execute("SELECT * FROM poker_tables ORDER BY platform, game_type, seats_total DESC, big_blind DESC")
        tables = [dict(row) for row in cursor.fetchall()]
        return jsonify({'ok': True, 'tables': tables})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/poker-tables/<int:table_id>', methods=['GET'])
@login_required
def get_poker_table(table_id):
    """Get single poker table"""
    conn = _get_poker_tables_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM poker_tables WHERE id = ?", (table_id,))
        table = cursor.fetchone()
        if table:
            return jsonify({'ok': True, 'table': dict(table)})
        else:
            return jsonify({'ok': False, 'error': 'Table not found'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/poker-tables', methods=['POST'])
@login_required
def create_poker_table():
    """Create new poker table"""
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400

    required = ['table_name', 'game_type', 'seats_total', 'small_blind', 'big_blind', 'stakes_display']
    for field in required:
        if field not in data:
            return jsonify({'ok': False, 'error': f'Missing field: {field}'}), 400

    conn = _get_poker_tables_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO poker_tables (table_name, game_type, seats_total, small_blind, big_blind, stakes_display, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data['table_name'],
            data['game_type'],
            data['seats_total'],
            data['small_blind'],
            data['big_blind'],
            data['stakes_display'],
            data.get('is_active', 1)
        ))
        conn.commit()
        return jsonify({'ok': True, 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'error': 'Table name already exists'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/poker-tables/<int:table_id>', methods=['PUT'])
@login_required
def update_poker_table(table_id):
    """Update poker table"""
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400

    conn = _get_poker_tables_db()
    try:
        cursor = conn.cursor()

        # Build UPDATE query dynamically
        allowed_fields = ['table_name', 'game_type', 'seats_total', 'small_blind', 'big_blind', 'stakes_display', 'is_active']
        updates = []
        values = []

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = ?")
                values.append(data[field])

        if not updates:
            return jsonify({'ok': False, 'error': 'No valid fields to update'}), 400

        # Add last_seen timestamp
        updates.append("last_seen = CURRENT_TIMESTAMP")
        values.append(table_id)

        query = f"UPDATE poker_tables SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({'ok': False, 'error': 'Table not found'}), 404

        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'error': 'Table name already exists'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/poker-tables/<int:table_id>', methods=['DELETE'])
@login_required
def delete_poker_table(table_id):
    """Delete poker table"""
    conn = _get_poker_tables_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM poker_tables WHERE id = ?", (table_id,))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({'ok': False, 'error': 'Table not found'}), 404

        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ═════════════════════════════════════════════════════════════════════════════
# TABLE SCRAPER API ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.route('/api/tables/scrape', methods=['POST'])
@login_required
def scrape_tables_endpoint():
    """
    Trigger a fresh scrape of available PLO6 tables from lobby.
    POST /api/tables/scrape
    Body (optional): {"headless": true}

    Returns:
        {
            "ok": true,
            "tables": [...],
            "count": 5,
            "database": {"inserted": 2, "updated": 3},
            "duration": 45.3
        }
    """
    try:
        data = request.get_json() or {}
        headless = data.get('headless', True)

        app.logger.info(f"[SCRAPER] Scrape triggered by {current_user.username}")

        # Import scraper module
        import table_scraper

        result = table_scraper.scrape_plo6_tables(headless=headless)

        if result["ok"]:
            app.logger.info(f"[SCRAPER] Success: {result['count']} tables found")
        else:
            app.logger.error(f"[SCRAPER] Failed: {result.get('error')}")

        return jsonify(result), 200 if result["ok"] else 500

    except Exception as e:
        app.logger.error(f"[SCRAPER] Exception: {e}")
        import traceback
        return jsonify({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route('/api/tables/available', methods=['GET'])
@login_required
def get_available_tables():
    """
    Get list of active PLO6 tables from database.
    GET /api/tables/available?game_type=PLO6

    Returns:
        {
            "ok": true,
            "count": 5,
            "tables": [
                {
                    "id": 1,
                    "table_name": "Algiers",
                    "game_type": "PLO6",
                    "seats_total": 6,
                    "small_blind": 5.0,
                    "big_blind": 10.0,
                    "stakes_display": "ZAR 5/10",
                    "is_active": true,
                    "last_seen": "2026-04-11T05:30:00"
                },
                ...
            ]
        }
    """
    try:
        game_type = request.args.get('game_type', 'PLO6')

        conn = _get_poker_tables_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                table_name,
                game_type,
                seats_total,
                small_blind,
                big_blind,
                stakes_display,
                is_active,
                scraped_at,
                last_seen
            FROM poker_tables
            WHERE is_active = 1 AND game_type = ?
            ORDER BY big_blind, small_blind
        """, (game_type,))

        tables = []
        for row in cursor.fetchall():
            tables.append({
                "id": row[0],
                "table_name": row[1],
                "game_type": row[2],
                "seats_total": row[3],
                "small_blind": float(row[4]),
                "big_blind": float(row[5]),
                "stakes_display": row[6],
                "is_active": bool(row[7]),
                "scraped_at": row[8],
                "last_seen": row[9]
            })

        conn.close()

        return jsonify({
            "ok": True,
            "count": len(tables),
            "tables": tables
        }), 200

    except Exception as e:
        app.logger.error(f"[TABLES] Failed to fetch: {e}")
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route('/api/tables/stats', methods=['GET'])
@login_required
def get_table_stats():
    """
    Get statistics about scraped tables.
    GET /api/tables/stats

    Returns:
        {
            "ok": true,
            "game_types": {
                "PLO6": {"total": 8, "active": 5},
                "PLO4": {"total": 12, "active": 10}
            },
            "last_scrape": "2026-04-11T05:30:00"
        }
    """
    try:
        conn = _get_poker_tables_db()
        cursor = conn.cursor()

        # Count by game type
        cursor.execute("""
            SELECT game_type, COUNT(*), SUM(is_active)
            FROM poker_tables
            GROUP BY game_type
        """)
        game_types = {}
        for row in cursor.fetchall():
            game_types[row[0]] = {
                "total": row[1],
                "active": row[2] or 0
            }

        # Last scrape time
        cursor.execute("""
            SELECT MAX(last_seen) FROM poker_tables
        """)
        last_scrape = cursor.fetchone()[0]

        conn.close()

        return jsonify({
            "ok": True,
            "game_types": game_types,
            "last_scrape": last_scrape
        }), 200

    except Exception as e:
        app.logger.error(f"[TABLES] Failed to fetch stats: {e}")
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

# ══════════════════════════════════════════════════════════════════════════════
# GoldRush API Extensions

from pathlib import Path
from datetime import datetime
import time

# GoldRush configuration
_COLLECTOR_SAVE_DIR_GOLDRUSH = Path(os.path.join(os.path.dirname(__file__), 'data', 'hand-collector', 'saved_hands_goldrush'))
_COLLECTOR_SAVE_DIR_GOLDRUSH.mkdir(parents=True, exist_ok=True)

# GoldRush table state (separate from PokerBet)
_tables_goldrush = {}

# GoldRush collector save endpoint
@app.route('/api/collector/save/goldrush', methods=['POST', 'OPTIONS'])
def collector_save_goldrush():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json(force=True)
        raw_batch = data.get('batch', '').strip()
        if not raw_batch:
            return jsonify({'ok': False, 'error': 'empty batch'}), 400
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f'goldrush_hand_{ts}.txt'
        filepath = _COLLECTOR_SAVE_DIR_GOLDRUSH / filename
        filepath.write_text(raw_batch, encoding='utf-8')
        app.logger.info(f'[GoldRush] Saved collector batch: {filename} ({len(raw_batch)} chars)')
        return jsonify({'ok': True, 'file': str(filepath), 'size': len(raw_batch)})
    except Exception as e:
        app.logger.error(f'[GoldRush] Collector save error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/collector/latest/goldrush', methods=['GET'])
def collector_latest_goldrush():
    try:
        candidates = list(_COLLECTOR_SAVE_DIR_GOLDRUSH.glob('goldrush_hand_*.txt'))
        if not candidates:
            return jsonify({'ok': False, 'error': 'no batches found'}), 404
        latest = max(candidates, key=lambda f: f.stat().st_mtime)
        raw_batch = latest.read_text(encoding='utf-8').strip()
        return jsonify({'ok': True, 'raw': raw_batch, 'file': str(latest), 'timestamp': latest.stat().st_mtime})
    except Exception as e:
        app.logger.error(f'[GoldRush] Collector latest error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/table/latest/goldrush', methods=['GET'])
def table_latest_goldrush():
    try:
        if not _tables_goldrush:
            return jsonify({'ok': False, 'error': 'no goldrush tables'}), 404
        latest_table_id = max(_tables_goldrush.keys(), key=lambda tid: _tables_goldrush[tid].get('last_updated', 0))
        table = _tables_goldrush[latest_table_id]
        try:
            candidates = list(_COLLECTOR_SAVE_DIR_GOLDRUSH.glob('goldrush_hand_*.txt'))
            if candidates:
                latest_file = max(candidates, key=lambda f: f.stat().st_mtime)
                raw_batch = latest_file.read_text(encoding='utf-8').strip()
                table['raw_batch'] = raw_batch
        except Exception as e:
            app.logger.warning(f'[GoldRush] Could not sync collector batch: {e}')
        return jsonify({'ok': True, 'table': table, 'table_id': latest_table_id})
    except Exception as e:
        app.logger.error(f'[GoldRush] Table latest error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/snapshot/goldrush', methods=['POST'])
def snapshot_goldrush():
    try:
        data = request.get_json(force=True)
        table_id = data.get('table_id', 'goldrush_default')
        if not table_id.startswith('goldrush_'):
            table_id = f'goldrush_{table_id}'
        if table_id not in _tables_goldrush:
            _tables_goldrush[table_id] = {
                'table_id': table_id, 'raw_batch': None, 'seats': [], 'board': {},
                'pot': 0, 'street': 'PREFLOP', 'last_updated': time.time()
            }
        table = _tables_goldrush[table_id]
        if 'seats' in data:
            table['seats'] = data['seats']
        if 'board' in data:
            table['board'] = data['board']
        if 'pot' in data:
            table['pot'] = data['pot']
        table['last_updated'] = time.time()
        app.logger.info(f'[GoldRush] Snapshot updated: {table_id}')
        return jsonify({'ok': True, 'table_id': table_id})
    except Exception as e:
        app.logger.error(f'[GoldRush] Snapshot error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

"""
er_hands PostgreSQL logger — records every hand action and equity result.

Uses a separate connection pool so DB failures never crash the poker pipeline.
All writes are fire-and-forget with catch-log-swallow — the poker table
continues even if the DB is unreachable.
"""

import os
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.pool

# ── Connection ──────────────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "er_hands")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "sunbet2024")

_pool = None
_pool_lock = threading.Lock()

def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                try:
                    _pool = psycopg2.pool.ThreadedConnectionPool(
                        1, 4,
                        host=DB_HOST, port=DB_PORT,
                        dbname=DB_NAME, user=DB_USER, password=DB_PASS,
                        connect_timeout=3,
                    )
                except Exception as e:
                    print(f"[DB_LOGGER] Pool init failed: {e}")
                    return None
    return _pool

# ── Hand action logging ─────────────────────────────────────────────────────

def log_hand_action(
    hand_id, table_id, street, action_seq, seat_no, player_name,
    action, amount=None, stack_zar=None, pot_zar=None,
    hole_cards=None, board_flop=None, board_turn=None, board_river=None,
    is_hero=False, is_all_in=False, raw_snapshot=None, source_ip=None,
):
    """Log a single poker action to hand_actions. Fire-and-forget."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hand_actions
                   (hand_id, table_id, street, action_seq, seat_no, player_name,
                    action, amount, stack_zar, pot_zar,
                    hole_cards, board_flop, board_turn, board_river,
                    is_hero, is_all_in, raw_snapshot, source_ip, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())""",
                (
                    hand_id, table_id, street, action_seq, seat_no, player_name,
                    action, amount, stack_zar, pot_zar,
                    hole_cards, board_flop, board_turn, board_river,
                    is_hero, is_all_in,
                    json.dumps(raw_snapshot, default=str) if raw_snapshot else None,
                    str(source_ip) if source_ip else None,
                ),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] log_hand_action failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def start_hand(hand_id, table_id, num_players=0):
    """Create a hand_results row (status='active')."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hand_results
                   (hand_id, table_id, started_at, num_players, status)
                   VALUES (%s,%s,NOW(),%s,'active')
                   ON CONFLICT (hand_id) DO UPDATE
                   SET num_players = EXCLUDED.num_players,
                       updated_at = NOW()""",
                (hand_id, table_id, num_players),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] start_hand failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def update_hand_street(hand_id, street, board_flop=None, board_turn=None, board_river=None, pot_zar=None):
    """Update hand_results street/board/pot."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE hand_results
                   SET street_count = CASE WHEN %s = 'PREFLOP' THEN 1
                                       WHEN %s = 'FLOP' THEN 2
                                       WHEN %s = 'TURN' THEN 3
                                       WHEN %s = 'RIVER' THEN 4
                                       WHEN %s = 'SHOWDOWN' THEN 5
                                       ELSE street_count END,
                       board_flop = COALESCE(%s, board_flop),
                       board_turn = COALESCE(%s, board_turn),
                       board_river = COALESCE(%s, board_river),
                       pot_final = COALESCE(%s, pot_final),
                       updated_at = NOW()
                   WHERE hand_id = %s""",
                (street, street, street, street, street,
                 board_flop, board_turn, board_river, pot_zar, hand_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] update_hand_street failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def end_hand(hand_id, winner_name=None, winner_hand=None, win_amount=None,
             pot_final=None, num_players=None, num_showdown=None):
    """Mark hand as completed."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE hand_results
                   SET ended_at = NOW(),
                       status = 'completed',
                       winner_name = COALESCE(%s, winner_name),
                       winner_hand = COALESCE(%s, winner_hand),
                       win_amount = COALESCE(%s, win_amount),
                       pot_final = COALESCE(%s, pot_final),
                       num_players = COALESCE(%s, num_players),
                       num_showdown = COALESCE(%s, num_showdown),
                       updated_at = NOW()
                   WHERE hand_id = %s""",
                (winner_name, winner_hand, win_amount, pot_final,
                 num_players, num_showdown, hand_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] end_hand failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def log_equity_result(
    run_id, job_id, variant, street, num_players, num_samples,
    hands_text, player_names, results_json,
    best_disparity=None, best_underdog=None, best_favourite=None,
    total_pairs=None, total_runtime=None, error=None,
):
    """Log an equity calculation result."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO equity_results
                   (run_id, job_id, variant, street, num_players, num_samples,
                    hands_text, player_names, results_json,
                    best_disparity, best_underdog, best_favourite,
                    total_pairs, total_runtime, error, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT (run_id) DO UPDATE SET
                    results_json = EXCLUDED.results_json,
                    best_disparity = EXCLUDED.best_disparity,
                    total_pairs = EXCLUDED.total_pairs""",
                (
                    run_id, job_id, variant, street, num_players, num_samples,
                    hands_text, player_names,
                    json.dumps(results_json, default=str) if results_json else None,
                    best_disparity, best_underdog, best_favourite,
                    total_pairs, total_runtime, error,
                ),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] log_equity_result failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def log_session(table_id, bot_id, snapshots=0, commands=0):
    """Upsert session record."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO sessions (table_id, bot_id, started_at, last_seen, total_snapshots, total_commands)
                   VALUES (%s,%s,NOW(),NOW(),%s,%s)
                   ON CONFLICT (table_id, bot_id, started_at) DO UPDATE
                   SET last_seen = NOW(),
                       total_snapshots = sessions.total_snapshots + EXCLUDED.total_snapshots,
                       total_commands = sessions.total_commands + EXCLUDED.total_commands""",
                (table_id, bot_id, snapshots, commands),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] log_session failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


# ── Account registry ─────────────────────────────────────────────────────────

def upsert_account(username, password, player_name=None, bot_id=None, site='pokerbet', email=None, notes=None):
    """Create or update an account record. Returns account_id."""
    pool = _get_pool()
    if not pool:
        return None
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO accounts
                   (username, password, player_name, bot_id, site, email, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (username) DO UPDATE SET
                    password = EXCLUDED.password,
                    player_name = COALESCE(EXCLUDED.player_name, accounts.player_name),
                    bot_id = COALESCE(EXCLUDED.bot_id, accounts.bot_id),
                    site = EXCLUDED.site,
                    email = COALESCE(EXCLUDED.email, accounts.email),
                    notes = COALESCE(EXCLUDED.notes, accounts.notes),
                    updated_at = NOW()
                   RETURNING account_id""",
                (username, password, player_name, bot_id, site, email, notes),
            )
            account_id = cur.fetchone()[0]
        conn.commit()
        return account_id
    except Exception as e:
        print(f"[DB_LOGGER] upsert_account failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def get_accounts(site=None, status='active'):
    """List accounts, optionally filtered by site and status."""
    pool = _get_pool()
    if not pool:
        return []
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            if site:
                cur.execute(
                    "SELECT account_id, username, player_name, bot_id, site, status, last_login_at FROM accounts WHERE site=%s AND status=%s ORDER BY account_id",
                    (site, status),
                )
            else:
                cur.execute(
                    "SELECT account_id, username, player_name, bot_id, site, status, last_login_at FROM accounts WHERE status=%s ORDER BY account_id",
                    (status,),
                )
            rows = cur.fetchall()
            return [
                {
                    "account_id": r[0], "username": r[1], "player_name": r[2],
                    "bot_id": r[3], "site": r[4], "status": r[5], "last_login_at": r[6],
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[DB_LOGGER] get_accounts failed: {e}")
        return []
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def get_account_credentials(username):
    """Return (username, password, bot_id) for a single account."""
    pool = _get_pool()
    if not pool:
        return None
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, password, bot_id FROM accounts WHERE username=%s AND status='active'",
                (username,),
            )
            row = cur.fetchone()
            if row:
                return {"username": row[0], "password": row[1], "bot_id": row[2]}
            return None
    except Exception as e:
        print(f"[DB_LOGGER] get_account_credentials failed: {e}")
        return None
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def start_account_session(account_id, bot_id, table_id, ip_address=None):
    """Record a login session. Returns session_id."""
    pool = _get_pool()
    if not pool:
        return None
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO account_sessions (account_id, bot_id, table_id, ip_address, started_at)
                   VALUES (%s,%s,%s,%s,NOW()) RETURNING session_id""",
                (account_id, bot_id, table_id, str(ip_address) if ip_address else None),
            )
            sid = cur.fetchone()[0]
            cur.execute(
                "UPDATE accounts SET last_login_at = NOW() WHERE account_id = %s",
                (account_id,),
            )
        conn.commit()
        return sid
    except Exception as e:
        print(f"[DB_LOGGER] start_account_session failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def end_account_session(session_id, reason=None):
    """Close an account session."""
    pool = _get_pool()
    if not pool:
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE account_sessions
                   SET ended_at = NOW(), closed_reason = %s
                   WHERE session_id = %s AND ended_at IS NULL""",
                (reason, session_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[DB_LOGGER] end_account_session failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


# ── Health ───────────────────────────────────────────────────────────────────

def db_health():
    """Return True if DB is reachable."""
    pool = _get_pool()
    if not pool:
        return False
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass

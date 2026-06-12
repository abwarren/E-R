"""
Audit Logging — Login/logout/activity tracking module.

Imports into app.py via:
    import audit_logs

Provides:
    - audit_logs.log_login_failed(username, ip_address=..., user_agent=...)
    - audit_logs.log_login_success(username, user_id=..., ip_address=..., user_agent=...)
    - audit_logs.log_logout(username, user_id=..., ip_address=...)
    - audit_logs.log_action(username, action, status, details, ...)
"""

import os
import json
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

# Audit database path (shared with auth_models)
_AUDIT_DB_PATH = os.getenv('AUDIT_DB_PATH', '/home/wa/REMOTEREMOTE/data/audit.db')


def _get_connection():
    """Get a SQLite connection to the audit database."""
    db_dir = os.path.dirname(_AUDIT_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(_AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table():
    """Ensure the audit_log table exists."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                username TEXT NOT NULL,
                user_id INTEGER,
                action TEXT NOT NULL,
                status TEXT DEFAULT 'success',
                ip_address TEXT,
                user_agent TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(timestamp)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(username)
        ''')
        conn.commit()
    except Exception as e:
        logger.error(f"[AUDIT] Table creation failed: {e}")
    finally:
        conn.close()


def _insert_log(username, user_id, action, status='success',
                ip_address=None, user_agent=None, details=None):
    """Insert an audit log entry."""
    import time
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO audit_log
               (timestamp, username, user_id, action, status, ip_address, user_agent, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (time.time(), username, user_id, action, status,
             ip_address or '', user_agent or '', details or '')
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[AUDIT] Failed to write log: {e}")


def log_login_failed(username, ip_address=None, user_agent=None):
    """
    Log a failed login attempt.

    Called from app.py:
        audit_logs.log_login_failed(username,
                         ip_address=request.remote_addr,
                         user_agent=request.headers.get('User-Agent'))
    """
    _ensure_table()
    _insert_log(
        username=username,
        user_id=None,
        action='login_failed',
        status='failure',
        ip_address=ip_address,
        user_agent=user_agent,
        details='Invalid credentials',
    )
    logger.warning(f"[AUDIT] Login FAILED: {username} from {ip_address or '?'}")


def log_login_success(username, user_id=None, ip_address=None, user_agent=None):
    """
    Log a successful login.

    Called from app.py:
        audit_logs.log_login_success(user.username, user_id=user.id,
                         ip_address=request.remote_addr,
                         user_agent=request.headers.get('User-Agent'))
    """
    _ensure_table()
    _insert_log(
        username=username,
        user_id=user_id,
        action='login_success',
        status='success',
        ip_address=ip_address,
        user_agent=user_agent,
    )
    logger.info(f"[AUDIT] Login SUCCESS: {username} from {ip_address or '?'}")


def log_logout(username, user_id=None, ip_address=None):
    """
    Log a logout event.

    Called from app.py:
        audit_logs.log_logout(current_user.username, user_id=current_user.id,
                         ip_address=request.remote_addr)
    """
    _ensure_table()
    _insert_log(
        username=username,
        user_id=user_id,
        action='logout',
        status='success',
        ip_address=ip_address,
    )
    logger.info(f"[AUDIT] Logout: {username}")


def log_action(username, user_id=None, action='action', status='success',
               ip_address=None, user_agent=None, details=None):
    """
    Generic action logger for custom events.
    """
    _ensure_table()
    _insert_log(
        username=username,
        user_id=user_id,
        action=action,
        status=status,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
    )
    logger.info(f"[AUDIT] {username} | {action} | {status}")


def get_recent_logs(limit=50, username=None, action=None):
    """
    Retrieve recent audit logs. Used for audit view pages.

    Args:
        limit: Max number of log entries to return
        username: Optional filter by username
        action: Optional filter by action type

    Returns:
        List of dict log entries, newest first
    """
    _ensure_table()
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        query = 'SELECT * FROM audit_log WHERE 1=1'
        params = []

        if username:
            query += ' AND username = ?'
            params.append(username)
        if action:
            query += ' AND action = ?'
            params.append(action)

        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        logs = []
        for row in rows:
            logs.append({
                'id': row[0],
                'timestamp': row[1],
                'username': row[2],
                'user_id': row[3],
                'action': row[4],
                'status': row[5],
                'ip_address': row[6],
                'user_agent': row[7],
                'details': row[8],
                'created_at': row[9],
            })
        return logs
    except Exception as e:
        logger.error(f"[AUDIT] Failed to fetch logs: {e}")
        return []
    finally:
        conn.close()


def cleanup_old_logs(days=90):
    """Remove audit logs older than the specified number of days."""
    import time
    cutoff = time.time() - (days * 86400)
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM audit_log WHERE timestamp < ?', (cutoff,))
        conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info(f"[AUDIT] Cleaned up {deleted} old log entries")
        return deleted
    except Exception as e:
        logger.error(f"[AUDIT] Cleanup failed: {e}")
        return 0
    finally:
        conn.close()

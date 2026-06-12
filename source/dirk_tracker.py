# -*- coding: utf-8 -*-
"""
Dirk Activity Tracker
=====================
Logs every authenticated request from user 'dirk' to a SQLite database.
Tracks: login, logout, page views, API calls, engine runs, clicks, etc.

Usage: import and call init_dirk_tracker(app, active_tokens) after Flask app setup.

DB: /opt/plo-engine-backend/dirk_activity.db
"""

import sqlite3
import time
import json
import os
import threading
from datetime import datetime, timezone
from flask import request, g, jsonify

import os
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BASE_DIR, "dirk_activity.db")
_lock = threading.Lock()

def _get_db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn

def _init_db():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dirk_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            epoch REAL NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            query_string TEXT,
            status_code INTEGER,
            response_size INTEGER,
            duration_ms REAL,
            ip_address TEXT,
            user_agent TEXT,
            referer TEXT,
            request_body TEXT,
            content_type TEXT,
            auth_token_prefix TEXT,
            session_id TEXT,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dirk_ts ON dirk_activity(timestamp);
        CREATE INDEX IF NOT EXISTS idx_dirk_path ON dirk_activity(path);
        CREATE INDEX IF NOT EXISTS idx_dirk_epoch ON dirk_activity(epoch);

        CREATE TABLE IF NOT EXISTS dirk_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_prefix TEXT UNIQUE,
            login_time TEXT,
            login_ip TEXT,
            login_ua TEXT,
            last_seen TEXT,
            request_count INTEGER DEFAULT 0
        );
    """)
    conn.close()

def _log_activity(data):
    with _lock:
        try:
            conn = _get_db()
            conn.execute("""
                INSERT INTO dirk_activity
                (timestamp, epoch, method, path, query_string, status_code,
                 response_size, duration_ms, ip_address, user_agent, referer,
                 request_body, content_type, auth_token_prefix, session_id, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                data['timestamp'], data['epoch'], data['method'], data['path'],
                data.get('query_string'), data.get('status_code'),
                data.get('response_size'), data.get('duration_ms'),
                data.get('ip_address'), data.get('user_agent'), data.get('referer'),
                data.get('request_body'), data.get('content_type'),
                data.get('auth_token_prefix'), data.get('session_id'),
                data.get('notes')
            ))
            # Update session tracking
            tp = data.get('auth_token_prefix')
            if tp:
                conn.execute("""
                    INSERT INTO dirk_sessions (token_prefix, last_seen, request_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(token_prefix) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        request_count = request_count + 1
                """, (tp, data['timestamp']))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DIRK_TRACKER] log error: {e}")

def _safe_body(req):
    """Capture request body for POST/PUT, redact passwords."""
    if req.method not in ('POST', 'PUT', 'PATCH'):
        return None
    try:
        body = req.get_data(as_text=True, cache=True)
        if not body:
            return None
        # Redact password fields
        try:
            j = json.loads(body)
            for k in ('password', 'pass', 'pw', 'secret'):
                if k in j:
                    j[k] = '***REDACTED***'
            return json.dumps(j)
        except (json.JSONDecodeError, TypeError):
            return body[:2000]
    except Exception:
        return None

def _classify_action(method, path, body):
    """Generate a human-readable note about what Dirk did."""
    p = path.lower()
    if p == '/api/login':
        return 'LOGIN'
    if p == '/api/logout':
        return 'LOGOUT'
    if p == '/api/auth/verify':
        return 'SESSION_CHECK'
    if p == '/api/run':
        return 'RAN_EQUITY_ENGINE'
    if p.startswith('/api/run-batch'):
        return 'RAN_BATCH_ENGINE'
    if p.startswith('/api/stream/'):
        return 'WATCHING_ENGINE_STREAM'
    if p.startswith('/api/results/'):
        return 'VIEWED_RESULTS'
    if p.startswith('/api/download/'):
        return 'DOWNLOADED_RESULTS'
    if p == '/api/validate':
        return 'VALIDATED_HANDS'
    if p == '/api/fix':
        return 'APPLIED_CARD_FIX'
    if p.startswith('/api/collector/'):
        return 'COLLECTOR_ACTION'
    if p.startswith('/api/tracker/'):
        return 'TRACKER_ACTION'
    if p.startswith('/api/analytics/'):
        return 'AI_ANALYTICS_QUERY'
    if p.startswith('/api/rng/'):
        return 'RNG_GENERATE'
    if p.startswith('/api/batch/'):
        return 'BATCH_OPERATION'
    if p.startswith('/api/commands'):
        return 'COMMAND_ACTION'
    if p.startswith('/api/scanner'):
        return 'SCANNER_LOG'
    if p == '/api/current-hands':
        return 'VIEWED_CURRENT_HANDS'
    if p == '/api/health':
        return 'HEALTH_CHECK'
    if p == '/create':
        return 'CREATED_COLLAB_SESSION'
    if p == '/' or (method == 'GET' and not p.startswith('/api/')):
        return 'PAGE_VIEW'
    return f'{method} {path}'


def init_dirk_tracker(app, active_tokens_ref):
    """
    Call this after Flask app is created.
    active_tokens_ref: the dict {token: username} from auth.
    """
    _init_db()
    print("[DIRK_TRACKER] Initialized — logging all activity for user 'dirk'")

    @app.before_request
    def _dirk_before():
        g._dirk_start = time.time()
        g._dirk_user = None
        # Identify user from token
        token = request.headers.get('X-Auth-Token', '')
        if token and token in active_tokens_ref:
            g._dirk_user = active_tokens_ref[token]
            g._dirk_token_prefix = token[:12]
        else:
            g._dirk_user = None
            g._dirk_token_prefix = None

    @app.after_request
    def _dirk_after(response):
        user = getattr(g, '_dirk_user', None)
        path = request.path

        # Always log login attempts (even before token is set)
        is_login = (path == '/api/login' and request.method == 'POST')

        if is_login:
            # Check if this was Dirk logging in (from response)
            try:
                rdata = response.get_json(silent=True)
                if rdata and rdata.get('username', '').lower() == 'dirk':
                    user = 'dirk'
                    # Capture the new token prefix
                    tok = rdata.get('token', '')
                    g._dirk_token_prefix = tok[:12] if tok else None
                    # Record session
                    if g._dirk_token_prefix:
                        try:
                            conn = _get_db()
                            conn.execute("""
                                INSERT OR REPLACE INTO dirk_sessions
                                (token_prefix, login_time, login_ip, login_ua, last_seen, request_count)
                                VALUES (?, ?, ?, ?, ?, 1)
                            """, (
                                g._dirk_token_prefix,
                                datetime.now(timezone.utc).isoformat(),
                                request.remote_addr,
                                request.headers.get('User-Agent', ''),
                                datetime.now(timezone.utc).isoformat()
                            ))
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
            except Exception:
                pass

        # Only log if user is dirk
        if user != 'dirk':
            return response

        # Skip noisy health checks
        if path == '/api/health':
            return response

        now = datetime.now(timezone.utc)
        elapsed = (time.time() - getattr(g, '_dirk_start', time.time())) * 1000
        body = _safe_body(request)
        note = _classify_action(request.method, path, body)

        data = {
            'timestamp': now.isoformat(),
            'epoch': now.timestamp(),
            'method': request.method,
            'path': path,
            'query_string': request.query_string.decode('utf-8', errors='replace') if request.query_string else None,
            'status_code': response.status_code,
            'response_size': response.content_length,
            'duration_ms': round(elapsed, 2),
            'ip_address': request.headers.get('X-Forwarded-For', request.remote_addr),
            'user_agent': request.headers.get('User-Agent', ''),
            'referer': request.headers.get('Referer', ''),
            'request_body': body,
            'content_type': request.content_type,
            'auth_token_prefix': getattr(g, '_dirk_token_prefix', None),
            'session_id': None,
            'notes': note,
        }

        # Log async to avoid slowing down responses
        threading.Thread(target=_log_activity, args=(data,), daemon=True).start()
        return response

# ── Query API ────────────────────────────────────────────────────────────────
def register_dirk_routes(app):
    """Call after init to add /api/dirk/activity query endpoint."""

    @app.route('/api/dirk/activity', methods=['GET'])
    def dirk_activity():
        """
        Query Dirk's activity log.
        ?limit=50  (default 50, max 500)
        ?since=ISO-timestamp
        ?action=LOGIN,RAN_EQUITY_ENGINE  (comma-separated)
        ?format=summary  (optional, returns condensed view)
        """
        limit = min(int(request.args.get('limit', 50)), 500)
        since = request.args.get('since', '')
        actions = request.args.get('action', '')
        fmt = request.args.get('format', 'full')

        conn = _get_db()
        conn.row_factory = sqlite3.Row
        sql = 'SELECT * FROM dirk_activity'
        params = []
        clauses = []

        if since:
            clauses.append('timestamp >= ?')
            params.append(since)
        if actions:
            action_list = [a.strip() for a in actions.split(',')]
            placeholders = ','.join('?' * len(action_list))
            clauses.append(f'notes IN ({placeholders})')
            params.extend(action_list)

        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY id DESC LIMIT ?'
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()

        if fmt == 'summary':
            results = [{
                'time': r['timestamp'],
                'action': r['notes'],
                'path': r['path'],
                'status': r['status_code'],
                'ip': r['ip_address'],
                'ms': r['duration_ms'],
            } for r in rows]
        else:
            results = [dict(r) for r in rows]

        return jsonify({'count': len(results), 'activity': results})

    @app.route('/api/dirk/sessions', methods=['GET'])
    def dirk_sessions():
        conn = _get_db()
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM dirk_sessions ORDER BY login_time DESC LIMIT 20').fetchall()
        conn.close()
        return jsonify({'sessions': [dict(r) for r in rows]})

    @app.route('/api/dirk/summary', methods=['GET'])
    def dirk_summary():
        """Quick overview: total actions, last seen, top actions."""
        conn = _get_db()
        total = conn.execute('SELECT COUNT(*) FROM dirk_activity').fetchone()[0]
        last = conn.execute('SELECT timestamp, notes, path FROM dirk_activity ORDER BY id DESC LIMIT 1').fetchone()
        top_actions = conn.execute(
            'SELECT notes, COUNT(*) as cnt FROM dirk_activity GROUP BY notes ORDER BY cnt DESC LIMIT 10'
        ).fetchall()
        conn.close()
        return jsonify({
            'total_events': total,
            'last_seen': {'time': last[0], 'action': last[1], 'path': last[2]} if last else None,
            'top_actions': [{'action': r[0], 'count': r[1]} for r in top_actions],
        })

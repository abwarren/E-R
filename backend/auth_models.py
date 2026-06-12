"""
Authentication Models — Flask-Login User class with SQLite backend.

Imports into app.py via:
    from auth_models import User, init_database, log_user_activity, get_db_connection

Provides:
    - User class with Flask-Login interface (.is_authenticated, .get_id(), .is_admin())
    - User.get(user_id) — load user by ID
    - User.authenticate(username, password) — verify credentials
    - User.get_by_username(username) — get (user_obj, password_hash) tuple
    - init_database() — create/initialize the SQLite database
    - log_user_activity() — insert activity log entries
    - get_db_connection() — raw SQLite connection for direct queries
"""

import os
import sqlite3
import logging
import threading
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

logger = logging.getLogger(__name__)

# Database path
_AUTH_DB_PATH = os.getenv('AUTH_DB_PATH', '/home/wa/REMOTEREMOTE/data/auth.db')
_db_lock = threading.Lock()


class User(UserMixin):
    """Flask-Login compatible user model backed by SQLite."""

    def __init__(self, id, username, password_hash, role='user', is_active=True,
                 must_change_password=False, created_at=None, updated_at=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self._is_active = bool(is_active)
        self.must_change_password = bool(must_change_password)
        self.created_at = created_at
        self.updated_at = updated_at

    @property
    def is_active(self):
        return self._is_active

    def get_id(self):
        """Return string user ID for Flask-Login session."""
        return str(self.id)

    def is_admin(self):
        """Check if user has admin role."""
        return self.role == 'admin'

    @classmethod
    def get(cls, user_id):
        """Load user by ID (string or int). Used by Flask-Login loader."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logger.warning(f"[AUTH] Invalid user_id type: {type(user_id)}")
            return None

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, username, password_hash, role, is_active, must_change_password, created_at, updated_at '
                'FROM users WHERE id = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return cls(
                    id=row[0],
                    username=row[1],
                    password_hash=row[2],
                    role=row[3],
                    is_active=row[4],
                    must_change_password=row[5],
                    created_at=row[6],
                    updated_at=row[7],
                )
            return None
        except Exception as e:
            logger.error(f"[AUTH] Error loading user {user_id}: {e}")
            return None
        finally:
            conn.close()

    @classmethod
    def authenticate(cls, username, password):
        """
        Verify username and password.
        Returns User object on success, None on failure.
        """
        if not username or not password:
            return None

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, username, password_hash, role, is_active, must_change_password, created_at, updated_at '
                'FROM users WHERE username = ?',
                (username.strip().lower(),)
            )
            row = cursor.fetchone()
            if not row:
                return None

            stored_hash = row[2]
            if not check_password_hash(stored_hash, password):
                return None

            return cls(
                id=row[0],
                username=row[1],
                password_hash=stored_hash,
                role=row[3],
                is_active=row[4],
                must_change_password=row[5],
                created_at=row[6],
                updated_at=row[7],
            )
        except Exception as e:
            logger.error(f"[AUTH] Authentication error: {e}")
            return None
        finally:
            conn.close()

    @classmethod
    def get_by_username(cls, username):
        """
        Get user by username. Returns (user_object, password_hash) tuple.
        Used by password change flow.
        """
        if not username:
            return None, None

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, username, password_hash, role, is_active, must_change_password, created_at, updated_at '
                'FROM users WHERE username = ?',
                (username.strip().lower(),)
            )
            row = cursor.fetchone()
            if row:
                user = cls(
                    id=row[0],
                    username=row[1],
                    password_hash=row[2],
                    role=row[3],
                    is_active=row[4],
                    must_change_password=row[5],
                    created_at=row[6],
                    updated_at=row[7],
                )
                return user, row[2]
            return None, None
        except Exception as e:
            logger.error(f"[AUTH] Error fetching user by username: {e}")
            return None, None
        finally:
            conn.close()

    def to_dict(self):
        """Serialize user to dict (without password hash)."""
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'is_active': self._is_active,
            'must_change_password': self.must_change_password,
        }


def get_db_connection():
    """Get a SQLite database connection."""
    db_dir = os.path.dirname(_AUTH_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(_AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database():
    """
    Initialize the authentication database.
    Creates the users table and activity_log table if they don't exist.
    Also creates a default admin user if no users exist.
    """
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # Create users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create activity_log table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT DEFAULT 'success',
                    ip_address TEXT,
                    user_agent TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create activity_log index
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_activity_log_user_id
                ON activity_log(user_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_activity_log_created_at
                ON activity_log(created_at)
            ''')

            # Check if any users exist
            cursor.execute('SELECT COUNT(*) FROM users')
            count = cursor.fetchone()[0]

            if count == 0:
                # Create default admin user
                default_admin_user = os.getenv('DEFAULT_ADMIN_USER', 'admin')
                default_admin_pass = os.getenv('DEFAULT_ADMIN_PASSWORD', 'changeme123')

                password_hash = generate_password_hash(
                    default_admin_pass, method='pbkdf2:sha256'
                )
                cursor.execute(
                    'INSERT INTO users (username, password_hash, role, must_change_password) '
                    'VALUES (?, ?, ?, 1)',
                    (default_admin_user, password_hash, 'admin')
                )
                logger.info(
                    f"[AUTH] Created default admin user '{default_admin_user}' "
                    f"(must_change_password=True)"
                )

            conn.commit()
            logger.info("[AUTH] Database initialized successfully")
            return True

        except Exception as e:
            logger.error(f"[AUTH] Database initialization failed: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()


def log_user_activity(user_id, username, action, status='success',
                      ip_address=None, user_agent=None, details=None):
    """
    Log user activity to the database.

    Args:
        user_id: User's database ID
        username: User's username string
        action: Action name (e.g. 'login', 'password_change', 'logout')
        status: 'success' or 'failure'
        ip_address: Client IP address
        user_agent: Client user agent string
        details: Additional details string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO activity_log
               (user_id, username, action, status, ip_address, user_agent, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (user_id, username, action, status, ip_address, user_agent, details)
        )
        conn.commit()
        conn.close()
        logger.info(f"[AUDIT] {username} | {action} | {status} | {ip_address or '?'}")
    except Exception as e:
        logger.error(f"[AUDIT] Failed to log activity: {e}")

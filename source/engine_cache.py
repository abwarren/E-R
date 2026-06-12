"""
engine_cache.py
===============
LRU file cache for PLO engine results.
Enabled ONLY for: plo4-9max, plo6-6max.
Everything else: cache OFF.

Storage: /opt/plo-engine-backend/cache/
Max: 1GB, eviction: LRU (oldest access time)
"""
import os
import json
import hashlib
import time
import logging

CACHE_DIR = "/opt/plo-engine-backend/cache"
MAX_BYTES = 1 * 1024 * 1024 * 1024  # 1GB
ENABLED_VARIANTS = {"plo4-9max", "plo6-6max"}

logger = logging.getLogger("engine_cache")


def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def is_enabled(variant):
    enabled = variant in ENABLED_VARIANTS
    if enabled:
        logger.info(f"[CACHE] enabled variant={variant}")
    else:
        logger.info(f"[CACHE] disabled variant={variant}")
    return enabled


def _make_key(variant, hands, board, settings=None):
    """Generate cache key from normalized inputs."""
    # Normalize hands: sort lines, strip whitespace, uppercase
    hand_lines = sorted(h.strip().upper() for h in hands.splitlines() if h.strip())
    normalized_hands = "\n".join(hand_lines)
    normalized_board = (board or "").strip().upper()
    settings_str = json.dumps(settings or {}, sort_keys=True)

    raw = f"{variant}|{normalized_hands}|{normalized_board}|{settings_str}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.json")


def get(variant, hands, board, settings=None):
    """Check cache. Returns (hit, data) tuple."""
    if not is_enabled(variant):
        return False, None

    _ensure_dir()
    key = _make_key(variant, hands, board, settings)
    path = _cache_path(key)

    if os.path.exists(path):
        try:
            # Touch access time for LRU
            os.utime(path, None)
            with open(path, "r") as f:
                data = json.load(f)
            logger.info("[CACHE] hit")
            return True, data
        except (json.JSONDecodeError, OSError):
            # Corrupted cache entry
            try:
                os.remove(path)
            except OSError:
                pass

    logger.info("[CACHE] miss")
    return False, None


def save(variant, hands, board, results, settings=None):
    """Save results to cache. Never cache errors or invalid runs."""
    if not is_enabled(variant):
        return

    # Never cache errors
    if not results or isinstance(results, dict) and results.get("error"):
        return

    # Never cache <2 players
    if isinstance(results, dict):
        players = results.get("players", [])
        if len(players) < 2:
            return
        # Never cache partial results
        matchups = results.get("matchups", [])
        if not matchups:
            return

    _ensure_dir()
    key = _make_key(variant, hands, board, settings)
    path = _cache_path(key)

    try:
        with open(path, "w") as f:
            json.dump(results, f)
        logger.info("[CACHE] saved")
    except OSError as e:
        logger.warning(f"[CACHE] save failed: {e}")
        return

    # Eviction check
    _evict_if_needed()


def _evict_if_needed():
    """LRU eviction: remove oldest-accessed files until under MAX_BYTES."""
    try:
        entries = []
        total = 0
        for fname in os.listdir(CACHE_DIR):
            fpath = os.path.join(CACHE_DIR, fname)
            if not fname.endswith(".json"):
                continue
            stat = os.stat(fpath)
            entries.append((stat.st_atime, stat.st_size, fpath))
            total += stat.st_size

        if total <= MAX_BYTES:
            return

        # Sort by access time ascending (oldest first)
        entries.sort(key=lambda x: x[0])

        while total > MAX_BYTES and entries:
            atime, size, fpath = entries.pop(0)
            try:
                os.remove(fpath)
                total -= size
                logger.info(f"[CACHE] evicted {os.path.basename(fpath)}")
            except OSError:
                pass
    except OSError:
        pass

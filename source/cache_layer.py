"""
LRU Cache Layer for PLO Engine
Enabled ONLY for: PLO4-9max, PLO6-6max
Storage: /opt/plo-engine-backend/cache/
Max: 1GB, LRU eviction
"""
import hashlib
import json
import os
import time
import logging

CACHE_DIR = '/opt/plo-engine-backend/cache'
MAX_CACHE_BYTES = 1_000_000_000  # 1GB
ENABLED_VARIANTS = {'plo4-9max', 'plo6-6max'}

_log = logging.getLogger('cache')


def _cache_key(variant, hands, board):
    """Generate deterministic cache key from normalized input."""
    # Sort hands for order-independent caching
    hand_lines = sorted(h.strip().upper() for h in hands if h.strip())
    board_norm = (board or '').strip().upper()
    raw = f"{variant.lower()}|{'|'.join(hand_lines)}|{board_norm}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.json")


def _meta_path(key):
    return os.path.join(CACHE_DIR, f"{key}.meta")


def is_enabled(variant):
    """Check if caching is enabled for this variant."""
    v = (variant or '').lower().replace(' ', '')
    enabled = v in ENABLED_VARIANTS
    if enabled:
        _log.info(f'[CACHE] enabled variant={variant}')
    else:
        _log.info(f'[CACHE] disabled variant={variant}')
    return enabled


def get(variant, hands, board):
    """
    Check cache. Returns cached result dict or None.
    """
    if not is_enabled(variant):
        return None

    key = _cache_key(variant, hands, board)
    path = _cache_path(key)
    meta = _meta_path(key)

    if not os.path.exists(path):
        _log.info('[CACHE] miss')
        return None

    try:
        with open(path, 'r') as f:
            data = json.load(f)
        # Update access time for LRU
        with open(meta, 'w') as f:
            f.write(str(time.time()))
        _log.info('[CACHE] hit')
        return data
    except (json.JSONDecodeError, OSError):
        _log.warning('[CACHE] corrupted entry, removing')
        _safe_remove(path)
        _safe_remove(meta)
        return None


def put(variant, hands, board, result):
    """
    Store result in cache. Enforces max size via LRU eviction.
    Does NOT cache errors, <2 players, or partial results.
    """
    if not is_enabled(variant):
        return

    # Validation: don't cache bad results
    if not result or not isinstance(result, dict):
        return
    status = result.get('status', '')
    data = result.get('data', {})
    if status != 'done':
        return
    if data.get('pairs_evaluated', 0) == 0:
        return
    players = data.get('players', [])
    if len(players) < 2:
        return

    key = _cache_key(variant, hands, board)
    path = _cache_path(key)
    meta = _meta_path(key)

    try:
        payload = json.dumps(result)
        # Evict if needed
        _evict_if_needed(len(payload))
        with open(path, 'w') as f:
            f.write(payload)
        with open(meta, 'w') as f:
            f.write(str(time.time()))
        _log.info('[CACHE] saved')
    except OSError as e:
        _log.error(f'[CACHE] write error: {e}')


def _evict_if_needed(new_bytes):
    """LRU eviction to stay under MAX_CACHE_BYTES."""
    total = _cache_size()
    if total + new_bytes <= MAX_CACHE_BYTES:
        return

    # Get all cache entries sorted by last access (oldest first)
    entries = []
    for f in os.listdir(CACHE_DIR):
        if f.endswith('.json'):
            key = f[:-5]
            meta = _meta_path(key)
            try:
                atime = float(open(meta).read()) if os.path.exists(meta) else 0
            except (ValueError, OSError):
                atime = 0
            entries.append((atime, key, os.path.getsize(os.path.join(CACHE_DIR, f))))

    entries.sort()  # Oldest first

    freed = 0
    target = (total + new_bytes) - MAX_CACHE_BYTES
    for atime, key, size in entries:
        if freed >= target:
            break
        _safe_remove(_cache_path(key))
        _safe_remove(_meta_path(key))
        freed += size
        _log.info(f'[CACHE] evicted key={key[:12]}... freed={size}')


def _cache_size():
    """Total bytes in cache directory."""
    total = 0
    try:
        for f in os.listdir(CACHE_DIR):
            fp = os.path.join(CACHE_DIR, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    except OSError:
        pass
    return total


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass

"""
Equity Engine Routes — SSE streaming for equity calculations.
Imports into app.py via:
    from equity_routes import register_equity_routes
    register_equity_routes(app)
"""

import os
import sys
import time
import json
import logging
import random
import queue as _queue
import threading
from itertools import combinations
from pathlib import Path

import requests as _requests
from flask import jsonify, request, Response

logger = logging.getLogger(__name__)

# ── Direct engine import (remove subprocess where possible) ─────────────────
EQUITY_ENGINE_DIR = '/home/wa/E&R/ENGINEENGINE'
_direct_engine = None
try:
    _engine_source = os.path.join(EQUITY_ENGINE_DIR, 'source')
    if _engine_source not in sys.path:
        sys.path.insert(0, _engine_source)
    from result_parser import parse_results as _engine_parse_results
    _direct_engine = {'parse_results': _engine_parse_results}
    logger.info('[ENGINE-IMPORT] Direct engine import OK: result_parser available')
except Exception as e:
    logger.info('[ENGINE-IMPORT] Direct engine import unavailable (%s), falling back to subprocess/HTTP', e)
    _direct_engine = None

# ── Action Router (CDP injection into Vivaldi tabs) ──────────────────────────
_action_router = None
try:
    from action_router import ActionRouter, get_router
    _action_router = get_router()
    logger.info('[ACTION-ROUTER] Initialized OK')
except Exception as e:
    logger.warning('[ACTION-ROUTER] Init failed (%s), CDP actions disabled', e)

# Phase 1: Import in-memory ring buffer (fast path for /api/run)
from buffer import get_latest_snapshot, extract_hands_and_board

# Collector integration: canonical hand source for /api/run
_COLLECTOR_SAVE_DIR = Path('/home/wa/REMOTEREMOTE/data/hand-collector/saved_hands')
_COLLECTOR_FILE_MAX_AGE = 60.0

# In-memory store for active equity runs
_equity_runs = {}
_equity_lock = threading.Lock()
_equity_sse_clients = []
_equity_sse_lock = threading.Lock()


def _equity_sse_notify(data):
    """Push data to all equity SSE clients."""
    msg = json.dumps(data, default=str)
    dead = []
    with _equity_sse_lock:
        for q in _equity_sse_clients:
            try:
                q.put_nowait(msg)
            except _queue.Full:
                dead.append(q)
        for q in dead:
            _equity_sse_clients.remove(q)


def register_equity_routes(app):
    """Register all equity engine routes on the Flask app."""

    # ── Collector pre-normalizer — reads latest saved hands from collector files ──
    def _read_hands_from_collector():
        """Try to read canonical hands+board from the latest collector save file.

        Phase 1: Checks in-memory ring buffer first (fast path from /api/snapshot).
        Falls back to disk-based collector files if buffer is empty.
        """
        # ── Phase 1: Check in-memory ring buffer first (fast path) ──
        try:
            snapshot = get_latest_snapshot()
            if snapshot:
                hands, board = extract_hands_and_board(snapshot)
                if hands and len(hands) >= 2:
                    logger.info('[BUFFER] Loaded %d hands from in-memory buffer', len(hands))
                    return hands, board or ''
        except Exception as e:
            logger.warning('[BUFFER] Read error (will fall through to disk): %s', e)

        # ── Fallback: Disk-based collector files ──
        try:
            candidates = sorted(
                _COLLECTOR_SAVE_DIR.glob('*.txt'),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
            for f in candidates:
                age = time.time() - f.stat().st_mtime
                if age > _COLLECTOR_FILE_MAX_AGE:
                    continue
                text = f.read_text(encoding='utf-8').strip()
                hands = []
                board = None
                for line in text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('BOARD:'):
                        board = line[6:]
                        continue
                    # Validate as card string (8-14 chars for PLO4-PLO7)
                    if len(line) in (8, 10, 12, 14) and len(line) % 2 == 0:
                        hands.append(line)
                if hands:
                    logger.info('[COLLECTOR-NORM] Loaded %d hands from %s', len(hands), f.name)
                    return hands, board or ''
            return None, None
        except Exception as e:
            logger.warning('[COLLECTOR-NORM] Read error: %s', e)
            return None, None

    @app.route('/api/run', methods=['POST'])
    def equity_run():
        """
        Run an equity calculation.
        Accepts:
          a) Frontend canonical: { "variant": "plo5-6max", "hands": "AhKdQsJc9h\n7d3s4c6s...\n6h2dAh", "names": "Player1=Hero\n..." }
             - hands = raw textarea string, each line = one hand, last line = board (no BOARD label)
             - detect variant from hand length: 8=PLO4, 10=PLO5, 12=PLO6, 14=PLO7
             - max players: 5/6/8/9 depending on variant
          b) Legacy: { "hands": ["AsKs", "QdJd"], "board": "Tc9c3h", "samples": 10000, "game": "omaha" }
        Returns a run_id for polling results via SSE.
        """
        try:
            data = request.get_json(force=True)
            if not data:
                return jsonify({'ok': False, 'error': 'No data provided'}), 400

            raw_hands = data.get('hands', [])
            names_raw = data.get('names', '')

            # ── Collector pre-normalization: auto-fill hands from collector when sparse ──
            # Resolves dual-source gap: snapshot→collector→engine path unified.
            _is_sparse = (
                not raw_hands or
                (isinstance(raw_hands, str) and raw_hands.strip() == '') or
                (isinstance(raw_hands, list) and len(raw_hands) < 2)
            )
            if _is_sparse:
                col_hands, col_board = _read_hands_from_collector()
                if col_hands and len(col_hands) >= 2:
                    raw_hands = '\n'.join(col_hands + [col_board]) if col_board else '\n'.join(col_hands)
                    logger.info('[COLLECTOR-NORM] Replaced sparse hands with %d collector hands', len(col_hands))
                elif col_hands:
                    # Single hand from collector + no board → keep as-is for preflop
                    raw_hands = col_hands[0]

            # Initialise these before the str/list branch so they're always safe
            # for the _meta dict below.
            client_variant = (data.get('variant') or '').strip().lower()
            plo_type = None

            # Parse player names from "Player1=Hero\nPlayer2=Villain" format
            names = {}
            if names_raw and isinstance(names_raw, str):
                for line in names_raw.split('\n'):
                    line = line.strip()
                    if '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip().lower()
                        if key.startswith('player'):
                            idx = key.replace('player', '').strip()
                            if idx.isdigit():
                                names[int(idx)] = val.strip()

            if isinstance(raw_hands, str):
                # Canonical format: raw textarea string, hands-per-line, board=last line (if present)
                lines = [l.strip() for l in raw_hands.split('\n') if l.strip()]
                if len(lines) < 2:
                    return jsonify({'ok': False, 'error': 'parse_error', 'message': 'Need at least 2 hands'}), 400

                # Detect variant from hand length
                hlen = len(lines[0])
                variant_map = {8: 'plo4', 10: 'plo5', 12: 'plo6', 14: 'plo7'}
                plo_type = variant_map.get(hlen)

                # Determine if last line is a board or a hand:
                # Board is 6 (flop), 8 (turn), or 10 (river) chars — never matches PLO hand lengths
                last_line = lines[-1]
                board_len = len(last_line)
                is_board = board_len in (6, 8, 10) and (not plo_type or board_len != hlen)

                if is_board and len(lines) >= 3:
                    board = last_line
                    hands = lines[:-1]
                else:
                    # No board line — all lines are hands (preflop or full textarea)
                    board = data.get('board', '') or ''
                    hands = lines

                # Validate board length
                if board and len(board) not in (6, 8, 10):
                    return jsonify({'ok': False, 'error': 'parse_error', 'message': f'Invalid board line length: {len(board)}. Expected 6 (flop), 8 (turn), or 10 (river).'}), 400

                # Detect variant from hand length (after board separation)
                if hands:
                    hlen = len(hands[0])
                    variant_map = {8: 'plo4', 10: 'plo5', 12: 'plo6', 14: 'plo7'}
                    plo_type = variant_map.get(hlen)
                    if not plo_type:
                        return jsonify({'ok': False, 'error': 'parse_error', 'message': f'Invalid hand length: {hlen}. Expected 8 (PLO4), 10 (PLO5), 12 (PLO6), or 14 (PLO7).'}), 400

                    # Validate all hands have same length
                    for i, h in enumerate(hands):
                        if len(h) != hlen:
                            return jsonify({'ok': False, 'error': 'parse_error', 'message': f'Hand {i+1} has {len(h)} chars but expected {hlen} (all hands must match variant).'}), 400

                    # Preserve the UI's explicitly-selected variant (keeps its -max
                    # table size, e.g. plo6-8max) when it matches the detected PLO
                    # size.  Only synthesize from the hand count when the caller
                    # sent no usable selection.
                    if client_variant.startswith(plo_type + '-') and client_variant.endswith('max'):
                        data['variant'] = client_variant
                    else:
                        # Synthesize a valid VARIANTS key: pick the smallest valid
                        # max-player value that fits the detected hand count.
                        # Valid max values (must match ENGINEENGINE VARIANTS keys):
                        _VALID_MAX = {'plo4': [6, 8, 9], 'plo5': [5, 6, 8, 9],
                                      'plo6': [5, 6, 8], 'plo7': [5, 6]}
                        available = _VALID_MAX.get(plo_type, [6])
                        chosen_max = next((m for m in available if m >= len(hands)), available[-1])
                        data['variant'] = f'{plo_type}-{chosen_max}max'
            else:
                # Legacy format: hands as array, optional board field
                hands = raw_hands
                board = data.get('board', '')

            # Legacy: if hands is a list, check if last entry looks like a board
            if isinstance(hands, list) and len(hands) >= 2:
                if len(hands) >= 3 and isinstance(hands[-1], str) and len(hands[-1]) < 12 and not isinstance(hands[-1], str) and len(hands[-1]) < 12:
                    pass
                # Check if last entry looks like a board (short string, 6/8/10 chars)
                last = hands[-1]
                if len(last) in (6, 8, 10) and len(hands) >= 3:
                    board = last
                    hands = hands[:-1]

            if not hands or len(hands) < 2:
                return jsonify({'ok': False, 'error': 'Need at least 2 hands'}), 400

            board = data.get('board', board) or ''
            samples = min(int(data.get('samples', 10000)), 100000)
            variant = data.get('variant', '')
            # Map variant to game type for equity calculation
            if variant:
                v = variant.lower()
                if 'plo7' in v:
                    game = 'plo7'
                elif 'plo6' in v:
                    game = 'plo6'
                elif 'plo5' in v:
                    game = 'plo5'
                elif 'plo' in v:
                    game = 'plo'
                elif 'holdem' in v or 'nlh' in v:
                    game = 'holdem'
                else:
                    game = data.get('game', 'omaha')
            else:
                game = data.get('game', 'omaha')

            run_id = f"eq_{int(time.time() * 1000)}_{threading.get_ident()}"

            # Store run metadata
            with _equity_lock:
                _equity_runs[run_id] = {
                    'run_id': run_id,
                    'hands': hands,
                    'board': board,
                    'samples': samples,
                    'game': game,
                    'variant': variant,
                    'names': names,
                    'status': 'queued',
                    'progress': 0,
                    'results': None,
                    'created_at': time.time(),
                    '_meta': {
                        'requested_variant': client_variant,
                        'detected_plo_type': plo_type,
                        'final_variant': variant,
                        'game': game,
                        'hand_count': len(hands),
                        'cards_per_hand': len(hands[0]) // 2 if hands and hands[0] else None,
                        'board': board,
                        'job_id': run_id,
                        'route_source': 'equity_routes.py (port 4000)',
                        'engine_url': os.getenv('ENGINE_URL', 'http://127.0.0.1:5002'),
                    },
                }

            # Start calculation in background thread
            def _run_equity():
                try:
                    with _equity_lock:
                        _equity_runs[run_id]['status'] = 'running'

                    engine_url = os.getenv('ENGINE_URL', 'http://127.0.0.1:5002')

                    # Build hands string: one hand per line + board as last line
                    hands_str = '\n'.join(str(h) for h in hands)
                    if board:
                        hands_str += '\n' + board

                    # Delegate to real equity engine on port 5002
                    payload = {
                        'variant': variant,
                        'hands': hands_str,
                        'samples': samples,
                    }
                    if names:
                        name_lines = []
                        for idx, name in names.items():
                            name_lines.append(f'Player{idx}={name}')
                        payload['names'] = '\n'.join(name_lines)

                    result = None
                    try:
                        # Submit job to real engine
                        resp = _requests.post(
                            f'{engine_url}/api/run',
                            json=payload,
                            timeout=30
                        )
                        if resp.status_code == 200:
                            job_data = resp.json()
                            job_id = job_data.get('job_id')
                            if job_id:
                                # Poll for results (engine runs async as subprocess)
                                for _ in range(30):  # max 30 sec
                                    time.sleep(1)
                                    poll = _requests.get(
                                        f'{engine_url}/api/results/{job_id}',
                                        timeout=10
                                    )
                                    if poll.status_code == 200:
                                        poll_data = poll.json()
                                        if poll_data.get('status') == 'done':
                                            result = poll_data.get('data', poll_data)
                                            result['status'] = 'done'
                                            # Merge engine-level _meta into the route-level _meta
                                            engine_meta = poll_data.get('_meta')
                                            if engine_meta:
                                                result['_meta'] = engine_meta
                                            break
                                if result is None:
                                    result = {'error': 'Engine job timed out'}
                            else:
                                result = {'error': 'No job_id in engine response'}
                        else:
                            result = {'error': f'Engine returned HTTP {resp.status_code}'}
                    except Exception as e:
                        # Fallback: local naive equity calculation
                        logger.warning('[EQUITY][FALLBACK] external ENGINE_URL=%s failed (%s), using _naive_equity_fallback', engine_url, str(e)[:120])
                        result = _naive_equity_fallback(hands, board, samples, game, names)

                    # If external engine returned an error or unexpected format, fallback
                    if isinstance(result, dict) and result.get('error'):
                        logger.warning(f"[EQUITY] External engine failed ({result['error']}), using naive fallback")
                        result = _naive_equity_fallback(hands, board, samples, game, names)

                    with _equity_lock:
                        _equity_runs[run_id]['status'] = 'completed'
                        _equity_runs[run_id]['progress'] = 100
                        _equity_runs[run_id]['results'] = result

                    # Notify SSE clients
                    _equity_sse_notify({
                        'type': 'equity_result',
                        'run_id': run_id,
                        'results': result,
                    })

                    # ── Phase 3: CDP action injection (if decision_mode is active) ──
                    if data.get('decision_mode') and _action_router:
                        try:
                            action_result = _action_router.decide_and_act(
                                result,
                                tab_id=data.get('tab_id'),
                                decision_mode=data.get('decision_mode', 'auto'),
                            )
                            logger.info('[ACTION-ROUTER] Decision executed: %s → %s',
                                        action_result.get('decision'),
                                        'OK' if action_result.get('ok') else action_result.get('error'))
                            with _equity_lock:
                                _equity_runs[run_id]['_action_result'] = action_result
                        except Exception as ae:
                            logger.warning('[ACTION-ROUTER] Action injection failed: %s', ae)

                except Exception as e:
                    logger.exception('[ENGINE] Background thread died')
                    with _equity_lock:
                        if run_id in _equity_runs:
                            _equity_runs[run_id]['status'] = 'error'
                            _equity_runs[run_id]['error'] = str(e)
                    _equity_sse_notify({
                        'type': 'equity_error',
                        'run_id': run_id,
                        'error': str(e),
                    })

            t = threading.Thread(target=_run_equity, name=f"equity-{run_id}", daemon=True)
            t.start()

            return jsonify({
                'ok': True,
                'job_id': run_id,  # alias for frontend contract
                'run_id': run_id,
                'status': 'queued',
                'estimated_hands': len(hands),
            })

        except Exception as e:
            logger.exception('[EQUITY] Unhandled error in /api/run')
            return jsonify({'ok': False, 'error': 'internal_error', 'message': str(e)[:200]}), 500

    @app.route('/api/run/<run_id>', methods=['GET'])
    def equity_status(run_id):
        """Get status of a specific equity run."""
        with _equity_lock:
            run = _equity_runs.get(run_id)
            if not run:
                return jsonify({'ok': False, 'error': 'Run not found'}), 404
            return jsonify({
                'ok': True,
                'run': {
                    'run_id': run['run_id'],
                    'status': run['status'],
                    'progress': run['progress'],
                    'results': run.get('results'),
                    'error': run.get('error'),
                    'created_at': run['created_at'],
                }
            })

    @app.route('/api/stream/equity', methods=['GET'])
    def equity_sse_stream():
        """SSE stream for equity calculation results."""
        q = _queue.Queue(maxsize=50)
        with _equity_sse_lock:
            _equity_sse_clients.append(q)

        def generate():
            try:
                # Send existing completed runs
                with _equity_lock:
                    for run_id, run in list(_equity_runs.items()):
                        if run['status'] == 'completed' and run.get('results'):
                            yield f"data: {json.dumps({'type': 'equity_result', 'run_id': run_id, 'results': run['results']})}\n\n"

                while True:
                    try:
                        msg = q.get(timeout=30)
                        yield f"data: {msg}\n\n"
                    except _queue.Empty:
                        yield ": keepalive\n\n"
            except GeneratorExit:
                pass
            finally:
                with _equity_sse_lock:
                    if q in _equity_sse_clients:
                        _equity_sse_clients.remove(q)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.route('/api/stream/<run_id>', methods=['GET'])
    def equity_stream_job(run_id):
        """Per-job SSE stream for equity calculation results.
        
        This endpoint matches the frontend EventSource("/api/stream/{jobId}")
        contract. It yields the result when the specific run completes,
        then sends a 'done' SSE event to signal completion.
        Returns JSON 404 (not HTML) for unknown run_ids.
        """
        with _equity_lock:
            run = _equity_runs.get(run_id)
            if not run:
                return jsonify({'ok': False, 'error': 'Run not found'}), 404

        def generate():
            try:
                # If already completed, yield immediately
                with _equity_lock:
                    current = _equity_runs.get(run_id)
                    if current and current['status'] == 'completed' and current.get('results'):
                        yield f"data: {json.dumps({'type': 'equity_result', 'run_id': run_id, 'results': current['results']})}\n\n"
                        yield "event: done\ndata: 0\n\n"
                        return

                # Poll until completed, timed out, or timeout
                deadline = time.time() + 60  # max 60s wait
                while time.time() < deadline:
                    with _equity_lock:
                        current = _equity_runs.get(run_id)
                        if not current:
                            yield f"data: {json.dumps({'type': 'equity_error', 'run_id': run_id, 'error': 'Run evicted'})}\n\n"
                            return
                        if current['status'] == 'completed' and current.get('results'):
                            yield f"data: {json.dumps({'type': 'equity_result', 'run_id': run_id, 'results': current['results']})}\n\n"
                            break
                        if current['status'] == 'failed':
                            yield f"data: {json.dumps({'type': 'equity_error', 'run_id': run_id, 'error': current.get('error', 'Unknown error')})}\n\n"
                            return
                    try:
                        # Use a short sleep so we can check status frequently
                        time.sleep(2)
                    except GeneratorExit:
                        return
                else:
                    # Timed out
                    yield f"data: {json.dumps({'type': 'equity_timeout', 'run_id': run_id})}\n\n"
                    return

                # Send named 'done' event — frontend listens for this at api.js:107-109
                yield "event: done\ndata: 0\n\n"

            except GeneratorExit:
                pass

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.route('/api/runs', methods=['GET'])
    def equity_list_runs():
        """List recent equity runs."""
        with _equity_lock:
            runs = sorted(
                [{'run_id': r['run_id'], 'status': r['status'],
                  'hands': r['hands'], 'created_at': r['created_at'],
                  'progress': r['progress']}
                 for r in _equity_runs.values()],
                key=lambda r: r['created_at'],
                reverse=True
            )[:20]
        return jsonify({'ok': True, 'runs': runs})

    @app.route('/api/results/<run_id>', methods=['GET'])
    def equity_results(run_id):
        """Get results of a specific equity run.
        
        Returns results flat (not nested under 'results') matching the
        frontend EngineTab.jsx contract: checks res.status === 'done'
        and res.data?.matchups?.length.
        """
        with _equity_lock:
            run = _equity_runs.get(run_id)
            if not run:
                return jsonify({'ok': False, 'error': 'Run not found'}), 404
            meta = run.get('_meta', {})
            if run['status'] != 'completed':
                return jsonify({
                    'ok': True,
                    'run_id': run_id,
                    'status': run['status'],
                    'progress': run['progress'],
                    '_meta': meta,
                })
            results = run.get('results')
            if results and isinstance(results, dict):
                # _naive_equity_fallback returns { status: 'done', data: { matchups, street, ... } }
                # Flatten so frontend sees res.status === 'done' and res.data.matchups
                rstatus = results.get('status', 'done')
                rdata = results.get('data', results)
                # Merge engine-level _meta if the equity engine on :5002 returned one.
                # Engine fields are authoritative for script/final_variant;
                # route-level fields are authoritative for requested_variant.
                if isinstance(results, dict) and '_meta' in results:
                    engine_meta = results['_meta']
                    # Keys that the engine is authoritative for (script execution details)
                    engine_keys = {'detected_variant', 'final_variant', 'script_name',
                                   'script_path', 'variant_source', 'hand_card_count',
                                   'hand_count', 'job_id'}
                    for k in engine_keys:
                        if k in engine_meta:
                            meta[k] = engine_meta[k]
                    # Add any novel engine keys not already in route-level meta
                    for k, v in engine_meta.items():
                        if k not in meta:
                            meta[k] = v
                return jsonify({
                    'ok': True,
                    'run_id': run_id,
                    'status': rstatus,
                    'progress': 100,
                    'data': rdata,
                    '_meta': meta,
                })
            # Fallback: wrap legacy format
            return jsonify({
                'ok': True,
                'run_id': run_id,
                'status': 'done' if results else 'completed',
                'progress': 100,
                'data': results if results else {},
                '_meta': meta,
            })

    @app.route('/api/rng/generate', methods=['POST'])
    def rng_generate():
        """
        Generate random equity samples for a given poker variant/street.
        
        Request:
        {
            "variant": "plo",          # "plo", "plo6", "holdem"
            "table_size": 6,           # number of players
            "street": "preflop",       # "preflop", "flop", "turn", "river"
            "sample_count": 100        # number of random scenarios
        }
        
        Returns:
        {
            "ok": true,
            "samples": [...],
            "variant": "plo",
            "table_size": 6,
            "street": "preflop"
        }
        """
        try:
            data = request.get_json(force=True)
            if not data:
                return jsonify({'ok': False, 'error': 'No data provided'}), 400

            variant = data.get('variant', 'plo')
            table_size = int(data.get('table_size', 6))
            street = data.get('street', 'preflop')
            sample_count = min(int(data.get('sample_count', 100)), 1000)

            # Build random hand samples — support all PLO variants
            cards_per_player = {'plo': 4, 'plo4': 4, 'plo5': 5, 'plo6': 6, 'plo7': 7, 'holdem': 2}.get(variant, 4)
            board_cards_needed = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}.get(street, 0)

            samples = []
            deck = [f"{r}{s}" for r in 'AKQJT98765432' for s in 'shdc']

            for _ in range(sample_count):
                random.shuffle(deck)
                idx = 0
                hands = []
                for p in range(table_size):
                    hand = ''.join(deck[idx:idx + cards_per_player])
                    hands.append(hand)
                    idx += cards_per_player
                board = ''.join(deck[idx:idx + board_cards_needed])

                samples.append({
                    'hands': hands,
                    'board': board,
                })

            return jsonify({
                'ok': True,
                'samples': samples,
                'variant': variant,
                'table_size': table_size,
                'street': street,
                'sample_count': len(samples),
            })

        except Exception as e:
            logger.error(f"[RNG] Generate failed: {e}")
            return jsonify({'ok': False, 'error': str(e)}), 500

    # ── Phase 3: POST /api/decide — runs engine + injects action in one call ──
    @app.route('/api/decide', methods=['POST'])
    def equity_decide():
        """Run equity calculation AND inject the resulting action into Vivaldi.
        
        Accepts same payload as /api/run plus:
          - decision_mode: "auto" (default), "conservative", "aggressive"
          - tab_id: optional CDP tab ID (auto-discovers Goldrush tab if omitted)
        
        Returns combined equity result + action injection result.
        """
        try:
            data = request.get_json(force=True)
            if not data:
                return jsonify({'ok': False, 'error': 'No data provided'}), 400

            # ── Step 1: Run equity calculation (reuse the same pipeline as /api/run) ──
            raw_hands = data.get('hands', [])
            names_raw = data.get('names', '')
            board = data.get('board', '')
            samples = min(int(data.get('samples', 10000)), 100000)
            variant = data.get('variant', '')
            game = data.get('game', 'omaha')
            decision_mode = data.get('decision_mode', 'auto')
            tab_id = data.get('tab_id')

            # Parse hands
            if isinstance(raw_hands, str):
                lines = [l.strip() for l in raw_hands.split('\n') if l.strip()]
                # Last line might be board
                last_line = lines[-1] if lines else ''
                if len(last_line) in (6, 8, 10) and len(lines) >= 3:
                    board = last_line
                    hands = lines[:-1]
                else:
                    hands = lines
            else:
                hands = raw_hands
                if isinstance(hands, list) and len(hands) >= 3:
                    last = hands[-1]
                    if len(last) in (6, 8, 10):
                        board = last
                        hands = hands[:-1]

            if not hands or len(hands) < 2:
                return jsonify({'ok': False, 'error': 'Need at least 2 hands'}), 400

            # ── Step 2: Compute equity (try direct engine → fallback) ──
            if game and variant:
                v = variant.lower()
            else:
                v = data.get('variant', '')
            if v:
                if 'plo7' in v: game = 'plo7'
                elif 'plo6' in v: game = 'plo6'
                elif 'plo5' in v: game = 'plo5'
                elif 'plo' in v: game = 'plo'
                elif 'holdem' in v or 'nlh' in v: game = 'holdem'
                else: game = game or 'omaha'
            else:
                game = game or 'omaha'

            result = _naive_equity_fallback(hands, board, samples, game)

            # ── Step 3: Inject action via CDP ──
            action_result = None
            if _action_router:
                try:
                    action_result = _action_router.decide_and_act(
                        result,
                        tab_id=tab_id,
                        decision_mode=decision_mode,
                    )
                    logger.info('[DECIDE] Action injected: %s', action_result.get('decision'))
                except Exception as ae:
                    logger.warning('[DECIDE] Action injection failed: %s', ae)
                    action_result = {'ok': False, 'error': str(ae)}
            else:
                action_result = {'ok': False, 'error': 'ActionRouter not available (CDP disabled)'}

            return jsonify({
                'ok': True,
                'equity': result,
                'action': action_result,
                'decision_mode': decision_mode,
            })

        except Exception as e:
            logger.error(f"[DECIDE] Failed: {e}")
            return jsonify({'ok': False, 'error': str(e)}), 500


def _naive_equity_fallback(hands, board, samples, game, names=None):
    """
    Naive Monte Carlo equity fallback when the external engine is unreachable.
    Works for Omaha (all variants) by dealing random cards and evaluating.
    Returns { status: 'done', data: { matchups, street, runtime, cores, pairs_evaluated } }
    matching the frontend ResultsTable contract.
    """
    import random
    if names is None:
        names = {}

    deck = [f"{r}{s}" for r in 'AKQJT98765432' for s in 'shdc']
    # Remove known cards
    known = set()
    for h in hands:
        for i in range(0, len(h), 2):
            known.add(h[i:i+2])
    if board:
        for i in range(0, len(board), 2):
            known.add(board[i:i+2])
    available = [c for c in deck if c not in known]

    # Support all PLO variants: plo/plo4=4, plo5=5, plo6=6, plo7=7, holdem=2
    cards_per_hand = {'omaha': 4, 'plo': 4, 'plo4': 4, 'plo5': 5, 'plo6': 6, 'plo7': 7}.get(game, 2)

    player_shares = [0.0] * len(hands)
    total = 0

    # Hand ranks for evaluation
    rank_order = '23456789TJQKA'
    rank_values = {r: i for i, r in enumerate(rank_order)}

    def _eval_5(cards):
        """Simple 5-card hand evaluator - returns a comparable score."""
        ranks = sorted([rank_values[c[0]] for c in cards], reverse=True)
        suits = [c[1] for c in cards]

        is_flush = any(suits.count(s) >= 5 for s in set(suits))
        rank_counts = {}
        for r in ranks:
            rank_counts[r] = rank_counts.get(r, 0) + 1
        counts = sorted(rank_counts.values(), reverse=True)

        is_straight = False
        straight_high = 0
        unique_ranks = sorted(set(ranks), reverse=True)
        for i in range(len(unique_ranks) - 4):
            if unique_ranks[i] - unique_ranks[i+4] == 4:
                is_straight = True
                straight_high = unique_ranks[i]
                break
        # Check A-2-3-4-5 wheel
        if set([12, 0, 1, 2, 3]).issubset(set(ranks)):
            is_straight = True
            straight_high = 3

        # Score: hand_type (8 bits) + kickers
        if is_flush and is_straight:
            return (8 << 20) | (straight_high << 16)
        elif counts == [4, 1]:
            quads_rank = [r for r, c in rank_counts.items() if c == 4][0]
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return (7 << 20) | (quads_rank << 16) | (kicker << 12)
        elif counts == [3, 2]:
            trips_rank = [r for r, c in rank_counts.items() if c == 3][0]
            pair_rank = [r for r, c in rank_counts.items() if c == 2][0]
            return (6 << 20) | (trips_rank << 16) | (pair_rank << 12)
        elif is_flush:
            score = (5 << 20)
            for i, r in enumerate(ranks[:5]):
                score |= r << (16 - i * 4)
            return score
        elif is_straight:
            return (4 << 20) | (straight_high << 16)
        elif counts == [3, 1, 1]:
            trips_rank = [r for r, c in rank_counts.items() if c == 3][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            score = (3 << 20) | (trips_rank << 16)
            for i, k in enumerate(kickers[:2]):
                score |= k << (12 - i * 4)
            return score
        elif counts == [2, 2, 1]:
            pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            score = (2 << 20) | (pairs[0] << 16) | (pairs[1] << 12) | (kicker << 8)
            return score
        elif counts == [2, 1, 1, 1]:
            pair_rank = [r for r, c in rank_counts.items() if c == 2][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            score = (1 << 20) | (pair_rank << 16)
            for i, k in enumerate(kickers[:3]):
                score |= k << (12 - i * 4)
            return score
        else:
            score = 0
            for i, r in enumerate(ranks[:5]):
                score |= r << (16 - i * 4)
            return score

    total_cards_per_hand = {'omaha': 4, 'plo': 4, 'plo4': 4, 'plo5': 5, 'plo6': 6, 'plo7': 7}.get(game, 2)
    cards_per_player = total_cards_per_hand
    board_cards_known = list(board[i:i+2] for i in range(0, len(board), 2)) if board else []

    # Validate that each provided hand has the correct number of cards
    valid_hands = []
    for h in hands:
        if len(h) // 2 == cards_per_player:
            valid_hands.append(h)
        else:
            # Partial/empty hand — will be filled with random cards
            valid_hands.append(h)

    for _ in range(min(samples, 5000)):
        # Shuffle the available (non-known) cards for this iteration
        random.shuffle(available)
        avail_idx = 0

        # Use known hands directly; fill unknown/partial hands from available pool
        player_cards = []
        for h in valid_hands:
            known_hole = list(h[i:i+2] for i in range(0, len(h), 2))
            if len(known_hole) == cards_per_player:
                # Fully specified hand — use as-is
                player_cards.append(known_hole)
            else:
                # Partial or empty hand — fill from available
                filled = [c for c in known_hole if c]
                while len(filled) < cards_per_player and avail_idx < len(available):
                    card = available[avail_idx]
                    avail_idx += 1
                    if card not in filled:
                        filled.append(card)
                player_cards.append(filled)

        # Deal remaining board cards from available pool
        board_cards = board_cards_known[:]
        while len(board_cards) < 5 and avail_idx < len(available):
            card = available[avail_idx]
            avail_idx += 1
            if card not in board_cards and card not in [c for pc in player_cards for c in pc]:
                board_cards.append(card)

        # If any player didn't get a full hand or board is incomplete, skip this iteration
        if any(len(pc) != cards_per_player for pc in player_cards) or len(board_cards) < 5:
            continue

        best_scores = []
        for pc in player_cards:
            is_omaha = game in ('omaha', 'plo', 'plo4', 'plo5', 'plo6', 'plo7')
            if is_omaha:
                # Omaha rule: use exactly 2 hole cards + 3 board cards
                best = 0
                from itertools import combinations
                for hc in combinations(pc, 2):
                    for bc in combinations(board_cards, 3):
                        score = _eval_5(list(hc) + list(bc))
                        if score > best:
                            best = score
                best_scores.append(best)
            else:
                # Holdem: best 5 of 7
                best = 0
                from itertools import combinations
                for c5 in combinations(pc + board_cards, 5):
                    score = _eval_5(list(c5))
                    if score > best:
                        best = score
                best_scores.append(best)

        total += 1
        max_score = max(best_scores)
        tied_players = [i for i, s in enumerate(best_scores) if s == max_score]
        share = 1.0 / len(tied_players)
        for i in tied_players:
            player_shares[i] += share

    total_pots = total if total > 0 else 1
    equities = [round((player_shares[i] / total_pots) * 100, 1) for i in range(len(hands))]

    # Build matchups for frontend ResultsTable compatibility
    # Matchups are pair-wise comparisons: (i, j) with i < j
    # "underdog" = lower equity, "favourite" = higher equity
    matchups = []
    pair_num = 1
    for i in range(len(hands)):
        for j in range(i + 1, len(hands)):
            eq_i = equities[i]
            eq_j = equities[j]
            p1_name = names.get(i + 1, f'P{i+1}')
            p2_name = names.get(j + 1, f'P{j+1}')
            if eq_i <= eq_j:
                matchups.append({
                    'pair_num': pair_num,
                    'underdog_hand': hands[i],
                    'underdog_name': p1_name,
                    'favourite_hand': hands[j],
                    'favourite_name': p2_name,
                    'und_raw': eq_i,
                    'und_real': eq_i,
                    'disparity': round(abs(eq_j - eq_i), 1),
                    'fav_raw': eq_j,
                    'fav_real': eq_j,
                })
            else:
                matchups.append({
                    'pair_num': pair_num,
                    'underdog_hand': hands[j],
                    'underdog_name': p2_name,
                    'favourite_hand': hands[i],
                    'favourite_name': p1_name,
                    'und_raw': eq_j,
                    'und_real': eq_j,
                    'disparity': round(abs(eq_i - eq_j), 1),
                    'fav_raw': eq_i,
                    'fav_real': eq_i,
                })
            pair_num += 1

    # Determine street from board length
    board_len = len(board) // 2 if board else 0
    street_map = {0: 'preflop', 3: 'flop', 4: 'turn', 5: 'river'}
    street = street_map.get(board_len, 'preflop')

    return {
        'status': 'done',
        'data': {
            'matchups': matchups,
            'street': street,
            'runtime': f'{total} samples',
            'cores': 1,
            'pairs_evaluated': len(matchups),
        },
        'equities': equities,
        'hands': hands,
        'board': board,
        'samples': total,
        'game': game,
        'method': 'naive_fallback',
        'win_counts': [],
        'tie_counts': [],
    }

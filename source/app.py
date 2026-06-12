# import eventlet  # disabled: using gthread worker
# eventlet.monkey_patch()  # disabled: using gthread worker

# -*- coding: utf-8 -*-
"""
PLO Equity Engine - Flask Backend
==================================
Serves the React frontend (built to ./static/) and provides:
  GET  /                     - serves React app
  POST /api/run              - start an equity engine job
  GET  /api/stream/<id>      - SSE stream of job output (live log)
  GET  /api/results/<id>     - structured JSON results (after job complete)
  POST /api/validate         - validate a hands file, return all issues
  POST /api/fix              - apply a single card fix, return updated state
  GET  /api/download/<id>    - download plain-text results
  GET  /create               - create a collaborative session

Run:
  gunicorn -w 1 -k eventlet --bind 127.0.0.1:8080 app:app
"""

import os
import sys
import re
import uuid
import json
import queue
import time
import hashlib
import secrets
import threading
import subprocess
import tempfile
import logging
from pathlib import Path
from datetime import datetime as dt

from flask import (Flask, request, jsonify, Response,
                   send_file, abort, send_from_directory)
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_cors import CORS

from result_parser import parse_results
from ai_guard import (
    chunk_delta, normalize_chunk, compute_payload_hash, is_duplicate_payload,
    make_idempotency_key, idempotency_get, idempotency_set,
    enforce_token_limits, enforce_budgets, acquire_source_lease,
    release_source_lease, check_hard_refusals, retry_execute,
    audit_log, budget_status, estimate_tokens, GuardReject,
)
from dirk_tracker import init_dirk_tracker, register_dirk_routes

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "plo-equity-secret-change-me")
CORS(app)

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ── Auth ─────────────────────────────────────────────────────────────────────
_PW = lambda p: hashlib.sha256(p.encode()).hexdigest()
AUTH_USERS = {
    'admin':  _PW('PokerPass12345'),
    'dirk':   _PW('id260375@@'),
    'warren': _PW('Gemm@143'),
    'ninja':  _PW('Gemm@143'),
}
active_tokens = {}   # {token: username}
init_dirk_tracker(app, active_tokens)
register_dirk_routes(app)

@app.route("/api/health")
def api_health():
    from datetime import datetime as _dt
    return jsonify({"ok": True, "version": "plo-engine-1.0", "environment": "production", "timestamp": _dt.utcnow().isoformat()})

@app.route('/api/login', methods=['POST'])
def login():
    data     = request.get_json(force=True)
    username = (data.get('username') or '').strip().lower()
    password = (data.get('password') or '')
    ph       = hashlib.sha256(password.encode()).hexdigest()
    if username not in AUTH_USERS or AUTH_USERS[username] != ph:
        return jsonify({'ok': False, 'error': 'Invalid username or password'}), 401
    token = secrets.token_hex(32)
    active_tokens[token] = username
    return jsonify({'ok': True, 'token': token, 'username': username})

@app.route('/api/auth/verify', methods=['GET'])
def auth_verify():
    token = request.headers.get('X-Auth-Token', '')
    if token and token in active_tokens:
        return jsonify({'ok': True, 'username': active_tokens[token]})
    return jsonify({'ok': False, 'error': 'Unauthorized'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    token = request.headers.get('X-Auth-Token', '')
    active_tokens.pop(token, None)
    return jsonify({'ok': True})

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(os.environ.get("PLO_SCRIPTS_DIR", Path(__file__).parent / "scripts"))
UPLOAD_DIR  = Path(tempfile.gettempdir()) / "plo_jobs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

VARIANTS = {
    "plo4-6max": {"players": 6, "hole_cards": 4, "script": "plo4-6max.py"},
    "plo4-8max": {"players": 8, "hole_cards": 4, "script": "plo4-8max.py"},
    "plo4-9max": {"players": 9, "hole_cards": 4, "script": "plo4-9max.py"},
    "plo5-5max": {"players": 5, "hole_cards": 5, "script": "plo5-5max.py"},
    "plo5-6max": {"players": 6, "hole_cards": 5, "script": "plo5-6max.py"},
    "plo5-8max": {"players": 8, "hole_cards": 5, "script": "plo5-8max.py"},
    "plo5-9max": {"players": 9, "hole_cards": 5, "script": "plo5-9max.py"},
    "plo6-5max": {"players": 5, "hole_cards": 6, "script": "plo6-5max.py"},
    "plo6-6max": {"players": 6, "hole_cards": 6, "script": "plo6-6max.py"},
    "plo6-8max": {"players": 8, "hole_cards": 6, "script": "plo6-8max.py"},
    "plo7-5max": {"players": 5, "hole_cards": 7, "script": "plo7-5max.py"},
    "plo7-6max": {"players": 6, "hole_cards": 7, "script": "plo7-6max.py"},
}

# In-memory stores
jobs         = {}   # {job_id: {"q": Queue, "done": bool, "lines": [], "results": dict|None}}

session_data = {}   # {session_id: {...}}

# ── Card / tokenisation helpers ───────────────────────────────────────────────
RANK_SET    = set("AKQJT98765432")
VALID_SUITS = {"s", "h", "d", "c"}

def tokenise(raw: str) -> list:
    raw = raw.strip().upper()
    tokens, i = [], 0
    while i < len(raw):
        if raw[i:i+2] == "10":
            tokens.append(raw[i:i+3]); i += 3
        else:
            tokens.append(raw[i:i+2]); i += 2
    return tokens

def validate_token(tok: str):
    tok = tok.strip().upper()
    if tok[:2] == "10":
        r_raw = "T"; su_raw = tok[2:3].lower() if len(tok) > 2 else ""
    elif len(tok) >= 2:
        r_raw = tok[0]; su_raw = tok[1].lower()
    else:
        return None, "rank", f"token too short: '{tok}'"
    rank = "T" if r_raw == "10" else r_raw
    if rank not in RANK_SET:
        return None, "rank", f"unknown rank '{r_raw}'"
    if su_raw not in VALID_SUITS:
        return None, "suit", f"unknown suit '{su_raw}'"
    return rank + su_raw, None, None

def strip_name(line: str, hole_cards: int):
    line = line.strip()
    for delim in ("=", "+"):
        if delim in line:
            parts = line.split(delim, 1)
            if len(tokenise(parts[0].strip())) == hole_cards:
                return parts[0].strip(), parts[1].strip() if len(parts) > 1 else None
    parts = line.split(None, 1)
    if len(parts) > 1 and len(tokenise(parts[0].strip())) == hole_cards:
        return parts[0].strip(), parts[1].strip()
    return line, None

def parse_name_mapping(text: str) -> dict:
    m = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        left, _, right = line.partition("=")
        k, v = left.strip(), right.strip()
        if k and v:
            m[k] = v
    return m

def strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

# ── React frontend ────────────────────────────────────────────────────────────
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    # API and Socket.IO routes are handled above — don't catch them here
    if path.startswith("api/") or path.startswith("socket.io"):
        abort(404)
    # Static assets are served directly by nginx via alias block.
    # Flask must NOT intercept them — returning 404 lets nginx handle it.
    # (nginx location /assets/ has higher priority but if Flask is reached, skip.)
    if path.startswith("assets/"):
        abort(404)
    full = os.path.join(app.static_folder, path)
    if path and os.path.exists(full):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

# ── /api/run ──────────────────────────────────────────────────────────────────

def detect_variant_simple(hands_text):
    """Detect variant from hand length and line count.
    Returns variant key like 'plo5-6max' based on card count and player count."""
    lines = [l.strip() for l in hands_text.splitlines() if l.strip()]
    if not lines:
        return None

    # Find the first line that looks like a hand (not a board line)
    # Board lines are shorter: 6 chars (flop), 8 chars (turn), 10 chars (river)
    # But PLO4 hands are also 8 chars — disambiguate by checking if ALL lines are same length
    hand_lengths = {}
    for line in lines:
        n = len(line)
        hand_lengths[n] = hand_lengths.get(n, 0) + 1

    # Determine hand length: the length that appears most frequently (board lines are fewer)
    # For PLO4 (8 chars) vs board (6/8/10): if 8 is the most common, it's a hand
    if not hand_lengths:
        return None

    most_common_len = max(hand_lengths, key=hand_lengths.get)

    # Map hand length to variant prefix
    variant_prefix = {8: 'plo4', 10: 'plo5', 12: 'plo6', 14: 'plo7'}.get(most_common_len)
    if not variant_prefix:
        return None

    # Count actual hand lines (lines matching the hand length)
    hand_count = sum(1 for l in lines if len(l) == most_common_len)

    # Pick the smallest valid variant that fits the detected hand count.
    # VARIANTS keys are like 'plo4-6max', 'plo5-5max', etc.
    # Find all valid max-player values for this variant prefix, sorted ascending.
    available_max = sorted(
        int(k.split('-')[1].replace('max', ''))
        for k in VARIANTS
        if k.startswith(variant_prefix + '-')
    )
    # Default to largest available if no match (should not happen)
    max_count = 9
    for mx in available_max:
        if mx >= hand_count:
            max_count = mx
            break
    else:
        # Fallback: use largest available variant
        if available_max:
            max_count = available_max[-1]

    return f'{variant_prefix}-{max_count}max'

@app.route("/api/run", methods=["POST"])
def run_engine():
    data    = request.get_json(force=True)
    variant = (data.get("variant") or "").strip().lower()
    requested_variant = variant  # snapshot for _meta tracer before any override
    hands   = data.get("hands", "")
    names   = data.get("names", "")

    # Normalize: frontend may send hands as list or string
    if isinstance(hands, list):
        hands = "\n".join(str(h) for h in hands)
    if isinstance(names, list):
        names = "\n".join(str(n) for n in names)

    # Preserve the explicitly-selected variant so the exact UI-chosen script runs
    # (e.g. plo6-8max -> plo6-8max.py).  Auto-detect from the hands only when no
    # valid variant was supplied, or when the hands clearly indicate a different
    # PLO size than the selection (hole-card count is authoritative, so we never
    # feed wrong-size hands to a script).
    detected = detect_variant_simple(hands)
    if variant in VARIANTS:
        if detected and detected.split("-")[0] != variant.split("-")[0]:
            variant = detected
    else:
        variant = detected or "plo5-6max"

    if variant not in VARIANTS:
        return jsonify({"error": f"Unknown variant '{variant}'"}), 400
    if not hands.strip():
        return jsonify({"error": "No hands provided"}), 400

    script_path = SCRIPTS_DIR / VARIANTS[variant]["script"]
    if not script_path.exists():
        return jsonify({"error": f"Script not found: {script_path}"}), 500

    job_id  = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    hands_file = job_dir / "hands.txt"

    # ── Board normalization: scripts expect flop (3 cards/6 chars) on one
    #     line and turn (1 card/2 chars) on the next.  Combined board lines
    #     (8 chars = turn, 10 chars = river) are split before writing.
    lines_out = hands.split('\n')
    if lines_out:
        last = lines_out[-1].strip()
        last_len = len(last)
        other_lines = [l.strip() for l in lines_out[:-1] if l.strip()]
        if other_lines:
            hand_len = len(other_lines[0])
            if last_len in (8, 10) and last_len != hand_len:
                flop = last[:6]        # first 3 cards
                rest = last[6:]
                extra = [rest[i:i+2] for i in range(0, len(rest), 2)]
                lines_out[-1:] = [flop] + extra
                hands = '\n'.join(lines_out)

    hands_file.write_text(hands, encoding="utf-8")

    cmd = [sys.executable, str(script_path), str(hands_file)]

    if names.strip():
        names_file = job_dir / "names.txt"
        names_file.write_text(names, encoding="utf-8")
        cmd += ["--names", str(names_file)]

    q = queue.Queue()

    # Count hand lines (non-board lines matching expected card count)
    hand_lines = [l.strip() for l in hands.strip().split('\n') if l.strip()]
    cfg = VARIANTS[variant]
    hole_cards_count = cfg["hole_cards"]
    hand_count = sum(1 for l in hand_lines if len(l) == hole_cards_count * 2)

    # Determine variant source for _meta tracer
    if requested_variant in VARIANTS:
        if detected and detected.split("-")[0] != requested_variant.split("-")[0]:
            v_source = "corrected_conflict"
        else:
            v_source = "preserved"
    else:
        v_source = "detected" if detected else "fallback"

    jobs[job_id] = {
        "q": q, "done": False, "lines": [], "results": None,
        "_meta": {
            "requested_variant": requested_variant,
            "detected_variant": detected,
            "final_variant": variant,
            "script_path": str(script_path),
            "script_name": script_path.name,
            "hand_card_count": hole_cards_count,
            "hand_count": hand_count,
            "variant_source": v_source,
            "job_id": job_id,
        },
    }

    def run():
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            for line in proc.stdout:
                clean = strip_ansi(line)
                jobs[job_id]["lines"].append(clean)
                q.put(clean)
            proc.wait(timeout=30)
            # Parse structured results now that the job is done
            full_text = "".join(jobs[job_id]["lines"])
            try:
                jobs[job_id]["results"] = parse_results(full_text)
            except Exception as parse_err:
                jobs[job_id]["results"] = {"error": str(parse_err)}
            q.put(f"\n__EXIT__{proc.returncode}__\n")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            q.put("\n__ERROR__Engine subprocess timed out after 30s__\n")
        except Exception as e:
            q.put(f"\n__ERROR__{e}__\n")
        finally:
            # Order matters: write disk first, then memory, then done flag
            results_obj = jobs[job_id].get("results")
            if results_obj:
                try:
                    (job_dir / "results.json").write_text(
                        json.dumps(results_obj, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            # Also persist _meta alongside results
            meta_obj = jobs[job_id].get("_meta")
            if meta_obj:
                try:
                    (job_dir / "meta.json").write_text(
                        json.dumps(meta_obj, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            jobs[job_id]["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})

# ── /api/stream/<job_id>  SSE ─────────────────────────────────────────────────
@app.route("/api/stream/<job_id>")
def stream(job_id):
    if job_id not in jobs:
        abort(404)
    job = jobs[job_id]

    def generate():
        idle_ticks = 0
        MAX_IDLE = 10  # 10 x 30s = 5 min max idle before giving up
        while True:
            try:
                line = job["q"].get(timeout=30)
                idle_ticks = 0
                yield f"data: {json.dumps(line)}\n\n"
                if "__EXIT__" in line or "__ERROR__" in line:
                    # Keep alive so client processes __EXIT__ before server closes
                    import time; time.sleep(2)
                    break
            except queue.Empty:
                if job.get("done"):
                    yield 'data: "__TIMEOUT__"\n\n'
                    break
                idle_ticks += 1
                if idle_ticks >= MAX_IDLE:
                    yield 'data: "__TIMEOUT__"\n\n'
                    break
                # Job still running - send SSE keepalive comment
                yield ": keepalive\n\n" 

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── /api/results/<job_id>  Structured JSON ────────────────────────────────────
@app.route("/api/results/<job_id>")
def results(job_id):
    # 1. in-memory first
    job = jobs.get(job_id)
    if job and job.get("done") and job.get("results") is not None:
        return jsonify({
            "status": "done",
            "data": job["results"],
            "_meta": job.get("_meta"),
        })

    # 2. disk fallback
    result_file = UPLOAD_DIR / job_id / "results.json"
    meta_file = UPLOAD_DIR / job_id / "meta.json"
    if result_file.exists():
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            resp = {"status": "done", "data": data}
            if meta_file.exists():
                try:
                    resp["_meta"] = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return jsonify(resp)
        except Exception as e:
            return jsonify({"status": "error", "error": f"bad results.json: {e}"}), 500

    # 3. done but no structured results (e.g. empty batch)
    if job and job.get("done"):
        return jsonify({
            "status": "done",
            "data": job.get("results") or {"matchups": [], "error": "No results produced"},
            "_meta": job.get("_meta"),
        })

    # 4. still running?
    if job and not job.get("done"):
        return jsonify({"status": "running", "_meta": job.get("_meta")}), 202

    # 5. not found
    return jsonify({"status": "error", "error": "job not found"}), 404

# ── /api/validate ─────────────────────────────────────────────────────────────
@app.route("/api/validate", methods=["POST"])
def validate():
    data      = request.get_json(force=True)
    variant   = data.get("variant", "plo5-6max")
    hands_txt = data.get("hands", "")
    names_txt = data.get("names", "")

    if variant not in VARIANTS:
        return jsonify({"error": f"Unknown variant '{variant}'"}), 400

    cfg        = VARIANTS[variant]
    n_players  = cfg["players"]
    hole_cards = cfg["hole_cards"]
    name_map   = parse_name_mapping(names_txt)

    ne_lines = [l.strip() for l in hands_txt.splitlines() if l.strip()]

    if len(ne_lines) < n_players:
        return jsonify({"error": f"Need at least {n_players} non-empty lines, got {len(ne_lines)}"}), 400

    players = []
    for idx in range(n_players):
        line = ne_lines[idx]
        hand_raw, inline_name = strip_name(line, hole_cards)
        map_key      = f"Player{idx+1}"
        display_name = name_map.get(map_key) or inline_name or map_key
        tokens       = tokenise(hand_raw)
        cards        = [validate_token(tok)[0] for tok in tokens]
        players.append({
            "slot": idx, "display_name": display_name,
            "hand_raw": hand_raw, "inline_name": inline_name,
            "tokens": tokens, "cards": cards,
        })

    issues = []
    for p in players:
        for pos, tok in enumerate(p["tokens"]):
            _, etype, edetail = validate_token(tok)
            if etype:
                issues.append({
                    "type": "malformed", "slot": p["slot"],
                    "player_name": p["display_name"], "hand_raw": p["hand_raw"],
                    "position": pos, "token": tok,
                    "error_type": etype, "detail": edetail,
                })

    seen = {}
    for p in players:
        for pos, cs in enumerate(p["cards"]):
            if cs:
                seen.setdefault(cs, []).append(
                    {"slot": p["slot"], "name": p["display_name"],
                     "hand_raw": p["hand_raw"], "pos": pos}
                )
    for cs, owners in seen.items():
        if len(owners) > 1:
            issues.append({"type": "duplicate", "card": cs, "owners": owners})

    return jsonify({
        "issues":      issues,
        "players":     [{"slot": p["slot"], "display_name": p["display_name"],
                          "hand_raw": p["hand_raw"], "tokens": p["tokens"],
                          "cards": p["cards"]} for p in players],
        "board_lines": ne_lines[n_players:],
        "clean":       len(issues) == 0,
    })

# ── /api/fix ──────────────────────────────────────────────────────────────────
@app.route("/api/fix", methods=["POST"])
def fix():
    data        = request.get_json(force=True)
    variant     = data.get("variant", "plo5-6max")
    hands_txt   = data.get("hands", "")
    slot        = data.get("slot")
    position    = data.get("position")
    replacement = data.get("replacement", "").strip().upper()

    if variant not in VARIANTS:
        return jsonify({"error": "Unknown variant"}), 400

    hole_cards = VARIANTS[variant]["hole_cards"]

    toks = tokenise(replacement)
    if len(toks) != 1:
        return jsonify({"error": "Enter exactly one card (e.g. Ah)"}), 400
    normed, etype, edetail = validate_token(toks[0])
    if etype:
        return jsonify({"error": f"Invalid card: {edetail}"}), 400

    raw_lines = hands_txt.splitlines(keepends=True)
    ne_idx    = [i for i, l in enumerate(raw_lines) if l.strip()]

    if slot >= len(ne_idx):
        return jsonify({"error": "Slot out of range"}), 400

    line_idx = ne_idx[slot]
    line     = raw_lines[line_idx].rstrip("\n")
    hand_raw, inline_name = strip_name(line, hole_cards)
    tokens   = tokenise(hand_raw)

    if position >= len(tokens):
        return jsonify({"error": "Position out of range"}), 400

    tokens[position] = normed
    new_hand_raw = "".join(tokens)
    new_line     = (f"{new_hand_raw} {inline_name}" if inline_name else new_hand_raw) + "\n"
    raw_lines[line_idx] = new_line

    return jsonify({"hands": "".join(raw_lines)})

# ── /api/download/<job_id> ────────────────────────────────────────────────────
@app.route("/api/download/<job_id>")
def download(job_id):
    if job_id not in jobs:
        abort(404)
    content = "".join(jobs[job_id].get("lines", []))
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    tmp.write(content); tmp.close()
    return send_file(tmp.name, as_attachment=True,
                     download_name=f"plo_results_{job_id[:8]}.txt")

# ── /api/run-batch  Batch Equity Engine (up to 500 samples) ──────────────────
MAX_BATCH_SIZE = 500

@app.route("/api/run-batch", methods=["POST"])
def run_batch():
    """
    Run multiple hand samples through the equity engine.
    Samples are separated by blank lines in the hands text.
    If >1 sample, returns only the sample with the biggest disparity.
    Streams progress via SSE at /api/stream/<batch_id>.
    """
    data    = request.get_json(force=True)
    variant = data.get("variant", "plo5-6max")
    hands   = data.get("hands", "")
    names   = data.get("names", "")

    # Handle names as list (from JSON array) or string
    if isinstance(names, list):
        names = "\n".join(str(n) for n in names if n)
    # Handle hands as list (from JSON array) or string
    if isinstance(hands, list):
        hands = "\n\n".join(str(h) for h in hands if h)

    if variant not in VARIANTS:
        return jsonify({"error": f"Unknown variant '{variant}'"}), 400
    if not hands or not hands.strip():
        return jsonify({"error": "No hands provided"}), 400

    # Split into samples by blank lines (one or more empty/whitespace-only lines)
    import re as _re
    raw_samples = [s.strip() for s in _re.split(r'\n\s*\n', hands.strip()) if s.strip()]

    if len(raw_samples) > MAX_BATCH_SIZE:
        return jsonify({"error": f"Max {MAX_BATCH_SIZE} samples allowed, got {len(raw_samples)}"}), 400

    if len(raw_samples) == 0:
        return jsonify({"error": "No valid samples found"}), 400

    # If only 1 sample, redirect to normal run
    if len(raw_samples) == 1:
        data["hands"] = raw_samples[0]
        # Forward to the regular run endpoint logic
        return _run_single(variant, raw_samples[0], names)

    batch_id = str(uuid.uuid4())
    jobs[batch_id] = {
        "q": queue.Queue(), "done": False, "lines": [],
        "results": None, "batch": True,
        "total_samples": len(raw_samples), "completed_samples": 0,
    }

    script_path = SCRIPTS_DIR / VARIANTS[variant]["script"]
    if not script_path.exists():
        return jsonify({"error": f"Script not found: {script_path}"}), 500

    def run_batch_worker():
        all_best       = []
        all_top_pairs  = []
        TOP_N          = 5
        first_street   = None

        q = jobs[batch_id]["q"]
        q.put(f"Starting batch: {len(raw_samples)} samples\n")

        for i, sample_hands in enumerate(raw_samples):
            q.put(f"\n--- Sample {i+1}/{len(raw_samples)} ---\n")

            # Write hands to temp file
            sample_dir = UPLOAD_DIR / batch_id / f"sample_{i}"
            sample_dir.mkdir(parents=True, exist_ok=True)
            hands_file = sample_dir / "hands.txt"
            hands_file.write_text(sample_hands, encoding="utf-8")

            cmd = [sys.executable, str(script_path), str(hands_file)]
            if names.strip():
                names_file = sample_dir / "names.txt"
                names_file.write_text(names, encoding="utf-8")
                cmd += ["--names", str(names_file)]

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                sample_lines = []
                for line in proc.stdout:
                    clean = strip_ansi(line)
                    sample_lines.append(clean)
                    q.put(clean)
                proc.wait(timeout=30)

                full_text = "".join(sample_lines)
                try:
                    parsed = parse_results(full_text)
                except Exception:
                    parsed = {"matchups": []}

                # Pick the matchup with the largest |disparity| in this sample
                if parsed.get("matchups"):
                    # Sort ascending: most negative disparity = strongest BUY signal first
                    sorted_pairs = sorted(parsed["matchups"], key=lambda m: m["disparity"])
                    best_m = sorted_pairs[0]
                    best_m["sample_num"] = i + 1
                    all_best.append(best_m)
                    if first_street is None:
                        first_street = parsed.get("street", "")
                    # Keep top-N for frequency analysis (copy to avoid mutation)
                    for pair in sorted_pairs[:TOP_N]:
                        pc = dict(pair)
                        pc["sample_num"] = i + 1
                        all_top_pairs.append(pc)
                    q.put(f"  -> Best disparity in sample {i+1}: {best_m['disparity']:.4f}%\n")
                else:
                    q.put(f"  -> No matchups found in sample {i+1}\n")

            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                q.put(f"  -> TIMEOUT in sample {i+1}: engine subprocess timed out after 30s\n")
            except Exception as e:
                q.put(f"  -> ERROR in sample {i+1}: {str(e)}\n")

            jobs[batch_id]["completed_samples"] = i + 1

                  # Sort winners by disparity ASC (most negative = best BUY = rank 1)
        all_best.sort(key=lambda m: m["disparity"])

        q.put(f"\n{'='*60}\n")
        q.put(f"BATCH COMPLETE: {len(raw_samples)} samples processed, {len(all_best)} valid\n")
        if all_best:
              q.put(f"Best overall: Sample {all_best[0]['sample_num']} disparity = {all_best[0]['disparity']:.4f}%\n")

        batch_result = {
            "batch_results": True,
            "total_samples":  len(raw_samples),
            "valid_samples":  len(all_best),
            "matchups":       all_best,        # one winner per sample
            "top_pairs":      all_top_pairs,   # top-N per sample (frequency analysis)
            "top_n":          TOP_N,
            "street":         first_street or "",
          }

        jobs[batch_id]["results"] = batch_result
        q.put(f"\n__EXIT__0__\n")
        jobs[batch_id]["done"] = True

    threading.Thread(target=run_batch_worker, daemon=True).start()
    return jsonify({"job_id": batch_id, "batch": True, "total_samples": len(raw_samples)}), 200


def _run_single(variant, hands, names):
    """Helper: run a single sample (same logic as /api/run)."""
    script_path = SCRIPTS_DIR / VARIANTS[variant]["script"]
    if not script_path.exists():
        return jsonify({"error": f"Script not found: {script_path}"}), 500

    job_id  = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    hands_file = job_dir / "hands.txt"
    hands_file.write_text(hands, encoding="utf-8")

    cmd = [sys.executable, str(script_path), str(hands_file)]
    if names.strip():
        names_file = job_dir / "names.txt"
        names_file.write_text(names, encoding="utf-8")
        cmd += ["--names", str(names_file)]

    q = queue.Queue()
    jobs[job_id] = {"q": q, "done": False, "lines": [], "results": None}

    def run():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            for line in proc.stdout:
                clean = strip_ansi(line)
                jobs[job_id]["lines"].append(clean)
                q.put(clean)
            proc.wait(timeout=30)
            full_text = "".join(jobs[job_id]["lines"])
            try:
                jobs[job_id]["results"] = parse_results(full_text)
            except Exception as e:
                jobs[job_id]["results"] = {"error": str(e)}
            q.put(f"\n__EXIT__{proc.returncode}__\n")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logging.warning('[ENGINE] Subprocess timed out after 30s for job_id=%s', job_id)
            jobs[job_id]["results"] = {"error": "Engine subprocess timed out after 30s"}
            q.put("\n__ERROR__Engine subprocess timed out after 30s__\n")
        except Exception as e:
            q.put(f"\n__ERROR__{e}__\n")
        finally:
            jobs[job_id]["done"] = True
            if jobs[job_id].get("results"):
                try:
                    (job_dir / "results.json").write_text(
                        json.dumps(jobs[job_id]["results"]))
                except Exception:
                    pass

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── /create  Collaborative session ────────────────────────────────────────────
@app.route("/create")
def create_session():
    session_id = str(uuid.uuid4())[:8]
    session_data[session_id] = {
        "variant": "plo5-6max",
        "hands": "",
        "names": "",
        "board": "",
        "dead": "",
        "users": [],
        "last_updated_by": None,
        "current_job_id": None,
    }
    return jsonify({
        "session_id": session_id,
        "share_url": f"{request.host_url}?s={session_id}",
    })

# ── Socket.IO events ──────────────────────────────────────────────────────────
@socketio.on("join")
def on_join(data):
    session_id = data["session_id"]
    username   = data.get("username", f"User_{str(uuid.uuid4())[:4]}")

    if session_id not in session_data:
        emit("error", {"msg": "Session not found"})
        return

    join_room(session_id)
    if username not in session_data[session_id]["users"]:
        session_data[session_id]["users"].append(username)

    emit("init_state", session_data[session_id])
    emit("user_joined", {
        "username": username,
        "users": session_data[session_id]["users"],
    }, to=session_id, skip_sid=request.sid)

@socketio.on("leave")
def on_leave(data):
    session_id = data["session_id"]
    username   = data.get("username")
    if session_id in session_data and username:
        session_data[session_id]["users"] = [
            u for u in session_data[session_id]["users"] if u != username
        ]
        leave_room(session_id)
        emit("user_left", {"username": username, "users": session_data[session_id]["users"]}, to=session_id)

@socketio.on("update_field")
def on_update_field(data):
    session_id = data["session_id"]
    field      = data["field"]
    value      = data["value"]
    username   = data.get("username", "Anonymous")

    if session_id not in session_data:
        return

    session_data[session_id][field] = value
    session_data[session_id]["last_updated_by"] = username

    emit("field_updated", {
        "field": field, "value": value, "updated_by": username,
    }, to=session_id)

@socketio.on("run_session_engine")
def on_run_session_engine(data):
    """Any user in the session can trigger an engine run for everyone."""
    session_id = data["session_id"]
    username   = data.get("username", "Anonymous")

    if session_id not in session_data:
        emit("error", {"msg": "Session not found"})
        return

    sd      = session_data[session_id]
    variant = sd.get("variant", "plo5-6max")
    hands   = sd.get("hands", "")
    names   = sd.get("names", "")

    if not hands.strip():
        emit("error", {"msg": "No hands in session"})
        return

    script_path = SCRIPTS_DIR / VARIANTS.get(variant, VARIANTS["plo5-6max"])["script"]
    if not script_path.exists():
        emit("error", {"msg": f"Script not found for variant {variant}"})
        return

    job_id  = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    (job_dir / "hands.txt").write_text(hands, encoding="utf-8")
    cmd = [sys.executable, str(script_path), str(job_dir / "hands.txt")]
    if names.strip():
        (job_dir / "names.txt").write_text(names, encoding="utf-8")
        cmd += ["--names", str(job_dir / "names.txt")]

    q = queue.Queue()
    jobs[job_id] = {"q": q, "done": False, "lines": [], "results": None}
    session_data[session_id]["current_job_id"] = job_id

    # Broadcast to all session users: a job has started
    emit("engine_started", {"job_id": job_id, "started_by": username}, to=session_id)

    def run():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            for line in proc.stdout:
                clean = strip_ansi(line)
                jobs[job_id]["lines"].append(clean)
                q.put(clean)
            proc.wait(timeout=30)
            full_text = "".join(jobs[job_id]["lines"])
            try:
                jobs[job_id]["results"] = parse_results(full_text)
            except Exception as e:
                jobs[job_id]["results"] = {"error": str(e)}
            q.put(f"\n__EXIT__{proc.returncode}__\n")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logging.warning('[ENGINE] Subprocess timed out after 30s for job_id=%s', job_id)
            jobs[job_id]["results"] = {"error": "Engine subprocess timed out after 30s"}
            q.put("\n__ERROR__Engine subprocess timed out after 30s__\n")
        except Exception as e:
            q.put(f"\n__ERROR__{e}__\n")
        finally:
            jobs[job_id]["done"] = True

    threading.Thread(target=run, daemon=True).start()

@socketio.on("request_validate")
def on_request_validate(data):
    session_id = data["session_id"]
    emit("validate_requested", {"by": data.get("username")}, to=session_id)

# ── PokerReader Remote Launcher ────────────────────────────────────────────────
pending_commands = {}  # {command_id: {"command": "launch_pokerreader", "status": "pending"}}

@app.route("/api/launch/pokerreader", methods=["POST"])
def launch_pokerreader():
    """
    Queue a command to launch PokerReader on Windows.
    Windows command executor polls this endpoint and executes pending commands.

    Optional body:
    {
        "exe_path": "C:\\Users\\Name\\Desktop\\PokerReader\\PokerReader.exe"
    }
    """
    try:
        payload = request.get_json(force=True)
    except:
        payload = {}

    exe_path = payload.get("exe_path")  # Optional custom path from frontend

    command_id = str(uuid.uuid4())[:8]
    pending_commands[command_id] = {
        "command": "launch_pokerreader",
        "status": "pending",
        "created_at": str(dt.now()),
        "exe_path": exe_path,  # Pass custom path if provided
    }
    return jsonify({
        "status": "queued",
        "command_id": command_id,
        "message": "PokerReader launch command queued. Waiting for Windows executor..."
    }), 202

@app.route("/api/commands/pending", methods=["GET"])
def get_pending_commands():
    """
    Windows executor calls this to get pending commands.
    Returns pending commands and marks them as executing.
    """
    pending = {cid: cmd for cid, cmd in pending_commands.items() if cmd["status"] == "pending"}

    # Mark as executing
    for cid in pending:
        pending_commands[cid]["status"] = "executing"

    return jsonify({"commands": pending})

@app.route("/api/commands/<command_id>/complete", methods=["POST"])
def mark_command_complete(command_id):
    """
    Windows executor calls this after successfully executing a command.
    """
    if command_id in pending_commands:
        pending_commands[command_id]["status"] = "completed"
        return jsonify({"status": "ok"})
    return jsonify({"error": "Command not found"}), 404

@app.route("/api/commands/<command_id>/status", methods=["GET"])
def get_command_status(command_id):
    """
    Frontend calls this to check if command was executed.
    """
    if command_id not in pending_commands:
        return jsonify({"status": "not_found"}), 404

    cmd = pending_commands[command_id]
    return jsonify({
        "command_id": command_id,
        "status": cmd["status"],  # pending, executing, completed
        "command": cmd["command"],
    })

# ── PokerReader Scanner API ───────────────────────────────────────────────────
SCANNER_API_KEY = os.getenv("SCANNER_API_KEY", "a3f9k2b7e1d4c8f0a2b5e9d3c7f1b4e8a6d2c9f3b7e1d4c8f0a2b5e9d3c7f1")

@app.route("/api/scanner/log", methods=["POST"])
def scanner_log():
    """
    Receive table scan data from PokerReader's log_watcher.
    Validates API key and broadcasts to all connected browsers via SocketIO.

    Expected payload:
    {
        "table_id": 4,
        "raw": "AhKsQdJc..."
    }
    """
    # Validate API key
    api_key = request.headers.get("X-Api-Key", "")
    if api_key != SCANNER_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        payload = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": f"Invalid JSON: {str(e)}"}), 400

    table_id = payload.get("table_id", 0)
    raw_text = payload.get("raw", "").strip()

    # Broadcast raw text to all connected clients — no filtering, preserve newlines
    socketio.emit("scanner_cards", {
        "table_id": table_id,
        "raw": raw_text,
        "timestamp": str(uuid.uuid4())[:8],
    })

    return jsonify({"status": "ok", "broadcast": True}), 200

# ══════════════════════════════════════════════════════════════════════════════
# ██  HAND TRACKER  —  Browser -> API -> Validate -> Store (Phase 1)
# ══════════════════════════════════════════════════════════════════════════════

# ── Tracker Config ────────────────────────────────────────────────────────────
TRACKER_API_KEY = os.getenv(
    "TRACKER_API_KEY",
    "trk_b4e8a6d2c9f3b7e1d4c8f0a2b5e9d3c7f1b4e8a6d2c9f3b7e1d4c8f0a2b5e9",
)
TRACKER_EVENTS_DIR = Path(
    os.getenv("TRACKER_EVENTS_DIR", Path(__file__).parent / "tracker_events")
)
VALIDATED_HANDS_DIR = Path(
    os.getenv("VALIDATED_HANDS_DIR", Path(__file__).parent / "validated_hands")
)
TRACKER_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
VALIDATED_HANDS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory dedup caches  (bounded — oldest evicted when full)
_DEDUP_PAYLOAD_IDS = {}       # {payload_id: timestamp}  — Rule 1
_DEDUP_SOURCE_HAND = {}       # {source_key+hand_key: timestamp}  — Rule 2
_DEDUP_VALIDATOR_TEXT = {}     # {source_key+validator_text: timestamp}  — Rule 3
_DEDUP_MAX = 10_000

# ── Hand aggregator — collects one hand per browser until all players submitted ──
# key: variant + ":" + flop_str  →  {machine_id: hand_str, "__meta__": {...}}
_HAND_AGGREGATOR = {}

# Store current aggregated hands globally for auto-population
_CURRENT_AGGREGATED_HANDS = ""
_LAST_AGGREGATION_TIME = 0
_AGG_WINDOW_S    = 60   # seconds; stale aggregations discarded


def _variant_player_count(variant: str) -> int:
    """Extract expected player count from variant string (e.g. plo5-6max → 6)."""
    for suffix, n in [("9max", 9), ("8max", 8), ("6max", 6), ("5max", 5)]:
        if variant.endswith(suffix):
            return n
    return 0


def _agg_add(variant: str, flop_norm: list, machine_id: str, hand_str: str) -> tuple[list, bool, int]:
    """
    Register one player's hand for this (variant, flop) deal.
    Always returns (current_hands, is_complete) so the textarea updates
    progressively as each of the 6 browsers submits — not only when all are in.
    """
    now   = time.time()
    key   = variant + ":" + "".join(flop_norm)

    # Evict stale aggregations
    stale = [k for k, v in _HAND_AGGREGATOR.items()
             if now - v["__meta__"]["created_at"] > _AGG_WINDOW_S]
    for k in stale:
        del _HAND_AGGREGATOR[k]

    if key not in _HAND_AGGREGATOR:
        _HAND_AGGREGATOR[key] = {"__meta__": {"variant": variant,
                                               "flop": flop_norm,
                                               "created_at": now}}

    bucket = _HAND_AGGREGATOR[key]
    bucket[machine_id] = {"hand": hand_str, "received_at": now}          # last submission from this machine wins

    expected = _variant_player_count(variant)
    players  = {k: v for k, v in bucket.items() if k != "__meta__"}
    is_complete = expected > 0 and len(players) >= expected

    if is_complete:
        del _HAND_AGGREGATOR[key]

    age = now - bucket["__meta__"]["created_at"]
    hands_list = [p["hand"] if isinstance(p, dict) else p for p in players.values()]
    return hands_list, is_complete, int(age)


def _evict_dedup(cache: dict, max_size: int = _DEDUP_MAX):
    """Drop oldest 20 % when cache exceeds max_size."""
    if len(cache) <= max_size:
        return
    to_drop = sorted(cache, key=cache.get)[: max_size // 5]
    for k in to_drop:
        cache.pop(k, None)


# ── Tracker card normalisation ────────────────────────────────────────────────
_SUIT_UNICODE = {
    "\u2660": "s", "\u2665": "h", "\u2666": "d", "\u2663": "c",  # black
    "\u2664": "s", "\u2661": "h", "\u2662": "d", "\u2667": "c",  # white
}
_RANK_ALIAS = {"10": "T", "1": "A"}  # common browser quirks


def normalize_tracker_card(raw: str) -> str | None:
    """
    Accept various card formats from the browser tracker and return
    engine-canonical form  e.g. "As", "Td", "9h".

    Handles:
      - Unicode suits:  "A\u2660" -> "As"
      - Rank "10":      "10c" -> "Tc"
      - Already normal:  "9d" -> "9d"
    Returns None if unparseable.
    """
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()

    # Replace unicode suit symbols
    for sym, letter in _SUIT_UNICODE.items():
        raw = raw.replace(sym, letter)

    raw = raw.upper()

    # Handle "10x" -> "Tx"
    if raw.startswith("10") and len(raw) == 3:
        raw = "T" + raw[2]

    if len(raw) != 2:
        return None

    rank, suit = raw[0], raw[1].lower()
    if rank not in RANK_SET:
        return None
    if suit not in VALID_SUITS:
        return None
    return rank + suit


def _normalize_card_list(cards) -> list:
    """Normalise a list of card strings, dropping any that fail."""
    if not cards or not isinstance(cards, list):
        return []
    out = []
    for c in cards:
        n = normalize_tracker_card(c)
        if n:
            out.append(n)
    return out


# ── Build validator input text from normalised payload ────────────────────────
def _build_validator_text(hole_cards: list, flop: list, turn: str | None, river: str | None) -> str:
    """Produce the text format the existing validator / engine expects."""
    lines = []
    lines.append("".join(hole_cards))  # e.g. "As9dKhQcTc"
    if flop:
        lines.append("".join(flop))
    if turn:
        lines.append(turn)
    if river:
        lines.append(river)
    return "\n".join(lines) + "\n"


# ── Detect variant from hole card count ───────────────────────────────────────
def _detect_variant(n_hole: int, requested: str | None) -> str:
    """Return the best matching VARIANTS key."""
    if requested and requested in VARIANTS:
        return requested
    mapping = {2: "nlh", 4: "plo4-6max", 5: "plo5-6max", 6: "plo6-6max", 7: "plo7-6max"}
    return mapping.get(n_hole, "unknown")


# ── 3-Rule Deduplication ──────────────────────────────────────────────────────
def _check_dedup(payload: dict) -> str | None:
    """
    Returns a reason string if this payload is a duplicate, else None.
    Also records the payload for future checks.
    """
    now = time.time()

    # Rule 1 — exact payload_id
    pid = payload.get("payload_id", "")
    if pid in _DEDUP_PAYLOAD_IDS:
        return "duplicate_payload_id"
    _DEDUP_PAYLOAD_IDS[pid] = now
    _evict_dedup(_DEDUP_PAYLOAD_IDS)

    # Rule 2 — same source + hand key within 3 s
    sk = payload.get("source_key", "") + ":" + payload.get("hand_id", "")
    prev = _DEDUP_SOURCE_HAND.get(sk)
    if prev and (now - prev) < 3.0:
        return "duplicate_source_hand_3s"
    _DEDUP_SOURCE_HAND[sk] = now
    _evict_dedup(_DEDUP_SOURCE_HAND)

    # Rule 3 — same source + validator text within 5 s
    vt = payload.get("_validator_text", "")
    vk = payload.get("source_key", "") + ":" + vt
    prev2 = _DEDUP_VALIDATOR_TEXT.get(vk)
    if prev2 and (now - prev2) < 5.0:
        return "duplicate_validator_text_5s"
    _DEDUP_VALIDATOR_TEXT[vk] = now
    _evict_dedup(_DEDUP_VALIDATOR_TEXT)

    return None


# ── Save helpers ──────────────────────────────────────────────────────────────
def _ts_slug() -> str:
    return dt.utcnow().strftime("%Y%m%d_%H%M%S")


def _save_raw_event(payload: dict) -> str:
    """Write raw JSON payload to tracker_events/. Returns file path."""
    machine = payload.get("machine_id", "unknown")
    sub = TRACKER_EVENTS_DIR / machine
    sub.mkdir(parents=True, exist_ok=True)
    fname = f"{_ts_slug()}_{payload.get('payload_id', uuid.uuid4().hex[:8])}.json"
    path = sub / fname
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(path)


def _save_validated_hand(raw_event_path: str, payload: dict,
                         validator_text: str, valid: bool,
                         validation_error: str | None) -> str:
    """Write validated hand record. Returns file path."""
    record = {
        "raw_event_path": raw_event_path,
        "source_key": payload.get("source_key"),
        "hand_id": payload.get("hand_id"),
        "variant": payload.get("_variant"),
        "player_name": payload.get("player_name"),
        "stack_zar": payload.get("stack_zar"),
        "hole_cards": payload.get("_hole_norm"),
        "flop": payload.get("_flop_norm"),
        "turn": payload.get("_turn_norm"),
        "river": payload.get("_river_norm"),
        "street": payload.get("street"),
        "validator_text": validator_text,
        "valid": valid,
        "validation_error": validation_error,
        "created_at": dt.utcnow().isoformat() + "Z",
    }
    fname = f"{_ts_slug()}_{payload.get('payload_id', uuid.uuid4().hex[:8])}.json"
    path = VALIDATED_HANDS_DIR / fname
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return str(path)


# ── POST /api/tracker/hand ────────────────────────────────────────────────────
@app.route("/api/tracker/hand", methods=["POST", "OPTIONS"])
def tracker_hand():
    # Handle CORS preflight
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Api-Key"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp

    """
    Receive a hand payload from the browser tracker.

    Pipeline:
      1. Authenticate via X-API-Key header
      2. Validate required JSON fields
      3. Normalise cards (unicode, 10->T, uppercase)
      4. 3-rule deduplication
      5. Save raw event
      6. Build validator input text
      7. Run card validation (rank/suit + duplicates)
      8. Save validated hand record
      9. Return result (Phase 1 — no engine enqueue yet)
    """
    # ── 1. Auth ───────────────────────────────────────────────────────────
    api_key = request.headers.get("X-API-Key", "") or request.headers.get("X-Api-Key", "")
    if api_key != TRACKER_API_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # ── 2. Parse body ─────────────────────────────────────────────────────
    try:
        payload = request.get_json(force=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"invalid JSON: {e}"}), 400

    # Required fields
    required = ["payload_id", "machine_id", "client_id", "table_id",
                "timestamp_utc", "player_name", "hole_cards"]
    for f in required:
        if f not in payload or payload[f] is None:
            return jsonify({"ok": False, "error": f"missing field: {f}"}), 400

    if not isinstance(payload.get("hole_cards"), list) or len(payload["hole_cards"]) == 0:
        return jsonify({"ok": False, "error": "hole_cards must be a non-empty array"}), 400

    # ── 3. Normalise cards ────────────────────────────────────────────────
    hole_norm = _normalize_card_list(payload["hole_cards"])
    flop_norm = _normalize_card_list(payload.get("flop") or [])
    turn_norm = normalize_tracker_card(payload.get("turn") or "")
    river_norm = normalize_tracker_card(payload.get("river") or "")

    if len(hole_norm) == 0:
        return jsonify({"ok": False, "error": "no valid hole cards after normalisation"}), 400

    # Attach normalised data to payload for downstream use
    payload["_hole_norm"] = hole_norm
    payload["_flop_norm"] = flop_norm
    payload["_turn_norm"] = turn_norm
    payload["_river_norm"] = river_norm
    payload["_variant"] = _detect_variant(len(hole_norm), payload.get("variant"))

    # Build validator text
    vtext = _build_validator_text(hole_norm, flop_norm, turn_norm, river_norm)
    payload["_validator_text"] = vtext

    # Build hand_id if not provided
    if not payload.get("hand_id"):
        src = payload.get("source_key", payload["machine_id"] + ":" + payload["client_id"] + ":" + payload["table_id"])
        payload["hand_id"] = src + ":" + "".join(hole_norm) + ":" + "".join(flop_norm)
    if not payload.get("source_key"):
        payload["source_key"] = payload["machine_id"] + ":" + payload["client_id"] + ":" + payload["table_id"]

    # ── 4. Deduplication ──────────────────────────────────────────────────
    dup_reason = _check_dedup(payload)
    if dup_reason:
        return jsonify({"ok": True, "duplicate": True, "reason": dup_reason}), 200

    # ── 5. Save raw event ─────────────────────────────────────────────────
    raw_path = _save_raw_event(payload)

    # ── 6-7. Validate cards ───────────────────────────────────────────────
    validation_errors = []

    # Check each card is valid rank+suit
    all_cards = list(hole_norm) + list(flop_norm)
    if turn_norm:
        all_cards.append(turn_norm)
    if river_norm:
        all_cards.append(river_norm)

    for card in all_cards:
        _, etype, edetail = validate_token(card)
        if etype:
            validation_errors.append(f"{card}: {edetail}")

    # Check for duplicate cards
    seen_cards = {}
    for card in all_cards:
        if card in seen_cards:
            validation_errors.append(f"duplicate card: {card}")
        seen_cards[card] = True

    is_valid = len(validation_errors) == 0
    verr_str = "; ".join(validation_errors) if validation_errors else None

    # ── 8. Save validated hand ────────────────────────────────────────────
    hand_path = _save_validated_hand(raw_path, payload, vtext, is_valid, verr_str)

    # ── 9. Response (Phase 1 — no engine enqueue) ─────────────────────────
    sample_id     = "snap-" + payload["payload_id"]
    handtracker_id = "ht-" + hashlib.sha1(payload["hand_id"].encode()).hexdigest()[:12]
    resp = {
        "ok": True,
        "duplicate": False,
        "validated": is_valid,
        "validation_error": verr_str,
        "sample_id": sample_id,
        "handtracker_id": handtracker_id,
        "raw_event_path": raw_path,
        "hand_path": hand_path,
        "variant": payload["_variant"],
        "hole_cards": hole_norm,
        "street": payload.get("street", "UNKNOWN"),
    }

    # ── 10. Broadcast to frontend ─────────────────────────────────────
    # 10a. Per-player event — updates TrackerHandsPanel only (no textarea)
    socketio.emit("scanner_cards", {
        "table_id":            payload.get("table_id", "tracker"),
        "raw":                 "",   # textarea updated via aggregate below
        "timestamp":           str(uuid.uuid4())[:8],
        "source":              "tracker",
        "player_name":         payload.get("player_name", ""),
        "variant":             payload["_variant"],
        "street":              payload.get("street", "UNKNOWN"),
        "validated":           is_valid,
        "validation_error":    verr_str,
        "hole_cards":          hole_norm,
        "flop_from_player1":   "".join(flop_norm),
        "flop_from_last_player": "".join(flop_norm),
        "total_zar":           payload.get("stack_zar"),
    })

    # 10b. Progressive aggregate — fires after EVERY submission so the textarea
    #      builds up hand-by-hand as each of the 6 browsers sends their cards.
    machine_id           = payload.get("machine_id", str(uuid.uuid4())[:8])
    hand_str             = "".join(hole_norm)
    all_hands, complete  = _agg_add(payload["_variant"], flop_norm, machine_id, hand_str)

    raw_for_frontend = "\n".join(all_hands)
    if flop_norm:
        raw_for_frontend += "\n" + "".join(flop_norm)
    if turn_norm:
        raw_for_frontend += "\n" + turn_norm
    if river_norm:
        raw_for_frontend += "\n" + river_norm

    socketio.emit("scanner_cards", {
        "table_id":  payload.get("table_id", "tracker"),
        "raw":       raw_for_frontend,
        "timestamp": str(uuid.uuid4())[:8],
        "source":    "tracker_aggregate",
        "variant":   payload["_variant"],
        "complete":  complete,
    })

    return jsonify(resp), 200


# ── GET /api/tracker/status — Health check for tracker subsystem ──────────────
@app.route("/api/tracker/status", methods=["GET"])
def tracker_status():
    """Quick health / stats endpoint for the tracker pipeline."""
    # Count files
    raw_count = sum(1 for _ in TRACKER_EVENTS_DIR.rglob("*.json"))
    val_count = sum(1 for _ in VALIDATED_HANDS_DIR.glob("*.json"))
    return jsonify({
        "ok": True,
        "raw_events": raw_count,
        "validated_hands": val_count,
        "dedup_payload_ids": len(_DEDUP_PAYLOAD_IDS),
        "dedup_source_hand": len(_DEDUP_SOURCE_HAND),
        "dedup_validator_text": len(_DEDUP_VALIDATOR_TEXT),
    }), 200


# ── GET /api/current-hands — Return current aggregated hands for frontend polling ──

# ── /api/collector/save ───────────────────────────────────────────
@app.route("/api/collector/save", methods=["POST"])
def collector_save():
    """Unified hand collector endpoint (merges hand-collector:6001)."""
    try:
        payload = request.get_json(force=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Invalid JSON: {e}"}), 400
    
    text = (payload.get("text") or "").strip()
    variant = (payload.get("variant") or "plo5-6max").strip().lower()
    
    if not text:
        return jsonify({"ok": False, "error": "text field required"}), 400
    
    if variant not in VARIANTS:
        variant = "plo5-6max"
    
    if "|" in text:
        hand_part, board_part = text.split("|", 1)
    else:
        hand_part = text.strip()
        board_part = ""
    
    hole_tokens = tokenise(hand_part)
    hole_cards = [validate_token(t)[0] for t in hole_tokens]
    hole_cards = [c for c in hole_cards if c]
    
    flop_tokens = tokenise(board_part) if board_part else []
    flop_cards = [validate_token(t)[0] for t in flop_tokens[:3]]
    flop_cards = [c for c in flop_cards if c]
    
    if not hole_cards:
        return jsonify({"ok": False, "error": "No valid hole cards"}), 400
    
    machine_id = payload.get("machine_id") or request.remote_addr[:16]
    hand_str = "".join(hole_cards)
    
    try:
        all_hands, is_complete, age = _agg_add(variant, flop_cards, machine_id, hand_str)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    
    raw = "\n".join(all_hands)
    if flop_cards:
        raw += "\n" + "".join(flop_cards)
    
    return jsonify({
        "ok": True, "hands": raw, "complete": is_complete, "age_s": age,
        "player_count": len(all_hands), "variant": variant,
    }), 200


# ── /api/collector/send-to-engine ─────────────────────────────────
@app.route("/api/collector/send-to-engine", methods=["POST"])
def collector_send_to_engine():
    """Send aggregated hands to equity engine."""
    try:
        payload = request.get_json(force=True)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    
    variant = (payload.get("variant") or "plo5-6max").strip().lower()
    hands = (payload.get("hands") or "").strip()
    
    if not hands:
        return jsonify({"error": "No hands provided"}), 400
    
    if variant not in VARIANTS:
        return jsonify({"error": f"Unknown variant '{variant}'"}), 400
    
    script_path = SCRIPTS_DIR / VARIANTS[variant]["script"]
    if not script_path.exists():
        return jsonify({"error": f"Script not found"}), 500
    
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    hands_file = job_dir / "hands.txt"
    hands_file.write_text(hands, encoding="utf-8")
    
    cmd = [sys.executable, str(script_path), str(hands_file)]
    q = queue.Queue()
    jobs[job_id] = {"q": q, "done": False, "lines": [], "results": None}
    
    def run():
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1,
                                   env={**os.environ, "PYTHONUNBUFFERED": "1"})
            for line in proc.stdout:
                clean = strip_ansi(line)
                jobs[job_id]["lines"].append(clean)
                q.put(clean)
            proc.wait(timeout=30)
            full_text = "".join(jobs[job_id]["lines"])
            try:
                jobs[job_id]["results"] = parse_results(full_text)
            except Exception as e:
                jobs[job_id]["results"] = {"error": str(e)}
            q.put(f"\n__EXIT__{proc.returncode}__\n")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logging.warning('[ENGINE] Subprocess timed out after 30s for job_id=%s', job_id)
            jobs[job_id]["results"] = {"error": "Engine subprocess timed out after 30s"}
            q.put("\n__ERROR__Engine subprocess timed out after 30s__\n")
        except Exception as e:
            q.put(f"\n__ERROR__{e}__\n")
        finally:
            jobs[job_id]["done"] = True
    
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id}), 200


@app.route("/api/current-hands", methods=["GET"])
def current_hands():
    """
    Return the current state of all active hand aggregations.
    The frontend polls this to display hands as they arrive from the tracker.
    """
    now = time.time()
    result = []
    for key, bucket in list(_HAND_AGGREGATOR.items()):
        meta = bucket.get("__meta__", {})
        if now - meta.get("created_at", now) > _AGG_WINDOW_S:
            continue  # skip stale
        players = {k: v for k, v in bucket.items() if k != "__meta__"}
        variant  = meta.get("variant", "")
        flop     = meta.get("flop", [])
        expected = _variant_player_count(variant)
        hands_list = list(players.values())
        raw = "\n".join(hands_list)
        if flop:
            raw += "\n" + "".join(flop)
        result.append({
            "key":      key,
            "variant":  variant,
            "flop":     flop,
            "hands":    hands_list,
            "raw":      raw,
            "count":    len(players),
            "expected": expected,
            "complete": expected > 0 and len(players) >= expected,
            "age_s":    round(now - meta.get("created_at", now), 1),
        })
    # Pick the most recent aggregation as the top-level hands/age the frontend expects
    best = min(result, key=lambda r: r["age_s"]) if result else None
    return jsonify({
        "ok":           True,
        "aggregations": result,
        "count":        len(result),
        "hands":        best["raw"] if best else "",
        "age":          best["age_s"] if best else None,
        "variant":      best["variant"] if best else "",
        "complete":     best["complete"] if best else False,
    }), 200


# ════════════════════════════════════════════════════════════════════════════
# ██  AI ANALYST  —  Claude via ai_guard pipeline
# ════════════════════════════════════════════════════════════════════════════

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")


def _call_claude(payload: dict, headers: dict) -> str:
    """Actual model call — only reached after all guard checks pass."""
    import urllib.request
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set on server")
    dataset  = payload.get("dataset", [])
    question = payload.get("question", "")
    context  = payload.get("context", "")
    system_prompt = (
        "You are an expert poker equity analyst. "
        "You are given a structured dataset of PLO equity matchups. "
        "Fields: sample, pair, underdog, favourite, und_raw (%), und_real (%), "
        "disparity (realized - raw, %), fav_raw (%), fav_real (%). "
        "Negative disparity = underdog improves vs raw equity = profitable signal. "
        "Answer concisely and specifically."
    )
    dataset_text = json.dumps(dataset[:500], default=str)
    user_message = f"{context}\n\nDataset:\n{dataset_text}\n\nQuestion: {question}"
    body = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": 1024,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_message}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
            "Idempotency-Key":   headers.get("Idempotency-Key", ""),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data["content"][0]["text"]


@app.route("/api/analytics/ask", methods=["POST"])
def analytics_ask():
    """
    POST /api/analytics/ask
    Body: { question: str, dataset: list, context: str }
    Full guard pipeline: hash → idempotency → token limits → budgets → retry → audit
    """
    try:
        body = request.get_json(force=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"invalid JSON: {e}"}), 400

    question = (body.get("question") or "").strip()
    dataset  = body.get("dataset", [])
    context  = body.get("context", "")
    if not question:
        return jsonify({"ok": False, "error": "question is required"}), 400

    source_id = f"ask-{request.remote_addr}"
    worker_id = str(uuid.uuid4())[:8]
    raw_payload = {"question": question, "dataset": dataset, "context": context}
    raw_bytes   = json.dumps(raw_payload, default=str).encode()
    chunks      = chunk_delta(raw_bytes)
    if not chunks:
        return jsonify({"ok": False, "error": "empty payload"}), 400

    try:
        acquire_source_lease(source_id, worker_id)
    except GuardReject as e:
        return jsonify({"ok": False, "error": e.reason, "code": e.code}), 429

    try:
        _raw_pl, norm_pl = normalize_chunk(chunks[0], source_id)
        ph       = compute_payload_hash(norm_pl)

        if is_duplicate_payload(source_id, ph):
            audit_log(source_id, ph, "", 0, action="skipped", reason="duplicate_payload")
            return jsonify({"ok": True, "answer": "(duplicate request)"}), 200

        idem_key = make_idempotency_key(ph, source_id)
        cached   = idempotency_get(idem_key)
        if cached:
            audit_log(source_id, ph, idem_key, 0, action="skipped", reason="idempotency_hit")
            return jsonify({"ok": True, "answer": cached, "cached": True}), 200

        try:
            norm_pl = enforce_token_limits(norm_pl)
        except GuardReject as e:
            audit_log(source_id, ph, idem_key, estimate_tokens(norm_pl), action="rejected", reason=e.code)
            return jsonify({"ok": False, "error": e.reason, "code": e.code}), 413

        est = estimate_tokens(norm_pl)
        try:
            enforce_budgets(est)
        except GuardReject as e:
            audit_log(source_id, ph, idem_key, est, action="rejected", reason=e.code)
            return jsonify({"ok": False, "error": e.reason, "code": e.code}), 429

        try:
            check_hard_refusals(norm_pl, retry_count=0, fanout_count=0)
        except GuardReject as e:
            audit_log(source_id, ph, idem_key, est, action="rejected", reason=e.code)
            return jsonify({"ok": False, "error": e.reason, "code": e.code}), 400

        req_id  = f"{source_id[:8]}-{worker_id}"
        headers = {"Idempotency-Key": idem_key}
        try:
            answer = retry_execute(_call_claude, norm_pl, headers, req_id)
        except GuardReject as e:
            audit_log(source_id, ph, idem_key, est, action="rejected", reason=e.code)
            return jsonify({"ok": False, "error": e.reason, "code": e.code}), 500

        idempotency_set(idem_key, answer)
        audit_log(source_id, ph, idem_key, est, action="sent", cost_estimate=est * 0.000003)
        return jsonify({"ok": True, "answer": answer}), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        release_source_lease(source_id, worker_id)


@app.route("/api/ai/budget", methods=["GET"])
def ai_budget():
    """Return current AI guard budget status."""
    return jsonify(budget_status()), 200


# ══════════════════════════════════════════════════════════════════════════════
# ██  RNG SAMPLE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

import random as _random

_RNG_RANKS             = ['A','K','Q','J','T','9','8','7','6','5','4','3','2']
_RNG_SUITS             = ['s','h','d','c']
_FULL_DECK             = [r + s for r in _RNG_RANKS for s in _RNG_SUITS]
_RNG_CARDS_PER_PLAYER  = {'PLO4': 4, 'PLO5': 5, 'PLO6': 6, 'PLO7': 7}
_RNG_BOARD_CARDS       = {'PREFLOP': 0, 'FLOP': 3, 'TURN': 4, 'RIVER': 5}
_RNG_VALID_TABLE_SIZES = [2, 5, 6, 8, 9]
RNG_MAX_SAMPLES        = 1000


def _rng_resolve_rules(variant: str, table_size: int, street: str) -> dict:
    cpp  = _RNG_CARDS_PER_PLAYER[variant]
    bcc  = _RNG_BOARD_CARDS[street]
    need = table_size * cpp + bcc
    if need > 52:
        raise ValueError(
            f"{variant} {table_size}-max {street} needs {need} cards — exceeds 52-card deck"
        )
    return {'variant': variant, 'player_count': table_size,
            'cards_per_player': cpp, 'board_card_count': bcc, 'total_cards': need}


def _rng_generate_sample(rules: dict) -> dict:
    deck = _FULL_DECK[:]
    _random.shuffle(deck)
    cursor, players, cpp = 0, [], rules['cards_per_player']
    for _ in range(rules['player_count']):
        players.append(deck[cursor: cursor + cpp])
        cursor += cpp
    board = deck[cursor: cursor + rules['board_card_count']]
    seen = set()
    for hand in players:
        for c in hand:
            assert c not in seen, f'Duplicate: {c}'; seen.add(c)
    for c in board:
        assert c not in seen, f'Duplicate: {c}'; seen.add(c)
    return {'players': players, 'board': board}


def _rng_format_sample(sample: dict) -> str:
    lines = [''.join(h) for h in sample['players']]
    lines.append(''.join(sample['board']))
    return '\n'.join(lines)


@app.route('/api/rng/generate', methods=['POST'])
def rng_generate():
    """POST /api/rng/generate — generate RNG poker samples."""
    try:
        body = request.get_json(force=True)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'invalid JSON: {e}'}), 400

    variant      = (body.get('variant')      or '').strip().upper()
    table_size   = body.get('table_size')
    street       = (body.get('street')       or '').strip().upper()
    sample_count = body.get('sample_count')

    if variant not in _RNG_CARDS_PER_PLAYER:
        return jsonify({'ok': False, 'error': f'unsupported variant "{variant}" — use PLO4 PLO5 PLO6 PLO7'}), 400
    if not isinstance(table_size, int) or table_size not in _RNG_VALID_TABLE_SIZES:
        return jsonify({'ok': False, 'error': f'unsupported table_size — use one of {_RNG_VALID_TABLE_SIZES}'}), 400
    if street not in _RNG_BOARD_CARDS:
        return jsonify({'ok': False, 'error': f'unsupported street "{street}" — use FLOP TURN RIVER'}), 400
    if not isinstance(sample_count, int) or sample_count < 1:
        return jsonify({'ok': False, 'error': 'sample_count must be a positive integer'}), 400
    if sample_count > RNG_MAX_SAMPLES:
        return jsonify({'ok': False, 'error': f'sample_count exceeds maximum of {RNG_MAX_SAMPLES}'}), 400

    try:
        rules = _rng_resolve_rules(variant, table_size, street)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    try:
        samples = [_rng_format_sample(_rng_generate_sample(rules)) for _ in range(sample_count)]
        output  = '\n\n'.join(samples)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'generation error: {e}'}), 500

    return jsonify({'ok': True, 'variant': variant, 'table_size': table_size,
                    'street': street, 'sample_count': sample_count,
                    'total_cards': rules['total_cards'], 'output': output}), 200


# ── Run app ────────────────────────────────────────────────────────────────────────────


# =====================================================================
# BATCH PARSER API  /api/batch/*
# =====================================================================
from result_parser import (
    parse_batch_text, validate_sample, build_pair_dataset,
    extract_best_pair, compare_winners, filter_pairs,
    batch_summary, _DISPLAY_LABELS, split_batch_blocks,
)

_BATCH_VALID_MODES = {
    "all", "winners", "top_buy", "top_reverse",
    "pos_ev", "neg_ev", "near_zero", "buy", "reverse",
}

def _require_raw():
    try:
        body = request.get_json(force=True) or {}
    except Exception as e:
        return None, (jsonify({"ok": False, "error": str(e)}), 400)
    raw = (body.get("raw") or "").strip()
    if not raw:
        return None, (jsonify({"ok": False, "error": "Field raw is required"}), 400)
    return raw, None

def _safe_parse(raw):
    try:
        samples = parse_batch_text(raw)
    except Exception as e:
        return None, (jsonify({"ok": False, "error": str(e)}), 500)
    if not samples:
        return None, (jsonify({"ok": False, "error": "No sample blocks detected"}), 422)
    return samples, None

def _clean(rows):
    return [{k: v for k, v in r.items() if k != "_raw"} for r in rows]

@app.route("/api/batch/detect", methods=["POST"])
def batch_detect():
    raw, err = _require_raw()
    if err: return err
    blocks = split_batch_blocks(raw)
    info = [{"block_num":i+1,"line_count":len(b.splitlines()),
             "has_matchups":"ALL MATCHUPS" in b,
             "preview":b.splitlines()[0][:80] if b.splitlines() else ""}
            for i,b in enumerate(blocks)]
    return jsonify({"ok":True,"sample_count":len(blocks),"blocks":info,
                    "message":f"{len(blocks)} sample blocks detected"})

@app.route("/api/batch/parse", methods=["POST"])
def batch_parse():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    all_pairs = build_pair_dataset(samples)
    out = [{"sample_id":s["sample_id"],"street":s["street"],"runtime":s["runtime"],
            "pairs_evaluated":s["pairs_evaluated"],"player_count":len(s["players"]),
            "pair_count":len(s["pairs"]),"sections_found":s["sections_found"],
            "parse_errors":s["parse_errors"],"has_winner":s["winner"] is not None,
            "winner_ev":s["winner"]["EV"] if s["winner"] else None}
           for s in samples]
    return jsonify({"ok":True,"samples":out,
                    "summary":batch_summary(samples,all_pairs),"field_map":_DISPLAY_LABELS})

@app.route("/api/batch/validate", methods=["POST"])
def batch_validate():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    results = [validate_sample(s) for s in samples]
    n_pass = sum(1 for r in results if r["ok"])
    secs = ["header","player_list","flop","matchup_rows","ranked_table","final_result"]
    sec_stats = {}
    for sec in secs:
        have = sum(1 for r in results if sec in r["found"])
        sec_stats[sec] = {"present":have,"missing":len(results)-have,
                          "pct":round(have/len(results)*100,1) if results else 0}
    return jsonify({"ok":True,"total":len(results),"passed":n_pass,
                    "failed":len(results)-n_pass,"all_valid":len(results)==n_pass,
                    "results":results,"section_stats":sec_stats})

@app.route("/api/batch/normalize", methods=["POST"])
def batch_normalize():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    all_pairs = build_pair_dataset(samples)
    mapping = [
        {"engine_field":"underdog",  "market_field":"BUY",                "display":"BUY"},
        {"engine_field":"favourite", "market_field":"REVERSE_BUYER",      "display":"REVERSE BUYER"},
        {"engine_field":"und_raw",   "market_field":"PRICE",              "display":"PRICE"},
        {"engine_field":"und_real",  "market_field":"REVERSE_BUY_HIT_PCT","display":"Reverse Buy Hit %"},
        {"engine_field":"fav_raw",   "market_field":"RVS_PRICE",          "display":"RvsPrice"},
        {"engine_field":"fav_real",  "market_field":"HIT_RATE_PCT",       "display":"HitRate %"},
        {"engine_field":"disparity", "market_field":"EV",                 "display":"EV"},
    ]
    return jsonify({"ok":True,"mapping":mapping,"sample_rows":_clean(all_pairs[:10]),
                    "total_pairs":len(all_pairs),"message":"Fields normalised to market model"})

@app.route("/api/batch/pairs", methods=["POST"])
def batch_pairs():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    all_pairs = build_pair_dataset(samples)
    return jsonify({"ok":True,"rows":_clean(all_pairs),"count":len(all_pairs),
                    "summary":batch_summary(samples,all_pairs)})

@app.route("/api/batch/winners", methods=["POST"])
def batch_winners():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    winners = extract_best_pair(samples)
    all_pairs = build_pair_dataset(samples)
    return jsonify({"ok":True,"rows":_clean(winners),"count":len(winners),
                    "summary":batch_summary(samples,all_pairs)})

@app.route("/api/batch/compare", methods=["POST"])
def batch_compare():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    ranked = compare_winners(samples)
    all_pairs = build_pair_dataset(samples)
    rows = _clean(ranked)
    for i,r in enumerate(rows): r["comparison_rank"] = i+1
    return jsonify({"ok":True,"rows":rows,"count":len(rows),
                    "summary":batch_summary(samples,all_pairs)})

@app.route("/api/batch/filter", methods=["POST"])
def batch_filter():
    try: body = request.get_json(force=True) or {}
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),400
    raw  = (body.get("raw")  or "").strip()
    mode = (body.get("mode") or "all").strip().lower()
    if not raw: return jsonify({"ok":False,"error":"Field raw is required"}),400
    if mode not in _BATCH_VALID_MODES:
        return jsonify({"ok":False,"error":f"Unknown mode {mode}"}),400
    samples, err = _safe_parse(raw)
    if err: return err
    all_pairs = build_pair_dataset(samples)
    filtered  = filter_pairs(all_pairs, mode)
    return jsonify({"ok":True,"mode":mode,"rows":_clean(filtered),"count":len(filtered),
                    "total_before_filter":len(all_pairs),
                    "summary":batch_summary(samples,all_pairs)})

@app.route("/api/batch/errors", methods=["POST"])
def batch_errors():
    raw, err = _require_raw()
    if err: return err
    samples, err = _safe_parse(raw)
    if err: return err
    report = []
    for s in samples:
        v = validate_sample(s)
        if s.get("parse_errors") or not v["ok"]:
            report.append({"sample_id":s["sample_id"],"parse_errors":s.get("parse_errors",[]),
                "missing":v["missing"],"found":v["found"],
                "pair_count":len(s.get("pairs",[])),"player_count":len(s.get("players",[])),
                "raw_preview":s["raw"][:300]})
    return jsonify({"ok":True,"total":len(samples),"clean":len(samples)-len(report),
                    "error_count":len(report),"errors":report,"all_clean":len(report)==0})

@app.route("/api/batch/fields", methods=["GET"])
def batch_fields():
    return jsonify({"ok":True,"field_map":_DISPLAY_LABELS,
        "column_order":["sample_id","rank","pair_num","BUY","BUY_HAND",
                        "REVERSE_BUYER","REVERSE_BUYER_HAND","PRICE",
                        "REVERSE_BUY_HIT_PCT","RVS_PRICE","HIT_RATE_PCT","EV"],
        "filter_modes":[
            {"mode":"all","label":"Keep All Pairs"},
            {"mode":"winners","label":"Keep Winners Only"},
            {"mode":"top_buy","label":"Top BUY Set"},
            {"mode":"top_reverse","label":"Top REVERSE Set"},
            {"mode":"pos_ev","label":"Positive EV"},
            {"mode":"neg_ev","label":"Negative EV"},
            {"mode":"near_zero","label":"Near Zero EV"},
            {"mode":"buy","label":"Filter by BUY"},
            {"mode":"reverse","label":"Filter by REVERSE BUYER"},
        ]})


if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=5002, allow_unsafe_werkzeug=True)

# ── GET /api/current-hands — Get currently aggregated hands ──────────────
@app.route("/api/current-hands", methods=["GET"])
def get_current_hands():
    """Return currently aggregated hands for auto-populating textarea."""
    global _CURRENT_AGGREGATED_HANDS, _LAST_AGGREGATION_TIME
    
    # Check if hands are recent (within 5 minutes)
    if time.time() - _LAST_AGGREGATION_TIME > 300:
        return jsonify({"hands": "", "age": -1})
    
    return jsonify({
        "hands": _CURRENT_AGGREGATED_HANDS,
        "age": int(time.time() - _LAST_AGGREGATION_TIME),
        "timestamp": _LAST_AGGREGATION_TIME
    })

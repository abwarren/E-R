#!/usr/bin/env python3
"""
Pipeline Trace — Extension → POST → Flask → Store → API → UI
Collects hand_id presence at each pipeline stage to identify where hands disappear.
READ-ONLY observation agent.
"""
import requests
import json
import time
import hashlib
import subprocess
from datetime import datetime

CO_URL = "http://localhost:4000"
SAMPLE_COUNT = 200
POLL_INTERVAL = 0.5  # 500ms

def hash_dict(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:8]

def get_flask_snapshots(since_ts):
    """Get recent snapshot ACCEPT logs from Flask container."""
    try:
        result = subprocess.run(
            ["docker", "logs", "er-remote"],
            capture_output=True, text=True, timeout=8
        )
        lines = result.stdout.strip().split('\n')
        # Extract snapshot ACCEPT and TRACE POST lines
        snapshots = []
        for l in lines[-500:]:  # Last 500 lines
            if ('[SNAPSHOT][ACCEPT]' in l or '[TRACE][POST]' in l):
                # Parse: table_id=X hand_id=Y street=Z
                import re
                m_tid = re.search(r'table_id=(\S+)', l)
                m_hid = re.search(r'hand_id=(\S+)', l)
                m_st = re.search(r'street=(\S+)', l)
                m_aa = re.search(r'aa=(\S+)', l)
                m_ts = re.search(r'received_ts=([\d.]+)', l)
                m_logts = re.search(r'(\d{2}:\d{2}:\d{2}\.\d+)', l)
                snapshots.append({
                    'table_id': m_tid.group(1) if m_tid else '?',
                    'hand_id': (m_hid.group(1) or '?')[:16] if m_hid else '?',
                    'street': m_st.group(1) if m_st else '?',
                    'actions': m_aa.group(1) if m_aa else '?',
                    'log_ts': m_logts.group(1) if m_logts else '?',
                })
        return snapshots
    except:
        return []

def get_flask_authority():
    """Get recent authority decisions."""
    try:
        result = subprocess.run(
            ["docker", "logs", "er-remote"],
            capture_output=True, text=True, timeout=8
        )
        lines = result.stdout.strip().split('\n')
        auths = []
        for l in lines[-500:]:
            if '[AUTH]' in l:
                import re
                m_ts = re.search(r'(\d{2}:\d{2}:\d{2}\.\d+)', l)
                auths.append({
                    'ts': m_ts.group(1) if m_ts else '?',
                    'line': l.strip()[-200:]
                })
        return auths
    except:
        return []

def get_api_latest():
    """Get /api/table/latest - what Engine and UI see."""
    try:
        r = requests.get(f"{CO_URL}/api/table/latest", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data.get('ok') and data.get('table'):
                t = data['table']
                # Collect all hero hole cards
                hero_cards = {}
                for s in t.get('seats', []):
                    if s.get('is_hero') or s.get('hole_cards'):
                        hero_cards[s.get('seat_no')] = {
                            'name': s.get('name'),
                            'is_hero': s.get('is_hero'),
                            'cards': s.get('hole_cards', []),
                            'actions': s.get('available_actions', []) or [],
                            'needs_action': s.get('needs_action'),
                            'status': s.get('status'),
                        }
                return {
                    'table_id': t.get('table_id'),
                    'hand_id': t.get('hand_id'),
                    'street': t.get('street'),
                    'pot': t.get('pot_zar'),
                    'board': t.get('board'),
                    'authority_source': t.get('authority', {}).get('source_bot'),
                    'hero_cards': hero_cards,
                    'hash': hash_dict(t),
                }
        return None
    except:
        return None

def get_all_tables():
    """Get full per-bot table state."""
    try:
        r = requests.get(f"{CO_URL}/api/tables", timeout=3)
        if r.status_code == 200:
            tables = r.json().get('tables', [])
            result = {}
            for t in tables:
                bots = [s.get('name') for s in t.get('seats', []) if s.get('is_hero')]
                
                # Collect cards per seat
                cards_by_seat = {}
                for s in t.get('seats', []):
                    hc = s.get('hole_cards', [])
                    if hc:
                        cards_by_seat[s.get('seat_no')] = hc
                
                result[t.get('table_id')] = {
                    'hand_id': t.get('hand_id'),
                    'street': t.get('street'),
                    'hero_bots': bots,
                    'cards': cards_by_seat,
                    'needs_action_seats': [s.get('seat_no') for s in t.get('seats', []) if s.get('needs_action')],
                    'available_actions_seats': [(s.get('seat_no'), s.get('available_actions')) for s in t.get('seats', []) if s.get('available_actions')],
                }
            return result
    except:
        return {}

print(f"{'=' * 80}")
print(f"PIPELINE TRACE — {SAMPLE_COUNT} samples at {POLL_INTERVAL}s intervals")
print(f"Start: {datetime.now().isoformat()}")
print(f"{'=' * 80}")

# Phase A: Collect
samples = []
hand_ids_seen_in_logs = set()
hand_ids_seen_in_api = set()

for i in range(SAMPLE_COUNT):
    sample_start = time.time()
    
    snap_logs = get_flask_snapshots(sample_start)
    auth_logs = get_flask_authority()
    api_latest = get_api_latest()
    all_tables = get_all_tables()
    
    # Track hand_ids
    for s in snap_logs:
        hand_ids_seen_in_logs.add(s['hand_id'])
    if api_latest:
        hand_ids_seen_in_api.add(api_latest['hand_id'])
    
    sample = {
        'seq': i + 1,
        'ts': time.time(),
        'snapshot_logs_count': len(snap_logs),
        'latest_snapshot_logs': snap_logs[-3:] if snap_logs else [],
        'latest_auths': auth_logs[-3:] if auth_logs else [],
        'api_latest': api_latest,
        'all_tables': all_tables,
    }
    samples.append(sample)
    
    # Progress
    if api_latest:
        cards_count = sum(
            len(h.get('cards', [])) for h in api_latest.get('hero_cards', {}).values()
        )
        active_seats = sum(
            1 for h in api_latest.get('hero_cards', {}).values()
            if h.get('actions') and any(a not in ('back_to_game',) for a in h['actions'])
        )
        print(f"[{i+1:3d}/{SAMPLE_COUNT}] "
              f"hand={api_latest.get('hand_id', '?')[:8]} "
              f"street={api_latest.get('street', '?')} "
              f"pot={api_latest.get('pot', 0)} "
              f"cards={cards_count} "
              f"active={active_seats} "
              f"src={api_latest.get('authority_source', '?')}")
    else:
        print(f"[{i+1:3d}/{SAMPLE_COUNT}] NO API RESPONSE")
    
    elapsed = time.time() - sample_start
    if elapsed < POLL_INTERVAL and i < SAMPLE_COUNT - 1:
        time.sleep(POLL_INTERVAL - elapsed)

# Phase B: Analyze
print(f"\n{'=' * 80}")
print(f"PIPELINE ANALYSIS")
print(f"{'=' * 80}")

# 1. Hand ID continuity
print(f"\n--- HAND IDS SEEN ---")
print(f"Seen in Flask ACCEPT logs:  {len(hand_ids_seen_in_logs)}")
for hid in sorted(hand_ids_seen_in_logs):
    print(f"  LOG: {hid}")
print(f"Seen in API /latest:       {len(hand_ids_seen_in_api)}")
for hid in sorted(hand_ids_seen_in_api):
    print(f"  API: {hid}")

# Hands in logs but NOT in API
missing_from_api = hand_ids_seen_in_logs - hand_ids_seen_in_api
if missing_from_api:
    print(f"\n⚠  HANDS IN LOGS BUT MISSING FROM API: {len(missing_from_api)}")
    for hid in sorted(missing_from_api):
        print(f"  MISSING: {hid}")
else:
    print(f"\n✓  All hands in logs also appear in API")

# 2. Analysis of all_tables vs API/latest
print(f"\n--- PER-BOT TABLE STATE vs SELECTED API ---")
# Compare: what cards exist in _tables vs what cards appear in /api/table/latest
all_cards_by_table = {}
api_cards_by_table = {}

for s in samples:
    tstate = s.get('all_tables', {})
    api = s.get('api_latest')
    
    if api:
        tid = api.get('table_id')
        if tid not in api_cards_by_table:
            api_cards_by_table[tid] = set()
        for sn, info in api.get('hero_cards', {}).items():
            cards_key = tuple(sorted(info.get('cards', [])))
            if cards_key:
                api_cards_by_table[tid].add((info.get('name'), cards_key))
    
    for tid, tdata in tstate.items():
        if tid not in all_cards_by_table:
            all_cards_by_table[tid] = set()
        for sn, cards in tdata.get('cards', {}).items():
            cards_key = tuple(sorted(cards))
            if cards_key:
                all_cards_by_table[tid].add(cards_key)

for tid in set(list(all_cards_by_table.keys()) + list(api_cards_by_table.keys())):
    all_c = all_cards_by_table.get(tid, set())
    api_c = api_cards_by_table.get(tid, set())
    missing = all_c - api_c
    print(f"\n  Table {tid}:")
    print(f"    All card sets in _tables: {len(all_c)}")
    print(f"    Card sets in API/latest:  {len(api_c)}")
    if missing:
        print(f"    ⚠  Cards in _tables but NOT in API: {len(missing)}")
        for ck in missing:
            print(f"      {ck}")
    else:
        print(f"    ✓  All card sets reach API")

# 3. Authority decisions analysis
print(f"\n--- AUTHORITY DECISIONS ---")
all_auths = []
for s in samples:
    all_auths.extend(s.get('latest_auths', []))

if all_auths:
    # Group by type
    for a in all_auths[-10:]:
        print(f"  {a['ts']}: {a['line']}")

# 4. Save raw data
output = {
    'meta': {
        'samples': SAMPLE_COUNT,
        'interval': POLL_INTERVAL,
        'timestamp': datetime.now().isoformat(),
    },
    'hand_ids_in_logs': list(hand_ids_seen_in_logs),
    'hand_ids_in_api': list(hand_ids_seen_in_api),
    'missing_from_api': list(hand_ids_seen_in_logs - hand_ids_seen_in_api),
    'card_sets_in_tables': {k: [list(x) for x in v] for k, v in all_cards_by_table.items()},
    'card_sets_in_api': {k: [list(x) for x in v] for k, v in api_cards_by_table.items()},
}

with open('/home/wa/projects/poker/E&R/investigation/pipeline_trace.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n[SAVED] /home/wa/projects/poker/E&R/investigation/pipeline_trace.json")

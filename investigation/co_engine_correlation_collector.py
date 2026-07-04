#!/usr/bin/env python3
"""
CO ↔ Engine Correlation Collector — 100 Sample Study
READ-ONLY observation agent. No modifications.
Polls CO and Engine state concurrently for 100 consecutive samples.
"""
import requests
import json
import time
import hashlib
import sys
from datetime import datetime

CO_URL = "http://localhost:4000"
ENGINE_URL = "http://localhost:5002"
POLL_INTERVAL = 0.2  # 200ms between samples
NUM_SAMPLES = 100

def canonical_hash(data):
    """Compute a stable content hash for snapshot dedup/comparison."""
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

def get_co_state():
    """Get CO state from /api/table/latest (what both CO and Engine consume)."""
    try:
        r = requests.get(f"{CO_URL}/api/table/latest", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data.get('ok'):
                return {
                    'source': 'co_latest',
                    'table': data['table'],
                    'raw_response': data,
                    'error': None
                }
            return {'source': 'co_latest', 'table': None, 'raw_response': data, 'error': data.get('error', 'not ok')}
        return {'source': 'co_latest', 'table': None, 'raw_response': None, 'error': f'HTTP {r.status_code}'}
    except Exception as e:
        return {'source': 'co_latest', 'table': None, 'raw_response': None, 'error': str(e)}

def get_all_tables():
    """Get all table entries (full CO state with per-bot data)."""
    try:
        r = requests.get(f"{CO_URL}/api/tables", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return data.get('tables', [])
        return []
    except Exception:
        return []

def get_engine_health():
    """Get engine health status."""
    try:
        r = requests.get(f"{ENGINE_URL}/api/health", timeout=2)
        if r.status_code == 200:
            return r.json()
        return {'status': f'HTTP {r.status_code}'}
    except Exception as e:
        return {'status': f'error: {e}'}

def get_engine_textarea(api_table):
    """Reconstruct the canonical text format that the Engine would display.
    This is the formatTableDataToCanonical() output from engine.js."""
    if not api_table:
        return None
    
    parts = []
    # Table identity
    parts.append(f"TABLE: {api_table.get('table_id')}")
    parts.append(f"HAND: {api_table.get('hand_id')}")
    parts.append(f"STREET: {api_table.get('street')}")
    
    # Board
    board = api_table.get('board', {})
    if board:
        flop = board.get('flop', [])
        turn = board.get('turn')
        river = board.get('river')
        if flop:
            parts.append(f"FLOP: {' '.join(flop)}")
        if turn:
            parts.append(f"TURN: {turn}")
        if river:
            parts.append(f"RIVER: {river}")
    
    # Seats and hands
    for s in api_table.get('seats', []):
        name = s.get('name') or 'EMPTY'
        hc = s.get('hole_cards', [])
        cards = ' '.join(hc) if hc else '--'
        stack = s.get('stack_zar', 0)
        hero_mark = ' [HERO]' if s.get('is_hero') else ''
        parts.append(f"SEAT {s.get('seat_no')}: {name} (ZAR{stack}){hero_mark} [{cards}]")
    
    return '\n'.join(parts)

def extract_sample_fields(table):
    """Extract standardized fields from a table for comparison."""
    if not table:
        return None
    
    board = table.get('board', {})
    board_flat = []
    if board:
        board_flat = list(board.get('flop', [])) + ([board['turn']] if board.get('turn') else []) + ([board['river']] if board.get('river') else [])
    
    # Collect hole cards per seat
    hole_cards_by_seat = {}
    needs_action_seats = []
    available_actions_by_seat = {}
    hero_seat = None
    
    for s in table.get('seats', []):
        sno = s.get('seat_no')
        hc = s.get('hole_cards', [])
        if hc:
            hole_cards_by_seat[sno] = hc
        if s.get('needs_action'):
            needs_action_seats.append(sno)
        if s.get('available_actions'):
            available_actions_by_seat[sno] = s.get('available_actions')
        if s.get('is_hero'):
            hero_seat = sno
    
    return {
        'table_id': table.get('table_id'),
        'hand_id': table.get('hand_id'),
        'street': table.get('street'),
        'pot_zar': table.get('pot_zar'),
        'board': board_flat,
        'hole_cards': hole_cards_by_seat,
        'needs_action': needs_action_seats,
        'available_actions': available_actions_by_seat,
        'hero_seat': hero_seat,
        'dealer_seat': table.get('dealer_seat'),
        'state_version': table.get('state_version'),
        'last_updated': table.get('last_updated'),
        'authority_source_bot': table.get('authority', {}).get('source_bot'),
    }

def compare_states(sample_prev, sample_curr, field):
    """Compare a specific field between two samples."""
    if sample_prev is None or sample_curr is None:
        return 'missing'
    if field not in sample_prev or field not in sample_curr:
        return 'missing'
    if sample_prev[field] == sample_curr[field]:
        return 'identical'
    return 'changed'

def collect_100_samples():
    """Collect 100 consecutive samples."""
    samples = []
    
    print(f"[COLLECTOR] Starting 100-sample collection at {datetime.now().isoformat()}")
    print(f"[COLLECTOR] Poll interval: {POLL_INTERVAL}s, estimated duration: {NUM_SAMPLES * POLL_INTERVAL:.0f}s")
    
    for i in range(NUM_SAMPLES):
        sample_start = time.time()
        
        # Primary: CO latest (what the Engine would see)
        co = get_co_state()
        
        # Secondary: all tables (complete CO state)
        all_tables = get_all_tables()
        
        # Engine health
        engine = get_engine_health()
        
        # Reconstruct Engine textarea
        table = co.get('table')
        textarea = get_engine_textarea(table)
        
        sample = {
            'sample_num': i + 1,
            'timestamp': time.time(),
            'timestamp_iso': datetime.now().isoformat(),
            'co': co,
            'all_tables_count': len(all_tables),
            'engine_health': engine,
            'table_api': table,
            'fields': extract_sample_fields(table),
            'textarea_contents': textarea,
            'textarea_hash': canonical_hash(textarea) if textarea else None,
            'api_hash': canonical_hash(co.get('raw_response')) if co.get('raw_response') else None,
            'field_hash': canonical_hash(extract_sample_fields(table)),
        }
        
        samples.append(sample)
        
        # Progress indicator
        if table:
            board_str = ''.join(sample['fields']['board']) if sample['fields'].get('board') else 'none'
            print(f"[{i+1:3d}/{NUM_SAMPLES}] hand={table.get('hand_id','?')[:8]} "
                  f"street={table.get('street','?')} "
                  f"board={board_str[:10]} "
                  f"pot={table.get('pot_zar',0)} "
                  f"seats={len(table.get('seats',[]))} "
                  f"na={sample['fields'].get('needs_action',[])} "
                  f"hash={sample['field_hash'][:8]}")
        else:
            print(f"[{i+1:3d}/{NUM_SAMPLES}] NO TABLE: {co.get('error','?')}")
        
        # Maintain poll interval
        elapsed = time.time() - sample_start
        if elapsed < POLL_INTERVAL and i < NUM_SAMPLES - 1:
            time.sleep(POLL_INTERVAL - elapsed)

    return samples

def analyze_samples(samples):
    """Correlation analysis of 100 samples."""
    
    # Extract valid samples
    valid = [s for s in samples if s['fields'] is not None]
    no_table = len(samples) - len(valid)
    
    print(f"\n{'='*80}")
    print(f"CORRELATION ANALYSIS: {len(samples)} Samples")
    print(f"{'='*80}")
    print(f"Valid samples: {len(valid)}")
    print(f"No table: {no_table}")
    
    if len(valid) < 2:
        print("[ERROR] Not enough valid samples for analysis")
        return
    
    # ── Field stability analysis ──
    fields = ['hand_id', 'table_id', 'street', 'pot_zar', 'board', 
              'hole_cards', 'needs_action', 'available_actions', 'dealer_seat']
    
    field_stats = {}
    for field in fields:
        changes = 0
        identical = 0
        values_seen = set()
        
        for i in range(1, len(valid)):
            prev_val = valid[i-1]['fields'].get(field)
            curr_val = valid[i]['fields'].get(field)
            
            # Make hashable for set
            if isinstance(prev_val, list):
                prev_hash = tuple(sorted(str(x) for x in prev_val))
            elif isinstance(prev_val, dict):
                prev_hash = tuple(sorted(f"{k}:{v}" for k, v in prev_val.items()))
            else:
                prev_hash = str(prev_val)
                
            if isinstance(curr_val, list):
                curr_hash = tuple(sorted(str(x) for x in curr_val))
            elif isinstance(curr_val, dict):
                curr_hash = tuple(sorted(f"{k}:{v}" for k, v in curr_val.items()))
            else:
                curr_hash = str(curr_val)
            
            values_seen.add(prev_hash)
            values_seen.add(curr_hash)
            
            if prev_hash == curr_hash:
                identical += 1
            else:
                changes += 1
        
        total_comparisons = identical + changes
        match_pct = (identical / total_comparisons * 100) if total_comparisons > 0 else 0
        
        field_stats[field] = {
            'changes': changes,
            'identical': identical,
            'match_pct': match_pct,
            'unique_values': len(values_seen),
        }
    
    # ── Relationship Matrix ──
    print(f"\n{'─'*80}")
    print("RELATIONSHIP MATRIX")
    print(f"{'─'*80}")
    print(f"{'Field':<25} {'Match %':>8} {'Changes':>8} {'Identical':>10} {'Values':>8}")
    print(f"{'─'*25} {'─'*8} {'─'*8} {'─'*10} {'─'*8}")
    
    for field in fields:
        s = field_stats[field]
        print(f"{field:<25} {s['match_pct']:7.1f}% {s['changes']:8d} {s['identical']:10d} {s['unique_values']:8d}")
    
    # ── Timing Analysis ──
    timestamps = [s['timestamp'] for s in valid]
    intervals = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
    
    if intervals:
        print(f"\n{'─'*80}")
        print("TIMING ANALYSIS")
        print(f"{'─'*80}")
        print(f"Collection duration: {timestamps[-1] - timestamps[0]:.2f}s")
        print(f"Average interval:    {sum(intervals)/len(intervals)*1000:.1f}ms")
        print(f"Minimum interval:    {min(intervals)*1000:.1f}ms")
        print(f"Maximum interval:    {max(intervals)*1000:.1f}ms")
    
    # ── Divergence Detection ──
    print(f"\n{'─'*80}")
    print("DIVERGENCE EVENTS (field changes between consecutive samples)")
    print(f"{'─'*80}")
    
    divergence_count = 0
    for i in range(1, len(valid)):
        prev = valid[i-1]
        curr = valid[i]
        changed_fields = []
        for field in fields:
            if compare_states(prev['fields'], curr['fields'], field) == 'changed':
                changed_fields.append(field)
        if changed_fields:
            divergence_count += 1
            t = datetime.fromtimestamp(curr['timestamp'])
            print(f"\n  Sample {curr['sample_num']} @ {t.strftime('%H:%M:%S.%f')[:-3]}:")
            for cf in changed_fields:
                pv = prev['fields'].get(cf)
                cv = curr['fields'].get(cf)
                print(f"    {cf}:")
                print(f"      prev: {pv}")
                print(f"      curr: {cv}")
    
    if divergence_count == 0:
        print("  No divergences detected — all 99 consecutive comparisons identical")
    
    # ── Statistical Summary ──
    print(f"\n{'═'*80}")
    print("STATISTICAL SUMMARY")
    print(f"{'═'*80}")
    print(f"Total samples:          {len(samples)}")
    print(f"Valid (table present):  {len(valid)}")
    print(f"No table:               {no_table}")
    print(f"Divergence events:      {divergence_count} / {len(valid)-1} comparisons")
    
    # Perfect matches (all fields identical across consecutive samples)
    perfect = sum(1 for i in range(1, len(valid)) 
                  if all(compare_states(valid[i-1]['fields'], valid[i]['fields'], f) == 'identical' 
                        for f in fields))
    partial = len(valid) - 1 - perfect
    print(f"Perfect matches:        {perfect}")
    print(f"Partial matches:        {partial}")
    
    # How many different hashes
    hashes = set(s['field_hash'] for s in valid)
    print(f"Unique field hashes:    {len(hashes)}")
    
    # Field-specific percentages for the report
    print(f"\n{'─'*80}")
    print("FIELD MATCH PERCENTAGES (table format)")
    print(f"{'─'*80}")
    for field in fields:
        s = field_stats[field]
        print(f"  {field:<22} {s['match_pct']:.0f}%")
    
    return field_stats, divergence_count, hashes

if __name__ == '__main__':
    samples = collect_100_samples()
    field_stats, div_count, hashes = analyze_samples(samples)
    
    # Save raw data
    output_file = '/home/wa/projects/poker/E&R/investigation/co_engine_100_samples.json'
    with open(output_file, 'w') as f:
        # Strip bulky raw_response to keep file manageable
        slim = []
        for s in samples:
            slim.append({
                'sample_num': s['sample_num'],
                'timestamp': s['timestamp'],
                'timestamp_iso': s['timestamp_iso'],
                'fields': s['fields'],
                'textarea_hash': s['textarea_hash'],
                'api_hash': s['api_hash'],
                'field_hash': s['field_hash'],
                'textarea_preview': s['textarea_contents'][:200] if s['textarea_contents'] else None,
            })
        json.dump(slim, f, indent=2, default=str)
    
    print(f"\n[SAVED] Raw data: {output_file}")

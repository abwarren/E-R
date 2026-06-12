#!/bin/bash
# End-to-end pipeline test: snapshot → API → engine
# Usage: bash pipe_test.sh

API="http://127.0.0.1:4000"
PASS=0
FAIL=0

check() {
    local label="$1" expected="$2" actual="$3"
    if [ "$actual" = "$expected" ]; then
        echo "  ✓ $label"
        ((PASS++))
    else
        echo "  ✗ $label — expected: $expected"
        echo "    got:      $actual"
        ((FAIL++))
    fi
}

echo "═══════════════════════════════════════════════"
echo "  PIPE TEST — REMOTEREMOTE v3.0"
echo "═══════════════════════════════════════════════"

# ── 1. Health check ──
echo ""
echo "[1] Health check"
HEALTH=$(curl -sf "$API/api/health" 2>&1)
if echo "$HEALTH" | grep -q '"ok":true'; then
    echo "  ✓ API is alive"
    ((PASS++))
else
    echo "  ✗ API unreachable: $HEALTH"
    ((FAIL++))
fi

# ── 2. Table data ──
echo ""
echo "[2] /api/table/latest"
TABLE=$(curl -sf "$API/api/table/latest" 2>&1)
TABLE_OK=$(echo "$TABLE" | python3 -c "import json,sys; d=json.load(sys.stdin); print('yes' if d.get('ok') else 'no')" 2>&1)
check "ok" "yes" "$TABLE_OK"

TABLE_ID=$(echo "$TABLE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('table',{}).get('table_id',''))" 2>&1)
echo "  table_id: $TABLE_ID"

# ── 3. Seat count with hole_cards ──
echo ""
echo "[3] Seats with hole_cards"
CARDS=$(echo "$TABLE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
seats = d.get('table',{}).get('seats',[])
with_cards = [s for s in seats if s.get('hole_cards') and len(s.get('hole_cards',[])) > 0]
print(len(with_cards))
" 2>&1)
echo "  seats with cards: $CARDS"

SEAT_DETAIL=$(echo "$TABLE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
seats = d.get('table',{}).get('seats',[])
for s in seats:
    cards = s.get('hole_cards') or []
    name = s.get('name') or '?'
    hero = '★' if s.get('is_hero') else ' '
    if cards:
        print(f'    [{hero}] Seat {s.get(\"seat_no\")}: {name:20s} {len(cards)} cards')
" 2>&1)
echo "$SEAT_DETAIL"

# ── 4. Board / street ──
echo ""
echo "[4] Street & Board"
STREET=$(echo "$TABLE" | python3 -c "import json,sys; d=json.load(sys.stdin); t=d.get('table',{}); print(t.get('street','?'))" 2>&1)
echo "  street: $STREET"
BOARDS=$(echo "$TABLE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
b = d.get('table',{}).get('board',{})
print(f'flop={b.get(\"flop\",[])} turn={b.get(\"turn\")} river={b.get(\"river\")}')
" 2>&1)
echo "  board:  $BOARDS"

# ── 5. Collector batch ──
echo ""
echo "[5] Collector batch"
BATCH=$(echo "$TABLE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
batch = d.get('table',{}).get('collector_batch')
if batch and batch.get('hands'):
    print(f'  {len(batch[\"hands\"])} hands in batch')
else:
    print('  (empty)')
" 2>&1)
echo "$BATCH"

# ── 6. Engine parse test ──
echo ""
echo "[6] /api/run — parse test"
# Build canonical input from table data
CANON=$(echo "$TABLE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
seats = d.get('table',{}).get('seats',[])
board = d.get('table',{}).get('board',{})
hands = []
for s in seats:
    cards = s.get('hole_cards') or []
    if cards:
        hands.append(''.join(cards))
board_str = ''.join([c for c in (board.get('flop') or []) + ([board['turn']] if board.get('turn') else []) + ([board['river']] if board.get('river') else [])])
print(json.dumps({'hands': hands, 'board': board_str, 'variant': 'plo6-6max', 'samples': 20}))
" 2>&1)

RUN=$(curl -sf -X POST "$API/api/run" -H 'Content-Type: application/json' -d "$CANON" 2>&1)
RUN_OK=$(echo "$RUN" | python3 -c "import json,sys; d=json.load(sys.stdin); print('yes' if d.get('ok') else d.get('error','no'))" 2>&1)
echo "  Hands sent: $(echo "$CANON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['hands']))" 2>&1)"
check "run accepted" "yes" "$RUN_OK"

if echo "$RUN" | grep -q '"run_id"'; then
    RID=$(echo "$RUN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('run_id',''))" 2>&1)
    echo "  run_id: $RID"
fi

# ── 7. Pending commands ──
echo ""
echo "[7] Pending commands"
CMDS=$(curl -sf "$API/api/health" 2>&1)
CMD_COUNT=$(echo "$CMDS" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('pending_cmds','?'))" 2>&1)
echo "  pending: $CMD_COUNT"

# ── Summary ──
echo ""
echo "═══════════════════════════════════════════════"
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

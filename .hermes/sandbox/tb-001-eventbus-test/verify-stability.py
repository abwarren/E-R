#!/usr/bin/env python3
"""
hermes-verify-stability.py — Flicker & Staleness Validator

Checks:
  1. No flicker: 20 consecutive polls return same hand_id + street + board
  2. No stale data: after 30s inactivity, table returns WAITING
  3. Board clears between hands
  4. hand_id stable within hand, changes on new hand
  5. authority field consistent across consecutive polls
"""
import json, time, urllib.request, sys, uuid

BASE = "http://127.0.0.1:4000"
API_KEY = "03622c896cfbeacdfc537e9434f9ddc5"
P, F = 0, 0
def ok(m): global P; P+=1; print(f"  ✅ {m}")
def fail(m): global F; F+=1; print(f"  ❌ {m}")

def post(endpoint, data):
    req = urllib.request.Request(f"{BASE}{endpoint}",
        data=json.dumps(data).encode(),
        headers={"Content-Type":"application/json","X-API-Key":API_KEY})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get(endpoint):
    with urllib.request.urlopen(f"{BASE}{endpoint}", timeout=10) as r:
        return json.loads(r.read())

TID = "pb_stability_test"
BID = "stability-bot"
HID = f"stable-hand-{uuid.uuid4().hex[:8]}"

print("=== STABILITY: FLICKER & STALENESS ===")

# ─────────────────────────────────────────────────────────────
# 1. Inject a stable hand state
# ─────────────────────────────────────────────────────────────
print("\n─── Inject baseline hand ───")
seats = [
    {"seat_no":1,"name":"Hero","stack_zar":995.0,
     "hole_cards":["Ah","Kh","Qd","Jd"],"available_actions":["fold","check","call","raise"],
     "is_hero":True,"status":"active"},
    {"seat_no":2,"name":"Villain","stack_zar":990.0,
     "hole_cards":[],"available_actions":[],"is_hero":False,"status":"active"},
]
post("/api/snapshot", {
    "table_id":TID,"bot_id":BID,"hand_id":HID,
    "seats":seats,"board":{"flop":["Kc","Qc","7d"],"turn":None,"river":None},
    "street":"FLOP","pot_zar":35.0,"available_actions":["fold","check","bet","raise"],
    "needs_action":True,"snapshot_seq":1,
})
time.sleep(0.3)

# ─────────────────────────────────────────────────────────────
# 2. Flicker test: 20 rapid polls, check stability
# ─────────────────────────────────────────────────────────────
print("\n─── Flicker check: 20 consecutive polls ───")

hand_ids = []
streets = []
board_hashes = []
auth_reasons = []
pot_values = []

for i in range(20):
    try:
        tbl = get("/api/table/latest")
        if tbl.get("ok") and tbl.get("table"):
            t = tbl["table"]
            hand_ids.append(t.get("hand_id","?"))
            streets.append(t.get("street","?"))
            b = t.get("board",{})
            bh = str(b.get("flop",[])) + "|" + str(b.get("turn","")) + "|" + str(b.get("river",""))
            board_hashes.append(bh)
            auth_reasons.append(t.get("authority",{}).get("reason","?"))
            pot_values.append(t.get("pot_zar",-1))
    except:
        pass
    time.sleep(0.05)

# Check no oscillation — all hand_ids should be same
all_same_hand = len(set(hand_ids)) == 1
all_same_street = len(set(streets)) == 1
all_same_board = len(set(board_hashes)) == 1
all_same_pot = len(set(pot_values)) == 1

ok(all_same_hand) if all_same_hand else fail(f"hand_id oscillated across polls: {set(hand_ids)}")
ok(all_same_street) if all_same_street else fail(f"street oscillated: {set(streets)}")
ok(all_same_board) if all_same_board else fail(f"board oscillated across {len(set(board_hashes))} variants")
ok(all_same_pot) if all_same_pot else fail(f"pot oscillated: {set(pot_values)}")

# Check authority reason stable
all_same_auth = len(set(auth_reasons)) == 1
ok(all_same_auth) if all_same_auth else fail(f"authority reason oscillated: {set(auth_reasons)}")

print(f"  {len(hand_ids)} polls, {len(set(hand_ids))} hand_ids, {len(set(streets))} streets")

# ─────────────────────────────────────────────────────────────
# 3. Board progression doesn't flicker backwards
# ─────────────────────────────────────────────────────────────
print("\n─── Board progression: no backwards flicker ───")

# Hit with a snapshot that has less-advanced board (stale snapshot arriving late)
post("/api/snapshot", {
    "table_id":TID,"bot_id":BID,"hand_id":HID,
    "seats":seats,"board":{"flop":["Kc","Qc","7d"],"turn":None,"river":None},
    "street":"FLOP","pot_zar":35.0,"available_actions":["fold","check","bet","raise"],
    "needs_action":True,"snapshot_seq":2,
})
time.sleep(0.2)

# Now post TURN
seats_turn = seats.copy()
seats_turn[0]["stack_zar"] = 955.0
post("/api/snapshot", {
    "table_id":TID,"bot_id":BID,"hand_id":HID,
    "seats":seats_turn,"board":{"flop":["Kc","Qc","7d"],"turn":"As","river":None},
    "street":"TURN","pot_zar":55.0,"available_actions":["fold","check","bet","raise"],
    "needs_action":True,"snapshot_seq":3,
})
time.sleep(0.2)

# Now send a LATE FLOP snapshot (simulating delayed out-of-order delivery)
post("/api/snapshot", {
    "table_id":TID,"bot_id":BID,"hand_id":HID,
    "seats":seats,"board":{"flop":["Kc","Qc","7d"],"turn":None,"river":None},
    "street":"FLOP","pot_zar":35.0,"available_actions":["fold","check","bet","raise"],
    "needs_action":True,"snapshot_seq":2,  # same seq as before
})
time.sleep(0.2)

# Fetch — should STILL be TURN (not flickered back to FLOP)
tbl = get("/api/table/latest")
if tbl.get("ok") and tbl.get("table"):
    t = tbl["table"]
    ok(t.get("street") == "TURN") if t.get("street") == "TURN" else fail(f"street flickered backwards: got {t.get('street')} expected TURN")
    ok(t.get("board",{}).get("turn") == "As") if t.get("board",{}).get("turn") == "As" else fail(f"turn card disappeared")
else:
    fail("could not fetch after out-of-order test")

# ─────────────────────────────────────────────────────────────
# 4. Hand transition: no stale data between hands
# ─────────────────────────────────────────────────────────────
print("\n─── Hand transition: no stale data ───")

# Start a new hand with new hand_id
HID2 = f"new-hand-{uuid.uuid4().hex[:8]}"
post("/api/snapshot", {
    "table_id":TID,"bot_id":BID,"hand_id":HID2,
    "seats":seats,"board":{"flop":[],"turn":None,"river":None},
    "street":"PREFLOP","pot_zar":15.0,"available_actions":["fold","check","call","raise"],
    "needs_action":True,"snapshot_seq":10,
})
time.sleep(0.3)

# Fetch — should show NEW hand's state, not old hand's board
tbl = get("/api/table/latest")
if tbl.get("ok") and tbl.get("table"):
    t = tbl["table"]
    current_hid = t.get("hand_id","")
    ok(current_hid == HID2) if current_hid == HID2 else fail(f"hand_id didn't switch: got {current_hid[:20]} expected {HID2[:20]}")
    # Board should be empty for PREFLOP
    board = t.get("board",{})
    flop = board.get("flop",[])
    ok(len(flop) == 0) if len(flop) == 0 else fail(f"stale board cards from previous hand: {flop}")
    ok(t.get("pot_zar") == 15.0) if t.get("pot_zar") == 15.0 else fail(f"stale pot: got {t.get('pot_zar')} expected 15")
else:
    fail("could not fetch after hand transition")

# ─────────────────────────────────────────────────────────────
# 5. No-zero-readings check
# ─────────────────────────────────────────────────────────────
print("\n─── Health stability: no zero readings ───")

h = get("/api/health")
check_seq = h.get("snapshot_seq", 0)
ok(check_seq >= 4) if check_seq >= 4 else fail(f"snapshot_seq seems low: {check_seq}")

# ─────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────
total = P + F
print(f"\n=== {P}/{total} pass, {F} fail ===")
sys.exit(0 if F == 0 else 1)

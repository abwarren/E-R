"""Debug: print raw /api/latest response."""
import json
import urllib.request

url = "http://127.0.0.1:1080/api/latest"
req = urllib.request.Request(url)
req.add_header("Accept", "application/json")

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        # Print keys and table_id
        print(f"ok: {data.get('ok')}")
        t = data.get('table', {})
        print(f"table keys: {list(t.keys())}")
        print(f"table_id: {t.get('table_id')}")
        print(f"hand_id: {t.get('hand_id', '?')[:16]}")
        print(f"street: {t.get('street')}")
        print(f"seats count: {len(t.get('seats', []))}")
        print(f"last_updated: {t.get('last_updated')}")
        # Print first seat
        seats = t.get('seats', [])
        if seats:
            s0 = seats[0]
            print(f"seat[0] keys: {list(s0.keys())}")
            print(f"seat[0] name: {s0.get('name')}")
            print(f"seat[0] hole_cards: {s0.get('hole_cards')}")
            print(f"seat[0] available_actions: {s0.get('available_actions')}")
        print()
        print("FULL RESPONSE:")
        print(json.dumps(data, indent=2, default=str)[:3000])
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

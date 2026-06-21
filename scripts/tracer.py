#!/usr/bin/env python3
"""
W4P PIPELINE TRACER BULLET
Run on Warren's laptop. Validates all 6 layers end-to-end.
Usage: python3 /home/wa/tracer.py

Layer map:
  L1  Express  :4000   /health       proxy alive
  L2  Flask    :1080   /api/health   backend alive
  L3  Snapshots        /api/tables   seat data flowing
  L4  Engine   :5002   /api/health   equity engine
  L5  UI       :4000/               remote control HTML
  L6  Hero seat        /api/tables   1+ seat with is_hero:true

Also does: launch browser with extension + CDP, wait for seats, run full trace.
"""
import subprocess, time, os, sys, glob, json, argparse, datetime

# ─── config ─────────────────────────────────────────────────
CHROMIUM_BIN = "/snap/chromium/current/usr/lib/chromium-browser/chrome"
EXT_DIR      = "/tmp/w4p_ext_chromium"
PROFILE_DIR  = "/tmp/w4p_profile_chromium"
CDP_PORT     = 9222
GOLDRUSH_URL = "https://www.goldrush.co.za/live-poker"
FLASK_LOG    = "/tmp/flask.log"
EXPRESS_LOG  = "/tmp/express.log"
API_KEY      = "03622c896cfbeacdfc537e9434f9ddc5"

def die(msg):
    print(f"FATAL: {msg}")
    sys.exit(1)

def cmd(args, timeout=10):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

def curl(url, extra_args=None, timeout=5):
    parts = ["curl", "-s", "--max-time", str(timeout)]
    if extra_args:
        parts.extend(extra_args)
    parts.append(url)
    return cmd(parts, timeout + 2)

def jq(text, key):
    try:
        d = json.loads(text)
        return d.get(key)
    except:
        return None

def green(s):  return f"\033[32m{s}\033[0m"
def red(s):    return f"\033[31m{s}\033[0m"
def yellow(s): return f"\033[33m{s}\033[0m"

def check(label, ok, detail=""):
    mark = green("PASS") if ok else red("FAIL")
    print(f"  {mark}  {label}  {detail}")

def announce(title):
    print()
    print("=" * 55)
    print(f"  {title}")
    print("=" * 55)

# ─── setup display (for SSH) ───────────────────────────────
os.environ["DISPLAY"] = ":0"
xa = glob.glob("/run/user/1000/.mutter-Xwaylandauth.*")
if xa:
    os.environ["XAUTHORITY"] = xa[0]

# ─── args ───────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="W4P Pipeline Tracer")
parser.add_argument("--launch", action="store_true",
                    help="Kill old browser, launch fresh Chromium with extension")
parser.add_argument("--quick", action="store_true",
                    help="Run trace only, no browser launch")
args = parser.parse_args()

# ─── browser launch ─────────────────────────────────────────
if not args.quick:
    announce("KILLING STALE BROWSERS")
    subprocess.run(["pkill", "-9", "-f", "w4p_profile_chromium"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "brave"], capture_output=True)
    time.sleep(2)
    print("  Old processes killed")

    announce("LAUNCHING CHROMIUM")
    subprocess.Popen([
        CHROMIUM_BIN,
        "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={PROFILE_DIR}",
        f"--load-extension={EXT_DIR}",
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        GOLDRUSH_URL
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)

    # verify CDP
    try:
        r = curl(f"http://127.0.0.1:{CDP_PORT}/json")
        pages = json.loads(r)
        for p in pages:
            if p.get("type") == "page":
                print(f"  CDP: {p.get('title', '?')[:60]}")
                print(f"  URL: {p.get('url', '?')[:100]}")
    except:
        die("Browser did not start or CDP port not reachable")

    announce("WAITING FOR SEATS (~35s)")
    print("  The game iframe needs to load, then w4p.js waits 30s for seat containers.")
    print("  If a cash table is already open in a tab, seats will appear faster.")
    time.sleep(35)

# ─── tracer ─────────────────────────────────────────────────
announce("W4P PIPELINE TRACER")
print(f"  Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# L1: Express health
r = curl("http://127.0.0.1:4000/health")
ok = jq(r, "ok")
check("L1 Express :4000    /health", ok, "")

# L2: Flask health
r = curl("http://127.0.0.1:1080/api/health")
ok = jq(r, "ok")
seq = jq(r, "snapshot_seq") or "?"
check("L2 Flask   :1080    /api/health", ok, f"seq={seq}")

# L4: Engine health
r = curl("http://127.0.0.1:5002/api/health")
ok = jq(r, "ok")
check("L4 Engine  :5002    /api/health", ok, "")

# L5: UI root
r = subprocess.run(["curl", "-sI", "--max-time", "3", "http://127.0.0.1:4000/"],
                   capture_output=True, text=True)
ok = "200" in r.stdout.split("\n")[0] if r.stdout else False
check("L5 UI      :4000/   GET /", ok, "")

print()

# L3 + L6: Table data
r = curl("http://127.0.0.1:4000/api/tables")
try:
    d = json.loads(r)
    tables = d.get("tables", [])
    live_count = 0
    hero_count = 0
    for t in tables:
        seats = t.get("seats", [])
        named = [s for s in seats if s.get("name")]
        hero = [s for s in seats if s.get("is_hero")]
        if named:
            live_count += 1
            hero_count += len(hero)
            print(f"  {green('LIVE')}  table={t['table_id']}  seats={len(named)}  hero={'Y' if hero else 'N'}")
            for s in seats:
                n = s.get("name") or "(empty)"
                h = "HERO" if s.get("is_hero") else ""
                st = s.get("stack_zar", 0)
                if n != "(empty)" or h:
                    idx = s.get("seat_index", 0)
                    print(f"       seat{idx+1}: {n[:16]:16s} stack={st:8.1f}  {h}")
    if live_count == 0:
        print(f"  {red('DEAD')}  No tables with seat data")
        print(f"  → Open a cash table in the GoldRush iframe")
    else:
        print()
        check("L3 Snapshot data    /api/tables", True, f"{live_count} table(s) with seats")
        check("L6 Hero seat        /api/tables", hero_count > 0, f"{hero_count} hero seat(s)")

    # Show stale tables too
    stale = [t for t in tables if not any(s.get("name") for s in t.get("seats", []))]
    if stale:
        print(f"\n  Stale tables (no seats): {len(stale)}")
except:
    print(f"  {red('ERROR')}  Could not parse /api/tables")
    print(f"  Raw: {r[:200]}")

# ─── Flask activity ─────────────────────────────────────────
print()
r = grep_count = cmd(["grep", "-c", "POST /api/snapshot", FLASK_LOG]) or "0"
print(f"Flask snapshot POSTs total: {grep_count}")
recent = cmd(["grep", "POST /api/snapshot", FLASK_LOG])
for line in recent.split("\n")[-5:]:
    if line.strip():
        print(f"  {line.strip()}")

# ─── browser check ──────────────────────────────────────────
print()
try:
    r = curl(f"http://127.0.0.1:{CDP_PORT}/json")
    pages = json.loads(r)
    for p in pages:
        if p.get("type") == "page":
            url = p.get("url", "")[:120]
            title = p.get("title", "")[:60]
            print(f"Browser: {title} | {url}")
except:
    print(f"Browser: {red('CDP DEAD')} — CDP port {CDP_PORT} unreachable")

# ─── summary ────────────────────────────────────────────────
print()
print("=" * 55)
print("  FIX COMMANDS (if needed)")
print("=" * 55)
print("""
# Restart Express
cd ~/projects/poker/E\&R/scripts && nohup node server.js > /tmp/express.log 2>&1 &

# Restart Flask (PORT=1080 is critical)
cd ~/projects/poker/E\&R/backend && PORT=1080 nohup ./venv/bin/python app.py > /tmp/flask.log 2>&1 &

# Restart Engine
cd ~/projects/poker/ENGINEENGINE/source && \
  nohup ./venv/bin/python app.py --port 5002 > /tmp/engine.log 2>&1 &

# Sync extension after w4p.js edit
for d in /tmp/w4p_ext_*/; do
  cp /home/wa/projects/poker/E\&R/source/w4p-extension-dev/w4p.js "$d/w4p.js"
done

# Kill + relaunch browser
python3 /home/wa/tracer.py --launch
""")

print("Done.")

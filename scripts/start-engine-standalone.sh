#!/usr/bin/env bash
# PLO Engine UI — Standalone Startup Script
# Starts both the engine Flask (port 5002) and the Express proxy (port 4001).
# The engine Flask runs the real Monte Carlo equity scripts with eval7.
set -e

ENGINE_DIR="/home/wa/ENGINEENGINE"
LOG_DIR="$ENGINE_DIR/logs"
SCRIPTS_DIR="$ENGINE_DIR/scripts"
SOURCE_DIR="$ENGINE_DIR/source"

mkdir -p "$LOG_DIR"

echo ""
echo "  Starting PLO Engine UI — Standalone"
echo "  ------------------------------------------"
echo ""

# Step 1: Start engine Flask on port 5002 (real equity + RNG)
echo "  [1/3] Starting Engine Flask (port 5002)..."
pkill -f "python $SOURCE_DIR/app.py" 2>/dev/null || true
sleep 1
cd "$SOURCE_DIR"
source venv/bin/activate
nohup python app.py > "$LOG_DIR/engine-flask.log" 2>&1 &
FLASK_PID=$!
echo "        Flask PID: $FLASK_PID"
sleep 3

if curl -sf http://127.0.0.1:5002/api/health > /dev/null 2>&1; then
    echo "        ✓ Engine Flask is running (equity + RNG)"
else
    echo "        ERROR: Engine Flask failed to start"
    cat "$LOG_DIR/engine-flask.log"
    exit 1
fi

# Step 2: Ensure shared backend is running (check, don't start)
echo "  [2/3] Checking Shared Backend API (port 1080)..."
if curl -sf http://127.0.0.1:1080/api/health > /dev/null 2>&1; then
    echo "        ✓ Shared Backend is running (table state, snapshots)"
else
    echo "        ⚠ Shared Backend is NOT running on 127.0.0.1:1080"
    echo "        Start it first: cd /home/wa/REMOTEREMOTE/backend && python app.py"
    echo "        Continuing (equity/RNG will work, but table state unavailable)..."
fi

# Step 3: Start Express proxy on port 4001
echo "  [3/3] Starting Express proxy (port 4001)..."
cd "$SCRIPTS_DIR"
nohup node server-standalone.js > "$LOG_DIR/engine-ui.log" 2>&1 &
EXPRESS_PID=$!
echo "        Express PID: $EXPRESS_PID"
sleep 2

if kill -0 $EXPRESS_PID 2>/dev/null; then
    echo "        ✓ Express proxy is running"
else
    echo "        ERROR: Express proxy failed to start"
    cat "$LOG_DIR/engine-ui.log"
    exit 1
fi

echo ""
echo "  All services started!"
echo "  ─────────────────────────────────────"
echo "  Engine UI:     http://localhost:4001/engine"
echo "  Equity API:    POST :5002/api/run  (via engine Flask)"
echo "  RNG API:       POST :5002/api/rng/generate  (via engine Flask)"
echo "  Engine health: http://localhost:4001/health"
echo ""
echo "  Routing:"
echo "    Equity/RNG → http://127.0.0.1:5002 (real Monte Carlo engine)"
echo "    Shared API  → http://127.0.0.1:1080 (table state, snapshots)"
echo ""
echo "  Logs:"
echo "    Engine Flask: $LOG_DIR/engine-flask.log"
echo "    Express UI:   $LOG_DIR/engine-ui.log"
echo ""
echo "  Stop: pkill -f 'python $SOURCE_DIR/app.py'; pkill -f 'node server-standalone.js'"
echo ""

# Health checks
echo "  Verifying..."
sleep 1

if curl -sf http://localhost:4001/health > /dev/null 2>&1; then
    echo "  ✓ Engine UI server PASSED"
else
    echo "  ✗ Engine UI server FAILED"
fi

if curl -sf http://localhost:5002/api/health > /dev/null 2>&1; then
    echo "  ✓ Engine Flask (equity+RNG) PASSED"
else
    echo "  ✗ Engine Flask FAILED"
fi

if curl -sf -X POST http://localhost:4001/api/rng/generate \
    -H "Content-Type: application/json" \
    -d '{"variant":"PLO5","table_size":6,"street":"FLOP","sample_count":1}' > /dev/null 2>&1; then
    echo "  ✓ RNG through proxy PASSED"
else
    echo "  ✗ RNG through proxy FAILED"
fi

echo ""

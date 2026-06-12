#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$ENGINE_DIR/logs"

echo ""
echo "  Starting PLO Equity Engine - Local Clone"
echo "  ------------------------------------------"
echo ""

# Kill any existing processes on our ports
pkill -f "node $ENGINE_DIR/scripts/server.js" 2>/dev/null || true
pkill -f "python $ENGINE_DIR/source/app.py" 2>/dev/null || true
sleep 1

# Step 1: Start Flask backend on port 5002
echo "  [1/2] Starting Flask backend (port 5002)..."
cd "$ENGINE_DIR/source"
source venv/bin/activate
nohup python app.py > "$LOG_DIR/flask.log" 2>&1 &
FLASK_PID=$!
echo "        Flask PID: $FLASK_PID"
sleep 4

if kill -0 $FLASK_PID 2>/dev/null; then
    echo "        Flask backend is running"
else
    echo "        ERROR: Flask backend failed to start"
    cat "$LOG_DIR/flask.log"
    exit 1
fi

# Step 2: Start Express proxy on port 4002
echo "  [2/2] Starting Express proxy (port 4002)..."
cd "$ENGINE_DIR/scripts"
nohup node server.js > "$LOG_DIR/express.log" 2>&1 &
EXPRESS_PID=$!
echo "        Express PID: $EXPRESS_PID"
sleep 4

if kill -0 $EXPRESS_PID 2>/dev/null; then
    echo "        Express proxy is running"
else
    echo "        ERROR: Express proxy failed to start"
    cat "$LOG_DIR/express.log"
    exit 1
fi

echo ""
echo "  All services started successfully!"
echo "  ─────────────────────────────────────"
echo "  Local URL:  http://localhost:4002"
echo "  Engine URL: http://localhost:4002/engine"
echo "  Login:      admin / PokerPass12345"
echo "  Logs:       $LOG_DIR/"
echo "  Stop:       pkill -f 'python $ENGINE_DIR/source/app.py'; pkill -f 'node $ENGINE_DIR/scripts/server.js'"
echo "  Dashboard:  http://localhost:4002/engine/dashboard  (if route exists)"
echo ""

#!/bin/bash
# ── E&R container entrypoint ──
# Starts Flask backend (1080) then Express frontend (4000) in same container.
# If Flask dies, Express still serves but returns 503 from proxy.
# Docker healthcheck hits Flask directly so container restarts if backend dies.

set -e

echo "[entrypoint] Starting REMOTEREMOTE backend (Flask :1080)..."
cd /app/backend
python app.py &
FLASK_PID=$!

# Wait for Flask health
echo -n "[entrypoint] Waiting for Flask..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:1080/api/health > /dev/null 2>&1; then
        echo " OK (PID $FLASK_PID)"
        break
    fi
    sleep 1
    echo -n "."
done

echo "[entrypoint] Starting Express frontend (:4000)..."
cd /app/scripts
exec node server-container.js

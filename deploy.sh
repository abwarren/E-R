#!/bin/bash
# ── E&R Docker Deploy ──────────────────────────────────────────────────────
# One-command deployment for barebones Linux with Docker + docker compose.
#
# Usage (fresh machine):
#   git clone git@github.com:abwarren/E-R.git REMOTEREMOTE
#   cd REMOTEREMOTE
#   ./deploy.sh
#
# What it does:
#   1. Clones ENGINEENGINE repo alongside (if missing)
#   2. Creates .env from sample or prompts
#   3. Builds both Docker images
#   4. Starts containers with health checks + auto-restart
#   5. Prints access URLs
# ────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════╗"
echo "║     E&R — Docker Deploy                 ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Clone ENGINEENGINE if missing ───────────────────────────────────────
if [ ! -d "../ENGINEENGINE" ] && [ ! -d "$PARENT_DIR/ENGINEENGINE" ]; then
    echo "[1/6] Cloning ENGINEENGINE..."
    cd "$PARENT_DIR"
    git clone -b engine git@github.com:abwarren/E-R.git ENGINEENGINE
    echo "   ENGINEENGINE cloned"
else
    echo "[1/6] ENGINEENGINE found — skipping clone"
fi
cd "$SCRIPT_DIR"

# ── 2. .env setup ──────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "[2/6] Creating .env..."
    cat > .env << 'DOTENV'
# Fill in your keys below:

TRACKER_API_KEY=*** DOTENV
    echo "   .env created — edit it with your real API keys, then re-run deploy.sh"
    exit 1
else
    echo "[2/6] .env exists — using existing"
fi

# ── 3. Build ──────────────────────────────────────────────────────────────
echo "[3/6] Building Docker images..."
docker compose build 2>&1 | grep -E "Built|ERROR" || true

# ── 4. Down stale ─────────────────────────────────────────────────────────
echo "[4/6] Stopping stale containers..."
docker compose down --remove-orphans 2>/dev/null || true

# ── 5. Start ──────────────────────────────────────────────────────────────
echo "[5/6] Starting containers..."
docker compose up -d

# ── 6. Wait for healthy ────────────────────────────────────────────────────
echo "[6/6] Waiting for health checks..."
for svc in engine remote; do
    echo -n "   $svc..."
    for i in $(seq 1 30); do
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "er-$svc" 2>/dev/null || echo "missing")
        if [ "$STATUS" = "healthy" ]; then
            echo " OK"
            break
        fi
        sleep 2
        echo -n "."
    done
done

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     E&R — Running                        ║"
echo "╠══════════════════════════════════════════╣"
printf "║  %-38s ║\n" "Remote UI:  http://localhost:4000/remote"
printf "║  %-38s ║\n" "Engine:     http://localhost:5002/"
echo "╚══════════════════════════════════════════╝"
echo ""

curl -sf http://localhost:4000/api/health > /dev/null 2>&1 && echo "  OK Remote UI" || echo "  FAIL Remote UI"
curl -sf http://localhost:5002/api/health > /dev/null 2>&1 && echo "  OK Engine" || echo "  FAIL Engine"
echo ""
echo "Logs:  docker compose logs -f"
echo "Stop:  docker compose down"

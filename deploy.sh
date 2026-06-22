#!/usr/bin/env bash
# ============================================================
# deploy.sh — W4P Poker Platform Production Deploy
# Target: barebones Linux (Ubuntu 24.04 tested)
# Run as root or user with Docker permissions
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
DEPLOY_LOG="/tmp/w4p-deploy.log"
TAG="${1:-latest}"

log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$DEPLOY_LOG"; }
die()  { log "FATAL: $*"; exit 1; }

# ── Prerequisites ──────────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "Docker not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not found"

log "=== W4P Poker Platform Deploy (tag=$TAG) ==="
log "Project root: $PROJECT_ROOT"

# ── 1. Port conflict guard ─────────────────────────────────
for port in 4000 5002; do
    if ss -tlnp | grep -q ":$port "; then
        log "WARNING: Port $port is in use — killing stale process"
        fuser -k "$port/tcp" 2>/dev/null || true
        sleep 1
    fi
done

# ── 2. Build images ────────────────────────────────────────
log "Building Docker images..."
cd "$PROJECT_ROOT"

docker compose build --no-cache 2>&1 | tee -a "$DEPLOY_LOG" || {
    log "Build failed — trying without cache bypass"
    docker compose build 2>&1 | tee -a "$DEPLOY_LOG" || die "Build failed"
}

# ── 3. Start services ──────────────────────────────────────
log "Starting containers..."
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d 2>&1 | tee -a "$DEPLOY_LOG"

sleep 4

# ── 4. Health checks ───────────────────────────────────────
log "Running health checks..."

check_http() {
    local url="$1" label="$2"
    local resp
    resp=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)
    if [ "$resp" = "200" ]; then
        log "  PASS $label ($url)"
        return 0
    else
        log "  FAIL $label ($url) — HTTP $resp"
        return 1
    fi
}

FAILS=0

check_http "http://127.0.0.1:4000/api/health"   "Express :4000" || ((FAILS++))
check_http "http://127.0.0.1:4000/remote"       "Remote UI"     || ((FAILS++))
check_http "http://127.0.0.1:4000/api/tables"    "Tables API"    || ((FAILS++))
check_http "http://127.0.0.1:5002/api/health"    "Engine :5002"  || ((FAILS++))

# Flask internal check (runs inside er-remote container)
FLASK_HEALTH=$(docker exec er-remote curl -s http://127.0.0.1:1080/api/health 2>/dev/null)
if echo "$FLASK_HEALTH" | grep -q '"ok":true'; then
    log "  PASS Flask :1080 (internal)"
else
    log "  FAIL Flask :1080 — $FLASK_HEALTH"
    ((FAILS++))
fi

# ── 5. Summary ─────────────────────────────────────────────
if [ $FAILS -eq 0 ]; then
    log "=== ALL HEALTH CHECKS PASSED ==="
    log "  Remote UI:  http://localhost:4000/remote"
    log "  Engine:     http://localhost:5002"
    log "  API:        http://localhost:4000/api/tables"
    log ""
    log "  Next: launch browsers with extension, navigate to GoldRush"
else
    log "=== $FAILS health check(s) FAILED — check logs ==="
    log "  docker logs er-remote --tail 50"
    log "  docker logs er-engine --tail 50"
    exit 1
fi

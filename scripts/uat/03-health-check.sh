#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# 03-health-check.sh
# Verifies all UAT services are running and responsive.
# Tests public endpoints without auth, protected endpoints with auth.
# Run with: bash scripts/03-health-check.sh
# ---------------------------------------------------------------

HOST="${HOST:-localhost}"
PORT="${HTTP_PORT:-8080}"
BASE="http://$HOST:$PORT"
API="$BASE/api/v1"

echo "=== FUTURE Platform - UAT Health Check ==="
echo "Target: $BASE"
echo ""

PASS=0
FAIL=0

check_public() {
    local name="$1"
    local url="$2"
    local expected="${3:-200}"

    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
    if [ "$response" = "$expected" ]; then
        echo "  [PASS] $name (HTTP $response)"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name (expected $expected, got $response)"
        FAIL=$((FAIL + 1))
    fi
}

check_auth() {
    local name="$1"
    local url="$2"
    local token="$3"
    local expected="${4:-200}"

    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "Authorization: Bearer $token" "$url" 2>/dev/null || echo "000")
    if [ "$response" = "$expected" ]; then
        echo "  [PASS] $name (HTTP $response)"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name (expected $expected, got $response)"
        FAIL=$((FAIL + 1))
    fi
}

# -------------------------------------------------------
# Infrastructure (no auth)
# -------------------------------------------------------
echo "[Infrastructure]"
check_public "Frontend served" "$BASE/index.html"
check_public "Backend health" "$BASE/health"

# -------------------------------------------------------
# Auth — get a token for protected endpoints
# -------------------------------------------------------
echo ""
echo "[Authentication]"

# Read admin password from .env
ADMIN_USER="admin"
ADMIN_PASS=$(grep BOOTSTRAP_ADMIN_PASSWORD /opt/future-uat/backend/.env 2>/dev/null | cut -d= -f2 || echo "")

TOKEN=""
if [ -n "$ADMIN_PASS" ]; then
    LOGIN_RESP=$(curl -s --max-time 10 -X POST "$API/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"identifier\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" 2>/dev/null || echo "{}")
    TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")
fi

if [ -n "$TOKEN" ]; then
    echo "  [PASS] Login as $ADMIN_USER (token obtained)"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] Login as $ADMIN_USER (no token)"
    FAIL=$((FAIL + 1))
fi

check_public "Register page" "$BASE/register.html"

# -------------------------------------------------------
# Protected API endpoints (with auth token)
# -------------------------------------------------------
echo ""
echo "[Core API]"

if [ -n "$TOKEN" ]; then
    check_auth "Auth /me" "$API/auth/me" "$TOKEN"
    check_auth "Model readiness" "$API/predictive/model-readiness" "$TOKEN"
    check_auth "Model metrics" "$API/predictive/model-metrics" "$TOKEN"
    check_auth "Forecasts" "$API/predictive/forecast/jobs" "$TOKEN"
    check_auth "Feature importance" "$API/predictive/forecast/feature-importance" "$TOKEN"
    check_auth "Data quality summary" "$API/ingestion/data-quality/summary" "$TOKEN"
    check_auth "Security readiness" "$API/operations/security-readiness" "$TOKEN"
    check_auth "Deployment readiness" "$API/operations/deployment-readiness" "$TOKEN"
    check_auth "Skills summary" "$API/skills/summary" "$TOKEN"
else
    echo "  [SKIP] Protected endpoints — no auth token"
fi

# -------------------------------------------------------
# Docker status
# -------------------------------------------------------
echo ""
echo "[Docker]"
DOCKER_OK=true
for SVC in future-postgres future-backend future-nginx; do
    STATUS=$(docker inspect --format='{{.State.Status}}' "$SVC" 2>/dev/null || echo "missing")
    if [ "$STATUS" = "running" ]; then
        echo "  [PASS] $SVC running"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $SVC $STATUS"
        FAIL=$((FAIL + 1))
        DOCKER_OK=false
    fi
done

# -------------------------------------------------------
# Summary
# -------------------------------------------------------
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -eq 0 ]; then
    echo "=== ALL CHECKS PASSED ==="
    exit 0
else
    echo "=== SOME CHECKS FAILED ==="
    echo "Logs: docker compose -f /opt/future-uat/docker-compose.yml logs"
    exit 1
fi

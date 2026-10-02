#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# 02-start-uat.sh
# Builds and starts the UAT environment.
# Steps: stop → build → start postgres → migrate → start backend → approve admin → start nginx
# Run with: bash scripts/02-start-uat.sh
# ---------------------------------------------------------------

INSTALL_DIR="/opt/future-uat"

echo "=== FUTURE Platform - UAT Startup ==="
echo ""

cd "$INSTALL_DIR"

# Verify .env exists
if [ ! -f "backend/.env" ]; then
    echo "ERROR: backend/.env not found."
    echo "Run: bash scripts/01-generate-env.sh"
    exit 1
fi

# Create required directories (idempotent)
mkdir -p backend/{models,data/raw,data/processed,data/temporal,data/output,logs,migrations} nginx/logs frontend

# -------------------------------------------------------
# 1. Stop existing containers
# -------------------------------------------------------
echo "[1/7] Stopping existing containers..."
docker compose down --remove-orphans 2>/dev/null || true

# -------------------------------------------------------
# 2. Build Docker images (only rebuild if Dockerfile or requirements.txt changed)
# -------------------------------------------------------
echo "[2/7] Building Docker images..."
# Check if build is needed by comparing checksums
BUILD_NEEDED=false
if [ ! -f ".build_checksum" ]; then
    BUILD_NEEDED=true
else
    CURRENT_CHECKSUM=$(md5sum backend/Dockerfile backend/requirements.txt 2>/dev/null | md5sum | awk '{print $1}')
    OLD_CHECKSUM=$(cat .build_checksum 2>/dev/null || echo "none")
    if [ "$CURRENT_CHECKSUM" != "$OLD_CHECKSUM" ]; then
        BUILD_NEEDED=true
    fi
fi

if [ "$BUILD_NEEDED" = true ]; then
    echo "  Changes detected — rebuilding..."
    docker compose build --no-cache
    md5sum backend/Dockerfile backend/requirements.txt 2>/dev/null | md5sum | awk '{print $1}' > .build_checksum
else
    echo "  No changes — using existing image."
fi

# -------------------------------------------------------
# 3. Start PostgreSQL
# -------------------------------------------------------
echo "[3/7] Starting PostgreSQL..."
docker compose up -d postgres

echo "  Waiting for PostgreSQL to be healthy..."
for i in $(seq 1 30); do
    HEALTHY=$(docker inspect --format='{{.State.Health.Status}}' future-postgres 2>/dev/null || echo "unknown")
    if [ "$HEALTHY" = "healthy" ]; then
        echo "  PostgreSQL is healthy."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ERROR: PostgreSQL failed to become healthy."
        docker compose logs postgres
        exit 1
    fi
    sleep 3
done

# -------------------------------------------------------
# 4. Start backend (force-recreate to pick up .env changes)
# -------------------------------------------------------
echo "[4/7] Starting backend..."
docker compose up -d --force-recreate backend

echo "  Waiting for backend to become healthy (up to 120s)..."
for i in $(seq 1 24); do
    sleep 5
    HEALTHY=$(docker inspect --format='{{.State.Health.Status}}' future-backend 2>/dev/null || echo "unknown")
    echo "  [$((i*5))s] Backend: $HEALTHY"
    if [ "$HEALTHY" = "healthy" ]; then
        echo "  Backend is healthy!"
        break
    fi
    if [ "$HEALTHY" = "unhealthy" ]; then
        echo "  ERROR: Backend is unhealthy! Check logs:"
        echo "    docker compose logs backend"
        exit 1
    fi
done

# -------------------------------------------------------
# 5. Run Alembic migrations (idempotent — safe on existing DB)
# -------------------------------------------------------
echo "[5/7] Running database migrations..."
docker exec future-backend alembic upgrade head 2>&1 || {
    echo "  WARNING: Alembic migration had issues (may be OK if already up to date)"
}

# -------------------------------------------------------
# 6. Approve bootstrap admin user
# -------------------------------------------------------
echo "[6/7] Ensuring admin user is approved..."
docker exec future-backend python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    result = db.execute(text(\"SELECT identity_id, approval_status FROM jus01_systemidentity WHERE identity_id='admin'\"))
    row = result.fetchone()
    if row and row[1] != 'approved':
        db.execute(text(\"UPDATE jus01_systemidentity SET approval_status='approved', is_active=true, is_admin=true WHERE identity_id='admin'\"))
        db.commit()
        print('  Admin user approved.')
    elif row:
        print('  Admin user already approved.')
    else:
        print('  No admin user found (bootstrap will create on next restart).')
except Exception as e:
    print(f'  Warning: {e}')
finally:
    db.close()
" 2>&1 || echo "  WARNING: Admin approval step failed (non-critical)"

# -------------------------------------------------------
# 7. Start Nginx
# -------------------------------------------------------
echo "[7/7] Starting Nginx..."
docker compose up -d nginx

echo ""
echo "=== Container Status ==="
docker compose ps

echo ""
echo "=== UAT Started ==="
echo "Frontend: http://localhost:8080"
echo "Backend:  http://localhost:8080/api/v1/health"
echo "Admin:    admin / (password you set in 01-generate-env.sh)"
echo ""
echo "Health check: bash scripts/03-health-check.sh"
echo "View logs:    docker compose logs -f"
echo "Stop:         docker compose down"

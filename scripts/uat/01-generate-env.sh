#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# 01-generate-env.sh
# Creates .env file for the backend container.
# PostgreSQL runs as a local Docker container (see docker-compose.yml).
# Database/application secrets are generated locally; no secret is committed.
# Idempotent: warns if .env exists, asks before overwriting.
# Run with: bash scripts/01-generate-env.sh
# ---------------------------------------------------------------

INSTALL_DIR="/opt/future-uat"
ENV_FILE="$INSTALL_DIR/backend/.env"

echo "=== FUTURE Platform - Environment Setup ==="
echo "PostgreSQL runs as a local Docker container (no external DB needed)."
echo ""

# Check if .env exists
if [ -f "$ENV_FILE" ]; then
    echo "WARNING: .env already exists at $ENV_FILE"
    read -p "Overwrite? [y/N]: " OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env"
        exit 0
    fi
    echo "Backing up to .env.bak"
    cp "$ENV_FILE" "$ENV_FILE.bak"
fi

# --- PostgreSQL (local Docker container — values must match docker-compose.yml) ---
PG_USER="future_user"
PG_PASS=$(openssl rand -hex 24)
PG_DB="future_uat"
PG_HOST="postgres"
PG_PORT="5432"

# --- Application secrets ---
SECRET_KEY=$(openssl rand -hex 32)
read -p "Secret key [auto-generate]: " INPUT_KEY
SECRET_KEY="${INPUT_KEY:-$SECRET_KEY}"

read -s -p "Admin password for bootstrap admin user: " ADMIN_PASS
echo ""
if [ -z "$ADMIN_PASS" ]; then
    echo "ERROR: Admin password cannot be empty."
    exit 1
fi

read -p "Admin email [admin@future.local]: " ADMIN_EMAIL
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@future.local}"

read -p "Environment [uat]: " ENV_NAME
ENV_NAME="${ENV_NAME:-uat}"

cat > "$ENV_FILE" << EOF
# FUTURE Platform - UAT Environment
# Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# PostgreSQL runs as a local Docker container (postgres service in docker-compose.yml)

# --- Database (must match docker-compose.yml) ---
POSTGRES_HOST=$PG_HOST
POSTGRES_PORT=$PG_PORT
POSTGRES_DB=$PG_DB
POSTGRES_USER=$PG_USER
POSTGRES_PASSWORD=$PG_PASS

# --- Connection string (Docker networking: 'postgres' = container hostname) ---
DATABASE_URL=postgresql://$PG_USER:$PG_PASS@$PG_HOST:$PG_PORT/$PG_DB

# --- JWT / Security ---
SECRET_KEY=$SECRET_KEY
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# --- Application ---
ENVIRONMENT=$ENV_NAME
API_V1_PREFIX=/api/v1
BACKEND_PORT=8000

# --- CORS ---
CORS_ORIGINS=["http://localhost:8080","http://127.0.0.1:8080"]

# --- Feature flags ---
ENABLE_DEMO_MODE=false
ENABLE_PREDICTIVE=true
ENABLE_INGESTION=true

# --- Bootstrap admin (created on first startup if no users exist) ---
ENABLE_BOOTSTRAP_ADMIN=true
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_EMAIL=$ADMIN_EMAIL
BOOTSTRAP_ADMIN_PASSWORD=$ADMIN_PASS
EOF

echo ""
echo "=== .env created at: $ENV_FILE ==="
echo ""
echo "Next: bash scripts/02-start-uat.sh"

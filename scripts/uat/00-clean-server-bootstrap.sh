#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# 00-clean-server-bootstrap.sh
# System-level preparation: stops containers, cleans Docker, installs packages.
# Does NOT remove /opt/future-uat (the zip extraction provides fresh files).
# Idempotent: safe to run multiple times.
# Run with: sudo bash scripts/00-clean-server-bootstrap.sh
# ---------------------------------------------------------------

INSTALL_DIR="/opt/future-uat"

echo "=== FUTURE UAT - System Bootstrap ==="

# Stop any existing containers (ignore errors if not running)
echo "[1/4] Stopping existing containers..."
cd /  # escape the target dir before any cleanup
if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    (cd "$INSTALL_DIR" && docker compose down --remove-orphans) 2>/dev/null || true
fi

# Clean Docker images only (NEVER prune volumes — destroys PostgreSQL data)
echo "[2/4] Cleaning Docker images..."
docker image prune -f 2>/dev/null || true

# System updates
echo "[3/4] System updates..."
apt-get update -qq
apt-get upgrade -y -qq

# Install base utilities
echo "[4/4] Installing base utilities..."
apt-get install -y -qq \
    curl \
    wget \
    unzip \
    jq \
    git \
    net-tools

echo ""
echo "=== System bootstrap complete ==="
echo "Next: sudo bash scripts/00-install-docker-ubuntu.sh"

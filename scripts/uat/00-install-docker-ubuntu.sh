#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# 00-install-docker-ubuntu.sh
# Installs Docker Engine + Docker Compose on Ubuntu.
# Idempotent: checks if already installed, asks before reinstalling.
# Run with: sudo bash scripts/00-install-docker-ubuntu.sh
# ---------------------------------------------------------------

echo "=== Docker Engine Installation ==="

# Check if Docker is already installed
if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version 2>/dev/null || echo "unknown")
    echo "Docker already installed: $DOCKER_VER"
    if docker compose version &>/dev/null; then
        echo "Docker Compose: $(docker compose version --short 2>/dev/null)"
    fi
    read -p "Reinstall/upgrade Docker? [y/N]: " REINSTALL
    if [[ ! "$REINSTALL" =~ ^[Yy]$ ]]; then
        echo "Skipping Docker install."
        exit 0
    fi
fi

# Remove old versions
apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Prerequisites
apt-get update -qq
apt-get install -y -qq \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Docker GPG key (idempotent - overwrite if exists)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Docker repository (idempotent - overwrite if exists)
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
apt-get update -qq
apt-get install -y -qq \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

# Verify
echo ""
echo "Docker version: $(docker --version)"
echo "Docker Compose version: $(docker compose version)"

# Add current user to docker group (if not root)
if [ -n "${SUDO_USER:-}" ]; then
    usermod -aG docker "$SUDO_USER"
    echo "Added $SUDO_USER to docker group (run 'newgrp docker' or log out/in)"
fi

echo ""
echo "=== Docker installed ==="

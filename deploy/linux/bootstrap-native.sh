#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need sudo; need curl
[[ -f /etc/os-release ]] || die "Unsupported Linux: /etc/os-release is absent"
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
  die "Native installation is verified only for Ubuntu 24.04; use Docker Compose on this host"
need apt-get
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib postgresql-16-pgvector python3.12 python3.12-venv nginx curl
printf 'System packages installed idempotently. Continue with configure-native.sh.\n'

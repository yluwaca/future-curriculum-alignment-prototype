#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need python3
required=(
  "$DEPLOY_ROOT/.env.example"
  "$DEPLOY_ROOT/docker-compose.yml"
  "$DEPLOY_ROOT/backend/Dockerfile"
  "$DEPLOY_ROOT/backend/alembic.ini"
  "$DEPLOY_ROOT/backend/requirements.txt"
  "$DEPLOY_ROOT/backend/requirements.lock"
  "$DEPLOY_ROOT/frontend/index.html"
  "$DEPLOY_ROOT/deploy/linux/configure-docker.sh"
  "$DEPLOY_ROOT/deploy/linux/nginx.examiner.conf"
)
for path in "${required[@]}"; do [[ -f "$path" ]] || die "Missing package file: $path"; done
if find "$DEPLOY_ROOT" -type f \( -name '.env' -o -name '*.pem' -o -name '*.key' \) -print -quit | grep -q .; then
  die "Potential secret file found in deployment package"
fi
if find "$DEPLOY_ROOT" -type d \( -name venv -o -name .venv -o -name __pycache__ \) -print -quit | grep -q .; then
  die "Generated environment/cache directory found in deployment package"
fi
python3 "$DEPLOY_ROOT/deploy/validate_python_sources.py"
python3 "$DEPLOY_ROOT/deploy/locks/audit_lock.py"
printf 'Static package boundary and Python syntax checks passed without generating cache files.\n'

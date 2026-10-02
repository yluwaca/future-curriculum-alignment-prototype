#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
load_env; validate_native_env; need systemctl
POSTGRES_DB="$(env_value POSTGRES_DB)"; POSTGRES_USER="$(env_value POSTGRES_USER)"; POSTGRES_PASSWORD="$(env_value POSTGRES_PASSWORD)"
SECRET_KEY="$(env_value SECRET_KEY)"; export SECRET_KEY
export DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
sudo systemctl start postgresql
sudo systemctl restart nginx
mkdir -p "$DEPLOY_ROOT/run"
if [[ -f "$DEPLOY_ROOT/run/backend.pid" ]] && kill -0 "$(cat "$DEPLOY_ROOT/run/backend.pid")" 2>/dev/null; then
  printf 'Backend already running.\n'; exit 0
fi
(cd "$DEPLOY_ROOT/backend" && nohup "$DEPLOY_ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$DEPLOY_ROOT/run/backend.log" 2>&1 & echo $! >"$DEPLOY_ROOT/run/backend.pid")
printf 'Native application started at http://127.0.0.1:8080. Add reviewed TLS before remote exposure.\n'

#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
load_env; validate_native_env
cd "$DEPLOY_ROOT/backend"
if [[ ! -x "$DEPLOY_ROOT/.venv/bin/python" ]]; then
  echo "Native virtual environment is absent; run bootstrap-native.sh first." >&2
  exit 1
fi
read -r -p "Local examiner admin username [admin]: " admin_user
admin_user="${admin_user:-admin}"
read -r -p "Local examiner admin email [admin@future.local]: " admin_email
admin_email="${admin_email:-admin@future.local}"
read -r -s -p "Local examiner admin password: " admin_password
printf '\n'
if [[ ${#admin_password} -lt 12 ]]; then echo "Password must contain at least 12 characters." >&2; exit 1; fi
export ENABLE_BOOTSTRAP_ADMIN=true BOOTSTRAP_ADMIN_USERNAME="$admin_user" BOOTSTRAP_ADMIN_EMAIL="$admin_email" BOOTSTRAP_ADMIN_PASSWORD="$admin_password"
POSTGRES_DB="$(env_value POSTGRES_DB)"; POSTGRES_USER="$(env_value POSTGRES_USER)"; POSTGRES_PASSWORD="$(env_value POSTGRES_PASSWORD)"
export SECRET_KEY="$(env_value SECRET_KEY)"
export DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
"$DEPLOY_ROOT/.venv/bin/python" -c "from app.core.bootstrap import ensure_admin_user; from app.db.session import SessionLocal; db=SessionLocal(); ensure_admin_user(db); db.close(); print('Local examiner admin created or repaired')"
unset BOOTSTRAP_ADMIN_PASSWORD

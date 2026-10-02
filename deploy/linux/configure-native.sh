#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
load_env; validate_native_env; need sudo; need python3.12; need psql
POSTGRES_DB="$(env_value POSTGRES_DB)"; POSTGRES_USER="$(env_value POSTGRES_USER)"; POSTGRES_PASSWORD="$(env_value POSTGRES_PASSWORD)"
sudo systemctl enable --now postgresql
sudo -u postgres psql -v ON_ERROR_STOP=1 --set=db_name="$POSTGRES_DB" --set=db_user="$POSTGRES_USER" --set=db_password="$POSTGRES_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db_user') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name') \gexec
SQL
sudo -u postgres psql -v ON_ERROR_STOP=1 --dbname="$POSTGRES_DB" -c 'CREATE EXTENSION IF NOT EXISTS vector;'
python3.12 -m venv "$DEPLOY_ROOT/.venv"
"$DEPLOY_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$DEPLOY_ROOT/.venv/bin/pip" install --requirement "$DEPLOY_ROOT/backend/requirements.lock"
"$DEPLOY_ROOT/.venv/bin/pip" check
export DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
(cd "$DEPLOY_ROOT/backend" && "$DEPLOY_ROOT/.venv/bin/alembic" upgrade head)
mkdir -p "$DEPLOY_ROOT/run"
escaped_root="${DEPLOY_ROOT//\//\\/}"
sed "s/__DEPLOY_ROOT__/${escaped_root}/g" "$DEPLOY_ROOT/deploy/linux/nginx.native.conf.template" > "$DEPLOY_ROOT/run-nginx.conf"
sudo install -m 0644 "$DEPLOY_ROOT/run-nginx.conf" /etc/nginx/sites-available/future-prototype
sudo ln -sfn /etc/nginx/sites-available/future-prototype /etc/nginx/sites-enabled/future-prototype
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
printf 'Native database, vector extension, environment and migrations configured.\n'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

read -r -p "Local examiner admin username [admin]: " admin_user
admin_user="${admin_user:-admin}"
read -r -p "Local examiner admin email [admin@future.local]: " admin_email
admin_email="${admin_email:-admin@future.local}"
read -r -s -p "Local examiner admin password: " admin_password
printf '\n'
if [[ ${#admin_password} -lt 12 ]]; then
  echo "Password must contain at least 12 characters." >&2
  exit 1
fi

docker compose run --rm --no-deps \
  -e ENABLE_BOOTSTRAP_ADMIN=true \
  -e BOOTSTRAP_ADMIN_USERNAME="$admin_user" \
  -e BOOTSTRAP_ADMIN_EMAIL="$admin_email" \
  -e BOOTSTRAP_ADMIN_PASSWORD="$admin_password" \
  backend python -c "from app.core.bootstrap import ensure_admin_user; from app.db.session import SessionLocal; db=SessionLocal(); ensure_admin_user(db); db.close(); print('Local examiner admin created or repaired')"
unset admin_password

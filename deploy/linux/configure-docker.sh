#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need openssl

umask 077
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$DEPLOY_ROOT/.env.example" "$ENV_FILE"
fi

if grep -q '^POSTGRES_PASSWORD=CHANGE_ME' "$ENV_FILE"; then
  postgres_password="$(openssl rand -hex 32)"
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${postgres_password}/" "$ENV_FILE"
  unset postgres_password
fi
if grep -q '^SECRET_KEY=CHANGE_ME' "$ENV_FILE"; then
  secret_key="$(openssl rand -hex 48)"
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=${secret_key}/" "$ENV_FILE"
  unset secret_key
fi

chmod 600 "$ENV_FILE"
load_env
printf 'Docker examiner configuration is ready at %s; secrets were not displayed.\n' "$ENV_FILE"

#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$DEPLOY_ROOT/.env"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"; }
load_env() {
  [[ -f "$ENV_FILE" ]] || die "Missing $ENV_FILE. Copy .env.example to .env and replace CHANGE_ME values."
  if grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*CHANGE_ME' "$ENV_FILE"; then
    die "Replace all active CHANGE_ME configuration values in $ENV_FILE"
  fi
}
env_value() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  [[ -n "$value" ]] || die "Missing ${key} in $ENV_FILE"
  printf '%s' "$value"
}
validate_native_env() {
  local key value
  for key in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD SECRET_KEY; do
    value="$(env_value "$key")"
    [[ "$value" =~ ^[A-Za-z0-9_.~-]+$ ]] || die "${key} must contain only letters, digits, underscore, dot, tilde or hyphen in native mode"
  done
  [[ "$(env_value POSTGRES_PASSWORD)" != CHANGE_ME* ]] || die "Replace POSTGRES_PASSWORD"
  value="$(env_value SECRET_KEY)"
  [[ ${#value} -ge 32 ]] || die "SECRET_KEY must be at least 32 characters"
}
compose() { docker compose --project-directory "$DEPLOY_ROOT" --env-file "$ENV_FILE" "$@"; }

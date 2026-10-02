#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need docker; need curl; load_env
compose ps
http_port="$(sed -n 's/^HTTP_PORT=//p' "$ENV_FILE" | tail -n 1)"; http_port="${http_port:-8080}"
curl --fail --silent --show-error "http://127.0.0.1:${http_port}/health" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${http_port}/ready" >/dev/null
printf 'Healthy: http://127.0.0.1:%s\n' "$http_port"

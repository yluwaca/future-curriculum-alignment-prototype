#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need curl
curl --fail --silent --show-error http://127.0.0.1:8080/health >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8080/ready >/dev/null
printf 'Native backend healthy.\n'

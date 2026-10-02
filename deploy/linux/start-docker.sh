#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need docker; load_env
# Bootstrap owns image construction. Normal start must be offline-capable and
# must never change the verified image merely because a registry is reachable.
compose up -d --no-build --wait
"$DEPLOY_ROOT/deploy/linux/health-docker.sh"

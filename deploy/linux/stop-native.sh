#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
pid_file="$DEPLOY_ROOT/run/backend.pid"
if [[ ! -f "$pid_file" ]]; then printf 'Backend already stopped.\n'; exit 0; fi
pid="$(cat "$pid_file")"
if kill -0 "$pid" 2>/dev/null; then kill "$pid"; fi
rm -f "$pid_file"
printf 'Native backend stopped; PostgreSQL and all data were preserved.\n'


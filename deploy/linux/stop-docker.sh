#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
need docker; load_env
compose down
printf 'Stopped. Named database and application volumes were preserved.\n'


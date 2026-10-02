#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
die "Destructive reset is intentionally not automated. To remove named volumes, use an explicit reviewed Docker Compose command."


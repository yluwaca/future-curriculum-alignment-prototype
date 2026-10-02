#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
python3.12 -m piptools compile --generate-hashes --resolver=backtracking \
  --output-file "$root/backend/requirements.linux-py312.lock" \
  "$root/backend/requirements.txt"
printf 'Generated backend/requirements.linux-py312.lock; review and clean-room test before commit.\n'

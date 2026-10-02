#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
base_url="${PCLMAS_BASE_URL:-http://localhost:8080}"
exec python3 "$script_dir/run_smoke.py" --base-url "$base_url" "$@"

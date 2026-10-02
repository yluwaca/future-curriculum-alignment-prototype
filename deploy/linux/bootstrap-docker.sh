#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
if [[ "${EUID}" -eq 0 ]]; then
  die "Do not deploy as root. Repair ownership if needed, then run as the examiner account (for example: su - future)."
fi
if find "$DEPLOY_ROOT" -xdev \( -type f -o -type d \) -perm /002 -print -quit | grep -q .; then
  die "Deployment package is world-writable. As root run: chown -R $USER:$USER '$DEPLOY_ROOT'; find '$DEPLOY_ROOT' -type d -exec chmod 755 {} +; find '$DEPLOY_ROOT' -type f -exec chmod 644 {} +; find '$DEPLOY_ROOT/deploy' -type f -name '*.sh' -exec chmod 755 {} +"
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  bash "$(dirname "$0")/install-docker-ubuntu.sh"
fi
docker info >/dev/null 2>&1 || die "Docker is installed but unavailable to this account. Start Docker and sign out/in after docker-group membership changes."
docker_root="$(docker info --format '{{.DockerRootDir}}')"
[[ -d "$docker_root" ]] || die "Docker storage directory is unavailable: $docker_root"
available_kb="$(df -Pk "$docker_root" | awk 'NR==2 {print $4}')"
minimum_kb=$((30 * 1024 * 1024))
if [[ ! "$available_kb" =~ ^[0-9]+$ ]] || (( available_kb < minimum_kb )); then
  available_gb=$(( ${available_kb:-0} / 1024 / 1024 ))
  die "Docker image build requires at least 30 GiB free on the Docker storage filesystem; ${available_gb} GiB is available at $docker_root. Extend the disk/filesystem before bootstrap."
fi
[[ -f "$DEPLOY_ROOT/backend/Dockerfile" ]] || die "Deploy/backend/Dockerfile is missing"
[[ -f "$DEPLOY_ROOT/frontend/index.html" ]] || die "Deploy/frontend/index.html is missing"
# Idempotent: creates a missing file, replaces only template placeholders, and
# preserves an already configured environment.
bash "$(dirname "$0")/configure-docker.sh"
load_env
compose config --quiet
compose build
printf 'Docker images built. Run deploy/linux/start-docker.sh.\n'

#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -ne 0 ]] || die "Run this as the examiner account, not root (for example: su - future). The script uses sudo only for host package installation."
command -v sudo >/dev/null 2>&1 || die "sudo is required to install Docker Engine."
[[ -r /etc/os-release ]] || die "Cannot identify this Linux distribution. Use a documented Ubuntu Docker target."

# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || \
  die "Automatic Docker installation is supported only on Ubuntu; detected ${PRETTY_NAME:-unknown}."
case "${VERSION_ID:-}" in
  22.04|24.04) ;;
  *) die "Automatic Docker installation is supported on Ubuntu 22.04 and 24.04; detected ${PRETTY_NAME:-unknown}." ;;
esac

for conflicting in docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc; do
  if dpkg-query -W -f='${Status}' "$conflicting" 2>/dev/null | grep -q 'install ok installed'; then
    die "Conflicting package '$conflicting' is installed. Review and remove it explicitly before using Docker's official repository."
  fi
done

sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

architecture="$(dpkg --print-architecture)"
codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
[[ -n "$codename" ]] || die "Ubuntu codename is unavailable in /etc/os-release."
printf '%s\n' \
  'Types: deb' \
  'URIs: https://download.docker.com/linux/ubuntu' \
  "Suites: ${codename}" \
  'Components: stable' \
  "Architectures: ${architecture}" \
  'Signed-By: /etc/apt/keyrings/docker.asc' | \
  sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

docker_version="$(sudo docker --version)"
compose_version="$(sudo docker compose version)"
printf 'Installed %s\n' "$docker_version"
printf 'Installed %s\n' "$compose_version"
printf 'Added %s to the docker group. Sign out of the Linux session and sign in again, then rerun bootstrap-docker.sh.\n' "$USER"
exit 2

#!/usr/bin/env bash
# Deploy and install script for Agent Studio web service
#
# This script is intended to be run once as root on a fresh Ubuntu 22.04 VM.
# It is idempotent – running it multiple times will not cause errors or
# duplicate installations.

set -euo pipefail

# Helper for logging
log() { printf '\n==> %s\n' "$*"; }

# Ensure we are running as root
if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (e.g., sudo ./deploy/install.sh)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"

########################
# 1. Install Docker
########################
if command -v docker >/dev/null 2>&1; then
  log "Docker already installed"
else
  log "Installing Docker (apt)"
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg lsb-release
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  log "Docker installation complete"
fi

# Verify Docker daemon is running
if ! systemctl is-active --quiet docker; then
  log "Starting Docker daemon"
  systemctl start docker
fi

########################
# 2. Install Docker Compose (via Docker plugin)
########################
# The Docker Compose CLI plugin is installed with the Docker package above.
# Verify that "docker compose" works.
if docker compose version >/dev/null 2>&1; then
  log "Docker Compose plugin available"
else
  log "Docker Compose plugin not found – attempting manual install"
  COMPOSE_VERSION="v2.27.0"
  curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
  log "Docker Compose installed"
fi

########################
# 3. Pull latest images and bring up services
########################
if [ -f "$COMPOSE_FILE" ]; then
  log "Pulling latest Docker images"
  docker compose -f "$COMPOSE_FILE" pull
  log "Starting services"
  docker compose -f "$COMPOSE_FILE" up -d
else
  echo "Compose file not found at $COMPOSE_FILE" >&2
  exit 1
fi

########################
# 4. Verify application reachable
########################
HOST="${DEPLOY_HOST:-localhost}"
URL="https://$HOST"
log "Checking application health at $URL"
# Wait up to 30 seconds for the service to become healthy
for i in {1..30}; do
  if curl -k -s -o /dev/null -w "%{http_code}" "$URL" | grep -q '^2'; then
    log "Application responded with HTTP 200"
    break
  fi
  sleep 1
done

########################
# 5. Summary
########################
log "Deploy/install completed successfully"
exit 0


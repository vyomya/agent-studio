#!/usr/bin/env bash
# Install Agent Studio on a fresh Ubuntu 24.04 VM and enable it at boot.
set -euo pipefail

log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  fail 'Run as root (for example: sudo deploy/install.sh).'
fi

if [[ ! -r /etc/os-release ]]; then
  fail 'Cannot identify the operating system; Ubuntu 24.04 is required.'
fi
# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
  fail "Ubuntu 24.04 is required (detected ${PRETTY_NAME:-unknown})."
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deploy/docker-compose.yml"
[[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"
ENV_FILE="$REPO_ROOT/deploy/.env"

if ! command -v docker >/dev/null 2>&1; then
  log 'Installing Docker Engine and Compose plugin'
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg lsb-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if ! docker compose version >/dev/null 2>&1; then
  log 'Installing Docker Compose plugin'
  apt-get update -y
  apt-get install -y docker-compose-plugin
fi
docker compose version >/dev/null || fail 'Docker Compose plugin is unavailable.'

# Keep operator-supplied model settings intact; add a public sslip.io domain only
# when the deployment environment file does not already define one.
if [[ ! -f "$ENV_FILE" ]] || ! grep -qE '^[[:space:]]*DOMAIN=' "$ENV_FILE"; then
  PUBLIC_IP="$(curl -4 -fsS --max-time 10 https://api.ipify.org)" \
    || fail 'Could not determine the VM public IPv4 address for DOMAIN.'
  if [[ ! "$PUBLIC_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    fail 'Invalid public IPv4 address returned while setting DOMAIN.'
  fi
  DOMAIN="${PUBLIC_IP//./-}.sslip.io"
  if [[ -f "$ENV_FILE" ]]; then
    printf '\nDOMAIN=%s\n' "$DOMAIN" >> "$ENV_FILE"
  else
    (umask 077; printf 'DOMAIN=%s\n' "$DOMAIN" > "$ENV_FILE")
  fi
  chmod 0600 "$ENV_FILE"
fi

systemctl enable docker
if ! systemctl is-active --quiet docker; then
  systemctl start docker
fi

SYSTEMD_UNIT=/etc/systemd/system/agent-studio.service
DOCKER_BIN="$(command -v docker)"
UNIT_TMP="$(mktemp)"
ENV_TMP=''
trap 'rm -f "$UNIT_TMP" "$ENV_TMP"' EXIT
cat > "$UNIT_TMP" <<EOF
[Unit]
Description=Agent Studio
Requires=docker.service
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$REPO_ROOT
ExecStart=$DOCKER_BIN compose --env-file $ENV_FILE -f $COMPOSE_FILE up --build -d
ExecStop=$DOCKER_BIN compose --env-file $ENV_FILE -f $COMPOSE_FILE down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
SYSTEMD_CHANGED=0
if ! cmp -s "$UNIT_TMP" "$SYSTEMD_UNIT"; then
  install -m 0644 "$UNIT_TMP" "$SYSTEMD_UNIT"
  SYSTEMD_CHANGED=1
fi

AUTO_DEPLOY_ENV=/etc/default/agent-studio-auto-deploy
ENV_TMP="$(mktemp)"
printf 'AGENT_STUDIO_REPO="%s"\n' "$REPO_ROOT" > "$ENV_TMP"
if ! cmp -s "$ENV_TMP" "$AUTO_DEPLOY_ENV"; then
  install -m 0644 "$ENV_TMP" "$AUTO_DEPLOY_ENV"
  SYSTEMD_CHANGED=1
fi
for unit in agent-studio-auto-deploy.service agent-studio-auto-deploy.timer; do
  source="$REPO_ROOT/deploy/$unit"
  target="/etc/systemd/system/$unit"
  [[ -r "$source" ]] || fail "Auto-deploy unit not found: $source"
  if ! cmp -s "$source" "$target"; then
    install -m 0644 "$source" "$target"
    SYSTEMD_CHANGED=1
  fi
done
if [[ "$SYSTEMD_CHANGED" -eq 1 ]]; then
  systemctl daemon-reload
fi
systemctl enable agent-studio.service
systemctl enable --now agent-studio-auto-deploy.timer

log 'Compose configuration to be deployed:'
cat "$COMPOSE_FILE"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
systemctl restart agent-studio.service

HEALTH_URL="${DEPLOY_URL:-https://${DEPLOY_HOST:-localhost}/}"
log "Waiting for the application at $HEALTH_URL"
healthy=0
for _ in {1..30}; do
  if curl --insecure --fail --silent --output /dev/null --max-time 2 "$HEALTH_URL"; then
    healthy=1
    break
  fi
  sleep 1
done
if [[ "$healthy" -ne 1 ]]; then
  fail "Health check failed for $HEALTH_URL after 30 seconds."
fi

log 'Agent Studio deployment completed successfully.'

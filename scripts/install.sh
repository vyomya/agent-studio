#!/usr/bin/env bash
# Stands up the whole Agent Studio system on a fresh VM made by infra/<provider>/ Terraform.
#
#   git clone https://github.com/vyomya/agent-studio && cd agent-studio
#   sudo ./scripts/install.sh            # install everything, timers stay OFF
#   sudo ./scripts/install.sh --start    # same, then turn the agents' timers ON
#   sudo ./scripts/install.sh --update-agents   # only refresh agents/ rules, config and wake script
#
# Safe to run again. Steps marked VERIFY use runtime CLI flags confirmed from docs but not yet on this VM.
set -euo pipefail

MODE="${1:-}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT=/srv/agent-studio
# shellcheck source=/dev/null
source "$REPO_DIR/agents/agents.conf"
step() { printf '\n==> %s\n' "$*"; }
as_agents() { sudo -iu agents bash -lc "$*"; }
cfg() { local v="AGENT_${1//-/_}_$2"; printf '%s' "${!v:-}"; }

refresh_agents() {
  step "Installing agent rules, team config and wake-up script into $ROOT/agents"
  rm -rf "$ROOT/agents.new"; cp -r "$REPO_DIR/agents" "$ROOT/agents.new"
  rm -rf "$ROOT/agents"; mv "$ROOT/agents.new" "$ROOT/agents"
  chmod +x "$ROOT/agents/bin/wake.sh"
  chown -R agents:agents "$ROOT/agents"
}

if [ "$MODE" = "--update-agents" ]; then refresh_agents; echo "Done."; exit 0; fi

step "Checking base tools from cloud-init"
for t in git gh node npm docker jq python3 curl flock; do
  command -v "$t" >/dev/null || { echo "Missing $t. Did cloud-init finish? (ls ~/.cloud-init-done)" >&2; exit 1; }
done
node -e 'const [a,b]=process.versions.node.split(".").map(Number); if (a<24 || (a===24 && b<16)) { console.error("OpenClaw needs Node 24.16+ (found "+process.versions.node+")"); process.exit(1) }'

step "Creating the 'agents' user (no sudo, not in the docker group)"
id agents >/dev/null 2>&1 || useradd --create-home --shell /bin/bash agents
mkdir -p "$ROOT"/{work,logs,ledger,state,run}
chown -R agents:agents "$ROOT"

refresh_agents

step "Secrets"
if [ ! -f "$ROOT/.env" ]; then
  install -m 600 -o agents -g agents "$REPO_DIR/agents/env.example" "$ROOT/.env"
  echo "Created $ROOT/.env from the template. Fill it in (sudo nano $ROOT/.env), then run this script again."
  exit 0
fi
chmod 600 "$ROOT/.env"; chown agents:agents "$ROOT/.env"
grep -q '^GH_TOKEN=.\+' "$ROOT/.env" || { echo "GH_TOKEN is empty in $ROOT/.env" >&2; exit 1; }

step "Installing OpenClaw and Hermes Agent for the agents user"
# VERIFY: if an installer opens an interactive setup, finish or skip it, then run this script again.
as_agents 'command -v openclaw >/dev/null || curl -fsSL https://openclaw.ai/install.sh | bash'
as_agents 'command -v hermes   >/dev/null || curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash'
as_agents 'command -v openclaw && command -v hermes' >/dev/null || { echo "A runtime is not on the agents PATH yet." >&2; exit 1; }
printf 'PATH=%s\n' "$(as_agents 'echo $PATH')" > "$ROOT/path.env"

step "Cloning one workspace per agent, each with its own git identity"
for a in $AGENTS; do
  rt="$(cfg "$a" RUNTIME)"
  as_agents "set -a; . $ROOT/.env; set +a
    if ! git -C $ROOT/work/$a remote get-url origin >/dev/null 2>&1; then
      [ -e $ROOT/work/$a ] && mv $ROOT/work/$a $ROOT/work/$a.pre-clone-\$(date +%s)
      gh repo clone $REPO $ROOT/work/$a -- --quiet
    fi
    git -C $ROOT/work/$a config user.name  '$a ($rt)'
    git -C $ROOT/work/$a config user.email '$a@agents.agent-studio.local'"
done
as_agents "set -a; . $ROOT/.env; set +a; gh auth setup-git"

step "Registering agents in their runtimes"
for a in $AGENTS; do
  rt="$(cfg "$a" RUNTIME)"; model="$(cfg "$a" MODEL)"; fb="$(cfg "$a" FALLBACK)"
  case "$rt" in
    hermes)
      # VERIFY: one Hermes profile per agent; the model is also passed on every run by wake.sh.
      as_agents "hermes profile list 2>/dev/null | grep -qw '$a' || hermes profile create '$a' --description 'Agent Studio $a'"
      ;;
    openclaw)
      # VERIFY: registers the agent so it shows in the OpenClaw roster and dashboard; wake.sh runs it headless.
      as_agents "openclaw agents list 2>/dev/null | grep -qw '$a' || openclaw agents add '$a' --model '$model' ${fb:+--fallback-model '$fb'} --workspace '$ROOT/work/$a'"
      ;;
  esac
done
step "Trimming OpenClaw's default workspace files (fewer prompt tokens, nothing personal, never committed)"
for a in $AGENTS; do
  [ "$(cfg "$a" RUNTIME)" = openclaw ] || continue
  as_agents "W=$ROOT/work/$a
    rm -f \$W/BOOTSTRAP.md
    printf '# %s\\nHeadless Agent Studio agent. Your full instructions arrive in each message; follow them only.\\n' $a > \$W/AGENTS.md
    printf 'Concise, careful software engineer.\\n' > \$W/SOUL.md
    printf 'Name: %s\\n' $a > \$W/IDENTITY.md
    printf 'No human is chatting. Report through GitHub comments as the protocol says.\\n' > \$W/USER.md
    grep -qx AGENTS.md \$W/.git/info/exclude 2>/dev/null || printf 'AGENTS.md\\nSOUL.md\\nIDENTITY.md\\nUSER.md\\nBOOTSTRAP.md\\nMEMORY.md\\nmemory/\\n.openclaw/\\n' >> \$W/.git/info/exclude"
done
step "Shared test database for agents' tests (127.0.0.1:5433)"
docker ps -a --format '{{.Names}}' | grep -qx studio-testdb || \
  docker run -d --name studio-testdb --restart unless-stopped \
    -e POSTGRES_PASSWORD=test -e POSTGRES_DB=studio_test -p 127.0.0.1:5433:5432 postgres:16 >/dev/null

step "Wake-up timers (one per agent, staggered inside each 10 minutes)"
install -m 644 "$REPO_DIR/agents/systemd/agent-studio-wake@.service" /etc/systemd/system/
for a in $AGENTS; do
  off="$(cfg "$a" OFFSET)"
  cat > "/etc/systemd/system/agent-studio-wake-$a.timer" <<UNIT
[Unit]
Description=Wake the $a agent every 10 minutes (minute offset $off)

[Timer]
OnCalendar=*:0$off/10
Unit=agent-studio-wake@$a.service

[Install]
WantedBy=timers.target
UNIT
done
systemctl daemon-reload

step "Product deployment (written by the agents)"
if [ -x "$REPO_DIR/deploy/install.sh" ]; then
  "$REPO_DIR/deploy/install.sh"
else
  echo "deploy/install.sh does not exist yet; the builder-web tickets create it. Skipping."
fi

if [ "$MODE" = "--start" ]; then
  step "Starting the agents' timers"
  for a in $AGENTS; do systemctl enable --now "agent-studio-wake-$a.timer"; done
  systemctl list-timers 'agent-studio-wake-*' --no-pager
else
  cat <<MSG

Installed. Timers are OFF. Smoke-test one agent by hand first, for example:
  sudo -iu agents $ROOT/agents/bin/wake.sh lead --dry-run
  sudo -iu agents $ROOT/agents/bin/wake.sh lead
Then turn the team on:
  sudo $REPO_DIR/scripts/install.sh --start
MSG
fi

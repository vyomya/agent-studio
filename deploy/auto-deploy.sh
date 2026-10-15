#!/usr/bin/env bash
# Fast-forward the VM checkout and restart the stack only when main advances.
set -euo pipefail

REPO_ROOT="${AGENT_STUDIO_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOCK_FILE="${AGENT_STUDIO_LOCK_FILE:-/run/lock/agent-studio-auto-deploy.lock}"

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v flock >/dev/null 2>&1 || fail 'flock is required.'
exec 9>"$LOCK_FILE"
flock -n 9 || { log 'Another auto-deploy run is active; skipping.'; exit 0; }

[[ -d "$REPO_ROOT/.git" ]] || fail "Git checkout not found: $REPO_ROOT"
branch="$(git -C "$REPO_ROOT" branch --show-current)"
[[ "$branch" == main ]] || fail "Expected the main branch, found '$branch'."
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  fail 'Checkout has local changes; refusing to deploy over them.'
fi

git -C "$REPO_ROOT" fetch --quiet origin main
current="$(git -C "$REPO_ROOT" rev-parse HEAD)"
target="$(git -C "$REPO_ROOT" rev-parse refs/remotes/origin/main)"
if [[ "$current" == "$target" ]]; then
  log 'Checkout is already at origin/main; no restart needed.'
  exit 0
fi

git -C "$REPO_ROOT" merge-base --is-ancestor HEAD refs/remotes/origin/main \
  || fail 'origin/main is not a fast-forward; refusing to rewrite the checkout.'
git -C "$REPO_ROOT" merge --ff-only --quiet refs/remotes/origin/main
systemctl restart agent-studio.service
log "Deployed $(git -C "$REPO_ROOT" rev-parse --short HEAD) and restarted agent-studio.service."

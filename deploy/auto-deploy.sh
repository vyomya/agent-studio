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
REPO_OWNER="$(stat -c %U "$REPO_ROOT")"
git_repo() {
  if [[ "$REPO_OWNER" != root && "$(id -u)" -eq 0 ]]; then
    runuser -u "$REPO_OWNER" -- git -C "$REPO_ROOT" "$@"
  else
    git -C "$REPO_ROOT" "$@"
  fi
}

branch="$(git_repo branch --show-current)"
[[ "$branch" == main ]] || fail "Expected the main branch, found '$branch'."
if [[ -n "$(git_repo status --porcelain --untracked-files=no)" ]]; then
  fail 'Checkout has local changes; refusing to deploy over them.'
fi

git_repo fetch --quiet origin main
current="$(git_repo rev-parse HEAD)"
target="$(git_repo rev-parse refs/remotes/origin/main)"
if [[ "$current" == "$target" ]]; then
  log 'Checkout is already at origin/main; no restart needed.'
  exit 0
fi

git_repo merge-base --is-ancestor HEAD refs/remotes/origin/main \
  || fail 'origin/main is not a fast-forward; refusing to rewrite the checkout.'
git_repo merge --ff-only --quiet refs/remotes/origin/main
systemctl restart agent-studio.service
log "Deployed $(git_repo rev-parse --short HEAD) and restarted agent-studio.service."

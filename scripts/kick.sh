# Handoff trail (vyomya/agent-studio)

Every `[claim]` and `[handoff]` line posted by the agents, oldest first.

ubuntu@agent-studio:~/agent-studio$ ls humans/
apply-agents-update.sh  file-bug-timeout.sh   kick.sh
file-bug-37.sh          file-bug-versions.sh  set-product-env.sh
ubuntu@agent-studio:~/agent-studio$ cat humans/kick.sh 
#!/usr/bin/env bash
# Walk one ticket through the team now instead of waiting for the 10-minute timers.
# Each step is the normal wake-up (same rules, same logs); an agent with nothing to do just logs "skip".
#   sudo ./human/kick.sh                 # lead -> builder-core -> reviewer -> tester -> lead
#   sudo ./human/kick.sh builder-web     # same, with builder-web as the builder
set -uo pipefail
BUILDER="${1:-builder-core}"
for a in lead "$BUILDER" reviewer tester lead; do
  printf '\n==> %s (%s)\n' "$a" "$(date -u +%H:%M:%SZ)"
  systemctl start "agent-studio-wake@$a.service"      # waits until this run ends
  grep "\[$a\]" /srv/agent-studio/logs/wake.log | tail -3
done
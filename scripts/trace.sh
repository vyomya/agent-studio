#!/usr/bin/env bash
# Collects the delivery trail into docs/traces/ for DELIVERY.md:
#   handoffs.md    every [claim] and [handoff] line the agents posted, with links
#   gates.md       every time a review or test gate rejected or passed work (label events)
#   wake-log.txt   the last 200 lines of the wake-up log (only when run on the VM)
# Usage: ./scripts/trace.sh [owner/repo]
set -euo pipefail
REPO="${1:-vyomya/agent-studio}"
OUT="docs/traces"; mkdir -p "$OUT"

{
  echo "# Handoff trail ($REPO)"; echo
  echo "Every \`[claim]\` and \`[handoff]\` line posted by the agents, oldest first."; echo
  gh api --paginate "repos/$REPO/issues/comments?per_page=100&sort=created&direction=asc" \
    --jq '.[] | . as $c
          | ($c.body | split("\n") | map(select(test("^\\s*\\[(handoff|claim)\\]"))) ) as $lines
          | select($lines | length > 0)
          | "- \($c.created_at) · [\($c.user.login)](\($c.html_url))\n" + ($lines | map("  - `" + . + "`") | join("\n"))'
} > "$OUT/handoffs.md"

{
  echo "# Gate decisions ($REPO)"; echo
  echo "| When | Issue/PR | Gate | Label |"; echo "|---|---|---|---|"
  gh api --paginate "repos/$REPO/issues/events?per_page=100" \
    --jq '.[] | select(.event == "labeled")
          | select(.label.name | test("^(review|test):|^status:(changes-requested|test-failed|blocked|ready-to-merge)$"))
          | "| \(.created_at) | [#\(.issue.number)](\(.issue.html_url)) \(.issue.title | gsub("\\|"; "/")) | \(.label.name | split(":")[0]) | `\(.label.name)` |"' \
    | sort
} > "$OUT/gates.md"

if [ -r /srv/agent-studio/logs/wake.log ]; then
  tail -n 200 /srv/agent-studio/logs/wake.log > "$OUT/wake-log.txt"
fi

echo "Wrote: $(ls "$OUT" | tr '\n' ' ')"
echo "Handoff lines: $(grep -c '^  - `' "$OUT/handoffs.md" || true)   Gate events: $(grep -c '^| 20' "$OUT/gates.md" || true)"

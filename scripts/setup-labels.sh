#!/usr/bin/env bash
# Creates (or updates) the label state machine the agents use to hand work to each other.
# Usage: ./scripts/setup-labels.sh vyomya/agent-studio
set -euo pipefail
REPO="${1:?usage: setup-labels.sh owner/repo}"
lbl() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force; }

# Who owns the ticket right now
lbl "agent:pm"         "5319e7" "Orchestrator (Hermes) owns this"
lbl "agent:builder-1"  "1d76db" "Builder 1 (OpenClaw) owns this"
lbl "agent:builder-2"  "0e8a16" "Builder 2 (OpenClaw) owns this"
lbl "agent:reviewer"   "fbca04" "Reviewer (Hermes) owns this"
lbl "agent:tester"     "d93f0b" "Tester (OpenClaw) owns this"
lbl "agent:human"      "000000" "Needs Vyom"

# Where the ticket is in the flow (issues)
lbl "status:ready"              "c2e0c6" "Assigned by pm, waiting for pickup"
lbl "status:in-progress"        "0052cc" "Claimed by an agent"
lbl "status:needs-review"       "fbca04" "PR open, waiting for reviewer"
lbl "status:changes-requested"  "e99695" "Reviewer sent it back"
lbl "status:needs-test"         "f9d0c4" "Approved, waiting for tester"
lbl "status:test-failed"        "b60205" "Tester sent it back"
lbl "status:ready-to-merge"     "0e8a16" "Both gates passed, waiting for human merge"
lbl "status:blocked"            "000000" "Stuck; pm or human must act"

# Gate labels on PRs (the merge-gate check reads these)
lbl "review:approved"           "0e8a16" "Reviewer approved this PR"
lbl "review:changes-requested"  "d93f0b" "Reviewer rejected this PR with reasons"
lbl "test:passed"               "0e8a16" "Tester passed this PR"
lbl "test:failed"               "b60205" "Tester failed this PR"

# Ticket type and priority
lbl "type:feature"  "a2eeef" "New capability"
lbl "type:bug"      "d73a4a" "Something is broken"
lbl "type:chore"    "cfd3d7" "Setup, docs, refactor"
lbl "source:tester" "d93f0b" "Bug filed by the tester agent"
lbl "priority:p0"   "b60205" "Core path, do first"
lbl "priority:p1"   "fbca04" "Core but not blocking"
lbl "priority:p2"   "c5def5" "Stretch"

echo "Labels ready on $REPO"

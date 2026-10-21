# Agent Studio: operator guide

Every command needed to connect to the VM, check the models, watch the agents, run a change live, and read the
token numbers. Commands assume you are `ubuntu` on the VM in `~/agent-studio` unless a step says otherwise.

## 0. Where everything is

| What | Where |
|---|---|
| VM | `agent-studio`, zone `us-east1-b`, IP `35.237.72.93` |
| Live site | https://35-237-72-93.sslip.io/ (health: `/health`) |
| Live checkout (auto-deployed) | `/home/ubuntu/agent-studio`, owner `ubuntu`, `gh` logged in as `vyomya` |
| Live site settings and keys | `/home/ubuntu/agent-studio/deploy/.env` (mode 600) |
| Agent team root | `/srv/agent-studio` |
| Agent keys | `/srv/agent-studio/.env` (root only, never printed) |
| Installed agent config, roles, wake.sh | `/srv/agent-studio/agents/` (`agents.conf`, `PROTOCOL.md`, `<agent>/ROLE.md`, `bin/wake.sh`) |
| Each agent's own clone | `/srv/agent-studio/work/<agent>/` (owner `agents`, `gh` logged in as `vyom-agents`) |
| One-line log of every wake-up | `/srv/agent-studio/logs/wake.log` |
| Files of each model run | `/srv/agent-studio/logs/<agent>/<UTC time>.prompt.md`, `.out`, `.err`, `.usage.json` (tester also `.app.log`) |
| Token ledger (one JSON line per run) | `/srv/agent-studio/ledger/usage.jsonl` |
| Locks and lead state | `/srv/agent-studio/run/`, `/srv/agent-studio/state/` |

systemd units:

| Unit | Job |
|---|---|
| `agent-studio-wake-<agent>.timer` → `agent-studio-wake@<agent>.service` | wakes one agent every 10 minutes |
| `agent-studio-auto-deploy.timer` → `agent-studio-auto-deploy.service` | fast-forwards the live checkout to `origin/main` every 5 minutes, restarts the app if main moved |
| `agent-studio.service` | the live site (Docker Compose: `app`, `db` Postgres 16, `caddy` HTTPS) |

Wake-up minute within each 10 minutes: lead 0, architect 1, builder-core 3, builder-web 5, reviewer 7, tester 9.

Agents and models:

| Agent | Runtime | Model | Fallback |
|---|---|---|---|
| architect | Hermes | Ollama Cloud `gpt-oss:120b` | none |
| lead | Hermes | Ollama Cloud `gpt-oss:20b` | none |
| builder-core | OpenClaw | OpenAI `gpt-6-luna` | Gemini `gemini-3.5-flash-lite` |
| builder-web | OpenClaw | OpenAI `gpt-6-luna` | Gemini `gemini-3.1-flash-lite` |
| reviewer | Hermes | Ollama Cloud `nemotron-3-super` | none |
| tester | Hermes | Ollama Cloud `nemotron-3-super` (12 min limit) | none |
| live site | app code | Gemini `gemini-3.1-flash-lite` | OpenAI `gpt-6-luna` |

## 1. Connect

From the Mac:
```bash
gcloud compute instances list --filter="name=agent-studio" --format="value(name,zone,status)"   # RUNNING?
gcloud compute instances start agent-studio --zone us-east1-b                                   # only if TERMINATED
gcloud compute ssh agent-studio --zone us-east1-b
```
From the browser: console.cloud.google.com → Compute Engine → VM instances → **SSH** on the `agent-studio` row.

Either way you land as your own Google user with an empty home folder. Switch users:
```bash
sudo -iu ubuntu && cd ~/agent-studio        # live checkout, gh as vyomya (use this for tickets and merges)
sudo -iu agents                             # the agents' user (no sudo); only to look around as they do
```
Open a second terminal for a live view of the team:
```bash
tail -f /srv/agent-studio/logs/wake.log
```

## 2. Pre-call check (run 15 minutes before)

```bash
curl -s -o /dev/null -w 'site /health: %{http_code}\n' https://35-237-72-93.sslip.io/health
sudo systemctl is-active docker agent-studio.service agent-studio-auto-deploy.timer
systemctl list-timers --all | grep agent-studio                 # 7 timers, each with a NEXT time
tail -12 /srv/agent-studio/logs/wake.log                        # recent "skip:" or "start:" lines from every agent
sudo bash scripts/check-models.sh                               # every model: OK or FAIL, plus OpenAI budget
df -h / | tail -1                                               # disk use below 85%
git -C ~/agent-studio status -sb && git -C ~/agent-studio log --oneline -3   # clean, on main
gh auth status                                                  # vyomya
gh issue list --state open && gh pr list
```
All green means: site 200, units `active`, 7 timers, every model `OK`, OpenAI spend below the cap, a clean checkout.

## 3. Model checks

```bash
sudo bash scripts/check-models.sh
```
It reads the models from `agents.conf` and `deploy/.env`, sends each one "Reply with the single word OK", and prints
`OK <seconds>` or `FAIL HTTP <code> <message>`. Then it prints the OpenAI spend against the cap. Keys are never printed.

What a failure means:

| Fails | Effect | Action |
|---|---|---|
| OpenAI `gpt-6-luna`, HTTP 429 `insufficient_quota` | builders lose their main model; the live site loses its fallback | add credit at https://platform.openai.com/usage. Builders switch to Gemini on their own |
| OpenAI spend at the cap | `wake.sh` sends builders to their Gemini fallback (log line `budget: ... using ...`) | raise `OPENAI_BUDGET_USD` in `/srv/agent-studio/agents/agents.conf` (e.g. `3.00`) |
| Gemini, HTTP 503 or 429 | builder fallback is down; the live site uses its OpenAI fallback | usually passes in minutes; limits at https://aistudio.google.com/usage |
| Ollama Cloud, any model, HTTP 429 / 402 / 401 | **lead, reviewer, tester and architect have no fallback: the pipeline stops after the builder** | check the monthly allowance at https://ollama.com/settings **before the call** |

Runtimes (as the agents' user):
```bash
sudo -iu agents bash -lc 'command -v hermes openclaw; hermes --version; openclaw --version'
```

Raise the budget (one line, takes effect on the next wake-up, no restart):
```bash
sudo sed -i 's/^OPENAI_BUDGET_USD=.*/OPENAI_BUDGET_USD=3.00/' /srv/agent-studio/agents/agents.conf
grep OPENAI_BUDGET_USD /srv/agent-studio/agents/agents.conf
```
Make the same change in `agents/agents.conf` in the repo afterwards, so the repo matches the VM.

## 4. Agent status

All agents:
```bash
systemctl list-timers --all | grep agent-studio-wake            # last and next wake-up of each
systemctl list-units 'agent-studio-wake@*' --all --no-legend    # "activating" = a model run is in progress now
grep -E '\] start' /srv/agent-studio/logs/wake.log | tail -10   # the last 10 real model runs
```

One agent (replace `reviewer`):
```bash
A=reviewer
grep "\[$A\]" /srv/agent-studio/logs/wake.log | tail -10        # its decisions: skip reasons, start, end, budget
systemctl status agent-studio-wake@$A.service --no-pager
sudo journalctl -u agent-studio-wake@$A.service -n 40 --no-pager
sudo ls -t /srv/agent-studio/logs/$A | head -8                  # newest run files first
```

The last run of one agent, in detail:
```bash
A=reviewer
L=$(sudo ls -t /srv/agent-studio/logs/$A/*.prompt.md | head -1); L=${L%.prompt.md}
sudo less $L.prompt.md          # exactly what the model received: protocol, role, and the facts code found
sudo tail -60 $L.out            # what the agent did
sudo tail -30 $L.err            # runtime errors, if any
sudo cat $L.usage.json          # tokens the runtime reported
```

What would an agent do right now (no model call, no tokens):
```bash
sudo -u agents /srv/agent-studio/agents/bin/wake.sh lead --dry-run
```

An agent's own clone:
```bash
sudo -u agents git -C /srv/agent-studio/work/builder-web status -sb
sudo -u agents git -C /srv/agent-studio/work/builder-web log --oneline -5
```

Skip reasons in `wake.log`:

| Line | Meaning |
|---|---|
| `skip: nothing waiting` | no ticket or PR has this agent's label |
| `skip: nothing for the lead to decide` | no dispatchable ticket, rejection, board problem, merge-ready PR, bug, or stuck ticket |
| `skip: same open decisions as the last lead run (retry after 60 min)` | the lead already saw exactly this board; clear with `sudo rm /srv/agent-studio/state/lead.fp` |
| `skip: previous run still active` | this agent is still running from the last wake-up |
| `skip: another OpenClaw agent busy` | the two builders share one OpenClaw lock; one waits |
| `budget: OpenAI spend ... using <fallback>` | the cap is reached; the builder runs on Gemini |

## 5. Run a change live (the demo)

**1. File the ticket as vyomya** (as `ubuntu` on the VM, or from the Mac). The lead only dispatches tickets with
`type:feature` (or `type:bug`), one `area:*`, `agent:lead`, and no `status:*` label.
```bash
cat > /tmp/ticket.md <<'EOF'
## Goal
Show a small footer on the gallery page: "Built by the Agent Studio agent team".

## Acceptance criteria
- [ ] The gallery page ends with a footer that contains the text "Built by the Agent Studio agent team".
- [ ] No route, form field, limit, or iframe sandbox changes.
- [ ] A test asserts the footer text renders on GET /; all existing tests pass.

## Area
web

## Out of scope
Anything else on the page.

## Depends on
none

## Assignment (kept up to date by lead)
- Owner:
- Attempt: 1
EOF
gh issue create --repo vyomya/agent-studio --title "[T14] Add a footer to the gallery page" \
  --body-file /tmp/ticket.md --label type:feature --label area:web --label agent:lead
```

**2. Run the team now instead of waiting for the timers:**
```bash
sudo bash scripts/kick.sh builder-web      # lead → builder-web → reviewer → tester → lead, one after the other
```
Or one step at a time, to talk through each handoff:
```bash
sudo systemctl start agent-studio-wake@lead.service          # dispatch: ticket → agent:builder-web, status:ready
sudo systemctl start agent-studio-wake@builder-web.service   # branch, code, tests, PR, handoff to reviewer
sudo systemctl start agent-studio-wake@reviewer.service      # review:approved or changes-requested
sudo systemctl start agent-studio-wake@tester.service        # pytest + 9 smoke checks in code, then the verdict
sudo systemctl start agent-studio-wake@lead.service          # hands the PR to the human: status:ready-to-merge
```
Each command returns when that run ends. Watch the second terminal and the issue page meanwhile.

**3. Follow it on GitHub:**
```bash
gh issue view <n> --comments | tail -40
gh pr list
gh pr view <pr> --comments | tail -40
gh pr checks <pr>                                         # the "gate" check must pass
```

**4. Merge** (human only): in the PR page on GitHub, as before. Then deploy now instead of waiting up to 5 minutes:
```bash
sudo systemctl start agent-studio-auto-deploy.service
sudo journalctl -u agent-studio-auto-deploy.service -n 5 --no-pager    # "Deployed <sha> and restarted ..."
git -C ~/agent-studio log --oneline -1
curl -s https://35-237-72-93.sslip.io/ | grep -i "agent team"
```

## 6. Board and trail

```bash
gh issue list --state open --json number,title,labels --jq '.[] | "#\(.number) \(.title) [\([.labels[].name]|join(", "))]"'
gh issue list --label agent:reviewer                      # what one agent owns
gh issue view 62 --comments                               # a full ticket trail (UI polish, merged as PR #63)
gh pr view 63 --comments                                  # its review and the tester's PASS comment
gh api repos/vyomya/agent-studio/issues/62/events \
  --jq '.[] | select(.event=="labeled" or .event=="unlabeled") | "\(.created_at) \(.actor.login) \(.event) \(.label.name)"'
gh api repos/vyomya/agent-studio/rulesets/25076902 --jq '.rules[] | .type'   # main is protected: PR, approval, gate
```
Trail files in the repo: `docs/traces/handoffs.md` and `docs/traces/gates.md` (rebuild with `./scripts/trace.sh`).

## 7. Tokens and cost

```bash
L=/srv/agent-studio/ledger/usage.jsonl

# full report (by agent, by model, by phase, skipped wake-ups)
python3 scripts/token-report.py $L /srv/agent-studio/logs/wake.log | less

# last 10 runs
jq -r '[.ts, .agent, .model, .status, "\(.seconds)s", (.total_tokens // "none"), .ticket] | @tsv' $L | tail -10 | column -t

# one ticket (e.g. #64): every run and the total
jq -r 'select(.ticket == "#64") | [.ts, .agent, .phase, .status, (.total_tokens // "none")] | @tsv' $L | column -t
jq -s '[.[] | select(.ticket == "#64") | .total_tokens // 0] | add' $L

# tokens per ticket, largest first
jq -s -r 'group_by(.ticket)[] | [(.[0].ticket // "-"), length, ([.[].total_tokens // 0] | add)] | @tsv' $L | sort -t$'\t' -k3 -nr | head

# today's runs per agent
jq -r --arg d "$(date -u +%F)" 'select(.ts | startswith($d)) | .agent' $L | sort | uniq -c

# OpenAI spend so far (same formula as the budget guard)
jq -s '[.[] | select(.provider == "openai")
        | ((.prompt_tokens // 0) * 0.10 + (.cache_read_tokens // 0) * 0.01 + (.completion_tokens // 0) * 0.50) / 1000000] | add' $L

# wake-ups that cost nothing vs model runs
grep -c '] skip' /srv/agent-studio/logs/wake.log; grep -c '] start' /srv/agent-studio/logs/wake.log
```

## 8. Live site

```bash
curl -s https://35-237-72-93.sslip.io/health
sudo systemctl status agent-studio.service --no-pager
cd ~/agent-studio
sudo docker compose -f deploy/docker-compose.yml ps                         # app, db, caddy: Up (db healthy)
sudo docker compose -f deploy/docker-compose.yml logs --tail 40 app         # model calls, fallback, validator errors
sudo docker compose -f deploy/docker-compose.yml exec db \
  psql -U agent_studio -d agent_studio -c 'select count(*) from pages;'
sudo sed -E 's/^((PRIMARY|FALLBACK)_API_KEY|POSTGRES_PASSWORD)=.*/\1=***/' deploy/.env   # settings, keys hidden
```
A generation from the command line uses a real model call and counts against the limits (5 per hour, 20 per day,
40 per day for the whole site):
```bash
curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' -X POST \
  --data-urlencode 'spec=A one-page landing page for a neighbourhood bakery' https://35-237-72-93.sslip.io/generate
```

## 9. When something goes wrong

| Problem | Command |
|---|---|
| Stop one agent's current run (its timer keeps going) | `sudo systemctl stop agent-studio-wake@tester.service` |
| Pause the whole team | `for a in architect lead builder-core builder-web reviewer tester; do sudo systemctl stop agent-studio-wake-$a.timer; done` |
| Resume the whole team (name each timer, never a wildcard) | `for a in architect lead builder-core builder-web reviewer tester; do sudo systemctl start agent-studio-wake-$a.timer; done` |
| Lead ignores a new ticket | check its labels: `type:feature` or `type:bug`, one `area:*`, `agent:lead`, no `status:*` |
| Lead says "same open decisions" | `sudo rm /srv/agent-studio/state/lead.fp`, then start the lead |
| Board labels contradict each other | the lead's next run prints exact fix commands under BOARD PROBLEMS: `sudo -u agents /srv/agent-studio/agents/bin/wake.sh lead --dry-run` |
| Tester ends runs without a verdict | after 3 such runs `wake.sh` comments on the ticket; read the last `.out` and `.app.log` (section 4) |
| Site down after a deploy | `sudo journalctl -u agent-studio.service -n 50 --no-pager` and the app logs (section 8); roll back with `git -C ~/agent-studio log --oneline -5`, then a revert PR |
| Auto-deploy refuses | `sudo journalctl -u agent-studio-auto-deploy.service -n 20 --no-pager`; it refuses local changes or a non-fast-forward |
| VM rebooted | everything is enabled at boot; repeat section 2 |
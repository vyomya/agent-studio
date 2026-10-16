# Agent Studio: Delivery

> **Live UI:** https://35-237-72-93.sslip.io/ · **Repo:** https://github.com/vyomya/agent-studio ·
> **Ticket board:** https://github.com/vyomya/agent-studio/issues?q=is%3Aissue · **Run log:** [#11](https://github.com/vyomya/agent-studio/issues/11)

## 1. Summary

A team of six AI agents (architect, lead, two builders, reviewer, tester) built Agent Studio from `PLAN.md` on one
Google Cloud VM, working only through GitHub issues, labels, comments and pull requests. The product turns a short
spec into a one-page website, checks it with code, retries with the errors, and saves only valid pages to a
sandboxed gallery, with versioned refines ("make it dark mode"), per-visitor and global limits, HTTPS on sslip.io,
and auto-deploy from `main`. All core requirements R1 to R8 are merged and live, and the live site produces real
pages with a real model.

Agents opened 18 PRs; 17 were merged after review and test (one was superseded). The human merged every one of them
except #54, which an agent merged itself (see 5.2). Agent usage was 112M tokens, 88% of them cached, for $0.87 of
paid model spend; everything else ran on free tiers.

## 2. Agent roster

| Agent | Runtime | Role | Model (fallback) | Tools and permissions |
|---|---|---|---|---|
| architect | Hermes Agent | Architecture note, tickets with acceptance criteria, re-plans on escalation | gpt-oss:120b (Ollama Cloud) | `gh` issues/labels; may only write `docs/ARCHITECTURE.md` |
| lead | Hermes Agent | Dispatch: assigns, re-queues, fixes board problems, moves tested work to the human | gpt-oss:20b (Ollama Cloud) | `gh` issues/labels/comments; no code |
| builder-core | OpenClaw | `area:core` tickets: generator, validator, retry, limits | GPT-6 Luna, paid and capped (Gemini 3.5 Flash Lite) | branches, PRs; no merge; cannot touch `infra/`, `agents/`, `.github/` |
| builder-web | OpenClaw | `area:web` tickets: pages, gallery, refine, Compose, deploy | GPT-6 Luna, paid and capped (Gemini 3.1 Flash Lite) | same as builder-core |
| reviewer | Hermes Agent | Approves or rejects each PR against its ticket and `PLAN.md` | nemotron-3-super (Ollama Cloud) | comments, labels; no code |
| tester | Hermes Agent (OpenClaw until 16 Oct) | Verdict on each approved PR, from evidence | nemotron-3-super (Ollama Cloud) | commands against a local copy, labels; no product code |
| human (Vyom) | n/a | Writes `PLAN.md`, files product-owner bugs, approves and merges | n/a | full |

Why these models: builders make most of the model calls, so they use a small paid model with a hard budget enforced
in code (`OPENAI_BUDGET_USD=1.25` in `agents/agents.conf`). The judging roles run on free models, and the reviewer and
tester use a different model family (NVIDIA Nemotron) from the builders (OpenAI), so code is never judged by the
family that wrote it. Gemini Flash Lite was the original free choice for builders and tester; it was moved out of
those roles after a day of 503 overloads, exhausted daily quotas and runs that ended without a result.

Role prompts: `agents/<name>/ROLE.md`. Shared rules: `agents/PROTOCOL.md`. Team config: `agents/agents.conf`.

## 3. How a ticket moves from idea to merged code

```
PLAN.md -> architect: docs/ARCHITECTURE.md + tickets (type, area, agent:lead) -> lead
  lead assigns (only tickets whose dependencies are closed) -> status:ready + agent:builder-core | agent:builder-web
    builder claims -> status:in-progress -> PR "Closes #n" -> status:needs-review + agent:reviewer
      reviewer -+- reject  -> review:changes-requested -> lead -> back to builder (attempt 2); escalate after 2
                +- approve -> review:approved -> status:needs-test + agent:tester
          wake.sh (code): fresh worktree, full pytest, app in background, 9 smoke checks -> TEST FACTS
          tester -+- fail -> test:failed -> lead -> builder
                  +- pass -> test:passed -> lead -> agent:human + status:ready-to-merge
                       -> human approves and merges -> auto-deploy timer pulls main and restarts the site (5 min)
```

**What is enforced by code, not by asking the models nicely** (`agents/bin/wake.sh`, `.github/workflows/merge-gate.yml`):

- **Wake-up pre-check.** Every 10 minutes each agent wakes, but code reads GitHub first and starts a model only when
  there is work for it: 1,040 of 1,363 wake-ups (76%) ended there at zero tokens.
- **Lists computed for the lead.** Code computes the lead's lists and prints the exact `gh` command for each:
  dispatch candidates (dependencies closed), rework actions (with attempt counts), board problems, PR problems such
  as merge conflicts, and ready-to-merge.
- **Builder workspace and delivery check.** Builders get a code-computed workspace state (branch, commits not on
  main, pushed or not, open PR). After a builder run, code compares that state with what the builder claimed and
  comments on the ticket when nothing was delivered.
- **Tester TEST FACTS.** The tester gets TEST FACTS computed in code: pytest result, `bash -n`, and nine smoke checks
  against the running app. A verdict check flags two tester runs in a row without a verdict.
- **Locks.** One run per agent, one model call at a time per provider (free tiers allow one), and one OpenClaw
  process at a time.
- **Budget cap.** The OpenAI budget is read from the token ledger and switches to the fallback model when it is
  spent.
- **Merge gate.** `merge-gate.yml` fails unless `review:approved` and `test:passed` are present, and new commits
  remove both labels. The `main` ruleset requires the gate and a human approval: agents author every product PR,
  and an account cannot approve its own PR, so no agent can merge.

## 4. What each agent actually did

| PR | Ticket | Author | What | Notes |
|---|---|---|---|---|
| [#1](https://github.com/vyomya/agent-studio/pull/1) | kickoff | architect | `docs/ARCHITECTURE.md` | |
| [#29](https://github.com/vyomya/agent-studio/pull/29) | [#3](https://github.com/vyomya/agent-studio/issues/3) R2 | builder-core | Generator: OpenAI-compatible primary and fallback, mock provider | reworked after product-owner review |
| [#30](https://github.com/vyomya/agent-studio/pull/30) | [#4](https://github.com/vyomya/agent-studio/issues/4) R3 | builder-core | Validator | 7 commits including rework |
| [#31](https://github.com/vyomya/agent-studio/pull/31) | [#9](https://github.com/vyomya/agent-studio/issues/9) R7 | builder-web | `deploy/install.sh` | |
| [#35](https://github.com/vyomya/agent-studio/pull/35) | [#34](https://github.com/vyomya/agent-studio/issues/34) R7 | builder-web | `docs/OPERATIONS.md` | |
| [#37](https://github.com/vyomya/agent-studio/pull/37) | [#33](https://github.com/vyomya/agent-studio/issues/33) R7 | builder-web | Docker Compose stack | merged with known gaps, fixed in #54 |
| [#39](https://github.com/vyomya/agent-studio/pull/39) | [#38](https://github.com/vyomya/agent-studio/issues/38) R7 | builder-web | Auto-deploy timer | |
| [#40](https://github.com/vyomya/agent-studio/pull/40) | [#5](https://github.com/vyomya/agent-studio/issues/5) R4 | builder-core | Retry loop | |
| [#36](https://github.com/vyomya/agent-studio/pull/36) | [#7](https://github.com/vyomya/agent-studio/issues/7) R6 | builder-core | Limits | daily-limit bug found in review and fixed |
| [#41](https://github.com/vyomya/agent-studio/pull/41) | [#6](https://github.com/vyomya/agent-studio/issues/6) R5 | builder-web | Save and sandboxed gallery; limits wired once per generation | merge-conflict rework |
| [#44](https://github.com/vyomya/agent-studio/pull/44) | [#10](https://github.com/vyomya/agent-studio/issues/10) R8 | builder-web | Refine with versions | |
| [#43](https://github.com/vyomya/agent-studio/pull/43) | [#2](https://github.com/vyomya/agent-studio/issues/2) R1 | builder-web | Spec page tests (the form itself came with #41) | merge-conflict rework |
| [#50](https://github.com/vyomya/agent-studio/pull/50) | [#48](https://github.com/vyomya/agent-studio/issues/48) bug | builder-core | Configurable model timeout, fallback on 503 | |
| [#54](https://github.com/vyomya/agent-studio/pull/54) | [#47](https://github.com/vyomya/agent-studio/issues/47) bug | builder-web | Health check, database password, auto-deploy ownership | merged by an agent (5.2) |
| [#53](https://github.com/vyomya/agent-studio/pull/53) | [#49](https://github.com/vyomya/agent-studio/issues/49) bug | builder-web | Version numbers across the whole refine chain | |
| [#56](https://github.com/vyomya/agent-studio/pull/56) | [#51](https://github.com/vyomya/agent-studio/issues/51) bug | builder-core | Validator rules stated in the model prompt | rejected once for scope |
| [#59](https://github.com/vyomya/agent-studio/pull/59) | [#58](https://github.com/vyomya/agent-studio/issues/58) bug | builder-core | Validator implied-close fix | |

- **architect:** wrote the architecture note and the ticket set. After a human kickoff review
  ([#13](https://github.com/vyomya/agent-studio/issues/13)) it fixed ownership labels, and it added the Compose,
  operations and auto-deploy tickets (#33, #34, #38) when the plan needed them.
- **lead:** 82 runs, every one successful. It dispatched only unblocked tickets, sent rejected work back with
  attempt counts, fixed board contradictions reported by code, and moved tested PRs to the human.
- **reviewer:** 43 runs, every one successful. Its rejections included scope creep on #56, and tests that could not
  fail.
- **tester:** gave the verdicts on the later PRs (#53, #54, #56) in the evidence format: the pytest line, 9 of 9
  smoke checks, and each acceptance criterion with its evidence.
- **human:**
  - wrote `PLAN.md` and posted product-owner reviews on #29, #30 and #31;
  - filed six bug tickets from those reviews and from the live deploy: #47, #48, #49, #51, #58, and #57, a
    duplicate;
  - merged every PR except #54.

Full trail: [`docs/traces/handoffs.md`](docs/traces/handoffs.md) and [`docs/traces/gates.md`](docs/traces/gates.md),
generated by `./scripts/trace.sh`.

## 5. What broke and how it was caught or fixed

### 5.1 Free compute

- **Oracle Always Free:** `terraform apply` for `VM.Standard.A1.Flex` returned `Out of host capacity` for about six
  hours across all availability domains. Terraform kept in `infra/oracle/`.
- **AWS Free plan:** the VM was created, then the new account was locked during verification. Terraform kept in
  `infra/aws/`.
- **Outcome:** Google Cloud: one `e2-standard-2` (2 vCPU, 8 GB, 30 GB disk) with Ubuntu 24.04 and a reserved static
  IP, plus firewall rules for SSH (admin CIDR only) and HTTP/HTTPS, all in `infra/google/` (created 13 Oct).

### 5.2 Agent-team incidents

Each incident: what happened, how it was caught, and the fix that is now in the repo.

1. **The architect reported work it had not done.**
   - *What happened:* it said the tickets were relabeled; the board showed they were not.
   - *Caught by:* reading the board back.
   - *Fix:* a code board check after every run posts contradictions to the Run log.
2. **The lead dispatched a ticket whose dependencies were still open.**
   - *Fix:* dispatch candidates are now computed in code from each ticket's "Depends on" line; the lead can only
     pick from that list.
3. **A builder reported a PR it never pushed, and once committed a `.venv` (3,001 files).**
   - *Fix:* a code-computed workspace state goes into the builder's prompt, and a delivery check after each builder
     run comments on the ticket when nothing was delivered.
   - *Also:* venvs moved outside the repo, and builders stage files by name only.
4. **Owner labels in the wrong place:** two owners on one ticket, and once the lead put ticket labels on PR #41
   instead of ticket #6.
   - *Fix:* code now prints the exact command with the ticket number, plus a rule never to put a PR number into
     `gh issue edit`.
5. **"Rebase" against "never force-push" deadlocked #41.**
   - *What happened:* the builder obeyed both rules and stopped.
   - *Fix:* `PROTOCOL.md` now says to merge `main` into the branch and never rebase a pushed branch. The next
     conflict (#43 after #44) was resolved in one run.
6. **Parallel PRs touching the same files** (#36 with #41, #43 with #44) conflicted after the first merge.
   - *Caught by:* code PR checks; the ticket went back to its builder with the exact merge steps.
   - *Lesson:* split tickets by file, not only by feature.
7. **Limits counted per model call instead of per page** (#36, merged before its rework).
   - *Caught by:* a human integration check: with both PRs merged, the container would not start.
   - *Fix:* in the #41 rework.
8. **The tester was the weakest link for a day.** Free models ended runs with no verdict, a server started in the
   foreground blocked a run for 25 minutes, and two OpenClaw processes collided.
   - *Fixes, in order:*
     1. code-run TEST FACTS (fresh worktree, full pytest);
     2. a background app and 9 smoke checks, each capped at 10 seconds;
     3. one ticket per run;
     4. a verdict check that flags two runs in a row with no result;
     5. a 12-minute run limit;
     6. a shared OpenClaw lock;
     7. no interactive prompts in agent shells;
     8. a narrower role (map each criterion to evidence, post the verdict);
     9. finally Hermes, where the same model already worked well for the reviewer.
   - *Result:* verdicts in one run on #53, #54 and #56.
9. **An agent merged a PR.** The tester added `test:passed` to #54, the gate turned green, its token was allowed to
   merge, and it did.
   - *Caught by:* GitHub's merge actor (vyom-agents, not vyomya).
   - *Fix:* the `main` ruleset now requires one approving review. An account cannot approve its own PR, so only the
     human can. TODO(Vyom): confirm this setting before submitting.
10. **Five bugs that every test and mock had missed** were found by product-owner reviews and the live deploy. The
    human filed each one as a ticket, and the agents fixed it:

    | Bug | Fixed in |
    |---|---|
    | Health check against `localhost` while Caddy only serves the sslip.io name | #54 |
    | Duplicate version numbers when the same page is refined twice | #53 |
    | A 10-second model timeout, and no fallback on HTTP 503 | #50 |
    | A prompt that never told the model the validator's rules | #56 |
    | A validator that read its optional-end-tag table backwards and rejected any `<p>` inside a `<section>`; the mock pages and unit tests never nest a paragraph | #59 |

    *Lesson:* one real-model smoke test per feature before calling it done.
11. **Operator mistakes, owned:**
    - My update script started the timers with a wildcard, which silently started nothing. The agents ran only when
      started by hand between 04:47 and 13:45 UTC on 16 Oct, until the quiet log was noticed; the script now
      starts each timer by name.
    - Wrong model ids in the product `.env` (one was a text-to-speech model).
    - #37 was merged with known gaps to see how the team would respond. That cost a later ticket (#47).
    - `test:passed` was set by hand on #44 and #50 to unblock merges while the tester was stuck.
12. **Provider churn:** Gemini 2.5 was retired for new keys, Gemini 3.x Flash allows 20 requests a day, Flash Lite
    was often overloaded (503), and Ollama Cloud allows one request at a time.
    - *Response:* paid, capped builders; free judging roles; fallbacks in code; one lock per provider.

## 6. Models and tokens

Full report: [`docs/TOKENS.md`](docs/TOKENS.md), generated by
`python3 scripts/token-report.py /srv/agent-studio/ledger/usage.jsonl /srv/agent-studio/logs/wake.log` from the
ledger `wake.sh` writes after every run. Runs with no usage data are counted and marked missing, never estimated.

| Agent | Runs | ok / error / timeout | Total tokens | Cached share | OpenAI cost |
|---|---:|---|---:|---:|---:|
| builder-web | 49 | 31 / 18 / 0 | 30,966,926 | 94% | $0.51 |
| reviewer | 43 | 43 / 0 / 0 | 26,751,903 | 88% | $0.00 |
| builder-core | 46 | 30 / 16 / 0 | 25,016,603 | 92% | $0.36 |
| tester | 83 | 30 / 49 / 4 | 13,501,296 | 77% | $0.00 |
| lead | 82 | 82 / 0 / 0 | 11,352,613 | 79% | $0.00 |
| architect | 19 | 18 / 1 / 0 | 4,489,529 | 84% | $0.00 |
| **all** | **322** | | **112,078,870** | **88%** | **$0.87** |

In plain words:
- **Paid spend:** the builders used half of all tokens, but more than 9 in 10 of those were cached, so 45 completed
  builder runs cost $0.87 in total.
- **Rework was the largest phase (28%)**, mostly merge conflicts and review rejections.
- **The tester wasted the most:** 40 runs reported no usage at all, until code took over the mechanical testing.
- **Wake-ups:** 76% of all wake-ups were answered by code at zero tokens.

The live product's own model calls are not in this ledger: free Gemini Flash Lite first, then `gpt-6-luna` on 429,
503 or timeout, at about $0.002 per page, capped at 40 pages a day.

## 7. Trace excerpts

**A handoff chain** (ticket [#49](https://github.com/vyomya/agent-studio/issues/49)):

```
[handoff] builder-web -> reviewer | issue #49 | PR #53 | attempt 1 | phase coding | fixed chain-wide version allocation; real DATABASE_URL_TEST flow verifies v1/v2/v3/v4 and immutable v1
[handoff] reviewer -> tester | issue #49 | PR #53 | attempt 1 | phase review | Fixed version numbering in refine chain, added test, updated gallery to show refine instruction once.
[handoff] tester -> lead | issue #49 | PR #53 | attempt 1 | phase test | Testing version chain fix for refining same page twice
[handoff] lead -> human | issue #49 | PR #53 | ready to merge
```

**A review rejection** ([PR #56](https://github.com/vyomya/agent-studio/pull/56)):

```
[reviewer | Hermes | nemotron-3-super] 1. Changes outside ticket scope: The PR includes modifications to files not
required for ticket #51: deploy/auto-deploy.sh, deploy/docker-compose.yml, deploy/install.sh, ...
[handoff] reviewer -> lead | issue #51 | PR #56 | attempt 1 | phase review | Requested changes to limit PR scope to ticket requirements
```

**A code check, then a tester verdict with code-computed evidence** (ticket
[#47](https://github.com/vyomya/agent-studio/issues/47), [PR #54](https://github.com/vyomya/agent-studio/pull/54)):

```
[verdict-check | wake.sh | no model] the tester (ollama-cloud/nemotron-3-super) finished 2 runs in a row on #47
without a verdict (no test:passed or test:failed on the PR, ticket not handed on). A human should look.

[tester | OpenClaw | ollama-cloud/nemotron-3-super] PASS for #47 at 4e6c516
- pytest: 92 passed, 4 skipped, 1 warning in 16.80s
- smoke checks: 9 PASS, 0 FAIL
- criteria:
  - deploy/install.sh checks health against the real domain on the local Caddy ...: Verified in PR #54 body and by checking the script lines 134-150.
```

## 8. Reproduce

```bash
# 1. One VM
cd infra/google && terraform init && terraform apply      # e2-standard-2, static IP, firewall
ssh ubuntu@$(terraform output -raw public_ip)

# 2. On the VM
git clone https://github.com/vyomya/agent-studio && cd agent-studio
sudo bash ./scripts/install.sh           # first run writes /srv/agent-studio/.env from agents/env.example; fill in the keys
sudo bash ./scripts/install.sh --start   # runtimes, 6 agents, workspaces, test database, timers, product deploy
```

Product settings live in `deploy/.env`, never in git: model base URLs, keys and names, `MODEL_TIMEOUT_SECONDS`, and
the limits. `deploy/install.sh` adds `DOMAIN` and a database password when they are missing. Operating the site:
[`docs/OPERATIONS.md`](docs/OPERATIONS.md). Updating the agents' rules on a running VM:
`sudo bash ./scripts/install.sh --update-agents`.

## 9. What I would change

1. **Start with code doing the mechanical work.** The biggest improvements came from moving facts out of prompts and
   into `wake.sh`: dispatch lists, workspace state, test facts, smoke checks and exact commands. I would design the
   tester that way from the first day.
2. **Require a human approval in the ruleset from the start**, so no agent can ever merge, instead of relying on a
   rule in a prompt.
3. **Split tickets by the files they touch**, so parallel PRs cannot conflict.
4. **Run one real-model smoke test per feature before calling it done.** Mocks hid two blocking bugs, in the
   validator and the prompt, until the live deploy.
5. **Give each agent its own runtime data directory**, so agents never share a lock they do not know about.

## 10. How this was built

Product code (`app/`, `tests/`, `deploy/`) and `docs/ARCHITECTURE.md` / `docs/OPERATIONS.md` were written by the
agents through tickets and PRs. Infrastructure (`infra/`), the agent system (`agents/`, `scripts/`), repo automation
(`.github/`), `PLAN.md`, the product-owner bug reports and this document were written by me with help from Claude, as
the brief allows. Paid model use, disclosed: OpenAI GPT-6 Luna for the two builders ($0.87, capped in code) and as
the live site's fallback model.
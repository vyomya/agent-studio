# Token and model report

Generated on the VM on 16 Oct 2026 with
`python3 scripts/token-report.py /srv/agent-studio/ledger/usage.jsonl /srv/agent-studio/logs/wake.log`.

Source: `/srv/agent-studio/ledger/usage.jsonl`: 322 agent runs from 2026-10-14T02:38:43Z to 2026-10-16T16:23:41Z.
Numbers are the runtimes' own usage reports, written by `agents/bin/wake.sh` after every run. 89 runs reported no
usage (killed, timed out, or refused before the model was called) and are counted as runs only; their tokens are
missing, not estimated.

- **Total tokens:** 112,078,870, of which **98,786,481 (88%) were cached input** (re-sent context the provider
  served from cache).
- **Paid spend (OpenAI, builders only):** $0.87 at $0.10 / $0.01 / $0.50 per 1M new input / cached input / output
  tokens. Every other agent model ran on a free tier.

## By agent

| Agent | Runs | ok / error / timeout | No usage reported | New input | Cached input | Output | Total tokens | Run time | OpenAI cost |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| builder-web | 49 | 31 / 18 / 0 | 26 | 53,143 | 28,959,794 | 445,698 | **30,966,926** | 157 min | $0.51 |
| reviewer | 43 | 43 / 0 / 0 | 0 | 2,876,833 | 23,591,568 | 264,347 | **26,751,903** | 161 min | $0.00 |
| builder-core | 46 | 30 / 16 / 0 | 22 | 86,594 | 23,098,717 | 262,566 | **25,016,603** | 140 min | $0.36 |
| tester | 83 | 30 / 49 / 4 | 40 | 2,981,701 | 10,393,040 | 126,555 | **13,501,296** | 342 min | $0.00 |
| lead | 82 | 82 / 0 / 0 | 0 | 2,164,960 | 8,988,130 | 136,234 | **11,352,613** | 57 min | $0.00 |
| architect | 19 | 18 / 1 / 0 | 1 | 308,742 | 3,755,232 | 45,984 | **4,489,529** | 10 min | $0.00 |

## By model

| Model | Runs | ok / error / timeout | No usage reported | New input | Cached input | Output | Total tokens | Run time | OpenAI cost |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | 45 | 45 / 0 / 0 | 0 | 7,142 | 51,566,647 | 700,241 | **55,351,047** | 204 min | $0.87 |
| nemotron-3-super | 51 | 51 / 0 / 0 | 8 | 2,876,833 | 23,591,568 | 264,347 | **26,751,903** | 240 min | $0.00 |
| gpt-oss:20b | 82 | 82 / 0 / 0 | 0 | 2,164,960 | 8,988,130 | 136,234 | **11,352,613** | 57 min | $0.00 |
| gemini-3.1-flash-lite | 38 | 12 / 26 / 0 | 0 | 2,546,918 | 8,315,724 | 100,183 | **10,962,825** | 126 min | $0.00 |
| gpt-oss:120b | 39 | 37 / 2 / 0 | 21 | 308,742 | 3,755,232 | 45,984 | **4,489,529** | 86 min | $0.00 |
| gemini-3.5-flash-lite | 7 | 7 / 0 / 0 | 0 | 567,378 | 2,569,180 | 34,395 | **3,170,953** | 17 min | $0.00 |
| google/gemini-3.1-flash-lite | 26 | 0 / 26 / 0 | 26 | 0 | 0 | 0 | **0** | 36 min | $0.00 |
| ollama-cloud/gpt-oss:120b | 4 | 0 / 4 / 0 | 4 | 0 | 0 | 0 | **0** | 22 min | $0.00 |
| openai/gpt-6-luna | 22 | 0 / 22 / 0 | 22 | 0 | 0 | 0 | **0** | 4 min | $0.00 |
| google/gemini-3.5-flash-lite | 3 | 0 / 3 / 0 | 3 | 0 | 0 | 0 | **0** | 0 min | $0.00 |
| ollama-cloud/nemotron-3-super | 5 | 0 / 1 / 4 | 5 | 0 | 0 | 0 | **0** | 74 min | $0.00 |

How to read the model rows: when a run reports usage, the ledger records the model name the runtime returned
(for example `gpt-6-luna`). When a run fails before the runtime reports anything, the ledger falls back to the
configured name with its provider prefix (for example `openai/gpt-6-luna`). So the prefixed rows are exactly the
runs that never reached the model: OpenClaw refusing a second process, Gemini overloads, and killed tester runs.

## By phase

| Phase | Tokens | Share |
|---|---:|---:|
| planning | 15,842,142 | 14% |
| coding | 25,112,565 | 22% |
| rework | 30,870,964 | 28% |
| review | 26,751,903 | 24% |
| test | 13,501,296 | 12% |

## Wake-ups that cost nothing

Every 10 minutes each agent wakes up, but code checks GitHub first and only starts a model when there is work for
it. Skipped wake-ups spend no tokens.

| Agent | Model runs started | Wake-ups skipped by code | Skipped share |
|---|---:|---:|---:|
| architect | 19 | 202 | 91% |
| builder-core | 46 | 182 | 80% |
| builder-web | 49 | 175 | 78% |
| lead | 82 | 157 | 66% |
| reviewer | 43 | 186 | 81% |
| tester | 84 | 138 | 62% |
| **all** | **323** | **1040** | **76%** |

Most common skip reasons: nothing waiting (882); nothing for the lead to decide (134); same open decisions as the
last lead run (21); board unchanged since last run (2); another OpenClaw agent busy (1).

## Where the tokens went, in plain words

1. **Caching made the paid part cheap.** The two builders used half of all tokens (56M), almost all of it re-sent
   context that OpenAI served from cache at a tenth of the input price. Their whole bill for 45 completed runs was
   $0.87, about two cents per run, against a $1.25 cap enforced by `wake.sh` from this ledger.
2. **Rework was the largest phase (28%).** Most of it came from merge conflicts between PRs that touched the same
   files (#36 and #41), a builder that rebased into a no-force-push rule, and review rejections. The fixes were
   process fixes: merge, never rebase, a pushed branch (`PROTOCOL.md`), and code that names the exact ticket and
   command for each conflict (`pr_problems` in `wake.sh`).
3. **The tester was the least efficient role.** 83 runs, only 30 finished cleanly, and 40 reported no usage. The
   causes were free models that stopped mid-run, a server started in the foreground, and two OpenClaw processes
   colliding. After `wake.sh` took over the mechanical part (fresh worktree, full pytest, a background app and
   nine smoke checks, all before the model starts) and the role shrank to "map each acceptance criterion to
   evidence and post the verdict", verdicts came in one run (PRs #53, #54, #56).
4. **The code pre-check is the main token saver.** 1,040 of 1,363 wake-ups (76%) ended in code without calling a
   model. The lead, which runs on every board change, is also skipped when the open decisions are the same as on
   its last run.
5. **The review gate held.** The reviewer (nemotron-3-super, a different model family from the builders) ran 43
   times without a single error or timeout and rejected work for real reasons, for example scope creep on #56.

Not in this ledger: the live product's own model calls. The site uses free Gemini Flash Lite first and falls back
to `gpt-6-luna` on 429, 503 or timeout, at roughly $0.002 per page, capped by the global limit of 40 pages a day.

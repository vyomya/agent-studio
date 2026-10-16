#!/usr/bin/env python3
"""Turn the agents' token ledger into the token report for DELIVERY.md.

Usage (on the VM):
  python3 scripts/token-report.py /srv/agent-studio/ledger/usage.jsonl /srv/agent-studio/logs/wake.log > docs/TOKENS.md

Both arguments are optional (those paths are the defaults). Every number comes from the runtimes' own usage
reports, written to the ledger by agents/bin/wake.sh after each run. Runs that reported no usage (killed or timed
out) are counted as runs and shown as missing; their tokens are never estimated.

OpenAI cost uses the prices in agents/agents.conf (USD per 1M tokens), overridable with OPENAI_PRICE_IN,
OPENAI_PRICE_CACHED and OPENAI_PRICE_OUT in the environment.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

LEDGER = sys.argv[1] if len(sys.argv) > 1 else "/srv/agent-studio/ledger/usage.jsonl"
WAKELOG = sys.argv[2] if len(sys.argv) > 2 else "/srv/agent-studio/logs/wake.log"
PRICE_IN = float(os.environ.get("OPENAI_PRICE_IN", "0.10"))
PRICE_CACHED = float(os.environ.get("OPENAI_PRICE_CACHED", "0.01"))
PRICE_OUT = float(os.environ.get("OPENAI_PRICE_OUT", "0.50"))
PHASE_OF = {"planning": "planning", "coding": "coding", "retry": "rework", "review": "review", "test": "test"}
PHASES = ["planning", "coding", "rework", "review", "test"]


def load(path):
    rows = []
    try:
        with open(path) as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"warning: skipped bad ledger line {n}", file=sys.stderr)
    except FileNotFoundError:
        sys.exit(f"Ledger not found: {path}")
    return rows


def n(v):
    return v if isinstance(v, (int, float)) else 0


def fmt(v):
    return f"{int(v):,}"


def openai_cost(r):
    if r.get("provider") != "openai":
        return 0.0
    return (n(r.get("prompt_tokens")) * PRICE_IN + n(r.get("cache_read_tokens")) * PRICE_CACHED
            + n(r.get("completion_tokens")) * PRICE_OUT) / 1_000_000


def table(rows, key, title):
    agg = defaultdict(lambda: {"runs": 0, "ok": 0, "error": 0, "timeout": 0, "missing": 0,
                               "new_in": 0, "cached": 0, "out": 0, "total": 0, "secs": 0, "cost": 0.0})
    for r in rows:
        a = agg[r.get(key) or "unknown"]
        a["runs"] += 1
        st = r.get("status") or "unknown"
        a[st if st in ("ok", "error", "timeout") else "error"] += 1
        a["secs"] += n(r.get("seconds"))
        a["cost"] += openai_cost(r)
        if r.get("total_tokens") is None:
            a["missing"] += 1
            continue
        a["new_in"] += n(r.get("prompt_tokens"))
        a["cached"] += n(r.get("cache_read_tokens"))
        a["out"] += n(r.get("completion_tokens"))
        a["total"] += n(r.get("total_tokens"))
    lines = [f"| {title} | Runs | ok / error / timeout | No usage reported | New input | Cached input | Output | "
             f"Total tokens | Run time | OpenAI cost |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in sorted(agg, key=lambda k: -agg[k]["total"]):
        a = agg[name]
        lines.append(f"| {name} | {a['runs']} | {a['ok']} / {a['error']} / {a['timeout']} | {a['missing']} | "
                     f"{fmt(a['new_in'])} | {fmt(a['cached'])} | {fmt(a['out'])} | **{fmt(a['total'])}** | "
                     f"{a['secs'] / 60:.0f} min | ${a['cost']:.2f} |")
    return "\n".join(lines)


def wake_stats(path):
    """Wake-ups per agent from wake.log: how many started a model run and how many were skipped by code."""
    starts, skips, reasons = Counter(), Counter(), Counter()
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r"\S+ \[([\w-]+)\] (start|skip): ?(.*)", line)
                if not m:
                    continue
                agent, kind, rest = m.groups()
                if kind == "start":
                    starts[agent] += 1
                else:
                    skips[agent] += 1
                    reasons[re.sub(r" for \d+s$", "", rest.strip())[:60]] += 1
    except FileNotFoundError:
        return None
    return starts, skips, reasons


def main():
    rows = load(LEDGER)
    if not rows:
        print("No ledger rows found.")
        return
    total = sum(n(r.get("total_tokens")) for r in rows)
    cached = sum(n(r.get("cache_read_tokens")) for r in rows)
    cost = sum(openai_cost(r) for r in rows)
    missing = sum(1 for r in rows if r.get("total_tokens") is None)
    by_phase = Counter()
    for r in rows:
        by_phase[PHASE_OF.get(r.get("phase"), "planning")] += n(r.get("total_tokens"))

    print("# Token and model report\n")
    print(f"Source: `{LEDGER}`: {len(rows)} agent runs from {rows[0].get('ts', '?')} to {rows[-1].get('ts', '?')}. "
          "Numbers are the runtimes' own usage reports, written by `agents/bin/wake.sh` after every run. "
          f"{missing} runs reported no usage (killed or timed out) and are counted as runs only; "
          "their tokens are missing, not estimated.\n")
    print(f"- **Total tokens:** {fmt(total)}, of which **{fmt(cached)} ({cached / total * 100 if total else 0:.0f}%) "
          "were cached input** (re-sent context the provider served from cache).")
    print(f"- **Paid spend (OpenAI, builders only):** ${cost:.2f} at ${PRICE_IN}/${PRICE_CACHED}/${PRICE_OUT} per 1M "
          "new input / cached input / output tokens. Every other model ran on a free tier.\n")
    print("## By agent\n")
    print(table(rows, "agent", "Agent") + "\n")
    print("## By model\n")
    print(table(rows, "model", "Model") + "\n")
    print("## By phase\n")
    print("| Phase | Tokens | Share |\n|---|---:|---:|")
    for p in PHASES:
        print(f"| {p} | {fmt(by_phase[p])} | {by_phase[p] / total * 100 if total else 0:.0f}% |")
    print()
    ws = wake_stats(WAKELOG)
    if ws:
        starts, skips, reasons = ws
        all_agents = sorted(set(starts) | set(skips))
        print("## Wake-ups that cost nothing\n")
        print("Every 10 minutes each agent wakes up, but code checks GitHub first and only starts a model when there "
              "is work for it. Skipped wake-ups spend no tokens.\n")
        print("| Agent | Model runs started | Wake-ups skipped by code | Skipped share |\n|---|---:|---:|---:|")
        for a in all_agents:
            t = starts[a] + skips[a]
            print(f"| {a} | {starts[a]} | {skips[a]} | {skips[a] / t * 100 if t else 0:.0f}% |")
        t_s, t_k = sum(starts.values()), sum(skips.values())
        print(f"| **all** | **{t_s}** | **{t_k}** | **{t_k / (t_s + t_k) * 100 if t_s + t_k else 0:.0f}%** |\n")
        print("Most common skip reasons: " + "; ".join(f"{k} ({v})" for k, v in reasons.most_common(5)) + "\n")


if __name__ == "__main__":
    main()
